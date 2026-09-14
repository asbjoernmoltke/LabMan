import asyncio
import math
import time
from dataclasses import dataclass, field

import numpy as np

from labman_core.context import TaskContext
from labman_core.devices import Aligner
from labman_tasks.auto_alignment import algorithm, safety
from labman_tasks.auto_alignment.params import AutoAlignmentParams
from labman_tasks.auto_alignment.result import (
    CYCLE_REASONS,
    KIND_CENTRE,
    KIND_MAP,
    KIND_PROBE,
    AutoAlignmentRawData,
)

_KIND_NAMES = {KIND_CENTRE: "centre", KIND_PROBE: "probe", KIND_MAP: "map"}


async def acquire(ctx: TaskContext, params: AutoAlignmentParams) -> AutoAlignmentRawData:
    """Map or track. Returns normally on completion, duration, a limit, or `ctx.request_stop()`.

    The hardware always ends latched: tracking holds the best confirmed centre,
    a map returns to where it started.
    """
    aligner: Aligner = ctx.devices["aligner"]  # type: ignore[assignment]
    await aligner.latch()  # the software loop owns the position from here
    start = await aligner.get_position_v()
    run = _Run(start_v=start, best_v=start, t0=time.monotonic())
    ctx.live.publish("start", {"mode": params.mode, "start_v": start})

    try:
        if params.mode == "map":
            await _run_map(ctx, aligner, params, run)
        else:
            await _run_track(ctx, aligner, params, run)
    finally:
        hold_at = run.best_v if params.mode == "track" else start
        run.best_v = hold_at
        await safety.to_safe_state(ctx.devices, hold_at=hold_at)

    return run.to_raw(params.mode, aligner.max_voltage_v)


async def _run_map(
    ctx: TaskContext, aligner: Aligner, params: AutoAlignmentParams, run: "_Run"
) -> None:
    run.map_axes = algorithm.map_axes(run.start_v, params.map_half_width_v, params.map_points)
    points = algorithm.map_points(
        run.start_v, params.map_half_width_v, params.map_points, aligner.max_voltage_v
    )
    for k, point in enumerate(points):
        if ctx.stop_requested:
            run.stop_reason = "stopped"
            return
        signal, in_range = await _measure(aligner, point.h_v, point.v_v, params)
        run.add_sample(ctx, point.h_v, point.v_v, signal, in_range, KIND_MAP, -1, point.i, point.j)
        ctx.progress.report((k + 1) / len(points), f"Map point {k + 1}/{len(points)}")
    run.stop_reason = "completed"


async def _run_track(
    ctx: TaskContext, aligner: Aligner, params: AutoAlignmentParams, run: "_Run"
) -> None:
    centre = run.start_v
    cycle = 0
    while True:
        elapsed = time.monotonic() - run.t0
        if ctx.stop_requested:
            run.stop_reason = "stopped"
            return
        if params.duration_s is not None and elapsed >= params.duration_s:
            run.stop_reason = "duration"
            return

        centre_signal, centre_ok = await _measure(aligner, *centre, params)
        run.add_sample(ctx, *centre, centre_signal, centre_ok, KIND_CENTRE, cycle, -1, -1)

        angles = algorithm.probe_angles(params.probe_points, cycle)
        hs, vs = algorithm.probe_positions(centre, params.probe_radius_v, angles,
                                           aligner.max_voltage_v)
        ring = np.empty(len(hs))
        all_ok = centre_ok
        for n, (h, v) in enumerate(zip(hs, vs, strict=True)):
            if ctx.stop_requested:
                run.stop_reason = "stopped"  # partial cycle: discarded, no step taken
                return
            ring[n], ok = await _measure(aligner, float(h), float(v), params)
            all_ok = all_ok and ok
            run.add_sample(ctx, float(h), float(v), float(ring[n]), ok, KIND_PROBE, cycle, -1, -1)

        decision = algorithm.decide_step(
            algorithm.ProbeCycle(centre, centre_signal, hs, vs, ring, all_ok),
            params.gain, params.max_step_v, params.min_contrast,
        )
        if decision.in_dip and all_ok and not centre_signal >= run.best_signal_a:
            run.best_v, run.best_signal_a = centre, centre_signal
        next_centre, limit = algorithm.apply_limits(
            centre, decision.step_v, run.start_v, params.max_excursion_v, aligner.max_voltage_v
        )
        reason = limit or decision.reason
        run.add_cycle(ctx, cycle, centre, centre_signal, decision, reason, next_centre)

        if params.duration_s is not None:
            ctx.progress.report(elapsed / params.duration_s, f"Cycle {cycle + 1}: {reason}")
        else:
            ctx.progress.report(0.0, f"Cycle {cycle + 1}: {reason}")

        if limit is not None:
            run.stop_reason = limit
            return
        centre = next_centre
        cycle += 1


