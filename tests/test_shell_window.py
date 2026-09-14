from pathlib import Path

import pytest

from labman_core.lab_config import LabConfig
from labman_core.registry import DeviceRegistry
from labman_tasks.coupling_efficiency import CouplingEfficiencyTask

EXAMPLE_LAB = Path(__file__).parents[1] / "examples" / "lab.sim.yaml"
BINDINGS = {b: b for b in CouplingEfficiencyTask.required_bindings}


class RecordingTask(CouplingEfficiencyTask):
    def __init__(self) -> None:
        self.safe_state_calls = 0

    async def to_safe_state(self, devices) -> None:
        self.safe_state_calls += 1
        await super().to_safe_state(devices)


def _window(qapp, tmp_path: Path, task=None):
    from labman_app.shell import ShellWindow

    reg = DeviceRegistry(LabConfig.from_path(EXAMPLE_LAB))
    reg.instantiate_all()
    task = task or CouplingEfficiencyTask()
    return ShellWindow(reg, [task], data_root=tmp_path), reg, task


def test_binding_page_preselects_defaults(qapp, tmp_path: Path) -> None:
    win, _reg, task = _window(qapp, tmp_path)
    win.show_binding_page(task)
    assert win.current_bindings() == BINDINGS


async def test_open_task_hosts_widget_and_initializes(qapp, tmp_path: Path) -> None:
    win, reg, task = _window(qapp, tmp_path)
    await reg.device("laser").set_power_mw(12.0)

    await win.open_task(task, BINDINGS)

    widget = win.active_widget
    assert widget is not None
    assert widget._device_panels["laser"].setable_widgets["power"].value() == pytest.approx(12.0)
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
