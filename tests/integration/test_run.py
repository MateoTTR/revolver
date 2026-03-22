"""L2 integration tests for ``revolver run`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner with real
SQLite databases (project + global) in ``tmp_path``. OpenEvolveRunner
and TokenCountingProxy are mocked at the infra boundary.

Traceable to: val-integration-tests.md section 2.5 (13 scenarios).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.project import init_project
from revolver.infra.db import (
    get_global_db_at,
    get_project_db,
)
from revolver.infra.openevolve import RunOutput
from revolver.infra.store import REVOLVER_DIR
from revolver.infra.token_proxy import TokenUsage as ProxyTokenUsage

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Counter for unique run/solution IDs in tests
_id_counter = 0


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


def _parse_json_output(result: object) -> object:
    """Extract and parse the first JSON object/array from CLI output.

    CliRunner mixes stdout and stderr, so we find the JSON portion
    by looking for the first '{' or '[' and parsing from there.
    """
    output = getattr(result, "output", "")
    # Find the start of JSON (first { or [)
    for i, ch in enumerate(output):
        if ch in ("{", "["):
            # Try to parse from this position
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(output, i)
            return obj
    msg = f"No JSON found in output: {output[:200]}"
    raise ValueError(msg)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with init_project and return the root."""
    init_project(tmp_path, "test-project")
    return tmp_path


@pytest.fixture()
def dataset_dir(tmp_path: Path) -> Path:
    """Create a directory with 3 JSON instance files for dataset tests."""
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
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    conn.close()
    return db_path


def _create_problem_version(project_root: Path, tag: str) -> None:
    """Create a problem version in the project."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    shutil.copy2(fixtures_dir / "evaluator_simple.py", project_root / "evaluator.py")
    shutil.copy2(
        fixtures_dir / "initial_program_simple.py",
        project_root / "initial_program.py",
    )
    shutil.copy2(fixtures_dir / "config_simple.yaml", project_root / "config.yaml")

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
    input_cost: float | None = None,
    output_cost: float | None = None,
) -> None:
    """Register an LLM in the global database."""
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
                input_cost,
                output_cost,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _make_mock_runner() -> MagicMock:
    """Create a mock OpenEvolveRunner that returns a successful run."""
    mock_runner_instance = MagicMock()
    mock_runner_instance.run.return_value = RunOutput(
        best_score=0.95,
        best_program="def solve(): pass",
        output_dir=None,
    )
    return mock_runner_instance


def _make_mock_proxy(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> MagicMock:
    """Create a mock TokenCountingProxy."""
    mock_proxy = MagicMock()
    mock_proxy.start.return_value = "http://127.0.0.1:9999"
    mock_proxy.stop.return_value = ProxyTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return mock_proxy


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


@pytest.fixture()
def mock_global_db(
    global_db_path: Path,
) -> Generator[Path, None, None]:
    """Patch get_global_db so the CLI opens connections to our temp DB."""
    with patch(
        "revolver.core.run.get_global_db",
        side_effect=lambda: get_global_db_at(global_db_path),
    ):
        yield global_db_path


def _invoke_with_cwd(args: list[str], cwd: Path) -> object:
    """Invoke the CLI with a patched working directory."""
    with patch("pathlib.Path.cwd", return_value=cwd):
        return runner.invoke(app, args, catch_exceptions=False)


def _next_ids() -> tuple[str, str]:
    """Generate unique run and solution IDs for tests."""
    global _id_counter
    _id_counter += 1
    return (
        f"run-20260315-{_id_counter:06d}",
        f"sol-20260315-{_id_counter:06d}",
    )


def _invoke_with_mocks(
    args: list[str],
    cwd: Path,
    global_db_path: Path,
    mock_runner: MagicMock | None = None,
    mock_proxy: MagicMock | None = None,
) -> object:
    """Invoke CLI with mocked OpenEvolveRunner, TokenCountingProxy, and global DB."""
    if mock_runner is None:
        mock_runner = _make_mock_runner()
    if mock_proxy is None:
        mock_proxy = _make_mock_proxy()

    mock_runner_cls = MagicMock(return_value=mock_runner)
    mock_proxy_cls = MagicMock(return_value=mock_proxy)

    run_id, sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=cwd),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.core.run.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=run_id),
        patch("revolver.core.run.generate_solution_id", return_value=sol_id),
    ):
        return runner.invoke(app, args, catch_exceptions=False)


# ── Test 1: run — valid config, mocked OpenEvolve (FR-RUN-001, 005..010) ───


@pytest.mark.integration
def test_run_valid_config(project_with_prereqs: dict[str, Path]) -> None:
    """Valid config, mocked OpenEvolve: run dir, DB entries, lineage, env vars."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        ["run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small"],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify DB entries: run record exists
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT * FROM runs WHERE status = 'completed'")
        runs = cursor.fetchall()
        assert len(runs) >= 1, "Expected at least 1 completed run in DB"

        # Verify solution record exists
        cursor = conn.execute("SELECT * FROM solutions")
        solutions = cursor.fetchall()
        assert len(solutions) >= 1, "Expected at least 1 solution in DB"
    finally:
        conn.close()

    # Verify run dir was created
    runs_dir = root / REVOLVER_DIR / "runs"
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("run-")]
    assert len(run_dirs) >= 1, "Expected at least 1 run directory"

    # Verify output contains run info
    assert "run-" in output
    assert "v1.0" in output


