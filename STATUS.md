# LabMan — Implementation Status

Living snapshot of what exists, what's planned, and what's been deliberately
deferred. Update this file whenever the answer to any of those changes.

For *rules and conventions*, see [CLAUDE.md](CLAUDE.md). This document only
tracks state.

Last updated: 2026-04-22

---

## Done

### `labman_core`
- [x] `roles.DeviceRole` (StrEnum: LASER, POWER_METER, CAMERA, SPECTROMETER, STAGE)
- [x] `schema`: `Range`, `ParamMeta`, `Setable`, `Readable`, `Action`, `DeviceControls`
- [x] `devices`: `Device`, `LaserSource`, `PowerMeter` Protocols + `LaserState`
- [x] `storage`: `StorageOptions` (folder / naming "timestamp"|"iterator" / prefix), `RunStorage` (eager dir creation, raw/result/params/meta paths)
- [x] `context`: `TaskContext`, `ProgressReporter` (subscribable, noop default)
- [x] `task.Task` Protocol
- [x] `simulators.SimLaser`, `simulators.SimPowerMeter` (full `controls()` exposed)

### `labman_tasks.coupling_efficiency`
- [x] `params.CouplingEfficiencyParams` (with `Annotated[T, ParamMeta]` schema)
- [x] `result.CouplingEfficiencyRawData`, `CouplingEfficiencyResult`
- [x] `workflow.acquire()` (async, hardware IO only, try/finally cleanup)
- [x] `analysis.analyze()` (pure function, NaN-safe)
- [x] `task.CouplingEfficiencyTask` (glue + HDF5/JSON persistence)
- [x] Entry-point registered in `pyproject.toml`

### Tests (12 passing)
- [x] Storage path layout: default, prefix, iterator, custom folder
- [x] Analysis: known ratio, correction factor scaling, NaN at zero input
- [x] Workflow E2E: file outputs, raw round-trip, params persistence, progress events, laser cleanup

### Tooling
- [x] `pyproject.toml` (hatchling, numpy, h5py, pytest-asyncio, ruff)
- [x] `.gitignore` (incl. `app/data/`, `app/presets/`, `*.h5`)
- [x] `CLAUDE.md` — architecture and conventions
- [x] `STATUS.md` — this file

---

## Next up (uncommitted, logical next slice)

The renderer + Qt shell, in roughly this order:

- [ ] **Pick PyQt6 vs PySide6 finally** (currently leaning PySide6, not yet code-committed)
- [ ] `labman_app/widgets/numeric_input.py` — composite slider+entry with bounds & unit
- [ ] `labman_app/widgets/enum_input.py`, `bool_input.py`, `text_input.py`
- [ ] `labman_app/forms.build_params_form(cls) -> (QWidget, getter)` — walks `Annotated[T, ParamMeta]`, infers widget from type+bounds
- [ ] `labman_app/forms.build_device_panel(device) -> QWidget` — walks `device.controls()`, renders setables/readables/actions sections
- [ ] `labman_app/shell` — Qt main window, task registry (entry-point discovery), device-binding UI
- [ ] `labman_tasks/coupling_efficiency/widget.py` — first concrete task widget using the above
- [ ] `labman_tasks/coupling_efficiency/plots.py` — efficiency vs setpoint, p_in/p_out overlay
- [ ] `qasync` integration in shell (Start button → `asyncio.create_task(task.run_headless(...))`)

---

## Planned (committed in design, not yet started)

### Core
- [ ] `Camera`, `Spectrometer`, `Stage` Protocols
- [ ] Sim devices for each (`SimCamera`, `SimSpectrometer`, `SimStage`)
- [ ] `lab.yaml` config loader (binds device drivers + addresses + sync policy)
- [ ] Connect-time sync policy (`hydrate` | `push_defaults` | `skip`) implementation
- [ ] Resource manager — enforces single-connection-per-device
- [ ] Readable polling subsystem (per-device poll rate from config)

### App
- [ ] `PresetStore` (per-task JSON; `__last_used__` auto-update; named save/load/delete)
- [ ] Preset bar widget above params form
- [ ] Live plot widget (pyqtgraph) used by tasks during acquire
- [ ] Detachable task windows (so a task feels standalone)
- [ ] Status bar, log viewer, error dialog

### Tasks (other three)
- [ ] `beam_profile` — camera images over laser settings + z-positions → fitted parameters
- [ ] `power_spectrum` — laser power ramp → spectra per setpoint
- [ ] `spectral_feature_tracking` — dark → reference → acquire → track feature

### Cross-cutting
- [ ] Generic HDF5 persistence helper in `labman_core` (lift from `coupling_efficiency/task.py` when 2nd task duplicates it)
- [ ] Cancellation test (cancel mid-`acquire`, assert laser still cleaned up)
- [ ] Bump `requires-python` back to `>=3.14` once 3.14 is installed locally

---

## Deferred (deliberately skipped, with reason)

- **`pint` / units library** — string units on `ParamMeta`/`Setable` are sufficient for now; SI internally everywhere. Revisit only if a real ambiguity forces it.
- **Splitting into three distributable packages** (`labman-core`, `labman-app`, `labman-tasks`) — single repo with `src/labman_core/` and `src/labman_tasks/` is enough at this stage. Logical boundary (no Qt in core) enforced by code, not packaging. Split when there's a concrete reason (third-party publishing, multi-machine deploys).
- **Instrument profiles** (cross-device preset concept like "1550 nm alignment") — task presets first; instrument profiles can come later once the basic mechanism is proven.
- **Mocking devices vs simulators** — committed to simulators only. No mocks in tests.
- **Type checker (mypy/pyright) wiring** — ruff lint-only for now; revisit after Qt code lands and the surface stabilises.

---

## Open questions

- **PyQt6 vs PySide6** — leaning PySide6 (LGPL, Qt Company official). Final commit happens at first `from PySide6.x import y` line.
- **Live device-panel updates when *we* change state** (e.g. an action button updates a related readable) — re-poll the affected readable, or expose a `changed` notify hook on `Setable`/`Action`? Decide when the first device panel ships.
- **What `ShellServices` looks like** (the object passed to `Task.build_widget`) — needs at minimum: `device(binding_name)`, access to `PresetStore`, `RunStorage` factory. Shape will firm up while building the shell.
- **Cross-task dataset linking** (e.g. "this beam-profile run used the laser settings from coupling-efficiency run X") — likely just a `parent_run` field in `meta.json`; not yet designed.

---

## How to update this file

- Move items from **Next up** → **Done** as soon as they ship and have tests.
- New ideas land in **Planned**. If they're being rejected, put them in **Deferred** with a one-line reason.
- **Open questions** is for things that block design decisions. Resolved questions disappear (the resolution lives in CLAUDE.md or in code).
- Bump the "Last updated" date when you change anything substantive.
