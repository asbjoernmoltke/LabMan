from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labman_core.devices import Device
from labman_core.lab_config import DeviceConfig, DeviceSync, LabConfig, SyncPolicy
from labman_core.resource_lock import DEFAULT_LOCK_DIR, ResourceLock
from labman_core.roles import DeviceRole

logger = logging.getLogger("labman.registry")


@dataclass
class DeviceFailure:
    """A configured device that could not be brought up."""

    name: str
    driver: str
    error: Exception

    @property
    def message(self) -> str:
        return f"{type(self.error).__name__}: {self.error}"


class DeviceRegistry:
    """Owns the lifetime of all configured devices.

    Single source of truth for "which physical devices exist and what role does
    each play". The shell wraps this in `RegistryShellServices` to expose only
    the `device(binding_name)` projection a task sees.

    A device that fails to come up (import or constructor error, resource held
    by another process, or depending on a failed device) is recorded in
    `failures` and left out of every lookup; the rest of the lab still starts.
    """

    def __init__(self, config: LabConfig, lock_dir: Path = DEFAULT_LOCK_DIR) -> None:
        self._config = config
        self._lock_dir = Path(lock_dir)
        self._devices: dict[str, Device] = {}
        self._locks: dict[str, ResourceLock] = {}
        self._failures: dict[str, DeviceFailure] = {}
        self._synced: set[str] = set()
        self._instantiated = False
        self._configs_by_name: dict[str, DeviceConfig] = {dc.name: dc for dc in config.devices}

    def instantiate_all(self) -> dict[str, DeviceFailure]:
        """Bring up every configured device, in file order. Idempotent.

        Never raises for a single device; returns the failures (also available
        as `failures`) so the shell can report them.
        """
        if self._instantiated:
            return self.failures
        self._instantiated = True
        for dc in self._config.devices:
            try:
                self._instantiate(dc)
            except Exception as e:  # noqa: BLE001
                self._release_lock(dc.name)
                self._failures[dc.name] = DeviceFailure(dc.name, dc.driver, e)
                logger.error("device %r (%s) unavailable: %s", dc.name, dc.driver, e)
        return self.failures

    def _instantiate(self, dc: DeviceConfig) -> None:
        kwargs = {k: self._resolve_arg(dc.name, v) for k, v in dc.args.items()}
        if dc.resource is not None:
            lock = ResourceLock(dc.resource, self._lock_dir)
            lock.acquire()
            self._locks[dc.name] = lock
        cls = _import_class(dc.driver)
        # Pass the config name only to drivers that accept it. Checked via the
        # signature rather than catching TypeError, which would mask real
        # constructor errors (e.g. a misspelled arg in lab.yaml).
        if _accepts_kwarg(cls, "name"):
            kwargs.setdefault("name", dc.name)
        self._devices[dc.name] = cls(**kwargs)
        logger.info("instantiated device %r (%s, role=%s)", dc.name, dc.driver, dc.role.value)

    def _resolve_arg(self, owner: str, value: Any) -> Any:
        """Replace `{device: <name>}` with the already-instantiated device.

        Lets simulators (or drivers sharing a controller) reference each other
        from lab.yaml. Only devices declared earlier in the file can be referenced.
        """
        if isinstance(value, dict) and set(value) == {"device"}:
            ref = value["device"]
            if ref in self._failures:
                raise ValueError(f"depends on device {ref!r}, which is unavailable")
            if ref not in self._devices:
                raise ValueError(
                    f"device {owner!r}: arg references {ref!r}, "
                    "which is not declared earlier in lab.yaml"
                )
            return self._devices[ref]
        return value

    @property
    def failures(self) -> dict[str, DeviceFailure]:
        return dict(self._failures)

    def device(self, name: str) -> Device:
        if name in self._failures:
            raise KeyError(f"device {name!r} is unavailable: {self._failures[name].message}")
        return self._devices[name]

    def names(self) -> list[str]:
        """Names of available (successfully instantiated) devices."""
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

    def connect_sync(self, name: str) -> DeviceSync:
        """Sync a panel should apply when showing this device.

        The configured policy applies on the first successful use in a session
        (see `mark_synced`). After that LabMan owns the device state, so panels
        re-read it (`hydrate`) instead of pushing defaults again over whatever
        another task set; `skip` stays `skip`.
        """
        dc = self._configs_by_name[name]
        if name not in self._synced:
            return DeviceSync(dc.sync_policy, dict(dc.defaults))
        return DeviceSync("skip" if dc.sync_policy == "skip" else "hydrate")

    def mark_synced(self, name: str) -> None:
        self._synced.add(name)

    async def shutdown_all(self) -> None:
        """Best-effort shutdown of every device, then release resource locks.

        Called by the shell on app close, after the active task's
        `to_safe_state` has run. Logs and continues on failure.
        """
        for name, dev in self._devices.items():
            try:
                await dev.shutdown()
            except Exception as e:  # noqa: BLE001
                logger.warning("shutdown of device %r failed: %s", name, e)
        for name in list(self._locks):
            self._release_lock(name)

    def _release_lock(self, name: str) -> None:
        lock = self._locks.pop(name, None)
        if lock is None:
            return
        try:
            lock.release()
        except Exception as e:  # noqa: BLE001
            logger.warning("releasing resource lock for %r failed: %s", name, e)


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
