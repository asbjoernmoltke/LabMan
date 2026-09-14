import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

import pytest

from labman_app.presets import LAST_USED, PresetStore, params_from_dict, params_to_dict
from labman_core.schema import ParamMeta, Range
from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams as CE


class Mode(Enum):
    FAST = "fast"
    SLOW = "slow"


@dataclass
class Mixed:
    mode: Mode = Mode.FAST
    shape: Literal["gauss", "flat"] = "gauss"
    out: Path = Path("out")
    enabled: bool = True
    count: Annotated[int, ParamMeta(display="Count", bounds=Range(1, 10))] = 3
    guard: float | None = None


# ----- params <-> dict -----


def test_round_trip_coupling_efficiency_params() -> None:
    p = CE(power_start=2.0, power_steps=7, abort_below=0.25)
    data = json.loads(json.dumps(params_to_dict(p)))
    values, unknown = params_from_dict(CE, data)
    assert CE(**values) == p
    assert unknown == []


def test_to_dict_is_json_ready() -> None:
    data = params_to_dict(Mixed(mode=Mode.SLOW, out=Path("a") / "b"))
    assert data["mode"] == "slow"
    assert data["out"] == str(Path("a") / "b")
    json.dumps(data)


def test_to_dict_rejects_non_dataclass() -> None:
    with pytest.raises(TypeError):
        params_to_dict({"power_steps": 3})


def test_from_dict_coerces_json_types() -> None:
    values, _ = params_from_dict(Mixed, {"mode": "slow", "out": "x", "count": 4.0, "guard": 1})
    assert values["mode"] is Mode.SLOW
    assert values["out"] == Path("x")
    assert values["count"] == 4 and isinstance(values["count"], int)
    assert values["guard"] == 1.0 and isinstance(values["guard"], float)


def test_missing_fields_take_defaults_and_unknown_keys_are_reported() -> None:
    values, unknown = params_from_dict(Mixed, {"count": 5, "removed_field": 1})
    assert Mixed(**values) == Mixed(count=5)
    assert unknown == ["removed_field"]


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ({"mode": "medium"}, "not a valid Mode"),
        ({"shape": "square"}, "not one of"),
        ({"count": 2.5}, "expected an integer"),
        ({"count": True}, "expected an integer"),
        ({"enabled": "yes"}, "expected true/false"),
        ({"guard": "high"}, "expected a number"),
        ({"count": None}, "null"),
        ({"out": 3}, "expected a path"),
    ],
)
def test_from_dict_rejects_wrong_types(data: dict, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        params_from_dict(Mixed, data)


# ----- PresetStore -----


def test_one_file_per_task(tmp_path: Path) -> None:
    store = PresetStore("coupling_efficiency", tmp_path)
    assert store.path == tmp_path / "coupling_efficiency.json"


def test_save_load_and_names(tmp_path: Path) -> None:
    store = PresetStore("t", tmp_path)
    store.save("b 1550", CE(wavelength_nm=1550.0))
    store.save("A 1310", CE(wavelength_nm=1310.0))

    reopened = PresetStore("t", tmp_path)
    assert reopened.names() == ["A 1310", "b 1550"]
    assert reopened.load("A 1310")["wavelength_nm"] == 1310.0


def test_last_used_is_kept_apart_from_named_presets(tmp_path: Path) -> None:
    store = PresetStore("t", tmp_path)
    assert store.load_last_used() is None
    assert not store.has_last_used()

    store.save_last_used(CE(power_steps=9))

    assert store.has_last_used()
    assert store.load_last_used()["power_steps"] == 9
    assert store.names() == []
    assert LAST_USED in json.loads(store.path.read_text(encoding="utf-8"))


def test_load_missing_preset_raises_key_error(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="nope"):
        PresetStore("t", tmp_path).load("nope")


def test_delete(tmp_path: Path) -> None:
    store = PresetStore("t", tmp_path)
    store.save("p", CE())
    store.delete("p")
    store.delete("p")  # idempotent
    assert store.names() == []
    with pytest.raises(ValueError, match="last-used"):
        store.delete(LAST_USED)


@pytest.mark.parametrize("name", ["", "   ", " padded", LAST_USED, "__private", "x" * 101])
def test_invalid_names_are_rejected(tmp_path: Path, name: str) -> None:
    store = PresetStore("t", tmp_path)
    with pytest.raises(ValueError):
        store.save(name, CE())
    assert not store.path.exists()


def test_unreadable_file_is_set_aside_not_overwritten(tmp_path: Path) -> None:
    store = PresetStore("t", tmp_path)
    store.path.write_text("{broken", encoding="utf-8")
    assert store.names() == []

    store.save("new", CE())

    assert store.names() == ["new"]
    assert (tmp_path / "t.json.corrupt").read_text(encoding="utf-8") == "{broken"
