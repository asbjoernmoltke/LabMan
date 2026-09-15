"""Run an auto-alignment map on the KNA and save map.png into the run folder.

Usage: map_run.py <half width V> <points per axis> [settle s] [averages] [min start nA]
Refuses to scan (no moves) if the signal at the start is below `min start nA`
(laser blocked?). Reads the start signal before and after to check drift.
"""
import asyncio
import logging
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from labman_core.context import TaskContext
from labman_core.drivers.kinesis_nanotrak import KinesisNanoTrak
from labman_core.storage import DEFAULT_DATA_ROOT, RunStorage, StorageOptions
from labman_tasks.auto_alignment.params import AutoAlignmentParams
from labman_tasks.auto_alignment.task import AutoAlignmentTask

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
HERE = Path(__file__).parent


async def signal_at_rest(dev: KinesisNanoTrak, n: int = 20) -> tuple[float, str]:
    vals = [(await dev.read_signal()).signal_a for _ in range(n)]
    good = [x for x in vals if not math.isnan(x)]
    mean = statistics.mean(good)
    return mean, f"{mean * 1e9:.2f} ± {statistics.stdev(good) * 1e9:.2f} nA ({len(good)}/{n})"


async def main() -> None:
    half_width, points = float(sys.argv[1]), int(sys.argv[2])
    settle = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
    averages = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    min_start_a = (float(sys.argv[5]) if len(sys.argv) > 5 else 3.0) * 1e-9

    dev = KinesisNanoTrak("57535374", name="aligner", max_voltage_v=150, set_voltage_range=True)
    try:
        start = await dev.get_position_v()
        start_signal, text = await signal_at_rest(dev)
        print(f"start H {start[0]:.2f} V / V {start[1]:.2f} V, signal {text}", flush=True)
        if start_signal < min_start_a:
            print(f"start signal below {min_start_a * 1e9:.1f} nA — laser blocked? Not scanning.")
            return
        storage = RunStorage("auto_alignment", StorageOptions(), DEFAULT_DATA_ROOT)
        ctx = TaskContext(devices={"aligner": dev}, storage=storage)
        params = AutoAlignmentParams(mode="map", averages=averages, settle_time_s=settle,
                                     map_half_width_v=half_width, map_points=points)
        rows_seen: set[int] = set()
        row_every = max(1, points // 10)

        def on_sample(p: dict) -> None:
            if p["j"] not in rows_seen:
                rows_seen.add(p["j"])
                if p["j"] % row_every == 0:
                    print(f"  {time.strftime('%H:%M:%S')} t {p['t_s']:6.1f} s: row V "
                          f"{p['v_v']:6.2f} V", flush=True)

        ctx.live.subscribe("sample", on_sample)
        t0 = time.perf_counter()
        result = await AutoAlignmentTask().run_headless(ctx, params)
        print(f"took {time.perf_counter() - t0:.1f} s, stop_reason {result.stop_reason}")
        run_dir = storage.raw_path().parent
        print(f"saved in {run_dir}")
        await asyncio.sleep(1.2)  # let the device position report catch up
        end = dev._get_words_sync()
        _, text = await signal_at_rest(dev)
        print(f"end position (device report) H {dev._to_volts(end[0]):.2f} V / "
              f"V {dev._to_volts(end[1]):.2f} V, signal {text}")
    finally:
        await dev.shutdown()

    m = result.map
    grid = m.signal_a * 1e9
    print(f"valid points {np.isfinite(grid).sum()}/{grid.size}, "
          f"range {np.nanmin(grid):.2f} .. {np.nanmax(grid):.2f} nA, "
          f"start point {m.start_signal_a * 1e9:.2f} nA")
    sigma = "1.0" if points <= 41 else "2.0"
    subprocess.run([sys.executable, str(HERE / "plot_map_mpl.py"), str(run_dir),
                    str(run_dir / "map.png"), sigma], check=False)


asyncio.run(main())
