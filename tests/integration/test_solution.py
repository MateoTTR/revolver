"""L2 integration tests for ``revolver solution`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner with real
SQLite databases in ``tmp_path``. Runs and solutions are pre-seeded
in the database as fixtures.

Traceable to: val-integration-tests.md section 2.7 (9 scenarios).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.project import init_project
from revolver.infra.db import (
    get_project_db,
    insert_run,
    insert_solution,
)
from revolver.infra.store import REVOLVER_DIR, RUNS_DIR

pytestmark = pytest.mark.integration

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


def _parse_json_output(result: object) -> object:
    """Extract and parse the first JSON object/array from CLI output."""
    output = getattr(result, "output", "")
    for i, ch in enumerate(output):
        if ch in ("{", "["):
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(output, i)
            return obj
    msg = f"No JSON found in output: {output[:200]}"
    raise ValueError(msg)


def _invoke_with_cwd(args: list[str], cwd: Path) -> object:
    """Invoke the CLI with a patched working directory."""
    with patch("pathlib.Path.cwd", return_value=cwd):
        return runner.invoke(app, args, catch_exceptions=False)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with init_project and return the root."""
    init_project(tmp_path, "test-project")
    return tmp_path


def _create_problem_version_in_db(
    project_root: Path,
    tag: str,
) -> None:
    """Insert a problem version directly into the DB and create snapshot dir."""
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO problem_versions (tag, hash, message, created_at) "
            "VALUES (?, ?, ?, ?)",
            (tag, f"hash-{tag}", f"Version {tag}", now),
        )
        conn.commit()
    finally:
        conn.close()

    # Create snapshot directory with evaluator
    snapshot_dir = project_root / REVOLVER_DIR / "problem" / tag
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "evaluator.py").write_text(
        'def evaluate(program_path):\n    return {"combined_score": 0.5}\n',
        encoding="utf-8",
    )


