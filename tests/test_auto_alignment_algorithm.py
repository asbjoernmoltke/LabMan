import math

import numpy as np
import pytest

from labman_tasks.auto_alignment import algorithm as alg


def _bowl(opt=(75.0, 75.0), k=2.0, s0=1.0):
    return lambda h, v: s0 + 0.5 * k * ((h - opt[0]) ** 2 + (v - opt[1]) ** 2)


def _donut(opt=(75.0, 75.0), radius=1.0, background=1e-9, peak=1e-6):
    def signal(h, v):
        x2 = ((h - opt[0]) ** 2 + (v - opt[1]) ** 2) / radius**2
        return background + peak * x2 * math.exp(1.0 - x2)
    return signal


def _cycle(signal, centre, radius=0.2, n=8, in_range=True, max_v=150.0):
    hs, vs = alg.probe_positions(centre, radius, alg.probe_angles(n), max_v)
    ring = np.array([signal(h, v) for h, v in zip(hs, vs, strict=True)])
    return alg.ProbeCycle(centre, signal(*centre), hs, vs, ring, in_range)


# ----- decide_step -----


def test_full_newton_step_lands_on_bowl_minimum() -> None:
    d = alg.decide_step(_cycle(_bowl(k=2.0), (75.1, 74.95)), gain=1.0, max_step_v=1.0,
                        min_contrast=0.01)
    assert d.reason == alg.STEP
    assert d.in_dip
    assert d.step_v == pytest.approx((-0.1, 0.05), abs=1e-9)
    assert d.curvature_a_per_v2 == pytest.approx(2.0)
    assert d.gradient_a_per_v == pytest.approx((0.2, -0.1), abs=1e-9)


def test_gain_scales_and_max_step_clips() -> None:
    half = alg.decide_step(_cycle(_bowl(), (75.1, 75.0)), gain=0.5, max_step_v=1.0,
                           min_contrast=0.01)
    assert half.step_v == pytest.approx((-0.05, 0.0), abs=1e-9)

    # Far out on the bowl the centre is only ~1% below its probe ring, so use a
    # low contrast threshold to reach the clipping branch.
    clipped = alg.decide_step(_cycle(_bowl(), (77.0, 75.0)), gain=1.0, max_step_v=0.1,
                              min_contrast=0.001)
    assert math.hypot(*clipped.step_v) == pytest.approx(0.1)
    assert clipped.step_v[0] < 0


def test_steps_toward_centre_inside_donut_dip() -> None:
    d = alg.decide_step(_cycle(_donut(), (75.3, 75.0), radius=0.1), gain=0.5, max_step_v=1.0,
                        min_contrast=0.05)
    assert d.in_dip
    assert d.step_v[0] < 0
    assert abs(d.step_v[1]) < 1e-9


def test_holds_on_the_bright_ring() -> None:
    d = alg.decide_step(_cycle(_donut(), (76.0, 75.0), radius=0.1), gain=0.5, max_step_v=1.0,
                        min_contrast=0.05)
    assert d.reason == alg.HOLD_NOT_IN_DIP
    assert not d.in_dip
    assert d.step_v == (0.0, 0.0)


def test_holds_on_a_flat_signal() -> None:
    d = alg.decide_step(_cycle(lambda h, v: 1e-7, (75.0, 75.0)), gain=0.5, max_step_v=1.0,
                        min_contrast=0.05)
    assert d.reason == alg.HOLD_NOT_IN_DIP
    assert d.step_v == (0.0, 0.0)


def test_holds_when_detector_out_of_range() -> None:
    d = alg.decide_step(_cycle(_bowl(), (75.1, 75.0), in_range=False), gain=0.5,
                        max_step_v=1.0, min_contrast=0.01)
    assert d.reason == alg.HOLD_OUT_OF_RANGE
    assert d.step_v == (0.0, 0.0)


def test_holds_on_degenerate_probe_geometry() -> None:
    same = np.full(4, 75.0)
    cycle = alg.ProbeCycle((75.0, 75.0), 1.0, same, same, np.ones(4))
    d = alg.decide_step(cycle, gain=0.5, max_step_v=1.0, min_contrast=0.01)
    assert d.reason == alg.HOLD_DEGENERATE
    assert d.step_v == (0.0, 0.0)


def test_uses_actual_positions_when_probes_are_clipped_at_zero() -> None:
    signal = _bowl(opt=(0.3, 0.3))
    d = alg.decide_step(_cycle(signal, (0.05, 0.05), radius=0.1), gain=1.0, max_step_v=1.0,
                        min_contrast=0.001)
    assert d.reason == alg.STEP
    assert d.step_v[0] > 0 and d.step_v[1] > 0


# ----- geometry helpers -----


def test_probe_angles_rotate_every_other_cycle() -> None:
    a0 = alg.probe_angles(4, cycle=0)
    a1 = alg.probe_angles(4, cycle=1)
    assert a0 == pytest.approx([0, math.pi / 2, math.pi, 3 * math.pi / 2])
    assert a1 == pytest.approx(a0 + math.pi / 4)
    assert alg.probe_angles(4, cycle=2) == pytest.approx(a0)


def test_probe_positions_are_clipped_to_voltage_range() -> None:
    h, v = alg.probe_positions((149.95, 0.05), 0.1, alg.probe_angles(4), 150.0)
    assert h.max() <= 150.0 and v.min() >= 0.0


def test_apply_limits() -> None:
    start = (75.0, 75.0)
    assert alg.apply_limits(start, (0.0, 0.0), start, 1.0, 150.0) == (start, None)
    assert alg.apply_limits(start, (0.1, 0.0), start, 1.0, 150.0) == ((75.1, 75.0), None)
    assert alg.apply_limits((75.9, 75.0), (0.2, 0.0), start, 1.0, 150.0) == (
        (75.9, 75.0), alg.LIMIT_EXCURSION)
    assert alg.apply_limits((149.95, 75.0), (0.1, 0.0), (149.9, 75.0), 1.0, 150.0) == (
        (149.95, 75.0), alg.LIMIT_VOLTAGE)


def test_map_points_serpentine_and_skip_out_of_range() -> None:
    points = alg.map_points((75.0, 75.0), 1.0, 3, 150.0)
    assert [(p.i, p.j) for p in points] == [
        (0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (0, 1), (0, 2), (1, 2), (2, 2)
    ]
    assert (points[0].h_v, points[0].v_v) == (74.0, 74.0)

    near_zero = alg.map_points((0.5, 75.0), 1.0, 3, 150.0)
    assert all(p.h_v >= 0 for p in near_zero)
    assert len(near_zero) == 6
