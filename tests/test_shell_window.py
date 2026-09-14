from pathlib import Path

import pytest

from labman_app.binding_store import BindingStore
from labman_core.lab_config import LabConfig
from labman_core.registry import DeviceRegistry
from labman_tasks.coupling_efficiency import CouplingEfficiencyTask

EXAMPLE_LAB = Path(__file__).parents[1] / "examples" / "lab.sim.yaml"
BINDINGS = {b: b for b in CouplingEfficiencyTask.required_bindings}

LASER = {"driver": "labman_core.simulators.SimLaser", "role": "laser"}
PM = {"driver": "labman_core.simulators.SimPowerMeter", "role": "power_meter"}


class RecordingTask(CouplingEfficiencyTask):
    def __init__(self) -> None:
        self.safe_state_calls = 0

    async def to_safe_state(self, devices) -> None:
        self.safe_state_calls += 1
        await super().to_safe_state(devices)


def _window(qapp, tmp_path: Path, task=None, devices=None, store=None, presets_root=None):
    from labman_app.shell import ShellWindow

    if devices is None:
        config = LabConfig.from_path(EXAMPLE_LAB)
    else:
        config = LabConfig.from_dict({"version": 1, "devices": devices})
    reg = DeviceRegistry(config)
    reg.instantiate_all()
    task = task or CouplingEfficiencyTask()
    win = ShellWindow(
        reg, [task], data_root=tmp_path, binding_store=store, presets_root=presets_root
    )
    return win, reg, task


def _panel_value(win, binding: str, setable: str):
    return win.active_widget._device_panels[binding].setable_widgets[setable].value()


def test_binding_page_preselects_defaults(qapp, tmp_path: Path) -> None:
    win, _reg, task = _window(qapp, tmp_path)
    win.show_binding_page(task)
    assert win.current_bindings() == BINDINGS
    assert win._unavailable_label is None


async def test_open_task_hosts_widget_and_initializes(qapp, tmp_path: Path) -> None:
    win, reg, task = _window(qapp, tmp_path)
    await reg.device("laser").set_power_mw(12.0)

    await win.open_task(task, BINDINGS)

    widget = win.active_widget
    assert widget is not None
    assert _panel_value(win, "laser", "power") == pytest.approx(12.0)
    assert len(widget._poll_tasks) == 3
    await win.shutdown()


async def test_open_task_rejects_invalid_bindings(qapp, tmp_path: Path) -> None:
    win, _reg, task = _window(qapp, tmp_path)
    bad = dict(BINDINGS, power_meter_out="power_meter_in")
    with pytest.raises(ValueError, match="already bound"):
        await win.open_task(task, bad)
    assert win.active_widget is None


async def test_close_active_task_runs_safe_state(qapp, tmp_path: Path) -> None:
    win, reg, task = _window(qapp, tmp_path, task=RecordingTask())
    await win.open_task(task, BINDINGS)
    widget = win.active_widget
    laser = reg.device("laser")
    await laser.set_power_mw(20.0)
    await laser.set_enabled(True)

    await win.close_active_task()

    assert task.safe_state_calls == 1
    state = await laser.get_state()
    assert state.power_mw == 0.0
    assert state.enabled is False
    assert win.active_widget is None
    assert widget._poll_tasks == []  # widget.shutdown() stopped polling


async def test_window_close_runs_safe_state_then_accepts(qapp, tmp_path: Path) -> None:
    win, reg, task = _window(qapp, tmp_path, task=RecordingTask())
    await win.open_task(task, BINDINGS)
    widget = win.active_widget
    await reg.device("laser").set_power_mw(20.0)

    win.close()  # first close is deferred until safe-state has run
    assert win._shutdown_future is not None
    await win._shutdown_future

    assert task.safe_state_calls == 1
    assert (await reg.device("laser").get_state()).power_mw == 0.0
    assert win._shutdown_complete
    assert widget._poll_tasks == []


# ----- connect-time sync policy -----


async def test_push_defaults_applied_on_first_open_only(qapp, tmp_path: Path) -> None:
    devices = {
        "laser": {**LASER, "sync_policy": "push_defaults",
                  "defaults": {"wavelength": 1310.0, "power": 5.0}},
        "power_meter_in": PM,
        "power_meter_out": PM,
    }
    win, reg, task = _window(qapp, tmp_path, devices=devices)
    laser = reg.device("laser")

    await win.open_task(task, BINDINGS)
    assert laser.wavelength_nm == 1310.0
    assert _panel_value(win, "laser", "wavelength") == pytest.approx(1310.0)
    assert _panel_value(win, "laser", "power") == pytest.approx(5.0)

    await win.close_active_task()
    await laser.set_wavelength_nm(1550.0)  # state changed later in the session

    await win.open_task(task, BINDINGS)
    assert laser.wavelength_nm == 1550.0  # not pushed again
    assert _panel_value(win, "laser", "wavelength") == pytest.approx(1550.0)  # hydrated
    await win.shutdown()


