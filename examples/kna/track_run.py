"""Auto-alignment tracking on the KNA with the PM100 logged alongside (read-only check).

Runs the task's track mode (run_headless, so raw/result/params/meta are saved as
usual). A background task logs coupled power every 0.25 s; the power meter never
influences the tracker. Saves power_log.csv and track.png into the run folder.

Usage: track_run.py [duration s] [probe radius V] [min contrast] [averages]
       [settle s] [max excursion V] [max step V]
"""
import asyncio
import csv
import logging
import math
import sys
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from labman_core.context import TaskContext  # noqa: E402
from labman_core.drivers import KinesisNanoTrak, ThorlabsPM100  # noqa: E402
from labman_core.storage import DEFAULT_DATA_ROOT, RunStorage, StorageOptions  # noqa: E402
from labman_tasks.auto_alignment.params import AutoAlignmentParams  # noqa: E402
from labman_tasks.auto_alignment.task import AutoAlignmentTask  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

args = sys.argv[1:]
DURATION_S = float(args[0]) if len(args) > 0 else 180.0
RADIUS_V = float(args[1]) if len(args) > 1 else 6.0
MIN_CONTRAST = float(args[2]) if len(args) > 2 else 0.015
AVERAGES = int(args[3]) if len(args) > 3 else 5
SETTLE_S = float(args[4]) if len(args) > 4 else 0.2
MAX_EXCURSION_V = float(args[5]) if len(args) > 5 else 15.0
MAX_STEP_V = float(args[6]) if len(args) > 6 else 1.0


