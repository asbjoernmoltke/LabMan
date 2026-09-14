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
- [x] `drivers.KinesisNanoTrak` — Kinesis C API via ctypes; keeps the KNA latched (firmware tracking maximizes and is never enabled); verifies but never changes the 75/150 V range; blocking calls in a worker thread; shutdown latches without zeroing outputs
- [x] `persistence` (core) — dataclass ↔ HDF5 (nested, None, bool/int/str attrs), params/meta JSON; used by `auto_alignment` (coupling efficiency not migrated yet)
- [x] `algorithm.py` (pure) — probe circle, plane fit + curvature, Newton step toward the dip only when the centre is confirmed lower than its ring; holds on ring/flat/out-of-range/degenerate; excursion and voltage limits; serpentine map raster
- [x] `workflow.py` — map mode (returns to start) and continuous track mode (until Stop, duration, or a limit); every sample and cycle logged and published live; `finally` → safe state
- [x] `safety.py` — latch, then move to `hold_at` (best confirmed centre when tracking, start after a map); never zeroes outputs
- [x] `analysis.py` — map grid; nearest dip = downhill walk from the start (the global minimum can be background beyond the ring and is reported separately); `dip_found` false when the walk runs off the map edge; radial profile in one-grid-step rings + advisory `profile_shape`; tracking summary (cycles, in-dip fraction, drift, best)
- [x] `plots.py` / `widget.py` — position plane (live samples coloured by signal, centre trajectory, start/best markers, map heatmap) + signal vs time; Stop = graceful, second Stop = force; `labman_app.widgets.layout` column helpers
- [x] `examples/lab.sim.yaml` gains a simulated aligner; `examples/lab.kna.yaml` template for the real KNA
- [x] Fixes found by the smoke test: `RunStorage` timestamp dirs no longer collide when two runs start within one second; both task widgets create storage inside `try`, so a storage error resets the UI instead of leaving Start disabled

### Tests (247 passing)
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
- [x] Auto-alignment analysis: 10 tests (dip_in_ring / minimum / maximum / flat classification, coarse offset map finds nearest dip not background beyond ring, downhill walk, missing points, track summary)
- [x] Auto-alignment widget: 5 tests (map run, graceful stop saves, second Stop force-cancels, hydrate, storage failure reports error and resets UI)
- [x] Persistence: 4 tests (nested round trip incl. None/bool/empty arrays, unsupported type, params and meta JSON)
- [x] KinesisNanoTrak (fake DLL): 16 tests (connect latches, simulator flag, voltage-range refusal closes device, open error, V ↔ device units, out-of-range move never sent, range flag, garbage reading retried / persistent → NaN out of range / constant scale mismatch and dark readings accepted, latch/identify/idempotent shutdown, controls, example yaml)
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
- [ ] Verify that `NT_SetCircleHomePosition` + `NT_HomeCircle` moves the output while latched (one tiny step and back)
- [ ] Units: `absoluteReading` ≈ 0.36 × (relative/32767 × range full scale) on every reading — confirm absolute is in A (e.g. a known photocurrent) or correct the scale. Tracking only needs monotonic signal, but stored values may be off by a constant factor
- [ ] Auto-ranging is on (status bit 0x10): range switches mid-probe add steps and delay; consider a fixed TIA range during map/track
- [ ] Run a **map** around the hand-aligned point and check `profile_shape` — confirms (or refutes) the dip-inside-ring picture before trusting tracking
- [ ] Tune `probe_radius_v` together with `min_contrast` (dip contrast scales with radius²), then `gain` / `max_step_v`
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
