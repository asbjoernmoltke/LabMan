"""Qt-free half of the shell: task discovery, device binding, ShellServices.

Kept separate from `shell.py` so binding logic is testable without a
QApplication. Nothing here imports Qt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from labman_app.presets import PresetStore
from labman_core.devices import Device
from labman_core.lab_config import DeviceSync
from labman_core.registry import DeviceRegistry
from labman_core.roles import DeviceRole
from labman_core.storage import DEFAULT_DATA_ROOT, RunStorage, StorageOptions
from labman_core.task import Task

logger = logging.getLogger("labman.shell")

TASK_ENTRY_POINT_GROUP = "labman.tasks"


def discover_tasks(group: str = TASK_ENTRY_POINT_GROUP) -> list[Task]:
    """Load every task registered under the entry-point group, sorted by display name.

    A task that fails to import is logged and skipped, so one broken task
    doesn't take down the shell.
    """
    tasks: list[Task] = []
    for ep in entry_points(group=group):
        try:
            obj = ep.load()
            task = obj() if isinstance(obj, type) else obj
        except Exception:
            logger.exception("failed to load task entry point %r", ep.name)
            continue
        tasks.append(task)
    return sorted(tasks, key=lambda t: t.display_name)


def candidates_for(role: DeviceRole, registry: DeviceRegistry) -> list[str]:
    return [name for name, _ in registry.devices_by_role(role)]


def default_bindings(
    required: dict[str, DeviceRole],
    registry: DeviceRegistry,
    remembered: dict[str, str] | None = None,
) -> dict[str, str | None]:
    """Propose a device per binding.

    Priority per binding: the remembered device (if still available with the
    right role), then a device whose name equals the binding name, then the
    first free device of the role. A binding with no free candidate gets None —
    never silently share one device between two bindings (e.g. power_meter_in
    and power_meter_out on the same meter).
    """
    remembered = remembered or {}
    chosen: dict[str, str] = {}
    used: set[str] = set()

    def take(binding: str, device: str) -> None:
        chosen[binding] = device
        used.add(device)

    for binding, role in required.items():
        device = remembered.get(binding)
        if device and device not in used and device in candidates_for(role, registry):
            take(binding, device)
    for binding, role in required.items():
        if (
            binding not in chosen
            and binding not in used
            and binding in candidates_for(role, registry)
        ):
            take(binding, binding)
    for binding, role in required.items():
        if binding in chosen:
            continue
        free = [n for n in candidates_for(role, registry) if n not in used]
        if free:
            take(binding, free[0])
    return {b: chosen.get(b) for b in required}


def validate_bindings(
    required: dict[str, DeviceRole],
    bindings: dict[str, str | None],
    registry: DeviceRegistry,
) -> list[str]:
    """Return human-readable problems; empty list means the bindings are usable."""
    errors: list[str] = []
    known = set(registry.names())
    failures = registry.failures
    seen: dict[str, str] = {}
    for binding, role in required.items():
        device = bindings.get(binding)
        if not device:
            errors.append(f"{binding}: no device selected")
            continue
        if device in failures:
            errors.append(f"{binding}: {device!r} is unavailable ({failures[device].message})")
            continue
        if device not in known:
            errors.append(f"{binding}: unknown device {device!r}")
            continue
        if registry.role_of(device) != role:
            errors.append(
                f"{binding}: {device!r} is a {registry.role_of(device).value}, "
                f"expected {role.value}"
            )
        if device in seen:
            errors.append(f"{binding}: {device!r} is already bound to {seen[device]}")
        else:
            seen[device] = binding
    return errors


class RegistryShellServices:
    """`ShellServices` for one opened task: binding names resolve through the registry.

    `presets_root=None` disables presets (plain params form, no last-used updates).
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        bindings: dict[str, str],
        data_root: Path = DEFAULT_DATA_ROOT,
        presets_root: Path | None = None,
    ) -> None:
        self._registry = registry
        self._bindings = dict(bindings)
        self._data_root = Path(data_root)
        self._presets_root = Path(presets_root) if presets_root is not None else None

    @property
    def bindings(self) -> dict[str, str]:
        return dict(self._bindings)

    def device(self, binding_name: str) -> Device:
        return self._registry.device(self._bindings[binding_name])

    def device_sync(self, binding_name: str) -> DeviceSync:
        return self._registry.connect_sync(self._bindings[binding_name])

    def bound_devices(self) -> dict[str, Device]:
        return {b: self._registry.device(name) for b, name in self._bindings.items()}

    def make_storage(
        self, task_name: str, opts: StorageOptions | None = None
    ) -> RunStorage:
        return RunStorage(task_name, opts or StorageOptions(), self._data_root)

    def params_form(self, task_name: str, params_cls: type) -> tuple[Any, Callable[[], Any]]:
        # Imported here so this module stays importable without Qt.
        from labman_app.forms import build_params_form, build_params_form_with_presets

        if self._presets_root is None:
            return build_params_form(params_cls)
        return build_params_form_with_presets(
            params_cls, PresetStore(task_name, self._presets_root)
        )

    def run_succeeded(self, task_name: str, params: Any) -> None:
        if self._presets_root is None:
            return
        try:
            PresetStore(task_name, self._presets_root).save_last_used(params)
        except OSError:
            logger.warning("could not save last-used params for %r", task_name, exc_info=True)
