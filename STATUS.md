# LabMan — Implementation Status

Living snapshot of what exists, what's planned, and what's been deliberately
deferred. Update this file whenever the answer to any of those changes.

For *rules and conventions*, see [CLAUDE.md](CLAUDE.md). This document only
tracks state.

Last updated: 2026-09-14 (auto-alignment task, KNA-IR driver)

---

## Done

### `labman_core`
- [x] `roles.DeviceRole` (StrEnum: LASER, POWER_METER, CAMERA, SPECTROMETER, STAGE)
- [x] `schema`: `Range`, `ParamMeta`, `Setable`, `Readable`, `Action`, `DeviceControls`
- [x] `devices`: `Device`, `LaserSource`, `PowerMeter` Protocols + `LaserState`
- [x] `storage`: `StorageOptions`, `RunStorage`, `DEFAULT_DATA_ROOT = Path("app/data")`
- [x] `context`: `TaskContext`, `ProgressReporter`, `LivePublisher`
- [x] `exceptions.AbortConditionMet` — typed signal for user-defined guards
- [x] `task.Task` Protocol — now includes `to_safe_state(devices)` per the Safety contract
- [x] `shell.ShellServices` Protocol
- [x] `lab_config.LabConfig` / `DeviceConfig` / `DeviceSync` — `lab.yaml` v1 loader (driver dotted path, role, args, `sync_policy` default `hydrate`, `defaults` for `push_defaults`, optional unique `resource`), validated with clear errors
- [x] `resource_lock.ResourceLock` — non-blocking cross-process OS file lock per resource string (msvcrt / flock); released by the OS if the process dies
- [x] `registry.DeviceRegistry` — imports + instantiates drivers from `LabConfig` (passes config `name` only if the constructor accepts it), lookup by name/role/sync policy, best-effort `shutdown_all` (then releases locks); `{device: <name>}` args pass an earlier-declared device instance
  - Per-device failures (driver error, resource busy, dependency failed) recorded in `failures`, excluded from lookups; the rest of the lab starts
  - `connect_sync(name)` / `mark_synced(name)` — configured policy on first use per session, `hydrate` afterwards (`skip` stays `skip`)
- [x] `SimPowerMeter(source_laser=...)` — lab.yaml-friendly alternative to the `source_mw` callable
- [x] `schema.Readable.display_precision` — values below this render as "0" in panels
- [x] `simulators.SimLaser`, `simulators.SimPowerMeter`
  - SimPowerMeter: choices/int/calibrate action, **negative reads allowed** (no clipping); power/offset readables carry `display_precision=1e-9`

### `labman_app`
- [x] **Committed to PySide6** (6.11).
- [x] `widgets.SchemaWidget` base — `committed(value)` signal contract, `value()/set_value()` API
- [x] `widgets.NumericInput` — slider+entry composite when bounds present
- [x] `widgets.ChoiceInput`, `BoolInput`, `TextInput`, `OptionalWrapper`
- [x] `forms.build_params_form(cls)` — `(QWidget, getter)` from `Annotated[T, ParamMeta]` dataclasses; getter enforces bounds and names the field on errors
- [x] `forms.build_params_form_with_presets(cls, store)` — preset bar above the form; starts from `__last_used__` when it still validates. Shared internal setter applies values with type + bounds validation and restores the form on failure.
- [x] `forms.build_device_panel(device)` — returns `DevicePanel(widget, setable_widgets, readable_labels, readables)`; three sections (Settings/Readouts/Actions); async commits via running loop
- [x] `forms.sync_panel_from_device(panel, device)` — one-shot hydrate of setables from device state
- [x] `forms.poll_readables(panel, interval_s)` — background task updates readable labels at configured rate (5 Hz default)
- [x] `services` (Qt-free) — `discover_tasks()` via `labman.tasks` entry points (broken tasks logged + skipped); `default_bindings` (remembered device, then name match, then first free device of the role; never shares a device); `validate_bindings`; `RegistryShellServices` (real `ShellServices`)
- [x] `shell.ShellWindow` — task list | binding page (combo per binding, filtered by role) → hosts task widget and awaits `initialize()`. Switching tasks asks for confirmation, then `widget.shutdown()` + `task.to_safe_state`. Window close defers until safe-state + `registry.shutdown_all` have run.
  - Binding page pre-selects remembered bindings, lists unavailable devices of the task's roles; bindings saved and devices marked synced only after a successful open
  - A failed `initialize()` (e.g. default push rejected) runs safe state and returns to the binding page with the error
