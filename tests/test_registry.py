from pathlib import Path

import pytest

from labman_core.lab_config import DeviceSync, LabConfig
from labman_core.registry import DeviceRegistry
from labman_core.resource_lock import ResourceBusy, ResourceLock
from labman_core.roles import DeviceRole
from labman_core.simulators import SimLaser, SimPowerMeter

LASER = {"driver": "labman_core.simulators.SimLaser", "role": "laser"}
PM = {"driver": "labman_core.simulators.SimPowerMeter", "role": "power_meter"}


class NamelessDevice:
    """Driver whose constructor takes no `name` kwarg."""

    def __init__(self, gain: float = 1.0) -> None:
        self.gain = gain

    @property
    def name(self) -> str:
        return "nameless"

    async def shutdown(self) -> None:
        return None


class FailingShutdownDevice:
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def shutdown(self) -> None:
        raise RuntimeError("boom")


class RecordingDevice:
    shutdowns: list[str] = []

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def shutdown(self) -> None:
        RecordingDevice.shutdowns.append(self._name)


class CountingFailingDevice:
    attempts = 0

    def __init__(self) -> None:
        CountingFailingDevice.attempts += 1
        raise RuntimeError("instrument not found")


@pytest.fixture
def lock_dir(tmp_path: Path) -> Path:
    return tmp_path / "locks"


def _config(devices: dict) -> LabConfig:
    return LabConfig.from_dict({"version": 1, "devices": devices})


def _sim_lab() -> LabConfig:
    return _config(
        {
            "laser": {**LASER, "args": {"max_power_mw": 50.0}, "sync_policy": "hydrate"},
            "pm_in": PM,
            "pm_out": {**PM, "args": {"coupling": 0.5}, "sync_policy": "skip"},
        }
    )


def test_instantiates_drivers_with_config_name_and_args() -> None:
    reg = DeviceRegistry(_sim_lab())
    assert reg.instantiate_all() == {}

    assert reg.names() == ["laser", "pm_in", "pm_out"]
    laser = reg.device("laser")
    assert isinstance(laser, SimLaser)
    assert laser.name == "laser"
    assert laser._max_power_mw == 50.0
    assert isinstance(reg.device("pm_out"), SimPowerMeter)
    assert reg.device("pm_out").name == "pm_out"


def test_instantiate_all_is_idempotent() -> None:
    reg = DeviceRegistry(_sim_lab())
    reg.instantiate_all()
    first = reg.device("laser")
    reg.instantiate_all()
    assert reg.device("laser") is first


def test_role_and_sync_policy_lookup() -> None:
    reg = DeviceRegistry(_sim_lab())
    reg.instantiate_all()
    assert reg.role_of("pm_in") == DeviceRole.POWER_METER
    assert reg.sync_policy_of("laser") == "hydrate"
    assert reg.sync_policy_of("pm_in") == "hydrate"
    assert reg.sync_policy_of("pm_out") == "skip"


def test_devices_by_role() -> None:
    reg = DeviceRegistry(_sim_lab())
    reg.instantiate_all()
    assert [n for n, _ in reg.devices_by_role(DeviceRole.POWER_METER)] == ["pm_in", "pm_out"]
    assert [n for n, _ in reg.devices_by_role(DeviceRole.LASER)] == ["laser"]
    assert reg.devices_by_role(DeviceRole.CAMERA) == []


def test_driver_without_name_kwarg() -> None:
    reg = DeviceRegistry(
        _config(
            {"x": {"driver": f"{__name__}.NamelessDevice", "role": "stage", "args": {"gain": 2.0}}}
        )
    )
    reg.instantiate_all()
    assert reg.device("x").gain == 2.0


# ----- per-device failures -----


def test_bad_driver_arg_is_recorded_not_raised() -> None:
    reg = DeviceRegistry(_config({"laser": {**LASER, "args": {"max_powr_mw": 1.0}}}))
    failures = reg.instantiate_all()
    assert isinstance(failures["laser"].error, TypeError)
    assert "max_powr_mw" in failures["laser"].message
    assert reg.names() == []
    with pytest.raises(KeyError, match="unavailable"):
        reg.device("laser")


def test_non_dotted_driver_path_is_a_failure() -> None:
    reg = DeviceRegistry(_config({"x": {"driver": "SimLaser", "role": "laser"}}))
    reg.instantiate_all()
    assert "dotted" in reg.failures["x"].message


def test_missing_driver_module_is_a_failure() -> None:
    reg = DeviceRegistry(_config({"x": {"driver": "no_such_pkg.Thing", "role": "laser"}}))
    reg.instantiate_all()
    assert isinstance(reg.failures["x"].error, ModuleNotFoundError)


def test_failure_does_not_block_other_devices() -> None:
    reg = DeviceRegistry(
        _config({"broken": {"driver": "no_such_pkg.Thing", "role": "laser"}, "laser": LASER})
    )
    reg.instantiate_all()
    assert reg.names() == ["laser"]
    assert [n for n, _ in reg.devices_by_role(DeviceRole.LASER)] == ["laser"]
    assert set(reg.failures) == {"broken"}


