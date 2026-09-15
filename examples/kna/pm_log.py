"""Log the PM100USB once per second: print each reading and append it to a live CSV.

Usage: pm_log.py [duration s] [interval s]
Writes app/data/pm_log/<timestamp>/power_log.csv (flushed every line) and power_log.png.
"""
import asyncio
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from labman_core.drivers import ThorlabsPM100  # noqa: E402

DURATION_S = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
INTERVAL_S = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0


async def main() -> None:
    run_dir = Path("app/data/pm_log") / time.strftime("%Y%m%dT%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / "power_log.csv"
    pm = ThorlabsPM100("1931430", name="pm_out", wavelength_nm=1030.0)
    times, powers = [], []
    try:
        print(f"logging {pm.model} S/N {pm.serial_no} at {await pm.get_wavelength_nm():.0f} nm "
              f"every {INTERVAL_S} s for {DURATION_S} s -> {csv_path.resolve()}", flush=True)
        with open(csv_path, "w", buffering=1) as f:
            f.write("clock,t_s,power_mW\n")
            t0 = time.monotonic()
            k = 0
            while (elapsed := time.monotonic() - t0) < DURATION_S:
                power_mw = await pm.read_power_w() * 1e3
                clock = time.strftime("%H:%M:%S")
                f.write(f"{clock},{elapsed:.1f},{power_mw:.4f}\n")
                times.append(elapsed)
                powers.append(power_mw)
                print(f"{clock}  t {elapsed:6.1f} s  {power_mw:9.4f} mW", flush=True)
                k += 1
                await asyncio.sleep(max(0.0, t0 + k * INTERVAL_S - time.monotonic()))
    finally:
        await pm.shutdown()
    if powers:
        fig, ax = plt.subplots(figsize=(9, 4), constrained_layout=True)
        ax.plot(times, powers, ".-")
        ax.set(xlabel="time (s)", ylabel="power (mW, 1030 nm correction)",
               title=f"PM100USB log {run_dir.name}")
        ax.grid(alpha=0.3)
        fig.savefig(run_dir / "power_log.png", dpi=110)
        print(f"done: {len(powers)} readings, {min(powers):.4f} .. {max(powers):.4f} mW; "
              f"plot {run_dir / 'power_log.png'}")


asyncio.run(main())
