from labman_core.devices import LaserState
from labman_core.schema import (
    Action,
    DeviceControls,
    Range,
    Readable,
    Setable,
)


class SimLaser:
    """In-memory laser simulator. Implements the LaserSource Protocol structurally."""

    def __init__(
        self,
        name: str = "sim_laser",
        power_mw: float = 0.0,
        wavelength_nm: float = 1550.0,
        max_power_mw: float = 100.0,
    ) -> None:
        self._name = name
        self._power_mw = power_mw
        self._wavelength_nm = wavelength_nm
        self._enabled = False
        self._max_power_mw = max_power_mw

    @property
    def name(self) -> str:
        return self._name

    async def set_power_mw(self, power_mw: float) -> None:
        if not 0.0 <= power_mw <= self._max_power_mw:
            raise ValueError(f"power_mw {power_mw} outside [0, {self._max_power_mw}]")
        self._power_mw = float(power_mw)

    async def set_wavelength_nm(self, wavelength_nm: float) -> None:
        self._wavelength_nm = float(wavelength_nm)

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    async def get_state(self) -> LaserState:
        return LaserState(
            power_mw=self._power_mw,
            wavelength_nm=self._wavelength_nm,
            enabled=self._enabled,
        )

    async def shutdown(self) -> None:
        self._enabled = False

    @property
    def power_mw(self) -> float:
        return self._power_mw

    @property
    def wavelength_nm(self) -> float:
        return self._wavelength_nm

    def controls(self) -> DeviceControls:
        return DeviceControls(
            setables=[
                Setable(
                    name="power",
                    display="Power",
                    unit="mW",
                    kind=float,
                    bounds=Range(0.0, self._max_power_mw),
                    choices=None,
                    get=self._get_power,
                    set=self.set_power_mw,
                ),
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
                    name="enabled",
                    display="Output enabled",
                    unit="",
                    kind=bool,
                    bounds=None,
                    choices=None,
                    get=self._get_enabled,
                    set=self.set_enabled,
                ),
            ],
            readables=[
                Readable(
                    name="state",
                    display="Laser state",
                    unit="",
                    kind=LaserState,
                    get=self.get_state,
                ),
            ],
            actions=[
                Action(name="shutdown", display="Shutdown", call=self.shutdown),
            ],
        )

    async def _get_power(self) -> float:
        return self._power_mw

    async def _get_wavelength(self) -> float:
        return self._wavelength_nm

    async def _get_enabled(self) -> bool:
        return self._enabled
