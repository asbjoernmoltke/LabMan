import numpy as np
import pytest

from labman_tasks.coupling_efficiency.analysis import analyze
from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams
from labman_tasks.coupling_efficiency.result import CouplingEfficiencyRawData


def _raw(n: int = 5, a: int = 4, eff: float = 0.8) -> CouplingEfficiencyRawData:
    setpoints = np.linspace(1.0, 10.0, n)
    p_in = np.broadcast_to(setpoints[:, None] * 1e-3, (n, a)).copy()
    p_out = p_in * eff
    t = np.zeros((n, a))
    return CouplingEfficiencyRawData(setpoints, p_in, p_out, t)


def test_efficiency_recovers_known_ratio() -> None:
    raw = _raw(eff=0.75)
    params = CouplingEfficiencyParams(power_start=1.0, power_stop=10.0, power_steps=5)
    result = analyze(raw, params)

    assert np.allclose(result.efficiency, 0.75)
    assert result.efficiency_mean == pytest.approx(0.75)
    assert result.efficiency_std == pytest.approx(0.0, abs=1e-12)
    assert result.wavelength_nm == params.wavelength_nm
    assert result.correction_factor == 1.0


def test_correction_factor_scales_input() -> None:
    raw = _raw(eff=0.5)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=10.0, power_steps=5, correction_factor=2.0
    )
    result = analyze(raw, params)
    # eff = p_out / (correction * p_in) = 0.5 / 2.0 = 0.25
    assert np.allclose(result.efficiency, 0.25)


def test_zero_input_yields_nan() -> None:
    n, a = 3, 2
    setpoints = np.array([0.0, 1.0, 2.0])
    p_in = np.zeros((n, a))
    p_in[1:, :] = np.array([[1e-3, 1e-3], [2e-3, 2e-3]])
    p_out = p_in * 0.8
    raw = CouplingEfficiencyRawData(setpoints, p_in, p_out, np.zeros((n, a)))
    params = CouplingEfficiencyParams()

    result = analyze(raw, params)
    assert np.isnan(result.efficiency[0])
    assert np.allclose(result.efficiency[1:], 0.8)
