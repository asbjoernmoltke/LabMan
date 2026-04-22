from collections.abc import Callable

import numpy as np

from labman_core.schema import (
    Action,
    DeviceControls,
    Range,
    Readable,
    Setable,
)


class SimPowerMeter:
    """Power meter simulator. Reads power as `coupling * laser_power_mW * 1e-3` plus noise.

    Pass a `source_mw` callable that returns the laser power in mW; the meter
    converts to watts and applies the coupling factor + Gaussian noise. Used in
    tests by binding the same SimLaser to two SimPowerMeters with different
    `coupling` values to mimic input/output ports.
    """

    def __init__(
        self,
        name: str = "sim_pm",
        source_mw: Callable[[], float] | None = None,
        coupling: float = 1.0,
        noise_w: float = 1e-9,
        wavelength_nm: float = 1550.0,
        seed: int | None = 0,
    ) -> None:
        self._name = name
        self._source_mw = source_mw or (lambda: 0.0)
        self._coupling = float(coupling)
        self._noise_w = float(noise_w)
        self._wavelength_nm = float(wavelength_nm)
        self._rng = np.random.default_rng(seed)

    @property
    def name(self) -> str:
        return self._name

    async def read_power_w(self) -> float:
        true_w = self._coupling * self._source_mw() * 1e-3
        noise = float(self._rng.normal(0.0, self._noise_w))
        return max(0.0, true_w + noise)

    async def set_wavelength_nm(self, wavelength_nm: float) -> None:
        self._wavelength_nm = float(wavelength_nm)

    async def shutdown(self) -> None:
        return None

    def controls(self) -> DeviceControls:
        return DeviceControls(
            setables=[
                Setable(
                    name="wavelength",
                    display="Wavelength",
                    unit="nm",
                    kind=float,
                    bounds=Range(400.0, 2000.0),
                    choices=None,
                    get=self._get_wavelength,
                    set=self.set_wavelength_nm,
                ),
            ],
            readables=[
                Readable(
                    name="power",
                    display="Power",
                    unit="W",
                    kind=float,
                    get=self.read_power_w,
                ),
            ],
            actions=[
                Action(name="shutdown", display="Shutdown", call=self.shutdown),
            ],
        )

    async def _get_wavelength(self) -> float:
        return self._wavelength_nm
