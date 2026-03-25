"""L2 integration tests for workspace detection guard (S9-09).

Tests that CLI commands requiring a workspace (run list, solution list,
benchmark list) fail gracefully with exit 1 and a clear error message
when invoked from a directory without ``.revolver/``.

Traceable to: val-integration-tests.md section 2 (Sprint 009).
"""

from __future__ import annotations

from pathlib import Path
import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app

pytestmark = pytest.mark.integration

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_WORKSPACE_MSG = "Not in a Revolver workspace"


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _get_all_output(result: object) -> str:
    """Combine stdout and stderr from a CliRunner result."""
    parts: list[str] = []
    for attr in ("stdout", "stderr", "output"):
        val = getattr(result, attr, None)
        if val:
            parts.append(val)
    return _strip_ansi("".join(parts))


def _invoke_with_cwd(args: list[str], cwd: Path) -> object:
    """Invoke the CLI with a patched working directory."""
    with patch("pathlib.Path.cwd", return_value=cwd):
        return runner.invoke(app, args, catch_exceptions=False)


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_run_list_outside_workspace(tmp_path: Path) -> None:
    """``revolver run list`` outside workspace exits 1 with clear message.

    Validates: S9-09 — workspace detection guard for ``run list``.
    """
    # tmp_path has no .revolver/ directory
    result = _invoke_with_cwd(["run", "list"], tmp_path)
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert _WORKSPACE_MSG in output


@pytest.mark.integration
def test_solution_list_outside_workspace(tmp_path: Path) -> None:
    """``revolver solution list`` outside workspace exits 1 with clear message.

    Validates: S9-09 — workspace detection guard for ``solution list``.
    """
    result = _invoke_with_cwd(["solution", "list"], tmp_path)
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert _WORKSPACE_MSG in output


@pytest.mark.integration
def test_benchmark_list_outside_workspace(tmp_path: Path) -> None:
    """``revolver benchmark list`` outside workspace exits 1 with clear message.

    Validates: S9-09 — workspace detection guard for ``benchmark list``.
    """
    result = _invoke_with_cwd(["benchmark", "list"], tmp_path)
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert _WORKSPACE_MSG in output
