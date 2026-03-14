"""Project store — directory structure management and manifest I/O.

Handles the ``.revolver/`` directory tree: creation, discovery, and
YAML manifest read/write. Includes dataset manifest and snapshot operations.

Traceable to: NFR-010, NFR-012, NFR-051 (permissions 700), DES-004 §6.
"""

from __future__ import annotations

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
