"""Thorlabs PM100-series power meter (PM100USB, PM100D, ...) via the TLPMX C library.

The PM100USB installs with Thorlabs' own USB driver, so it is not a VISA USBTMC
resource that pyvisa can list; `TLPMX_64.dll` (Thorlabs Optical Power Monitor, in the
IVI Foundation VISA folder) is the supported route. Calls block, so they run in a
worker thread.

The meter is opened with an ID query but without a device reset, so the settings made
on the meter (wavelength, averaging, range) survive connecting.
"""

import asyncio
import ctypes
import logging
import threading
from pathlib import Path
from typing import Any

from labman_core.schema import DeviceControls, Range, Readable, Setable

logger = logging.getLogger("labman.drivers.thorlabs_pm100")

DEFAULT_DLL = Path(r"C:\Program Files\IVI Foundation\VISA\Win64\Bin\TLPMX_64.dll")

ATTR_SET = 0
ATTR_MIN = 1
ATTR_MAX = 2
AUTORANGE_ON = 1
AUTORANGE_OFF = 0
BUFFER_SIZE = 1024


class ThorlabsPM100Error(RuntimeError):
    """A TLPMX call failed or the requested meter was not found."""


class ThorlabsPM100:
    def __init__(
        self,
        serial_no: str | int | None = None,
        name: str = "pm100",
        wavelength_nm: float | None = None,
        channel: int = 1,
        dll_path: str | Path = DEFAULT_DLL,
        _lib: Any = None,
    ) -> None:
        self._name = name
        self._serial = None if serial_no is None else str(serial_no)
        self._channel = ctypes.c_uint16(int(channel))
        self._lock = threading.Lock()
        self._lib = _lib if _lib is not None else _load_library(Path(dll_path))
        self._session = ctypes.c_uint32(0)
        self._open = False
        self.resource_name = ""
        self.model = ""
        self._connect()
        if wavelength_nm is not None:
            self._set_wavelength_sync(float(wavelength_nm))

    # ----- PowerMeter protocol -----

    @property
    def name(self) -> str:
        return self._name

    @property
    def serial_no(self) -> str | None:
        return self._serial

    async def read_power_w(self) -> float:
        return await asyncio.to_thread(self._read_power_sync)

    async def set_wavelength_nm(self, wavelength_nm: float) -> None:
        await asyncio.to_thread(self._set_wavelength_sync, float(wavelength_nm))

    async def get_wavelength_nm(self) -> float:
        return await asyncio.to_thread(self._get_double, "TLPMX_getWavelength", ATTR_SET)

    async def set_auto_range(self, enabled: bool) -> None:
        mode = AUTORANGE_ON if enabled else AUTORANGE_OFF
        await asyncio.to_thread(self._call, "TLPMX_setPowerAutoRange", ctypes.c_uint8(mode),
                                self._channel)

    async def get_auto_range(self) -> bool:
        return await asyncio.to_thread(self._get_auto_range_sync)

    async def set_average_time_s(self, seconds: float) -> None:
        low, high = self._avg_time_bounds_s
        if not low <= seconds <= high:
            raise ValueError(f"average time {seconds} s outside [{low}, {high}] s")
        await asyncio.to_thread(self._call, "TLPMX_setAvgTime", ctypes.c_double(seconds),
                                self._channel)

    async def get_average_time_s(self) -> float:
        return await asyncio.to_thread(self._get_double, "TLPMX_getAvgTime", ATTR_SET)

    async def shutdown(self) -> None:
        """Close the session. Idempotent; the meter keeps its settings."""
        await asyncio.to_thread(self._shutdown_sync)

    def controls(self) -> DeviceControls:
        wl_low, wl_high = self._wavelength_bounds_nm
        avg_low, avg_high = self._avg_time_bounds_s
        return DeviceControls(
            setables=[
                Setable(
                    name="wavelength",
                    display="Wavelength",
                    unit="nm",
                    kind=float,
                    bounds=Range(wl_low, wl_high),
                    choices=None,
                    get=self.get_wavelength_nm,
                    set=self.set_wavelength_nm,
                ),
                Setable(
                    name="auto_range",
                    display="Auto range",
                    unit="",
                    kind=bool,
                    bounds=None,
                    choices=None,
                    get=self.get_auto_range,
                    set=self.set_auto_range,
                ),
                Setable(
                    name="average_time",
                    display="Average time",
                    unit="s",
                    kind=float,
                    bounds=Range(avg_low, avg_high),
                    choices=None,
                    get=self.get_average_time_s,
                    set=self.set_average_time_s,
                ),
            ],
            readables=[
                Readable(name="power", display="Power", unit="W", kind=float,
                         get=self.read_power_w, display_precision=1e-9),
            ],
            actions=[],
        )

    # ----- blocking implementation -----

    def _connect(self) -> None:
        count = ctypes.c_uint32()
        self._call_unopened("TLPMX_findRsrc", ctypes.c_uint32(0), ctypes.byref(count))
        found = []
        for index in range(count.value):
            resource = ctypes.create_string_buffer(BUFFER_SIZE)
            model = ctypes.create_string_buffer(BUFFER_SIZE)
            serial = ctypes.create_string_buffer(BUFFER_SIZE)
            maker = ctypes.create_string_buffer(BUFFER_SIZE)
            available = ctypes.c_uint8()
            self._call_unopened("TLPMX_getRsrcName", ctypes.c_uint32(0), ctypes.c_uint32(index),
                                resource)
            self._call_unopened("TLPMX_getRsrcInfo", ctypes.c_uint32(0), ctypes.c_uint32(index),
                                model, serial, maker, ctypes.byref(available))
            found.append((resource.value, model.value.decode(errors="replace"),
                          serial.value.decode(errors="replace"), bool(available.value)))

        matches = [f for f in found if self._serial is None or f[2] == self._serial]
        if not matches:
            listed = ", ".join(f"{m} S/N {s}" for _r, m, s, _a in found) or "none"
            wanted = f"S/N {self._serial}" if self._serial else "any meter"
            raise ThorlabsPM100Error(f"Thorlabs power meter ({wanted}) not found; found: {listed}")
        resource, model, serial, available = matches[0]
        if not available:
            # Hardware (S/N 1931430, 2026-09-15): the flag stayed 0 with nothing else holding
            # the meter, and opening worked. Only a failing init means the meter is busy.
            logger.warning("%s S/N %s reports not available; trying to open anyway",
                           model, serial)

        session = ctypes.c_uint32(0)
        status = self._lib.TLPMX_init(resource, ctypes.c_uint8(1), ctypes.c_uint8(0),
                                      ctypes.byref(session))
        if status < 0:
            hint = (" — the meter reports it is in use; close Optical Power Monitor or other "
                    "software" if not available else "")
            raise ThorlabsPM100Error(
                f"TLPMX_init failed for {resource.decode(errors='replace')}: "
                f"{self._error_text(session, status)}{hint}"
            )
        self._session = session
        self._open = True
        self._serial = serial
        self.model = model
        self.resource_name = resource.decode(errors="replace")
        try:
            self._wavelength_bounds_nm = (self._get_double("TLPMX_getWavelength", ATTR_MIN),
                                          self._get_double("TLPMX_getWavelength", ATTR_MAX))
            self._avg_time_bounds_s = (self._get_double("TLPMX_getAvgTime", ATTR_MIN),
                                       self._get_double("TLPMX_getAvgTime", ATTR_MAX))
        except Exception:
            self._shutdown_sync()
            raise
        logger.info("connected %s S/N %s (%s)", model, serial, self.resource_name)

    def _read_power_sync(self) -> float:
        value = ctypes.c_double()
        self._call("TLPMX_measPower", ctypes.byref(value), self._channel)
        return float(value.value)

    def _set_wavelength_sync(self, wavelength_nm: float) -> None:
        low, high = self._wavelength_bounds_nm
        if not low <= wavelength_nm <= high:
            raise ValueError(f"wavelength {wavelength_nm} nm outside the sensor's "
                             f"[{low}, {high}] nm")
        self._call("TLPMX_setWavelength", ctypes.c_double(wavelength_nm), self._channel)

    def _get_auto_range_sync(self) -> bool:
        mode = ctypes.c_uint8()
        self._call("TLPMX_getPowerAutorange", ctypes.byref(mode), self._channel)
        return mode.value == AUTORANGE_ON

    def _get_double(self, function: str, attribute: int) -> float:
        value = ctypes.c_double()
        self._call(function, ctypes.c_int16(attribute), ctypes.byref(value), self._channel)
        return float(value.value)

    def _call(self, function: str, *args: Any) -> None:
        if not self._open:
            raise ThorlabsPM100Error(f"{self._name}: power meter session is closed")
        with self._lock:
            status = getattr(self._lib, function)(self._session, *args)
        if status < 0:
            detail = self._error_text(self._session, status)
            raise ThorlabsPM100Error(f"{function} failed for S/N {self._serial}: {detail}")

    def _call_unopened(self, function: str, *args: Any) -> None:
        with self._lock:
            status = getattr(self._lib, function)(*args)
        if status < 0:
            raise ThorlabsPM100Error(f"{function} failed: "
                                     f"{self._error_text(ctypes.c_uint32(0), status)}")

    def _error_text(self, session: ctypes.c_uint32, status: int) -> str:
        buffer = ctypes.create_string_buffer(BUFFER_SIZE)
        try:
            self._lib.TLPMX_errorMessage(session, ctypes.c_long(status), buffer)
            text = buffer.value.decode(errors="replace")
        except Exception:  # noqa: BLE001
            text = ""
        return f"{text or 'error'} (status {status})"

    def _shutdown_sync(self) -> None:
        if not self._open:
            return
        with self._lock:
            try:
                self._lib.TLPMX_close(self._session)
            except Exception as e:  # noqa: BLE001
                logger.warning("TLPMX_close failed: %s", e)
            self._open = False


