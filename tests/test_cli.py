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

from revolver import __version__
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
        assert __version__ in result.stdout

    def test_version_short_flag(self) -> None:
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert __version__ in result.stdout


def _flatten_error_output(result: object) -> str:
    """Strip ANSI codes and rich panel borders, collapse whitespace.

    Rich wraps error text inside a bordered panel with hard line breaks at
    arbitrary positions, so multi-word assertions must run against a
    flattened single-line view of the output.
    """
    parts: list[str] = []
    for attr in ("stdout", "stderr", "output"):
        val = getattr(result, attr, None)
        if val:
            parts.append(val)
    cleaned = re.sub(r"[│╭╮╰╯─]", " ", _strip_ansi("".join(parts)))
    return " ".join(cleaned.split())


@pytest.mark.unit
class TestUnknownSubcommandEqualsTokenHint:
    """U3 (S17a-10): stray ``key=value`` tokens get a repeatable-option hint."""

    def test_unknown_subcommand_equals_token_hint(self) -> None:
        """``revolver run foo=bar`` names the likely repeatable options."""
        result = runner.invoke(app, ["run", "foo=bar"])
        assert result.exit_code != 0
        output = _flatten_error_output(result)
        assert "No such command 'foo=bar'." in output
        assert "one key=value per flag" in output
        # The likely options are named, with a copy-pasteable example.
        assert "--config-override foo=bar" in output
        assert "--selection-kwarg" in output
        assert "--llm-weight" in output

    def test_equals_token_hint_on_root_group(self) -> None:
        """The hint is generic to every GlobalOptionGroup level (root too)."""
        result = runner.invoke(app, ["foo=bar"])
        assert result.exit_code != 0
        output = _flatten_error_output(result)
        assert "No such command 'foo=bar'." in output
        assert "one key=value per flag" in output

    def test_genuine_typo_still_gets_did_you_mean(self) -> None:
        """A non-'=' typo keeps Typer's did-you-mean and gains no hint."""
        result = runner.invoke(app, ["run", "stat"])
        assert result.exit_code != 0
        output = _flatten_error_output(result)
        assert "Did you mean 'status'?" in output
        assert "Hint:" not in output


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
