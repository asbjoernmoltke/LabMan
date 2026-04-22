from typing import Any, Protocol, runtime_checkable

from labman_core.context import TaskContext
from labman_core.roles import DeviceRole


@runtime_checkable
class Task(Protocol):
    """Contract every measurement task implements.

    The widget is the only Qt-touching surface; it is constructed lazily by
    build_widget() so labman_core never imports Qt. run_headless() runs the
    full acquire->persist->analyze->persist sequence without any UI.
    """

    name: str
    display_name: str
    required_bindings: dict[str, DeviceRole]
    params_cls: type

    def build_widget(self, shell: Any) -> Any: ...

    async def run_headless(self, ctx: TaskContext, params: Any) -> Any: ...
