import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from labman_core.context import TaskContext
from labman_core.roles import DeviceRole
from labman_tasks.coupling_efficiency.analysis import analyze
from labman_tasks.coupling_efficiency.params import CouplingEfficiencyParams
from labman_tasks.coupling_efficiency.result import (
    CouplingEfficiencyRawData,
    CouplingEfficiencyResult,
)
from labman_tasks.coupling_efficiency.workflow import acquire


class CouplingEfficiencyTask:
    name = "coupling_efficiency"
    display_name = "Coupling Efficiency"
    required_bindings: dict[str, DeviceRole] = {
        "laser": DeviceRole.LASER,
        "power_meter_in": DeviceRole.POWER_METER,
        "power_meter_out": DeviceRole.POWER_METER,
    }
    params_cls = CouplingEfficiencyParams

    def build_widget(self, shell: Any) -> Any:
        from labman_tasks.coupling_efficiency.widget import CouplingEfficiencyWidget

        return CouplingEfficiencyWidget(self, shell)

    async def run_headless(
        self, ctx: TaskContext, params: CouplingEfficiencyParams
    ) -> CouplingEfficiencyResult:
        raw = await acquire(ctx, params)
        _save_raw(ctx.storage.raw_path(), raw)
        _save_params(ctx.storage.params_path(), params)
        _save_meta(ctx.storage.meta_path(), task_name=self.name, devices=ctx.devices)

        result = analyze(raw, params)
        _save_result(ctx.storage.result_path(), result)
        return result


def _save_raw(path: Path, raw: CouplingEfficiencyRawData) -> None:
    with h5py.File(path, "w") as f:
        f.create_dataset("setpoints_mw", data=raw.setpoints_mw)
        f.create_dataset("p_in_w", data=raw.p_in_w)
        f.create_dataset("p_out_w", data=raw.p_out_w)
        f.create_dataset("t_seconds", data=raw.t_seconds)


def _save_result(path: Path, result: CouplingEfficiencyResult) -> None:
    with h5py.File(path, "w") as f:
        f.create_dataset("setpoints_mw", data=result.setpoints_mw)
        f.create_dataset("p_in_mean_w", data=result.p_in_mean_w)
        f.create_dataset("p_out_mean_w", data=result.p_out_mean_w)
        f.create_dataset("efficiency", data=result.efficiency)
        f.attrs["efficiency_mean"] = result.efficiency_mean
        f.attrs["efficiency_std"] = result.efficiency_std
        f.attrs["wavelength_nm"] = result.wavelength_nm
        f.attrs["correction_factor"] = result.correction_factor


def _save_params(path: Path, params: CouplingEfficiencyParams) -> None:
    path.write_text(json.dumps(asdict(params), indent=2, default=_json_default))


def _save_meta(path: Path, *, task_name: str, devices: dict) -> None:
    meta = {
        "task_name": task_name,
        "saved_at_utc": datetime.now(UTC).isoformat(),
        "git_hash": _git_hash(),
        "devices": {binding: type(dev).__name__ for binding, dev in devices.items()},
    }
    path.write_text(json.dumps(meta, indent=2))


def _git_hash() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=2,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
