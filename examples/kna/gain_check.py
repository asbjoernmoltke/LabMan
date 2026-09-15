"""Check whether the KNA's TIA ranges agree (no mirror moves).

Reads the current range mode, then forces manual ranging on several ranges in turn at
the current mirror position and compares relative/32767 x nominal full scale. Restores
the original range mode at the end, also on errors.

Usage: gain_check.py [range codes, default 5 6 7 8]
"""
import ctypes
import statistics
import sys
import time

from labman_core.drivers.kinesis_nanotrak import (
    RELATIVE_FULL,
    TIA_FULL_SCALE_A,
    KinesisNanoTrak,
    TIAReading,
)

RANGES = [int(r) for r in sys.argv[1:]] or [5, 6, 7, 8]
MODE_NAMES = {0: "undefined", 1: "auto at selected", 2: "manual at selected",
              3: "manual at parameter", 4: "auto at parameter"}
MANUAL_AT_SELECTED = 2


class ProbeNanoTrak(KinesisNanoTrak):
    def _ensure_voltage_range(self) -> None:  # never switch the HV range here
        self.ranges = self._read_voltage_range()


def readings(dev: KinesisNanoTrak, n: int = 20) -> list[tuple[int, int, int]]:
    """(relative, range code, under/over) with explicit requests, 150 ms apart."""
    lib, serial = dev._lib, dev._serial
    out = []
    for _ in range(n):
        reading = TIAReading()
        lib.NT_RequestReading(serial)
        time.sleep(0.15)
        lib.NT_GetReading(serial, ctypes.byref(reading))
        out.append((reading.relativeReading, reading.selectedRange, reading.underOrOverRead))
    return out


def summary(rows: list[tuple[int, int, int]]) -> str:
    codes = sorted({r for _, r, _ in rows})
    states = sorted({s for _, _, s in rows})
    nA = [rel / RELATIVE_FULL * TIA_FULL_SCALE_A[r] * 1e9 for rel, r, _ in rows
          if r in TIA_FULL_SCALE_A and rel <= RELATIVE_FULL]
    rel = [rel for rel, _, _ in rows]
    if not nA:
        return f"codes {codes}, states {states}, no convertible readings"
    return (f"range codes {codes}, under/over {states}, relative median "
            f"{statistics.median(rel):.0f}, current {statistics.mean(nA):.2f} ± "
            f"{statistics.stdev(nA):.2f} nA")


def main() -> None:
    dev = ProbeNanoTrak("57535374", max_voltage_v=150)
    lib, serial = dev._lib, dev._serial
    lib.NT_RequestTIArangeParams.restype = ctypes.c_short
    lib.NT_RequestTIArangeParams.argtypes = [ctypes.c_char_p]
    lib.NT_GetRangeMode.restype = ctypes.c_short
    lib.NT_GetRangeMode.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint16),
                                    ctypes.POINTER(ctypes.c_uint16)]
    lib.NT_SetRangeMode.restype = ctypes.c_short
    lib.NT_SetRangeMode.argtypes = [ctypes.c_char_p, ctypes.c_uint16, ctypes.c_uint16]
    lib.NT_GetTIARange.restype = ctypes.c_uint16
    lib.NT_GetTIARange.argtypes = [ctypes.c_char_p]
    lib.NT_SetTIARange.restype = ctypes.c_short
    lib.NT_SetTIARange.argtypes = [ctypes.c_char_p, ctypes.c_uint16]

    mode, odd_even = ctypes.c_uint16(), ctypes.c_uint16()
    lib.NT_RequestTIArangeParams(serial)
    time.sleep(0.5)
    code = lib.NT_GetRangeMode(serial, ctypes.byref(mode), ctypes.byref(odd_even))
    original = (mode.value, odd_even.value)
    print(f"position words {dev._get_words_sync()}; range mode {original[0]} "
          f"({MODE_NAMES.get(original[0], '?')}), odd/even {original[1]}, "
          f"current TIA range code {lib.NT_GetTIARange(serial)} (get code {code})")
    try:
        print(f"[auto, before] {summary(readings(dev))}", flush=True)
        results = {}
        for rng in RANGES:
            c1 = lib.NT_SetRangeMode(serial, MANUAL_AT_SELECTED, original[1] or 1)
            c2 = lib.NT_SetTIARange(serial, rng)
            time.sleep(0.8)
            rows = readings(dev)
            results[rng] = rows
            print(f"[manual range {rng} ({TIA_FULL_SCALE_A[rng] * 1e9:g} nA FS), codes "
                  f"{c1}/{c2}] {summary(rows)}", flush=True)
        means = {}
        for rng, rows in results.items():
            vals = [rel / RELATIVE_FULL * TIA_FULL_SCALE_A[r] * 1e9 for rel, r, s in rows
                    if r == rng and s == 1 and rel <= RELATIVE_FULL]
            if len(vals) >= 5:
                means[rng] = statistics.mean(vals)
        if means:
            ref = means.get(6) or next(iter(means.values()))
            print("ratio to reference: " + ", ".join(f"range {r}: {m / ref:.3f}"
                                                     for r, m in means.items()))
    finally:
        restore = lib.NT_SetRangeMode(serial, original[0] or 1, original[1] or 1)
        time.sleep(0.8)
        lib.NT_RequestTIArangeParams(serial)
        time.sleep(0.5)
        lib.NT_GetRangeMode(serial, ctypes.byref(mode), ctypes.byref(odd_even))
        print(f"restored range mode -> {mode.value} ({MODE_NAMES.get(mode.value, '?')}), "
              f"odd/even {odd_even.value} (set code {restore})")
        print(f"[auto, after] {summary(readings(dev, 10))}")
        dev._shutdown_sync()


main()
