"""L2 integration tests for Sprint 009a features.

Tests cover:
- build_config checkpoint_interval guard
- validate_oe_config namespace detection
- find_latest_checkpoint directory scanning
- Resume CLI flags (--iterations, --temperature, --parallel)
- Dry-run resolved config display

Traceable to: sprint-009a.md Integration Tests table.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.infra.backends.openevolve import (
    build_config,
    find_latest_checkpoint,
    validate_oe_config,
)
from revolver.models.llm import LLMEntry

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


def _make_llm(**kwargs: object) -> LLMEntry:
    """Create a test LLMEntry with sensible defaults."""
    from datetime import UTC, datetime

    defaults: dict[str, object] = {
        "name": "test",
        "source": "local",
        "provider": "ollama",
        "model": "test:latest",
        "base_url": "http://localhost:11434/v1",
        "registered_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return LLMEntry(**defaults)  # type: ignore[arg-type]


# ── build_config checkpoint_interval guard ────────────────────────────────────


@pytest.mark.integration
def test_build_config_checkpoint_interval_override() -> None:
    """checkpoint_interval absent + iterations=5 -> override to 5."""
    llm = _make_llm()
    config = build_config(
        problem_config=None,
        llm=llm,
        iterations=5,
    )
    # OE default is 100, which exceeds 5 iterations.
    # The guard should override checkpoint_interval to 5.
    assert config["checkpoint_interval"] == 5


@pytest.mark.integration
def test_build_config_checkpoint_interval_gt_iterations() -> None:
    """checkpoint_interval=50 + iterations=10 -> override to 10."""
    llm = _make_llm()
    config = build_config(
        problem_config=None,
        llm=llm,
        iterations=10,
        config_overrides=["checkpoint_interval=50"],
    )
    assert config["checkpoint_interval"] == 10


@pytest.mark.integration
def test_build_config_checkpoint_interval_ok() -> None:
    """checkpoint_interval=10 + iterations=50 -> kept as 10."""
    llm = _make_llm()
    config = build_config(
        problem_config=None,
        llm=llm,
        iterations=50,
        config_overrides=["checkpoint_interval=10"],
    )
    assert config["checkpoint_interval"] == 10


# ── validate_oe_config ────────────────────────────────────────────────────────


def _has_dacite_and_openevolve() -> bool:
    """Check if dacite and openevolve are installed (required for config validation)."""
    try:
        import dacite  # noqa: F401
        from openevolve.config import Config  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _has_dacite_and_openevolve(), reason="dacite/openevolve not installed")
def test_validate_oe_config_misplaced_num_islands() -> None:
    """Top-level num_islands -> warning about database.num_islands."""
    config = {
        "max_iterations": 100,
        "num_islands": 3,
    }
    warnings = validate_oe_config(config)
    # Should produce at least one warning mentioning database.num_islands
    assert any("database.num_islands" in w for w in warnings), (
        f"Expected warning about database.num_islands, got: {warnings}"
    )


@pytest.mark.integration
@pytest.mark.skipif(not _has_dacite_and_openevolve(), reason="dacite/openevolve not installed")
def test_validate_oe_config_valid() -> None:
    """Correct database: namespace -> empty list."""
    config = {
        "max_iterations": 100,
        "database": {
            "num_islands": 3,
        },
    }
    warnings = validate_oe_config(config)
    assert warnings == []


# ── S10-01: Revolver key filtering ───────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.skipif(not _has_dacite_and_openevolve(), reason="dacite/openevolve not installed")
def test_validate_oe_config_initial_program_filtered() -> None:
    """initial_program key is silently filtered — no warnings emitted."""
    config = {
        "max_iterations": 100,
        "initial_program": "solve.py",
    }
    warnings = validate_oe_config(config)
    assert warnings == [], f"Expected no warnings, got: {warnings}"


@pytest.mark.integration
@pytest.mark.skipif(not _has_dacite_and_openevolve(), reason="dacite/openevolve not installed")
def test_validate_oe_config_timeout_per_instance_filtered() -> None:
    """timeout_per_instance key is silently filtered — no warnings emitted."""
    config = {
        "max_iterations": 100,
        "timeout_per_instance": 30,
    }
    warnings = validate_oe_config(config)
    assert warnings == [], f"Expected no warnings, got: {warnings}"


@pytest.mark.integration
@pytest.mark.skipif(not _has_dacite_and_openevolve(), reason="dacite/openevolve not installed")
def test_validate_oe_config_num_generations_deprecated() -> None:
    """num_generations key emits a deprecation notice, not an 'Unknown key' warning."""
    config = {
        "num_generations": 50,
    }
    warnings = validate_oe_config(config)
    # Should have exactly one warning: the deprecation notice
    assert len(warnings) == 1, f"Expected 1 warning, got {len(warnings)}: {warnings}"
    assert "Deprecation" in warnings[0]
    assert "num_generations" in warnings[0]
    assert "max_iterations" in warnings[0]
    # Must NOT contain "Unknown" — it should be a deprecation, not an unknown key error
    assert "Unknown" not in warnings[0], f"Got unexpected 'Unknown key' warning: {warnings[0]}"


@pytest.mark.integration
@pytest.mark.skipif(not _has_dacite_and_openevolve(), reason="dacite/openevolve not installed")
def test_validate_oe_config_num_generations_with_unknown_key() -> None:
    """num_generations + truly unknown key -> deprecation notice AND unknown key warning."""
    config = {
        "num_generations": 50,
        "bogus_key": True,
    }
    warnings = validate_oe_config(config)
    # Should have exactly two warnings: deprecation + unknown key
    assert len(warnings) == 2, f"Expected 2 warnings, got {len(warnings)}: {warnings}"
    # First warning is the deprecation notice
    assert "Deprecation" in warnings[0]
    assert "num_generations" in warnings[0]
    # Second warning is the unknown key
    assert "Unknown" in warnings[1]
    assert "bogus_key" in warnings[1]


# ── find_latest_checkpoint ────────────────────────────────────────────────────


@pytest.mark.integration
def test_find_latest_checkpoint_multiple(tmp_path: Path) -> None:
    """Multiple checkpoint_N dirs -> returns highest N."""
    checkpoints_dir = tmp_path / "oe-output" / "checkpoints"
    checkpoints_dir.mkdir(parents=True)

    # Create several checkpoint directories
    for n in (5, 10, 3, 20, 15):
        (checkpoints_dir / f"checkpoint_{n}").mkdir()

    result = find_latest_checkpoint(tmp_path)
    assert result is not None
    assert result.name == "checkpoint_20"


@pytest.mark.integration
def test_find_latest_checkpoint_none(tmp_path: Path) -> None:
    """No checkpoints -> returns None."""
    # Empty run dir, no oe-output/checkpoints
    result = find_latest_checkpoint(tmp_path)
    assert result is None


# ── Resume CLI flags ──────────────────────────────────────────────────────────


@pytest.mark.integration
def test_resume_cli_iterations_flag() -> None:
    """--iterations visible in --help for resume."""
    result = runner.invoke(app, ["run", "resume", "--help"])
    output = _get_all_output(result)
    assert "--iterations" in output


@pytest.mark.integration
def test_resume_cli_temperature_flag() -> None:
    """--temperature visible in --help for resume."""
    result = runner.invoke(app, ["run", "resume", "--help"])
    output = _get_all_output(result)
    assert "--temperature" in output


@pytest.mark.integration
def test_resume_cli_parallel_flag() -> None:
    """--parallel visible in --help for resume."""
    result = runner.invoke(app, ["run", "resume", "--help"])
    output = _get_all_output(result)
    assert "--parallel" in output


# ── Dry-run resolved config ──────────────────────────────────────────────────


_FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with init_project and return the root."""
    from revolver.core.project import init_project

    init_project(tmp_path, "test-project")
    return tmp_path


