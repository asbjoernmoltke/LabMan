"""Static cross around the current KNA position: stray light vs coupled power.

At each point (returning to the centre in between), ramp there in 2.5 V steps, wait
`settle` seconds, then alternate KNA and PM100 readings for `samples` pairs. Saves
cross.csv, summary.json and cross.png into app/data/auto_alignment_cross/<timestamp>/.
The outputs return to the centre at the end, also on errors.

Usage: static_cross.py [offsets V, comma separated, default 5,10] [settle s] [samples]
"""
import asyncio
import csv
import json
import math
import statistics
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from labman_core.drivers import KinesisNanoTrak, ThorlabsPM100  # noqa: E402
from labman_core.storage import DEFAULT_DATA_ROOT, RunStorage, StorageOptions  # noqa: E402

OFFSETS = [float(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "5,10").split(",")]
SETTLE_S = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
SAMPLES = int(sys.argv[3]) if len(sys.argv) > 3 else 20
STEP_V = 2.5


async def ramp(kna: KinesisNanoTrak, current: tuple[float, float],
               target: tuple[float, float]) -> tuple[float, float]:
    n = max(1, math.ceil(max(abs(target[0] - current[0]), abs(target[1] - current[1])) / STEP_V))
    for k in range(1, n + 1):
        await kna.move_to_v(current[0] + (target[0] - current[0]) * k / n,
                            current[1] + (target[1] - current[1]) * k / n)
        await asyncio.sleep(0.1)
    return target


async def measure(kna: KinesisNanoTrak, pm: ThorlabsPM100) -> dict:
    stray, power = [], []
    for _ in range(SAMPLES):
        r = await kna.read_signal()
        if not math.isnan(r.signal_a) and r.in_range:
            stray.append(r.signal_a)
        power.append(await pm.read_power_w())
    return {
        "stray_nA": statistics.mean(stray) * 1e9 if stray else math.nan,
        "stray_sd_nA": statistics.stdev(stray) * 1e9 if len(stray) > 1 else math.nan,
        "power_mW": statistics.mean(power) * 1e3,
        "power_sd_mW": statistics.stdev(power) * 1e3 if len(power) > 1 else math.nan,
        "n_stray": len(stray),
    }


async def main() -> None:
    storage = RunStorage("auto_alignment_cross", StorageOptions(), DEFAULT_DATA_ROOT)
    run_dir = storage.raw_path().parent
    run_dir.mkdir(parents=True, exist_ok=True)
    kna = KinesisNanoTrak("57535374", name="aligner", max_voltage_v=150, set_voltage_range=True)
    pm = ThorlabsPM100("1931430", name="pm_out", wavelength_nm=1030.0)
    print(f"power meter at {await pm.get_wavelength_nm():.1f} nm", flush=True)
    centre = await kna.get_position_v()
    position = centre
    rows: list[dict] = []
    plan = []
    for axis in ("H", "V"):
        for off in OFFSETS:
            for sign in (+1, -1):
                d = (sign * off, 0.0) if axis == "H" else (0.0, sign * off)
                plan.append((axis, sign * off, (centre[0] + d[0], centre[1] + d[1])))
    print(f"centre H {centre[0]:.2f} / V {centre[1]:.2f} V; {len(plan)} points, settle "
          f"{SETTLE_S} s, {SAMPLES} sample pairs; saving to {run_dir}", flush=True)
    t0 = time.perf_counter()
    try:
        async def record(label: str, axis: str, offset: float, target: tuple[float, float]):
            nonlocal position
            position = await ramp(kna, position, target)
            await asyncio.sleep(SETTLE_S)
            print(f"  {time.strftime('%H:%M:%S')} measuring {label:>12s} at "
                  f"H {target[0]:.1f} / V {target[1]:.1f} V", flush=True)
            m = await measure(kna, pm)
            row = {"t_s": round(time.perf_counter() - t0, 2), "label": label, "axis": axis,
                   "offset_V": offset, "H_V": target[0], "V_V": target[1], **m}
            rows.append(row)
            print(f"      stray {m['stray_nA']:7.2f} ± {m['stray_sd_nA']:.2f} nA, "
                  f"power {m['power_mW']:7.4f} ± {m['power_sd_mW']:.4f} mW", flush=True)

        await record("centre", "-", 0.0, centre)
        for axis, offset, target in plan:
            await record(f"{axis} {offset:+.0f} V", axis, offset, target)
            await record("centre", "-", 0.0, centre)
    finally:
        try:
            position = await ramp(kna, position, centre)
        finally:
            await kna.shutdown()
            await pm.shutdown()
        print(f"returned to centre H {centre[0]:.2f} / V {centre[1]:.2f} V")

        if rows:
            with open(run_dir / "cross.csv", "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            (run_dir / "summary.json").write_text(json.dumps(
                {"centre_V": centre, "offsets_V": OFFSETS, "settle_s": SETTLE_S,
                 "samples": SAMPLES, "rows": rows}, indent=2))
            plot(rows, run_dir / "cross.png")
            print(f"saved cross.csv, summary.json, cross.png in {run_dir}")


def plot(rows: list[dict], out: Path) -> None:
    centres = [r for r in rows if r["label"] == "centre"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), constrained_layout=True)
    for axis, colour in (("H", "tab:blue"), ("V", "tab:orange")):
        pts = sorted([r for r in rows if r["axis"] == axis] +
                     [{**c, "offset_V": 0.0} for c in centres[:1]], key=lambda r: r["offset_V"])
        axes[0].errorbar([p["offset_V"] for p in pts], [p["power_mW"] for p in pts],
                         yerr=[p["power_sd_mW"] for p in pts], marker="o", color=colour,
                         label=f"{axis} axis")
        axes[1].errorbar([p["offset_V"] for p in pts], [p["stray_nA"] for p in pts],
                         yerr=[p["stray_sd_nA"] for p in pts], marker="o", color=colour,
                         label=f"{axis} axis")
    axes[0].set(xlabel="offset from centre (V)", ylabel="coupled power (mW)",
                title="coupled power")
    axes[1].set(xlabel="offset from centre (V)", ylabel="stray light (nA, relative)",
                title="KNA stray light")
    others = [r for r in rows if r["label"] != "centre"]
    sc = axes[2].scatter([r["stray_nA"] for r in others], [r["power_mW"] for r in others],
                         c=[r["t_s"] for r in others], cmap="viridis", label="off-centre")
    axes[2].scatter([c["stray_nA"] for c in centres], [c["power_mW"] for c in centres],
                    marker="x", color="red", label="centre (repeats)")
    for r in others:
        axes[2].annotate(r["label"], (r["stray_nA"], r["power_mW"]), fontsize=7,
                         xytext=(3, 3), textcoords="offset points")
    fig.colorbar(sc, ax=axes[2], label="time (s)")
    axes[2].set(xlabel="stray light (nA, relative)", ylabel="coupled power (mW)",
                title="coupling vs stray light")
    for ax in axes:
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.savefig(out, dpi=110)


asyncio.run(main())
