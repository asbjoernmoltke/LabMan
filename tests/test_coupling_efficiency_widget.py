import asyncio
from pathlib import Path

import pytest

from labman_core.devices import Device
from labman_core.lab_config import DeviceSync
from labman_core.simulators import SimLaser, SimPowerMeter
from labman_core.storage import RunStorage, StorageOptions
from labman_tasks.coupling_efficiency import CouplingEfficiencyTask
from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams


class StubShell:
    def __init__(self, devices: dict[str, Device], data_root: Path) -> None:
        self._devices = devices
        self._data_root = data_root
        self.succeeded: list[tuple[str, object]] = []

    def device(self, binding_name: str) -> Device:
        return self._devices[binding_name]

    def device_sync(self, binding_name: str) -> DeviceSync:
        return DeviceSync("hydrate")

    def params_form(self, task_name: str, params_cls: type):
        from labman_app.forms import build_params_form

        return build_params_form(params_cls)

    def run_succeeded(self, task_name: str, params) -> None:
        self.succeeded.append((task_name, params))

    def make_storage(
        self, task_name: str, opts: StorageOptions | None = None
    ) -> RunStorage:
        return RunStorage(task_name, opts or StorageOptions(naming="iterator"), self._data_root)


def _build_widget(qapp, tmp_path: Path, eff: float = 0.6):
    from labman_tasks.coupling_efficiency.widget import CouplingEfficiencyWidget

    laser = SimLaser(name="laser", max_power_mw=50.0)
    pm_in = SimPowerMeter(
        name="pm_in", source_mw=lambda: laser.power_mw, coupling=1.0, noise_w=0.0, seed=1
    )
    pm_out = SimPowerMeter(
        name="pm_out", source_mw=lambda: laser.power_mw, coupling=eff, noise_w=0.0, seed=2
    )
    shell = StubShell(
        {"laser": laser, "power_meter_in": pm_in, "power_meter_out": pm_out},
        data_root=tmp_path,
    )
    task = CouplingEfficiencyTask()
    widget = CouplingEfficiencyWidget(task, shell)
    return widget, laser


@pytest.mark.asyncio
async def test_widget_run_populates_plots_and_persists(qapp, tmp_path: Path) -> None:
    widget, _laser = _build_widget(qapp, tmp_path, eff=0.6)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=10.0, power_steps=4,
        averages_per_point=2, settle_time_s=0.0,
    )

    await widget._run(params)

    assert widget._shell.succeeded == [("coupling_efficiency", params)]
    assert len(widget._sp_buf) == 4
    assert all(p == pytest.approx(0.6 * sp * 1e-3, rel=1e-6)
               for sp, p in zip(widget._sp_buf, widget._pout_buf, strict=True))

    saved_dirs = list((tmp_path / "coupling_efficiency").iterdir())
    assert len(saved_dirs) == 1
    run_dir = saved_dirs[0]
    assert (run_dir / "raw.h5").exists()
    assert (run_dir / "result.h5").exists()
    assert (run_dir / "params.json").exists()
    assert (run_dir / "meta.json").exists()


@pytest.mark.asyncio
async def test_widget_progress_subscription_updates_progressbar(qapp, tmp_path: Path) -> None:
    widget, _laser = _build_widget(qapp, tmp_path)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=5.0, power_steps=5,
        averages_per_point=1, settle_time_s=0.0,
    )
    await widget._run(params)
    assert widget._progress.value() == 100


@pytest.mark.asyncio
async def test_widget_cancellation_cleans_up_laser(qapp, tmp_path: Path) -> None:
    widget, laser = _build_widget(qapp, tmp_path)
    params = CouplingEfficiencyParams(
        power_start=1.0, power_stop=5.0, power_steps=20,
        averages_per_point=1, settle_time_s=0.05,
    )

    run_task = asyncio.create_task(widget._run(params))
    # Let a couple of points complete, then cancel.
    await asyncio.sleep(0.12)
    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    state = await laser.get_state()
    assert state.enabled is False
    assert state.power_mw == 0.0
    assert widget._shell.succeeded == []  # a stopped run is not "last used"


@pytest.mark.asyncio
async def test_initialize_hydrates_panels_and_starts_polling(qapp, tmp_path: Path) -> None:
    widget, laser = _build_widget(qapp, tmp_path)

    await laser.set_power_mw(17.0)
    await widget.initialize()

    laser_panel = widget._device_panels["laser"]
    assert laser_panel.setable_widgets["power"].value() == pytest.approx(17.0)
    assert len(widget._poll_tasks) == 3  # one per device

    widget.shutdown()
    await asyncio.sleep(0)


def test_live_publisher_dispatches_by_event() -> None:
    from labman_core.context import LivePublisher

    pub = LivePublisher()
    points: list = []
    images: list = []
    pub.subscribe("point", points.append)
    pub.subscribe("image", images.append)

    pub.publish("point", {"x": 1})
    pub.publish("image", {"frame": 0})
    pub.publish("point", {"x": 2})

    assert points == [{"x": 1}, {"x": 2}]
    assert images == [{"frame": 0}]
