import asyncio
from dataclasses import dataclass
from typing import Annotated, Literal

import pytest

from labman_core.schema import ParamMeta, Range
from labman_core.simulators import SimLaser, SimPowerMeter


def test_build_params_form_round_trip(qapp) -> None:
    from labman_app.forms import build_params_form

    @dataclass
    class P:
        x: Annotated[float, ParamMeta(display="X", bounds=Range(0.0, 10.0))] = 1.0
        n: Annotated[int, ParamMeta(display="N", bounds=Range(1, 100))] = 5
        name: Annotated[str, ParamMeta(display="Name")] = "default"
        on: Annotated[bool, ParamMeta(display="On")] = False

    _widget, getter = build_params_form(P)
    out = getter()
    assert out == P()


def test_build_params_form_uses_initial(qapp) -> None:
    from labman_app.forms import build_params_form

    @dataclass
    class P:
        x: Annotated[float, ParamMeta(display="X", bounds=Range(0.0, 10.0))] = 1.0

    _widget, getter = build_params_form(P, initial=P(x=7.5))
    assert getter().x == 7.5


def test_build_params_form_handles_optional(qapp) -> None:
    from labman_app.forms import build_params_form

    @dataclass
    class P:
        guard: Annotated[
            float | None, ParamMeta(display="Guard", bounds=Range(0.0, 1.0), optional=True)
        ] = None

    _widget, getter = build_params_form(P)
    assert getter().guard is None


def test_build_params_form_handles_literal_choices(qapp) -> None:
    from labman_app.forms import build_params_form

    @dataclass
    class P:
        mode: Annotated[
            Literal["fast", "medium", "slow"], ParamMeta(display="Mode")
        ] = "medium"

    _widget, getter = build_params_form(P)
    assert getter().mode == "medium"


def test_build_params_form_real_coupling_efficiency_params(qapp) -> None:
    from labman_app.forms import build_params_form
    from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams

    _widget, getter = build_params_form(CouplingEfficiencyParams)
    out = getter()
    assert out == CouplingEfficiencyParams()


def test_build_device_panel_for_sim_laser_has_three_groups(qapp) -> None:
    from PySide6.QtWidgets import QGroupBox

    from labman_app.forms import build_device_panel

    panel = build_device_panel(SimLaser())
    titles = {gb.title() for gb in panel.widget.findChildren(QGroupBox)}
    assert {"Settings", "Readouts", "Actions"}.issubset(titles)


def test_build_device_panel_exposes_setable_and_readable_handles(qapp) -> None:
    from labman_app.forms import build_device_panel

    panel = build_device_panel(SimPowerMeter())
    assert set(panel.setable_widgets) == {"wavelength", "range", "acq_mode", "averaging"}
    assert set(panel.readable_labels) == {"power", "offset"}


def test_build_device_panel_for_sim_power_meter_renders_choices(qapp) -> None:
    from labman_app.forms import build_device_panel
    from labman_app.widgets.choice import ChoiceInput

    panel = build_device_panel(SimPowerMeter())
    assert isinstance(panel.setable_widgets["range"], ChoiceInput)
    assert isinstance(panel.setable_widgets["acq_mode"], ChoiceInput)


@pytest.mark.asyncio
async def test_setable_commit_propagates_to_device(qapp) -> None:
    from labman_app.forms import build_device_panel

    laser = SimLaser(max_power_mw=100.0)
    panel = build_device_panel(laser)

    power_widget = panel.setable_widgets["power"]
    power_widget.set_value(42.0)
    power_widget.committed.emit(42.0)

    await asyncio.sleep(0)
    state = await laser.get_state()
    assert state.power_mw == pytest.approx(42.0)


@pytest.mark.asyncio
async def test_action_button_invokes_device_action(qapp) -> None:
    from PySide6.QtWidgets import QPushButton

    from labman_app.forms import build_device_panel

    pm = SimPowerMeter(source_mw=lambda: 5.0, coupling=1.0, noise_w=0.0)
    panel = build_device_panel(pm)

    calibrate_btn = next(
        b for b in panel.widget.findChildren(QPushButton) if b.text() == "Calibrate"
    )
    calibrate_btn.click()
    await asyncio.sleep(0)

    after = await pm.read_power_w()
    assert after == pytest.approx(0.0, abs=1e-12)


@pytest.mark.asyncio
async def test_sync_panel_from_device_hydrates_widgets(qapp) -> None:
    from labman_app.forms import build_device_panel, sync_panel_from_device

    laser = SimLaser(max_power_mw=100.0)
    await laser.set_power_mw(37.5)
    await laser.set_wavelength_nm(1310.0)

    panel = build_device_panel(laser)
    # widgets start at zero/defaults; after sync they should reflect device state
    await sync_panel_from_device(panel, laser)

    assert panel.setable_widgets["power"].value() == pytest.approx(37.5)
    assert panel.setable_widgets["wavelength"].value() == pytest.approx(1310.0)


@pytest.mark.asyncio
async def test_poll_readables_updates_label(qapp) -> None:
    from labman_app.forms import build_device_panel, poll_readables

    laser = SimLaser(max_power_mw=100.0)
    pm = SimPowerMeter(source_mw=lambda: laser.power_mw, coupling=1.0, noise_w=0.0)
    panel = build_device_panel(pm)

    assert panel.readable_labels["power"].text() == "—"

    await laser.set_power_mw(10.0)
    poll_task = asyncio.create_task(poll_readables(panel, interval_s=0.01))
    try:
        # Allow at least one poll cycle.
        await asyncio.sleep(0.05)
        text = panel.readable_labels["power"].text()
        assert text != "—"
        assert float(text) == pytest.approx(0.01, rel=1e-3)
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_poll_readables_suppresses_subprecision_values(qapp) -> None:
    """Readings below the readable's display_precision render as '0'."""
    from labman_app.forms import build_device_panel, poll_readables

    # PM with noise well below display_precision (1e-9). Laser is off.
    pm = SimPowerMeter(source_mw=lambda: 0.0, noise_w=1e-12, seed=42)
    panel = build_device_panel(pm)

    poll_task = asyncio.create_task(poll_readables(panel, interval_s=0.01))
    try:
        await asyncio.sleep(0.05)
        assert panel.readable_labels["power"].text() == "0"
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
