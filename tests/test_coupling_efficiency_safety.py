from pathlib import Path

import pytest

from labman_core.exceptions import AbortConditionMet
from labman_core.simulators import SimLaser, SimPowerMeter
from labman_core.storage import RunStorage, StorageOptions
from labman_tasks.coupling_efficiency import CouplingEfficiencyTask
from labman_tasks.coupling_efficiency import safety as ce_safety
from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams


def _devices(eff: float = 0.6):
    laser = SimLaser(name="laser", max_power_mw=50.0)
    pm_in = SimPowerMeter(
        name="pm_in", source_mw=lambda: laser.power_mw, coupling=1.0, noise_w=0.0
    )
    pm_out = SimPowerMeter(
        name="pm_out", source_mw=lambda: laser.power_mw, coupling=eff, noise_w=0.0
    )
    return laser, {"laser": laser, "power_meter_in": pm_in, "power_meter_out": pm_out}


def _build_ctx(tmp_path: Path, eff: float = 0.6):
    from labman_core.context import TaskContext

    laser, devices = _devices(eff=eff)
    storage = RunStorage(
        "coupling_efficiency", StorageOptions(naming="iterator"), tmp_path
    )
    return laser, TaskContext(devices=devices, storage=storage)


# ----- safety module: idempotency and resilience -----

@pytest.mark.asyncio
async def test_to_safe_state_disables_laser() -> None:
    laser, devices = _devices()
    await laser.set_power_mw(40.0)
    await laser.set_enabled(True)

    await ce_safety.to_safe_state(devices)

    state = await laser.get_state()
    assert state.power_mw == 0.0
    assert state.enabled is False


@pytest.mark.asyncio
async def test_to_safe_state_is_idempotent() -> None:
    laser, devices = _devices()
    await laser.set_power_mw(20.0)
    await laser.set_enabled(True)

    for _ in range(5):
        await ce_safety.to_safe_state(devices)

    state = await laser.get_state()
    assert state.power_mw == 0.0
    assert state.enabled is False


@pytest.mark.asyncio
async def test_to_safe_state_handles_missing_laser() -> None:
    # Empty dict — nothing to do. Must not raise.
    await ce_safety.to_safe_state({})


@pytest.mark.asyncio
async def test_task_to_safe_state_delegates() -> None:
    laser, devices = _devices()
    await laser.set_power_mw(30.0)
    await laser.set_enabled(True)

    task = CouplingEfficiencyTask()
    await task.to_safe_state(devices)

    state = await laser.get_state()
    assert state.power_mw == 0.0
    assert state.enabled is False


# ----- abort_below: triggers exception, leaves hardware safe -----

@pytest.mark.asyncio
async def test_abort_below_raises_and_cleans_up(tmp_path: Path) -> None:
    laser, ctx = _build_ctx(tmp_path, eff=0.1)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=10.0, power_steps=5,
        averages_per_point=2, settle_time_s=0.0,
        abort_below=0.5,  # we expect 0.1, so the very first point trips
    )
    task = CouplingEfficiencyTask()

    with pytest.raises(AbortConditionMet):
        await task.run_headless(ctx, params)

    state = await laser.get_state()
    assert state.power_mw == 0.0
    assert state.enabled is False


@pytest.mark.asyncio
async def test_abort_below_does_not_trigger_when_efficiency_above(tmp_path: Path) -> None:
    laser, ctx = _build_ctx(tmp_path, eff=0.8)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=5.0, power_steps=3,
        averages_per_point=2, settle_time_s=0.0,
        abort_below=0.5,
    )
    task = CouplingEfficiencyTask()
    result = await task.run_headless(ctx, params)
    assert result.efficiency_mean == pytest.approx(0.8)


# ----- safety runs on every termination path -----

@pytest.mark.asyncio
async def test_safety_runs_on_normal_completion(tmp_path: Path) -> None:
    laser, ctx = _build_ctx(tmp_path)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=3.0, power_steps=3,
        averages_per_point=1, settle_time_s=0.0,
    )
    await CouplingEfficiencyTask().run_headless(ctx, params)
    state = await laser.get_state()
    assert state.power_mw == 0.0
    assert state.enabled is False


@pytest.mark.asyncio
async def test_safety_runs_on_unhandled_workflow_error(tmp_path: Path) -> None:
    """If a device raises mid-acquire, safety still runs."""
    from unittest.mock import patch

    laser, ctx = _build_ctx(tmp_path)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=5.0, power_steps=3,
        averages_per_point=1, settle_time_s=0.0,
    )

    # Make pm_in.read_power_w blow up after the first call.
    pm_in = ctx.devices["power_meter_in"]
    real_read = pm_in.read_power_w
    call_count = {"n": 0}

    async def bad_read():
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise RuntimeError("simulated meter failure")
        return await real_read()

    with patch.object(pm_in, "read_power_w", bad_read):
        with pytest.raises(RuntimeError, match="simulated meter failure"):
            await CouplingEfficiencyTask().run_headless(ctx, params)

    state = await laser.get_state()
    assert state.power_mw == 0.0
    assert state.enabled is False
