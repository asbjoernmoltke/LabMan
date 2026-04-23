from typing import Protocol, runtime_checkable

from labman_core.devices import Device
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

    def make_storage(
        self, task_name: str, opts: StorageOptions | None = None
    ) -> RunStorage: ...
