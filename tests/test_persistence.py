import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

import numpy as np
import pytest

from labman_core.persistence import (
    load_dataclass_h5,
    save_dataclass_h5,
    save_meta,
    save_params_json,
)


@dataclass
class Inner:
    values: np.ndarray
    label: str


@dataclass
class Outer:
    name: str
    count: int
    ratio: float
    ok: bool
    samples: np.ndarray
    flags: np.ndarray
    empty: np.ndarray
    inner: Inner | None = None
    missing: Inner | None = None


class Colour(Enum):
    RED = "red"


@dataclass
class Params:
    mode: Literal["a", "b"] = "a"
    colour: Colour = Colour.RED
    folder: Path = Path("x")
    limit: float | None = None
    numbers: list[int] = field(default_factory=lambda: [1, 2])


def test_dataclass_round_trip(tmp_path: Path) -> None:
    obj = Outer(
        name="run", count=3, ratio=0.25, ok=True,
        samples=np.arange(6.0).reshape(2, 3), flags=np.array([True, False]), empty=np.empty(0),
        inner=Inner(values=np.array([1.5, 2.5]), label="nested"),
    )
    path = tmp_path / "raw.h5"
    save_dataclass_h5(path, obj)

    loaded = load_dataclass_h5(path, Outer)

    assert (loaded.name, loaded.count, loaded.ratio, loaded.ok) == ("run", 3, 0.25, True)
    assert isinstance(loaded.count, int) and isinstance(loaded.ok, bool)
    assert np.array_equal(loaded.samples, obj.samples)
    assert loaded.flags.dtype == bool
    assert loaded.empty.shape == (0,)
    assert loaded.inner.label == "nested"
    assert np.array_equal(loaded.inner.values, obj.inner.values)
    assert loaded.missing is None


def test_unsupported_field_type_raises(tmp_path: Path) -> None:
    @dataclass
    class Bad:
        payload: object

    with pytest.raises(TypeError, match="cannot store"):
        save_dataclass_h5(tmp_path / "bad.h5", Bad(payload=object()))


def test_save_params_json(tmp_path: Path) -> None:
    path = tmp_path / "params.json"
    save_params_json(path, Params())
    assert json.loads(path.read_text()) == {
        "mode": "a", "colour": "red", "folder": "x", "limit": None, "numbers": [1, 2]
    }


def test_save_meta_includes_extra(tmp_path: Path) -> None:
    path = tmp_path / "meta.json"
    save_meta(path, task_name="t", devices={"aligner": object()}, extra={"stop_reason": "stopped"})
    meta = json.loads(path.read_text())
    assert meta["task_name"] == "t"
    assert meta["devices"] == {"aligner": "object"}
    assert meta["stop_reason"] == "stopped"
    assert "saved_at_utc" in meta