def _create_dataset_in_db(
    project_root: Path,
    name: str,
    *,
    split: str = "train",
    instance_count: int = 3,
) -> Path:
    """Insert a dataset into DB and create instance files. Returns dataset dir."""
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    data_dir = project_root / "data" / name
    data_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, instance_count + 1):
        (data_dir / f"instance_{i:03d}.json").write_text(json.dumps({"id": i}), encoding="utf-8")
    try:
        conn.execute(
            "INSERT INTO datasets (name, path, split, storage, description, "
            "global_hash, instance_count, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                str(data_dir),
                split,
                "reference",
                "",
                f"hash-{name}",
                instance_count,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return data_dir


def _create_run_with_solution(
    project_root: Path,
    run_id: str,
    solution_id: str,
    *,
    problem_version: str = "v1.0",
    llm: str = "test-llm",
    dataset: str = "train-small",
    best_score: float | None = 0.95,
    alias: str | None = None,
    rank: int = 1,
) -> None:
    """Create a run and solution in the DB, and create the program file."""
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    now = datetime.now(UTC)
    try:
        insert_run(
            conn,
            run_id=run_id,
            problem_version=problem_version,
            llm=llm,
            dataset=dataset,
            iterations=10,
            problem_hash=f"phash-{problem_version}",
            dataset_hash=f"dhash-{dataset}",
            llm_model="gpt-4",
            created_at=now,
            status="completed",
            generation_time_s=30.0,
        )
        insert_solution(
            conn,
            solution_id=solution_id,
            run_id=run_id,
            rank=rank,
            best_score=best_score,
            alias=alias,
        )
    finally:
        conn.close()

    # Create program file
    programs_dir = project_root / REVOLVER_DIR / RUNS_DIR / run_id / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    (programs_dir / f"rank-{rank}.py").write_text("def solve(): pass\n", encoding="utf-8")


@pytest.fixture()
def project_with_solutions(tmp_project: Path) -> Path:
    """Set up a project with 2 runs and solutions for testing.

    - Run 1: sol-run1 (v1.0, test-llm, rank 1, score 0.95)
    - Run 2: sol-run2 (v2.0, other-llm, rank 1, score 0.80)
    """
    _create_problem_version_in_db(tmp_project, "v1.0")
    _create_problem_version_in_db(tmp_project, "v2.0")
    _create_dataset_in_db(tmp_project, "train-small")

    _create_run_with_solution(
        tmp_project,
        run_id="run-20260301-100000",
        solution_id="sol-20260301-100000",
        problem_version="v1.0",
        llm="test-llm",
        best_score=0.95,
    )
    _create_run_with_solution(
        tmp_project,
        run_id="run-20260302-100000",
        solution_id="sol-20260302-100000",
        problem_version="v2.0",
        llm="other-llm",
        best_score=0.80,
    )
    return tmp_project


@pytest.fixture()
def project_with_siblings(tmp_project: Path) -> Path:
    """Set up a project with a run that has 2 solutions (siblings).

    - Run: run-sibling, sol-sibling-1 (rank 1), sol-sibling-2 (rank 2)
    """
    _create_problem_version_in_db(tmp_project, "v1.0")
    _create_dataset_in_db(tmp_project, "train-small")

    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    now = datetime.now(UTC)
    try:
        insert_run(
            conn,
            run_id="run-sibling",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="phash-v1.0",
            dataset_hash="dhash-train",
            llm_model="gpt-4",
            created_at=now,
            status="completed",
            generation_time_s=30.0,
        )
        insert_solution(
            conn,
            solution_id="sol-sibling-1",
            run_id="run-sibling",
            rank=1,
            best_score=0.90,
        )
        insert_solution(
            conn,
            solution_id="sol-sibling-2",
            run_id="run-sibling",
            rank=2,
            best_score=0.85,
        )
    finally:
        conn.close()

    # Create program files
    programs_dir = tmp_project / REVOLVER_DIR / RUNS_DIR / "run-sibling" / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    (programs_dir / "rank-1.py").write_text("def solve(): pass\n", encoding="utf-8")
    (programs_dir / "rank-2.py").write_text("def solve2(): pass\n", encoding="utf-8")

    return tmp_project


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_list_shows_all_solutions(project_with_solutions: Path) -> None:
    """After 2 runs, ``solution list`` shows all solutions with expected columns.

    Validates: FR-SOL-001
    """
    result = _invoke_with_cwd(["solution", "list"], project_with_solutions)
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "sol-20260301-100000" in output
    assert "sol-20260302-100000" in output


@pytest.mark.integration
def test_list_filters(project_with_solutions: Path) -> None:
    """``solution list --version v1.0`` filters correctly.

    Validates: FR-SOL-002
    """
    result = _invoke_with_cwd(
        ["solution", "list", "--version", "v1.0"],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "sol-20260301-100000" in output
    assert "sol-20260302-100000" not in output


@pytest.mark.integration
def test_info_full_lineage(project_with_solutions: Path) -> None:
    """``solution info`` shows full lineage via run JOIN.

    Validates: FR-SOL-003, FR-SOL-004, FR-SOL-005
    """
    # Use JSON mode to avoid Rich table truncation of long paths
    result = _invoke_with_cwd(
        ["--json", "solution", "info", "sol-20260301-100000"],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    data = _parse_json_output(result)
    assert isinstance(data, dict)
    # Check lineage fields (FR-SOL-003)
    assert data["run_id"] == "run-20260301-100000"
    assert data["problem_version"] == "v1.0"
    assert data["llm"] == "test-llm"
    assert data["dataset"] == "train-small"
    # Check program path (FR-SOL-004)
    assert "rank-1.py" in str(data["program_path"])


@pytest.mark.integration
def test_info_shows_sibling_solutions(project_with_siblings: Path) -> None:
    """``solution info`` shows sibling solutions from same run.

    Validates: FR-SOL-009
    """
    result = _invoke_with_cwd(
        ["solution", "info", "sol-sibling-1"],
        project_with_siblings,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    # The sibling should be mentioned
    assert "sol-sibling-2" in output


@pytest.mark.integration
def test_alias_set(project_with_solutions: Path) -> None:
    """``solution alias`` sets alias — DB updated.

    Validates: FR-SOL-006, FR-SOL-007
    """
    result = _invoke_with_cwd(
        ["solution", "alias", "sol-20260301-100000", "my-best"],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "my-best" in output

    # Verify in DB
    db_path = project_with_solutions / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT alias FROM solutions WHERE id = ?",
            ("sol-20260301-100000",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "my-best"
    finally:
        conn.close()


@pytest.mark.integration
def test_alias_unique(project_with_solutions: Path) -> None:
    """Duplicate alias → exit code 1.

    Validates: FR-SOL-007
    """
    # Set alias on first solution
    _invoke_with_cwd(
        ["solution", "alias", "sol-20260301-100000", "unique-name"],
        project_with_solutions,
    )

    # Try to set same alias on second solution → should fail
    result = _invoke_with_cwd(
        ["solution", "alias", "sol-20260302-100000", "unique-name"],
        project_with_solutions,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]


@pytest.mark.integration
def test_reference_by_alias(project_with_solutions: Path) -> None:
    """Alias works in solution info (FR-SOL-008).

    Validates: FR-SOL-008
    """
    # Set alias
    _invoke_with_cwd(
        ["solution", "alias", "sol-20260301-100000", "best-v1"],
        project_with_solutions,
    )

    # Reference by alias in info
    result = _invoke_with_cwd(
        ["solution", "info", "best-v1"],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "sol-20260301-100000" in output
    assert "v1.0" in output


@pytest.mark.integration
def test_extract_promotes_program(project_with_solutions: Path) -> None:
    """``solution extract`` promotes rank #2 — new solution entry, unique ID.

    Validates: FR-SOL-011, FR-SOL-013
    """
    # Create rank-2 program file
    programs_dir = (
        project_with_solutions / REVOLVER_DIR / RUNS_DIR / "run-20260301-100000" / "programs"
    )
    (programs_dir / "rank-2.py").write_text("def solve2(): pass\n", encoding="utf-8")

    result = _invoke_with_cwd(
        [
            "solution",
            "extract",
            "--run",
            "run-20260301-100000",
            "--rank",
            "2",
            "--alias",
            "rank2-solution",
        ],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "rank2-solution" in output

    # Verify in DB: new solution exists with correct run_id and rank
    db_path = project_with_solutions / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT id, run_id, rank, alias FROM solutions WHERE run_id = ? AND rank = 2",
            ("run-20260301-100000",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "run-20260301-100000"
        assert row[2] == 2
        assert row[3] == "rank2-solution"
        # ID should follow sol-YYYYMMDD-HHMMSS pattern
        assert row[0].startswith("sol-")
    finally:
        conn.close()


@pytest.mark.integration
def test_extract_duplicate_blocked(project_with_solutions: Path) -> None:
    """Same (run_id, rank) already extracted → exit code 1.

    Validates: FR-SOL-012
    """
    # rank-1 is already extracted for run-20260301-100000
    result = _invoke_with_cwd(
        [
            "solution",
            "extract",
            "--run",
            "run-20260301-100000",
            "--rank",
            "1",
        ],
        project_with_solutions,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]


@pytest.mark.integration
def test_extract_rejects_non_completed_run(tmp_project: Path) -> None:
    """``solution extract`` rejects a run that is not completed.

    Validates: CRITICAL-1 review finding — run status must be 'completed'.
    """
    _create_problem_version_in_db(tmp_project, "v1.0")
    _create_dataset_in_db(tmp_project, "train-small")

    # Create a run with status='running' (not completed)
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id="run-running",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="phash-v1.0",
            dataset_hash="dhash-train-small",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="running",
        )
    finally:
        conn.close()

    # Create program file so that the file-existence check passes
    programs_dir = tmp_project / REVOLVER_DIR / RUNS_DIR / "run-running" / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    (programs_dir / "rank-1.py").write_text("def solve(): pass\n", encoding="utf-8")

    result = _invoke_with_cwd(
        ["solution", "extract", "--run", "run-running", "--rank", "1"],
        tmp_project,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "not completed" in output.lower()


@pytest.mark.integration
def test_extract_rejects_rank_zero(project_with_solutions: Path) -> None:
    """``solution extract --rank 0`` is rejected with validation error.

    Validates: WARNING-4 review finding — rank must be > 0.
    """
    result = _invoke_with_cwd(
        ["solution", "extract", "--run", "run-20260301-100000", "--rank", "0"],
        project_with_solutions,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "rank" in output.lower()


@pytest.mark.integration
def test_alias_rejects_empty_string(project_with_solutions: Path) -> None:
    """``solution alias <id> ""`` is rejected with validation error.

    Validates: WARNING-4 review finding — alias must not be empty.
    """
    result = _invoke_with_cwd(
        ["solution", "alias", "sol-20260301-100000", ""],
        project_with_solutions,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]


# ── solution delete tests (F4 — Sprint 005a) ──────────────────────────────────


@pytest.mark.integration
def test_solution_delete_by_alias(project_with_solutions: Path) -> None:
    """Create solution with alias, delete by alias, verify gone.

    Validates: F4 acceptance — delete by alias with confirmation.
    """
    # Set alias on a solution
    _invoke_with_cwd(
        ["solution", "alias", "sol-20260301-100000", "to-delete"],
        project_with_solutions,
    )

    # Delete by alias with --force (skip interactive confirmation)
    result = _invoke_with_cwd(
        ["solution", "delete", "to-delete", "--force"],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "sol-20260301-100000" in output
    assert "deleted" in output.lower()

    # Verify solution is gone from DB
    db_path = project_with_solutions / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT id FROM solutions WHERE id = ?",
            ("sol-20260301-100000",),
        )
        assert cursor.fetchone() is None
    finally:
        conn.close()


@pytest.mark.integration
def test_solution_delete_by_id_force(project_with_solutions: Path) -> None:
    """Delete solution by ID with --force, verify gone.

    Validates: F4 acceptance — delete by ID, --force skips confirmation.
    """
    result = _invoke_with_cwd(
        ["solution", "delete", "sol-20260301-100000", "--force"],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "deleted" in output.lower()

    # Verify solution is gone
    db_path = project_with_solutions / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT id FROM solutions WHERE id = ?",
            ("sol-20260301-100000",),
        )
        assert cursor.fetchone() is None
    finally:
        conn.close()


@pytest.mark.integration
def test_solution_delete_nonexistent(project_with_solutions: Path) -> None:
    """Delete nonexistent solution → exit code 1.

    Validates: F4 acceptance — nonexistent alias.
    """
    result = _invoke_with_cwd(
        ["solution", "delete", "ghost-solution", "--force"],
        project_with_solutions,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]


@pytest.mark.integration
def test_solution_delete_json_mode_requires_force(project_with_solutions: Path) -> None:
    """JSON mode without --force → exit code 1.

    Validates: F4 acceptance — JSON mode rejects without --force.
    """
    result = _invoke_with_cwd(
        ["--json", "solution", "delete", "sol-20260301-100000"],
        project_with_solutions,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "--force" in output


@pytest.mark.integration
def test_solution_delete_json_mode_with_force(project_with_solutions: Path) -> None:
    """JSON mode with --force → JSON output with deleted status.

    Validates: F4 acceptance — JSON mode + --force works.
    """
    result = _invoke_with_cwd(
        ["--json", "solution", "delete", "sol-20260301-100000", "--force"],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    data = _parse_json_output(result)
    assert isinstance(data, dict)
    assert data["solution_id"] == "sol-20260301-100000"
    assert data["status"] == "deleted"


@pytest.mark.integration
def test_solution_delete_user_cancels(project_with_solutions: Path) -> None:
    """User declines confirmation prompt → solution is NOT deleted.

    Validates: F4 acceptance — interactive cancellation aborts delete.
    """
    interactive_runner = CliRunner()
    with patch("pathlib.Path.cwd", return_value=project_with_solutions):
        result = interactive_runner.invoke(
            app,
            ["solution", "delete", "sol-20260301-100000"],
            input="n\n",
        )

    # typer.confirm with abort=True raises Abort → exit code 1
    assert result.exit_code == 1  # type: ignore[union-attr]

    # Verify solution is still in DB
    db_path = project_with_solutions / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT id FROM solutions WHERE id = ?",
            ("sol-20260301-100000",),
        )
        assert cursor.fetchone() is not None
    finally:
        conn.close()


@pytest.mark.integration
def test_solution_delete_user_confirms(project_with_solutions: Path) -> None:
    """User accepts confirmation prompt → solution is deleted.

    Validates: F4 acceptance — interactive confirmation proceeds with delete.
    """
    interactive_runner = CliRunner()
    with patch("pathlib.Path.cwd", return_value=project_with_solutions):
        result = interactive_runner.invoke(
            app,
            ["solution", "delete", "sol-20260301-100000"],
            input="y\n",
        )

    assert result.exit_code == 0  # type: ignore[union-attr]

    # Verify solution is gone from DB
    db_path = project_with_solutions / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT id FROM solutions WHERE id = ?",
            ("sol-20260301-100000",),
        )
        assert cursor.fetchone() is None
    finally:
        conn.close()
