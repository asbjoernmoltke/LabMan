from collections.abc import Iterable
from typing import Any

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from labman_app.widgets.base import SchemaWidget


class ChoiceInput(SchemaWidget):
    def __init__(self, choices: Iterable[Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._choices = list(choices)
        self._combo = QComboBox()
        for c in self._choices:
            self._combo.addItem(str(c), c)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._combo)
        self._suppress = False
        self._combo.currentIndexChanged.connect(self._on_changed)

    def value(self) -> Any:
        return self._combo.currentData()

    def set_value(self, v: Any) -> None:
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == v:
                self._suppress = True
                try:
                    self._combo.setCurrentIndex(i)
                finally:
                    self._suppress = False
                return
        raise ValueError(f"value {v!r} not in choices {self._choices}")

    def _on_changed(self, _index: int) -> None:
        if self._suppress:
            return
        self.committed.emit(self.value())
