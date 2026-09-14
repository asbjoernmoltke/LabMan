import math
import time
from collections.abc import Callable, Sequence

import numpy as np

from labman_core.devices import SignalReading
from labman_core.schema import Action, DeviceControls, Range, Readable, Setable

PROFILES = ("donut", "minimum")


class SimAligner:
    """NanoTrak-style aligner simulator: two piezo voltages -> detector signal.

    The optimum sits at `optimum_v` and moves at `drift_v_per_s`. The distance
    d (in V) from the optimum maps to signal according to `profile`:

    - "donut":   background + peak * (d/R)^2 * exp(1 - (d/R)^2)
                 low at the optimum, maximum `peak` on a ring of radius R, back
                 to background far away (the cladding-light picture).
    - "minimum": background + peak * (1 - exp(-(d/R)^2))   (a plain bowl)

    Noise is multiplicative Gaussian (`noise_rel`). Positions outside
    [0, max_voltage_v] are rejected, like the real driver.
    """

    def __init__(
        self,
        name: str = "sim_aligner",
        max_voltage_v: float = 150.0,
        start_v: Sequence[float] = (75.0, 75.0),
        optimum_v: Sequence[float] = (75.0, 75.0),
        profile: str = "donut",
        ring_radius_v: float = 1.0,
        background_a: float = 2e-9,
        peak_a: float = 5e-7,
        noise_rel: float = 0.0,
        drift_v_per_s: Sequence[float] = (0.0, 0.0),
        seed: int | None = 0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if profile not in PROFILES:
            raise ValueError(f"profile={profile!r} not in {list(PROFILES)}")
        self._name = name
        self._max_v = float(max_voltage_v)
        self._h, self._v = self._validate(float(start_v[0]), float(start_v[1]))
        self._profile = profile
        self._ring = float(ring_radius_v)
        self._background = float(background_a)
        self._peak = float(peak_a)
        self._noise = float(noise_rel)
        self._drift = (float(drift_v_per_s[0]), float(drift_v_per_s[1]))
        self._rng = np.random.default_rng(seed)
        self._clock = clock
        self._optimum = (float(optimum_v[0]), float(optimum_v[1]))
        self._t0 = clock()
        self.latched = True
        self.move_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def max_voltage_v(self) -> float:
        return self._max_v

    @property
    def optimum_v(self) -> tuple[float, float]:
        dt = self._clock() - self._t0
        return (self._optimum[0] + self._drift[0] * dt, self._optimum[1] + self._drift[1] * dt)

    @optimum_v.setter
    def optimum_v(self, value: Sequence[float]) -> None:
        self._optimum = (float(value[0]), float(value[1]))
        self._t0 = self._clock()

    def signal_at(self, horizontal_v: float, vertical_v: float) -> float:
        """Noise-free model signal in A at a position."""
        oh, ov = self.optimum_v
        x2 = (math.hypot(horizontal_v - oh, vertical_v - ov) / self._ring) ** 2
        if self._profile == "donut":
            return self._background + self._peak * x2 * math.exp(1.0 - x2)
        return self._background + self._peak * (1.0 - math.exp(-x2))

    async def get_position_v(self) -> tuple[float, float]:
        return (self._h, self._v)

    async def move_to_v(self, horizontal_v: float, vertical_v: float) -> None:
        self._h, self._v = self._validate(float(horizontal_v), float(vertical_v))
        self.move_count += 1

    async def read_signal(self) -> SignalReading:
        s = self.signal_at(self._h, self._v)
        if self._noise > 0:
            s *= 1.0 + self._noise * float(self._rng.normal())
        return SignalReading(signal_a=s, in_range=True)

    async def latch(self) -> None:
        self.latched = True

    async def shutdown(self) -> None:
        self.latched = True

    def controls(self) -> DeviceControls:
        return DeviceControls(
            setables=[
                Setable(
                    name="horizontal_v",
                    display="Horizontal",
                    unit="V",
                    kind=float,
                    bounds=Range(0.0, self._max_v),
                    choices=None,
                    get=self._get_h,
                    set=lambda value: self.move_to_v(value, self._v),
                ),
                Setable(
                    name="vertical_v",
                    display="Vertical",
                    unit="V",
                    kind=float,
                    bounds=Range(0.0, self._max_v),
                    choices=None,
                    get=self._get_v,
                    set=lambda value: self.move_to_v(self._h, value),
                ),
            ],
            readables=[
                Readable(
                    name="signal",
                    display="Signal",
                    unit="A",
                    kind=float,
                    get=self._get_signal,
                ),
            ],
            actions=[Action(name="latch", display="Latch", call=self.latch)],
        )

    def _validate(self, h: float, v: float) -> tuple[float, float]:
        for label, value in (("horizontal", h), ("vertical", v)):
            if not 0.0 <= value <= self._max_v:
                raise ValueError(f"{label} {value} V outside [0, {self._max_v}] V")
        return h, v

    async def _get_h(self) -> float:
        return self._h

    async def _get_v(self) -> float:
        return self._v

    async def _get_signal(self) -> float:
        return (await self.read_signal()).signal_a
