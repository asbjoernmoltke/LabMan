from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from labman_app.forms import (
    DevicePanel,
    apply_sync_policy,
    build_device_panel,
    poll_readables,
)
from labman_core.context import TaskContext
from labman_core.exceptions import AbortConditionMet
from labman_core.shell import ShellServices
from labman_tasks.coupling_efficiency.plots import (
    clear_plots,
    make_plots,
    show_result,
    update_live,
)
from labman_tasks.coupling_efficiency.result import CouplingEfficiencyResult

if TYPE_CHECKING:
    from labman_tasks.coupling_efficiency.task import CouplingEfficiencyTask


class CouplingEfficiencyWidget(QWidget):
    """Three-column task widget: Equipment | Experiment | Graphics.

    Composes device panels for the bound devices, a params form, Start/Stop
    + progress bar, and live plots. Start launches `task.run_headless` on the
    running asyncio loop; Stop cancels the running coroutine.
    """

    def __init__(
        self,
        task: CouplingEfficiencyTask,
        shell: ShellServices,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._shell = shell

        self._devices = {name: shell.device(name) for name in task.required_bindings}
        self._device_panels: dict[str, DevicePanel] = {}
        self._poll_tasks: list[asyncio.Task] = []
        self._run_task: asyncio.Task | None = None
        self._reset_live_buffers()

        # Build columns
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_equipment_column())
        splitter.addWidget(self._build_experiment_column())
        splitter.addWidget(self._build_graphics_column())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([320, 340, 640])

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(splitter)

    async def initialize(self) -> None:
        """Per-device connect-time sync (policy from the shell) + start readable polling.

        Call once after construction, while an asyncio loop is running. The
        shell does this when a task is opened.
        """
        for binding_name, device in self._devices.items():
            panel = self._device_panels[binding_name]
            await apply_sync_policy(panel, device, self._shell.device_sync(binding_name))
            self._poll_tasks.append(asyncio.create_task(poll_readables(panel)))

    def shutdown(self) -> None:
        """Stop polling and cancel a running workflow if any."""
        for t in self._poll_tasks:
            t.cancel()
        self._poll_tasks.clear()
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()

    # ----- column builders -----

    def _build_equipment_column(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        for binding_name, device in self._devices.items():
            panel = build_device_panel(device)
            self._device_panels[binding_name] = panel
            layout.addWidget(_labeled(binding_name, panel.widget))
        layout.addStretch(1)
        return _column("Equipment", body, scrollable=True)

    def _build_experiment_column(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)

        form, get_params = self._shell.params_form(self._task.name, self._task.params_cls)
        self._get_params = get_params
        layout.addWidget(form)

        self._status_label = QLabel("Ready.")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        button_row = QHBoxLayout()
        self._start_btn = QPushButton("Start")
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start_clicked)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        button_row.addWidget(self._start_btn)
        button_row.addWidget(self._stop_btn)
        layout.addLayout(button_row)

        layout.addStretch(1)
        return _column("Experiment", body, scrollable=True)

    def _build_graphics_column(self) -> QWidget:
        self._plots = make_plots()
        return _column("Graphics", self._plots.widget, scrollable=False)

    # ----- run lifecycle -----

    def _on_start_clicked(self) -> None:
        if self._run_task is not None and not self._run_task.done():
            return
        try:
            params = self._get_params()
        except Exception as e:
            self._status_label.setText(f"Invalid parameters: {e}")
            return
        self._set_running_ui(True)
        self._reset_live_buffers()
        clear_plots(self._plots)
        self._progress.setValue(0)
        self._status_label.setText("Running…")
        self._run_task = asyncio.create_task(self._run(params))

    def _on_stop_clicked(self) -> None:
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()

    async def _run(self, params: Any) -> None:
        storage = self._shell.make_storage(self._task.name)
        ctx = TaskContext(devices=self._devices, storage=storage)
        ctx.progress.subscribe(self._on_progress)
        ctx.live.subscribe("point", self._on_point)
        try:
            result = await self._task.run_headless(ctx, params)
            self._shell.run_succeeded(self._task.name, params)
            show_result(self._plots, result)
            self._on_complete(result, storage.root)
        except AbortConditionMet as e:
            self._status_label.setText(f"Aborted: {e}   |   Partial data: {storage.root}")
        except asyncio.CancelledError:
            self._status_label.setText(f"Stopped. Partial data: {storage.root}")
            raise
        except Exception as e:  # noqa: BLE001
            self._status_label.setText(f"Error: {e}")
        finally:
            self._set_running_ui(False)
            self._run_task = None

    def _on_progress(self, fraction: float, message: str) -> None:
        self._progress.setValue(int(round(fraction * 100)))
        if message:
            self._status_label.setText(f"Running: {message}")

    def _on_point(self, payload: dict) -> None:
        self._sp_buf.append(payload["setpoint_mw"])
        self._pin_buf.append(payload["p_in_w"])
        self._pout_buf.append(payload["p_out_w"])
        update_live(self._plots, self._sp_buf, self._pin_buf, self._pout_buf)

    def _on_complete(
        self, result: CouplingEfficiencyResult, run_dir: Any
    ) -> None:
        self._status_label.setText(
            f"Done. η = {result.efficiency_mean:.4f} ± {result.efficiency_std:.4f} "
            f"   |   {run_dir}"
        )

    def _set_running_ui(self, running: bool) -> None:
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)

    def _reset_live_buffers(self) -> None:
        self._sp_buf: list[float] = []
        self._pin_buf: list[float] = []
        self._pout_buf: list[float] = []


def _column(title: str, body: QWidget, *, scrollable: bool) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(f"<h3 style='margin:0'>{title}</h3>"))
    if scrollable:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(body)
        layout.addWidget(sa, 1)
    else:
        layout.addWidget(body, 1)
    return holder


def _labeled(title: str, widget: QWidget) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(f"<b>{title}</b>"))
    layout.addWidget(widget)
    return holder
