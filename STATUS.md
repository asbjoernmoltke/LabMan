# LabMan — Implementation Status

Living snapshot of what exists, what's planned, and what's been deliberately
deferred. Update this file whenever the answer to any of those changes.

For *rules and conventions*, see [CLAUDE.md](CLAUDE.md). This document only
tracks state.

Last updated: 2026-09-14 (lab config + device registry)

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
- [x] `lab_config.LabConfig` / `DeviceConfig` — `lab.yaml` v1 loader (driver dotted path, role, args, sync_policy), validated with clear errors
- [x] `registry.DeviceRegistry` — imports + instantiates drivers from `LabConfig` (passes config `name` only if the constructor accepts it), lookup by name/role/sync policy, best-effort `shutdown_all`
- [x] `schema.Readable.display_precision` — values below this render as "0" in panels
- [x] `simulators.SimLaser`, `simulators.SimPowerMeter`
  - SimPowerMeter: choices/int/calibrate action, **negative reads allowed** (no clipping); power/offset readables carry `display_precision=1e-9`

### `labman_app`
- [x] **Committed to PySide6** (6.11).
- [x] `widgets.SchemaWidget` base — `committed(value)` signal contract, `value()/set_value()` API
- [x] `widgets.NumericInput` — slider+entry composite when bounds present
- [x] `widgets.ChoiceInput`, `BoolInput`, `TextInput`, `OptionalWrapper`
- [x] `forms.build_params_form(cls)` — `(QWidget, getter)` from `Annotated[T, ParamMeta]` dataclasses
- [x] `forms.build_device_panel(device)` — returns `DevicePanel(widget, setable_widgets, readable_labels, readables)`; three sections (Settings/Readouts/Actions); async commits via running loop
- [x] `forms.sync_panel_from_device(panel, device)` — one-shot hydrate of setables from device state
- [x] `forms.poll_readables(panel, interval_s)` — background task updates readable labels at configured rate (5 Hz default)

### `labman_tasks.coupling_efficiency`
- [x] `params.CouplingEfficiencyParams` (`Annotated[T, ParamMeta]` schema)
- [x] `result.CouplingEfficiencyRawData`, `CouplingEfficiencyResult`
- [x] `safety.py` — load-bearing safe-state for the task (laser power=0, disabled). Idempotent, non-raising.
- [x] `workflow.acquire()` (async, hardware IO only, finally → `safety.to_safe_state`, publishes `point` events, **honors `abort_below`** by raising `AbortConditionMet`)
- [x] `analysis.analyze()` (pure function, NaN-safe)
- [x] `task.CouplingEfficiencyTask` — glue + HDF5/JSON/meta persistence; `to_safe_state` delegates to `safety.py`; `run_headless` finally calls it as defense-in-depth
- [x] `plots.py` — pyqtgraph two-plot stack
- [x] `widget.CouplingEfficiencyWidget` — three-column layout, Start/Stop/progress, async run lifecycle, live plot updates, hydrate + poll on `initialize()`, **friendly status for `AbortConditionMet`**, live buffers initialised in `__init__` (not just on Start)
- [x] Entry-point registered in `pyproject.toml`

### Tests (73 passing)
- [x] Storage: 4 tests
- [x] Analysis: 3 tests
- [x] Workflow E2E: 5 tests
- [x] SimPowerMeter: 8 tests (incl. negative reads after calibrate, negative noise samples not clipped, display_precision present)
- [x] Widgets: 12 tests
- [x] Forms: 13 tests (incl. hydrate sync, readable polling, sub-precision suppression)
- [x] Coupling-efficiency widget: 5 tests
- [x] Coupling-efficiency safety: 8 tests (idempotency, missing laser, abort raises + cleans up, abort doesn't trigger when efficiency above threshold, safety on normal completion, safety on unhandled workflow error)
- [x] Lab config: 6 tests (round trip, full config, bad version/role/sync_policy, missing driver)
- [x] Device registry: 9 tests (instantiation w/ and w/o `name` kwarg, idempotency, role/policy lookup, bad args surface, bad driver paths, shutdown continues past failures)

### Tooling / Examples
- [x] `pyproject.toml` (hatchling, numpy, h5py, pytest-asyncio, ruff, `[app]` extra: PySide6 / qasync / pyqtgraph)
- [x] `.gitignore`, `CLAUDE.md`, `STATUS.md`
- [x] `tests/conftest.py` — session-scoped `qapp` fixture
- [x] `examples/coupling_efficiency_demo.py` — full task widget against simulators + qasync loop. `DemoShell` is a stub `ShellServices`; the real shell will replace it.

---

## Next up (uncommitted, logical next slice)

The Qt shell — host application that discovers tasks, binds devices to roles, and launches task widgets:

- [ ] `labman_app/shell.py` — main window with task picker (sidebar/tab) and active task widget area
- [ ] Task discovery via Python entry points (`importlib.metadata.entry_points(group="labman.tasks")`)
- [ ] Example `lab.yaml` wired to simulators (loader and registry are done — see Done)
- [ ] Real `ShellServices` implementation backed by the device registry
- [ ] Device-binding UI — for each task's `required_bindings`, dropdown to pick from available devices of the matching role; remembered per task
- [ ] Connect-time sync policy implementation (`hydrate` | `push_defaults` | `skip`)
- [ ] Resource manager — enforces single-connection-per-device when shell starts
- [ ] Splash/error reporting for failed device connects

---

## Planned (committed in design, not yet started)

### Core
- [ ] `Camera`, `Spectrometer`, `Stage` Protocols
- [ ] Sim devices for each (`SimCamera`, `SimSpectrometer`, `SimStage`)

### App
- [ ] `PresetStore` (per-task JSON; `__last_used__` auto-update; named save/load/delete)
- [ ] Preset bar widget above params form
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
- **App-close safety** — `Task.to_safe_state` is called on workflow exit and on widget Stop; needs wiring on Qt `closeEvent` (shell territory). For SIGKILL/power-loss, hardware fail-safes are out of scope.

---

## How to update this file

- Move items from **Next up** → **Done** as soon as they ship and have tests.
- New ideas land in **Planned**. If they're being rejected, put them in **Deferred** with a one-line reason.
- **Open questions** is for things that block design decisions. Resolved questions disappear (the resolution lives in CLAUDE.md or in code).
- Bump the "Last updated" date when you change anything substantive.
