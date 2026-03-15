"""L1 unit tests for revolver.infra.store — run store operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from revolver.infra.store import (
    copy_run_file,
    create_run_dir,
    get_active_locks,
    get_run_dir,
    init_project_store,
    read_run_manifest,
    remove_run_lock,
    write_run_lock,
    write_run_manifest,
)


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with initialized .revolver/ store."""
    init_project_store(tmp_path)
    return tmp_path


@pytest.mark.unit
def test_create_run_dir(tmp_project: Path) -> None:
    """create_run_dir must create the run directory with programs/ subdir."""
    run_dir = create_run_dir(tmp_project, "run-20260310-143000")

    assert run_dir.is_dir()
    assert (run_dir / "programs").is_dir()
    assert run_dir.name == "run-20260310-143000"


@pytest.mark.unit
def test_create_run_dir_already_exists(tmp_project: Path) -> None:
    """create_run_dir must raise if directory already exists."""
    create_run_dir(tmp_project, "run-20260310-143000")

    with pytest.raises(FileExistsError):
        create_run_dir(tmp_project, "run-20260310-143000")


@pytest.mark.unit
def test_write_and_read_run_manifest(tmp_project: Path) -> None:
    """write_run_manifest and read_run_manifest must round-trip YAML data."""
    run_id = "run-20260310-143000"
    create_run_dir(tmp_project, run_id)

    data = {
        "run_id": run_id,
        "status": "completed",
        "iterations": 10,
        "programs": [{"rank": 1, "file": "programs/rank-1.py"}],
    }
    write_run_manifest(tmp_project, run_id, data)
    loaded = read_run_manifest(tmp_project, run_id)

    assert loaded == data


@pytest.mark.unit
def test_read_run_manifest_not_found(tmp_project: Path) -> None:
    """read_run_manifest must raise FileNotFoundError if manifest does not exist."""
    with pytest.raises(FileNotFoundError):
        read_run_manifest(tmp_project, "nonexistent-run")


@pytest.mark.unit
def test_write_and_remove_run_lock(tmp_project: Path) -> None:
    """write_run_lock must create a lock file; remove_run_lock must delete it."""
    run_id = "run-20260310-143000"
    lock_data = {"run_id": run_id, "pid": 12345, "llm_source": "local"}

    write_run_lock(tmp_project, run_id, lock_data)

    # Lock file should exist
    locks_dir = tmp_project / ".revolver" / "runs" / "locks"
    lock_file = locks_dir / f"{run_id}.lock"
    assert lock_file.exists()

    remove_run_lock(tmp_project, run_id)
    assert not lock_file.exists()


@pytest.mark.unit
def test_remove_run_lock_nonexistent(tmp_project: Path) -> None:
    """remove_run_lock must not raise if lock file does not exist."""
    remove_run_lock(tmp_project, "nonexistent-run")  # Should not raise


@pytest.mark.unit
def test_get_active_locks_empty(tmp_project: Path) -> None:
    """get_active_locks must return empty list if no locks exist."""
    result = get_active_locks(tmp_project)
    assert result == []


@pytest.mark.unit
def test_get_active_locks_with_locks(tmp_project: Path) -> None:
    """get_active_locks must return parsed data for each lock file."""
    write_run_lock(
        tmp_project,
        "run-001",
        {"run_id": "run-001", "pid": 100, "llm_source": "local"},
    )
    write_run_lock(
        tmp_project,
        "run-002",
        {"run_id": "run-002", "pid": 200, "llm_source": "remote"},
    )

    locks = get_active_locks(tmp_project)
    assert len(locks) == 2
    assert locks[0]["run_id"] == "run-001"
    assert locks[1]["run_id"] == "run-002"
    assert "_lock_file" in locks[0]


@pytest.mark.unit
def test_copy_run_file(tmp_path: Path) -> None:
    """copy_run_file must copy a file preserving content."""
    src = tmp_path / "source" / "test.py"
    src.parent.mkdir()
    src.write_text("print('hello')")

    dst = tmp_path / "dest" / "subdir" / "test.py"
    copy_run_file(src, dst)

    assert dst.exists()
    assert dst.read_text() == "print('hello')"


@pytest.mark.unit
def test_copy_run_file_directory(tmp_path: Path) -> None:
    """copy_run_file must copy a directory tree."""
    src_dir = tmp_path / "source" / "checkpoint"
    src_dir.mkdir(parents=True)
    (src_dir / "data.bin").write_bytes(b"checkpoint data")
    (src_dir / "meta.json").write_text('{"step": 42}')

    dst_dir = tmp_path / "dest" / "checkpoint"
    copy_run_file(src_dir, dst_dir)

    assert dst_dir.is_dir()
    assert (dst_dir / "data.bin").read_bytes() == b"checkpoint data"
    assert (dst_dir / "meta.json").read_text() == '{"step": 42}'


@pytest.mark.unit
def test_get_run_dir(tmp_project: Path) -> None:
    """get_run_dir must return the correct path."""
    run_dir = get_run_dir(tmp_project, "run-20260310-143000")
    expected = tmp_project / ".revolver" / "runs" / "run-20260310-143000"
    assert run_dir == expected
