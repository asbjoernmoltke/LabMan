from dataclasses import dataclass

import numpy as np


@dataclass
class CouplingEfficiencyRawData:
    setpoints_mw: np.ndarray   # (N,)
    p_in_w: np.ndarray         # (N, A)
    p_out_w: np.ndarray        # (N, A)
    t_seconds: np.ndarray      # (N, A)


@dataclass
class CouplingEfficiencyResult:
    setpoints_mw: np.ndarray
    p_in_mean_w: np.ndarray
    p_out_mean_w: np.ndarray
    efficiency: np.ndarray     # p_out / (correction * p_in) per setpoint
    efficiency_mean: float
    efficiency_std: float
    wavelength_nm: float
    correction_factor: float
