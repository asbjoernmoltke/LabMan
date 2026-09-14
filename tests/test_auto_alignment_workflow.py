import asyncio
import json
import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from labman_core.context import TaskContext
from labman_core.persistence import load_dataclass_h5
from labman_core.simulators import SimAligner
from labman_core.storage import RunStorage, StorageOptions
from labman_tasks.auto_alignment import AutoAlignmentTask
from labman_tasks.auto_alignment import safety as aa_safety
from labman_tasks.auto_alignment.analysis import analyze
from labman_tasks.auto_alignment.params import AutoAlignmentParams
from labman_tasks.auto_alignment.result import CYCLE_REASONS, AutoAlignmentRawData
from labman_tasks.auto_alignment.workflow import acquire

OPTIMUM = (75.0, 75.0)
FAST = {"settle_time_s": 0.0, "averages": 1}
# Dip contrast scales with probe_radius²: with a 0.05 V probe the centre is <1 % below
# its ring a few tenths of a volt from the optimum and tracking (correctly) holds still.
TRACK = {**FAST, "mode": "track", "probe_radius_v": 0.2, "gain": 0.5, "max_step_v": 0.1,
         "min_contrast": 0.05, "max_excursion_v": 3.0}


def _ctx(tmp_path: Path, start=(75.3, 74.8), **sim_kwargs) -> tuple[SimAligner, TaskContext]:
    sim = SimAligner(start_v=start, optimum_v=OPTIMUM, ring_radius_v=1.0, **sim_kwargs)
    storage = RunStorage("auto_alignment", StorageOptions(naming="iterator"), tmp_path)
    return sim, TaskContext(devices={"aligner": sim}, storage=storage)


def _stop_after_cycles(ctx: TaskContext, n: int) -> None:
    ctx.live.subscribe("cycle", lambda p: p["cycle"] + 1 >= n and ctx.request_stop())


# ----- map -----


async def test_map_run_headless_saves_and_returns_to_start(tmp_path: Path) -> None:
    sim, ctx = _ctx(tmp_path)
    params = AutoAlignmentParams(mode="map", map_points=5, map_half_width_v=1.0, **FAST)

    result = await AutoAlignmentTask().run_headless(ctx, params)

    for path in (ctx.storage.raw_path(), ctx.storage.result_path(), ctx.storage.params_path(),
                 ctx.storage.meta_path()):
        assert path.exists()
    assert json.loads(ctx.storage.meta_path().read_text())["stop_reason"] == "completed"

    assert result.stop_reason == "completed"
    assert result.map is not None
    assert result.map.signal_a.shape == (5, 5)
    assert not np.isnan(result.map.signal_a).any()
    assert math.hypot(*(result.map.min_v - np.array(OPTIMUM))) < 0.5
    assert await sim.get_position_v() == (75.3, 74.8)
    assert sim.latched


async def test_saved_raw_reanalyzes_identically(tmp_path: Path) -> None:
    _sim, ctx = _ctx(tmp_path)
    params = AutoAlignmentParams(mode="map", map_points=7, map_half_width_v=2.0, **FAST)
    result = await AutoAlignmentTask().run_headless(ctx, params)

    raw = load_dataclass_h5(ctx.storage.raw_path(), AutoAlignmentRawData)
    again = analyze(raw, params)
    assert np.array_equal(again.map.signal_a, result.map.signal_a, equal_nan=True)
    assert again.map.profile_shape == result.map.profile_shape


async def test_map_stop_request_ends_early_and_returns_to_start(tmp_path: Path) -> None:
    sim, ctx = _ctx(tmp_path)
    seen: list[dict] = []
    ctx.live.subscribe("sample", lambda p: (seen.append(p), len(seen) >= 3 and ctx.request_stop()))
    params = AutoAlignmentParams(mode="map", map_points=5, **FAST)

    raw = await acquire(ctx, params)

    assert raw.stop_reason == "stopped"
    assert raw.sample_signal_a.size == 3
    assert await sim.get_position_v() == (75.3, 74.8)


# ----- tracking -----


async def test_tracking_converges_to_dip_and_latches_at_best(tmp_path: Path) -> None:
    sim, ctx = _ctx(tmp_path)
    _stop_after_cycles(ctx, 25)
    params = AutoAlignmentParams(**TRACK)

    result = await AutoAlignmentTask().run_headless(ctx, params)

    assert result.stop_reason == "stopped"
    assert result.track.n_cycles == 25
    assert result.track.in_dip_fraction == 1.0
    best = result.track.best_v
    assert math.hypot(best[0] - OPTIMUM[0], best[1] - OPTIMUM[1]) < 0.02
    assert await sim.get_position_v() == pytest.approx(tuple(best))
    assert sim.latched
    assert ctx.storage.raw_path().exists()