- [x] `forms.apply_sync_policy(panel, device, sync)` — `hydrate` / `push_defaults` (write in order, then hydrate; raises on unknown setable or rejected value) / `skip`
- [x] `binding_store.BindingStore` — last-used bindings per task in `app/state/bindings.json`; tolerant of missing/corrupt file
- [x] `presets.PresetStore` (Qt-free) — `app/presets/<task_name>.json`; named save/load/delete, `__last_used__`, reserved `__` names, unreadable file moved to `.corrupt` before writing; `params_to_dict` / `params_from_dict` (Enum, Literal, Path, bool/int/float strictness, defaults for missing fields, unknown keys reported)
- [x] `widgets.PresetBar` — preset dropdown incl. "(last used)", Load / Save as… / Delete with overwrite + delete confirmation, inline error messages
- [x] `ShellServices.device_sync(binding)` — task widgets ask the shell which sync to apply
- [x] `ShellServices.params_form(task_name, params_cls)` / `run_succeeded(task_name, params)` — presets wired by the shell; `RegistryShellServices(presets_root=None)` disables presets (tests, demo)
- [x] `shell.main()` / `python -m labman_app --lab <lab.yaml> [--data-root]` — fatal dialog only if `lab.yaml` can't be loaded; unavailable devices → warning, app starts without them

### `labman_tasks.coupling_efficiency`
- [x] `params.CouplingEfficiencyParams` (`Annotated[T, ParamMeta]` schema)
- [x] `result.CouplingEfficiencyRawData`, `CouplingEfficiencyResult`
- [x] `safety.py` — load-bearing safe-state for the task (laser power=0, disabled). Idempotent, non-raising.
- [x] `workflow.acquire()` (async, hardware IO only, finally → `safety.to_safe_state`, publishes `point` events, **honors `abort_below`** by raising `AbortConditionMet`)
- [x] `analysis.analyze()` (pure function, NaN-safe)
- [x] `task.CouplingEfficiencyTask` — glue + HDF5/JSON/meta persistence; `to_safe_state` delegates to `safety.py`; `run_headless` finally calls it as defense-in-depth
- [x] `plots.py` — pyqtgraph two-plot stack
- [x] `widget.CouplingEfficiencyWidget` — three-column layout, Start/Stop/progress, async run lifecycle, live plot updates, hydrate + poll on `initialize()`, **friendly status for `AbortConditionMet`**, live buffers initialised in `__init__` (not just on Start), params form from the shell (presets), reports successful runs
- [x] Entry-point registered in `pyproject.toml`

