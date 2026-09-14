import json
from pathlib import Path

from labman_app.presets import LAST_USED, PresetStore
from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams as CE


def _bar(tmp_path: Path, confirm: bool = True):
    from labman_app.forms import _build_form
    from labman_app.widgets.preset_bar import PresetBar

    store = PresetStore("coupling_efficiency", tmp_path)
    form, getter, setter = _build_form(CE, None)
    bar = PresetBar(store, getter, setter)
    bar._form_keepalive = form  # otherwise Qt deletes the form's widgets when it's collected
    bar._confirm = lambda question: confirm  # no modal dialogs in tests
    return bar, store, getter, setter


def test_empty_store_disables_load_and_delete(qapp, tmp_path: Path) -> None:
    bar, _store, _getter, _setter = _bar(tmp_path)
    assert bar._combo.count() == 0
    assert not bar._load_btn.isEnabled()
    assert not bar._delete_btn.isEnabled()
    assert bar.load_selected() is False


def test_save_then_load_round_trip(qapp, tmp_path: Path) -> None:
    bar, store, getter, setter = _bar(tmp_path)
    setter({"power_steps": 12, "wavelength_nm": 1310.0})
    assert bar.save_as("sweep 12")
    assert store.names() == ["sweep 12"]
    assert bar._combo.currentData() == "sweep 12"

    setter({"power_steps": 3})
    assert bar.load_selected()

    p = getter()
    assert p.power_steps == 12
    assert p.wavelength_nm == 1310.0
    assert "Loaded sweep 12" in bar.message


def test_save_as_asks_for_name_and_strips_it(qapp, tmp_path: Path) -> None:
    bar, store, _getter, _setter = _bar(tmp_path)
    bar._ask_name = lambda: "  fast  "
    assert bar.save_as()
    assert store.names() == ["fast"]

    bar._ask_name = lambda: None  # dialog cancelled
    assert bar.save_as() is False


def test_overwrite_needs_confirmation(qapp, tmp_path: Path) -> None:
    bar, store, _getter, setter = _bar(tmp_path, confirm=False)
    setter({"power_steps": 12})
    assert bar.save_as("p")  # new name: no confirmation needed
    setter({"power_steps": 20})
    assert bar.save_as("p") is False
    assert store.load("p")["power_steps"] == 12


def test_reserved_name_is_rejected(qapp, tmp_path: Path) -> None:
    bar, store, _getter, _setter = _bar(tmp_path)
    assert bar.save_as(LAST_USED) is False
    assert "reserved" in bar.message
    assert store.names() == []


def test_save_with_invalid_form_reports_error(qapp, tmp_path: Path) -> None:
    bar, store, _getter, _setter = _bar(tmp_path)

    def invalid_form():
        raise ValueError("Start: empty numeric value")

    bar._get_params = invalid_form
    assert bar.save_as("p") is False
    assert "Cannot save: Start: empty numeric value" in bar.message
    assert store.names() == []


def test_invalid_preset_leaves_form_unchanged(qapp, tmp_path: Path) -> None:
    bar, store, getter, setter = _bar(tmp_path)
    store.path.write_text(
        json.dumps({"hand edited": {"power_steps": 5000, "wavelength_nm": 1310.0}}),
        encoding="utf-8",
    )
    bar.refresh()
    setter({"power_steps": 12})

    assert bar.load_selected() is False
    assert "outside [2, 1000]" in bar.message
    assert getter().power_steps == 12
    assert getter().wavelength_nm == 1550.0


def test_unknown_fields_are_reported_on_load(qapp, tmp_path: Path) -> None:
    bar, store, getter, _setter = _bar(tmp_path)
    store.path.write_text(
        json.dumps({"old": {"power_steps": 8, "laser_current_ma": 40}}), encoding="utf-8"
    )
    bar.refresh()
    assert bar.load_selected()
    assert getter().power_steps == 8
    assert "laser_current_ma" in bar.message


def test_delete_needs_confirmation(qapp, tmp_path: Path) -> None:
    bar, store, _getter, _setter = _bar(tmp_path, confirm=False)
    bar.save_as("p")
    assert bar.delete_selected() is False
    assert store.names() == ["p"]

    bar._confirm = lambda question: True
    assert bar.delete_selected()
    assert store.names() == []
    assert bar._combo.count() == 0


def test_last_used_entry_is_loadable_but_not_deletable(qapp, tmp_path: Path) -> None:
    bar, store, getter, _setter = _bar(tmp_path)
    store.save_last_used(CE(power_steps=33))
    store.save("named", CE())
    bar.refresh()

    assert bar._combo.currentData() == LAST_USED
    assert not bar._delete_btn.isEnabled()
    assert bar.delete_selected() is False

    assert bar.load_selected()
    assert getter().power_steps == 33
    assert "(last used)" in bar.message
