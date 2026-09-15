import math

import numpy as np
import pytest

from labman_tasks.auto_alignment.algorithm import map_axes
from labman_tasks.auto_alignment.analysis import analyze, classify_profile
from labman_tasks.auto_alignment.params import AutoAlignmentParams
from labman_tasks.auto_alignment.result import KIND_CENTRE, KIND_MAP, AutoAlignmentRawData

START = (75.0, 75.0)
E = np.empty(0)


def _raw(**overrides) -> AutoAlignmentRawData:
    fields = {
        "mode": "map", "stop_reason": "completed", "max_voltage_v": 150.0,
        "start_v": np.array(START), "best_v": np.array(START), "best_signal_a": math.nan,
        "sample_t_s": E, "sample_h_v": E, "sample_v_v": E, "sample_signal_a": E,
        "sample_in_range": E.astype(bool), "sample_kind": E.astype(int),
        "sample_cycle": E.astype(int), "sample_map_i": E.astype(int),
        "sample_map_j": E.astype(int), "map_h_axis_v": E, "map_v_axis_v": E,
        "cycle_t_s": E, "cycle_centre_h_v": E, "cycle_centre_v_v": E,
        "cycle_centre_signal_a": E, "cycle_ring_mean_a": E, "cycle_gradient_h_a_per_v": E,
        "cycle_gradient_v_a_per_v": E, "cycle_curvature_a_per_v2": E,
        "cycle_in_dip": E.astype(bool), "cycle_reason_code": E.astype(int),
        "cycle_next_h_v": E, "cycle_next_v_v": E,
    }
    fields.update(overrides)
    return AutoAlignmentRawData(**fields)


def _map_raw(signal, n=15, half_width=2.0, skip=(), start=START) -> AutoAlignmentRawData:
    h_axis, v_axis = map_axes(start, half_width, n)
    rows = [(i, j, h_axis[i], v_axis[j], signal(h_axis[i], v_axis[j]))
            for j in range(n) for i in range(n) if (i, j) not in skip]
    i, j, h, v, s = (np.array(c) for c in zip(*rows, strict=True))
    size = s.size
    return _raw(
        start_v=np.array(start),
        sample_t_s=np.arange(size, dtype=float), sample_h_v=h, sample_v_v=v, sample_signal_a=s,
        sample_in_range=np.ones(size, bool), sample_kind=np.full(size, KIND_MAP),
        sample_cycle=np.full(size, -1), sample_map_i=i.astype(int), sample_map_j=j.astype(int),
        map_h_axis_v=h_axis, map_v_axis_v=v_axis,
    )


def _radial(fn):
    return lambda h, v: fn(math.hypot(h - START[0], v - START[1]))


def test_donut_map_is_classified_as_dip_in_ring() -> None:
    donut = _radial(lambda r: 1e-9 + 1e-6 * r**2 * math.exp(1 - r**2))
    result = analyze(_map_raw(donut), AutoAlignmentParams())
    m = result.map
    assert m.profile_shape == "dip_in_ring"
    assert m.signal_a.shape == (15, 15)
    assert m.min_v == pytest.approx(START)
    assert m.start_signal_a == pytest.approx(1e-9)
    assert m.radial_r_v.size == m.radial_signal_a.size > 0
    assert result.track is None


def test_coarse_offset_map_reports_nearest_dip_not_background_beyond_ring() -> None:
    """Regression: a 9x9 map ±2 V around a slightly off-optimum start.

    The lowest grid value is background out past the ring (a corner); the dip the
    user is aligning to is the local minimum reached from the start.
    """
    def donut(h, v):
        r = math.hypot(h - 75.0, v - 75.0)
        return 2e-9 + 5e-7 * r**2 * math.exp(1 - r**2)

    m = analyze(_map_raw(donut, n=9, start=(75.3, 74.8)), AutoAlignmentParams()).map

    assert m.dip_found
    assert math.hypot(m.local_min_v[0] - 75.0, m.local_min_v[1] - 75.0) < 0.5
    assert math.hypot(m.min_v[0] - 75.0, m.min_v[1] - 75.0) > 2.0
    assert m.local_min_signal_a < m.start_signal_a
    assert m.profile_shape == "dip_in_ring"