def _load_library(dll_path: Path) -> ctypes.CDLL:
    if not dll_path.exists():
        raise FileNotFoundError(
            f"Thorlabs TLPMX library not found at {dll_path} (install Thorlabs Optical Power "
            "Monitor)"
        )
    lib = ctypes.cdll.LoadLibrary(str(dll_path))
    _configure_signatures(lib)
    return lib


def _configure_signatures(lib: ctypes.CDLL) -> None:
    session = ctypes.c_uint32
    status = ctypes.c_long
    signatures: dict[str, list[Any]] = {
        "TLPMX_init": [ctypes.c_char_p, ctypes.c_uint8, ctypes.c_uint8, ctypes.POINTER(session)],
        "TLPMX_close": [session],
        "TLPMX_findRsrc": [session, ctypes.POINTER(ctypes.c_uint32)],
        "TLPMX_getRsrcName": [session, ctypes.c_uint32, ctypes.c_char_p],
        "TLPMX_getRsrcInfo": [session, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p,
                              ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint8)],
        "TLPMX_measPower": [session, ctypes.POINTER(ctypes.c_double), ctypes.c_uint16],
        "TLPMX_setWavelength": [session, ctypes.c_double, ctypes.c_uint16],
        "TLPMX_getWavelength": [session, ctypes.c_int16, ctypes.POINTER(ctypes.c_double),
                                ctypes.c_uint16],
        "TLPMX_setPowerAutoRange": [session, ctypes.c_uint8, ctypes.c_uint16],
        "TLPMX_getPowerAutorange": [session, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint16],
        "TLPMX_setAvgTime": [session, ctypes.c_double, ctypes.c_uint16],
        "TLPMX_getAvgTime": [session, ctypes.c_int16, ctypes.POINTER(ctypes.c_double),
                             ctypes.c_uint16],
        "TLPMX_errorMessage": [session, status, ctypes.c_char_p],
    }
    for function_name, argtypes in signatures.items():
        function = getattr(lib, function_name)
        function.restype = status
        function.argtypes = argtypes
