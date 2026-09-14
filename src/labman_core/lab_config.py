from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from labman_core.roles import DeviceRole

SyncPolicy = Literal["hydrate", "push_defaults", "skip"]
SYNC_POLICIES: tuple[str, ...] = ("hydrate", "push_defaults", "skip")


@dataclass
class DeviceSync:
    """What a device panel does when a task first shows the device.

    hydrate       - read every setable from hardware into its widget.
    push_defaults - write `defaults` (setable name -> value, in order), then hydrate.
    skip          - no initial read or write; widgets keep their initial values.
    """

    policy: SyncPolicy = "hydrate"
    defaults: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceConfig:
    """Declarative spec for one device in a lab.yaml."""

    name: str
    driver: str                       # full dotted path, e.g. "labman_core.simulators.SimLaser"
    role: DeviceRole
    args: dict[str, Any] = field(default_factory=dict)
    sync_policy: SyncPolicy = "hydrate"
    defaults: dict[str, Any] = field(default_factory=dict)
    resource: str | None = None       # physical resource id; one LabMan process may hold it


@dataclass
class LabConfig:
    """Parsed contents of a lab.yaml.

    Schema (v1):

        version: 1
        devices:
          <name>:
            driver: <module.Class>
            role: <laser|power_meter|camera|spectrometer|stage>
            args: { ... }            # optional, kwargs for the driver;
                                     # `{device: <name>}` passes an earlier device
            sync_policy: <hydrate|push_defaults|skip>   # optional, default hydrate
            defaults: { <setable>: <value> }            # required with push_defaults only
            resource: <string>       # optional, e.g. "GPIB0::5::INSTR"; unique per file,
                                     # locked machine-wide while LabMan holds the device
    """

    version: int
    devices: list[DeviceConfig]

    @staticmethod
    def from_path(path: Path) -> LabConfig:
        with Path(path).open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected mapping at top level")
        return LabConfig.from_dict(data)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> LabConfig:
        version = data.get("version")
        if version != 1:
            raise ValueError(f"Unsupported lab.yaml version: {version!r} (expected 1)")

        devices_block = data.get("devices") or {}
        if not isinstance(devices_block, dict):
            raise ValueError("`devices` must be a mapping of name -> spec")

        devices: list[DeviceConfig] = []
        for name, spec in devices_block.items():
            devices.append(_parse_device(name, spec))

        owners: dict[str, str] = {}
        for dc in devices:
            if dc.resource is None:
                continue
            if dc.resource in owners:
                raise ValueError(
                    f"devices {owners[dc.resource]!r} and {dc.name!r} both claim "
                    f"resource {dc.resource!r}"
                )
            owners[dc.resource] = dc.name

        return LabConfig(version=version, devices=devices)


def _parse_device(name: str, spec: Any) -> DeviceConfig:
    if not isinstance(spec, dict):
        raise ValueError(f"device {name!r}: expected mapping, got {type(spec).__name__}")
    try:
        driver = spec["driver"]
        role_str = spec["role"]
    except KeyError as e:
        raise ValueError(f"device {name!r} missing required field: {e.args[0]!r}") from e

    try:
        role = DeviceRole(role_str)
    except ValueError as e:
        valid = [r.value for r in DeviceRole]
        raise ValueError(
            f"device {name!r}: unknown role {role_str!r}; valid: {valid}"
        ) from e

    args = spec.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError(f"device {name!r}: `args` must be a mapping")

    sync_policy = spec.get("sync_policy", "hydrate")
    if sync_policy not in SYNC_POLICIES:
        raise ValueError(
            f"device {name!r}: unknown sync_policy {sync_policy!r}; "
            "valid: hydrate, push_defaults, skip"
        )

    defaults = spec.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError(f"device {name!r}: `defaults` must be a mapping of setable -> value")
    if sync_policy == "push_defaults" and not defaults:
        raise ValueError(f"device {name!r}: sync_policy push_defaults requires `defaults`")
    if defaults and sync_policy != "push_defaults":
        raise ValueError(f"device {name!r}: `defaults` only apply with sync_policy push_defaults")

    resource = spec.get("resource")
    if resource is not None and (not isinstance(resource, str) or not resource.strip()):
        raise ValueError(f"device {name!r}: `resource` must be a non-empty string")

    return DeviceConfig(
        name=name,
        driver=driver,
        role=role,
        args=args,
        sync_policy=sync_policy,
        defaults=defaults,
        resource=resource,
    )
