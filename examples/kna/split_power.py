"""Split two same-grid maps taken at laser power P1 and P2 = ratio x P1 into a
laser-proportional part and a power-independent background, per point:

    old = B + L,  new = B + ratio·L   ->   L = (new - old) / (ratio - 1),  B = old - L

Usage: split_power.py <old run> <new run> <ratio> <out.png>
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from plot_map_mpl import gaussian_smooth  # noqa: E402

from labman_core.persistence import load_dataclass_h5  # noqa: E402
from labman_tasks.auto_alignment.result import AutoAlignmentResult  # noqa: E402


def main() -> None:
    old_run, new_run = Path(sys.argv[1]), Path(sys.argv[2])
    ratio, out = float(sys.argv[3]), Path(sys.argv[4])
    old = load_dataclass_h5(old_run / "result.h5", AutoAlignmentResult)
    new = load_dataclass_h5(new_run / "result.h5", AutoAlignmentResult)
    assert np.allclose(old.map.h_axis_v, new.map.h_axis_v)
    assert np.allclose(old.map.v_axis_v, new.map.v_axis_v)

    a, b = old.map.signal_a * 1e9, new.map.signal_a * 1e9
    laser = (b - a) / (ratio - 1)
    background = a - laser
    print(f"per-point ratio new/old: median {np.nanmedian(b / a):.2f}, "
          f"range {np.nanmin(b / a):.2f} .. {np.nanmax(b / a):.2f}")
    print(f"laser-proportional part at old power: median {np.nanmedian(laser):.2f} nA, "
          f"range {np.nanmin(laser):.2f} .. {np.nanmax(laser):.2f} nA")
    print(f"background: median {np.nanmedian(background):.2f} nA, "
          f"range {np.nanmin(background):.2f} .. {np.nanmax(background):.2f} nA")

    h, v = old.map.h_axis_v, old.map.v_axis_v
    extent = (h[0] - 0.25, h[-1] + 0.25, v[0] - 0.25, v[-1] + 0.25)
    panels = [
        (a, "old power: total (smoothed)"),
        (b, f"new power (x{ratio:g}): total (smoothed)"),
        (laser, "laser-proportional part, at old power (smoothed)"),
        (background, "power-independent background (smoothed)"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 9.5), constrained_layout=True)
    for ax, (data, title) in zip(axes.flat, panels, strict=True):
        smooth = gaussian_smooth(data, 2.0)
        im = ax.imshow(smooth, origin="lower", extent=extent, cmap="viridis")
        ax.contour(h, v, smooth, levels=10, colors="white", linewidths=0.5, alpha=0.7)
        ax.plot(*old.start_v, "+", color="white", ms=14, mew=2.5)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("horizontal piezo (V)")
        ax.set_ylabel("vertical piezo (V)")
        fig.colorbar(im, ax=ax, label="nA (relative scale)")
    fig.suptitle(f"Laser power split: {old_run.name} vs {new_run.name}")
    fig.savefig(out, dpi=100)
    print(f"wrote {out}")


main()