async def _measure(
    aligner: Aligner, h: float, v: float, params: AutoAlignmentParams
) -> tuple[float, bool]:
    await aligner.move_to_v(h, v)
    # Always await, even for 0 s: yields to the event loop so the GUI stays
    # responsive and Stop/cancel land promptly with devices that never block.
    await asyncio.sleep(params.settle_time_s)
    total = 0.0
    in_range = True
    for _ in range(params.averages):
        reading = await aligner.read_signal()
        total += reading.signal_a
        in_range = in_range and reading.in_range
    return total / params.averages, in_range


@dataclass
class _Run:
    start_v: tuple[float, float]
    best_v: tuple[float, float]
    t0: float
    best_signal_a: float = math.nan
    stop_reason: str = "stopped"  # overwritten on every normal exit; stays if cancelled
    map_axes: tuple[np.ndarray, np.ndarray] | None = None
    samples: list[tuple] = field(default_factory=list)
    cycles: list[tuple] = field(default_factory=list)

    def add_sample(self, ctx: TaskContext, h: float, v: float, signal: float, in_range: bool,
                   kind: int, cycle: int, i: int, j: int) -> None:
        t = time.monotonic() - self.t0
        self.samples.append((t, h, v, signal, in_range, kind, cycle, i, j))
        ctx.live.publish("sample", {
            "t_s": t, "h_v": h, "v_v": v, "signal_a": signal, "in_range": in_range,
            "kind": _KIND_NAMES[kind], "cycle": cycle, "i": i, "j": j,
        })

    def add_cycle(self, ctx: TaskContext, cycle: int, centre: tuple[float, float],
                  centre_signal: float, decision: algorithm.StepDecision, reason: str,
                  next_centre: tuple[float, float]) -> None:
        t = time.monotonic() - self.t0
        self.cycles.append((
            t, centre[0], centre[1], centre_signal, decision.ring_mean_a,
            decision.gradient_a_per_v[0], decision.gradient_a_per_v[1],
            decision.curvature_a_per_v2, decision.in_dip, CYCLE_REASONS.index(reason),
            next_centre[0], next_centre[1],
        ))
        ctx.live.publish("cycle", {
            "cycle": cycle, "t_s": t, "centre_v": centre, "centre_signal_a": centre_signal,
            "ring_mean_a": decision.ring_mean_a, "in_dip": decision.in_dip, "reason": reason,
            "next_v": next_centre, "best_v": self.best_v, "best_signal_a": self.best_signal_a,
        })

    def to_raw(self, mode: str, max_voltage_v: float) -> AutoAlignmentRawData:
        s = _columns(self.samples, 9)
        c = _columns(self.cycles, 12)
        h_axis, v_axis = self.map_axes if self.map_axes is not None else (np.empty(0),
                                                                          np.empty(0))
        return AutoAlignmentRawData(
            mode=mode,
            stop_reason=self.stop_reason,
            max_voltage_v=float(max_voltage_v),
            start_v=np.asarray(self.start_v, dtype=float),
            best_v=np.asarray(self.best_v, dtype=float),
            best_signal_a=float(self.best_signal_a),
            sample_t_s=s[0].astype(float),
            sample_h_v=s[1].astype(float),
            sample_v_v=s[2].astype(float),
            sample_signal_a=s[3].astype(float),
            sample_in_range=s[4].astype(bool),
            sample_kind=s[5].astype(int),
            sample_cycle=s[6].astype(int),
            sample_map_i=s[7].astype(int),
            sample_map_j=s[8].astype(int),
            map_h_axis_v=np.asarray(h_axis, dtype=float),
            map_v_axis_v=np.asarray(v_axis, dtype=float),
            cycle_t_s=c[0].astype(float),
            cycle_centre_h_v=c[1].astype(float),
            cycle_centre_v_v=c[2].astype(float),
            cycle_centre_signal_a=c[3].astype(float),
            cycle_ring_mean_a=c[4].astype(float),
            cycle_gradient_h_a_per_v=c[5].astype(float),
            cycle_gradient_v_a_per_v=c[6].astype(float),
            cycle_curvature_a_per_v2=c[7].astype(float),
            cycle_in_dip=c[8].astype(bool),
            cycle_reason_code=c[9].astype(int),
            cycle_next_h_v=c[10].astype(float),
            cycle_next_v_v=c[11].astype(float),
        )


def _columns(rows: list[tuple], width: int) -> list[np.ndarray]:
    if not rows:
        return [np.empty(0) for _ in range(width)]
    return [np.array(column) for column in zip(*rows, strict=True)]
