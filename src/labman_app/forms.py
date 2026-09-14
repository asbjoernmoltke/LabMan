import asyncio
import dataclasses
import enum
import logging
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from labman_app.presets import PresetStore, params_from_dict
from labman_app.widgets.base import SchemaWidget
from labman_app.widgets.bool import BoolInput
from labman_app.widgets.choice import ChoiceInput
from labman_app.widgets.numeric import NumericInput
from labman_app.widgets.optional import OptionalWrapper
from labman_app.widgets.preset_bar import PresetBar
from labman_app.widgets.text import TextInput
from labman_core.lab_config import DeviceSync
from labman_core.schema import Action, ParamMeta, Range, Readable, Setable

logger = logging.getLogger("labman.forms")


@dataclass
class DevicePanel:
    """Result of `build_device_panel`. The panel widget plus per-control handles.

    `setable_widgets` and `readable_labels` keep references so initial sync and
    polling helpers can find the widgets/labels they need to update without
    walking the Qt tree.
    """

    widget: QWidget
    setable_widgets: dict[str, SchemaWidget] = field(default_factory=dict)
    readable_labels: dict[str, QLabel] = field(default_factory=dict)
    readables: dict[str, Readable] = field(default_factory=dict)


def build_params_form(
    cls: type, initial: Any | None = None
) -> tuple[QWidget, Callable[[], Any]]:
    """Build a form widget from a dataclass with `Annotated[T, ParamMeta]` fields.

    Returns `(container, getter)` where `getter()` reads current widget values
    and constructs a validated instance of `cls`. It raises ValueError naming
    the field for empty or out-of-bounds values.
    """
    container, getter, _setter = _build_form(cls, initial)
    return container, getter


def build_params_form_with_presets(
    cls: type, store: PresetStore, initial: Any | None = None
) -> tuple[QWidget, Callable[[], Any]]:
    """`build_params_form` with a preset bar above it (Presets in CLAUDE.md).

    Unless `initial` is given, the form starts from the task's last-used values
    if they still validate, otherwise from the dataclass defaults. Presets are
    applied through the same validation as manual entry.
    """
    form, getter, setter = _build_form(cls, initial)
    if initial is None:
        last_used = store.load_last_used()
        if last_used is not None:
            try:
                setter(last_used)
            except ValueError as e:
                logger.warning("ignoring last-used params for %r: %s", store.task_name, e)

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(PresetBar(store, getter, setter))
    layout.addWidget(form)
    return container, getter


def _build_form(
    cls: type, initial: Any | None
) -> tuple[QWidget, Callable[[], Any], Callable[[dict[str, Any]], list[str]]]:
    """Shared form builder returning `(container, getter, setter)`."""
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls.__name__} is not a dataclass")

    container = QWidget()
    outer = QVBoxLayout(container)
    outer.setContentsMargins(8, 8, 8, 8)

    type_hints = get_type_hints(cls, include_extras=True)
    initial_obj = initial if initial is not None else cls()

    grouped: dict[str, list[tuple[str, Any, ParamMeta]]] = {}
    for f in dataclasses.fields(cls):
        ann = type_hints.get(f.name, f.type)
        meta = _extract_meta(ann)
        inner = _strip_annotated(ann)
        grouped.setdefault(meta.group, []).append((f.name, inner, meta))

    field_widgets: dict[str, SchemaWidget] = {}
    metas: dict[str, ParamMeta] = {}

    for group_name, entries in grouped.items():
        box = QGroupBox(group_name) if group_name else QGroupBox()
        if not group_name:
            box.setFlat(True)
        form = QFormLayout(box)
        for name, type_, meta in entries:
            widget = _make_widget(type_, meta)
            widget.set_value(getattr(initial_obj, name))
            if meta.tooltip:
                widget.setToolTip(meta.tooltip)
            form.addRow(_label_with_unit(meta.display or name, meta.unit), widget)
            field_widgets[name] = widget
            metas[name] = meta
        outer.addWidget(box)

    def getter() -> Any:
        kwargs: dict[str, Any] = {}
        for name, widget in field_widgets.items():
            label = metas[name].display or name
            try:
                value = widget.value()
            except ValueError as e:
                raise ValueError(f"{label}: {e}") from e
            _check_bounds(label, metas[name].bounds, value)
            kwargs[name] = value
        return cls(**kwargs)

    def setter(data: dict[str, Any]) -> list[str]:
        """Apply field values (e.g. a preset) and validate them like manual entry.

        Missing fields take dataclass defaults; unknown keys are returned, not
        applied. On any invalid value the form is restored and ValueError raised.
        """
        values, unknown = params_from_dict(cls, data)
        previous: dict[str, Any] = {}
        for name, widget in field_widgets.items():
            try:
                previous[name] = widget.value()
            except ValueError:
                pass
        try:
            for name, value in values.items():
                field_widgets[name].set_value(value)
            getter()
        except (ValueError, TypeError) as e:
            for name, value in previous.items():
                field_widgets[name].set_value(value)
            raise ValueError(str(e)) from e
        return unknown

    return container, getter, setter