# ── Test 2: run --alias (FR-RUN-012) ────────────────────────────────────────


@pytest.mark.integration
def test_run_with_alias(project_with_prereqs: dict[str, Path]) -> None:
    """Solution alias set on completion."""
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
            "--alias",
            "my-best-solution",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify alias in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT alias FROM solutions WHERE alias IS NOT NULL")
        row = cursor.fetchone()
        assert row is not None, "Expected solution with alias"
        assert row[0] == "my-best-solution"
    finally:
        conn.close()

    assert "my-best-solution" in output


# ── Test 3: run --dry-run (FR-RUN-023) ─────────────────────────────────────


@pytest.mark.integration
def test_run_dry_run(project_with_prereqs: dict[str, Path]) -> None:
    """Config displayed, no run launched."""
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
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "dry-run" in output.lower()

    # Verify NO run was created in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM runs")
        count = cursor.fetchone()[0]
        assert count == 0, f"Expected 0 runs in DB, got {count}"
    finally:
        conn.close()


# ── Test 4: run — unknown LLM name → exit code 1 (FR-RUN-001) ──────────────


@pytest.mark.integration
def test_run_unknown_llm(project_with_prereqs: dict[str, Path]) -> None:
    """Unknown LLM name results in exit code 1."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "nonexistent-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"
    output = _get_all_output(result)
    assert "not found" in output.lower()


# ── Test 5: run — dataset integrity failure → exit code 2 (FR-RUN-004) ─────


@pytest.mark.integration
def test_run_dataset_integrity_failure(project_with_prereqs: dict[str, Path]) -> None:
    """Dataset integrity failure results in exit code 2."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]
    dataset_dir = project_with_prereqs["dataset_dir"]

    # Tamper with an instance file to cause integrity mismatch
    tampered_file = dataset_dir / "instance_001.json"
    tampered_file.write_text(
        json.dumps({"id": 1, "value": 9999, "tampered": True}),
        encoding="utf-8",
    )

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"
    output = _get_all_output(result)
    assert "integrity" in output.lower()


# ── Test 6: run — dataset split=eval → warning on stderr (FR-RUN-002) ──────