def test_failed_devices_are_not_retried() -> None:
    CountingFailingDevice.attempts = 0
    reg = DeviceRegistry(_config({"x": {"driver": f"{__name__}.CountingFailingDevice",
                                        "role": "laser"}}))
    reg.instantiate_all()
    reg.instantiate_all()
    assert CountingFailingDevice.attempts == 1
    assert set(reg.failures) == {"x"}


async def test_shutdown_all_continues_past_failures() -> None:
    RecordingDevice.shutdowns = []
    reg = DeviceRegistry(
        _config(
            {
                "a": {"driver": f"{__name__}.RecordingDevice", "role": "laser"},
                "bad": {"driver": f"{__name__}.FailingShutdownDevice", "role": "laser"},
                "b": {"driver": f"{__name__}.RecordingDevice", "role": "laser"},
            }
        )
    )
    reg.instantiate_all()
    await reg.shutdown_all()
    assert RecordingDevice.shutdowns == ["a", "b"]


# ----- device references -----


def test_device_reference_arg_passes_earlier_instance() -> None:
    reg = DeviceRegistry(
        _config(
            {
                "laser": LASER,
                "pm": {**PM, "args": {"source_laser": {"device": "laser"}, "coupling": 0.5,
                                      "noise_w": 0.0}},
            }
        )
    )
    reg.instantiate_all()
    reg.device("laser")._power_mw = 10.0
    assert reg.device("pm")._source_mw() == 10.0


def test_forward_device_reference_is_a_failure() -> None:
    reg = DeviceRegistry(
        _config({"pm": {**PM, "args": {"source_laser": {"device": "laser"}}}, "laser": LASER})
    )
    reg.instantiate_all()
    assert "not declared earlier" in reg.failures["pm"].message
    assert reg.names() == ["laser"]


def test_dependency_on_failed_device_fails_too() -> None:
    reg = DeviceRegistry(
        _config(
            {
                "laser": {**LASER, "args": {"bogus": 1}},
                "pm": {**PM, "args": {"source_laser": {"device": "laser"}}},
            }
        )
    )
    reg.instantiate_all()
    assert set(reg.failures) == {"laser", "pm"}
    assert "depends on device 'laser'" in reg.failures["pm"].message


# ----- resource locks -----


def test_resource_held_elsewhere_marks_device_unavailable(lock_dir: Path) -> None:
    with ResourceLock("GPIB0::5::INSTR", lock_dir):
        reg = DeviceRegistry(
            _config({"laser": {**LASER, "resource": "GPIB0::5::INSTR"}}), lock_dir=lock_dir
        )
        reg.instantiate_all()
    assert isinstance(reg.failures["laser"].error, ResourceBusy)
    assert reg.names() == []


async def test_second_registry_is_locked_out_until_shutdown(lock_dir: Path) -> None:
    cfg = _config({"laser": {**LASER, "resource": "GPIB0::5::INSTR"}})
    first = DeviceRegistry(cfg, lock_dir=lock_dir)
    assert first.instantiate_all() == {}

    second = DeviceRegistry(cfg, lock_dir=lock_dir)
    assert isinstance(second.instantiate_all()["laser"].error, ResourceBusy)

    await first.shutdown_all()
    third = DeviceRegistry(cfg, lock_dir=lock_dir)
    assert third.instantiate_all() == {}
    await third.shutdown_all()


def test_constructor_failure_releases_resource_lock(lock_dir: Path) -> None:
    reg = DeviceRegistry(
        _config({"x": {"driver": f"{__name__}.CountingFailingDevice", "role": "laser",
                       "resource": "COM7"}}),
        lock_dir=lock_dir,
    )
    reg.instantiate_all()
    assert "x" in reg.failures
    with ResourceLock("COM7", lock_dir) as lock:
        assert lock.held


def test_devices_without_resource_need_no_lock(lock_dir: Path) -> None:
    reg = DeviceRegistry(_config({"a": LASER, "b": LASER}), lock_dir=lock_dir)
    assert reg.instantiate_all() == {}
    assert not lock_dir.exists()


# ----- connect-time sync -----


def test_connect_sync_applies_configured_policy_once() -> None:
    reg = DeviceRegistry(
        _config(
            {
                "laser": {**LASER, "sync_policy": "push_defaults",
                          "defaults": {"wavelength": 1310.0}},
                "pm": {**PM, "sync_policy": "skip"},
            }
        )
    )
    reg.instantiate_all()
    assert reg.connect_sync("laser") == DeviceSync("push_defaults", {"wavelength": 1310.0})
    assert reg.connect_sync("laser") == DeviceSync("push_defaults", {"wavelength": 1310.0})

    reg.mark_synced("laser")
    reg.mark_synced("pm")
    assert reg.connect_sync("laser") == DeviceSync("hydrate")
    assert reg.connect_sync("pm") == DeviceSync("skip")
