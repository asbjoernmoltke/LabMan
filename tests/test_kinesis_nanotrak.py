"""KinesisNanoTrak driver against a fake Kinesis DLL (no hardware, no real DLL)."""

import math
from pathlib import Path

import pytest

from labman_core.devices import Aligner
from labman_core.drivers.kinesis_nanotrak import KinesisError, KinesisNanoTrak
from labman_core.lab_config import LabConfig
from labman_core.roles import DeviceRole

KNA_LAB = Path(__file__).parents[1] / "examples" / "lab.kna.yaml"


class FakeNanoTrakLib:
    """Mimics the NT_* C functions; out-parameters arrive as ctypes byref objects."""

    def __init__(self, range_flags: int = 0x11, open_code: int = 0) -> None:
        self.range_flags = range_flags
        self.open_code = open_code
        self.serial: bytes | None = None
        self.mode: int | None = None
        self.polling = False
        self.close_count = 0
        self.simulations = False
        self.home = (0, 0)
        self.position = (0, 0)
        self.reading = (1.5e-7, 1)
        # Optional queue of (absolute, range_state, relative, range_code), consumed per read.
        self.reading_queue: list[tuple[float, int, int, int]] = []
        self.reading_requests = 0
        self.identified = False

    def TLI_InitializeSimulations(self):  # noqa: N802
        self.simulations = True

    def TLI_BuildDeviceList(self):  # noqa: N802
        return 0

    def NT_Open(self, serial):  # noqa: N802
        self.serial = serial
        return self.open_code

    def NT_Close(self, serial):  # noqa: N802
        self.close_count += 1

    def NT_StartPolling(self, serial, ms):  # noqa: N802
        self.polling = True
        return True

    def NT_StopPolling(self, serial):  # noqa: N802
        self.polling = False

    def NT_SetMode(self, serial, mode):  # noqa: N802
        self.mode = mode
        return 0

    def NT_RequestIOsettings(self, serial):  # noqa: N802
        return 0

    def NT_GetIOsettings(self, serial, voltage_range, route):  # noqa: N802
        voltage_range._obj.value = self.range_flags
        route._obj.value = 0
        return 0

    def NT_SetCircleHomePosition(self, serial, position):  # noqa: N802
        self.home = (position._obj.horizontalComponent, position._obj.verticalComponent)
        return 0

    def NT_HomeCircle(self, serial):  # noqa: N802
        self.position = self.home
        return 0

    def NT_GetCirclePosition(self, serial, position):  # noqa: N802
        position._obj.horizontalComponent, position._obj.verticalComponent = self.position
        return 0

    def NT_RequestReading(self, serial):  # noqa: N802
        self.reading_requests += 1
        return 0

    def NT_GetReading(self, serial, reading):  # noqa: N802
        if self.reading_queue:
            absolute, state, relative, range_code = self.reading_queue.pop(0)
            reading._obj.relativeReading = relative
            reading._obj.selectedRange = range_code
        else:
            absolute, state = self.reading
        reading._obj.absoluteReading = absolute
        reading._obj.underOrOverRead = state
        return 0

    def NT_Identify(self, serial):  # noqa: N802
        self.identified = True


def _driver(
    lib: FakeNanoTrakLib | None = None, **kwargs
) -> tuple[KinesisNanoTrak, FakeNanoTrakLib]:
    lib = lib or FakeNanoTrakLib()
    options = {"max_voltage_v": 150.0, "startup_wait_s": 0.0, "read_delay_s": 0.0, **kwargs}
    return KinesisNanoTrak("57000001", _lib=lib, **options), lib


def test_connect_opens_polls_and_latches() -> None:
    driver, lib = _driver()
    assert isinstance(driver, Aligner)
    assert lib.serial == b"57000001"
    assert lib.polling
    assert lib.mode == 0x02
    assert not lib.simulations


def test_simulation_flag_initializes_kinesis_simulator() -> None:
    _driver_, lib = _driver(simulation=True)
    assert lib.simulations


def test_voltage_range_mismatch_refuses_and_closes() -> None:
    lib = FakeNanoTrakLib(range_flags=0x00)  # device on 75 V
    with pytest.raises(KinesisError, match="CH1 75 V / CH2 75 V but max_voltage_v is 150 V"):
        _driver(lib)
    assert lib.close_count == 1
    assert not lib.polling