@pytest.mark.integration
def test_run_dataset_split_eval_warning(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> None:
    """Dataset split=eval produces a warning on stderr, run proceeds."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(
        tmp_project, dataset_dir, name="eval-ds", split="eval", compatible_with=["v1.0"]
    )
    _register_llm(global_db_path, base_url="http://localhost:11434/v1")

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "eval-ds",
        ],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "warning" in output.lower()
    assert "eval" in output.lower()


# ── Test 7: run — dataset incompatible with version → warning (FR-RUN-003) ──


@pytest.mark.integration
def test_run_dataset_incompatible_warning(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> None:
    """Dataset incompatible with version produces a warning on stderr."""
    _create_problem_version(tmp_project, "v1.0")
    # Insert a v2.0 problem version directly in DB (skip file copy/hash
    # to avoid duplicate hash error from identical fixtures)
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
            ("v2.0", "hash-v2-fake", "Version v2.0", datetime.now(UTC).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    # Register dataset compatible with v2.0 (not v1.0)
    _register_dataset(tmp_project, dataset_dir, name="incompat-ds", compatible_with=["v2.0"])
    _register_llm(global_db_path, base_url="http://localhost:11434/v1")

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "incompat-ds",
        ],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "warning" in output.lower()
    assert "compatible" in output.lower()


# ── Test 8: run — completion with tokens (FR-RUN-028, 029) ─────────────────


@pytest.mark.integration
def test_run_with_token_usage(project_with_prereqs: dict[str, Path]) -> None:
    """Token usage displayed and stored in DB on completion."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy(prompt_tokens=1500, completion_tokens=3000)

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
        mock_runner=mock_runner,
        mock_proxy=mock_proxy,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify tokens displayed
    assert "1500" in output
    assert "3000" in output

    # Verify tokens stored in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT prompt_tokens, completion_tokens FROM runs")
        row = cursor.fetchone()
        assert row is not None, "Expected run with tokens in DB"
        assert row[0] == 1500
        assert row[1] == 3000
    finally:
        conn.close()


# ── Test 9: run — LLM has pricing → estimated cost displayed (FR-RUN-030) ──


@pytest.mark.integration
def test_run_with_pricing(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> None:
    """LLM with pricing: estimated cost displayed."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(tmp_project, dataset_dir, compatible_with=["v1.0"])
    _register_llm(
        global_db_path,
        name="priced-llm",
        base_url="http://localhost:11434/v1",
        input_cost=3.0,
        output_cost=15.0,
    )

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy(prompt_tokens=1000, completion_tokens=2000)

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "priced-llm",
            "--dataset",
            "train-small",
        ],
        cwd=tmp_project,
        global_db_path=global_db_path,
        mock_runner=mock_runner,
        mock_proxy=mock_proxy,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify estimated cost is displayed
    # Expected: (1000 * 3.0 + 2000 * 15.0) / 1_000_000 = 0.033
    assert "cost" in output.lower() or "$" in output


# ── Test 10: run — post-run eval on train set (FR-RUN-019, 020) ─────────────


@pytest.mark.integration
def test_run_post_run_evaluation(project_with_prereqs: dict[str, Path]) -> None:
    """Post-run evaluation invoked for rank-1 program."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy()
    mock_runner_cls = MagicMock(return_value=mock_runner)
    mock_proxy_cls = MagicMock(return_value=mock_proxy)
    eval_run_id, eval_sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.core.run.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation") as mock_eval,
        patch("revolver.core.run.generate_run_id", return_value=eval_run_id),
        patch("revolver.core.run.generate_solution_id", return_value=eval_sol_id),
    ):
        result = runner.invoke(
            app,
            [
                "run",
                "--version",
                "v1.0",
                "--llm",
                "test-llm",
                "--dataset",
                "train-small",
            ],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify _post_run_evaluation was called
    mock_eval.assert_called_once()
    call_kwargs = mock_eval.call_args
    # Should be called with proj_conn, run_id, solution_id, etc.
    assert call_kwargs is not None


# ── Test 11: run list — after 2 runs, both listed, filterable (FR-RUN-021) ──


@pytest.mark.integration
def test_run_list_after_two_runs(project_with_prereqs: dict[str, Path]) -> None:
    """After 2 runs, both listed with status, filterable."""
    root = project_with_prereqs["root"]

    # Insert 2 runs directly in DB to avoid timestamp collision
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        for i, rid in enumerate(["run-20260315-100001", "run-20260315-100002"]):
            conn.execute(
                "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
                "problem_hash, dataset_hash, llm_model, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    "v1.0",
                    "test-llm",
                    "train-small",
                    10,
                    f"hash-{i}",
                    f"dhash-{i}",
                    "gpt-4",
                    "completed",
                    f"2026-03-15T10:00:0{i + 1}",
                ),
            )
        conn.commit()
    finally:
        conn.close()

    # List all runs
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(app, ["--json", "run", "list"], catch_exceptions=False)

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert len(data) >= 2, f"Expected at least 2 runs, got {len(data)}"

    # Test filter by version
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "list", "--version", "v1.0"],
            catch_exceptions=False,
        )

    data = _parse_json_output(result)
    assert len(data) >= 2
    for run_item in data:
        assert run_item["problem_version"] == "v1.0"

    # Test filter by status
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "list", "--status", "completed"],
            catch_exceptions=False,
        )

    data = _parse_json_output(result)
    assert len(data) >= 2
    for run_item in data:
        assert run_item["status"] == "completed"


