"""Measure how fast the KNA reading follows a mirror move (reading lag / piezo response).

Moves H between two voltages at fixed V (latched moves), sampling the TIA reading every
~20 ms for a while after each jump. Reports time to 50 % and 90 % of the step, for up and
down jumps, and compares with the driver's own read_signal() cadence.

Usage: step_response.py [low H V] [high H V] [V V] [cycles] [record s]
Returns to the starting position at the end.
"""
import asyncio
import ctypes
import statistics
import sys
import time

import numpy as np

from labman_core.drivers.kinesis_nanotrak import (
    RELATIVE_FULL,
    TIA_FULL_SCALE_A,
    KinesisNanoTrak,
    TIAReading,
)

LOW_H = float(sys.argv[1]) if len(sys.argv) > 1 else 75.0
HIGH_H = float(sys.argv[2]) if len(sys.argv) > 2 else 130.0
V_V = float(sys.argv[3]) if len(sys.argv) > 3 else 75.0
CYCLES = int(sys.argv[4]) if len(sys.argv) > 4 else 3
RECORD_S = float(sys.argv[5]) if len(sys.argv) > 5 else 2.0


def fast_trace(dev: KinesisNanoTrak, seconds: float) -> tuple[np.ndarray, np.ndarray]:
    """(t since call, signal nA) sampled every ~20 ms with explicit reading requests."""
    lib, serial = dev._lib, dev._serial
    ts, sig = [], []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        reading = TIAReading()
        lib.NT_RequestReading(serial)
        time.sleep(0.02)
        lib.NT_GetReading(serial, ctypes.byref(reading))
        fs = TIA_FULL_SCALE_A.get(int(reading.selectedRange))
        if fs is not None and reading.relativeReading <= RELATIVE_FULL:
            ts.append(time.perf_counter() - t0)
            sig.append(reading.relativeReading / RELATIVE_FULL * fs * 1e9)
    return np.array(ts), np.array(sig)


def crossing(ts: np.ndarray, sig: np.ndarray, before: float, after: float,
             fraction: float) -> float:
    level = before + fraction * (after - before)
    rising = after > before
    for t, s in zip(ts, sig, strict=True):
        if (s >= level) if rising else (s <= level):
            return t
    return float("nan")


async def main() -> None:
    dev = KinesisNanoTrak("57535374", name="aligner", max_voltage_v=150, set_voltage_range=True)
    try:
        start = await dev.get_position_v()
        print(f"start H {start[0]:.2f} / V {start[1]:.2f} V; stepping H {LOW_H} <-> {HIGH_H} V "
              f"at V {V_V} V, {CYCLES} cycles, {RECORD_S} s per step")
        await dev.move_to_v(LOW_H, V_V)
        await asyncio.sleep(1.5)
        results = {"up": [], "down": []}
        level = {LOW_H: fast_trace(dev, 0.6)[1]}
        for cycle in range(CYCLES):
            for target, name in ((HIGH_H, "up"), (LOW_H, "down")):
                other = LOW_H if target == HIGH_H else HIGH_H
                before = statistics.median(level[other][-10:]) if other in level else None
                await dev.move_to_v(target, V_V)
                ts, sig = fast_trace(dev, RECORD_S)
                after = statistics.median(sig[-10:])
                level[target] = sig
                if before is None:
                    continue
                t50 = crossing(ts, sig, before, after, 0.5)
                t90 = crossing(ts, sig, before, after, 0.9)
                results[name].append((t50, t90))
                print(f"  cycle {cycle + 1} {name:4s}: {before:6.2f} -> {after:6.2f} nA, "
                      f"t50 {t50 * 1000:5.0f} ms, t90 {t90 * 1000:5.0f} ms, "
                      f"{ts.size} samples, first samples "
                      + ", ".join(f"{t * 1000:.0f}ms:{s:.1f}" for t, s in zip(ts[:6], sig[:6],
                                                                         strict=True)))
        for name, vals in results.items():
            if vals:
                t50 = np.nanmedian([v[0] for v in vals]) * 1000
                t90 = np.nanmedian([v[1] for v in vals]) * 1000
                print(f"{name}: median t50 {t50:.0f} ms, t90 {t90:.0f} ms")

        # the driver's own cadence: read_signal() calls right after a move
        await dev.move_to_v(LOW_H, V_V)
        await asyncio.sleep(1.5)
        await dev.move_to_v(HIGH_H, V_V)
        t0 = time.perf_counter()
        trace = []
        for _ in range(12):
            r = await dev.read_signal()
            trace.append(f"{(time.perf_counter() - t0) * 1000:.0f}ms:{r.signal_a * 1e9:.1f}")
        print("driver read_signal() after a jump up: " + ", ".join(trace))
    finally:
        try:
            await dev.move_to_v(*start)
        finally:
            await dev.shutdown()
        print(f"returned to H {start[0]:.2f} / V {start[1]:.2f} V")


asyncio.run(main())
