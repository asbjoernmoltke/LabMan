import numpy as np

from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams
from labman_tasks.coupling_efficiency.result import (
    CouplingEfficiencyRawData,
    CouplingEfficiencyResult,
)


def analyze(
    raw: CouplingEfficiencyRawData, params: CouplingEfficiencyParams
) -> CouplingEfficiencyResult:
    p_in_mean = raw.p_in_w.mean(axis=1)
    p_out_mean = raw.p_out_w.mean(axis=1)

    denom = params.correction_factor * p_in_mean
    with np.errstate(divide="ignore", invalid="ignore"):
        eff = np.where(denom > 0, p_out_mean / denom, np.nan)

    return CouplingEfficiencyResult(
        setpoints_mw=raw.setpoints_mw,
        p_in_mean_w=p_in_mean,
        p_out_mean_w=p_out_mean,
        efficiency=eff,
        efficiency_mean=float(np.nanmean(eff)),
        efficiency_std=float(np.nanstd(eff)),
        wavelength_nm=params.wavelength_nm,
        correction_factor=params.correction_factor,
    )
