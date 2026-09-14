from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from labman_app.forms import DevicePanel, apply_sync_policy, build_device_panel, poll_readables
from labman_app.widgets.layout import labeled, titled_column
from labman_core.context import TaskContext
from labman_core.shell import ShellServices
from labman_tasks.auto_alignment.plots import (
    add_cycle,
    add_sample,
    clear_plots,
    make_plots,
    on_start,
    show_result,
)
from labman_tasks.auto_alignment.result import AutoAlignmentResult

if TYPE_CHECKING:
    from labman_tasks.auto_alignment.task import AutoAlignmentTask

STOP_TEXT = "Stop"
FORCE_STOP_TEXT = "Force stop"


class AutoAlignmentWidget(QWidget):
    """Equipment | Experiment | Graphics for the auto-alignment task.

    Stop asks the run to finish after the current step, so its data is saved.
    Pressing Stop again (Force stop) cancels immediately: the hardware is still
    latched through the safe-state path, but that run's data is not saved.
    """

    def __init__(
        self, task: AutoAlignmentTask, shell: ShellServices, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._shell = shell
        self._devices = {name: shell.device(name) for name in task.required_bindings}
        self._device_panels: dict[str, DevicePanel] = {}
        self._poll_tasks: list[asyncio.Task] = []
        self._run_task: asyncio.Task | None = None
        self._ctx: TaskContext | None = None

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_equipment_column())
        splitter.addWidget(self._build_experiment_column())
        splitter.addWidget(self._build_graphics_column())
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([300, 360, 640])

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(splitter)

    async def initialize(self) -> None:
        for binding_name, device in self._devices.items():
            panel = self._device_panels[binding_name]
            await apply_sync_policy(panel, device, self._shell.device_sync(binding_name))
            self._poll_tasks.append(asyncio.create_task(poll_readables(panel)))

    def shutdown(self) -> None:
        for t in self._poll_tasks:
            t.cancel()
        self._poll_tasks.clear()
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()

    # ----- columns -----

    def _build_equipment_column(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        for binding_name, device in self._devices.items():
            panel = build_device_panel(device)
            self._device_panels[binding_name] = panel
            layout.addWidget(labeled(binding_name, panel.widget))
        layout.addStretch(1)
        return titled_column("Equipment", body, scrollable=True)

    def _build_experiment_column(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)

        form, self._get_params = self._shell.params_form(self._task.name, self._task.params_cls)
        layout.addWidget(form)

        readouts = QFormLayout()
        self._cycle_label = QLabel("—")
        self._centre_label = QLabel("—")
        self._dip_label = QLabel("—")
        readouts.addRow("Cycle", self._cycle_label)
        readouts.addRow("Centre", self._centre_label)
        readouts.addRow("In dip", self._dip_label)
        layout.addLayout(readouts)

        self._status_label = QLabel("Ready. Align by hand first, then map or track.")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        layout.addWidget(self._progress)

        row = QHBoxLayout()
        self._start_btn = QPushButton("Start")
        self._stop_btn = QPushButton(STOP_TEXT)
        self._stop_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start_clicked)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        row.addWidget(self._start_btn)
        row.addWidget(self._stop_btn)
        layout.addLayout(row)
        layout.addStretch(1)
        return titled_column("Experiment", body, scrollable=True)

    def _build_graphics_column(self) -> QWidget:
        self._plots = make_plots()
        return titled_column("Graphics", self._plots.widget, scrollable=False)

    # ----- run lifecycle -----

    def _on_start_clicked(self) -> None:
        if self._run_task is not None and not self._run_task.done():
            return
        try:
            params = self._get_params()
        except Exception as e:  # noqa: BLE001
            self._status_label.setText(f"Invalid parameters: {e}")
            return
        self._set_running_ui(True)
        clear_plots(self._plots)
        self._progress.setValue(0)
        self._status_label.setText("Mapping…" if params.mode == "map" else "Tracking…")
        self._run_task = asyncio.create_task(self._run(params))

    def _on_stop_clicked(self) -> None:
        if self._run_task is None or self._run_task.done():
            return
        if self._ctx is not None and not self._ctx.stop_requested:
            self._ctx.request_stop()
            self._stop_btn.setText(FORCE_STOP_TEXT)
            self._status_label.setText("Stopping after the current step…")
        else:
            self._run_task.cancel()

    async def _run(self, params: Any) -> None:
        try:
            # Inside the try: a storage failure must still reset the UI below.
            storage = self._shell.make_storage(self._task.name)
            ctx = TaskContext(devices=self._devices, storage=storage)
            self._ctx = ctx
            ctx.progress.subscribe(self._on_progress)
            ctx.live.subscribe("start", lambda p: on_start(self._plots, p))
            ctx.live.subscribe("sample", lambda p: add_sample(self._plots, p))
            ctx.live.subscribe("cycle", self._on_cycle)
            result = await self._task.run_headless(ctx, params)
            self._shell.run_succeeded(self._task.name, params)
            show_result(self._plots, result)
            self._status_label.setText(f"{summary_text(result)}   |   {storage.root}")
        except asyncio.CancelledError:
            self._status_label.setText("Force-stopped. Hardware latched; this run was not saved.")
            raise
        except Exception as e:  # noqa: BLE001
            self._status_label.setText(f"Error: {e}")
        finally:
            self._set_running_ui(False)
            self._run_task = None
            self._ctx = None

    def _on_progress(self, fraction: float, message: str) -> None:
        self._progress.setValue(int(round(fraction * 100)))
        if message:
            self._cycle_label.setText(message)

    def _on_cycle(self, payload: dict) -> None:
        add_cycle(self._plots, payload)
        h, v = payload["centre_v"]
        self._centre_label.setText(f"({h:.3f}, {v:.3f}) V   {payload['centre_signal_a']:.3g} A")
        self._dip_label.setText("yes" if payload["in_dip"] else f"no ({payload['reason']})")

    def _set_running_ui(self, running: bool) -> None:
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._stop_btn.setText(STOP_TEXT)


def summary_text(result: AutoAlignmentResult) -> str:
    if result.map is not None:
        m = result.map
        if m.dip_found:
            dip = (
                f"Nearest dip to start: {m.local_min_signal_a:.3g} A at "
                f"({m.local_min_v[0]:.3f}, {m.local_min_v[1]:.3f}) V "
                f"(start {m.start_signal_a:.3g} A); profile around it: {m.profile_shape}."
            )
        else:
            dip = (
                f"No dip inside the map: downhill from start reaches the map edge. "
                f"Profile around start: {m.profile_shape}."
            )
        return (
            f"Map {result.stop_reason}. {dip} Global minimum {m.min_signal_a:.3g} A at "
            f"({m.min_v[0]:.3f}, {m.min_v[1]:.3f}) V — may be beyond the ring. Returned to start."
        )
    t = result.track
    assert t is not None
    return (
        f"Tracking ended: {result.stop_reason}. {t.n_cycles} cycles, in dip "
        f"{t.in_dip_fraction:.0%}, moved {t.drift_v:.3f} V. Latched at "
        f"({t.best_v[0]:.3f}, {t.best_v[1]:.3f}) V."
    )
