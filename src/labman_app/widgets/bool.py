from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget

from labman_app.widgets.base import SchemaWidget


class BoolInput(SchemaWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._check = QCheckBox()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._check)
        self._suppress = False
        self._check.toggled.connect(self._on_toggled)

    def value(self) -> bool:
        return self._check.isChecked()

    def set_value(self, v: bool) -> None:
        self._suppress = True
        try:
            self._check.setChecked(bool(v))
        finally:
            self._suppress = False

    def _on_toggled(self, checked: bool) -> None:
        if self._suppress:
            return
        self.committed.emit(bool(checked))
