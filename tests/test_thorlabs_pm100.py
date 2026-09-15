"""ThorlabsPM100 driver against a fake TLPMX DLL (no hardware, no real DLL)."""

import pytest

from labman_core.devices import PowerMeter
from labman_core.drivers.thorlabs_pm100 import ThorlabsPM100, ThorlabsPM100Error

VI_ERROR = -1074001152  # a typical negative VISA status


class FakeTLPMX:
    """Mimics the TLPMX_* C functions; out-parameters arrive as ctypes byref objects."""

    def __init__(self, meters=(("PM100USB", "1931430", True),)) -> None:
        self.meters = list(meters)  # (model, serial, available)
        self.init_status = 0
        self.opened: list[bytes] = []
        self.init_flags: tuple[int, int] | None = None
        self.closed = 0
        self.power_w = 13.54e-3
        self.wavelength_nm = 635.0
        self.wavelength_limits = (400.0, 1100.0)
        self.autorange = 1
        self.avg_time_s = 0.0003
        self.avg_limits = (0.0001, 10.0)
        self.fail_meas = False

    @staticmethod
    def _resource(serial: str) -> bytes:
        return f"USB0::0x1313::0x8072::{serial}::INSTR".encode()

    def TLPMX_findRsrc(self, session, count):  # noqa: N802
        count._obj.value = len(self.meters)
        return 0

    def TLPMX_getRsrcName(self, session, index, buffer):  # noqa: N802
        buffer.value = self._resource(self.meters[index.value][1])
        return 0

    def TLPMX_getRsrcInfo(self, session, index, model, serial, maker, available):  # noqa: N802
        m, s, a = self.meters[index.value]
        model.value, serial.value, maker.value = m.encode(), s.encode(), b"Thorlabs"
        available._obj.value = int(a)
        return 0

    def TLPMX_init(self, resource, id_query, reset, session):  # noqa: N802
        if self.init_status < 0:
            return self.init_status
        self.opened.append(resource)
        self.init_flags = (id_query.value, reset.value)
        session._obj.value = 42
        return 0

    def TLPMX_close(self, session):  # noqa: N802
        self.closed += 1
        return 0

    def TLPMX_errorMessage(self, session, status, buffer):  # noqa: N802
        buffer.value = b"Instrument not responding"
        return 0

    def TLPMX_measPower(self, session, value, channel):  # noqa: N802
        if self.fail_meas:
            return VI_ERROR
        value._obj.value = self.power_w
        return 0

    def TLPMX_setWavelength(self, session, value, channel):  # noqa: N802
        self.wavelength_nm = value.value
        return 0

    def TLPMX_getWavelength(self, session, attribute, value, channel):  # noqa: N802
        value._obj.value = {0: self.wavelength_nm, 1: self.wavelength_limits[0],
                            2: self.wavelength_limits[1]}[attribute.value]
        return 0

    def TLPMX_setPowerAutoRange(self, session, mode, channel):  # noqa: N802
        self.autorange = mode.value
        return 0

    def TLPMX_getPowerAutorange(self, session, mode, channel):  # noqa: N802
        mode._obj.value = self.autorange
        return 0

    def TLPMX_setAvgTime(self, session, value, channel):  # noqa: N802
        self.avg_time_s = value.value
        return 0

    def TLPMX_getAvgTime(self, session, attribute, value, channel):  # noqa: N802
        value._obj.value = {0: self.avg_time_s, 1: self.avg_limits[0],
                            2: self.avg_limits[1]}[attribute.value]
        return 0


def test_opens_meter_by_serial_without_reset_and_reads_power() -> None:
    lib = FakeTLPMX(meters=[("PM100D", "111", True), ("PM100USB", "1931430", True)])
    meter = ThorlabsPM100("1931430", _lib=lib)
    assert isinstance(meter, PowerMeter)
    assert lib.opened == [b"USB0::0x1313::0x8072::1931430::INSTR"]
    assert lib.init_flags == (1, 0)  # ID query on, device reset off
    assert meter.model == "PM100USB"


async def test_read_power_and_settings() -> None:
    lib = FakeTLPMX()
    meter = ThorlabsPM100(_lib=lib)  # no serial: first meter
    assert await meter.read_power_w() == pytest.approx(13.54e-3)

    await meter.set_wavelength_nm(1030.0)
    assert await meter.get_wavelength_nm() == pytest.approx(1030.0)
    with pytest.raises(ValueError, match="outside the sensor"):
        await meter.set_wavelength_nm(1550.0)

    await meter.set_auto_range(False)
    assert lib.autorange == 0
    assert not await meter.get_auto_range()

    await meter.set_average_time_s(0.1)
    assert await meter.get_average_time_s() == pytest.approx(0.1)
    with pytest.raises(ValueError):
        await meter.set_average_time_s(20.0)


def test_initial_wavelength_is_applied_on_connect() -> None:
    lib = FakeTLPMX()
    ThorlabsPM100(wavelength_nm=1064.0, _lib=lib)
    assert lib.wavelength_nm == pytest.approx(1064.0)


def test_missing_meter_lists_what_was_found() -> None:
    lib = FakeTLPMX(meters=[("PM100D", "111", True)])
    with pytest.raises(ThorlabsPM100Error, match="S/N 1931430.*not found.*PM100D S/N 111"):
        ThorlabsPM100("1931430", _lib=lib)
    assert lib.opened == []


def test_unavailable_flag_only_warns_and_opens() -> None:
    """Hardware: the available flag stayed 0 although the meter opened and measured fine."""
    lib = FakeTLPMX(meters=[("PM100USB", "1931430", False)])
    meter = ThorlabsPM100("1931430", _lib=lib)
    assert lib.opened == [b"USB0::0x1313::0x8072::1931430::INSTR"]
    assert meter.model == "PM100USB"


def test_unavailable_meter_that_fails_to_open_mentions_other_software() -> None:
    lib = FakeTLPMX(meters=[("PM100USB", "1931430", False)])
    lib.init_status = VI_ERROR
    with pytest.raises(ThorlabsPM100Error, match="in use; close Optical Power Monitor"):
        ThorlabsPM100("1931430", _lib=lib)


def test_init_failure_reports_vendor_message() -> None:
    lib = FakeTLPMX()
    lib.init_status = VI_ERROR
    with pytest.raises(ThorlabsPM100Error, match="Instrument not responding"):
        ThorlabsPM100(_lib=lib)


async def test_measurement_error_raises_and_shutdown_is_idempotent() -> None:
    lib = FakeTLPMX()
    meter = ThorlabsPM100(_lib=lib)
    lib.fail_meas = True
    with pytest.raises(ThorlabsPM100Error, match="TLPMX_measPower failed"):
        await meter.read_power_w()

    await meter.shutdown()
    await meter.shutdown()
    assert lib.closed == 1
    with pytest.raises(ThorlabsPM100Error, match="closed"):
        await meter.read_power_w()


async def test_controls_use_sensor_limits() -> None:
    meter = ThorlabsPM100(_lib=FakeTLPMX())
    controls = meter.controls()
    setables = {s.name: s for s in controls.setables}
    assert setables["wavelength"].bounds.low == 400.0
    assert setables["wavelength"].bounds.high == 1100.0
    assert setables["auto_range"].kind is bool
    assert await setables["average_time"].get() == pytest.approx(0.0003)
    (power,) = controls.readables
    assert await power.get() == pytest.approx(13.54e-3)
