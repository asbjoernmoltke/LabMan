"""Cross-process exclusive lock on a physical hardware resource.

Backs the hardware-exclusivity assumption (CLAUDE.md): at most one LabMan
process holds a given instrument. Uses OS advisory file locks, which the OS
drops when the holding process exits, so a crash never leaves a stale lock.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from typing import IO

DEFAULT_LOCK_DIR: Path = Path(tempfile.gettempdir()) / "labman-locks"


class ResourceBusy(RuntimeError):
    """The resource is already held by another LabMan process or registry."""


class ResourceLock:
    """Non-blocking exclusive lock keyed by a resource string (e.g. a VISA address)."""

    def __init__(self, resource: str, lock_dir: Path = DEFAULT_LOCK_DIR) -> None:
        self.resource = resource
        digest = hashlib.sha1(resource.encode("utf-8")).hexdigest()[:16]
        self.path = Path(lock_dir) / f"{digest}.lock"
        self._fh: IO[bytes] | None = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    def acquire(self) -> None:
        """Take the lock or raise `ResourceBusy`. No-op if this object already holds it."""
        if self._fh is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")  # kept open for the lifetime of the lock
        try:
            _lock(fh)
        except OSError as e:
            fh.close()
            raise ResourceBusy(
                f"resource {self.resource!r} is in use by another LabMan process"
            ) from e
        self._fh = fh

    def release(self) -> None:
        """Release the lock. Idempotent."""
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            _unlock(fh)
        finally:
            fh.close()

    def __enter__(self) -> ResourceLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


if sys.platform == "win32":
    import msvcrt

    def _lock(fh: IO[bytes]) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(fh: IO[bytes]) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fh: IO[bytes]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fh: IO[bytes]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
