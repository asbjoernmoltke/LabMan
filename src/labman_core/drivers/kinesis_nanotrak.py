"""Thorlabs K-Cube NanoTrak (KNA-IR / KNA-VIS) via the Kinesis C API (ctypes).

Implements the `Aligner` protocol. LabMan runs its own scan loop, so the device
is kept in latch mode: the firmware's tracking mode maximizes signal and is
never enabled by this driver.

The piezo output voltage range (75 V / 150 V) is verified at connect time. By
default a mismatch with `max_voltage_v` is refused. With `set_voltage_range=True`
the driver switches the range itself, ordering the steps so the real output
voltage never rises above its current value, and persists the setting on the
device. (The Kinesis app pushes its own 75 V default whenever it connects.)

Kinesis calls block, so the async methods run them in a worker thread;
a lock serializes access to the DLL for this device.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

from labman_core.devices import SignalReading
from labman_core.schema import Action, DeviceControls, Range, Readable, Setable

logger = logging.getLogger("labman.drivers.kinesis_nanotrak")

DEFAULT_KINESIS_DIR = Path(r"C:\Program Files\Thorlabs\Kinesis")
DLL_NAME = "Thorlabs.MotionControl.KCube.NanoTrak.dll"

NT_MODE_LATCH = 0x02
NT_IN_RANGE = 0x0001
KNA_CH1_150V = 0x01
KNA_CH2_150V = 0x10
WORD_MAX = 65535
RELATIVE_FULL = 32767

# KNA_TIARange code -> full-scale current (A), from the Kinesis header. Used only to
# sanity-check absoluteReading against relativeReading, so a constant scale mismatch
# (seen on hardware: absolute ≈ 0.36 × relative·full-scale) is tolerated.
TIA_FULL_SCALE_A = {
    3: 5e-9, 4: 16.6e-9, 5: 50e-9, 6: 166e-9, 7: 500e-9, 8: 1.66e-6, 9: 5e-6,
    10: 16.6e-6, 11: 50e-6, 12: 166e-6, 13: 500e-6, 14: 1.66e-3, 15: 5e-3,
}


class KinesisError(RuntimeError):
    """A Kinesis call returned an error code or the device state is unexpected."""


class HVComponent(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("horizontalComponent", ctypes.c_uint16), ("verticalComponent", ctypes.c_uint16)]


class TIAReading(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("absoluteReading", ctypes.c_float),
        ("relativeReading", ctypes.c_uint16),
        ("selectedRange", ctypes.c_uint16),
        ("underOrOverRead", ctypes.c_uint16),
    ]


class KinesisNanoTrak:
    def __init__(
        self,
        serial_no: str | int,
        name: str = "nanotrak",
        max_voltage_v: float = 150.0,
        # Hardware (S/N 57535374, 2026-09-15): at 20 ms the KNA stopped sending status and
        # readings after a burst of moves, until a USB replug. 200 ms (as in Thorlabs'
        # examples) stayed fresh even with a move every 20 ms.
        poll_ms: int = 200,
        read_delay_s: float = 0.05,
        read_retries: int = 2,
        startup_wait_s: float = 0.5,
        kinesis_dir: str | Path = DEFAULT_KINESIS_DIR,
        simulation: bool = False,
        set_voltage_range: bool = False,
        _lib: Any = None,
    ) -> None:
        if float(max_voltage_v) not in (75.0, 150.0):
            raise ValueError(f"max_voltage_v must be 75 or 150, got {max_voltage_v}")
        self._name = name
        self._serial = str(serial_no).encode("ascii")
        self._max_v = float(max_voltage_v)
        self._poll_ms = int(poll_ms)
        # Hardware bring-up (S/N 57535374): with no delay the same stale value comes
        # back; ≥30 ms gives fresh readings.
        self._read_delay_s = float(read_delay_s)
        self._read_retries = int(read_retries)
        self._set_voltage_range = bool(set_voltage_range)
        self._startup_wait_s = float(startup_wait_s)
        self._lock = threading.Lock()
        self._lib = _lib if _lib is not None else _load_library(Path(kinesis_dir))
        self._open = False
        self._connect(simulation)

    # ----- Aligner protocol -----

    @property
    def name(self) -> str:
        return self._name

    @property
    def max_voltage_v(self) -> float:
        return self._max_v

    async def get_position_v(self) -> tuple[float, float]:
        return await asyncio.to_thread(self._get_position_sync)

    async def move_to_v(self, horizontal_v: float, vertical_v: float) -> None:
        position = HVComponent(self._to_word(horizontal_v), self._to_word(vertical_v))
        await asyncio.to_thread(self._move_sync, position)

    async def read_signal(self) -> SignalReading:
        return await asyncio.to_thread(self._read_signal_sync)

    async def latch(self) -> None:
        await asyncio.to_thread(self._call, "NT_SetMode", NT_MODE_LATCH)

    async def identify(self) -> None:
        await asyncio.to_thread(self._call_void, "NT_Identify")

    async def shutdown(self) -> None:
        """Latch (hold the current output), stop polling and close. Idempotent.

        Outputs are deliberately not zeroed: that would lose the alignment.
        """
        await asyncio.to_thread(self._shutdown_sync)

    def controls(self) -> DeviceControls:
        return DeviceControls(
            setables=[
                Setable(
                    name="horizontal_v",
                    display="Horizontal",
                    unit="V",
                    kind=float,
                    bounds=Range(0.0, self._max_v),
                    choices=None,
                    get=self._get_h,
                    set=self._set_h,
                ),
                Setable(
                    name="vertical_v",
                    display="Vertical",
                    unit="V",
                    kind=float,
                    bounds=Range(0.0, self._max_v),
                    choices=None,
                    get=self._get_v,
                    set=self._set_v,
                ),
            ],
            readables=[
                Readable(name="signal", display="Signal", unit="A", kind=float,
                         get=self._get_signal),
            ],
            actions=[
                Action(name="latch", display="Latch", call=self.latch),
                Action(name="identify", display="Identify (blink)", call=self.identify),
            ],
        )

    # ----- conversions -----

    def _to_word(self, volts: float) -> int:
        v = float(volts)
        if not 0.0 <= v <= self._max_v:
            raise ValueError(f"{v} V outside [0, {self._max_v}] V")
        return round(v / self._max_v * WORD_MAX)

    def _to_volts(self, word: int) -> float:
        return int(word) / WORD_MAX * self._max_v

    # ----- blocking implementation -----

    def _connect(self, simulation: bool) -> None:
        lib = self._lib
        if simulation:
            lib.TLI_InitializeSimulations()
        self._check(lib.TLI_BuildDeviceList(), "TLI_BuildDeviceList")
        self._check(lib.NT_Open(self._serial), "NT_Open")
        self._open = True
        try:
            if not lib.NT_StartPolling(self._serial, self._poll_ms):
                raise KinesisError(f"NT_StartPolling failed for {self._serial.decode()}")
            time.sleep(self._startup_wait_s)
            self._check(lib.NT_SetMode(self._serial, NT_MODE_LATCH), "NT_SetMode(latch)")
            self._ensure_voltage_range()
        except Exception:
            self._shutdown_sync()
            raise
        logger.info("connected KNA %s (%.0f V range)", self._serial.decode(), self._max_v)

    def _read_voltage_range(self) -> tuple[float, float, int]:
        """(CH1 range V, CH2 range V, raw HV route flags) as currently set on the device."""
        lib = self._lib
        self._check(lib.NT_RequestIOsettings(self._serial), "NT_RequestIOsettings")
        time.sleep(self._startup_wait_s)
        voltage_range = ctypes.c_uint16()
        route = ctypes.c_uint16()
        self._check(
            lib.NT_GetIOsettings(self._serial, ctypes.byref(voltage_range), ctypes.byref(route)),
            "NT_GetIOsettings",
        )
        ch1 = 150.0 if voltage_range.value & KNA_CH1_150V else 75.0
        ch2 = 150.0 if voltage_range.value & KNA_CH2_150V else 75.0
        return ch1, ch2, route.value

    def _ensure_voltage_range(self) -> None:
        ch1, ch2, route = self._read_voltage_range()
        if ch1 == self._max_v and ch2 == self._max_v:
            return
        if not self._set_voltage_range:
            raise KinesisError(
                f"KNA {self._serial.decode()} output range is CH1 {ch1:.0f} V / CH2 {ch2:.0f} V "
                f"but max_voltage_v is {self._max_v:.0f} V. Set the range in Kinesis, or pass "
                "set_voltage_range: true to let LabMan switch it."
            )
        self._switch_voltage_range((ch1, ch2), route)

    def _switch_voltage_range(self, old_ranges: tuple[float, float], route: int) -> None:
        """Switch both outputs to `max_voltage_v`, keeping their real voltages.

        The position is a fraction of the range, so switching range at a fixed
        position scales the real voltage. To never exceed the current voltage:
        channels whose range goes up get their position lowered *before* the
        switch, channels whose range goes down get it raised *after* the switch.
        Either way the output only dips briefly, then returns to its old voltage.
        """
        serial = self._serial.decode()
        new_range = self._max_v
        old_words = self._get_words_sync()
        volts = [w / WORD_MAX * r for w, r in zip(old_words, old_ranges, strict=True)]
        if any(v > new_range for v in volts):
            raise KinesisError(
                f"KNA {serial} outputs are at H {volts[0]:.2f} V / V {volts[1]:.2f} V, above the "
                f"{new_range:.0f} V range; lower them before switching range"
            )
        target = [round(v / new_range * WORD_MAX) for v in volts]
        first = [t if new_range > r else w
                 for t, w, r in zip(target, old_words, old_ranges, strict=True)]

        logger.warning(
            "KNA %s: switching output range CH1 %.0f V / CH2 %.0f V -> %.0f V, keeping outputs "
            "at H %.2f V / V %.2f V", serial, old_ranges[0], old_ranges[1], new_range, *volts,
        )
        self._move_sync(HVComponent(*first))
        flags = (KNA_CH1_150V | KNA_CH2_150V) if new_range == 150.0 else 0
        self._check(self._lib.NT_SetIOsettings(self._serial, flags, route), "NT_SetIOsettings")
        time.sleep(self._startup_wait_s)
        self._move_sync(HVComponent(*target))
        if not self._lib.NT_PersistSettings(self._serial):
            logger.warning("KNA %s: NT_PersistSettings failed; the range may revert after a "
                           "power cycle", serial)

        ch1, ch2, _route = self._read_voltage_range()
        if ch1 != new_range or ch2 != new_range:
            raise KinesisError(
                f"KNA {serial}: switching the output range to {new_range:.0f} V did not take "
                f"(device reports CH1 {ch1:.0f} V / CH2 {ch2:.0f} V)"
            )
        words = self._get_words_sync()
        if any(abs(w - t) > 2 for w, t in zip(words, target, strict=True)):
            raise KinesisError(
                f"KNA {serial}: position after the range switch is {words}, expected {target}"
            )
        logger.warning("KNA %s: output range now %.0f V", serial, new_range)

    def _get_words_sync(self) -> tuple[int, int]:
        position = HVComponent()
        with self._lock:
            self._check(
                self._lib.NT_GetCirclePosition(self._serial, ctypes.byref(position)),
                "NT_GetCirclePosition",
            )
        return position.horizontalComponent, position.verticalComponent

    def _get_position_sync(self) -> tuple[float, float]:
        h, v = self._get_words_sync()
        return self._to_volts(h), self._to_volts(v)

    def _move_sync(self, position: HVComponent) -> None:
        with self._lock:
            self._check(
                self._lib.NT_SetCircleHomePosition(self._serial, ctypes.byref(position)),
                "NT_SetCircleHomePosition",
            )
            self._check(self._lib.NT_HomeCircle(self._serial), "NT_HomeCircle")

    def _read_signal_sync(self) -> SignalReading:
        """One detector reading; retried if implausible.

        On hardware the DLL occasionally returns a garbage absoluteReading (~1e-38)
        alongside a normal relativeReading. Passed through, that looks like a
        perfect dip. If retries don't help, return NaN flagged out of range so the
        tracker holds instead of acting on it.
        """
        for attempt in range(self._read_retries + 1):
            reading = TIAReading()
            with self._lock:
                self._check(self._lib.NT_RequestReading(self._serial), "NT_RequestReading")
                time.sleep(self._read_delay_s)
                self._check(
                    self._lib.NT_GetReading(self._serial, ctypes.byref(reading)), "NT_GetReading"
                )
            if _reading_is_plausible(reading):
                return SignalReading(
                    signal_a=float(reading.absoluteReading),
                    in_range=reading.underOrOverRead == NT_IN_RANGE,
                )
            logger.warning(
                "discarding implausible KNA reading %.3g (relative %d, range %d), attempt %d",
                reading.absoluteReading, reading.relativeReading, reading.selectedRange,
                attempt + 1,
            )
        return SignalReading(signal_a=math.nan, in_range=False)

    def _call(self, function: str, *args: Any) -> None:
        with self._lock:
            self._check(getattr(self._lib, function)(self._serial, *args), function)

    def _call_void(self, function: str) -> None:
        with self._lock:
            getattr(self._lib, function)(self._serial)

    def _shutdown_sync(self) -> None:
        if not self._open:
            return
        with self._lock:
            for function, args in (("NT_SetMode", (NT_MODE_LATCH,)), ("NT_StopPolling", ()),
                                   ("NT_Close", ())):
                try:
                    getattr(self._lib, function)(self._serial, *args)
                except Exception as e:  # noqa: BLE001
                    logger.warning("%s failed during shutdown: %s", function, e)
            self._open = False

    def _check(self, code: int, what: str) -> None:
        if code != 0:
            raise KinesisError(
                f"{what} failed for KNA {self._serial.decode()}: Kinesis error {code}"
            )

    async def _get_h(self) -> float:
        return (await self.get_position_v())[0]

    async def _get_v(self) -> float:
        return (await self.get_position_v())[1]

    async def _set_h(self, value: float) -> None:
        _h, v = await self.get_position_v()
        await self.move_to_v(value, v)

    async def _set_v(self, value: float) -> None:
        h, _v = await self.get_position_v()
        await self.move_to_v(h, value)

    async def _get_signal(self) -> float:
        return (await self.read_signal()).signal_a


def _reading_is_plausible(reading: TIAReading) -> bool:
    """absoluteReading must be finite and, when relativeReading is at least 1 % of the
    range, within three orders of magnitude of relative × range full scale."""
    absolute = float(reading.absoluteReading)
    if not math.isfinite(absolute):
        return False
    full_scale = TIA_FULL_SCALE_A.get(int(reading.selectedRange))
    if full_scale is None or reading.relativeReading < RELATIVE_FULL // 100:
        return True  # nothing to cross-check against (unknown range or near-dark)
    expected = reading.relativeReading / RELATIVE_FULL * full_scale
    return 1e-3 * expected <= absolute <= 1e3 * expected


def _load_library(kinesis_dir: Path) -> ctypes.CDLL:
    dll = kinesis_dir / DLL_NAME
    if not dll.exists():
        raise FileNotFoundError(f"Kinesis NanoTrak DLL not found at {dll}")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(kinesis_dir))  # Kinesis DLLs load their dependencies from here
    lib = ctypes.cdll.LoadLibrary(str(dll))
    _configure_signatures(lib)
    return lib


def _configure_signatures(lib: ctypes.CDLL) -> None:
    serial = ctypes.c_char_p
    signatures: dict[str, tuple[Any, list[Any]]] = {
        "TLI_BuildDeviceList": (ctypes.c_short, []),
        "TLI_InitializeSimulations": (None, []),
        "NT_Open": (ctypes.c_short, [serial]),
        "NT_Close": (None, [serial]),
        "NT_StartPolling": (ctypes.c_bool, [serial, ctypes.c_int]),
        "NT_StopPolling": (None, [serial]),
        "NT_Identify": (None, [serial]),
        "NT_SetMode": (ctypes.c_short, [serial, ctypes.c_uint16]),
        "NT_SetCircleHomePosition": (ctypes.c_short, [serial, ctypes.POINTER(HVComponent)]),
        "NT_HomeCircle": (ctypes.c_short, [serial]),
        "NT_GetCirclePosition": (ctypes.c_short, [serial, ctypes.POINTER(HVComponent)]),
        "NT_RequestReading": (ctypes.c_short, [serial]),
        "NT_GetReading": (ctypes.c_short, [serial, ctypes.POINTER(TIAReading)]),
        "NT_RequestIOsettings": (ctypes.c_short, [serial]),
        "NT_SetIOsettings": (ctypes.c_short, [serial, ctypes.c_uint16, ctypes.c_uint16]),
        "NT_PersistSettings": (ctypes.c_bool, [serial]),
        "NT_GetIOsettings": (
            ctypes.c_short,
            [serial, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint16)],
        ),
    }
    for function_name, (restype, argtypes) in signatures.items():
        function = getattr(lib, function_name)
        function.restype = restype
        function.argtypes = argtypes
