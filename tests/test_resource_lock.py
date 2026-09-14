import subprocess
import sys
from pathlib import Path

import pytest

from labman_core.resource_lock import ResourceBusy, ResourceLock


def test_acquire_and_release_is_idempotent(tmp_path: Path) -> None:
    lock = ResourceLock("COM3", tmp_path)
    lock.acquire()
    lock.acquire()  # no-op when already held
    assert lock.held
    lock.release()
    lock.release()
    assert not lock.held


def test_second_holder_is_busy(tmp_path: Path) -> None:
    with ResourceLock("COM3", tmp_path), pytest.raises(ResourceBusy, match="COM3"):
        ResourceLock("COM3", tmp_path).acquire()


def test_reacquire_after_release(tmp_path: Path) -> None:
    with ResourceLock("COM3", tmp_path):
        pass
    with ResourceLock("COM3", tmp_path) as lock:
        assert lock.held


def test_different_resources_are_independent(tmp_path: Path) -> None:
    with ResourceLock("COM3", tmp_path), ResourceLock("COM4", tmp_path) as other:
        assert other.held


def test_lock_is_cross_process_and_dropped_when_holder_exits(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from labman_core.resource_lock import ResourceLock\n"
        "lock = ResourceLock('USB::1', Path(sys.argv[1]))\n"  # keep a ref: GC closes the file
        "lock.acquire()\n"
        "print('locked', flush=True)\n"
        "sys.stdin.read()\n"  # hold until the parent closes stdin; exit without release()
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "locked"
        with pytest.raises(ResourceBusy):
            ResourceLock("USB::1", tmp_path).acquire()
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(timeout=10)

    with ResourceLock("USB::1", tmp_path) as lock:
        assert lock.held
