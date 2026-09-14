"""Run the coupling-efficiency task widget against simulator devices.

This is the end-to-end demo: open the app, hit Start, watch the live plot
populate, get an HDF5 saved under ./app/data/coupling_efficiency/.

The DemoShell here is the stand-in for what the real shell will provide once
it lands. Tasks see only `ShellServices`; the demo and the shell both
implement that Protocol.

Run from repo root:
    python examples/coupling_efficiency_demo.py

Requires the [app] extra installed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import qasync
from PySide6.QtWidgets import QApplication, QMainWindow

from labman_core.devices import Device
from labman_core.simulators import SimLaser, SimPowerMeter
from labman_core.storage import DEFAULT_DATA_ROOT, RunStorage, StorageOptions
from labman_tasks.coupling_efficiency import CouplingEfficiencyTask


class DemoShell:
    """Stub `ShellServices`. Real shell will replace this."""

    def __init__(
        self,
        devices: dict[str, Device],
        data_root: Path = DEFAULT_DATA_ROOT,
    ) -> None:
        self._devices = devices
        self._data_root = data_root

    def device(self, binding_name: str) -> Device:
        return self._devices[binding_name]

    def make_storage(
        self, task_name: str, opts: StorageOptions | None = None
    ) -> RunStorage:
        return RunStorage(task_name, opts or StorageOptions(), self._data_root)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    laser = SimLaser(name="laser", max_power_mw=50.0)
    pm_in = SimPowerMeter(
        name="pm_in",
        source_mw=lambda: laser.power_mw,
        coupling=1.0,
        noise_w=1e-10,  # well below display_precision (1e-9); reads as "0" when laser off
    )
    pm_out = SimPowerMeter(
        name="pm_out",
        source_mw=lambda: laser.power_mw,
        coupling=0.6,
        noise_w=1e-10,
    )
    shell = DemoShell({
        "laser": laser,
        "power_meter_in": pm_in,
        "power_meter_out": pm_out,
    })

    task = CouplingEfficiencyTask()
    widget = task.build_widget(shell)

    win = QMainWindow()
    win.setWindowTitle("LabMan — Coupling Efficiency")
    win.setCentralWidget(widget)
    win.resize(1280, 760)
    win.show()

    asyncio.ensure_future(widget.initialize())

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