def _check_bounds(label: str, bounds: Range | None, value: Any) -> None:
    if bounds is None or isinstance(value, bool) or not isinstance(value, int | float):
        return
    if not bounds.contains(value):
        raise ValueError(f"{label}: {value:g} outside [{bounds.low:g}, {bounds.high:g}]")


def build_device_panel(device: Any) -> DevicePanel:
    """Build a panel from `device.controls()`: Settings / Readouts / Actions sections.

    Returns a `DevicePanel` with the QWidget plus references to the inner
    setable widgets and readable labels. Setable commits are scheduled on the
    running asyncio loop; if no loop is running the commit is dropped silently.
    """
    controls = device.controls()
    container = QWidget()
    outer = QVBoxLayout(container)
    outer.setContentsMargins(8, 8, 8, 8)

    panel = DevicePanel(widget=container)

    if controls.setables:
        outer.addWidget(_build_setables(controls.setables, panel))
    if controls.readables:
        outer.addWidget(_build_readables(controls.readables, panel))
    if controls.actions:
        outer.addWidget(_build_actions(controls.actions))

    return panel


async def sync_panel_from_device(panel: DevicePanel, device: Any) -> None:
    """One-shot read of every setable's current state into the widget.

    Implements the `hydrate` connect-time sync policy. Per CLAUDE.md, the
    widget is the source of truth for setables AFTER this call returns.
    Errors during read are logged via the device-context-free path: skipped.
    """
    for s in device.controls().setables:
        widget = panel.setable_widgets.get(s.name)
        if widget is None:
            continue
        try:
            value = await s.get()
        except Exception:
            continue
        widget.set_value(value)


async def apply_sync_policy(panel: DevicePanel, device: Any, sync: DeviceSync) -> None:
    """Connect-time sync of a device panel (Hardware exclusivity in CLAUDE.md).

    - hydrate:       read every setable into its widget.
    - push_defaults: write `sync.defaults` to the device in declaration order,
                     then hydrate so every widget reflects the hardware.
    - skip:          nothing; widgets keep their initial values.

    A failed default write raises: the device is in a partially configured
    state and the caller must surface that rather than carry on.
    """
    if sync.policy == "skip":
        return
    if sync.policy == "push_defaults":
        setables = {s.name: s for s in device.controls().setables}
        for name, value in sync.defaults.items():
            setable = setables.get(name)
            if setable is None:
                raise ValueError(
                    f"{device.name}: default for unknown setable {name!r}; "
                    f"available: {sorted(setables)}"
                )
            await setable.set(value)
    await sync_panel_from_device(panel, device)


async def poll_readables(panel: DevicePanel, interval_s: float = 0.2) -> None:
    """Background task: poll every readable on `panel` and update its label.

    Runs until cancelled. Spawn one of these per panel after construction:

        task = asyncio.create_task(poll_readables(panel))
        ...
        task.cancel()
    """
    while True:
        for name, readable in panel.readables.items():
            label = panel.readable_labels.get(name)
            if label is None:
                continue
            try:
                value = await readable.get()
            except Exception:
                continue
            label.setText(_format_readable_value(value, readable))
        await asyncio.sleep(interval_s)


