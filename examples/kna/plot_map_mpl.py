"""Matplotlib view of a saved auto-alignment map: raw grid and a lightly smoothed grid
with contours, start (white cross) and lowest smoothed point (red dot).

Usage: plot_map_mpl.py <run folder> <out.png> [smoothing sigma in grid steps, default 1.5]
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from labman_core.persistence import load_dataclass_h5  # noqa: E402
from labman_tasks.auto_alignment.result import AutoAlignmentResult  # noqa: E402


def gaussian_smooth(grid: np.ndarray, sigma: float) -> np.ndarray:
    """NaN-aware separable Gaussian smoothing (numpy only)."""
    radius = max(1, int(round(3 * sigma)))
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    valid = np.isfinite(grid).astype(float)
    filled = np.nan_to_num(grid)

    def convolve(a: np.ndarray, axis: int) -> np.ndarray:
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        a = np.pad(a, pad, mode="constant")
        return np.apply_along_axis(lambda r: np.convolve(r, kernel, mode="valid"), axis, a)

    num = convolve(convolve(filled * valid, 0), 1)
    den = convolve(convolve(valid, 0), 1)
    return num / np.where(den > 0, den, np.nan)


def main() -> None:
    run, out = Path(sys.argv[1]), Path(sys.argv[2])
    sigma = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5
    result = load_dataclass_h5(run / "result.h5", AutoAlignmentResult)
    m = result.map
    grid = m.signal_a * 1e9
    smooth = gaussian_smooth(grid, sigma)
    h, v = m.h_axis_v, m.v_axis_v
    extent = (h[0] - (h[1] - h[0]) / 2, h[-1] + (h[1] - h[0]) / 2,
              v[0] - (v[1] - v[0]) / 2, v[-1] + (v[1] - v[0]) / 2)
    js, is_ = np.unravel_index(np.nanargmin(smooth), smooth.shape)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), constrained_layout=True)
    for ax, data, title in ((axes[0], grid, "raw (1 reading per point)"),
                            (axes[1], smooth, f"smoothed (Gaussian σ = {sigma} steps)")):
        im = ax.imshow(data, origin="lower", extent=extent, cmap="viridis", aspect="equal")
        if data is smooth:
            ax.contour(h, v, smooth, levels=12, colors="white", linewidths=0.6, alpha=0.7)
            lowest = f"lowest smoothed {smooth[js, is_]:.2f} nA at ({h[is_]:.1f}, {v[js]:.1f}) V"
            ax.plot(h[is_], v[js], "o", color="red", ms=7, label=lowest)
        ax.plot(*result.start_v, "+", color="white", ms=14, mew=2.5,
                label=f"start ({result.start_v[0]:.1f}, {result.start_v[1]:.1f}) V")
        ax.set_xlabel("horizontal piezo (V)")
        ax.set_ylabel("vertical piezo (V)")
        ax.set_title(title)
        ax.legend(loc="upper left", fontsize=8, framealpha=0.8)
        fig.colorbar(im, ax=ax, label="stray-light signal (nA, relative scale)")
    fig.suptitle(f"KNA-IR stray-light map — {run.name}")
    fig.savefig(out, dpi=110)
    print(f"wrote {out}")
    print(f"smoothed range {np.nanmin(smooth):.2f} .. {np.nanmax(smooth):.2f} nA; lowest at "
          f"({h[is_]:.1f}, {v[js]:.1f}) V")
    residual = grid - smooth
    print(f"point-to-point scatter (raw - smoothed) sd {np.nanstd(residual):.2f} nA")


if __name__ == "__main__":
    main()
