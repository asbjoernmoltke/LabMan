from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSlider, QWidget

from labman_app.widgets.base import SchemaWidget
from labman_core.schema import Range


class NumericInput(SchemaWidget):
    """Numeric entry, optionally accompanied by a slider when bounds are set.

    Drag of the slider previews the value in the line edit but does NOT commit.
    Commit fires on slider release, line-edit Enter, or focus-out.
    Values failing validation/bounds revert to last-committed.
    """

    SLIDER_RES = 1000

    def __init__(
        self,
        bounds: Range | None = None,
        unit: str = "",
        integer: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bounds = bounds
        self._integer = integer
        self._unit = unit
        self._last_value: float | int | None = None

        self._line = QLineEdit()
        self._line.setValidator(self._make_validator())

        self._slider: QSlider | None = None
        if bounds is not None:
            self._slider = QSlider(Qt.Orientation.Horizontal)
            if integer:
                self._slider.setRange(int(bounds.low), int(bounds.high))
            else:
                self._slider.setRange(0, self.SLIDER_RES)
            self._slider.sliderMoved.connect(self._on_slider_moved)
            self._slider.sliderReleased.connect(self._on_slider_released)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if self._slider is not None:
            layout.addWidget(self._slider, 3)
        layout.addWidget(self._line, 2)
        if unit:
            layout.addWidget(QLabel(unit), 0)

        self._line.editingFinished.connect(self._on_line_committed)

    def value(self) -> Any:
        text = self._line.text().strip()
        if not text:
            raise ValueError("empty numeric value")
        return int(text) if self._integer else float(text)

    def set_value(self, v: Any) -> None:
        if self._integer:
            self._line.setText(str(int(v)))
        else:
            self._line.setText(self._format_float(float(v)))
        if self._slider is not None:
            self._sync_slider_from(float(v))
        self._last_value = int(v) if self._integer else float(v)

    def _make_validator(self) -> QIntValidator | QDoubleValidator:
        if self._integer:
            v = QIntValidator()
            if self._bounds is not None:
                v.setRange(int(self._bounds.low), int(self._bounds.high))
            return v
        v = QDoubleValidator()
        v.setNotation(QDoubleValidator.Notation.StandardNotation)
        if self._bounds is not None:
            v.setRange(float(self._bounds.low), float(self._bounds.high), 6)
        return v

    def _on_slider_moved(self, position: int) -> None:
        v = self._slider_to_value(position)
        if self._integer:
            self._line.setText(str(int(v)))
        else:
            self._line.setText(self._format_float(v))

    def _on_slider_released(self) -> None:
        self._commit_from_line()

    def _on_line_committed(self) -> None:
        self._commit_from_line()

    def _commit_from_line(self) -> None:
        try:
            v = self.value()
        except ValueError:
            self._restore_last()
            return
        if not self._in_bounds(v):
            self._restore_last()
            return
        if self._slider is not None:
            self._sync_slider_from(float(v))
        self._last_value = v
        self.committed.emit(v)

    def _restore_last(self) -> None:
        if self._last_value is not None:
            self.set_value(self._last_value)

    def _in_bounds(self, v: float) -> bool:
        return self._bounds is None or self._bounds.low <= v <= self._bounds.high

    def _slider_to_value(self, position: int) -> float:
        if self._integer or self._bounds is None:
            return float(position)
        frac = position / self.SLIDER_RES
        return self._bounds.low + frac * (self._bounds.high - self._bounds.low)

    def _sync_slider_from(self, v: float) -> None:
        assert self._slider is not None
        if self._integer:
            pos = int(v)
        else:
            assert self._bounds is not None
            span = self._bounds.high - self._bounds.low
            frac = (v - self._bounds.low) / span if span else 0.0
            pos = int(round(frac * self.SLIDER_RES))
        self._slider.blockSignals(True)
        self._slider.setValue(pos)
        self._slider.blockSignals(False)

    @staticmethod
    def _format_float(v: float) -> str:
        return f"{v:g}"
