from datetime import UTC, datetime
from pathlib import Path

from labman_core.storage import RunStorage, StorageOptions


def test_default_timestamp_layout(tmp_path: Path) -> None:
    fixed = datetime(2026, 4, 22, 14, 30, 22, tzinfo=UTC)
    s = RunStorage("coupling_efficiency", StorageOptions(), tmp_path, clock=lambda: fixed)
    expected = tmp_path / "coupling_efficiency" / "2026" / "04" / "22" / "20260422T143022"
    assert s.root == expected
    assert s.root.is_dir()
    assert s.raw_path() == expected / "raw.h5"


def test_timestamp_with_prefix(tmp_path: Path) -> None:
    fixed = datetime(2026, 4, 22, 14, 30, 22, tzinfo=UTC)
    s = RunStorage(
        "coupling_efficiency",
        StorageOptions(prefix="cal_"),
        tmp_path,
        clock=lambda: fixed,
    )
    assert s.root.name == "cal_20260422T143022"


def test_runs_started_in_the_same_second_get_distinct_dirs(tmp_path: Path) -> None:
    fixed = datetime(2026, 4, 22, 14, 30, 22, tzinfo=UTC)
    runs = [RunStorage("t", StorageOptions(), tmp_path, clock=lambda: fixed) for _ in range(3)]
    assert [r.root.name for r in runs] == [
        "20260422T143022", "20260422T143022_1", "20260422T143022_2"
    ]
    assert all(r.root.is_dir() for r in runs)


def test_iterator_naming(tmp_path: Path) -> None:
    opts = StorageOptions(naming="iterator", prefix="run_")
    s1 = RunStorage("t", opts, tmp_path)
    s2 = RunStorage("t", opts, tmp_path)
    s3 = RunStorage("t", opts, tmp_path)
    assert s1.root.name == "run_000"
    assert s2.root.name == "run_001"
    assert s3.root.name == "run_002"


def test_explicit_folder_overrides_default(tmp_path: Path) -> None:
    custom = tmp_path / "experiments" / "session_42"
    fixed = datetime(2026, 4, 22, 14, 30, 22, tzinfo=UTC)
    s = RunStorage(
        "coupling_efficiency",
        StorageOptions(folder=custom),
        tmp_path,
        clock=lambda: fixed,
    )
    assert s.root.parent.parent.parent.parent == custom
    assert "coupling_efficiency" not in str(s.root.relative_to(tmp_path))