async def test_skip_policy_does_not_read_hardware(qapp, tmp_path: Path) -> None:
    devices = {
        "laser": {**LASER, "sync_policy": "skip"},
        "power_meter_in": PM,
        "power_meter_out": PM,
    }
    win, reg, task = _window(qapp, tmp_path, devices=devices)
    await reg.device("laser").set_wavelength_nm(1310.0)

    await win.open_task(task, BINDINGS)
    with pytest.raises(ValueError, match="empty"):  # widget starts blank
        _panel_value(win, "laser", "wavelength")
    assert _panel_value(win, "power_meter_in", "wavelength") == pytest.approx(1550.0)  # hydrated
    await win.shutdown()


async def test_failed_default_push_returns_to_binding_page(qapp, tmp_path: Path) -> None:
    devices = {
        "laser": {**LASER, "sync_policy": "push_defaults", "defaults": {"power": 500.0}},
        "power_meter_in": PM,
        "power_meter_out": PM,
    }
    win, reg, task = _window(qapp, tmp_path, task=RecordingTask(), devices=devices)

    await win.open_task(task, BINDINGS)

    assert win.active_widget is None
    assert "Failed to initialize devices" in win._binding_error.text()
    assert task.safe_state_calls == 1
    # Not marked synced: the next open tries the configured policy again.
    assert reg.connect_sync("laser").policy == "push_defaults"


# ----- remembered bindings -----


async def test_bindings_are_remembered_across_windows(qapp, tmp_path: Path) -> None:
    store = BindingStore(tmp_path / "bindings.json")
    devices = {"laser": LASER, "pm_a": PM, "pm_b": PM}
    chosen = {"laser": "laser", "power_meter_in": "pm_b", "power_meter_out": "pm_a"}

    win, _reg, task = _window(qapp, tmp_path, devices=devices, store=store)
    win.show_binding_page(task)
    assert win.current_bindings()["power_meter_in"] == "pm_a"  # nothing remembered yet
    await win.open_task(task, chosen)
    await win.shutdown()
    assert store.load(task.name) == chosen

    win2, _reg2, task2 = _window(qapp, tmp_path, devices=devices, store=store)
    win2.show_binding_page(task2)
    assert win2.current_bindings() == chosen


async def test_failed_open_does_not_save_bindings(qapp, tmp_path: Path) -> None:
    store = BindingStore(tmp_path / "bindings.json")
    devices = {
        "laser": {**LASER, "sync_policy": "push_defaults", "defaults": {"power": 500.0}},
        "power_meter_in": PM,
        "power_meter_out": PM,
    }
    win, _reg, task = _window(qapp, tmp_path, devices=devices, store=store)
    await win.open_task(task, BINDINGS)
    assert store.load(task.name) == {}


# ----- presets -----


async def test_presets_wired_into_task_form_and_last_used_follows_runs(
    qapp, tmp_path: Path
) -> None:
    from labman_app.presets import PresetStore
    from labman_app.widgets.preset_bar import PresetBar
    from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams

    presets_root = tmp_path / "presets"
    win, _reg, task = _window(qapp, tmp_path, presets_root=presets_root)
    await win.open_task(task, BINDINGS)
    widget = win.active_widget
    assert widget.findChild(PresetBar) is not None

    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=2.0, power_steps=3, averages_per_point=1, settle_time_s=0.0
    )
    await widget._run(params)
    assert PresetStore(task.name, presets_root).load_last_used()["power_steps"] == 3

    await win.close_active_task()
    await win.open_task(task, BINDINGS)
    assert win.active_widget._get_params() == params  # form reopens on last-used values
    await win.shutdown()


async def test_no_preset_bar_without_presets_root(qapp, tmp_path: Path) -> None:
    from labman_app.widgets.preset_bar import PresetBar

    win, _reg, task = _window(qapp, tmp_path)
    await win.open_task(task, BINDINGS)
    assert win.active_widget.findChild(PresetBar) is None
    await win.shutdown()


# ----- unavailable devices -----


def test_binding_page_lists_unavailable_devices(qapp, tmp_path: Path) -> None:
    devices = {
        "laser": LASER,
        "power_meter_in": PM,
        "pm_broken": {"driver": "no_such_pkg.Meter", "role": "power_meter"},
    }
    win, _reg, task = _window(qapp, tmp_path, devices=devices)
    win.show_binding_page(task)

    assert win._unavailable_label is not None
    assert "pm_broken" in win._unavailable_label.text()
    assert win.current_bindings()["power_meter_out"] is None
    assert "unavailable" in win.statusBar().currentMessage()
