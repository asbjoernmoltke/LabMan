import asyncio
from pathlib import Path

import pytest

from labman_core.devices import Device
from labman_core.lab_config import DeviceSync
from labman_core.simulators import SimAligner
from labman_core.storage import RunStorage, StorageOptions
from labman_tasks.auto_alignment import AutoAlignmentTask
from labman_tasks.auto_alignment.params import AutoAlignmentParams


class StubShell:
    def __init__(self, devices: dict[str, Device], data_root: Path) -> None:
        self._devices = devices
        self._data_root = data_root
        self.succeeded: list = []

    def device(self, binding_name: str) -> Device:
        return self._devices[binding_name]

    def device_sync(self, binding_name: str) -> DeviceSync:
        return DeviceSync("hydrate")

    def make_storage(self, task_name: str, opts: StorageOptions | None = None) -> RunStorage:
        return RunStorage(task_name, opts or StorageOptions(naming="iterator"), self._data_root)

    def params_form(self, task_name: str, params_cls: type):
        from labman_app.forms import build_params_form

        return build_params_form(params_cls)

    def run_succeeded(self, task_name: str, params) -> None:
        self.succeeded.append((task_name, params))


def _widget(qapp, tmp_path: Path):
    from labman_tasks.auto_alignment.widget import AutoAlignmentWidget

    sim = SimAligner(start_v=(75.3, 74.8), optimum_v=(75.0, 75.0))
    shell = StubShell({"aligner": sim}, tmp_path)
    return AutoAlignmentWidget(AutoAlignmentTask(), shell), sim, shell


async def test_map_run_plots_saves_and_reports(qapp, tmp_path: Path) -> None:
    widget, sim, shell = _widget(qapp, tmp_path)
    params = AutoAlignmentParams(mode="map", map_points=5, settle_time_s=0.0, averages=1)

    await widget._run(params)

    assert "Map completed" in widget._status_label.text()
    assert shell.succeeded == [("auto_alignment", params)]
    run_dir = next((tmp_path / "auto_alignment").iterdir())
    assert (run_dir / "raw.h5").exists() and (run_dir / "result.h5").exists()
    assert widget._plots.image.image is not None
    assert await sim.get_position_v() == (75.3, 74.8)


async def test_stop_finishes_tracking_gracefully_and_saves(qapp, tmp_path: Path) -> None:
    widget, sim, shell = _widget(qapp, tmp_path)
    params = AutoAlignmentParams(mode="track", probe_radius_v=0.05, settle_time_s=0.001,
                                 averages=1)
    widget._set_running_ui(True)
    widget._run_task = asyncio.create_task(widget._run(params))
    await asyncio.sleep(0.1)

    widget._on_stop_clicked()
    assert widget._stop_btn.text() == "Force stop"
    await asyncio.wait_for(widget._run_task, timeout=5)

    assert "Tracking ended: stopped" in widget._status_label.text()
    assert len(shell.succeeded) == 1
    assert widget._stop_btn.text() == "Stop"
    assert widget._plots.buffers.cycle_t  # live cycles were plotted
    run_dir = next((tmp_path / "auto_alignment").iterdir())
    assert (run_dir / "raw.h5").exists()
    assert sim.latched


async def test_second_stop_click_force_cancels(qapp, tmp_path: Path) -> None:
    widget, sim, shell = _widget(qapp, tmp_path)
    params = AutoAlignmentParams(mode="track", settle_time_s=0.01, averages=1)
    widget._set_running_ui(True)
    run = asyncio.create_task(widget._run(params))
    widget._run_task = run
    await asyncio.sleep(0.05)

    widget._on_stop_clicked()  # graceful stop requested...
    widget._on_stop_clicked()  # ...clicked again before the run noticed -> cancel

    with pytest.raises(asyncio.CancelledError):
        await run
    assert "Force-stopped" in widget._status_label.text()
    assert shell.succeeded == []
    assert sim.latched


async def test_initialize_hydrates_voltages(qapp, tmp_path: Path) -> None:
    widget, _sim, _shell = _widget(qapp, tmp_path)
    await widget.initialize()
    panel = widget._device_panels["aligner"]
    assert panel.setable_widgets["horizontal_v"].value() == pytest.approx(75.3)
    widget.shutdown()
    await asyncio.sleep(0)


async def test_storage_failure_reports_error_and_resets_ui(qapp, tmp_path: Path) -> None:
    widget, _sim, shell = _widget(qapp, tmp_path)

    def broken_storage(task_name, opts=None):
        raise OSError("disk full")

    shell.make_storage = broken_storage
    widget._set_running_ui(True)

    await widget._run(AutoAlignmentParams(mode="map", map_points=3, settle_time_s=0.0,
                                          averages=1))

    assert "Error: disk full" in widget._status_label.text()
    assert widget._start_btn.isEnabled()
    assert widget._run_task is None and widget._ctx is None
    assert shell.succeeded == []
