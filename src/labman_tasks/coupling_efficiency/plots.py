from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from labman_tasks.coupling_efficiency.result import CouplingEfficiencyResult


@dataclass
class CouplingEfficiencyPlots:
    """Two stacked plots: powers (top) and efficiency (bottom).

    Holds the QWidget plus references to the four curves so live updates can
    push new (x, y) data without rebuilding the plot.
    """

    widget: QWidget
    p_in_curve: pg.PlotDataItem
    p_out_curve: pg.PlotDataItem
    eff_curve: pg.PlotDataItem


def make_plots() -> CouplingEfficiencyPlots:
    """Construct the empty two-plot layout. Push data via `update_live` or `show_result`."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    powers = pg.PlotWidget()
    powers.setBackground("w")
    powers.setLabel("bottom", "Setpoint", units="mW")
    powers.setLabel("left", "Power", units="W")
    powers.addLegend(offset=(10, 10))
    powers.showGrid(x=True, y=True, alpha=0.3)
    p_in = powers.plot([], [], pen=pg.mkPen(color=(60, 120, 220), width=2),
                       symbol="o", symbolSize=6, symbolBrush=(60, 120, 220),
                       name="P_in")
    p_out = powers.plot([], [], pen=pg.mkPen(color=(220, 100, 60), width=2),
                        symbol="o", symbolSize=6, symbolBrush=(220, 100, 60),
                        name="P_out")

    eff = pg.PlotWidget()
    eff.setBackground("w")
    eff.setLabel("bottom", "Setpoint", units="mW")
    eff.setLabel("left", "Efficiency", units="")
    eff.showGrid(x=True, y=True, alpha=0.3)
    eff_curve = eff.plot([], [], pen=pg.mkPen(color=(40, 160, 80), width=2),
                         symbol="o", symbolSize=6, symbolBrush=(40, 160, 80))
    eff.setXLink(powers)

    layout.addWidget(powers, 1)
    layout.addWidget(eff, 1)

    return CouplingEfficiencyPlots(
        widget=container,
        p_in_curve=p_in,
        p_out_curve=p_out,
        eff_curve=eff_curve,
    )


def update_live(
    plots: CouplingEfficiencyPlots,
    setpoints_mw: list[float],
    p_in_w: list[float],
    p_out_w: list[float],
) -> None:
    """Push accumulated points to the plots during acquisition.

    Caller maintains the running lists; this function just calls setData.
    Efficiency is computed pointwise as p_out / p_in (NaN where p_in <= 0).
    """
    x = np.asarray(setpoints_mw, dtype=float)
    pi = np.asarray(p_in_w, dtype=float)
    po = np.asarray(p_out_w, dtype=float)
    plots.p_in_curve.setData(x, pi)
    plots.p_out_curve.setData(x, po)
    with np.errstate(divide="ignore", invalid="ignore"):
        eff = np.where(pi > 0, po / pi, np.nan)
    plots.eff_curve.setData(x, eff)


def show_result(plots: CouplingEfficiencyPlots, result: CouplingEfficiencyResult) -> None:
    """Render a final result onto the plots, replacing any live trace."""
    plots.p_in_curve.setData(result.setpoints_mw, result.p_in_mean_w)
    plots.p_out_curve.setData(result.setpoints_mw, result.p_out_mean_w)
    plots.eff_curve.setData(result.setpoints_mw, result.efficiency)


def clear_plots(plots: CouplingEfficiencyPlots) -> None:
    plots.p_in_curve.setData([], [])
    plots.p_out_curve.setData([], [])
    plots.eff_curve.setData([], [])
