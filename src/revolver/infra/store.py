"""Project store — directory structure management and manifest I/O.

Handles the ``.revolver/`` directory tree: creation, discovery, and
YAML manifest read/write.

Traceable to: NFR-010, NFR-012, NFR-051 (permissions 700).
"""

from __future__ import annotations

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