def test_75v_configuration_accepted_when_declared() -> None:
    driver, _lib = _driver(FakeNanoTrakLib(range_flags=0x00), max_voltage_v=75)
    assert driver.max_voltage_v == 75.0


def test_mixed_channel_ranges_are_refused() -> None:
    with pytest.raises(KinesisError, match="CH1 150 V / CH2 75 V"):
        _driver(FakeNanoTrakLib(range_flags=0x01))


def test_open_error_code_raises() -> None:
    with pytest.raises(KinesisError, match="NT_Open .* error 2"):
        _driver(FakeNanoTrakLib(open_code=2))


def test_invalid_max_voltage_rejected() -> None:
    with pytest.raises(ValueError, match="75 or 150"):
        KinesisNanoTrak("1", max_voltage_v=100, _lib=FakeNanoTrakLib())


async def test_move_converts_volts_to_device_units_and_back() -> None:
    driver, lib = _driver()
    await driver.move_to_v(75.0, 150.0)
    assert lib.home == (32768, 65535)
    h, v = await driver.get_position_v()
    assert h == pytest.approx(75.0, abs=0.003)
    assert v == pytest.approx(150.0)


async def test_move_outside_range_never_reaches_the_device() -> None:
    driver, lib = _driver()
    with pytest.raises(ValueError, match="outside"):
        await driver.move_to_v(150.5, 10.0)
    assert lib.home == (0, 0)


async def test_read_signal_maps_range_flag() -> None:
    driver, lib = _driver()
    reading = await driver.read_signal()
    assert reading.signal_a == pytest.approx(1.5e-7)
    assert reading.in_range
    lib.reading = (5e-3, 3)  # over range
    assert not (await driver.read_signal()).in_range


async def test_garbage_absolute_reading_is_retried() -> None:
    """Seen on S/N 57535374: absolute 1.7e-38 with a normal relative value."""
    driver, lib = _driver()
    lib.reading_queue = [(1.717e-38, 1, 23100, 4), (4.183e-9, 1, 23100, 4)]
    reading = await driver.read_signal()
    assert reading.signal_a == pytest.approx(4.183e-9)
    assert reading.in_range
    assert lib.reading_requests == 2


async def test_persistently_implausible_reading_is_nan_and_out_of_range() -> None:
    driver, lib = _driver(read_retries=1)
    lib.reading_queue = [(1e-38, 1, 23100, 4), (float("inf"), 1, 23100, 4)]
    reading = await driver.read_signal()
    assert math.isnan(reading.signal_a)
    assert not reading.in_range
    assert lib.reading_requests == 2


async def test_plausibility_tolerates_constant_scale_mismatch_and_dark_readings() -> None:
    driver, lib = _driver()
    lib.reading_queue = [
        (4.183e-9, 1, 23100, 4),  # 0.36 x relative·full-scale, as measured on hardware
        (2e-13, 1, 10, 4),        # near-dark: relative < 1 %, nothing to cross-check
    ]
    assert (await driver.read_signal()).signal_a == pytest.approx(4.183e-9)
    assert (await driver.read_signal()).signal_a == pytest.approx(2e-13)
    assert lib.reading_requests == 2


async def test_latch_identify_and_idempotent_shutdown() -> None:
    driver, lib = _driver()
    lib.mode = 0x03  # e.g. someone enabled tracking on the front panel
    await driver.latch()
    assert lib.mode == 0x02
    await driver.identify()
    assert lib.identified

    await driver.shutdown()
    await driver.shutdown()
    assert lib.close_count == 1
    assert not lib.polling


async def test_controls_expose_voltages_and_signal() -> None:
    driver, _lib = _driver()
    setables = {s.name: s for s in driver.controls().setables}
    await setables["vertical_v"].set(30.0)
    await setables["horizontal_v"].set(60.0)
    h, v = await driver.get_position_v()
    assert h == pytest.approx(60.0, abs=0.003)
    assert v == pytest.approx(30.0, abs=0.003)


def test_example_lab_yaml_declares_an_aligner_with_a_resource_lock() -> None:
    config = LabConfig.from_path(KNA_LAB)
    (device,) = config.devices
    assert device.role == DeviceRole.ALIGNER
    assert device.driver == "labman_core.drivers.KinesisNanoTrak"
    assert device.resource is not None
    assert float(device.args["max_voltage_v"]) == 150.0
