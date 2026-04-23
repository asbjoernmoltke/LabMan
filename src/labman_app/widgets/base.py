from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class SchemaWidget(QWidget):
    """Base for schema-bound input widgets.

    Subclasses MUST emit `committed(value)` only on commit events
    (Enter, focus-out, slider release, choice selection, button click).
    `set_value()` is the programmatic API and MUST NOT emit `committed`.
    """

    committed = Signal(object)

    def value(self) -> Any:
        raise NotImplementedError

    def set_value(self, v: Any) -> None:
        raise NotImplementedError
