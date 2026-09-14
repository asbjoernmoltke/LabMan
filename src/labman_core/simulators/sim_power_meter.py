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
    """Power meter simulator.

    Reads power as `coupling * laser_power_mW * 1e-3` plus Gaussian noise,
    minus any calibrated offset. Pass a `source_mw` callable that returns the
    laser power in mW; tests bind the same SimLaser to two SimPowerMeters with
    different `coupling` values to mimic input/output ports.

    Reads can be negative — calibrating against a higher reference and then
    reading a smaller signal is a legitimate workflow. Callers are responsible
    for guarding division by p_in (analyzer's job, not the meter's).
    """

    RANGES: tuple[str, ...] = ("auto", "1mW", "30mW", "300mW")
    ACQ_MODES: tuple[str, ...] = ("fast", "medium", "slow")

    def __init__(
        self,
        name: str = "sim_pm",
        source_mw: Callable[[], float] | None = None,
        coupling: float = 1.0,
        noise_w: float = 1e-9,
        wavelength_nm: float = 1550.0,
        seed: int | None = 0,
        range_setting: str = "auto",
        acq_mode: str = "medium",
        averaging: int = 10,
    ) -> None:
        self._name = name
        self._source_mw = source_mw or (lambda: 0.0)
        self._coupling = float(coupling)
        self._noise_w = float(noise_w)
        self._wavelength_nm = float(wavelength_nm)
        self._rng = np.random.default_rng(seed)
        self._range = self._validate_choice(range_setting, self.RANGES, "range_setting")
        self._acq_mode = self._validate_choice(acq_mode, self.ACQ_MODES, "acq_mode")
        self._averaging = self._validate_int(averaging, 1, 10000, "averaging")
        self._offset_w = 0.0

    @property
    def name(self) -> str:
        return self._name

    async def read_power_w(self) -> float:
        return self._raw_sample_w() - self._offset_w

    async def set_wavelength_nm(self, wavelength_nm: float) -> None:
        self._wavelength_nm = float(wavelength_nm)

    async def set_range(self, value: str) -> None:
        self._range = self._validate_choice(value, self.RANGES, "range")

    async def set_acq_mode(self, value: str) -> None:
        self._acq_mode = self._validate_choice(value, self.ACQ_MODES, "acq_mode")

    async def set_averaging(self, value: int) -> None:
        self._averaging = self._validate_int(value, 1, 10000, "averaging")

    async def calibrate(self) -> None:
        """Sample `averaging` times at current source power and store the mean as offset.

        Offset can be negative (rare) — happens only if calibrating against
        below-baseline noise. Subsequent reads simply add the magnitude back.
        """
        samples = [self._raw_sample_w() for _ in range(self._averaging)]
        self._offset_w = float(np.mean(samples))

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
                Setable(
                    name="range",
                    display="Range",
                    unit="",
                    kind=str,
                    bounds=None,
                    choices=list(self.RANGES),
                    get=self._get_range,
                    set=self.set_range,
                ),
                Setable(
                    name="acq_mode",
                    display="Mode",
                    unit="",
                    kind=str,
                    bounds=None,
                    choices=list(self.ACQ_MODES),
                    get=self._get_acq_mode,
                    set=self.set_acq_mode,
                ),
                Setable(
                    name="averaging",
                    display="Averaging",
                    unit="",
                    kind=int,
                    bounds=Range(1, 10000),
                    choices=None,
                    get=self._get_averaging,
                    set=self.set_averaging,
                ),
            ],
            readables=[
                Readable(
                    name="power",
                    display="Power",
                    unit="W",
                    kind=float,
                    get=self.read_power_w,
                    display_precision=1e-9,
                ),
                Readable(
                    name="offset",
                    display="Offset",
                    unit="W",
                    kind=float,
                    get=self._get_offset,
                    display_precision=1e-9,
                ),
            ],
            actions=[
                Action(name="calibrate", display="Calibrate", call=self.calibrate),
                Action(name="shutdown", display="Shutdown", call=self.shutdown),
            ],
        )

    def _raw_sample_w(self) -> float:
        true_w = self._coupling * self._source_mw() * 1e-3
        noise = float(self._rng.normal(0.0, self._noise_w))
        return true_w + noise

    @staticmethod
    def _validate_choice(value: str, choices: tuple[str, ...], field: str) -> str:
        if value not in choices:
            raise ValueError(f"{field}={value!r} not in {list(choices)}")
        return value

    @staticmethod
    def _validate_int(value: int, low: int, high: int, field: str) -> int:
        v = int(value)
        if not low <= v <= high:
            raise ValueError(f"{field}={value} outside [{low}, {high}]")
        return v

    async def _get_wavelength(self) -> float:
        return self._wavelength_nm

    async def _get_range(self) -> str:
        return self._range

    async def _get_acq_mode(self) -> str:
        return self._acq_mode

    async def _get_averaging(self) -> int:
        return self._averaging

    async def _get_offset(self) -> float:
        return self._offset_w
