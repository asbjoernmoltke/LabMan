from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any

from labman_core.devices import Device
from labman_core.lab_config import DeviceConfig, LabConfig, SyncPolicy
from labman_core.roles import DeviceRole

logger = logging.getLogger("labman.registry")


class DeviceRegistry:
    """Owns the lifetime of all configured devices.

    Single source of truth for "which physical devices exist and what role does
    each play". The shell wraps this in `TaskShellServices` to expose only the
    `device(binding_name)` projection a task sees.
    """

    def __init__(self, config: LabConfig) -> None:
        self._config = config
        self._devices: dict[str, Device] = {}
        self._configs_by_name: dict[str, DeviceConfig] = {dc.name: dc for dc in config.devices}

    def instantiate_all(self) -> None:
        """Import each driver and instantiate. Idempotent (subsequent calls are no-ops).

        Raises if a driver fails to import or its constructor raises — the shell
        should catch and surface this to the user, since the app can't proceed
        without its hardware.
        """
        if self._devices:
            return
        for dc in self._config.devices:
            cls = _import_class(dc.driver)
            kwargs = dict(dc.args)
            # Pass the config name only to drivers that accept it. Checked via the
            # signature rather than catching TypeError, which would mask real
            # constructor errors (e.g. a misspelled arg in lab.yaml).
            if _accepts_kwarg(cls, "name"):
                kwargs.setdefault("name", dc.name)
            self._devices[dc.name] = cls(**kwargs)
            logger.info("instantiated device %r (%s, role=%s)", dc.name, dc.driver, dc.role.value)

    def device(self, name: str) -> Device:
        return self._devices[name]

    def names(self) -> list[str]:
        return list(self._devices)

    def role_of(self, name: str) -> DeviceRole:
        return self._configs_by_name[name].role

    def sync_policy_of(self, name: str) -> SyncPolicy:
        return self._configs_by_name[name].sync_policy

    def devices_by_role(self, role: DeviceRole) -> list[tuple[str, Device]]:
        return [
            (name, dev)
            for name, dev in self._devices.items()
            if self._configs_by_name[name].role == role
        ]

    async def shutdown_all(self) -> None:
        """Best-effort shutdown of every device. Logs and continues on failure.

        Called by the shell on app close, after the active task's
        `to_safe_state` has run.
        """
        for name, dev in self._devices.items():
            try:
                await dev.shutdown()
            except Exception as e:  # noqa: BLE001
                logger.warning("shutdown of device %r failed: %s", name, e)


def _accepts_kwarg(cls: Any, kwarg: str) -> bool:
    try:
        params = inspect.signature(cls).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        p.name == kwarg or p.kind is inspect.Parameter.VAR_KEYWORD for p in params
    )


def _import_class(dotted_path: str) -> Any:
    """Import a class from a dotted path like 'labman_core.simulators.SimLaser'."""
    if "." not in dotted_path:
        raise ValueError(f"driver path must be dotted (module.Class), got {dotted_path!r}")
    module_path, _, class_name = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
