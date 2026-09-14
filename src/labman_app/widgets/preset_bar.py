"""Preset bar: load / save / delete named parameter presets for one task."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from labman_app.presets import LAST_USED, PresetStore

LAST_USED_LABEL = "(last used)"


class PresetBar(QWidget):
    """Sits above a params form.

    `apply_values` is the form's setter: it validates exactly like manual
    entry and leaves the form unchanged on failure, so a stale or hand-edited
    preset can never put invalid values in the form.
    """

    def __init__(
        self,
        store: PresetStore,
        get_params: Callable[[], Any],
        apply_values: Callable[[dict[str, Any]], list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._get_params = get_params
        self._apply_values = apply_values

        self._combo = QComboBox()
        self._combo.setMinimumContentsLength(16)
        self._load_btn = QPushButton("Load")
        self._save_btn = QPushButton("Save as…")
        self._delete_btn = QPushButton("Delete")
        self._message = QLabel()
        self._message.setWordWrap(True)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Preset:"))
        row.addWidget(self._combo, 1)
        row.addWidget(self._load_btn)
        row.addWidget(self._save_btn)
        row.addWidget(self._delete_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 0, 8, 0)
        outer.addLayout(row)
        outer.addWidget(self._message)

        self._load_btn.clicked.connect(lambda: self.load_selected())
        self._save_btn.clicked.connect(lambda: self.save_as())
        self._delete_btn.clicked.connect(lambda: self.delete_selected())
        self._combo.currentIndexChanged.connect(lambda _i: self._update_buttons())
        self.refresh()

    @property
    def message(self) -> str:
        return self._message.text()

    def refresh(self, select: str | None = None) -> None:
        """Reload preset names from the store, keeping (or setting) the selection."""
        current = select if select is not None else self._combo.currentData()
        self._combo.blockSignals(True)
        self._combo.clear()
        if self._store.has_last_used():
            self._combo.addItem(LAST_USED_LABEL, LAST_USED)
        for name in self._store.names():
            self._combo.addItem(name, name)
        index = self._combo.findData(current) if current is not None else -1
        if index < 0:
            index = 0 if self._combo.count() else -1
        self._combo.setCurrentIndex(index)
        self._combo.blockSignals(False)
        self._update_buttons()

    def load_selected(self) -> bool:
        key = self._combo.currentData()
        if key is None:
            return False
        label = self._combo.currentText()
        try:
            unknown = self._apply_values(self._store.load(key))
        except (KeyError, ValueError) as e:
            self._show(f"Could not load {label}: {e}", error=True)
            return False
        note = f" Ignored unknown fields: {', '.join(unknown)}." if unknown else ""
        self._show(f"Loaded {label}.{note}")
        return True

    def save_as(self, name: str | None = None) -> bool:
        if name is None:
            name = self._ask_name()
            if name is None:
                return False
        name = name.strip()
        try:
            params = self._get_params()
        except (ValueError, TypeError) as e:
            self._show(f"Cannot save: {e}", error=True)
            return False
        if name in self._store.names() and not self._confirm(f"Overwrite preset '{name}'?"):
            return False
        try:
            self._store.save(name, params)
        except (ValueError, OSError) as e:
            self._show(f"Cannot save: {e}", error=True)
            return False
        self.refresh(select=name)
        self._show(f"Saved '{name}'.")
        return True

    def delete_selected(self) -> bool:
        key = self._combo.currentData()
        if key is None or key == LAST_USED:
            return False
        if not self._confirm(f"Delete preset '{key}'?"):
            return False
        try:
            self._store.delete(key)
        except OSError as e:
            self._show(f"Cannot delete: {e}", error=True)
            return False
        self.refresh()
        self._show(f"Deleted '{key}'.")
        return True

    def _update_buttons(self) -> None:
        key = self._combo.currentData()
        self._load_btn.setEnabled(key is not None)
        self._delete_btn.setEnabled(key is not None and key != LAST_USED)

    def _show(self, text: str, *, error: bool = False) -> None:
        self._message.setText(text)
        self._message.setStyleSheet("color: #b00020;" if error else "")

    def _ask_name(self) -> str | None:
        text, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        return text if ok else None

    def _confirm(self, question: str) -> bool:
        answer = QMessageBox.question(self, "Presets", question)
        return answer == QMessageBox.StandardButton.Yes
