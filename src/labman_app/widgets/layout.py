"""Layout helpers shared by task widgets."""

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget


def titled_column(title: str, body: QWidget, *, scrollable: bool) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(f"<h3 style='margin:0'>{title}</h3>"))
    if scrollable:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(body)
        layout.addWidget(area, 1)
    else:
        layout.addWidget(body, 1)
    return holder


def labeled(title: str, widget: QWidget) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(f"<b>{title}</b>"))
    layout.addWidget(widget)
    return holder
