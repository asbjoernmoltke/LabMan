from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QVBoxLayout, QWidget

from labman_tasks.auto_alignment.result import AutoAlignmentResult

MAX_LIVE_SAMPLES = 12_000
_CMAP = "viridis"


@dataclass
class LiveBuffers:
    sample_h: deque = field(default_factory=lambda: deque(maxlen=MAX_LIVE_SAMPLES))
    sample_v: deque = field(default_factory=lambda: deque(maxlen=MAX_LIVE_SAMPLES))
    sample_s: deque = field(default_factory=lambda: deque(maxlen=MAX_LIVE_SAMPLES))
    cycle_t: list[float] = field(default_factory=list)
    cycle_h: list[float] = field(default_factory=list)
    cycle_v: list[float] = field(default_factory=list)
    centre_s: list[float] = field(default_factory=list)
    ring_s: list[float] = field(default_factory=list)
    start_v: tuple[float, float] | None = None
    best_v: tuple[float, float] | None = None


@dataclass
class AutoAlignmentPlots:
    """Position plane (top) and signal vs time (bottom)."""

    widget: QWidget
    xy: pg.PlotWidget
    image: pg.ImageItem
    samples: pg.ScatterPlotItem
    trajectory: pg.PlotDataItem
    markers: pg.ScatterPlotItem
    signal: pg.PlotWidget
    centre_curve: pg.PlotDataItem
    ring_curve: pg.PlotDataItem
    buffers: LiveBuffers = field(default_factory=LiveBuffers)


def make_plots() -> AutoAlignmentPlots:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    cmap = pg.colormap.get(_CMAP)

    xy = pg.PlotWidget()
    xy.setBackground("w")
    xy.setLabel("bottom", "Horizontal", units="V")
    xy.setLabel("left", "Vertical", units="V")
    xy.setAspectLocked(True)
    xy.showGrid(x=True, y=True, alpha=0.3)
    image = pg.ImageItem(axisOrder="row-major")
    image.setLookupTable(cmap.getLookupTable(nPts=256))
    image.setZValue(-10)
    xy.addItem(image)
    samples = pg.ScatterPlotItem(size=7, pen=None)
    xy.addItem(samples)
    trajectory = xy.plot([], [], pen=pg.mkPen((220, 60, 60), width=2), symbol="o",
                         symbolSize=4, symbolBrush=(220, 60, 60))
    markers = pg.ScatterPlotItem(size=16)
    xy.addItem(markers)

    signal = pg.PlotWidget()
    signal.setBackground("w")
    signal.setLabel("bottom", "Time", units="s")
    signal.setLabel("left", "Stray-light signal", units="A")
    signal.addLegend(offset=(10, 10))
    signal.showGrid(x=True, y=True, alpha=0.3)
    centre_curve = signal.plot([], [], pen=pg.mkPen((60, 120, 220), width=2), name="centre")
    ring_curve = signal.plot([], [], pen=pg.mkPen((230, 140, 40), width=2), name="probe mean")

    layout.addWidget(xy, 3)
    layout.addWidget(signal, 2)
    return AutoAlignmentPlots(container, xy, image, samples, trajectory, markers, signal,
                              centre_curve, ring_curve)


def on_start(plots: AutoAlignmentPlots, payload: dict) -> None:
    plots.buffers.start_v = tuple(payload["start_v"])
    _update_markers(plots)


def add_sample(plots: AutoAlignmentPlots, payload: dict) -> None:
    b = plots.buffers
    b.sample_h.append(payload["h_v"])
    b.sample_v.append(payload["v_v"])
    b.sample_s.append(payload["signal_a"])
    values = np.fromiter(b.sample_s, dtype=float)
    plots.samples.setData(x=list(b.sample_h), y=list(b.sample_v), brush=_brushes(values))


def add_cycle(plots: AutoAlignmentPlots, payload: dict) -> None:
    b = plots.buffers
    b.cycle_t.append(payload["t_s"])
    b.cycle_h.append(payload["centre_v"][0])
    b.cycle_v.append(payload["centre_v"][1])
    b.centre_s.append(payload["centre_signal_a"])
    b.ring_s.append(payload["ring_mean_a"])
    b.best_v = tuple(payload["best_v"])
    plots.trajectory.setData(b.cycle_h, b.cycle_v)
    plots.centre_curve.setData(b.cycle_t, b.centre_s)
    plots.ring_curve.setData(b.cycle_t, b.ring_s)
    _update_markers(plots)


def show_result(plots: AutoAlignmentPlots, result: AutoAlignmentResult) -> None:
    plots.buffers.start_v = tuple(result.start_v)
    if result.map is not None and result.map.signal_a.size:
        m = result.map
        grid = m.signal_a.copy()
        if np.all(np.isnan(grid)):
            return
        grid[np.isnan(grid)] = np.nanmin(grid)
        dh = float(m.h_axis_v[1] - m.h_axis_v[0]) if m.h_axis_v.size > 1 else 1.0
        dv = float(m.v_axis_v[1] - m.v_axis_v[0]) if m.v_axis_v.size > 1 else 1.0
        plots.image.setImage(grid, autoLevels=True)
        plots.image.setRect(QRectF(m.h_axis_v[0] - dh / 2, m.v_axis_v[0] - dv / 2,
                                   dh * m.h_axis_v.size, dv * m.v_axis_v.size))
        plots.samples.setData([], [])
        plots.buffers.best_v = tuple(m.local_min_v) if m.dip_found else None
    elif result.track is not None:
        plots.buffers.best_v = tuple(result.track.best_v)
    _update_markers(plots)


def clear_plots(plots: AutoAlignmentPlots) -> None:
    plots.buffers = LiveBuffers()
    plots.image.clear()
    plots.samples.setData([], [])
    plots.trajectory.setData([], [])
    plots.markers.setData([])
    plots.centre_curve.setData([], [])
    plots.ring_curve.setData([], [])


def _update_markers(plots: AutoAlignmentPlots) -> None:
    spots = []
    if plots.buffers.start_v is not None:
        spots.append({"pos": plots.buffers.start_v, "symbol": "x", "brush": pg.mkBrush("k"),
                      "pen": pg.mkPen("k", width=2)})
    if plots.buffers.best_v is not None:
        spots.append({"pos": plots.buffers.best_v, "symbol": "star",
                      "brush": pg.mkBrush(40, 170, 80), "pen": pg.mkPen("k")})
    plots.markers.setData(spots)


def _brushes(values: np.ndarray) -> list:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return [pg.mkBrush(128, 128, 128)] * values.size
    lo, span = float(finite.min()), float(np.ptp(finite)) or 1.0
    normalized = np.clip((np.nan_to_num(values, nan=lo) - lo) / span, 0.0, 1.0)
    colours = pg.colormap.get(_CMAP).map(normalized, mode="qcolor")
    return [pg.mkBrush(c) for c in colours]