async def test_tracking_follows_a_drifting_optimum(tmp_path: Path) -> None:
    sim, ctx = _ctx(tmp_path, start=OPTIMUM)

    def drift(payload: dict) -> None:
        h, v = sim.optimum_v
        sim.optimum_v = (h + 0.01, v)
        if payload["cycle"] + 1 >= 40:
            ctx.request_stop()

    ctx.live.subscribe("cycle", drift)
    raw = await acquire(ctx, AutoAlignmentParams(**TRACK))

    final = (raw.cycle_next_h_v[-1], raw.cycle_next_v_v[-1])
    assert sim.optimum_v[0] == pytest.approx(75.4)
    assert math.hypot(final[0] - sim.optimum_v[0], final[1] - sim.optimum_v[1]) < 0.05


async def test_tracking_holds_still_on_the_ring(tmp_path: Path) -> None:
    sim, ctx = _ctx(tmp_path, start=(76.0, 75.0))
    _stop_after_cycles(ctx, 10)

    raw = await acquire(ctx, AutoAlignmentParams(**TRACK))

    assert np.all(raw.cycle_centre_h_v == 76.0)
    assert not raw.cycle_in_dip.any()
    assert {CYCLE_REASONS[c] for c in raw.cycle_reason_code} == {"not_in_dip"}
    assert math.isnan(raw.best_signal_a)
    assert await sim.get_position_v() == (76.0, 75.0)


async def test_excursion_limit_stops_and_holds_best(tmp_path: Path) -> None:
    sim, ctx = _ctx(tmp_path, start=(75.3, 75.0))
    _stop_after_cycles(ctx, 50)  # a regression fails the asserts instead of hanging
    params = AutoAlignmentParams(**{**TRACK, "max_step_v": 0.2, "max_excursion_v": 0.05})

    raw = await acquire(ctx, params)

    assert raw.stop_reason == "max_excursion"
    assert raw.cycle_t_s.size == 1
    assert await sim.get_position_v() == (75.3, 75.0)
    assert sim.latched


async def test_duration_ends_tracking(tmp_path: Path) -> None:
    _sim, ctx = _ctx(tmp_path)
    raw = await acquire(ctx, AutoAlignmentParams(**{**TRACK, "duration_s": 0.05}))
    assert raw.stop_reason == "duration"


# ----- safety on every exit path -----


async def test_cancellation_latches_within_excursion(tmp_path: Path) -> None:
    sim, ctx = _ctx(tmp_path)
    ctx.live.subscribe("sample", lambda _p: setattr(sim, "latched", False))
    params = AutoAlignmentParams(**{**TRACK, "settle_time_s": 0.001})

    run = asyncio.create_task(acquire(ctx, params))
    await asyncio.sleep(0.05)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    assert sim.latched
    h, v = await sim.get_position_v()
    assert math.hypot(h - 75.3, v - 74.8) <= params.max_excursion_v


async def test_device_error_mid_run_returns_to_start_and_latches(tmp_path: Path) -> None:
    sim, ctx = _ctx(tmp_path)
    real_read = sim.read_signal
    calls = {"n": 0}

    async def failing_read():
        calls["n"] += 1
        if calls["n"] >= 5:
            raise RuntimeError("detector unplugged")
        return await real_read()

    with patch.object(sim, "read_signal", failing_read), \
            pytest.raises(RuntimeError, match="unplugged"):
        await AutoAlignmentTask().run_headless(ctx, AutoAlignmentParams(mode="map", **FAST))

    assert sim.latched
    assert await sim.get_position_v() == (75.3, 74.8)


async def test_safe_state_is_idempotent_and_non_raising() -> None:
    sim = SimAligner(start_v=(10.0, 10.0))
    sim.latched = False
    for _ in range(3):
        await aa_safety.to_safe_state({"aligner": sim}, hold_at=(20.0, 30.0))
    assert sim.latched
    assert await sim.get_position_v() == (20.0, 30.0)

    await aa_safety.to_safe_state({})

    class Broken:
        async def latch(self):
            raise RuntimeError("usb gone")

        async def move_to_v(self, h, v):
            raise RuntimeError("usb gone")

    await aa_safety.to_safe_state({"aligner": Broken()}, hold_at=(1.0, 1.0))


async def test_task_to_safe_state_latches_in_place() -> None:
    sim = SimAligner(start_v=(12.0, 13.0))
    sim.latched = False
    await AutoAlignmentTask().to_safe_state({"aligner": sim})
    assert sim.latched
    assert await sim.get_position_v() == (12.0, 13.0)
    assert sim.move_count == 0


def test_request_stop_sets_flag(tmp_path: Path) -> None:
    _sim, ctx = _ctx(tmp_path)
    assert not ctx.stop_requested
    ctx.request_stop()
    assert ctx.stop_requested
