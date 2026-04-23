import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from labman_core.context import TaskContext
from labman_core.simulators import SimLaser, SimPowerMeter
from labman_core.storage import RunStorage, StorageOptions
from labman_tasks.coupling_efficiency import CouplingEfficiencyTask
from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams


def _build_ctx(tmp_path: Path, eff: float = 0.6) -> TaskContext:
    laser = SimLaser(name="laser", max_power_mw=50.0)
    pm_in = SimPowerMeter(
        name="pm_in", source_mw=lambda: laser.power_mw, coupling=1.0, noise_w=0.0, seed=1
    )
    pm_out = SimPowerMeter(
        name="pm_out", source_mw=lambda: laser.power_mw, coupling=eff, noise_w=0.0, seed=2
    )
    storage = RunStorage(
        "coupling_efficiency", StorageOptions(naming="iterator"), tmp_path
    )
    return TaskContext(
        devices={"laser": laser, "power_meter_in": pm_in, "power_meter_out": pm_out},
        storage=storage,
    )


@pytest.mark.asyncio
async def test_run_headless_produces_expected_files_and_efficiency(tmp_path: Path) -> None:
    ctx = _build_ctx(tmp_path, eff=0.6)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=10.0, power_steps=5,
        averages_per_point=4, settle_time_s=0.0,
    )

    task = CouplingEfficiencyTask()
    result = await task.run_headless(ctx, params)

    assert ctx.storage.raw_path().exists()
    assert ctx.storage.result_path().exists()
    assert ctx.storage.params_path().exists()
    assert ctx.storage.meta_path().exists()

    assert np.allclose(result.efficiency, 0.6, atol=1e-9)
    assert result.efficiency_mean == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_persisted_raw_round_trip(tmp_path: Path) -> None:
    ctx = _build_ctx(tmp_path, eff=0.5)
    params = CouplingEfficiencyParams(
        power_start=2.0, power_stop=8.0, power_steps=4,
        averages_per_point=3, settle_time_s=0.0,
    )

    task = CouplingEfficiencyTask()
    await task.run_headless(ctx, params)

    with h5py.File(ctx.storage.raw_path(), "r") as f:
        setpoints = f["setpoints_mw"][:]
        p_in = f["p_in_w"][:]
        p_out = f["p_out_w"][:]
    assert setpoints.shape == (4,)
    assert p_in.shape == (4, 3)
    assert p_out.shape == (4, 3)
    assert np.allclose(p_out / np.where(p_in > 0, p_in, np.nan), 0.5, atol=1e-9)


@pytest.mark.asyncio
async def test_persisted_params_match_input(tmp_path: Path) -> None:
    ctx = _build_ctx(tmp_path)
    params = CouplingEfficiencyParams(
        power_start=1.5, power_stop=7.5, power_steps=3,
        averages_per_point=2, settle_time_s=0.0, correction_factor=1.25,
    )

    task = CouplingEfficiencyTask()
    await task.run_headless(ctx, params)

    saved = json.loads(ctx.storage.params_path().read_text())
    assert saved["power_start"] == 1.5
    assert saved["power_stop"] == 7.5
    assert saved["power_steps"] == 3
    assert saved["correction_factor"] == 1.25


@pytest.mark.asyncio
async def test_progress_reports_one_per_setpoint(tmp_path: Path) -> None:
    ctx = _build_ctx(tmp_path)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=5.0, power_steps=5,
        averages_per_point=2, settle_time_s=0.0,
    )

    seen: list[float] = []
    ctx.progress.subscribe(lambda f, _msg: seen.append(f))

    task = CouplingEfficiencyTask()
    await task.run_headless(ctx, params)

    assert len(seen) == 5
    assert seen[-1] == pytest.approx(1.0)
    assert seen == sorted(seen)


@pytest.mark.asyncio
async def test_laser_disabled_after_run(tmp_path: Path) -> None:
    ctx = _build_ctx(tmp_path)
    laser = ctx.devices["laser"]
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=5.0, power_steps=3,
        averages_per_point=1, settle_time_s=0.0,
    )

    task = CouplingEfficiencyTask()
    await task.run_headless(ctx, params)

    state = await laser.get_state()
    assert state.enabled is False
    assert state.power_mw == 0.0
