"""Project store — directory structure management and manifest I/O.

Handles the ``.revolver/`` directory tree: creation, discovery, and
YAML manifest read/write. Includes dataset manifest/snapshot operations
and run directory/manifest/lock file operations.

Traceable to: NFR-010, NFR-012, NFR-051 (permissions 700), DES-004 §6, DES-005 §4.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

# ── Constants ────────────────────────────────────────────────────────────────

REVOLVER_DIR = ".revolver"
PROBLEM_DIR = "problem"
DATASETS_DIR = "datasets"
RUNS_DIR = "runs"

_SUBDIRS = (PROBLEM_DIR, DATASETS_DIR, RUNS_DIR)


class ProjectNotFoundError(Exception):
    """Raised when no ``.revolver/`` directory is found in the hierarchy."""


def find_project_root(start: Path) -> Path:
    """Walk upward from *start* looking for a ``.revolver/`` directory.

    Args:
        start: Directory to start searching from.

    Returns:
        The directory that contains ``.revolver/``.

    Raises:
        ProjectNotFoundError: If no ``.revolver/`` is found up to the
            filesystem root.
    """
    current = start.resolve()
    while True:
        candidate = current / REVOLVER_DIR
        if candidate.is_dir():
            return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root.
            raise ProjectNotFoundError(
                f"No {REVOLVER_DIR}/ directory found from {start} to filesystem root."
            )
        current = parent


def init_project_store(path: Path) -> Path:
    """Create the ``.revolver/`` directory tree with mode 700.

    Creates the following structure::

        <path>/.revolver/         (mode 700)
            problem/
            datasets/
            runs/

    Args:
        path: Project root directory (must exist).

    Returns:
        Path to the created ``.revolver/`` directory.
    """
    revolver_path = path / REVOLVER_DIR
    revolver_path.mkdir(mode=0o700, exist_ok=False)
    for subdir in _SUBDIRS:
        (revolver_path / subdir).mkdir()
    return revolver_path


def write_manifest(path: Path, data: dict[str, Any]) -> None:
    """Write a YAML manifest file.

    Args:
        path: Destination file path (e.g. ``.revolver/problem/v1.0/manifest.yaml``).
        data: Dictionary to serialize as YAML.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def read_manifest(path: Path) -> dict[str, Any]:
    """Read a YAML manifest file.

    Args:
        path: Path to the manifest file.

    Returns:
        Parsed dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    with open(path, encoding="utf-8") as f:
        result: dict[str, Any] = yaml.safe_load(f)
    return result


# ── Dataset store operations ───────────────────────────────────────────────


def _dataset_dir(project_root: Path, name: str) -> Path:
    """Return the dataset directory path: ``<project_root>/.revolver/datasets/<name>/``."""
    return project_root / REVOLVER_DIR / DATASETS_DIR / name


def _dataset_manifest_path(project_root: Path, name: str) -> Path:
    """Return the manifest file path for a dataset."""
    return _dataset_dir(project_root, name) / "manifest.yaml"


def write_dataset_manifest(
    project_root: Path,
    name: str,
    data: dict[str, Any],
) -> None:
    """Write a dataset manifest YAML file.

    Creates ``<project_root>/.revolver/datasets/<name>/manifest.yaml``.

    Args:
        project_root: Project root directory.
        name: Dataset name.
        data: Dictionary to serialize as YAML.
    """
    manifest_path = _dataset_manifest_path(project_root, name)
    write_manifest(manifest_path, data)


def read_dataset_manifest(
    project_root: Path,
    name: str,
) -> dict[str, Any]:
    """Read a dataset manifest YAML file.

    Args:
        project_root: Project root directory.
        name: Dataset name.

    Returns:
        Parsed dictionary.

    Raises:
        FileNotFoundError: If the manifest does not exist.
    """
    manifest_path = _dataset_manifest_path(project_root, name)
    return read_manifest(manifest_path)


def update_dataset_manifest(
    project_root: Path,
    name: str,
    data: dict[str, Any],
) -> None:
    """Overwrite a dataset manifest YAML file.

    Args:
        project_root: Project root directory.
        name: Dataset name.
        data: Dictionary to serialize as YAML (replaces existing content).
    """
    manifest_path = _dataset_manifest_path(project_root, name)
    write_manifest(manifest_path, data)


def delete_dataset_store(project_root: Path, name: str) -> None:
    """Remove the dataset directory tree.

    Deletes ``<project_root>/.revolver/datasets/<name>/`` and all contents
    (manifest, snapshot files, etc.).

    Args:
        project_root: Project root directory.
        name: Dataset name.
    """
    dataset_path = _dataset_dir(project_root, name)
    if dataset_path.exists():
        shutil.rmtree(dataset_path)


def create_dataset_snapshot(
    project_root: Path,
    name: str,
    source_path: Path,
) -> Path:
    """Copy all files from source into the dataset snapshot directory.

    Creates ``<project_root>/.revolver/datasets/<name>/snapshot/`` and copies
    all top-level files and subdirectories from *source_path* into it.

    Args:
        project_root: Project root directory.
        name: Dataset name.
        source_path: Source directory containing the dataset files.

    Returns:
        Path to the created snapshot directory.
    """
    snapshot_dir = get_snapshot_path(project_root, name)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source_path.iterdir()):
        if entry.name.startswith("."):
            continue
        dest = snapshot_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest)
        else:
            shutil.copy2(entry, dest)
    return snapshot_dir


def get_snapshot_path(project_root: Path, name: str) -> Path:
    """Return the snapshot directory path for a dataset.

    Args:
        project_root: Project root directory.
        name: Dataset name.

    Returns:
        Path to ``<project_root>/.revolver/datasets/<name>/snapshot/``.
    """
    return _dataset_dir(project_root, name) / "snapshot"


# ── Run store operations ──────────────────────────────────────────────────

LOCKS_DIR = "locks"


def _run_dir(project_root: Path, run_id: str) -> Path:
    """Return the run directory path: ``<project_root>/.revolver/runs/<run_id>/``."""
    return project_root / REVOLVER_DIR / RUNS_DIR / run_id


def _locks_dir(project_root: Path) -> Path:
    """Return the locks directory path: ``<project_root>/.revolver/runs/locks/``."""
    return project_root / REVOLVER_DIR / RUNS_DIR / LOCKS_DIR


def create_run_dir(project_root: Path, run_id: str) -> Path:
    """Create the run directory with a ``programs/`` subdirectory.

    Creates::

        <project_root>/.revolver/runs/<run_id>/
        <project_root>/.revolver/runs/<run_id>/programs/

    Args:
        project_root: Project root directory.
        run_id: Unique run identifier.

    Returns:
        Path to the created run directory.
    """
    run_path = _run_dir(project_root, run_id)
    run_path.mkdir(parents=True, exist_ok=False)
    (run_path / "programs").mkdir()
    return run_path


def write_run_manifest(
    project_root: Path,
    run_id: str,
    data: dict[str, Any],
) -> None:
    """Write a run manifest YAML file.

    Creates ``<project_root>/.revolver/runs/<run_id>/manifest.yaml``.

    Args:
        project_root: Project root directory.
        run_id: Unique run identifier.
        data: Dictionary to serialize as YAML.
    """
    manifest_path = _run_dir(project_root, run_id) / "manifest.yaml"
    write_manifest(manifest_path, data)


def read_run_manifest(
    project_root: Path,
    run_id: str,
) -> dict[str, Any]:
    """Read a run manifest YAML file.

    Args:
        project_root: Project root directory.
        run_id: Unique run identifier.

    Returns:
        Parsed dictionary.

    Raises:
        FileNotFoundError: If the manifest does not exist.
    """
    manifest_path = _run_dir(project_root, run_id) / "manifest.yaml"
    return read_manifest(manifest_path)


def write_run_lock(
    project_root: Path,
    run_id: str,
    lock_data: dict[str, Any],
) -> None:
    """Write a run lock file.

    Creates ``<project_root>/.revolver/runs/locks/<run_id>.lock``
    containing JSON-serialized lock data (PID, LLM source, start time, etc.).

    Args:
        project_root: Project root directory.
        run_id: Unique run identifier.
        lock_data: Dictionary to serialize as JSON.
    """
    locks_path = _locks_dir(project_root)
    locks_path.mkdir(parents=True, exist_ok=True)
    lock_file = locks_path / f"{run_id}.lock"
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")


def remove_run_lock(project_root: Path, run_id: str) -> None:
    """Remove a run lock file.

    Silently ignores if the lock file does not exist.

    Args:
        project_root: Project root directory.
        run_id: Unique run identifier.
    """
    lock_file = _locks_dir(project_root) / f"{run_id}.lock"
    if lock_file.exists():
        lock_file.unlink()


def get_active_locks(project_root: Path) -> list[dict[str, Any]]:
    """List all active lock files and return their parsed data.

    Scans ``<project_root>/.revolver/runs/locks/`` for ``.lock`` files
    and parses each as JSON.

    Args:
        project_root: Project root directory.

    Returns:
        A list of parsed lock data dicts. Each dict includes an extra
        ``"_lock_file"`` key with the lock file name (e.g. ``"run-123.lock"``).
    """
    locks_path = _locks_dir(project_root)
    if not locks_path.exists():
        return []

    result: list[dict[str, Any]] = []
    for lock_file in sorted(locks_path.glob("*.lock")):
        try:
            data: dict[str, Any] = json.loads(lock_file.read_text(encoding="utf-8"))
            data["_lock_file"] = lock_file.name
            result.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return result


def copy_run_file(src: Path, dst: Path) -> None:
    """Copy a file from one run directory to another.

    Utility for copying wrapper evaluators, checkpoints, etc.
    Creates parent directories if needed.

    Args:
        src: Source file path.
        dst: Destination file path.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def get_run_dir(project_root: Path, run_id: str) -> Path:
    """Return the run directory path.

    Args:
        project_root: Project root directory.
        run_id: Unique run identifier.

    Returns:
        Path to ``<project_root>/.revolver/runs/<run_id>/``.
    """
    return _run_dir(project_root, run_id)
