from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from labman_app.widgets.base import SchemaWidget


class TextInput(SchemaWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line = QLineEdit()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._line)
        self._line.editingFinished.connect(self._on_committed)

    def value(self) -> str:
        return self._line.text()

    def set_value(self, v: str) -> None:
        self._line.setText(str(v))

    def _on_committed(self) -> None:
        self.committed.emit(self._line.text())