# ── Test 12: run info — full details (FR-RUN-022) ──────────────────────────


@pytest.mark.integration
def test_run_info_full_details(project_with_prereqs: dict[str, Path]) -> None:
    """Full details: lineage, tokens, solution, stored programs."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy(prompt_tokens=500, completion_tokens=1000)

    # Launch a run first
    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
        mock_runner=mock_runner,
        mock_proxy=mock_proxy,
    )
    assert result.exit_code == 0
    run_data = _parse_json_output(result)
    run_id = run_data["run_id"]

    # Now get info
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
    ):
        result = runner.invoke(
            app,
            ["--json", "run", "info", run_id],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    info = _parse_json_output(result)
    assert info["run_id"] == run_id
    assert info["problem_version"] == "v1.0"
    assert info["llm"] == "test-llm"
    assert info["dataset"] == "train-small"
    assert info["status"] == "completed"

    # Verify lineage hashes present
    assert "problem_hash" in info
    assert "dataset_hash" in info
    assert "llm_model" in info

    # Verify token usage
    assert info["token_usage"] is not None
    assert info["token_usage"]["prompt_tokens"] == 500
    assert info["token_usage"]["completion_tokens"] == 1000

    # Verify solutions
    assert len(info["solutions"]) >= 1
    assert info["solutions"][0]["rank"] == 1


# ── Test 13: run resume — existing checkpoint (FR-RUN-013, 024) ─────────────


@pytest.mark.integration
def test_run_resume(project_with_prereqs: dict[str, Path]) -> None:
    """New run from parent, wrapper copied."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Launch initial run
    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0
    parent_data = _parse_json_output(result)
    parent_run_id = parent_data["run_id"]

    # Create a checkpoint dir in the parent run to simulate a resumable run
    parent_run_dir = root / REVOLVER_DIR / "runs" / parent_run_id
    checkpoint_dir = parent_run_dir / "oe-checkpoint"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "checkpoint.pkl").write_text("fake checkpoint data")

    # Resume the run with unique IDs
    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy()
    mock_runner_cls = MagicMock(return_value=mock_runner)
    mock_proxy_cls = MagicMock(return_value=mock_proxy)
    resume_run_id, resume_sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.core.run.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=resume_run_id),
        patch("revolver.core.run.generate_solution_id", return_value=resume_sol_id),
    ):
        result = runner.invoke(
            app,
            ["--json", "run", "resume", "--run", parent_run_id],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    resume_data = _parse_json_output(result)
    new_run_id = resume_data["run_id"]

    # Verify new run is different from parent
    assert new_run_id != parent_run_id

    # Verify resumed_from field
    assert resume_data.get("resumed_from") == parent_run_id

    # Verify DB has both runs
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM runs")
        count = cursor.fetchone()[0]
        assert count == 2, f"Expected 2 runs in DB, got {count}"

        # Verify resumed_from in DB
        cursor = conn.execute("SELECT resumed_from FROM runs WHERE id = ?", (new_run_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == parent_run_id
    finally:
        conn.close()

    # Verify wrapper was copied to new run dir
    new_run_dir = root / REVOLVER_DIR / "runs" / new_run_id
    assert new_run_dir.exists()


# ── Test 14: run info shows valid_iterations ─────────────────────────────


@pytest.mark.integration
def test_run_info_shows_valid_iterations(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run info shows valid_iterations when populated in DB."""
    root = project_with_prereqs["root"]

    # Insert a run with valid_iterations directly in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, created_at, "
            "valid_iterations) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-vi-001",
                "v1.0",
                "test-llm",
                "train-small",
                100,
                "hash-vi",
                "dhash-vi",
                "gpt-4",
                "completed",
                "2026-03-20T10:00:00",
                85,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Get info via CLI
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "info", "run-vi-001"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    info = _parse_json_output(result)
    assert info["run_id"] == "run-vi-001"
    assert info["valid_iterations"] == 85
    assert info["iterations"] == 100


# ── Test 15: run list shows valid column ─────────────────────────────────


@pytest.mark.integration
def test_run_list_shows_valid_iterations(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run list includes valid_iterations in JSON output."""
    root = project_with_prereqs["root"]

    # Insert two runs: one with valid_iterations, one without
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, created_at, "
            "valid_iterations) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-vl-001",
                "v1.0",
                "test-llm",
                "train-small",
                50,
                "hash-vl1",
                "dhash-vl1",
                "gpt-4",
                "completed",
                "2026-03-20T11:00:00",
                42,
            ),
        )
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-vl-002",
                "v1.0",
                "test-llm",
                "train-small",
                50,
                "hash-vl2",
                "dhash-vl2",
                "gpt-4",
                "completed",
                "2026-03-20T11:00:01",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # List runs via CLI
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "list"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    by_id = {r["run_id"]: r for r in data}

    assert by_id["run-vl-001"]["valid_iterations"] == 42
    assert by_id["run-vl-002"]["valid_iterations"] is None


# ── run delete --all tests (S8a-04, S8a-05) ────────────────────────────────


def _insert_run_directly(project_root: Path, run_id: str) -> None:
    """Insert a minimal run row directly into the project database."""
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                "v1.0",
                "test-llm",
                "train-small",
                10,
                f"hash-{run_id}",
                f"dhash-{run_id}",
                "gpt-4",
                "completed",
                "2026-03-20T10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_run_delete_all(project_with_prereqs: dict[str, Path]) -> None:
    """run delete --all --force removes all runs; run list returns empty."""
    root = project_with_prereqs["root"]

    # Insert 3 runs directly
    for i in range(1, 4):
        _insert_run_directly(root, f"run-del-all-{i:03d}")

    # Delete all with --force
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "delete", "--all", "--force"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert data["runs_deleted"] == 3
    assert data["status"] == "deleted"

    # Verify run list is now empty
    with patch("pathlib.Path.cwd", return_value=root):
        list_result = runner.invoke(
            app,
            ["--json", "run", "list"],
            catch_exceptions=False,
        )

    list_data = _parse_json_output(list_result)
    assert list_data == []


@pytest.mark.integration
def test_run_delete_all_no_force(project_with_prereqs: dict[str, Path]) -> None:
    """run delete --all without --force in JSON mode raises ValidationError."""
    root = project_with_prereqs["root"]

    # Insert a run so there is something to delete
    _insert_run_directly(root, "run-del-nf-001")

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "delete", "--all"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "--force" in output


@pytest.mark.integration
def test_run_delete_all_empty(project_with_prereqs: dict[str, Path]) -> None:
    """run delete --all --force with no runs returns no-op."""
    root = project_with_prereqs["root"]

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "delete", "--all", "--force"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert data["status"] == "no-op"


@pytest.mark.integration
def test_run_delete_all_with_id_error(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run delete --all <run_id> is mutually exclusive — should error."""
    root = project_with_prereqs["root"]

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["run", "delete", "--all", "run-some-id", "--force"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Cannot use --all with a specific run ID" in output


# ── Test: Smart default version — single version auto-selected (S8a-10) ─────


@pytest.mark.integration
def test_run_smart_default_version(project_with_prereqs: dict[str, Path]) -> None:
    """Single version auto-selected with notice when --version omitted."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        ["run", "--llm", "test-llm", "--dataset", "train-small", "--dry-run"],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "Using version v1.0 (only version)" in output
    assert "dry-run" in output.lower()


@pytest.mark.integration
def test_run_smart_default_version_multiple_error(
    tmp_project: Path, dataset_dir: Path, global_db_path: Path
) -> None:
    """Multiple versions → error listing available versions when --version omitted."""
    _create_problem_version(tmp_project, "v1.0")
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
            ("v2.0", "fakehash-v2", "Version v2.0", "2026-03-22T10:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    _register_dataset(tmp_project, dataset_dir, compatible_with=["v1.0"])
    _register_llm(global_db_path)

    result = _invoke_with_mocks(
        ["run", "--llm", "test-llm", "--dataset", "train-small", "--dry-run"],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Multiple problem versions exist" in output
    assert "v1.0" in output
    assert "v2.0" in output
    assert "--version" in output


@pytest.mark.integration
def test_run_smart_default_version_no_versions_error(
    tmp_project: Path, dataset_dir: Path, global_db_path: Path
) -> None:
    """No problem versions → error pointing to 'problem version'."""
    _register_dataset(tmp_project, dataset_dir, compatible_with=[])
    _register_llm(global_db_path)

    result = _invoke_with_mocks(
        ["run", "--llm", "test-llm", "--dataset", "train-small", "--dry-run"],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "No problem versions found" in output
    assert "problem version" in output


@pytest.mark.integration
def test_run_smart_default_version_explicit_respected(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Explicit --version is always respected, even with smart defaults available."""
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
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # Should NOT show smart default notice when explicit
    assert "Using version" not in output
    assert "dry-run" in output.lower()


# ── Test: Smart default dataset — single train dataset auto-selected (S8a-11) ─


@pytest.mark.integration
def test_run_smart_default_dataset(project_with_prereqs: dict[str, Path]) -> None:
    """Single train dataset auto-selected with notice when --dataset omitted."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        ["run", "--version", "v1.0", "--llm", "test-llm", "--dry-run"],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "Using dataset train-small (only train dataset)" in output
    assert "dry-run" in output.lower()


@pytest.mark.integration
def test_run_smart_default_dataset_multiple_error(
    tmp_project: Path, dataset_dir: Path, global_db_path: Path
) -> None:
    """Multiple train datasets → error listing them when --dataset omitted."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(tmp_project, dataset_dir, name="train-a", split="train")
    _register_dataset(tmp_project, dataset_dir, name="train-b", split="train")
    _register_llm(global_db_path)

    result = _invoke_with_mocks(
        ["run", "--version", "v1.0", "--llm", "test-llm", "--dry-run"],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Multiple train datasets exist" in output
    assert "train-a" in output
    assert "train-b" in output
    assert "--dataset" in output


@pytest.mark.integration
def test_run_smart_default_dataset_no_train_error(
    tmp_project: Path, dataset_dir: Path, global_db_path: Path
) -> None:
    """No train datasets → error pointing to 'dataset add --split train'."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(tmp_project, dataset_dir, name="eval-set", split="eval")
    _register_llm(global_db_path)

    result = _invoke_with_mocks(
        ["run", "--version", "v1.0", "--llm", "test-llm", "--dry-run"],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "No train datasets found" in output
    assert "dataset add --split train" in output


@pytest.mark.integration
def test_run_smart_default_dataset_explicit_respected(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Explicit --dataset is always respected, even with smart defaults available."""
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
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # Should NOT show smart default notice when explicit
    assert "Using dataset" not in output
    assert "dry-run" in output.lower()


@pytest.mark.integration
def test_run_smart_default_both(project_with_prereqs: dict[str, Path]) -> None:
    """Both version and dataset auto-selected when both omitted."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        ["run", "--llm", "test-llm", "--dry-run"],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "Using version v1.0 (only version)" in output
    assert "Using dataset train-small (only train dataset)" in output
    assert "dry-run" in output.lower()
