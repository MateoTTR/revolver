"""L2 integration tests for ``revolver project init``.

Tests the CLI command end-to-end through Typer's CliRunner with a real
SQLite database and real filesystem (in ``tmp_path``).

Traceable to: val-integration-tests.md section 2.1.
"""

from __future__ import annotations

import json
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


@pytest.mark.integration
def test_project_init_no_templates(tmp_path: pytest.TempPathFactory) -> None:
    """--no-templates creates .revolver/ and manifest but skips template files."""
    result = runner.invoke(
        app, ["project", "init", "my-project", "--path", str(tmp_path), "--no-templates"]
    )
    assert result.exit_code == 0, f"stdout: {result.stdout}"

    # .revolver/ directory exists
    revolver_dir = tmp_path / ".revolver"
    assert revolver_dir.is_dir()

    # project.yaml manifest exists with correct name
    project_yaml = tmp_path / "project.yaml"
    assert project_yaml.is_file()
    with open(project_yaml, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    assert manifest["name"] == "my-project"

    # SQLite database exists
    db_path = revolver_dir / "revolver.db"
    assert db_path.is_file()

    # Template files are NOT created
    assert not (tmp_path / "evaluator.py").exists()
    assert not (tmp_path / "initial_program.py").exists()
    assert not (tmp_path / "config.yaml").exists()

    # Output message contains project name
    output = _strip_ansi(result.stdout)
    assert "my-project" in output


@pytest.mark.integration
def test_project_init_templates_flag(tmp_path: pytest.TempPathFactory) -> None:
    """--templates (positive flag) creates template files, same as default behavior."""
    result = runner.invoke(
        app, ["project", "init", "my-project", "--path", str(tmp_path), "--templates"]
    )
    assert result.exit_code == 0, f"stdout: {result.stdout}"

    # .revolver/ directory exists
    revolver_dir = tmp_path / ".revolver"
    assert revolver_dir.is_dir()

    # project.yaml manifest exists
    project_yaml = tmp_path / "project.yaml"
    assert project_yaml.is_file()

    # Template files ARE created (same as default)
    assert (tmp_path / "evaluator.py").is_file()
    assert (tmp_path / "initial_program.py").is_file()
    assert (tmp_path / "config.yaml").is_file()

    # initial_program.py contains EVOLVE-BLOCK markers
    initial_program = (tmp_path / "initial_program.py").read_text(encoding="utf-8")
    assert "EVOLVE-BLOCK-START" in initial_program
    assert "EVOLVE-BLOCK-END" in initial_program

    # evaluator.py contains evaluate_instance with correct signature
    evaluator = (tmp_path / "evaluator.py").read_text(encoding="utf-8")
    assert "def evaluate_instance(program_path: str, instance_path: str)" in evaluator


@pytest.mark.integration
def test_project_init_no_templates_json(tmp_path: pytest.TempPathFactory) -> None:
    """--no-templates --json: JSON output has files_created without template files."""
    result = runner.invoke(
        app,
        [
            "--json",
            "project",
            "init",
            "my-project",
            "--path",
            str(tmp_path),
            "--no-templates",
        ],
    )
    assert result.exit_code == 0, f"stdout: {result.stdout}"

    output = _strip_ansi(result.stdout)
    data = json.loads(output)

    assert data["project"] == "my-project"
    assert isinstance(data["files_created"], list)

    # Template files must NOT appear in files_created
    assert "evaluator.py" not in data["files_created"]
    assert "initial_program.py" not in data["files_created"]
    assert "config.yaml" not in data["files_created"]

    # Core entries must still be present
    assert ".revolver/" in data["files_created"]
    assert "project.yaml" in data["files_created"]


# ── S13-13: config.yaml template served by the evolution backend ─────────────

# Golden copy of the OpenEvolve `config.yaml` scaffold served by
# OpenEvolveBackend.config_template() (ADR-007, sprint-013 S13-13).
# Rewritten in S16a (A6/#318) to OpenEvolve-schema-correct keys so a
# freshly-scaffolded project validates clean (zero validator warnings):
# `num_iterations` -> `max_iterations`, top-level `population_size` moved
# under a commented-out `database:` section (OE default 1000 preserved).
# S18 (U13/#367, FR-RUN-054): evaluation section gains the on_timeout /
# timeout_score timed-out-instance policy (default penalize).
_EXPECTED_CONFIG_TEMPLATE = """\
# OpenEvolve configuration — edit to match your problem.
#
# See OpenEvolve documentation for all available options.
# Revolver passes this file to OpenEvolve via --config.
# Keys here use OpenEvolve's own schema; a freshly-scaffolded project
# validates clean (zero warnings) at `problem version create`.

# Number of evolutionary iterations (generations).
max_iterations: 10

# LLM sampling settings.
llm:
  temperature: 0.8
  max_tokens: 4096

# MAP-Elites database settings.
# Population size — number of candidate programs kept in the archive.
# OpenEvolve defaults to 1000; uncomment to shrink it for quick experiments.
# feature_dimensions / feature_bins are the MAP-Elites feature axes and the
# per-axis bin counts (the archive grid); uncomment to customise the grid.
# database:
#   population_size: 10
#   feature_dimensions: ["complexity", "diversity"]
#   feature_bins: 10

# Evaluation settings (Revolver-specific; not part of the OpenEvolve schema).
evaluation:
  timeout_per_instance: 30  # seconds
  # Timed-out instance policy (v0.18): "penalize" counts the instance at
  # timeout_score in the fitness mean; "drop" excludes it (pre-0.18
  # survivor-mean). Note: with a negative timeout_score floor, lower
  # scores are the penalty — mind negative-is-good metrics.
  on_timeout: penalize
  timeout_score: 0.0
"""


@pytest.mark.integration
def test_init_config_template_served_by_backend(tmp_path: pytest.TempPathFactory) -> None:
    """config.yaml comes from the backend and is byte-identical to pre-S13.

    Validates: FR-PRJ-005, ADR-007 (S13-13 template ownership move).
    """
    from revolver.infra.backends.base import get_backend

    result = runner.invoke(app, ["project", "init", "tpl-project", "--path", str(tmp_path)])
    assert result.exit_code == 0, f"stdout: {result.stdout}"

    content = (tmp_path / "config.yaml").read_text(encoding="utf-8")

    # Served by the OpenEvolve backend (no core-owned template left)
    assert content == get_backend("openevolve").config_template()

    # Byte-identical to the historical template
    assert content == _EXPECTED_CONFIG_TEMPLATE


# ── S14-15: --backend selects the config.yaml template (ADR-007) ─────────────


@pytest.mark.integration
def test_project_init_backend_shinka_template(tmp_path: pytest.TempPathFactory) -> None:
    """project init --backend shinka scaffolds the Shinka-shaped config.yaml.

    Validates: FR-PRJ-005, ADR-007 (S14-15: template served by the
    selected backend — no shinka install required, the template is
    static data on the adapter).
    """
    from revolver.infra.backends.base import get_backend

    result = runner.invoke(
        app,
        ["project", "init", "shinka-project", "--path", str(tmp_path), "--backend", "shinka"],
    )
    assert result.exit_code == 0, f"stdout: {result.stdout}"

    content = (tmp_path / "config.yaml").read_text(encoding="utf-8")

    # Served by the Shinka backend
    assert content == get_backend("shinka").config_template()

    # Shinka-shaped scaffold: the three engine sections are present, and
    # the template parses as YAML with matching top-level keys.
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict)
    for section in ("evo_config", "db_config", "job_config"):
        assert section in parsed, f"missing section {section}"

    # No OpenEvolve-shaped keys leak into the Shinka scaffold
    assert "num_iterations" not in parsed
    assert "population_size" not in parsed

    # Other templates are backend-independent and still written
    assert (tmp_path / "initial_program.py").is_file()
    assert (tmp_path / "evaluator.py").is_file()


