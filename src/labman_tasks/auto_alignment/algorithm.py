"""Pure decision logic for the auto-alignment task. No I/O, no devices.

Tracking model: around the current centre c the stray-light signal is locally
s(x) ≈ s0 + g·x + (k/2)|x|². One cycle measures s(c) and the signal on a small
probe circle, fits the plane s ≈ c0 + g·x to the probe points, and estimates the
curvature k = 2 (c0 − s(c)) / <|x|²>.

- k > 0 with enough contrast: the centre sits in a dip, so take the Newton
  step −gain·g/k, clipped to max_step_v.
- Otherwise (on the bright ring, on a slope, flat, or detector out of range):
  hold. Following the gradient there could walk onto the ring or away from the
  fiber, so the loop never moves without a confirmed dip.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

STEP = "step"
HOLD_NOT_IN_DIP = "not_in_dip"
HOLD_OUT_OF_RANGE = "out_of_range"
HOLD_DEGENERATE = "degenerate"
LIMIT_EXCURSION = "max_excursion"
LIMIT_VOLTAGE = "voltage_limit"


@dataclass(frozen=True)
class ProbeCycle:
    centre_v: tuple[float, float]
    centre_signal_a: float
    probe_h_v: np.ndarray
    probe_v_v: np.ndarray
    probe_signal_a: np.ndarray
    all_in_range: bool = True


@dataclass(frozen=True)
class StepDecision:
    step_v: tuple[float, float]
    gradient_a_per_v: tuple[float, float]
    curvature_a_per_v2: float
    ring_mean_a: float
    in_dip: bool
    reason: str


@dataclass(frozen=True)
class MapPoint:
    i: int          # horizontal index
    j: int          # vertical index
    h_v: float
    v_v: float


def probe_angles(n: int, cycle: int = 0) -> np.ndarray:
    """n equally spaced angles; every other cycle is rotated by half a spacing."""
    offset = (cycle % 2) * math.pi / n
    return offset + 2.0 * math.pi * np.arange(n) / n


def probe_positions(
    centre_v: tuple[float, float], radius_v: float, angles: np.ndarray, max_voltage_v: float
) -> tuple[np.ndarray, np.ndarray]:
    h = np.clip(centre_v[0] + radius_v * np.cos(angles), 0.0, max_voltage_v)
    v = np.clip(centre_v[1] + radius_v * np.sin(angles), 0.0, max_voltage_v)
    return h, v


def decide_step(
    cycle: ProbeCycle, gain: float, max_step_v: float, min_contrast: float
) -> StepDecision:
    dx = np.asarray(cycle.probe_h_v, dtype=float) - cycle.centre_v[0]
    dy = np.asarray(cycle.probe_v_v, dtype=float) - cycle.centre_v[1]
    s = np.asarray(cycle.probe_signal_a, dtype=float)
    ring_mean = float(s.mean()) if s.size else math.nan

    design = np.column_stack([np.ones_like(dx), dx, dy])
    r2 = float(np.mean(dx**2 + dy**2)) if s.size else 0.0
    if s.size < 3 or r2 <= 0.0 or np.linalg.matrix_rank(design) < 3:
        return StepDecision((0.0, 0.0), (math.nan, math.nan), math.nan, ring_mean, False,
                            HOLD_DEGENERATE)

    (c0, gx, gy), *_ = np.linalg.lstsq(design, s, rcond=None)
    contrast = float(c0) - cycle.centre_signal_a
    curvature = 2.0 * contrast / r2
    scale = max(abs(float(c0)), abs(cycle.centre_signal_a), 1e-30)
    in_dip = contrast > min_contrast * scale
    gradient = (float(gx), float(gy))

    if not cycle.all_in_range:
        return StepDecision((0.0, 0.0), gradient, curvature, ring_mean, in_dip, HOLD_OUT_OF_RANGE)
    if not in_dip:
        return StepDecision((0.0, 0.0), gradient, curvature, ring_mean, False, HOLD_NOT_IN_DIP)

    sx = -gain * gradient[0] / curvature
    sy = -gain * gradient[1] / curvature
    norm = math.hypot(sx, sy)
    if norm > max_step_v:
        sx, sy = sx * max_step_v / norm, sy * max_step_v / norm
    return StepDecision((sx, sy), gradient, curvature, ring_mean, True, STEP)


def apply_limits(
    centre_v: tuple[float, float],
    step_v: tuple[float, float],
    start_v: tuple[float, float],
    max_excursion_v: float,
    max_voltage_v: float,
) -> tuple[tuple[float, float], str | None]:
    """Next centre after a step, or the unchanged centre plus the limit that blocked it."""
    if step_v == (0.0, 0.0):
        return centre_v, None
    target = (centre_v[0] + step_v[0], centre_v[1] + step_v[1])
    if math.hypot(target[0] - start_v[0], target[1] - start_v[1]) > max_excursion_v:
        return centre_v, LIMIT_EXCURSION
    if not (0.0 <= target[0] <= max_voltage_v and 0.0 <= target[1] <= max_voltage_v):
        return centre_v, LIMIT_VOLTAGE
    return target, None


def map_axes(
    centre_v: tuple[float, float], half_width_v: float, n: int
) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.linspace(centre_v[0] - half_width_v, centre_v[0] + half_width_v, n),
        np.linspace(centre_v[1] - half_width_v, centre_v[1] + half_width_v, n),
    )


def map_points(
    centre_v: tuple[float, float], half_width_v: float, n: int, max_voltage_v: float
) -> list[MapPoint]:
    """Serpentine raster (short moves between points); points outside [0, max] are skipped."""
    h_axis, v_axis = map_axes(centre_v, half_width_v, n)
    points: list[MapPoint] = []
    for j, v in enumerate(v_axis):
        columns = range(n) if j % 2 == 0 else range(n - 1, -1, -1)
        for i in columns:
            h = float(h_axis[i])
            if 0.0 <= h <= max_voltage_v and 0.0 <= v <= max_voltage_v:
                points.append(MapPoint(i, j, h, float(v)))
    return points
