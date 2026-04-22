import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from labman_core.devices import Device
from labman_core.storage import RunStorage


class ProgressReporter:
    """Reports progress (0.0 .. 1.0) and a status message during a workflow.

    Sinks are subscribed callables; the shell wires its progress bar in.
    Default sink is a noop so headless/test runs work without setup.
    """

    def __init__(self) -> None:
        self._sinks: list[Callable[[float, str], None]] = []

    def subscribe(self, sink: Callable[[float, str], None]) -> None:
        self._sinks.append(sink)

    def report(self, fraction: float, message: str = "") -> None:
        f = max(0.0, min(1.0, float(fraction)))
        for sink in self._sinks:
            sink(f, message)


@dataclass
class TaskContext:
    devices: dict[str, Device]
    storage: RunStorage
    progress: ProgressReporter = field(default_factory=ProgressReporter)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("labman.task"))
    extras: dict[str, Any] = field(default_factory=dict)