@pytest.mark.integration
def test_project_init_backend_default_is_openevolve(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Without --backend, project init keeps the OpenEvolve template."""
    from revolver.infra.backends.base import get_backend

    result = runner.invoke(app, ["project", "init", "default-project", "--path", str(tmp_path)])
    assert result.exit_code == 0, f"stdout: {result.stdout}"

    content = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert content == get_backend("openevolve").config_template()


# ── S16a-15 (A6/#318): the OE scaffold validates clean (zero warnings) ───────


def _has_dacite_and_openevolve() -> bool:
    """Check that dacite and openevolve are installed (validator no-ops without them)."""
    try:
        import dacite  # noqa: F401
        from openevolve.config import Config  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(
    not _has_dacite_and_openevolve(),
    reason="dacite/openevolve not installed — validator is a no-op, test would be vacuous",
)
def test_oe_scaffold_zero_warnings(tmp_path) -> None:
    """A freshly-scaffolded OpenEvolve project validates clean (A6/#318).

    Drives a real ``project init --backend openevolve`` followed by
    ``problem version create --backend openevolve`` on the untouched
    scaffold and asserts the backend config validator emits **zero**
    warnings — the official template must not warn about itself.

    Requires openevolve + dacite to be importable; otherwise
    ``validate_oe_config`` returns ``[]`` regardless of the template and
    the assertion would be vacuous, so the test auto-skips.

    Validates: FR-PRJ-005, ADR-007 (S16a-11/S16a-15).
    """
    from revolver.core.problem import create_version

    project_dir = tmp_path / "scaffold-demo"
    result = runner.invoke(
        app,
        [
            "project",
            "init",
            "scaffold-demo",
            "--path",
            str(project_dir),
            "--backend",
            "openevolve",
        ],
    )
    assert result.exit_code == 0, f"init failed: {_get_all_output(result)}"

    # Sanity: the scaffold is the untouched OpenEvolve template.
    from revolver.infra.backends.base import get_backend

    content = (project_dir / "config.yaml").read_text(encoding="utf-8")
    assert content == get_backend("openevolve").config_template()

    _pv, config_warnings = create_version(
        tag="v1.0", project_root=project_dir, backend="openevolve"
    )
    assert config_warnings == [], (
        f"Fresh OpenEvolve scaffold must validate clean, got: {config_warnings}"
    )


@pytest.mark.integration
def test_project_init_backend_unknown_fails_fast(tmp_path: pytest.TempPathFactory) -> None:
    """Unknown --backend: exit 1 and no project structure is created.

    The backend name is resolved before any side effect, so a typo must
    not leave a half-initialized project behind.
    """
    target = tmp_path / "sub"  # does not exist yet
    result = runner.invoke(
        app,
        ["project", "init", "bad-project", "--path", str(target), "--backend", "nope"],
    )

    assert result.exit_code == 1
    output = _get_all_output(result)
    assert "Unknown backend 'nope'" in output

    # Fail fast: nothing was created
    assert not (target / ".revolver").exists()
    assert not (target / "project.yaml").exists()
