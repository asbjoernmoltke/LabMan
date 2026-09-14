from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

DEFAULT_DATA_ROOT: Path = Path("app") / "data"


@dataclass
class StorageOptions:
    """Per-run overrides of the default storage layout.

    folder  - replaces "<data_root>/<task_name>/" when set.
    naming  - "timestamp" (default) uses YYYY/MM/DD/<prefix><YYYYMMDDTHHMMSS>;
              "iterator" uses <prefix><NNN> with NNN being the next free integer.
    prefix  - prepended to the leaf directory name. Default empty string.
    """

    folder: Path | None = None
    naming: Literal["timestamp", "iterator"] = "timestamp"
    prefix: str = ""


class RunStorage:
    """Owns the directory for one run and produces canonical file paths.

    Instantiation creates the run directory eagerly.
    """

    RAW = "raw.h5"
    RESULT = "result.h5"
    PARAMS = "params.json"
    META = "meta.json"

    def __init__(
        self,
        task_name: str,
        opts: StorageOptions,
        data_root: Path,
        clock: "Callable[[], datetime] | None" = None,  # noqa: F821
    ):
        self.task_name = task_name
        self.opts = opts
        self.data_root = Path(data_root)
        self._now = clock or (lambda: datetime.now(UTC))
        self._root = self._make_run_dir()

    @property
    def root(self) -> Path:
        return self._root

    def raw_path(self) -> Path:
        return self._root / self.RAW

    def result_path(self) -> Path:
        return self._root / self.RESULT

    def params_path(self) -> Path:
        return self._root / self.PARAMS

    def meta_path(self) -> Path:
        return self._root / self.META

    def _base_dir(self) -> Path:
        return self.opts.folder if self.opts.folder is not None else self.data_root / self.task_name

    def _make_run_dir(self) -> Path:
        base = self._base_dir()
        base.mkdir(parents=True, exist_ok=True)

        if self.opts.naming == "timestamp":
            now = self._now()
            day_dir = base / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}"
            day_dir.mkdir(parents=True, exist_ok=True)
            stamp = now.strftime("%Y%m%dT%H%M%S")
            leaf = f"{self.opts.prefix}{stamp}" if self.opts.prefix else stamp
            return self._make_unique(day_dir, leaf)
        if self.opts.naming == "iterator":
            run_dir = base / self._next_iterator_leaf(base, self.opts.prefix)
            run_dir.mkdir(parents=True, exist_ok=False)
            return run_dir
        raise ValueError(f"Unknown naming mode: {self.opts.naming!r}")

    @staticmethod
    def _make_unique(parent: Path, leaf: str) -> Path:
        """Create parent/leaf, or leaf_1, leaf_2, ... when runs start within the same second."""
        suffix = 0
        while True:
            run_dir = parent / (leaf if suffix == 0 else f"{leaf}_{suffix}")
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
                return run_dir
            except FileExistsError:
                suffix += 1

    @staticmethod
    def _next_iterator_leaf(base: Path, prefix: str) -> str:
        existing = []
        for p in base.iterdir():
            if not p.is_dir():
                continue
            tail = p.name[len(prefix):] if prefix and p.name.startswith(prefix) else p.name
            if tail.isdigit():
                existing.append(int(tail))
        n = (max(existing) + 1) if existing else 0
        return f"{prefix}{n:03d}"
