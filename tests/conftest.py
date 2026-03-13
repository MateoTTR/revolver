"""Shared test fixtures for Revolver test suite."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from revolver.infra.store import init_project_store


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary directory with an initialized ``.revolver/`` store.

    Yields:
        The project root directory (``tmp_path``) with ``.revolver/`` created.
    """
    init_project_store(tmp_path)
    yield tmp_path