async def main() -> None:
    kna = KinesisNanoTrak("57535374", name="aligner", max_voltage_v=150, set_voltage_range=True)
    pm = ThorlabsPM100("1931430", name="pm_out", wavelength_nm=1030.0)
    storage = RunStorage("auto_alignment", StorageOptions(), DEFAULT_DATA_ROOT)
    ctx = TaskContext(devices={"aligner": kna}, storage=storage)
    params = AutoAlignmentParams(
        mode="track", probe_radius_v=RADIUS_V, probe_points=8, averages=AVERAGES,
        settle_time_s=SETTLE_S, gain=0.5, max_step_v=MAX_STEP_V, min_contrast=MIN_CONTRAST,
        max_excursion_v=MAX_EXCURSION_V, duration_s=DURATION_S,
    )
    power_log: list[tuple[float, float]] = []
    t0 = time.monotonic()
    stop_logging = asyncio.Event()

    async def log_power() -> None:
        while not stop_logging.is_set():
            try:
                power_log.append((time.monotonic() - t0, await pm.read_power_w()))
            except Exception as e:  # noqa: BLE001
                print(f"  power meter read failed: {e}", flush=True)
            await asyncio.sleep(0.25)

    def on_cycle(p: dict) -> None:
        centre = p.get("centre_v") or (p.get("centre_h_v"), p.get("centre_v_v"))
        nxt = p.get("next_v") or (p.get("next_h_v"), p.get("next_v_v"))
        last_power = power_log[-1][1] * 1e3 if power_log else math.nan
        signal = p.get("centre_signal_a")
        ring = p.get("ring_mean_a")
        contrast = ((ring - signal) / ring * 100) if (ring and signal) else math.nan
        print(f"  cycle {p.get('cycle', '?'):>3} t {time.monotonic() - t0:6.1f} s  centre "
              f"({float(centre[0]):6.2f}, {float(centre[1]):6.2f}) V  stray "
              f"{(signal or math.nan) * 1e9:6.2f} nA  contrast {contrast:+5.2f} %  "
              f"{p.get('reason', '?'):12s} -> ({float(nxt[0]):6.2f}, {float(nxt[1]):6.2f})  "
              f"power {last_power:.3f} mW", flush=True)

    ctx.live.subscribe("cycle", on_cycle)
    start = await kna.get_position_v()
    print(f"start ({start[0]:.2f}, {start[1]:.2f}) V; probe radius {RADIUS_V} V, averages "
          f"{AVERAGES}, settle {SETTLE_S} s, min contrast {MIN_CONTRAST:.3f}, max step "
          f"{MAX_STEP_V} V, max excursion {MAX_EXCURSION_V} V, duration {DURATION_S} s",
          flush=True)
    logger_task = asyncio.create_task(log_power())
    result = None
    try:
        result = await AutoAlignmentTask().run_headless(ctx, params)
    finally:
        stop_logging.set()
        await logger_task
        await asyncio.sleep(1.2)
        end_words = kna._get_words_sync()
        end_power = await pm.read_power_w()
        await kna.shutdown()
        await pm.shutdown()
        run_dir = storage.raw_path().parent
        print(f"end position (device report) ({kna._to_volts(end_words[0]):.2f}, "
              f"{kna._to_volts(end_words[1]):.2f}) V, power {end_power * 1e3:.3f} mW")
        if run_dir.exists():
            with open(run_dir / "power_log.csv", "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["t_s", "power_W"])
                writer.writerows(power_log)
            print(f"saved in {run_dir}")

    if result is None:
        return
    t = result.track
    print(f"stop reason {result.stop_reason}; cycles {t.n_cycles}, in-dip fraction "
          f"{t.in_dip_fraction:.2f}, final ({t.final_v[0]:.2f}, {t.final_v[1]:.2f}) V, drift "
          f"{t.drift_v:.2f} V, best ({t.best_v[0]:.2f}, {t.best_v[1]:.2f}) V")
    plot(run_dir, power_log, t0)


def plot(run_dir, power_log, t0) -> None:
    from labman_core.persistence import load_dataclass_h5
    from labman_tasks.auto_alignment.result import CYCLE_REASONS, AutoAlignmentRawData

    raw = load_dataclass_h5(run_dir / "raw.h5", AutoAlignmentRawData)
    pt = np.array([p[0] for p in power_log])
    pw = np.array([p[1] for p in power_log]) * 1e3
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), constrained_layout=True)
    axes[0].plot(pt, pw, lw=0.8, color="tab:green")
    axes[0].set(xlabel="time (s, from script start)", ylabel="coupled power (mW)",
                title="coupled power (logged, not used by the tracker)")
    ax2 = axes[0].twinx()
    ax2.plot(raw.cycle_t_s, raw.cycle_centre_signal_a * 1e9, "o-", ms=3, color="tab:purple")
    ax2.set_ylabel("centre stray light (nA)", color="tab:purple")

    axes[1].plot(raw.cycle_t_s, raw.cycle_centre_h_v, "o-", ms=3, label="H centre")
    axes[1].plot(raw.cycle_t_s, raw.cycle_centre_v_v, "o-", ms=3, label="V centre")
    stepped = raw.cycle_reason_code == CYCLE_REASONS.index("step")
    axes[1].scatter(raw.cycle_t_s[stepped], raw.cycle_centre_h_v[stepped], marker="^",
                    color="k", s=14, zorder=3, label="step taken")
    axes[1].set(xlabel="time (s, run)", ylabel="piezo (V)", title="centre position per cycle")
    axes[1].legend(fontsize=8)

    sc = axes[2].scatter(raw.sample_h_v, raw.sample_v_v, c=raw.sample_signal_a * 1e9, s=8,
                         cmap="viridis")
    axes[2].plot(raw.cycle_centre_h_v, raw.cycle_centre_v_v, "-", color="red", lw=1.2,
                 label="centre path")
    axes[2].plot(*raw.start_v, "+", color="black", ms=12, mew=2, label="start")
    fig.colorbar(sc, ax=axes[2], label="stray light (nA)")
    axes[2].set(xlabel="H (V)", ylabel="V (V)", title="probe samples and centre path",
                aspect="equal")
    axes[2].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.savefig(run_dir / "track.png", dpi=110)
    print(f"wrote {run_dir / 'track.png'}")


asyncio.run(main())
