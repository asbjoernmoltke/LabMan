from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from labman_core.schema import DeviceControls


@dataclass
class LaserState:
    power_mw: float
    wavelength_nm: float
    enabled: bool


@runtime_checkable
class Device(Protocol):
    """Common base for any device."""

    @property
    def name(self) -> str: ...

    def controls(self) -> DeviceControls: ...

    async def shutdown(self) -> None: ...


@runtime_checkable
class LaserSource(Device, Protocol):
    async def set_power_mw(self, power_mw: float) -> None: ...

    async def set_wavelength_nm(self, wavelength_nm: float) -> None: ...

    async def set_enabled(self, enabled: bool) -> None: ...

    async def get_state(self) -> LaserState: ...


@runtime_checkable
class PowerMeter(Device, Protocol):
    async def read_power_w(self) -> float: ...

    async def set_wavelength_nm(self, wavelength_nm: float) -> None: ...