def _build_setables(setables: list[Setable], panel: DevicePanel) -> QGroupBox:
    box = QGroupBox("Settings")
    form = QFormLayout(box)
    for s in setables:
        widget = _widget_for_setable(s)
        widget.committed.connect(lambda value, sx=s: _schedule(sx.set(value)))
        form.addRow(_label_with_unit(s.display, s.unit), widget)
        panel.setable_widgets[s.name] = widget
    return box


def _build_readables(readables: list[Readable], panel: DevicePanel) -> QGroupBox:
    box = QGroupBox("Readouts")
    form = QFormLayout(box)
    for r in readables:
        label = QLabel("—")
        form.addRow(_label_with_unit(r.display, r.unit), label)
        panel.readable_labels[r.name] = label
        panel.readables[r.name] = r
    return box


def _build_actions(actions: list[Action]) -> QGroupBox:
    box = QGroupBox("Actions")
    layout = QVBoxLayout(box)
    for a in actions:
        btn = QPushButton(a.display)
        btn.clicked.connect(lambda _checked=False, ax=a: _schedule(ax.call()))
        layout.addWidget(btn)
    return box


def _widget_for_setable(s: Setable) -> SchemaWidget:
    if s.choices is not None:
        return ChoiceInput(s.choices)
    if s.kind is bool:
        return BoolInput()
    if s.kind is int:
        return NumericInput(bounds=s.bounds, integer=True)
    if s.kind is float:
        return NumericInput(bounds=s.bounds, integer=False)
    if s.kind is str:
        return TextInput()
    raise TypeError(f"No widget mapping for setable {s.name!r} kind={s.kind}")


def _make_widget(t: Any, meta: ParamMeta) -> SchemaWidget:
    if _is_optional(t):
        inner_type = _strip_optional(t)
        inner = _make_concrete_widget(inner_type, meta)
        return OptionalWrapper(inner)
    return _make_concrete_widget(t, meta)


def _make_concrete_widget(t: Any, meta: ParamMeta) -> SchemaWidget:
    if get_origin(t) is typing.Literal:
        return ChoiceInput(list(get_args(t)))
    if isinstance(t, type) and issubclass(t, enum.Enum):
        return ChoiceInput(list(t))
    if t is bool:
        return BoolInput()
    if t is int:
        return NumericInput(bounds=meta.bounds, integer=True)
    if t is float:
        return NumericInput(bounds=meta.bounds, integer=False)
    if t is str:
        return TextInput()
    raise TypeError(f"No widget mapping for type {t!r}")


def _label_with_unit(display: str, unit: str) -> str:
    return f"{display} [{unit}]" if unit else display


def _format_readable_value(value: Any, readable: Readable) -> str:
    if isinstance(value, float):
        if readable.display_precision is not None and abs(value) < readable.display_precision:
            return "0"
        return f"{value:.4g}"
    return str(value)


def _extract_meta(annotation: Any) -> ParamMeta:
    if get_origin(annotation) is Annotated or hasattr(annotation, "__metadata__"):
        for arg in getattr(annotation, "__metadata__", ()):
            if isinstance(arg, ParamMeta):
                return arg
    return ParamMeta(display="")


def _strip_annotated(annotation: Any) -> Any:
    if get_origin(annotation) is Annotated or hasattr(annotation, "__metadata__"):
        return get_args(annotation)[0]
    return annotation


def _is_optional(t: Any) -> bool:
    if get_origin(t) in (typing.Union, types.UnionType):
        return type(None) in get_args(t)
    return False


def _strip_optional(t: Any) -> Any:
    args = [a for a in get_args(t) if a is not type(None)]
    if len(args) == 1:
        return args[0]
    return t


def _schedule(coro: Any) -> None:
    """Submit a coroutine to the running asyncio loop, or drop silently if none."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    loop.create_task(coro)
