"""Check a serpentine map for scan-direction stripes (piezo hysteresis or lag).

For each interior row, compare it with the mean of the rows above and below (a smooth
map gives ~0). Rows scanned left-to-right vs right-to-left are summarised separately;
a consistent sign difference means direction-dependent readings. Also reports the
horizontal shift that best aligns L->R rows with R->L rows.

Usage: direction_check.py <run folder>
"""
import sys
from pathlib import Path

import numpy as np

from labman_core.persistence import load_dataclass_h5
from labman_tasks.auto_alignment.result import KIND_MAP, AutoAlignmentRawData


def main() -> None:
    run = Path(sys.argv[1])
    raw = load_dataclass_h5(run / "raw.h5", AutoAlignmentRawData)
    h, v = raw.map_h_axis_v, raw.map_v_axis_v
    grid = np.full((v.size, h.size), np.nan)
    mask = (raw.sample_kind == KIND_MAP) & raw.sample_in_range.astype(bool)
    grid[raw.sample_map_j[mask], raw.sample_map_i[mask]] = raw.sample_signal_a[mask] * 1e9

    # direction of each row from acquisition order
    direction = {}
    for j in range(v.size):
        sel = (raw.sample_kind == KIND_MAP) & (raw.sample_map_j == j)
        order = raw.sample_map_i[sel][np.argsort(raw.sample_t_s[sel])]
        direction[j] = "L->R" if order.size > 1 and order[-1] > order[0] else "R->L"

    deviations = {"L->R": [], "R->L": []}
    for j in range(1, v.size - 1):
        neighbours = np.nanmean([grid[j - 1], grid[j + 1]], axis=0)
        rel = (grid[j] - neighbours) / neighbours
        deviations[direction[j]].append(np.nanmedian(rel))
    for name, vals in deviations.items():
        vals = np.array(vals)
        print(f"{name}: {vals.size} rows, median row-vs-neighbours deviation "
              f"{100 * np.nanmedian(vals):+.1f} % (spread {100 * np.nanstd(vals):.1f} %)")

    # best horizontal shift (in grid steps) between L->R and R->L rows
    lr = np.array([grid[j] for j in range(v.size) if direction[j] == "L->R"])
    rl = np.array([grid[j] for j in range(v.size) if direction[j] == "R->L"])
    n = min(len(lr), len(rl))
    lr, rl = lr[:n], rl[:n]
    step = float(h[1] - h[0])
    best = None
    max_shift = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    for shift in range(-max_shift, max_shift + 1):
        a = np.roll(lr, shift, axis=1)[:, max_shift:-max_shift]
        b = rl[:, max_shift:-max_shift]
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 10:
            continue
        corr = np.corrcoef(a[ok], b[ok])[0, 1]
        print(f"  shift L->R rows by {shift:+d} steps ({shift * step:+.1f} V): corr {corr:.3f}")
        if best is None or corr > best[1]:
            best = (shift, corr)
    if best:
        print(f"best alignment: L->R rows shifted {best[0]:+d} steps ({best[0] * step:+.1f} V)")


main()
