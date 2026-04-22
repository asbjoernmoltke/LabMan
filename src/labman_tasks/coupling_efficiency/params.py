from dataclasses import dataclass
from typing import Annotated

from labman_core.schema import ParamMeta, Range


@dataclass
class CouplingEfficiencyParams:
    power_start: Annotated[
        float,
        ParamMeta(display="Start", unit="mW", bounds=Range(0.0, 100.0), group="Sweep"),
    ] = 1.0

    power_stop: Annotated[
        float,
        ParamMeta(display="Stop", unit="mW", bounds=Range(0.0, 100.0), group="Sweep"),
    ] = 10.0

    power_steps: Annotated[
        int,
        ParamMeta(display="# points", bounds=Range(2, 1000), group="Sweep"),
    ] = 5

    wavelength_nm: Annotated[
        float,
        ParamMeta(display="Wavelength", unit="nm", bounds=Range(400.0, 2000.0), group="Laser"),
    ] = 1550.0

    averages_per_point: Annotated[
        int,
        ParamMeta(display="Averages", bounds=Range(1, 1000), group="Acquisition"),
    ] = 10

    settle_time_s: Annotated[
        float,
        ParamMeta(
            display="Settle time", unit="s", bounds=Range(0.0, 10.0), group="Acquisition"
        ),
    ] = 0.05

    correction_factor: Annotated[
        float,
        ParamMeta(
            display="Correction factor",
            bounds=Range(0.0, 10.0),
            group="Analysis",
            tooltip="Multiplier applied to the input-power channel during analysis.",
        ),
    ] = 1.0

    abort_below: Annotated[
        float | None,
        ParamMeta(
            display="Abort if efficiency below",
            unit="",
            bounds=Range(0.0, 1.0),
            optional=True,
            group="Guards",
        ),
    ] = None
