"""Generic run persistence: dataclasses to HDF5, params and meta to JSON. No Qt.

Tasks call these from `task.py` with paths from `RunStorage`; nothing here
builds paths. Dataclass mapping:

- numpy arrays / lists / tuples -> datasets
- str, int, float, bool, numpy scalars, Enum values, Path -> attributes
- nested dataclasses -> groups
- None -> listed in the `__none__` attribute
"""

from __future__ import annotations

import dataclasses
import enum
import json
import subprocess
import types
import typing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import h5py
import numpy as np

_NONE_ATTR = "__none__"


def save_dataclass_h5(path: Path, obj: Any) -> None:
    with h5py.File(path, "w") as f:
        _write(f, obj)


def load_dataclass_h5(path: Path, cls: type) -> Any:
    """Inverse of `save_dataclass_h5` — lets analysis re-run on saved raw data."""
    with h5py.File(path, "r") as f:
        return _read(f, cls)


def save_params_json(path: Path, params: Any) -> None:
    path.write_text(
        json.dumps(dataclasses.asdict(params), indent=2, default=_json_default),
        encoding="utf-8",
    )


def save_meta(
    path: Path,
    *,
    task_name: str,
    devices: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> None:
    meta = {
        "task_name": task_name,
        "saved_at_utc": datetime.now(UTC).isoformat(),
        "git_hash": _git_hash(),
        "devices": {binding: type(dev).__name__ for binding, dev in devices.items()},
        **(extra or {}),
    }
    path.write_text(json.dumps(meta, indent=2, default=_json_default), encoding="utf-8")


def _write(group: h5py.Group, obj: Any) -> None:
    if not dataclasses.is_dataclass(obj) or isinstance(obj, type):
        raise TypeError(f"expected a dataclass instance, got {type(obj).__name__}")
    group.attrs["__type__"] = type(obj).__name__
    none_fields: list[str] = []
    for field in dataclasses.fields(obj):
        value = getattr(obj, field.name)
        if value is None:
            none_fields.append(field.name)
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            _write(group.create_group(field.name), value)
        elif isinstance(value, np.ndarray | list | tuple):
            group.create_dataset(field.name, data=np.asarray(value))
        elif isinstance(value, enum.Enum):
            group.attrs[field.name] = value.value
        elif isinstance(value, Path):
            group.attrs[field.name] = str(value)
        elif isinstance(value, str | int | float | bool | np.generic):
            group.attrs[field.name] = value
        else:
            raise TypeError(
                f"{type(obj).__name__}.{field.name}: cannot store {type(value).__name__} in HDF5"
            )
    if none_fields:
        group.attrs[_NONE_ATTR] = json.dumps(none_fields)


def _read(group: h5py.Group, cls: type) -> Any:
    hints = get_type_hints(cls)
    none_fields = set(json.loads(group.attrs.get(_NONE_ATTR, "[]")))
    kwargs: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        name = field.name
        if name in none_fields:
            kwargs[name] = None
        elif name in group and isinstance(group[name], h5py.Group):
            kwargs[name] = _read(group[name], _dataclass_type(hints[name]))
        elif name in group:
            kwargs[name] = group[name][()]
        elif name in group.attrs:
            kwargs[name] = _python_scalar(group.attrs[name])
        else:
            raise KeyError(f"{cls.__name__}.{name} missing from HDF5 file")
    return cls(**kwargs)


def _dataclass_type(t: Any) -> type:
    if get_origin(t) in (typing.Union, types.UnionType):
        candidates = [a for a in get_args(t) if dataclasses.is_dataclass(a)]
        if len(candidates) == 1:
            return candidates[0]
    if dataclasses.is_dataclass(t):
        return t
    raise TypeError(f"cannot read group into non-dataclass type {t!r}")


def _python_scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.generic):
        return value.item()
    return value


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _git_hash() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False, timeout=2
        )
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None
