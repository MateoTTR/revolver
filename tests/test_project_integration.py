"""L2 integration tests for ``revolver project init``.

Tests the CLI command end-to-end through Typer's CliRunner with a real
SQLite database and real filesystem (in ``tmp_path``).

Traceable to: val-integration-tests.md section 2.1.
"""

from __future__ import annotations

import re
import sqlite3
import stat

import pytest
from typer.testing import CliRunner
import yaml

from revolver.cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


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


@pytest.mark.integration
def test_init_creates_structure(tmp_path: pytest.TempPathFactory) -> None:
    """Happy path: project init creates .revolver/, project.yaml,
    revolver.db, and template files.
    """
    result = runner.invoke(app, ["project", "init", "my-project", "--path", str(tmp_path)])
    assert result.exit_code == 0, f"stdout: {result.stdout}"

    # .revolver/ directory exists
    revolver_dir = tmp_path / ".revolver"
    assert revolver_dir.is_dir()

    # Subdirectories exist (FR-PRJ-001)
    assert (revolver_dir / "problem").is_dir()
    assert (revolver_dir / "datasets").is_dir()
    assert (revolver_dir / "runs").is_dir()

    # project.yaml exists with correct name (FR-PRJ-002)
    project_yaml = tmp_path / "project.yaml"
    assert project_yaml.is_file()
    with open(project_yaml, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    assert manifest["name"] == "my-project"
    assert "created_at" in manifest
    assert "revolver_version" in manifest

    # revolver.db exists with tables (FR-PRJ-001)
    db_path = revolver_dir / "revolver.db"
    assert db_path.is_file()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "schema_version" in tables
    assert "problem_versions" in tables
    assert "datasets" in tables
    assert "runs" in tables
    assert "solutions" in tables

    # Template files created (FR-PRJ-003, FR-PRJ-004, FR-PRJ-005)
    assert (tmp_path / "initial_program.py").is_file()
    assert (tmp_path / "evaluator.py").is_file()
    assert (tmp_path / "config.yaml").is_file()

    # initial_program.py contains EVOLVE-BLOCK markers (FR-PRJ-003)
    initial_program = (tmp_path / "initial_program.py").read_text(encoding="utf-8")
    assert "EVOLVE-BLOCK-START" in initial_program
    assert "EVOLVE-BLOCK-END" in initial_program

    # evaluator.py contains evaluate_instance with correct signature (FR-PRJ-004)
    evaluator = (tmp_path / "evaluator.py").read_text(encoding="utf-8")
    assert "def evaluate_instance(program_path: str, instance_path: str)" in evaluator
    assert "combined_score" in evaluator
    # No legacy evaluate() — users must opt in explicitly
    assert "def evaluate(" not in evaluator

    # Output message contains project name
    output = _strip_ansi(result.stdout)
    assert "my-project" in output


@pytest.mark.integration
def test_init_existing_project_fails(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Dir already has .revolver/ -> exit code 1, error message."""
    # First init succeeds
    result1 = runner.invoke(app, ["project", "init", "my-project", "--path", str(tmp_path)])
    assert result1.exit_code == 0

    # Second init fails
    result2 = runner.invoke(app, ["project", "init", "my-project", "--path", str(tmp_path)])
    assert result2.exit_code == 1

    # Error message mentions already initialized
    output = _get_all_output(result2)
    assert "already initialized" in output.lower() or "error" in output.lower()


@pytest.mark.integration
def test_init_with_path_option(tmp_path: pytest.TempPathFactory) -> None:
    """--path creates a new directory and initializes the project inside."""
    new_dir = tmp_path / "new-dir"
    assert not new_dir.exists()

    result = runner.invoke(app, ["project", "init", "my-project", "--path", str(new_dir)])
    assert result.exit_code == 0

    # Directory was created
    assert new_dir.is_dir()

    # Project initialized inside
    assert (new_dir / ".revolver").is_dir()
    assert (new_dir / "project.yaml").is_file()
    assert (new_dir / "initial_program.py").is_file()
    assert (new_dir / "evaluator.py").is_file()
    assert (new_dir / "config.yaml").is_file()


@pytest.mark.integration
def test_init_directory_permissions(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """After init, .revolver/ has mode 700 (FR-PRJ-008, NFR-051)."""
    result = runner.invoke(app, ["project", "init", "my-project", "--path", str(tmp_path)])
    assert result.exit_code == 0

    revolver_dir = tmp_path / ".revolver"
    mode = stat.S_IMODE(revolver_dir.stat().st_mode)
    assert mode == 0o700, f"Expected mode 0o700, got {oct(mode)}"