### `labman_tasks.auto_alignment` (Thorlabs KNA-IR fiber-incoupling alignment)
- [x] Core: `DeviceRole.ALIGNER`, `Aligner` protocol + `SignalReading`; `TaskContext.request_stop()` / `stop_requested` for graceful stop
- [x] `simulators.SimAligner` — donut (dip inside bright ring) or bowl profile, drift, noise, voltage-range checks
- [x] `drivers.KinesisNanoTrak` — Kinesis C API via ctypes; keeps the KNA latched (firmware tracking maximizes and is never enabled); verifies the 75/150 V range and switches it only when `set_voltage_range` is enabled; blocking calls in a worker thread; shutdown latches without zeroing outputs
- [x] `drivers.ThorlabsPM100` — Thorlabs PM100-series power meter (PM100USB) via TLPMX_64.dll and ctypes (the PM100USB uses Thorlabs' USB driver, not VISA USBTMC, so pyvisa cannot see it); opens by serial with ID query and no reset; `read_power_w`, wavelength / auto range / average time setables with sensor limits; blocking calls in a worker thread; `pm_out` in `examples/lab.kna.yaml`
- [x] `persistence` (core) — dataclass ↔ HDF5 (nested, None, bool/int/str attrs), params/meta JSON; used by `auto_alignment` (coupling efficiency not migrated yet)
- [x] `algorithm.py` (pure) — probe circle, plane fit + curvature, Newton step toward the dip only when the centre is confirmed lower than its ring; holds on ring/flat/out-of-range/degenerate; excursion and voltage limits; serpentine map raster
- [x] `workflow.py` — map mode (returns to start) and continuous track mode (until Stop, duration, or a limit); every sample and cycle logged and published live; `finally` → safe state
- [x] `safety.py` — latch, then move to `hold_at` (best confirmed centre when tracking, start after a map); never zeroes outputs
- [x] `analysis.py` — map grid; nearest dip = downhill walk from the start (the global minimum can be background beyond the ring and is reported separately); `dip_found` false when the walk runs off the map edge; radial profile in one-grid-step rings + advisory `profile_shape`; tracking summary (cycles, in-dip fraction, drift, best)
- [x] `plots.py` / `widget.py` — position plane (live samples coloured by signal, centre trajectory, start/best markers, map heatmap) + signal vs time; Stop = graceful, second Stop = force; `labman_app.widgets.layout` column helpers
- [x] `examples/lab.sim.yaml` gains a simulated aligner; `examples/lab.kna.yaml` template for the real KNA
- [x] Fixes found by the smoke test: `RunStorage` timestamp dirs no longer collide when two runs start within one second; both task widgets create storage inside `try`, so a storage error resets the UI instead of leaving Start disabled

### Tests (265 passing)
- [x] Storage: 5 tests (incl. runs started in the same second get `_1`, `_2` suffixes)
- [x] Analysis: 3 tests
- [x] Workflow E2E: 5 tests
- [x] SimPowerMeter: 8 tests (incl. negative reads after calibrate, negative noise samples not clipped, display_precision present)
- [x] Widgets: 12 tests
- [x] Forms: 23 tests (incl. hydrate sync, readable polling, sub-precision suppression, sync policies, setter validation + rollback, field-named errors, last-used seeding)
- [x] Presets: 25 tests (params ↔ dict round trip and type coercion/rejection, store save/load/delete, last-used separation, reserved names, corrupt file set aside)
- [x] Preset bar: 10 tests (round trip, name dialog, overwrite/delete confirmation, reserved name, invalid form, invalid preset leaves form unchanged, unknown fields reported, last-used entry)
- [x] SimAligner: 10 tests (profiles, bounds, drift, noise, controls)
- [x] Auto-alignment algorithm: 12 tests (Newton step, gain/clip, steps inside donut dip, holds on ring/flat/out-of-range/degenerate, clipped probes, limits, serpentine map)
- [x] Auto-alignment workflow + safety: 13 tests (map saves/returns to start, saved raw re-analyzes identically, stop during map, tracking converges and latches at best, follows drift, holds on ring, excursion limit, duration, cancellation, device error, safe state idempotent/non-raising, task delegate latches in place)
- [x] Auto-alignment analysis: 11 tests (dip_in_ring / minimum / maximum / flat classification, coarse offset map finds nearest dip not background beyond ring, downhill walk, missing points, out-of-range zeros are not a dip, track summary)
- [x] Auto-alignment widget: 5 tests (map run, graceful stop saves, second Stop force-cancels, hydrate, storage failure reports error and resets UI)
- [x] Persistence: 4 tests (nested round trip incl. None/bool/empty arrays, unsupported type, params and meta JSON)
- [x] KinesisNanoTrak (fake DLL): 25 tests (signal from relative reading × range full scale, garbage absolute ignored, unknown range retried then NaN; position right after a move is the commanded one; connect latches, default 200 ms polling, simulator flag, voltage-range refusal closes device, opt-in range switch 75→150 / 150→75 / mixed channels never exceeding the starting voltage, refusal above new range, switch that doesn't take, persist failure, no change without opt-in or when matching, open error, V ↔ device units, out-of-range move never sent, range flag, latch/identify/idempotent shutdown, controls, example yaml)
- [x] ThorlabsPM100 (fake TLPMX DLL): 8 tests (open by serial without reset, read power and settings incl. sensor limits, initial wavelength, missing meter lists what was found, meter in use refused, init failure reports vendor message, measurement error + idempotent shutdown, controls)
- [x] Coupling-efficiency widget: 5 tests
- [x] Coupling-efficiency safety: 8 tests (idempotency, missing laser, abort raises + cleans up, abort doesn't trigger when efficiency above threshold, safety on normal completion, safety on unhandled workflow error)
- [x] Lab config: 12 tests (round trip, full config, bad version/role/sync_policy, missing driver, defaults/push_defaults rules, resource validation + duplicates)
- [x] Device registry: 19 tests (instantiation w/ and w/o `name` kwarg, idempotency, role/policy lookup, per-device failures incl. dependencies and no retry, shutdown continues past failures, device references, resource locks incl. second registry locked out until shutdown, connect-sync once per session)
- [x] Resource lock: 5 tests (idempotent acquire/release, busy, re-acquire, independence, cross-process + released when holder exits)
- [x] Binding store: 5 tests (round trip, missing/corrupt file, per-task independence, junk entries ignored)
- [x] Shell services: 19 tests (discovery, default bindings incl. no sharing and remembered/stale bindings, validation errors incl. unavailable, services resolution + device_sync, run_succeeded → last used, `examples/lab.sim.yaml` stays valid)
- [x] Shell window: 13 tests (presets wired + last used follows runs and seeds reopened form, no preset bar without presets root, binding defaults, open + hydrate, invalid bindings rejected, close runs safe state, window close deferred, push_defaults first open only, skip leaves widgets blank, failed push returns to binding page, bindings remembered across windows / not saved on failure, unavailable devices listed)

### Tooling / Examples
- [x] `pyproject.toml` (hatchling, numpy, h5py, pytest-asyncio, ruff, `[app]` extra: PySide6 / qasync / pyqtgraph)
- [x] `.gitignore`, `CLAUDE.md`, `STATUS.md`
- [x] `tests/conftest.py` — session-scoped `qapp` fixture
- [x] `examples/coupling_efficiency_demo.py` — single task widget against simulators, no shell (`DemoShell` stub)
- [x] `examples/lab.sim.yaml` — simulated laser + two power meters; `python -m labman_app --lab examples/lab.sim.yaml`

---

## Next up (logical next slice)

KNA-IR hardware bring-up for `auto_alignment` (everything so far is verified against simulators and a fake Kinesis DLL only):

- [x] Connected KNA-IR S/N 57535374 through LabMan's driver (2026-09-14): 150 V range verified, latch mode, feedback source TIA, outputs at H 74.6 V / V 75.3 V after hand alignment; serial in `examples/lab.kna.yaml`
- [x] Readings: no delay returns the same stale value; ≥30 ms gives fresh ones → default `read_delay_s` 50 ms (~50 ms per reading). Occasional garbage `absoluteReading` (~1e-38 with a normal relative value) → driver cross-checks against relative × range, retries, else returns NaN flagged out of range
- [x] Latch-mode moves reach the piezos (2026-09-14): a 20 V peak-to-peak horizontal swing (1 s dwell, 10 cycles) modulated the stray-light signal ~4.1 ↔ ~4.8 nA in lock with every cycle. Steps of 0.1–5 V were too small to notice by eye or in coupling efficiency
- [x] Kinesis resets the HV output range to 75 V whenever it connects (its built-in defaults). Driver opt-in `set_voltage_range: true` (on in `lab.kna.yaml`) switches the range on connect without ever raising the real output voltage (lower-then-switch for channels going up, switch-then-raise for channels going down), refuses if an output is above the new range, persists with `NT_PersistSettings`, and verifies range + position. Tested against the fake DLL only
- [x] Range switch on hardware (2026-09-15): Kinesis had left 75 V with outputs at mid-scale (37.5 V real). Connecting with `set_voltage_range: true` switched to 150 V in ~1 s (3 s connect in total), kept H/V at 37.50 V (words 32768 → 16384), and the range persisted across a fresh connect. Stray-light signal 4.71 → 5.17 nA (±0.15) across the switch; possibly piezo hysteresis from the ~1 s dip to 18.75 V — to be confirmed against the coupling
- [x] Piezos moved to 75 V / 75 V (mid-range) for a hand re-alignment there (2026-09-15). Kinesis had probably also reset the outputs to mid-scale of its 75 V range (37.5 V)
- [ ] **KNA stops delivering fresh data (2026-09-15), intermittently.** Symptoms: readings frozen at one value, status bits frozen at an impossible value (0x001c0665: tracking + under-read + over-read, channels not connected), or all-zero status/readings (out of range) for seconds after connect. The first map got 76/121 out-of-range zeros, the second map 121 identical readings. A USB replug recovers it; it also recovered by itself once. No other process holds the device and Kinesis logs show nothing. Suspects: the external USB2514 hub between laptop and KNA, and USB selective suspend (enabled on AC and DC). The hub is built into the instrument power supply (cannot be bypassed); the KNA front display keeps updating during a freeze, so the USB link is at fault. USB selective suspend disabled (AC and DC) on 2026-09-15; per-device power-off on the hub and USB 3 root hubs still to be disabled (needs admin). Per-device power-off then disabled on the hub and root hubs too; the freeze still persisted until a replug. **Cause: polling rate.** With `poll_ms` 20 the KNA stops answering status/reading requests after bursts of moves (and stays so until a replug); with 200 ms (as in all Thorlabs examples) a move-rate test down to 20 ms dwell and a full 11×11 map stayed fresh. Driver default is now 200 ms
- [x] With 200 ms polling the garbage `absoluteReading` (~1e-38) became frequent (a map discarded 267 readings, 77/121 points NaN, 19.5 s). The driver now takes the signal from `relativeReading / 32767 × range full scale` and ignores `absoluteReading`; unknown range codes are retried, then NaN out of range. Stored currents are ≈ 2.8× the KNA's absolute value (constant factor, consistent across ranges) and not calibrated in amps
- [x] First complete map (2026-09-15, ±10 V × 11 points around 75/75 V, 1 reading, 9.7 s, 121/121 valid): a smooth slope, ~13–14 nA towards low H/low V down to ~8–9 nA towards high H/high V, no dip inside the map. The analysis' `dip_found` (a single point ~1 nA below its neighbours) is within point-to-point scatter
- [ ] Map analysis: noise-aware dip detection (a single point below its neighbours by less than the scatter should not count as a dip)
- [x] Wide map (2026-09-15, ±30 V × 11 points, 0.15 s settle, 25 s, 121/121 valid): brightest towards low H + low V (~22–24 nA), lowest towards high V (~5–6 nA at V 99–105 V, H 63–75 V) and a low stretch near H 93 V; the hand-aligned start (12 nA) sits on the slope, not in a dip. After returning to 75/75 V the coupling efficiency was back where it started (piezo return is repeatable). Which direction is "good" is still unknown: coupling was not recorded during the scan
- [x] High-resolution map (2026-09-15, ±10 V around 75/75 V in 0.5 V steps, 41×41, 1 reading, 132 s, 1681/1681 valid; drift check at start 11.54 ± 0.28 → 11.73 ± 0.53 nA): no dip or ring at the hand-aligned position at this resolution. Smoothed (σ = 1 V) it is a smooth slope from ~14 nA at low H/low V to ~9 nA towards high H/high V; point-to-point scatter 0.44 nA. The wide ±30 V map shows the same slope, lowest along V ≈ 100–105 V, brightest at the low H/low V corner (still rising at the map edge). Plots via scratch matplotlib script (matplotlib installed in the venv, not in pyproject)
- [ ] Open question: is the stray light not minimal at best coupling, is the dip shallower than the scatter, or does the region of interest need a full-range (0–150 V) coarse map? Needs coupling-vs-voltage data (spot check or power meter logged during a map)
- [x] Same high-res map after raising the laser power 10× (2026-09-15, run 20260915T104822): the signal only rose ~1.47× (median per point, 1.21–2.10; 11.5 → 16.8 nA at 75/75 V), so most of the KNA signal does not scale with laser power. Point-by-point difference (new − old, shape independent of the assumed power ratio) shows a broad minimum just left of the hand alignment (~70–73 V H, 72–78 V V) rising towards high H / high V — the first dip-like structure seen. The non-scaling remainder still varies with mirror position (7–15 nA), which a true background could not; to be explained (did the input power really rise 10×? second light source? detector linearity?)
- [x] KNA dark level with the laser blocked (2026-09-15, at 75/75 V): 0.35 ± 0.34 nA (0–1 nA), negligible against the 11–17 nA map signal — the signal is light from the laser path, yet it rose only ~1.5× with 10× laser power. Open: how/where the power was raised, and whether the collected light saturates or comes from a part of the beam that did not scale
- [x] Full-range map (2026-09-15, run 20260915T105745: 0–150 V both axes, 5 V steps, 50 ms settle, 1 reading, 99 s): signal 6–147 nA. The hand alignment (75/75 V, ~25 nA) sits on the lower wall of a dark valley whose bottom is ~15 nA near H 80 V / V 90–100 V, between bright lobes left (~40/70 V, ~58 nA) and right (~140/70 V, ~60 nA), with a brighter region below (~100/10 V, ~90 nA); the valley is open upwards (~24 nA at V 140 V). All 61 out-of-range points are exactly the V = 150 V row and H = 150 V column (readings fail at full output). Signal at 75/75 V: 16.7 nA before, 15.0 nA after (possible piezo return offset after a 150 V swing)
- [ ] Scan-direction offset in serpentine maps: in the full-range map left-to-right and right-to-left rows correlate best when shifted by ~10–15 V against each other (corr 0.88 at 10 V, 0.85 at 15 V, 0.64 unshifted), so each scan direction lags by ~5–7 V (~1 point ≈ 0.1–0.15 s): readings lag the mirror position (200 ms polling cache, detector filtering or piezo response). Horizontal feature positions are uncertain by ~±5 V. Measure with `step_response.py`; then fix in the workflow (longer settle, single scan direction, or lag correction)
- [x] Full-range map after moving the collection fibre (2026-09-15, run 20260915T111350, same settings): signal 2.3× higher (median; 16–422 nA), start 42.7 nA before / 45.0 nA after. Normalised shape correlation with the previous full-range map only 0.09: lobes moved (left lobe → ~35/85 V, up to ~184 nA; bottom region gone; right lobe → band at ~115/100–140 V), but the dark valley just right of the hand alignment (~70–90 V H, 80–120 V V, bottom ~39–44 nA) is present in both. Conclusion: most of the bright structure depends on the collection geometry; the valley belongs to the incoupling. Scan-direction offset 15 V (corr 0.95). Comparison plot `compare_fibre_move.png` in that run folder
- [x] TIA range gains checked on hardware (2026-09-15, fixed position, ~44 nA): manual ranges 5/6/7/8 (50 nA … 1.66 µA full scale) give 44.45 / 44.17 / 44.28 / 43.88 nA — ratios 1.006 / 1.000 / 1.003 / 0.994, within noise. Converting relative × nominal full scale is consistent across ranges, so auto-range switches do not step the maps. Range mode read and restored (auto at selected, all ranges)
- [ ] Remaining auto-range effect: readings taken during a switch are unreliable (likely the 422 nA spike and two dark points in run 20260915T111350), and switches add delay. Store the range code per sample and drop/flag readings where the range changed; optionally a fixed manual range during a map (`NT_SetRangeMode` / `NT_SetTIARange`; at range 8, one relative count ≈ 2.5 nA)
- [x] First coupling vs stray-light check (2026-09-15, static holds, 2.5 V ramps): 75/75 V → 9.10 mW coupled, 44.3 nA; 85/95 V (the full-range map's valley bottom) → 8.54 mW (−6 %), 47.8 → 49.4 nA while holding (+8–12 %, creep). Back at 75/75 V: 40.7 nA (hysteresis/creep offset after the round trip). Locally, more stray light goes with less coupling, as hoped; but the scanned map misplaced the valley — static, slower sampling is needed near the optimum
- [x] PM100USB (S/N 1931430) on the lab PC through `ThorlabsPM100` (2026-09-15): model/serial/resource read, 5 readings 13.49–13.51 mW, sensor 400–1100 nm, average time 0.33 ms–10.9 s, auto range on. The meter was set to 635 nm — confirm the laser wavelength
- [x] Static cross with logged coupling (2026-09-15, run `app/data/auto_alignment_cross/2026/09/15/20260915T115115`, PM100 at 1030 nm; ±5/±10 V per axis around 75/75 V, centre repeated between points, 3 s settle, 20 KNA + 20 PM readings per point): coupled power 8.68–9.14 mW, stray light 39.9–48.2 nA. Stray light and power anti-correlate (r = −0.92 over all 17 points; −0.98 on the negative side, −0.67 on the positive side). Drift-corrected quadratic fits: power peaks at H +3.7 V / V +5.0 V, stray light is minimal at H +11.7 V / V +6.5 V — the stray-light minimum lies near but beyond the coupling optimum (~8 V off in H, ~1.5 V in V). Centre drift over 70 s: stray +1.7 nA/min, power −0.08 mW/min. Plot `cross.png`, data `cross.csv` / `summary.json`
- [ ] Decide what tracking should minimise: stray light alone overshoots the coupling optimum in H by several volts; options are a fixed offset, a combined figure (e.g. power/stray) while the power meter is available, or tracking on power directly. Constraint: at full power the fibre is strongly nonlinear and changes the spectrum, so the (wavelength-corrected photodiode) power reading is unreliable there — power can calibrate at low power but cannot drive tracking at full power. Decision (2026-09-15): no low-power calibration/offset scheme for now (judged unreliable); a thermal sensor is available but too slow (~1.1 s response) for tracking
- [x] First tracking run on hardware (2026-09-15, run 20260915T121159, laser ~40 mW, ~39 mW coupled): probe radius 6 V, 8 points, 5 averages, 0.2 s settle, min contrast 1.5 %, gain 0.5, max step 1 V, max excursion 15 V, 180 s; PM100 logged only. Converged in ~40 s from 75/75 V to (73.5 ± 0.13, 68.0 ± 0.16) V and held there for the remaining 140 s; every cycle saw a dip (in-dip fraction 1.00, contrast 2–4 %); centre stray light 178 → 166 nA (−7 %). Coupled power mean unchanged (39.09 / 39.08 / 39.06 / 39.07 mW over successive windows) — no gain, no loss — but the ±6 V probe dither modulates it between ~37.4 and 39.7 mW (±3 %, cycle period ~4.2 s). The tracker moved mainly in −V, opposite to the low-power cross test's stray minimum (+H, +V): the landscape or its minimum may shift with power. Default tracking params (2 V, 5 %) would not step on this valley
- [ ] Tracking dither costs ~3 % coupling peak-to-peak at 6 V probe radius: try a smaller radius with more averaging, or probe only occasionally (hold between probe cycles)
- [ ] Auto-alignment task: optional power meter binding so maps and tracking log coupled power next to the stray light
- [x] Plots saved next to the runs: `map.png` in each run folder, `power_split.png` in 20260915T104822 (scratch matplotlib scripts)
- [x] Driver: position right after a move — the device report lags by a polling period (the ±30 V map "ended" at 105/105 V although it had returned to 75/75 V). `get_position_v` now returns the commanded position for max(1 s, 5 × poll) after a move; the range-switch check still reads the device
- [ ] Record coupling during a map: log the output power meter alongside the KNA signal (needs the power meter bound in the task, or a second simultaneous acquisition), so stray light can be compared with coupling point by point
- [ ] Driver: detect stale data — status with under-read and over-read both set, and identical readings/status over several requests — and raise instead of returning stale values
- [x] Map analysis leaves out-of-range readings unmeasured (the KNA reports them as 0 A, which looked like a perfect dip) and walks downhill from the nearest measured point
- [ ] Optionally set Kinesis' startup option for this KNA to use the device's stored settings instead of pushing its own (`LoadSettingsOption = 2`, "UseFileSettings", today), so opening Kinesis stops resetting the range
- [ ] Units: `absoluteReading` ≈ 0.36 × (relative/32767 × range full scale) on every reading — confirm absolute is in A (e.g. a known photocurrent) or correct the scale. Tracking only needs monotonic signal, but stored values may be off by a constant factor
- [ ] Auto-ranging is on (status bit 0x10): range switches mid-probe add steps and delay; consider a fixed TIA range during map/track
- [ ] Run a **map** around the hand-aligned point and check `profile_shape` — confirms (or refutes) the dip-inside-ring picture before trusting tracking
- [x] Defaults rescaled to the K1S2P response (~17 % signal change per 20 V): map ±10 V × 11 points, probe radius 2 V, max step 0.5 V, max excursion 10 V; readings per point stays 3 (single readings scatter ~2-3 %). Simulated aligner in `lab.sim.yaml` scaled to match (ring radius 8 V)
- [ ] After the first map, tune `probe_radius_v` together with `min_contrast` (dip contrast scales with radius²), then `gain` / `max_step_v`
- [ ] Consider periodic raw checkpoints for very long tracking runs (today a force-stop or crash loses that run's log)

---

## Planned (committed in design, not yet started)

### Core
- [ ] `Camera`, `Spectrometer`, `Stage` Protocols
- [ ] Sim devices for each (`SimCamera`, `SimSpectrometer`, `SimStage`)

### App
- [ ] Retry an unavailable device from the shell (today: fix and restart LabMan)
- [ ] Detachable task windows
- [ ] Status bar, log viewer, error dialog

### Tasks (other three)
- [ ] `beam_profile`
- [ ] `power_spectrum`
- [ ] `spectral_feature_tracking` (dark → reference → acquire → track)

### Cross-cutting
- [ ] Migrate `coupling_efficiency/task.py` to `labman_core.persistence` (helper exists, used by `auto_alignment`)
- [ ] Migrate `CouplingEfficiencyWidget` to `labman_app.widgets.layout` helpers
- [ ] Second measurement task `beam_profile` (needs `Camera` + `Stage` protocols and simulators)
- [ ] Bump `requires-python` back to `>=3.14` once 3.14 is installed locally

---

## Deferred (deliberately skipped, with reason)

- **`pint` / units library** — string units on `ParamMeta`/`Setable` are sufficient for now; SI internally everywhere. Revisit only if a real ambiguity forces it.
- **Splitting into three distributable packages** (`labman-core`, `labman-app`, `labman-tasks`) — single repo is enough at this stage. Logical boundary enforced by code, not packaging. Split when there's a concrete reason (third-party publishing, multi-machine deploys).
- **Instrument profiles** (cross-device preset concept like "1550 nm alignment") — task presets first; instrument profiles later.
- **Mocking devices vs simulators** — committed to simulators only.
- **Type checker (mypy/pyright) wiring** — ruff lint-only for now; revisit after the shell stabilises.

---

## Open questions

- **Cross-task dataset linking** (e.g. "this beam-profile run used the laser settings from coupling-efficiency run X") — likely a `parent_run` field in `meta.json`; not yet designed.
- **Action-induced readable refresh** — currently readables only update on the polling tick. If an action like `calibrate` updates `offset`, you wait up to 200 ms to see it. Acceptable, or do we want immediate refresh after action completion?
- **Auto-alignment signal shape** — the dip-inside-ring picture is unconfirmed; run a map on the real setup first. Far outside the ring the signal tail is also locally convex, so tracking there would step *away*; `max_excursion_v` is the guard for that case.
- **Cross-machine exclusivity** — resource locks live in the local temp dir, so two PCs sharing one LAN/GPIB instrument are not detected. Needs a shared lock location or an instrument-side check if that setup occurs.

---

## How to update this file

- Move items from **Next up** → **Done** as soon as they ship and have tests.
- New ideas land in **Planned**. If they're being rejected, put them in **Deferred** with a one-line reason.
- **Open questions** is for things that block design decisions. Resolved questions disappear (the resolution lives in CLAUDE.md or in code).
- Bump the "Last updated" date when you change anything substantive.
