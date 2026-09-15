"""Summarise a saved map run: coarse text grid, where out-of-range points are, and the
signal of the in-range neighbours of those points.

Usage: inspect_run.py <run folder> [every Nth grid point]
"""
import sys
from pathlib import Path

import numpy as np

from labman_core.persistence import load_dataclass_h5
from labman_tasks.auto_alignment.result import KIND_MAP, AutoAlignmentRawData


def main() -> None:
    run = Path(sys.argv[1])
    every = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    raw = load_dataclass_h5(run / "raw.h5", AutoAlignmentRawData)
    h, v = raw.map_h_axis_v, raw.map_v_axis_v
    grid = np.full((v.size, h.size), np.nan)
    flag = np.zeros((v.size, h.size), bool)
    mask = raw.sample_kind == KIND_MAP
    j, i = raw.sample_map_j[mask], raw.sample_map_i[mask]
    grid[j, i] = raw.sample_signal_a[mask] * 1e9
    flag[j, i] = raw.sample_in_range[mask]

    out = ~flag
    print(f"out-of-range points: {int(out.sum())}/{grid.size}; their stored values "
          f"{np.nanmin(grid[out]) if out.any() else float('nan'):.2f} .. "
          f"{np.nanmax(grid[out]) if out.any() else float('nan'):.2f} nA")
    if out.any():
        oj, oi = np.nonzero(out)
        print(f"  H span {h[oi].min():.0f}..{h[oi].max():.0f} V, V span {v[oj].min():.0f}.."
              f"{v[oj].max():.0f} V")
        neigh = []
        for jj, ii in zip(oj, oi, strict=True):
            for dj in (-1, 0, 1):
                for di in (-1, 0, 1):
                    nj, ni = jj + dj, ii + di
                    if 0 <= nj < v.size and 0 <= ni < h.size and flag[nj, ni]:
                        neigh.append(grid[nj, ni])
        if neigh:
            print(f"  in-range neighbours: median {np.median(neigh):.1f} nA, "
                  f"max {np.max(neigh):.1f} nA")

    shown = np.where(flag, grid, np.nan)
    print(f"\nin-range signal (nA), every {every} grid points; '  ovr' = out of range")
    print("  V\\H " + "".join(f"{h[k]:6.0f}" for k in range(0, h.size, every)))
    for jj in reversed(range(0, v.size, every)):
        cells = []
        for k in range(0, h.size, every):
            cells.append("   ovr" if out[jj, k] else f"{shown[jj, k]:6.1f}")
        print(f"{v[jj]:6.0f} " + "".join(cells))


main()
