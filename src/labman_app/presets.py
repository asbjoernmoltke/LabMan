"""Per-task parameter presets (Presets in CLAUDE.md). No Qt imports.

One JSON file per task at `app/presets/<task_name>.json`, mapping preset name
-> {field: value}. The reserved key `__last_used__` holds the params of the
last successful run. The store does not validate values: loading goes through
the params form, the same path as manual entry.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import types
import typing
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

LAST_USED = "__last_used__"
DEFAULT_PRESETS_ROOT: Path = Path("app") / "presets"
MAX_NAME_LENGTH = 100

logger = logging.getLogger("labman.presets")


class PresetStore:
    def __init__(self, task_name: str, root: Path = DEFAULT_PRESETS_ROOT) -> None:
        self.task_name = task_name
        self.path = Path(root) / f"{task_name}.json"

    def names(self) -> list[str]:
        """User preset names, case-insensitively sorted; excludes `__last_used__`."""
        data = self._read()
        return sorted(
            (k for k, v in data.items() if k != LAST_USED and isinstance(v, dict)),
            key=str.casefold,
        )

    def has_last_used(self) -> bool:
        return isinstance(self._read().get(LAST_USED), dict)

    def load(self, name: str) -> dict[str, Any]:
        """Raw field values of a preset (or `LAST_USED`). Raises KeyError if absent."""
        entry = self._read().get(name)
        if not isinstance(entry, dict):
            raise KeyError(f"no preset named {name!r}")
        return dict(entry)

    def load_last_used(self) -> dict[str, Any] | None:
        try:
            return self.load(LAST_USED)
        except KeyError:
            return None

    def save(self, name: str, params: Any) -> None:
        validate_preset_name(name)
        self._update(name, params_to_dict(params))

    def save_last_used(self, params: Any) -> None:
        self._update(LAST_USED, params_to_dict(params))

    def delete(self, name: str) -> None:
        """Delete a user preset. No-op if it doesn't exist."""
        if name == LAST_USED:
            raise ValueError("the last-used entry cannot be deleted")
        data = self._read()
        if name in data:
            del data[name]
            self._write(data)

    def _update(self, key: str, value: dict[str, Any]) -> None:
        data = self._read()
        data[key] = value
        self._write(data)

    def _read(self) -> dict[str, Any]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("presets file %s is unreadable; treating as empty", self.path)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._set_aside_if_unreadable()
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def _set_aside_if_unreadable(self) -> None:
        """Never silently overwrite a presets file that could not be parsed."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        try:
            if isinstance(json.loads(text), dict):
                return
        except json.JSONDecodeError:
            pass
        backup = self.path.with_name(self.path.name + ".corrupt")
        self.path.replace(backup)
        logger.warning("moved unreadable presets file to %s", backup)


def validate_preset_name(name: str) -> None:
    if not name.strip():
        raise ValueError("preset name is empty")
    if name != name.strip():
        raise ValueError("preset name has leading or trailing whitespace")
    if name.startswith("__"):
        raise ValueError("preset names starting with '__' are reserved")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"preset name is longer than {MAX_NAME_LENGTH} characters")


def params_to_dict(params: Any) -> dict[str, Any]:
    """JSON-ready {field: value} for a params dataclass instance."""
    if not dataclasses.is_dataclass(params) or isinstance(params, type):
        raise TypeError(f"expected a params dataclass instance, got {params!r}")
    return {f.name: _to_json(getattr(params, f.name)) for f in dataclasses.fields(params)}


def params_from_dict(cls: type, data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Typed field values for `cls` from JSON data.

    Returns `(values, unknown_keys)`. Fields missing from `data` take their
    dataclass defaults (presets saved before a field existed keep loading).
    Raises ValueError naming the field on a value of the wrong type. Bounds
    are NOT checked here — the params form does that.
    """
    hints = get_type_hints(cls)
    fields = dataclasses.fields(cls)
    values: dict[str, Any] = {}
    for f in fields:
        if f.name in data:
            values[f.name] = _coerce(f.name, hints[f.name], data[f.name])
        elif f.default is not dataclasses.MISSING:
            values[f.name] = f.default
        elif f.default_factory is not dataclasses.MISSING:
            values[f.name] = f.default_factory()
        else:
            raise ValueError(f"{f.name}: missing and has no default")
    unknown = sorted(set(data) - {f.name for f in fields})
    return values, unknown


def _to_json(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple | list):
        return [_to_json(v) for v in value]
    return value


def _coerce(name: str, t: Any, value: Any) -> Any:
    origin = get_origin(t)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(t) if a is not type(None)]
        if value is None:
            if len(args) < len(get_args(t)):
                return None
            raise ValueError(f"{name}: null not allowed")
        return _coerce(name, args[0], value) if len(args) == 1 else value
    if value is None:
        raise ValueError(f"{name}: null not allowed")
    if origin is typing.Literal:
        if value in get_args(t):
            return value
        raise ValueError(f"{name}: {value!r} is not one of {list(get_args(t))}")
    if not isinstance(t, type):
        return value
    if issubclass(t, enum.Enum):
        try:
            return t(value)
        except ValueError:
            raise ValueError(f"{name}: {value!r} is not a valid {t.__name__}") from None
    if t is bool:
        if isinstance(value, bool):
            return value
        raise ValueError(f"{name}: expected true/false, got {value!r}")
    if t is int:
        is_integral = isinstance(value, int) or (isinstance(value, float) and value.is_integer())
        if isinstance(value, bool) or not is_integral:
            raise ValueError(f"{name}: expected an integer, got {value!r}")
        return int(value)
    if t is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{name}: expected a number, got {value!r}")
        return float(value)
    if t is str:
        if not isinstance(value, str):
            raise ValueError(f"{name}: expected text, got {value!r}")
        return value
    if issubclass(t, Path):
        if not isinstance(value, str):
            raise ValueError(f"{name}: expected a path, got {value!r}")
        return t(value)
    return value
