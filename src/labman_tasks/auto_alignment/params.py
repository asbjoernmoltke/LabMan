from dataclasses import dataclass
from typing import Annotated, Literal

from labman_core.schema import ParamMeta, Range


@dataclass
class AutoAlignmentParams:
    mode: Annotated[
        Literal["map", "track"],
        ParamMeta(
            display="Mode",
            group="Mode",
            tooltip="map: raster a small grid around the current position, then return to it.\n"
                    "track: probe a small circle and step toward the signal dip until stopped.",
        ),
    ] = "map"

    # ----- probing (both modes) -----
    settle_time_s: Annotated[
        float, ParamMeta(display="Settle time", unit="s", bounds=Range(0.0, 1.0), group="Probe",
                         tooltip="Wait after each move before reading the detector.")
    ] = 0.02
    averages: Annotated[
        int, ParamMeta(display="Readings per point", bounds=Range(1, 50), group="Probe",
                       tooltip="Detector readings averaged per point (~50 ms each on the KNA). "
                               "Single readings scatter ~2-3 %; 1 is fine for a quick map, "
                               "tracking decisions need 3 or more.")
    ] = 3

    # Defaults below are scaled to the K1S2P mount on the lab KNA-IR: a 20 V swing
    # changed the stray-light signal by ~17 %, so sub-volt steps are invisible.

    # ----- map -----
    map_half_width_v: Annotated[
        float, ParamMeta(display="Half width", unit="V", bounds=Range(0.05, 20.0), group="Map")
    ] = 10.0
    map_points: Annotated[
        int, ParamMeta(display="Points per axis", bounds=Range(3, 101), group="Map")
    ] = 11

    # ----- tracking -----
    probe_radius_v: Annotated[
        float, ParamMeta(display="Probe radius", unit="V", bounds=Range(0.01, 10.0),
                         group="Tracking",
                         tooltip="Radius of the probe circle around the centre. Must be small "
                                 "compared to the dip, or the ring is sampled instead.")
    ] = 2.0
    probe_points: Annotated[
        int, ParamMeta(display="Probe points", bounds=Range(4, 64), group="Tracking")
    ] = 8
    gain: Annotated[
        float, ParamMeta(display="Gain", bounds=Range(0.0, 1.0), group="Tracking",
                         tooltip="Fraction of the estimated distance to the minimum moved per "
                                 "cycle (1 = full Newton step).")
    ] = 0.5
    max_step_v: Annotated[
        float, ParamMeta(display="Max step", unit="V", bounds=Range(0.001, 5.0), group="Tracking")
    ] = 0.5
    min_contrast: Annotated[
        float, ParamMeta(display="Min dip contrast", bounds=Range(0.0, 1.0), group="Tracking",
                         tooltip="The centre must be this fraction below its surroundings to "
                                 "count as 'in the dip'. Otherwise the loop holds still.")
    ] = 0.05

    # ----- limits -----
    max_excursion_v: Annotated[
        float, ParamMeta(display="Max excursion", unit="V", bounds=Range(0.05, 75.0),
                         group="Limits",
                         tooltip="Tracking stops (and holds the best position) rather than move "
                                 "further than this from the starting position.")
    ] = 10.0
    duration_s: Annotated[
        float | None, ParamMeta(display="Stop after", unit="s", bounds=Range(1.0, 86400.0),
                                optional=True, group="Limits",
                                tooltip="Unchecked: track until Stop is pressed.")
    ] = None
