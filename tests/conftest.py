import sys

import pytest


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for widget tests.

    Lazy-imports PySide6 so that tests not needing Qt continue to run on
    machines without the `[app]` extra installed.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    yield app
