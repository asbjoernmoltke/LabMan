import asyncio
import time

import numpy as np

from labman_core.context import TaskContext
from labman_core.devices import LaserSource, PowerMeter
from labman_core.exceptions import AbortConditionMet
from labman_tasks.coupling_efficiency import safety
from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams
from labman_tasks.coupling_efficiency.result import CouplingEfficiencyRawData


async def acquire(
    ctx: TaskContext, params: CouplingEfficiencyParams
) -> CouplingEfficiencyRawData:
    laser: LaserSource = ctx.devices["laser"]            # type: ignore[assignment]
    pm_in: PowerMeter = ctx.devices["power_meter_in"]    # type: ignore[assignment]
    pm_out: PowerMeter = ctx.devices["power_meter_out"]  # type: ignore[assignment]

    await laser.set_wavelength_nm(params.wavelength_nm)
    await pm_in.set_wavelength_nm(params.wavelength_nm)
    await pm_out.set_wavelength_nm(params.wavelength_nm)
    await laser.set_enabled(True)

    setpoints = np.linspace(params.power_start, params.power_stop, params.power_steps)
    n, a = params.power_steps, params.averages_per_point
    p_in = np.empty((n, a), dtype=float)
    p_out = np.empty((n, a), dtype=float)
    t = np.empty((n, a), dtype=float)

    try:
        for i, sp in enumerate(setpoints):
            await laser.set_power_mw(float(sp))
            if params.settle_time_s > 0:
                await asyncio.sleep(params.settle_time_s)
            for j in range(a):
                t[i, j] = time.time()
                p_in[i, j] = await pm_in.read_power_w()
                p_out[i, j] = await pm_out.read_power_w()
            ctx.progress.report((i + 1) / n, f"Point {i + 1}/{n}")
            ctx.live.publish(
                "point",
                {
                    "index": i,
                    "setpoint_mw": float(sp),
                    "p_in_w": float(p_in[i].mean()),
                    "p_out_w": float(p_out[i].mean()),
                },
            )
            _check_abort(params, p_in[i], p_out[i])
    finally:
        await safety.to_safe_state(ctx.devices)

    return CouplingEfficiencyRawData(
        setpoints_mw=setpoints,
        p_in_w=p_in,
        p_out_w=p_out,
        t_seconds=t,
    )


def _check_abort(
    params: CouplingEfficiencyParams,
    p_in_point: np.ndarray,
    p_out_point: np.ndarray,
) -> None:
    if params.abort_below is None:
        return
    p_in_mean = float(p_in_point.mean())
    p_out_mean = float(p_out_point.mean())
    if p_in_mean <= 0:
        return
    eff = p_out_mean / p_in_mean
    if eff < params.abort_below:
        raise AbortConditionMet(
            f"η = {eff:.4f} below threshold {params.abort_below}"
        )
