"""Side-by-side comparison of two same-grid maps, each smoothed and shown on its own
colour scale, plus both normalised to their median and the ratio new/old.

Usage: compare_maps.py <old run> <new run> <out.png> [old label] [new label]
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
    old_run, new_run, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    old_label = sys.argv[4] if len(sys.argv) > 4 else old_run.name
    new_label = sys.argv[5] if len(sys.argv) > 5 else new_run.name
    old = load_dataclass_h5(old_run / "result.h5", AutoAlignmentResult)
    new = load_dataclass_h5(new_run / "result.h5", AutoAlignmentResult)
    h, v = old.map.h_axis_v, old.map.v_axis_v
    assert np.allclose(h, new.map.h_axis_v) and np.allclose(v, new.map.v_axis_v)

    a = gaussian_smooth(old.map.signal_a * 1e9, 1.0)
    b = gaussian_smooth(new.map.signal_a * 1e9, 1.0)
    a_norm, b_norm = a / np.nanmedian(a), b / np.nanmedian(b)
    step = float(h[1] - h[0])
    extent = (h[0] - step / 2, h[-1] + step / 2, v[0] - step / 2, v[-1] + step / 2)

    panels = [
        (a, f"{old_label}: signal (nA)", "viridis", None),
        (b, f"{new_label}: signal (nA)", "viridis", None),
        (b_norm - a_norm, "difference of median-normalised maps (new − old)", "RdBu_r",
         np.nanmax(np.abs(b_norm - a_norm))),
        (b / a, "ratio new / old", "magma", None),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 9.5), constrained_layout=True)
    for ax, (data, title, cmap, sym) in zip(axes.flat, panels, strict=True):
        kwargs = {"vmin": -sym, "vmax": sym} if sym else {}
        im = ax.imshow(data, origin="lower", extent=extent, cmap=cmap, **kwargs)
        ax.contour(h, v, data, levels=10, colors="white", linewidths=0.4, alpha=0.6)
        ax.plot(*old.start_v, "+", color="white", ms=14, mew=2.5)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("horizontal piezo (V)")
        ax.set_ylabel("vertical piezo (V)")
        fig.colorbar(im, ax=ax)
    fig.suptitle(f"{old_run.name} vs {new_run.name} (smoothed σ = 1 step)")
    fig.savefig(out, dpi=100)

    ratio = b / a
    print(f"wrote {out}")
    print(f"median signal: old {np.nanmedian(a):.1f} nA, new {np.nanmedian(b):.1f} nA; "
          f"ratio median {np.nanmedian(ratio):.2f}, range {np.nanmin(ratio):.2f} .. "
          f"{np.nanmax(ratio):.2f}")
    ok = np.isfinite(a_norm) & np.isfinite(b_norm)
    shape_corr = np.corrcoef(a_norm[ok], b_norm[ok])[0, 1]
    print(f"shape correlation (smoothed, normalised): {shape_corr:.3f}")
    for name, data in (("old", a), ("new", b)):
        j, i = np.unravel_index(np.nanargmin(data), data.shape)
        jm, im_ = np.unravel_index(np.nanargmax(data), data.shape)
        print(f"{name}: min {data[j, i]:.1f} nA at ({h[i]:.0f}, {v[j]:.0f}) V, "
              f"max {data[jm, im_]:.1f} nA at ({h[im_]:.0f}, {v[jm]:.0f}) V")


main()
