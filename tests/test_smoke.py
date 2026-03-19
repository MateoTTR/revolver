"""Smoke test — verify package imports and CLI entrypoint."""

from pathlib import Path
import re

import pytest
from typer.testing import CliRunner

from revolver import __version__
from revolver.cli import app

runner = CliRunner()

# Read version from pyproject.toml as ground truth
_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _pyproject_version() -> str:
    """Extract version string from pyproject.toml."""
    for line in _PYPROJECT.read_text().splitlines():
        m = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if m:
            return m.group(1)
    raise RuntimeError("version not found in pyproject.toml")


@pytest.mark.unit
def test_version_matches_pyproject() -> None:
    assert __version__ == _pyproject_version()


@pytest.mark.unit
def test_cli_app_exists() -> None:
    assert app is not None


@pytest.mark.unit
def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "OpenEvolve" in result.stdout


@pytest.mark.unit
def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
