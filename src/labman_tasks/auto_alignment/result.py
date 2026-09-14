from dataclasses import dataclass

import numpy as np

# sample_kind codes
KIND_CENTRE = 0
KIND_PROBE = 1
KIND_MAP = 2

# cycle_reason_code -> name (index into this tuple)
CYCLE_REASONS = ("step", "not_in_dip", "out_of_range", "degenerate", "max_excursion",
                 "voltage_limit")


@dataclass
class AutoAlignmentRawData:
    mode: str                       # "map" | "track"
    # "completed" | "stopped" | "duration" | "max_excursion" | "voltage_limit"
    stop_reason: str
    max_voltage_v: float
    start_v: np.ndarray             # (2,) position before the run
    best_v: np.ndarray              # (2,) position the hardware was left latched at
    best_signal_a: float            # centre signal at best_v (NaN if never confirmed in a dip)

    # every detector reading average, in acquisition order
    sample_t_s: np.ndarray          # (S,) seconds since run start
    sample_h_v: np.ndarray          # (S,)
    sample_v_v: np.ndarray          # (S,)
    sample_signal_a: np.ndarray     # (S,) mean of `averages` readings
    sample_in_range: np.ndarray     # (S,) bool
    sample_kind: np.ndarray         # (S,) KIND_*
    sample_cycle: np.ndarray        # (S,) tracking cycle index, -1 in map mode
    sample_map_i: np.ndarray        # (S,) horizontal grid index, -1 in track mode
    sample_map_j: np.ndarray        # (S,) vertical grid index, -1 in track mode

    # map grid axes (empty in track mode)
    map_h_axis_v: np.ndarray
    map_v_axis_v: np.ndarray

    # one entry per completed tracking cycle (empty in map mode)
    cycle_t_s: np.ndarray
    cycle_centre_h_v: np.ndarray
    cycle_centre_v_v: np.ndarray
    cycle_centre_signal_a: np.ndarray
    cycle_ring_mean_a: np.ndarray
    cycle_gradient_h_a_per_v: np.ndarray
    cycle_gradient_v_a_per_v: np.ndarray
    cycle_curvature_a_per_v2: np.ndarray
    cycle_in_dip: np.ndarray        # bool
    cycle_reason_code: np.ndarray   # index into CYCLE_REASONS
    cycle_next_h_v: np.ndarray      # centre used for the next cycle (after limits)
    cycle_next_v_v: np.ndarray


@dataclass
class AlignmentMap:
    h_axis_v: np.ndarray
    v_axis_v: np.ndarray
    signal_a: np.ndarray            # (n_v, n_h); NaN where not measured
    min_v: np.ndarray               # (2,) global minimum — may lie beyond the bright ring
    min_signal_a: float
    local_min_v: np.ndarray         # (2,) where walking downhill from the start ends
    local_min_signal_a: float
    dip_found: bool                 # False if that walk ends on the map edge (no dip inside)
    start_signal_a: float           # grid point nearest the start position
    radial_r_v: np.ndarray          # ring radii, one grid step apart, around local_min_v
                                    # (around the start position if no dip was found)
    radial_signal_a: np.ndarray     # mean signal per ring
    profile_shape: str              # "dip_in_ring" | "minimum" | "maximum" | "flat" | "unknown"


@dataclass
class TrackSummary:
    n_cycles: int
    duration_s: float
    in_dip_fraction: float
    final_v: np.ndarray             # (2,) last commanded centre
    drift_v: float                  # |final - start|
    best_v: np.ndarray
    best_signal_a: float
    median_centre_signal_a: float


@dataclass
class AutoAlignmentResult:
    mode: str
    stop_reason: str
    start_v: np.ndarray
    map: AlignmentMap | None = None
    track: TrackSummary | None = None
