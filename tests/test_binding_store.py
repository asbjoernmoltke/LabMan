from pathlib import Path

from labman_app.binding_store import BindingStore


def test_round_trip(tmp_path: Path) -> None:
    store = BindingStore(tmp_path / "state" / "bindings.json")
    store.save("coupling_efficiency", {"laser": "laser", "power_meter_in": "pm_b"})
    assert BindingStore(store.path).load("coupling_efficiency") == {
        "laser": "laser",
        "power_meter_in": "pm_b",
    }


def test_missing_file_loads_empty(tmp_path: Path) -> None:
    assert BindingStore(tmp_path / "nope.json").load("coupling_efficiency") == {}


def test_tasks_are_independent(tmp_path: Path) -> None:
    store = BindingStore(tmp_path / "bindings.json")
    store.save("a", {"laser": "l1"})
    store.save("b", {"laser": "l2"})
    store.save("a", {"laser": "l3"})
    assert store.load("a") == {"laser": "l3"}
    assert store.load("b") == {"laser": "l2"}
    assert store.load("c") == {}


def test_corrupt_file_loads_empty_and_is_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "bindings.json"
    path.write_text("{not json", encoding="utf-8")
    store = BindingStore(path)
    assert store.load("a") == {}
    store.save("a", {"laser": "l1"})
    assert store.load("a") == {"laser": "l1"}


def test_non_string_entries_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "bindings.json"
    path.write_text('{"a": {"laser": "l1", "pm": 3}, "b": "oops"}', encoding="utf-8")
    store = BindingStore(path)
    assert store.load("a") == {"laser": "l1"}
    assert store.load("b") == {}