def _create_problem_version(project_root: Path, tag: str) -> None:
    """Create a problem version in the project."""
    shutil.copy2(_FIXTURES / "evaluator_simple.py", project_root / "evaluator.py")
    shutil.copy2(
        _FIXTURES / "initial_program_simple.py",
        project_root / "initial_program.py",
    )
    shutil.copy2(_FIXTURES / "config_simple.yaml", project_root / "config.yaml")

    from revolver.core.problem import create_version

    create_version(tag=tag, message=f"Version {tag}", project_root=project_root)


def _register_dataset(
    project_root: Path,
    dataset_dir: Path,
    name: str = "train-small",
    split: str | None = "train",
    compatible_with: list[str] | None = None,
) -> None:
    """Register a dataset in the project."""
    from revolver.core.dataset import register_dataset

    register_dataset(
        project_root=project_root,
        name=name,
        path=dataset_dir,
        split=split,
        compatible_with=compatible_with,
    )


def _register_llm(
    global_db_path: Path,
    name: str = "test-llm",
    model: str = "gpt-4",
    source: str = "remote",
    base_url: str | None = "http://localhost:11434/v1",
) -> None:
    """Register an LLM in the global database."""
    from datetime import UTC, datetime

    from revolver.infra.db import get_global_db_at

    conn = get_global_db_at(global_db_path)
    try:
        conn.execute(
            "INSERT INTO llms (name, provider, model, source, base_url, "
            "api_key_env, input_cost_per_mtok, output_cost_per_mtok, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                "openai",
                model,
                source,
                base_url,
                None,
                None,
                None,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def dataset_dir(tmp_path: Path) -> Path:
    """Create a directory with 3 JSON instance files."""
    import json

    data_dir = tmp_path / "data" / "instances"
    data_dir.mkdir(parents=True)
    for i in range(1, 4):
        (data_dir / f"instance_{i:03d}.json").write_text(
            json.dumps({"id": i, "value": i * 10}),
            encoding="utf-8",
        )
    return data_dir


@pytest.fixture()
def global_db_path(tmp_path: Path) -> Path:
    """Return the path for a temporary global database."""
    from revolver.infra.db import get_global_db_at

    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    conn.close()
    return db_path


@pytest.fixture()
def project_with_prereqs(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> dict[str, Path]:
    """Set up a project with problem version, LLM, and dataset for run tests."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(tmp_project, dataset_dir, compatible_with=["v1.0"])
    _register_llm(global_db_path, base_url="http://localhost:11434/v1")
    return {
        "root": tmp_project,
        "dataset_dir": dataset_dir,
        "global_db_path": global_db_path,
    }


# Counter for unique run/solution IDs in tests
_id_counter = 0


def _next_ids() -> tuple[str, str]:
    """Generate unique run and solution IDs for tests."""
    global _id_counter
    _id_counter += 1
    return (
        f"run-20260327-{_id_counter:06d}",
        f"sol-20260327-{_id_counter:06d}",
    )


def _invoke_with_mocks(
    args: list[str],
    cwd: Path,
    global_db_path: Path,
    mock_runner: MagicMock | None = None,
    mock_proxy: MagicMock | None = None,
) -> object:
    """Invoke CLI with mocked OpenEvolveRunner, TokenCountingProxy, and global DB."""
    from revolver.infra.backends.openevolve import RunOutput
    from revolver.infra.db import get_global_db_at
    from revolver.infra.token_proxy import TokenUsage as ProxyTokenUsage

    if mock_runner is None:
        mock_runner_instance = MagicMock()
        mock_runner_instance.run.return_value = RunOutput(
            best_score=0.95,
            best_program="def solve(): pass",
            output_dir=None,
        )
        mock_runner = mock_runner_instance
    if mock_proxy is None:
        mock_proxy_instance = MagicMock()
        mock_proxy_instance.start.return_value = "http://127.0.0.1:9999"
        mock_proxy_instance.stop.return_value = ProxyTokenUsage(
            prompt_tokens=0,
            completion_tokens=0,
        )
        mock_proxy = mock_proxy_instance

    mock_runner_cls = MagicMock(return_value=mock_runner)
    mock_proxy_cls = MagicMock(return_value=mock_proxy)

    run_id, sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=cwd),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=run_id),
        patch("revolver.core.run.generate_solution_id", return_value=sol_id),
    ):
        return runner.invoke(app, args, catch_exceptions=False)


@pytest.mark.integration
def test_run_dry_run_shows_resolved_config(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Dry-run output contains key OE params."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--dry-run",
            "--iterations",
            "100",
            "--temperature",
            "0.8",
            "--parallel",
            "4",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"  # type: ignore[union-attr]
    assert "dry-run" in output.lower()

    # Verify resolved config section shows the key parameters
    assert "Resolved openevolve config" in output  # backend-aware header (S13 PR-C, FR-RUN-047)
    assert "iterations" in output.lower()
    assert "temperature" in output.lower()
    assert "parallel_evaluations" in output.lower()
