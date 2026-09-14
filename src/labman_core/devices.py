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


@dataclass
class SignalReading:
    signal_a: float
    in_range: bool = True   # False when the detector reports under- or over-range


@runtime_checkable
class Aligner(Device, Protocol):
    """Two-axis piezo positioner with a built-in detector (e.g. Thorlabs K-Cube NanoTrak).

    Positions are the two output voltages in V, (horizontal, vertical), each in
    [0, max_voltage_v]. `latch` stops any device-side tracking and holds the
    current output.
    """

    @property
    def max_voltage_v(self) -> float: ...

    async def get_position_v(self) -> tuple[float, float]: ...

    async def move_to_v(self, horizontal_v: float, vertical_v: float) -> None: ...

    async def read_signal(self) -> SignalReading: ...

    async def latch(self) -> None: ...
