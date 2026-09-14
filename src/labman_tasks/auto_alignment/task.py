from typing import Any

from labman_core.context import TaskContext
from labman_core.devices import Device
from labman_core.persistence import save_dataclass_h5, save_meta, save_params_json
from labman_core.roles import DeviceRole
from labman_tasks.auto_alignment import safety
from labman_tasks.auto_alignment.analysis import analyze
from labman_tasks.auto_alignment.params import AutoAlignmentParams
from labman_tasks.auto_alignment.result import AutoAlignmentResult
from labman_tasks.auto_alignment.workflow import acquire


class AutoAlignmentTask:
    name = "auto_alignment"
    display_name = "Auto-alignment (NanoTrak)"
    required_bindings: dict[str, DeviceRole] = {"aligner": DeviceRole.ALIGNER}
    params_cls = AutoAlignmentParams

    def build_widget(self, shell: Any) -> Any:
        from labman_tasks.auto_alignment.widget import AutoAlignmentWidget

        return AutoAlignmentWidget(self, shell)

    async def run_headless(
        self, ctx: TaskContext, params: AutoAlignmentParams
    ) -> AutoAlignmentResult:
        try:
            raw = await acquire(ctx, params)
            save_dataclass_h5(ctx.storage.raw_path(), raw)
            save_params_json(ctx.storage.params_path(), params)
            save_meta(ctx.storage.meta_path(), task_name=self.name, devices=ctx.devices,
                      extra={"stop_reason": raw.stop_reason})

            result = analyze(raw, params)
            save_dataclass_h5(ctx.storage.result_path(), result)
            return result
        finally:
            # Defense-in-depth: acquire already latched at its hold position.
            # Without a position this only latches in place. Idempotent.
            await self.to_safe_state(ctx.devices)

    async def to_safe_state(self, devices: dict[str, Device]) -> None:
        await safety.to_safe_state(devices)