def test_descent_stops_at_dip_bottom_not_lower_background_beyond_ring() -> None:
    from labman_tasks.auto_alignment.analysis import descend_to_local_minimum

    grid = np.array([
        [0.0, 5.0, 5.0, 5.0, 0.0],
        [5.0, 3.0, 2.0, 3.0, 5.0],
        [5.0, 2.0, 1.0, 2.0, 5.0],
        [5.0, 3.0, 2.0, np.nan, 5.0],
        [0.0, 5.0, 5.0, 5.0, 0.0],
    ])
    assert descend_to_local_minimum(grid, (2, 2)) == (2, 2)  # already at the bottom
    assert descend_to_local_minimum(grid, (1, 2)) == (2, 2)  # walks in, not out to a 0 corner
    assert descend_to_local_minimum(grid, (0, 1)) == (0, 0)  # outside the ring: goes outward


def test_bowl_map_is_classified_as_minimum() -> None:
    bowl = _radial(lambda r: 1e-7 * r**2)
    assert analyze(_map_raw(bowl), AutoAlignmentParams()).map.profile_shape == "minimum"


def test_peaked_map_is_classified_as_maximum() -> None:
    peak = _radial(lambda r: 1e-6 * math.exp(-(r**2)))
    m = analyze(_map_raw(peak), AutoAlignmentParams()).map
    assert not m.dip_found  # downhill from the peak runs off the map
    assert m.profile_shape == "maximum"


def test_flat_map_is_classified_as_flat() -> None:
    assert analyze(_map_raw(lambda h, v: 5e-8), AutoAlignmentParams()).map.profile_shape == "flat"


def test_unmeasured_points_are_nan() -> None:
    m = analyze(_map_raw(_radial(lambda r: r**2), n=5, skip={(0, 0)}), AutoAlignmentParams()).map
    assert math.isnan(m.signal_a[0, 0])
    assert np.isnan(m.signal_a).sum() == 1


def test_out_of_range_zeros_are_not_a_dip() -> None:
    """Regression (KNA-IR 2026-09-15): out-of-range readings come back as 0 A.

    They must be left unmeasured, not taken as the dip bottom.
    """
    bowl = _radial(lambda r: 1e-9 + 1e-10 * r**2)
    raw = _map_raw(bowl, n=9, start=(76.0, 75.0))
    # Blank the points around the start but not the true bottom at START (1 V away).
    near_start = np.hypot(raw.sample_h_v - 76.0, raw.sample_v_v - 75.0) < 0.8
    raw.sample_signal_a[near_start] = 0.0
    raw.sample_in_range[near_start] = False

    m = analyze(raw, AutoAlignmentParams()).map

    assert np.isnan(m.signal_a).sum() == int(near_start.sum())
    assert m.min_signal_a > 0
    assert m.local_min_signal_a > 0
    assert m.dip_found
    assert m.local_min_v == pytest.approx(START)


def test_classify_profile_needs_three_points() -> None:
    assert classify_profile(np.array([1.0, 2.0])) == "unknown"


def test_track_summary() -> None:
    raw = _raw(
        mode="track", stop_reason="stopped", best_v=np.array([75.1, 74.9]), best_signal_a=2e-9,
        sample_t_s=np.array([0.0, 1.0, 2.5]), sample_kind=np.full(3, KIND_CENTRE),
        cycle_t_s=np.array([0.5, 1.5, 2.5]),
        cycle_centre_h_v=np.array([75.0, 75.1, 75.1]),
        cycle_centre_v_v=np.array([75.0, 74.9, 74.9]),
        cycle_centre_signal_a=np.array([3e-9, 2e-9, 4e-9]),
        cycle_in_dip=np.array([True, False, True]),
        cycle_next_h_v=np.array([75.1, 75.1, 75.3]),
        cycle_next_v_v=np.array([74.9, 74.9, 75.0]),
    )
    t = analyze(raw, AutoAlignmentParams(mode="track")).track
    assert t.n_cycles == 3
    assert t.duration_s == 2.5
    assert t.in_dip_fraction == pytest.approx(2 / 3)
    assert t.final_v == pytest.approx([75.3, 75.0])
    assert t.drift_v == pytest.approx(0.3)
    assert t.median_centre_signal_a == pytest.approx(3e-9)
    assert t.best_v == pytest.approx([75.1, 74.9])


def test_track_summary_without_cycles() -> None:
    t = analyze(_raw(mode="track"), AutoAlignmentParams(mode="track")).track
    assert t.n_cycles == 0
    assert t.drift_v == 0.0
    assert math.isnan(t.in_dip_fraction)
