# LabMan — Architecture & Conventions

This file is the source of truth for **design decisions**. Read it before making
structural changes. Rationale is deliberately brief; see commit history / PR
discussions for fuller context.

For **what's currently built, planned, or deferred**, see [STATUS.md](STATUS.md).
Update STATUS.md whenever you finish, defer, or plan an item.

## Purpose

LabMan unifies hardware control, measurement acquisition, and analysis for
recurring optics-lab tasks (coupling efficiency, beam profiling, power–spectrum
sweeps, spectral feature tracking). Tasks share a hardware abstraction layer and
a typed data model so each new measurement is small to add.

## Top-level shape

One Qt application with pluggable task modules — **not** N standalone GUIs.
Tasks can be detached into their own windows at runtime for a standalone feel.
Separate executables are reserved for deployment-level splits (different
machines, incompatible vendor SDK runtimes, safety isolation).

## Packages

| Package         | Contents                                                                 | Imports Qt? |
|-----------------|--------------------------------------------------------------------------|-------------|
| `labman-core`   | Device protocols, roles, `TaskContext`, `RunStorage`, schema primitives, simulators | **No**      |
| `labman-app`    | Qt shell, task registry, form/panel renderers, common widgets, `PresetStore` | Yes         |
| `labman-tasks`  | One subpackage per task, discovered via Python entry points              | Only in `widget.py` |

Task discovery is via `[project.entry-points."labman.tasks"]` in each task
package's `pyproject.toml`. The shell does not know about any specific task.

## Task folder layout

```
labman_tasks/<task_name>/
├── __init__.py       # exports Task class
├── task.py           # Task protocol implementation; glue only, no logic
├── params.py         # Params dataclass with Annotated[T, ParamMeta] fields
├── result.py         # RawData and Result dataclasses
├── workflow.py       # async acquire(ctx, params) -> RawData; hardware IO only
├── analysis.py       # analyze(raw, params) -> Result; pure function
├── widget.py         # Qt widget; imports allowed here and nowhere else in task
├── plots.py          # Plot functions usable from widget AND notebooks
├── resources/        # Optional static assets (calibration files, references)
└── tests/
    ├── test_workflow.py   # runs against simulator devices
    └── test_analysis.py   # runs against canned RawData
```

## Invariants (do not violate without discussion)

1. **Workflow is the only place hardware is touched.** `analysis.py`,
   `plots.py`, and `result.py` never import device protocols or call devices.
2. **Analysis is a pure function.** `analyze(raw, params) -> Result` — no I/O,
   no globals, no Qt. Must be re-runnable on saved raw data.
3. **Persist raw before analysis runs.** If analysis crashes, the experiment is
   not lost.
4. **`labman-core` imports no Qt.** Ever. If you're tempted, the abstraction
   belongs in `labman-app`.
5. **Task logic runs headless.** `task.run_headless(ctx, params)` works with no
   GUI. The widget is a driver for `run_headless`, not a parallel implementation.
6. **Internal units are SI** (W, m, s, Hz, K). Display units live only in
   `ParamMeta`/`Setable`. No `pint` yet — plain floats.
7. **Plots take a `Result` (or `RawData`) and return a figure/widget.** Do not
   call devices from plot code.

## Storage

HDF5 per run. Default path:

```
app/data/<task_name>/<YYYY>/<MM>/<DD>/<timestamp>/
  ├── raw.h5
  ├── result.h5
  ├── params.json
  └── meta.json       # git hash, device serials, software versions, timestamps
```

Overrides via `StorageOptions(folder, naming, prefix)`:

- `folder: Path | None` — replaces `app/data/<task_name>/` when set.
- `naming: "timestamp" | "iterator"` — `iterator` uses `000`, `001`, … inside
  the folder instead of `YYYY/MM/DD/timestamp`.
- `prefix: str` — prepended to the leaf directory name; default `""`.

`RunStorage` is the only writer. Tasks never construct paths themselves.

## Device roles & binding

```python
class DeviceRole(str, Enum):
    LASER, POWER_METER, CAMERA, SPECTROMETER, STAGE = ...
```

Tasks declare **binding-name → role**, not a flat set:

```python
required_bindings = {
    "laser":           DeviceRole.LASER,
    "power_meter_in":  DeviceRole.POWER_METER,
    "power_meter_out": DeviceRole.POWER_METER,
}
```

The shell resolves each binding against connected devices of that role (user
picks per binding from a dropdown). Tasks access devices via
`ctx.devices["power_meter_in"]`.

## Schema pattern — params & device controls

### Task params

Schema lives **on** the dataclass via `Annotated`:

```python
@dataclass
class CouplingEfficiencyParams:
    power_start: Annotated[float, ParamMeta(display="Start", unit="mW",
                                            bounds=Range(0, 40))] = 0.0
    power_steps: Annotated[int,   ParamMeta(display="# points",
                                            bounds=Range(2, 1000))] = 20
```

- **`ParamMeta` is presentation only** (display, unit, tooltip, group, optional
  widget override). Data contract (type, bounds via `Range(low, high, step)`,
  `optional`) lives in the type system.
