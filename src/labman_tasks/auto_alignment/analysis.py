import math

import numpy as np

from labman_tasks.auto_alignment.params import AutoAlignmentParams
from labman_tasks.auto_alignment.result import (
    KIND_MAP,
    AlignmentMap,
    AutoAlignmentRawData,
    AutoAlignmentResult,
    TrackSummary,
)


def analyze(raw: AutoAlignmentRawData, params: AutoAlignmentParams) -> AutoAlignmentResult:
    if raw.mode == "map":
        return AutoAlignmentResult(raw.mode, raw.stop_reason, raw.start_v, map=analyze_map(raw))
    return AutoAlignmentResult(raw.mode, raw.stop_reason, raw.start_v, track=summarize_track(raw))


def analyze_map(raw: AutoAlignmentRawData) -> AlignmentMap:
    h_axis, v_axis = raw.map_h_axis_v, raw.map_v_axis_v
    grid = np.full((v_axis.size, h_axis.size), np.nan)
    # Out-of-range readings are not measurements: the KNA reports them as 0 A, which
    # would look like a perfect dip. Leave those grid points unmeasured (NaN).
    mask = (raw.sample_kind == KIND_MAP) & raw.sample_in_range.astype(bool)
    grid[raw.sample_map_j[mask], raw.sample_map_i[mask]] = raw.sample_signal_a[mask]

    if np.all(np.isnan(grid)):
        nan_v, empty = np.array([np.nan, np.nan]), np.empty(0)
        return AlignmentMap(
            h_axis_v=h_axis, v_axis_v=v_axis, signal_a=grid, min_v=nan_v, min_signal_a=math.nan,
            local_min_v=nan_v, local_min_signal_a=math.nan, dip_found=False,
            start_signal_a=math.nan, radial_r_v=empty, radial_signal_a=empty,
            profile_shape="unknown",
        )

    jm, im = np.unravel_index(np.nanargmin(grid), grid.shape)
    js = int(np.argmin(np.abs(v_axis - raw.start_v[1])))
    is_ = int(np.argmin(np.abs(h_axis - raw.start_v[0])))
    jl, il = descend_to_local_minimum(grid, nearest_measured(grid, h_axis, v_axis, raw.start_v))
    local_min_v = np.array([h_axis[il], v_axis[jl]])
    # Downhill ending on the edge means the signal keeps falling out of the map:
    # there is no dip inside it, so describe the landscape around the start.
    dip_found = bool(0 < jl < v_axis.size - 1 and 0 < il < h_axis.size - 1)
    profile_centre = local_min_v if dip_found else np.asarray(raw.start_v, dtype=float)
    radial_r, radial_s = radial_profile(grid, h_axis, v_axis, profile_centre)

    return AlignmentMap(
        h_axis_v=h_axis,
        v_axis_v=v_axis,
        signal_a=grid,
        min_v=np.array([h_axis[im], v_axis[jm]]),
        min_signal_a=float(grid[jm, im]),
        local_min_v=local_min_v,
        local_min_signal_a=float(grid[jl, il]),
        dip_found=dip_found,
        start_signal_a=float(grid[js, is_]),
        radial_r_v=radial_r,
        radial_signal_a=radial_s,
        profile_shape=classify_profile(radial_s),
    )


def nearest_measured(
    grid: np.ndarray, h_axis: np.ndarray, v_axis: np.ndarray, position_v: np.ndarray
) -> tuple[int, int]:
    """Grid index of the measured point closest to `position_v` (grid not all NaN)."""
    hh, vv = np.meshgrid(h_axis, v_axis)
    r = np.hypot(hh - position_v[0], vv - position_v[1])
    r[np.isnan(grid)] = np.inf
    j, i = np.unravel_index(np.argmin(r), grid.shape)
    return int(j), int(i)


def descend_to_local_minimum(grid: np.ndarray, start: tuple[int, int]) -> tuple[int, int]:
    """Walk to the lowest 8-neighbour until none is lower (NaNs ignored).

    From a start inside the dip this ends at the dip bottom rather than at the
    lower background beyond the bright ring, which the global minimum may be.
    """
    j, i = start
    if np.isnan(grid[j, i]):
        return start
    rows, cols = grid.shape
    while True:
        best = (j, i)
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                nj, ni = j + dj, i + di
                if (0 <= nj < rows and 0 <= ni < cols and not np.isnan(grid[nj, ni])
                        and grid[nj, ni] < grid[best]):
                    best = (nj, ni)
        if best == (j, i):
            return best
        j, i = best


def radial_profile(
    grid: np.ndarray, h_axis: np.ndarray, v_axis: np.ndarray, centre_v: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Mean signal vs distance from `centre_v`, in rings one grid step wide.

    Ring k holds points with distance ≈ k·step, so ring 0 is the centre point
    alone — wider bins would average the dip bottom with its rising walls and
    hide the dip on coarse maps. Empty rings are dropped.
    """
    hh, vv = np.meshgrid(h_axis, v_axis)
    r = np.hypot(hh - centre_v[0], vv - centre_v[1])
    valid = ~np.isnan(grid)
    steps = [float(np.min(np.diff(axis))) for axis in (h_axis, v_axis) if axis.size > 1]
    step = min(steps) if steps else 1.0
    ring = np.rint(r[valid] / step).astype(int)
    values = grid[valid]
    radii, means = [], []
    for k in range(int(ring.max()) + 1):
        in_ring = ring == k
        if np.any(in_ring):
            radii.append(k * step)
            means.append(float(values[in_ring].mean()))
    return np.array(radii), np.array(means)


def classify_profile(radial_signal: np.ndarray, flat_tolerance: float = 0.1) -> str:
    """Advisory label for the radial profile around the dip bottom nearest the start.

    dip_in_ring: rises from the centre to a maximum and falls again before the edge.
    minimum:     lowest near the centre and rising towards the edge of the map.
    maximum:     highest at the centre.
    flat:        peak-to-peak below `flat_tolerance` of the maximum.
    """
    p = radial_signal[~np.isnan(radial_signal)]
    if p.size < 3:
        return "unknown"
    lo, hi = float(p.min()), float(p.max())
    if hi <= 0 or hi - lo <= flat_tolerance * abs(hi):
        return "flat"
    peak = int(np.argmax(p))
    if peak == 0:
        return "maximum"
    if peak < p.size - 1 and p[-1] < hi - 0.25 * (hi - lo) and p[0] < hi - 0.25 * (hi - lo):
        return "dip_in_ring"
    return "minimum"


def summarize_track(raw: AutoAlignmentRawData) -> TrackSummary:
    n = int(raw.cycle_t_s.size)
    duration = float(raw.sample_t_s[-1]) if raw.sample_t_s.size else 0.0
    if n == 0:
        return TrackSummary(0, duration, math.nan, raw.start_v.copy(), 0.0, raw.best_v,
                            raw.best_signal_a, math.nan)
    final = np.array([raw.cycle_next_h_v[-1], raw.cycle_next_v_v[-1]])
    return TrackSummary(
        n_cycles=n,
        duration_s=duration,
        in_dip_fraction=float(np.mean(raw.cycle_in_dip)),
        final_v=final,
        drift_v=float(np.hypot(*(final - raw.start_v))),
        best_v=raw.best_v,
        best_signal_a=raw.best_signal_a,
        median_centre_signal_a=float(np.median(raw.cycle_centre_signal_a)),
    )
