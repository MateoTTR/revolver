"""Smoke test — verify package imports and CLI entrypoint."""

import pytest
from typer.testing import CliRunner

from revolver.cli import app

runner = CliRunner()


@pytest.mark.unit
def test_import_revolver() -> None:
    import revolver

    assert revolver.__version__ == "0.1.0"


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
    assert "0.1.0" in result.stdout