- **Widget is inferred** from type+bounds:
  - `float + bounds`  → slider + numeric entry (composite)
  - `float`           → numeric entry
  - `int + bounds`    → spin box / slider
  - `bool`            → checkbox
  - `Enum` / `Literal`→ dropdown
  - `Path`            → file picker
  - Explicit `widget=...` in `ParamMeta` is an escape hatch, rarely needed.

### Device controls

Each concrete driver exposes:

```python
def controls(self) -> DeviceControls: ...

@dataclass
class DeviceControls:
    setables:  list[Setable]    # user-writable state (wavelength, range, ...)
    readables: list[Readable]   # telemetry (temperature, live power, ...)
    actions:   list[Action]     # buttons (calibrate, home, ...)
```

Settables and readables are **per-concrete-driver, not per-role**. Tasks use
role protocols (`read_power_w`); panels introspect drivers for the full capability
set. A Thorlabs panel and an Ophir panel can look different; the coupling-
efficiency task does not care.

## Renderer contracts

```python
build_params_form(cls, initial=None) -> (QWidget, Callable[[], Params])
build_device_panel(device)           -> QWidget
```

- Return widgets; do not mutate a shared view.
- The second return value of `build_params_form` reads current form state as a
  validated dataclass instance.
- Composite widgets (slider+entry, numeric-with-unit, enum-as-radio) live in
  `labman-app/widgets/` and are chosen by the renderer. The schema never names a
  widget composition.

## Hardware exclusivity & setable binding

Assumption: each device permits exactly one software connection. While LabMan
holds the connection, no external agent can change device state. Therefore:

- **Widget is the source of truth for setables** after connect.
- **No polling of setables.** Readables are polled on a configured interval.
- **Connect-time sync policy** per device (from `lab.yaml`):
  - `hydrate` — read current hardware state into widget (default for stateful
    instruments like lasers).
  - `push_defaults` — write defaults to hardware.
  - `skip` — widget starts blank; no initial read/write.

### Commit semantics

Setables commit on:

- Enter key in a text/number entry
- Focus-out (Tab / click elsewhere)
- Slider release (drag updates label only, does not hit hardware)
- Dropdown / checkbox change (commit immediately)
- Action button click

On commit: validate → `await setable.set(value)`. On exception, revert widget
to last-known-good and surface error. No "Apply" button, no dirty-state tracking.

## Presets

- Task-scope only for now. Instrument-wide profiles are deferred.
- Stored as one JSON per task at `app/presets/<task_name>.json`.
- Reserved key `__last_used__` is auto-updated on every successful run.
- User-named presets saved/loaded through the same validation path as manual entry.
- `PresetStore` lives in `labman-app` and is wired by the shell into the
  params-form widget; tasks do not touch it directly.

## Async

- Workflows are `async def`. Shell uses `asyncio` with `qasync` to drive the Qt
  event loop.
- Blocking vendor SDK calls go through `asyncio.to_thread(...)`.
- Cancellation propagates naturally via `asyncio.CancelledError` at `await`
  points. Stop button calls `.cancel()` on the workflow task.
- `ctx.progress.report(fraction, message)` for progress updates.

## Testing

- Simulator devices in `labman-core/simulators/` implement all protocols and
  produce physically reasonable synthetic data. They are first-class, not a
  debug afterthought.
- Workflow tests run the full `acquire()` against simulators and assert the
  shape and sanity of `RawData`.
- Analysis tests use canned `RawData` arrays (no simulators needed).
- Every task must have both. Before shipping a task, `run_headless` must work
  end-to-end against simulators with real HDF5 output.

## Key types (reference)

Defined in `labman-core`:

- `DeviceRole` — enum of roles
- `Range(low, high, step)` — numeric bounds for schema fields
- `ParamMeta(display, unit, bounds, optional, tooltip, group, widget)` — UI
  metadata annotation
- `Setable`, `Readable`, `Action`, `DeviceControls` — device introspection
- `StorageOptions(folder, naming, prefix)` — per-run path overrides
- `RunStorage` — owns a run directory; produces raw/result/params/meta paths
- `TaskContext(devices, storage, progress, logger)` — what tasks receive at run time
- `Task` protocol — `name`, `display_name`, `required_bindings`, `params_cls`,
  `build_widget(shell)`, `run_headless(ctx, params)`

## Open / not yet decided

- **Python version and Qt binding** (PyQt6 vs PySide6) — pending user input.
- **Simulator device implementations** — designed, not yet written.
- **Instrument profiles** (cross-device preset concept) — deferred.
- **`pint` / units library** — deliberately not adopted; revisit only if
  string-unit approach fails.

## When modifying LabMan

- If you're about to add a parallel declaration (e.g. a dict that mirrors a
  dataclass), stop — extend the annotation instead.
- If you're about to poll a setable, stop — re-read the hardware-exclusivity
  assumption.
- If analysis needs a device, your workflow is under-specified — the acquire
  step should have captured what analysis needs into `RawData`.
- If a task's widget is re-implementing a form or a device panel, use the
  renderer in `labman-app`.
- New common widgets belong in `labman-app/widgets/`, not in a task.
