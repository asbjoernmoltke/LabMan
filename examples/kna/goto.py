"""Ramp the KNA outputs to (H, V) in small steps, read the signal before and after,
and leave the outputs latched there (shutdown latches, never zeroes).

Usage: goto.py <H V> <V V> [step V]
"""
import asyncio
import math
import statistics
import sys

from labman_core.drivers.kinesis_nanotrak import KinesisNanoTrak


async def signal(dev: KinesisNanoTrak, n: int = 20) -> str:
    vals = [(await dev.read_signal()).signal_a for _ in range(n)]
    good = [x for x in vals if not math.isnan(x)]
    return (f"{statistics.mean(good) * 1e9:.2f} ± {statistics.stdev(good) * 1e9:.2f} nA "
            f"({len(good)}/{n})")


async def main() -> None:
    target_h, target_v = float(sys.argv[1]), float(sys.argv[2])
    step = float(sys.argv[3]) if len(sys.argv) > 3 else 2.5
    dev = KinesisNanoTrak("57535374", name="aligner", max_voltage_v=150, set_voltage_range=True)
    try:
        h, v = await dev.get_position_v()
        print(f"from H {h:.2f} / V {v:.2f} V, signal {await signal(dev)}", flush=True)
        n = max(1, math.ceil(max(abs(target_h - h), abs(target_v - v)) / step))
        for k in range(1, n + 1):
            await dev.move_to_v(h + (target_h - h) * k / n, v + (target_v - v) * k / n)
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.0)
        h2, v2 = await dev.get_position_v()
        print(f"now  H {h2:.2f} / V {v2:.2f} V ({n} steps), signal {await signal(dev)}")
    finally:
        await dev.shutdown()
    print("outputs latched at the new position")


asyncio.run(main())
