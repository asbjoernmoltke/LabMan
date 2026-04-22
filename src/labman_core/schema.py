from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Range:
    low: float
    high: float
    step: float | None = None

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


@dataclass(frozen=True)
class ParamMeta:
    """Presentation metadata for a Params dataclass field.

    Attached via Annotated[T, ParamMeta(...)] on the field. The data contract
    (type, bounds, optional) lives in the type system; this carries only how
    the field should be shown.
    """

    display: str
    unit: str = ""
    bounds: Range | None = None
    optional: bool = False
    tooltip: str = ""
    group: str = ""
    widget: str | None = None


@dataclass
class Setable:
    name: str
    display: str
    unit: str
    kind: type
    bounds: Range | None
    choices: list[Any] | None
    get: Callable[[], Awaitable[Any]]
    set: Callable[[Any], Awaitable[None]]


@dataclass
class Readable:
    name: str
    display: str
    unit: str
    kind: type
    get: Callable[[], Awaitable[Any]]


@dataclass
class Action:
    name: str
    display: str
    call: Callable[[], Awaitable[None]]


@dataclass
class DeviceControls:
    setables: list[Setable] = field(default_factory=list)
    readables: list[Readable] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
