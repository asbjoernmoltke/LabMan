from pathlib import Path

import pytest

from labman_app.services import (
    RegistryShellServices,
    default_bindings,
    discover_tasks,
    validate_bindings,
)
from labman_core.lab_config import LabConfig
from labman_core.registry import DeviceRegistry
from labman_core.roles import DeviceRole
from labman_tasks.coupling_efficiency import CouplingEfficiencyTask

EXAMPLE_LAB = Path(__file__).parents[1] / "examples" / "lab.sim.yaml"
REQUIRED = CouplingEfficiencyTask.required_bindings

LASER = {"driver": "labman_core.simulators.SimLaser", "role": "laser"}
PM = {"driver": "labman_core.simulators.SimPowerMeter", "role": "power_meter"}


def _registry(devices: dict) -> DeviceRegistry:
    reg = DeviceRegistry(LabConfig.from_dict({"version": 1, "devices": devices}))
    reg.instantiate_all()
    return reg


def test_discover_tasks_finds_coupling_efficiency() -> None:
    tasks = discover_tasks()
    assert "coupling_efficiency" in [t.name for t in tasks]


def test_discover_tasks_unknown_group_is_empty() -> None:
    assert discover_tasks(group="labman.no_such_group") == []


def test_default_bindings_picks_free_devices_in_order() -> None:
    reg = _registry({"laser": LASER, "pm_a": PM, "pm_b": PM})
    assert default_bindings(REQUIRED, reg) == {
        "laser": "laser",
        "power_meter_in": "pm_a",
        "power_meter_out": "pm_b",
    }


def test_default_bindings_prefers_matching_names() -> None:
    reg = _registry({"src": LASER, "power_meter_out": PM, "power_meter_in": PM})
    assert default_bindings(REQUIRED, reg) == {
        "laser": "src",
        "power_meter_in": "power_meter_in",
        "power_meter_out": "power_meter_out",
    }


def test_default_bindings_never_shares_a_device() -> None:
    reg = _registry({"laser": LASER, "pm": PM})
    bindings = default_bindings(REQUIRED, reg)
    assert bindings["power_meter_in"] == "pm"
    assert bindings["power_meter_out"] is None


def test_validate_bindings_ok() -> None:
    reg = _registry({"laser": LASER, "pm_a": PM, "pm_b": PM})
    ok = {"laser": "laser", "power_meter_in": "pm_a", "power_meter_out": "pm_b"}
    assert validate_bindings(REQUIRED, ok, reg) == []


@pytest.mark.parametrize(
    ("bindings", "fragment"),
    [
        ({"laser": "laser", "power_meter_in": "pm_a", "power_meter_out": None}, "no device"),
        ({"laser": "laser", "power_meter_in": "pm_a", "power_meter_out": "zz"}, "unknown"),
        ({"laser": "pm_b", "power_meter_in": "pm_a", "power_meter_out": "laser"}, "expected"),
        ({"laser": "laser", "power_meter_in": "pm_a", "power_meter_out": "pm_a"}, "already"),
    ],
)
def test_validate_bindings_errors(bindings: dict, fragment: str) -> None:
    reg = _registry({"laser": LASER, "pm_a": PM, "pm_b": PM})
    errors = validate_bindings(REQUIRED, bindings, reg)
    assert any(fragment in e for e in errors), errors


def test_registry_shell_services_resolves_bindings(tmp_path: Path) -> None:
    reg = _registry({"laser": LASER, "pm_a": PM, "pm_b": PM})
    services = RegistryShellServices(
        reg, {"laser": "laser", "power_meter_in": "pm_b", "power_meter_out": "pm_a"}, tmp_path
    )
    assert services.device("power_meter_in") is reg.device("pm_b")
    assert set(services.bound_devices()) == set(REQUIRED)
    storage = services.make_storage("coupling_efficiency")
    assert storage.root.is_relative_to(tmp_path / "coupling_efficiency")


async def test_example_lab_yaml_wires_simulators() -> None:
    reg = DeviceRegistry(LabConfig.from_path(EXAMPLE_LAB))
    reg.instantiate_all()
    assert default_bindings(REQUIRED, reg) == {b: b for b in REQUIRED}
    assert reg.role_of("power_meter_out") == DeviceRole.POWER_METER

    await reg.device("laser").set_power_mw(10.0)
    p_out = await reg.device("power_meter_out").read_power_w()
    assert p_out == pytest.approx(0.6 * 10e-3, abs=1e-8)
