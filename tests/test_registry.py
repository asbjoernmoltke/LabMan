import pytest

from labman_core.lab_config import LabConfig
from labman_core.registry import DeviceRegistry
from labman_core.roles import DeviceRole
from labman_core.simulators import SimLaser, SimPowerMeter


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


def _config(devices: dict) -> LabConfig:
    return LabConfig.from_dict({"version": 1, "devices": devices})


def _sim_lab() -> LabConfig:
    return _config(
        {
            "laser": {
                "driver": "labman_core.simulators.SimLaser",
                "role": "laser",
                "args": {"max_power_mw": 50.0},
                "sync_policy": "hydrate",
            },
            "pm_in": {"driver": "labman_core.simulators.SimPowerMeter", "role": "power_meter"},
            "pm_out": {
                "driver": "labman_core.simulators.SimPowerMeter",
                "role": "power_meter",
                "args": {"coupling": 0.5},
            },
        }
    )


def test_instantiates_drivers_with_config_name_and_args() -> None:
    reg = DeviceRegistry(_sim_lab())
    reg.instantiate_all()

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
    assert reg.sync_policy_of("pm_in") == "skip"


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


def test_bad_driver_arg_surfaces_type_error() -> None:
    reg = DeviceRegistry(
        _config(
            {"laser": {"driver": "labman_core.simulators.SimLaser", "role": "laser",
                       "args": {"max_powr_mw": 1.0}}}
        )
    )
    with pytest.raises(TypeError, match="max_powr_mw"):
        reg.instantiate_all()


def test_non_dotted_driver_path_raises() -> None:
    reg = DeviceRegistry(_config({"x": {"driver": "SimLaser", "role": "laser"}}))
    with pytest.raises(ValueError, match="dotted"):
        reg.instantiate_all()


def test_missing_driver_module_raises() -> None:
    reg = DeviceRegistry(_config({"x": {"driver": "no_such_pkg.Thing", "role": "laser"}}))
    with pytest.raises(ModuleNotFoundError):
        reg.instantiate_all()


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


def test_device_reference_arg_passes_earlier_instance() -> None:
    reg = DeviceRegistry(
        _config(
            {
                "laser": {"driver": "labman_core.simulators.SimLaser", "role": "laser"},
                "pm": {
                    "driver": "labman_core.simulators.SimPowerMeter",
                    "role": "power_meter",
                    "args": {"source_laser": {"device": "laser"}, "coupling": 0.5,
                             "noise_w": 0.0},
                },
            }
        )
    )
    reg.instantiate_all()
    reg.device("laser")._power_mw = 10.0
    assert reg.device("pm")._source_mw() == 10.0


def test_forward_device_reference_raises() -> None:
    reg = DeviceRegistry(
        _config(
            {
                "pm": {
                    "driver": "labman_core.simulators.SimPowerMeter",
                    "role": "power_meter",
                    "args": {"source_laser": {"device": "laser"}},
                },
                "laser": {"driver": "labman_core.simulators.SimLaser", "role": "laser"},
            }
        )
    )
    with pytest.raises(ValueError, match="not declared earlier"):
        reg.instantiate_all()
