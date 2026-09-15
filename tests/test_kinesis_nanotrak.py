"""KinesisNanoTrak driver against a fake Kinesis DLL (no hardware, no real DLL)."""

import logging
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
        self.stale_position: tuple[int, int] | None = None
        # (absolute, range_state, relative, range_code); 9828/32767 x 500 nA = 150 nA
        self.reading: tuple[float, int, int, int] = (5.4e-8, 1, 9828, 7)
        # Optional queue of readings in the same form, consumed per read.
        self.reading_queue: list[tuple[float, int, int, int]] = []
        self.reading_requests = 0
        self.identified = False
        self.route_flags = 0
        self.accept_io = True     # False: NT_SetIOsettings "succeeds" but has no effect
        self.persist_ok = True
        self.events: list[tuple] = []
        self.peak_volts = [0.0, 0.0]

    def volts(self) -> list[float]:
        """Real output voltages for the current position and range."""
        return [w / 65535 * (150.0 if self.range_flags & flag else 75.0)
                for w, flag in zip(self.position, (0x01, 0x10), strict=True)]

    def _track_peak(self) -> None:
        self.peak_volts = [max(p, v) for p, v in zip(self.peak_volts, self.volts(), strict=True)]

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
        self.poll_ms = ms
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
        route._obj.value = self.route_flags
        return 0

    def NT_SetIOsettings(self, serial, voltage_range, route):  # noqa: N802
        self.events.append(("io", voltage_range, route))
        if self.accept_io:
            self.range_flags = voltage_range
            self._track_peak()
        return 0

    def NT_PersistSettings(self, serial):  # noqa: N802
        self.events.append(("persist",))
        return self.persist_ok

    def NT_SetCircleHomePosition(self, serial, position):  # noqa: N802
        self.home = (position._obj.horizontalComponent, position._obj.verticalComponent)
        return 0

    def NT_HomeCircle(self, serial):  # noqa: N802
        self.position = self.home
        self.events.append(("move", self.position))
        self._track_peak()
        return 0

    def NT_GetCirclePosition(self, serial, position):  # noqa: N802
        # stale_position mimics the real DLL, whose report lags moves by a polling period
        reported = self.stale_position if self.stale_position is not None else self.position
        position._obj.horizontalComponent, position._obj.verticalComponent = reported
        return 0

    def NT_RequestReading(self, serial):  # noqa: N802
        self.reading_requests += 1
        return 0

    def NT_GetReading(self, serial, reading):  # noqa: N802
        source = self.reading_queue.pop(0) if self.reading_queue else self.reading
        absolute, state, relative, range_code = source
        reading._obj.relativeReading = relative
        reading._obj.selectedRange = range_code
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


def test_default_polling_is_slow_enough_for_the_kna() -> None:
    """Regression: 20 ms polling froze the KNA's status/readings on hardware."""
    _dev, lib = _driver()
    assert lib.poll_ms == 200


async def test_position_right_after_a_move_is_the_commanded_one() -> None:
    """Regression: at 200 ms polling the device still reported the previous position."""
    driver, lib = _driver()
    lib.position = (32768, 32768)
    lib.stale_position = (32768, 32768)
    assert await driver.get_position_v() == pytest.approx((75.0, 75.0), abs=0.003)

    await driver.move_to_v(105.0, 45.0)  # the device report stays stale

    assert await driver.get_position_v() == pytest.approx((105.0, 45.0), abs=0.003)
    assert lib.position == (driver._to_word(105.0), driver._to_word(45.0))


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


# ----- opt-in output range switching -----


def _lib_at(range_flags: int, words: tuple[int, int]) -> FakeNanoTrakLib:
    lib = FakeNanoTrakLib(range_flags=range_flags)
    lib.position = words
    lib.peak_volts = lib.volts()
    return lib


def _kinds(lib: FakeNanoTrakLib) -> list[str]:
    return [event[0] for event in lib.events]


def test_without_opt_in_the_range_is_never_changed() -> None:
    lib = _lib_at(0x00, (1000, 1000))
    with pytest.raises(KinesisError, match="set_voltage_range"):
        _driver(lib)
    assert not {"io", "persist", "move"} & set(_kinds(lib))


def test_matching_range_with_opt_in_changes_nothing() -> None:
    lib = _lib_at(0x11, (1000, 1000))
    _driver(lib, set_voltage_range=True)
    assert lib.events == []


