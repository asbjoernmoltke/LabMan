import asyncio
import logging
from collections import defaultdict
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


class LivePublisher:
    """Pub/sub channel for intermediate task data.

    Tasks publish typed events by name (e.g. "point", "image", "spectrum");
    widgets subscribe to specific event names. Synchronous: sinks must be fast
    (typically a Qt slot that schedules a paint).

    Decoupled from ProgressReporter so progress is always a float and live
    payloads stay task-specific.
    """

    def __init__(self) -> None:
        self._sinks: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, event: str, sink: Callable[[Any], None]) -> None:
        self._sinks[event].append(sink)

    def publish(self, event: str, payload: Any) -> None:
        for sink in self._sinks.get(event, ()):
            sink(payload)


@dataclass
class TaskContext:
    devices: dict[str, Device]
    storage: RunStorage
    progress: ProgressReporter = field(default_factory=ProgressReporter)
    live: LivePublisher = field(default_factory=LivePublisher)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("labman.task"))
    extras: dict[str, Any] = field(default_factory=dict)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    def request_stop(self) -> None:
        """Ask an open-ended workflow to finish gracefully and return its data.

        Distinct from cancellation: a stopped workflow returns normally, so raw
        data is persisted. Workflows that run until stopped check
        `stop_requested` between steps.
        """
        self.stop_event.set()

    @property
    def stop_requested(self) -> bool:
        return self.stop_event.is_set()
