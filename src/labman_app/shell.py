"""LabMan main window: task picker, device binding, task hosting.

Run from repo root:
    python -m labman_app --lab examples/lab.sim.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Coroutine, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from labman_app.services import (
    RegistryShellServices,
    candidates_for,
    default_bindings,
    discover_tasks,
    validate_bindings,
)
from labman_core.lab_config import LabConfig
from labman_core.registry import DeviceRegistry
from labman_core.storage import DEFAULT_DATA_ROOT
from labman_core.task import Task

logger = logging.getLogger("labman.shell")


@dataclass
class _ActiveTask:
    task: Task
    services: RegistryShellServices
    widget: Any


class ShellWindow(QMainWindow):
    """Task list on the left; binding page or the active task widget on the right.

    One task is open at a time. Switching tasks or closing the window runs the
    active task's `to_safe_state` (Safety contract), and closing the window
    then shuts down every device in the registry.
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        tasks: Iterable[Task],
        data_root: Path = DEFAULT_DATA_ROOT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry = registry
        self._tasks = list(tasks)
        self._data_root = Path(data_root)
        self._active: _ActiveTask | None = None
        self._binding_combos: dict[str, QComboBox] = {}
        self._binding_error = QLabel()
        self._pending: set[asyncio.Future] = set()
        self._shutdown_future: asyncio.Future | None = None
        self._shutdown_complete = False

        self.setWindowTitle("LabMan")

        self._task_list = QListWidget()
        for task in self._tasks:
            self._task_list.addItem(task.display_name)
        self._task_list.currentRowChanged.connect(self._on_task_selected)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._set_content(self._placeholder())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._task_list)
        splitter.addWidget(self._content)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 1200])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage(
            f"{len(registry.names())} device(s), {len(self._tasks)} task(s)"
        )

    # ----- public API (also used by tests) -----

    @property
    def active_widget(self) -> Any | None:
        return self._active.widget if self._active else None

    def show_binding_page(self, task: Task) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(f"<h2 style='margin:0'>{task.display_name}</h2>"))
        layout.addWidget(QLabel("Choose a device for each binding:"))

        form = QFormLayout()
        defaults = default_bindings(task.required_bindings, self._registry)
        self._binding_combos = {}
        for binding, role in task.required_bindings.items():
            combo = QComboBox()
            combo.addItems(candidates_for(role, self._registry))
            if defaults[binding] is not None:
                combo.setCurrentText(defaults[binding])
            else:
                combo.setCurrentIndex(-1)
            form.addRow(f"{binding} ({role.value})", combo)
            self._binding_combos[binding] = combo
        layout.addLayout(form)

        self._binding_error = QLabel()
        self._binding_error.setWordWrap(True)
        self._binding_error.setStyleSheet("color: #b00020;")
        layout.addWidget(self._binding_error)

        open_btn = QPushButton("Open task")
        open_btn.clicked.connect(lambda: self._on_open_clicked(task))
        layout.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self._set_content(page)

    def current_bindings(self) -> dict[str, str | None]:
        return {b: (c.currentText() or None) for b, c in self._binding_combos.items()}

    async def open_task(self, task: Task, bindings: dict[str, str]) -> None:
        errors = validate_bindings(task.required_bindings, bindings, self._registry)
        if errors:
            raise ValueError("; ".join(errors))
        await self.close_active_task()

        services = RegistryShellServices(self._registry, bindings, self._data_root)
        widget = task.build_widget(services)
        self._active = _ActiveTask(task, services, widget)
        self._set_content(widget)
        self.statusBar().showMessage(
            f"{task.display_name}: "
            + ", ".join(f"{b} → {d}" for b, d in services.bindings.items())
        )

        initialize = getattr(widget, "initialize", None)
        if initialize is None:
            return
        try:
            await initialize()
        except Exception as e:  # noqa: BLE001
            logger.exception("initializing %r failed", task.name)
            await self.close_active_task()
            self.show_binding_page(task)
            self._binding_error.setText(f"Failed to initialize devices: {e}")

    async def close_active_task(self) -> None:
        """Stop the active widget and put its hardware in the safe state. Never raises."""
        active, self._active = self._active, None
        if active is None:
            return
        shutdown = getattr(active.widget, "shutdown", None)
        if shutdown is not None:
            try:
                shutdown()
            except Exception:  # noqa: BLE001
                logger.exception("widget shutdown for %r failed", active.task.name)
        # Let a cancelled workflow unwind through its own finally first.
        await asyncio.sleep(0)
        try:
            await active.task.to_safe_state(active.services.bound_devices())
        except Exception:  # noqa: BLE001
            logger.exception("to_safe_state for %r raised (contract violation)", active.task.name)
        self._set_content(self._placeholder())

    async def shutdown(self) -> None:
        await self.close_active_task()
        await self._registry.shutdown_all()

    # ----- Qt events -----

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._shutdown_complete:
            event.accept()
            return
        # Safe-state is async: defer the close until it has run.
        event.ignore()
        if self._shutdown_future is None:
            self._shutdown_future = asyncio.ensure_future(self._shutdown_then_close())

    async def _shutdown_then_close(self) -> None:
        try:
            await self.shutdown()
        finally:
            self._shutdown_complete = True
            self.close()

    # ----- slots -----

    def _on_task_selected(self, row: int) -> None:
        if row < 0:
            return
        task = self._tasks[row]
        if self._active is not None and self._active.task is task:
            return
        self._spawn(self._select_task(task))

    async def _select_task(self, task: Task) -> None:
        if self._active is not None:
            if not self._confirm_close_active():
                self._task_list.blockSignals(True)
                self._task_list.setCurrentRow(self._tasks.index(self._active.task))
                self._task_list.blockSignals(False)
                return
            await self.close_active_task()
        self.show_binding_page(task)

    def _on_open_clicked(self, task: Task) -> None:
        bindings = self.current_bindings()
        errors = validate_bindings(task.required_bindings, bindings, self._registry)
        if errors:
            self._binding_error.setText("\n".join(errors))
            return
        self._spawn(self.open_task(task, bindings))  # type: ignore[arg-type]

    def _confirm_close_active(self) -> bool:
        assert self._active is not None
        answer = QMessageBox.question(
            self,
            "Close task",
            f"Close {self._active.task.display_name}? A running measurement will be "
            "stopped and its hardware put in the safe state.",
        )
        return answer == QMessageBox.StandardButton.Yes

    # ----- helpers -----

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        fut = asyncio.ensure_future(coro)
        self._pending.add(fut)
        fut.add_done_callback(self._on_spawn_done)

    def _on_spawn_done(self, fut: asyncio.Future) -> None:
        self._pending.discard(fut)
        if fut.cancelled() or fut.exception() is None:
            return
        logger.error("shell action failed", exc_info=fut.exception())
        self.statusBar().showMessage(f"Error: {fut.exception()}")

    def _set_content(self, widget: QWidget) -> None:
        while self._content_layout.count():
            old = self._content_layout.takeAt(0).widget()
            if old is not None and old is not widget:
                old.setParent(None)
                old.deleteLater()
        self._content_layout.addWidget(widget)

    def _placeholder(self) -> QWidget:
        text = "Select a task on the left." if self._tasks else "No tasks installed."
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(prog="labman")
    parser.add_argument("--lab", type=Path, default=Path("lab.yaml"), help="lab.yaml path")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    args = parser.parse_args(argv[1:])

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app = QApplication.instance() or QApplication(argv)

    try:
        registry = DeviceRegistry(LabConfig.from_path(args.lab))
        registry.instantiate_all()
    except Exception as e:  # noqa: BLE001
        logger.exception("startup failed")
        QMessageBox.critical(
            None, "LabMan — startup failed", f"Could not load devices from {args.lab}:\n\n{e}"
        )
        return 1

    import qasync

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    win = ShellWindow(registry, discover_tasks(), data_root=args.data_root)
    win.resize(1400, 800)
    win.show()

    with loop:
        loop.run_forever()
    return 0
