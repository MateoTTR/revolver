"""Unit tests for the root CLI application.

Covers:
- Global options (--json, --verbose, --quiet) are stored in context
- --version still works
- All command groups appear in --help output
- Command group stubs exist
"""

from __future__ import annotations

import re
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from revolver.cli import app

runner = CliRunner()

# ANSI escape codes pattern (rich formatting in CI)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


@pytest.mark.unit
class TestCliGlobalOptions:
    """Global callback stores options in typer.Context.obj."""

    def test_help_shows_global_options(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.stdout)
        assert "--json" in output
        assert "--verbose" in output
        assert "--quiet" in output
        assert "--version" in output

    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout

    def test_version_short_flag(self) -> None:
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout


@pytest.mark.unit
class TestCliCommandGroups:
    """All command groups are registered and visible in help."""

    EXPECTED_GROUPS: ClassVar[list[str]] = [
        "project",
        "llm",
        "problem",
        "dataset",
        "run",
        "solution",
        "eval",
        "benchmark",
    ]

    def test_help_shows_all_command_groups(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.stdout)
        for group in self.EXPECTED_GROUPS:
            assert group in output, f"Command group '{group}' not found in --help"

    def test_no_args_shows_help(self) -> None:
        """When invoked with no args, help is displayed (Typer uses exit code 0)."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "OpenEvolve" in _strip_ansi(result.stdout)
