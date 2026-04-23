from typing import Any

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget

from labman_app.widgets.base import SchemaWidget


class OptionalWrapper(SchemaWidget):
    """Wraps an inner SchemaWidget with an enable checkbox.

    Unchecked => value() returns None and the inner widget is disabled.
    Checked => value() delegates to the inner widget.
    """

    def __init__(self, inner: SchemaWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inner = inner
        self._check = QCheckBox()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._check, 0)
        layout.addWidget(self._inner, 1)
        self._inner.setEnabled(False)
        self._suppress = False
        self._check.toggled.connect(self._on_toggled)
        self._inner.committed.connect(self._on_inner_committed)

    def value(self) -> Any:
        return self._inner.value() if self._check.isChecked() else None

    def set_value(self, v: Any) -> None:
        self._suppress = True
        try:
            if v is None:
                self._check.setChecked(False)
                self._inner.setEnabled(False)
            else:
                self._check.setChecked(True)
                self._inner.setEnabled(True)
                self._inner.set_value(v)
        finally:
            self._suppress = False

    def _on_toggled(self, checked: bool) -> None:
        self._inner.setEnabled(checked)
        if self._suppress:
            return
        self.committed.emit(self.value())

    def _on_inner_committed(self, _value: Any) -> None:
        if self._check.isChecked():
            self.committed.emit(self.value())
