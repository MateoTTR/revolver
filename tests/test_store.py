"""L1 unit tests for revolver.infra.store — project store management."""

from __future__ import annotations

from pathlib import Path
import stat

import pytest

from revolver.infra.store import (
    REVOLVER_DIR,
    ProjectNotFoundError,
    find_project_root,
    init_project_store,
    read_manifest,
    write_manifest,
)


@pytest.mark.unit
def test_find_project_root(tmp_path: Path) -> None:
    """find_project_root must walk upward and find .revolver/ directory."""
    # Create a nested directory with .revolver/ at the top
    root = tmp_path / "project"
    root.mkdir()
    (root / REVOLVER_DIR).mkdir()

    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)

    found = find_project_root(deep)
    assert found == root


@pytest.mark.unit
def test_find_project_root_not_found(tmp_path: Path) -> None:
    """find_project_root must raise ProjectNotFoundError when not found."""
    with pytest.raises(ProjectNotFoundError):
        find_project_root(tmp_path)


@pytest.mark.unit
def test_init_creates_structure(tmp_path: Path) -> None:
    """init_project_store must create .revolver/ with subdirectories."""
    revolver_path = init_project_store(tmp_path)

    assert revolver_path.is_dir()
    assert (revolver_path / "problem").is_dir()
    assert (revolver_path / "datasets").is_dir()
    assert (revolver_path / "runs").is_dir()


@pytest.mark.unit
def test_permissions_700(tmp_path: Path) -> None:
    """init_project_store must set .revolver/ permissions to 700 (NFR-051)."""
    revolver_path = init_project_store(tmp_path)

    mode = stat.S_IMODE(revolver_path.stat().st_mode)
    assert mode == 0o700, f"Expected mode 0o700, got {oct(mode)}"


@pytest.mark.unit
def test_write_and_read_manifest(tmp_path: Path) -> None:
    """write_manifest and read_manifest must round-trip YAML data."""
    manifest_path = tmp_path / "subdir" / "manifest.yaml"
    data = {"tag": "v1.0", "hash": "sha256:abc123", "files": ["a.py", "b.py"]}

    write_manifest(manifest_path, data)
    assert manifest_path.exists()

    loaded = read_manifest(manifest_path)
    assert loaded == data
