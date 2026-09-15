# KNA-IR hardware scripts

Scripts used to bring up and characterise the Thorlabs KNA-IR (K-Cube NanoTrak,
S/N 57535374) fibre-incoupling alignment, with the PM100USB (S/N 1931430) at the
fibre output. Serial numbers are hard-coded for that lab setup.

Run from the repository root, with the project's virtual environment:

```powershell
.venv\Scripts\python.exe examples\kna\<script>.py [args]
```

Close the Kinesis app and Thorlabs Optical Power Monitor first; only one program can
hold each device. Outputs go to `app/data/...` (not in git). The plotting scripts need
matplotlib (`.venv\Scripts\python.exe -m pip install matplotlib`).

## Moving the mirror

| Script | What it does | Moves the mirror? |
|---|---|---|
| `map_run.py <half width V> <points> [settle s] [averages] [min start nA]` | Auto-alignment map around the current position via `run_headless`; refuses to scan if the start signal is below the threshold (laser blocked); saves `map.png` | Yes, returns to start |
| `static_cross.py [offsets] [settle s] [samples]` | Holds ±offsets along each axis, back to centre between points, logs KNA stray light and PM100 power; saves CSV/JSON/PNG | Yes, returns to centre |
| `track_run.py [duration] [radius] [min contrast] [averages] [settle] [max excursion] [max step]` | Tracking mode via `run_headless` with the PM100 logged alongside (not used for control); saves `power_log.csv`, `track.png` | Yes, ends latched at best |
| `step_response.py [low H] [high H] [V] [cycles] [record s]` | Jumps H between two voltages and samples the detector every ~20 ms to measure reading lag | Yes, returns to start |
| `freeze_trigger.py` | Small moves at decreasing dwell times, checking the KNA still delivers fresh data | Yes, returns to 75/75 V |
| `goto.py <H> <V> [step V]` | Ramps the outputs to a position in small steps and leaves them latched there | Yes |

## Read-only / analysis

| Script | What it does |
|---|---|
| `diag_status.py` | KNA firmware, range, mode, status bits and raw readings (spots frozen data) |
| `gain_check.py [range codes]` | Forces TIA ranges in turn at a fixed position and compares the converted current; restores the range mode |
| `pm_log.py [duration s] [interval s]` | Prints and logs PM100 power once per interval (live CSV) |
| `plot_map_mpl.py <run folder> <out.png> [sigma]` | Raw and smoothed map with contours |
| `inspect_run.py <run folder> [every]` | Coarse text grid and where out-of-range points are |
| `direction_check.py <run folder> [max shift]` | Scan-direction offset between serpentine rows (reading lag) |
| `compare_maps.py <old> <new> <out.png> [labels]` | Side-by-side comparison of two same-grid maps |
| `split_power.py <old> <new> <ratio> <out.png>` | Splits two maps at different laser powers into power-proportional and constant parts |

Findings from these runs are recorded in [STATUS.md](../../STATUS.md) ("Next up").
