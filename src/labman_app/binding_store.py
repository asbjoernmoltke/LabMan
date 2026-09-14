"""Remembers the last device chosen for each task binding.

One JSON file for all tasks: `{task_name: {binding_name: device_name}}`.
Deliberately separate from `PresetStore`: bindings describe the lab wiring,
not measurement parameters. No Qt imports.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

DEFAULT_BINDINGS_PATH: Path = Path("app") / "state" / "bindings.json"

logger = logging.getLogger("labman.shell")


class BindingStore:
    def __init__(self, path: Path = DEFAULT_BINDINGS_PATH) -> None:
        self.path = Path(path)

    def load(self, task_name: str) -> dict[str, str]:
        """Last saved bindings for the task; empty if none or the file is unreadable."""
        entry = self._read_all().get(task_name)
        if not isinstance(entry, dict):
            return {}
        return {str(b): d for b, d in entry.items() if isinstance(d, str)}

    def save(self, task_name: str, bindings: dict[str, str]) -> None:
        data = self._read_all()
        data[task_name] = dict(bindings)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def _read_all(self) -> dict[str, Any]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("ignoring unreadable bindings file %s", self.path)
            return {}
        return data if isinstance(data, dict) else {}
