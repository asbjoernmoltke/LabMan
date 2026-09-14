# LabMan — Implementation Status

Living snapshot of what exists, what's planned, and what's been deliberately
deferred. Update this file whenever the answer to any of those changes.

For *rules and conventions*, see [CLAUDE.md](CLAUDE.md). This document only
tracks state.

Last updated: 2026-09-14 (presets)

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

### Tests (176 passing)
- [x] Storage: 4 tests
- [x] Analysis: 3 tests
- [x] Workflow E2E: 5 tests
- [x] SimPowerMeter: 8 tests (incl. negative reads after calibrate, negative noise samples not clipped, display_precision present)
- [x] Widgets: 12 tests
- [x] Forms: 23 tests (incl. hydrate sync, readable polling, sub-precision suppression, sync policies, setter validation + rollback, field-named errors, last-used seeding)
- [x] Presets: 25 tests (params ↔ dict round trip and type coercion/rejection, store save/load/delete, last-used separation, reserved names, corrupt file set aside)
- [x] Preset bar: 10 tests (round trip, name dialog, overwrite/delete confirmation, reserved name, invalid form, invalid preset leaves form unchanged, unknown fields reported, last-used entry)
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

Second task, `beam_profile` — the first real test of "each new measurement is small to add":

- [ ] `Camera` + `Stage` Protocols and `SimCamera` / `SimStage` (see Planned → Core)
- [ ] `beam_profile` task folder per the standard layout, incl. `safety.py`
- [ ] Lift the generic HDF5 persistence helper out of `coupling_efficiency/task.py` (see Planned → Cross-cutting)

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
- [ ] Generic HDF5 persistence helper in `labman_core` (lift when 2nd task duplicates `coupling_efficiency/task.py`)
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
- **Cross-machine exclusivity** — resource locks live in the local temp dir, so two PCs sharing one LAN/GPIB instrument are not detected. Needs a shared lock location or an instrument-side check if that setup occurs.

---

## How to update this file

- Move items from **Next up** → **Done** as soon as they ship and have tests.
- New ideas land in **Planned**. If they're being rejected, put them in **Deferred** with a one-line reason.
- **Open questions** is for things that block design decisions. Resolved questions disappear (the resolution lives in CLAUDE.md or in code).
- Bump the "Last updated" date when you change anything substantive.
