from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from labman_core.devices import Device
from labman_core.lab_config import DeviceSync
from labman_core.storage import RunStorage, StorageOptions


@runtime_checkable
class ShellServices(Protocol):
    """Interface a task widget receives from the host application.

    The real shell implements this; demo launchers and tests provide stubs.
    Tasks should never construct devices, storage paths, or presets directly —
    always go through ShellServices so the shell controls lifetime, exclusivity,
    and configuration.
    """

    def device(self, binding_name: str) -> Device: ...

    def device_sync(self, binding_name: str) -> DeviceSync:
        """Connect-time sync the widget applies to this binding's panel."""
        ...

    def params_form(self, task_name: str, params_cls: type) -> tuple[Any, Callable[[], Any]]:
        """`(QWidget, getter)` params form for the task, with the shell's presets wired in."""
        ...

    def run_succeeded(self, task_name: str, params: Any) -> None:
        """Called by the task widget after a successful run (updates last-used params)."""
        ...

    def make_storage(
        self, task_name: str, opts: StorageOptions | None = None
    ) -> RunStorage: ...