def test_switch_75_to_150_lowers_position_first_and_keeps_voltage() -> None:
    lib = _lib_at(0x00, (60000, 40000))  # 68.67 V / 45.78 V on the 75 V range
    lib.route_flags = 0x100
    before = lib.volts()

    driver, _lib = _driver(lib, set_voltage_range=True)

    assert lib.range_flags == 0x11
    assert lib.position == (30000, 20000)
    assert _kinds(lib) == ["move", "io", "move", "persist"]
    assert lib.events[0] == ("move", (30000, 20000))      # lowered before the switch
    assert lib.events[1] == ("io", 0x11, 0x100)             # routing flags preserved
    assert lib.volts() == pytest.approx(before, abs=0.003)
    assert lib.peak_volts == pytest.approx(before, abs=0.003)  # never above the start
    assert driver.max_voltage_v == 150.0


def test_switch_150_to_75_switches_first_then_raises_position() -> None:
    lib = _lib_at(0x11, (30000, 20000))  # 68.67 V / 45.78 V on the 150 V range
    before = lib.volts()

    _driver(lib, max_voltage_v=75, set_voltage_range=True)

    assert lib.range_flags == 0x00
    assert lib.position == (60000, 40000)
    assert _kinds(lib) == ["move", "io", "move", "persist"]
    assert lib.events[0] == ("move", (30000, 20000))      # unchanged before the switch
    assert lib.volts() == pytest.approx(before, abs=0.003)
    assert lib.peak_volts == pytest.approx(before, abs=0.003)


def test_switch_mixed_channels_to_150() -> None:
    lib = _lib_at(0x01, (40000, 40000))  # CH1 on 150 V (91.6 V), CH2 on 75 V (45.8 V)
    before = lib.volts()
    _driver(lib, set_voltage_range=True)
    assert lib.range_flags == 0x11
    assert lib.position == (40000, 20000)
    assert lib.peak_volts == pytest.approx(before, abs=0.003)


def test_switch_refused_when_an_output_is_above_the_new_range() -> None:
    lib = _lib_at(0x11, (50000, 1000))  # H at 114 V
    with pytest.raises(KinesisError, match="above the 75 V range"):
        _driver(lib, max_voltage_v=75, set_voltage_range=True)
    assert "io" not in _kinds(lib)
    assert lib.close_count == 1


def test_range_switch_that_does_not_take_raises_and_closes() -> None:
    lib = _lib_at(0x00, (1000, 1000))
    lib.accept_io = False
    with pytest.raises(KinesisError, match="did not take"):
        _driver(lib, set_voltage_range=True)
    assert lib.close_count == 1


def test_persist_failure_is_logged_but_connection_succeeds(caplog) -> None:
    lib = _lib_at(0x00, (1000, 1000))
    lib.persist_ok = False
    with caplog.at_level(logging.WARNING, logger="labman.drivers.kinesis_nanotrak"):
        _driver(lib, set_voltage_range=True)
    assert lib.range_flags == 0x11
    assert "NT_PersistSettings failed" in caplog.text


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


async def test_signal_is_relative_reading_times_range_full_scale() -> None:
    driver, lib = _driver()
    reading = await driver.read_signal()
    assert reading.signal_a == pytest.approx(9828 / 32767 * 500e-9)
    assert reading.in_range
    lib.reading = (5e-3, 3, 32767, 15)  # over range
    reading = await driver.read_signal()
    assert reading.signal_a == pytest.approx(5e-3)
    assert not reading.in_range
    lib.reading = (0.0, 2, 0, 3)  # under range / dark
    reading = await driver.read_signal()
    assert reading.signal_a == 0.0
    assert not reading.in_range


async def test_garbage_absolute_reading_is_ignored() -> None:
    """Seen on S/N 57535374: absolute ~1e-38 with a normal relative value."""
    driver, lib = _driver()
    lib.reading_queue = [(1.717e-38, 1, 23100, 4)]
    reading = await driver.read_signal()
    assert reading.signal_a == pytest.approx(23100 / 32767 * 16.6e-9)
    assert reading.in_range
    assert lib.reading_requests == 1


async def test_unknown_range_code_is_retried_then_nan_out_of_range() -> None:
    driver, lib = _driver(read_retries=1)
    lib.reading_queue = [(4e-9, 1, 7000, 0), (4e-9, 1, 7000, 5)]
    reading = await driver.read_signal()
    assert reading.signal_a == pytest.approx(7000 / 32767 * 50e-9)
    assert lib.reading_requests == 2

    lib.reading_queue = [(4e-9, 1, 7000, 0), (4e-9, 1, 40000, 5)]  # unknown, then > full
    reading = await driver.read_signal()
    assert math.isnan(reading.signal_a)
    assert not reading.in_range
    assert lib.reading_requests == 4


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
    (device,) = [d for d in config.devices if d.role == DeviceRole.ALIGNER]
    assert device.role == DeviceRole.ALIGNER
    assert device.driver == "labman_core.drivers.KinesisNanoTrak"
    assert device.resource is not None
    assert float(device.args["max_voltage_v"]) == 150.0
    assert device.args["set_voltage_range"] is True
