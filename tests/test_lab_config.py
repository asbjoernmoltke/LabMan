from pathlib import Path
from textwrap import dedent

import pytest

from labman_core.lab_config import LabConfig
from labman_core.roles import DeviceRole


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "lab.yaml"
    p.write_text(dedent(body))
    return p


def test_minimal_config_round_trip(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        """
        version: 1
        devices:
          laser:
            driver: labman_core.simulators.SimLaser
            role: laser
        """,
    )
    cfg = LabConfig.from_path(cfg_path)
    assert cfg.version == 1
    assert len(cfg.devices) == 1
    laser = cfg.devices[0]
    assert laser.name == "laser"
    assert laser.driver == "labman_core.simulators.SimLaser"
    assert laser.role == DeviceRole.LASER
    assert laser.args == {}
    assert laser.sync_policy == "skip"


def test_full_config(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        """
        version: 1
        devices:
          laser:
            driver: labman_core.simulators.SimLaser
            role: laser
            args:
              max_power_mw: 50.0
            sync_policy: hydrate
          pm_in:
            driver: labman_core.simulators.SimPowerMeter
            role: power_meter
            args:
              coupling: 1.0
              noise_w: 1.0e-10
            sync_policy: hydrate
        """,
    )
    cfg = LabConfig.from_path(cfg_path)
    assert {d.name for d in cfg.devices} == {"laser", "pm_in"}
    pm_in = next(d for d in cfg.devices if d.name == "pm_in")
    assert pm_in.role == DeviceRole.POWER_METER
    assert pm_in.args == {"coupling": 1.0, "noise_w": 1.0e-10}
    assert pm_in.sync_policy == "hydrate"


def test_unsupported_version_raises(tmp_path: Path) -> None:
    cfg_path = _write(tmp_path, "version: 2\ndevices: {}\n")
    with pytest.raises(ValueError, match="version"):
        LabConfig.from_path(cfg_path)


def test_unknown_role_raises(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        """
        version: 1
        devices:
          x:
            driver: a.b.C
            role: nonsense
        """,
    )
    with pytest.raises(ValueError, match="unknown role"):
        LabConfig.from_path(cfg_path)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        """
        version: 1
        devices:
          x:
            role: laser
        """,
    )
    with pytest.raises(ValueError, match="driver"):
        LabConfig.from_path(cfg_path)


def test_unknown_sync_policy_raises(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        """
        version: 1
        devices:
          laser:
            driver: a.b.C
            role: laser
            sync_policy: maybe
        """,
    )
    with pytest.raises(ValueError, match="sync_policy"):
        LabConfig.from_path(cfg_path)
