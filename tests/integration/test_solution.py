"""L2 integration tests for ``revolver solution`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner with real
SQLite databases in ``tmp_path``. Runs and solutions are pre-seeded
in the database as fixtures.

Traceable to: val-integration-tests.md section 2.7 (9 scenarios).
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
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


def _create_run_with_solution_content(
    project_root: Path,
    run_id: str,
    solution_id: str,
    program_content: str,
    *,
    problem_version: str = "v1.0",
    llm: str = "test-llm",
    dataset: str = "train-small",
    best_score: float | None = 0.95,
    alias: str | None = None,
    rank: int = 1,
    create_run: bool = True,
) -> None:
    """Create a run and solution in the DB with custom program content."""
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    now = datetime.now(UTC)
    try:
        if create_run:
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

    # Create program file with custom content
    programs_dir = project_root / REVOLVER_DIR / RUNS_DIR / run_id / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    (programs_dir / f"rank-{rank}.py").write_text(program_content, encoding="utf-8")


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
def test_extract_promotes_program(tmp_project: Path) -> None:
    """``solution extract`` promotes rank-1 program — new solution entry, unique ID.

    Validates: FR-SOL-011, FR-SOL-013

    Uses a fresh run (without pre-existing solution) so the extract creates
    the first solution for that run with hardcoded rank=1.
    """
    _create_problem_version_in_db(tmp_project, "v1.0")
    _create_dataset_in_db(tmp_project, "train-small")

    # Create a completed run without any solution extracted yet
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id="run-fresh",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="phash-v1.0",
            dataset_hash="dhash-train-small",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
            generation_time_s=30.0,
        )
    finally:
        conn.close()

    programs_dir = tmp_project / REVOLVER_DIR / RUNS_DIR / "run-fresh" / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    (programs_dir / "rank-1.py").write_text("def solve(): pass\n", encoding="utf-8")

    result = _invoke_with_cwd(
        [
            "solution",
            "extract",
            "--run",
            "run-fresh",
            "--alias",
            "fresh-solution",
        ],
        tmp_project,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "fresh-solution" in output

    # Verify in DB: new solution exists with correct run_id and rank=1
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT id, run_id, rank, alias FROM solutions WHERE run_id = ? AND rank = 1",
            ("run-fresh",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "run-fresh"
        assert row[2] == 1
        assert row[3] == "fresh-solution"
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
        ["solution", "extract", "--run", "run-running"],
        tmp_project,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "not completed" in output.lower()


@pytest.mark.integration
def test_extract_accepts_completed_with_errors(tmp_project: Path) -> None:
    """``solution extract`` succeeds on a run with status='completed_with_errors'.

    Validates: F3 fix — completed_with_errors runs should be extractable.
    """
    _create_problem_version_in_db(tmp_project, "v1.0")
    _create_dataset_in_db(tmp_project, "train-small")

    # Create a run with status='completed_with_errors'
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id="run-cwe",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="phash-v1.0",
            dataset_hash="dhash-train-small",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed_with_errors",
            generation_time_s=30.0,
        )
    finally:
        conn.close()

    # Create program file
    programs_dir = tmp_project / REVOLVER_DIR / RUNS_DIR / "run-cwe" / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    (programs_dir / "rank-1.py").write_text("def solve(): pass\n", encoding="utf-8")

    result = _invoke_with_cwd(
        ["solution", "extract", "--run", "run-cwe"],
        tmp_project,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "sol-" in output


def _seed_interrupted_run(
    tmp_project: Path,
    run_id: str,
    *,
    status: str = "interrupted",
    write_rank1: bool = True,
) -> Path:
    """Seed a run (default interrupted) and return its dir.

    ``write_rank1=False`` skips the placeholder ``programs/rank-1.py`` so a
    test can assert it is *absent* after an aborted --from-checkpoint command
    (finding #2: no stray file on abort).
    """
    _create_problem_version_in_db(tmp_project, "v1.0")
    _create_dataset_in_db(tmp_project, "train-small")

    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="phash-v1.0",
            dataset_hash="dhash-train-small",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status=status,
            backend="openevolve",
        )
    finally:
        conn.close()

    run_dir = tmp_project / REVOLVER_DIR / RUNS_DIR / run_id
    programs_dir = run_dir / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    if write_rank1:
        (programs_dir / "rank-1.py").write_text("def solve(): pass\n", encoding="utf-8")
    return run_dir


def _write_oe_checkpoint(
    run_dir: Path,
    best_code: str,
    best_score: float,
    extra_metrics: dict[str, float] | None = None,
) -> None:
    """Write a minimal OpenEvolve checkpoint with a tracked best program.

    *extra_metrics* are stored alongside ``combined_score`` so a test can
    assert the recovered score is the ``combined_score`` alone, not the sum of
    all numeric metrics (finding #1).
    """
    checkpoint = run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    programs = checkpoint / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    best_id = "prog-best-123"
    metrics: dict[str, float] = {"combined_score": best_score}
    if extra_metrics:
        metrics.update(extra_metrics)
    (checkpoint / "metadata.json").write_text(
        json.dumps({"best_program_id": best_id}), encoding="utf-8"
    )
    (programs / f"{best_id}.json").write_text(
        json.dumps(
            {
                "id": best_id,
                "code": best_code,
                "language": "python",
                "metrics": metrics,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.integration
def test_extract_rejects_interrupted_run(tmp_project: Path) -> None:
    """``solution extract`` (default) rejects a run with status='interrupted'.

    v0.17 policy change (B7 / S17-09): this consciously revises the original
    F3 decision. The **default** behaviour is unchanged — interrupted runs are
    still NOT extractable without the explicit ``--from-checkpoint`` flag (see
    ``test_extract_from_checkpoint_recovers_interrupted_run`` for the opt-in
    recovery path). This test pins the default-rejects contract.
    """
    _seed_interrupted_run(tmp_project, "run-interrupted")

    result = _invoke_with_cwd(
        ["solution", "extract", "--run", "run-interrupted"],
        tmp_project,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "not completed" in output.lower()


@pytest.mark.integration
def test_extract_from_checkpoint_recovers_interrupted_run(tmp_project: Path) -> None:
    """``solution extract --from-checkpoint`` recovers an interrupted run (B7).

    The flag path succeeds where the default rejects: the best program is
    recovered from the latest OpenEvolve checkpoint, materialized to the
    run's ``programs/rank-1.py``, and promoted to a solution carrying the
    recovered ``combined_score``.

    The checkpoint program carries multiple numeric metrics; the persisted
    score must be the ``combined_score`` alone (0.87), NOT the sum of all
    metrics (0.87 + 0.5 + 12.0 = 13.37) — finding #1.
    """
    run_dir = _seed_interrupted_run(tmp_project, "run-recover")
    recovered_code = "def solve():\n    return 42  # recovered from checkpoint\n"
    _write_oe_checkpoint(
        run_dir,
        recovered_code,
        best_score=0.87,
        extra_metrics={"accuracy": 0.5, "latency_ms": 12.0},
    )

    result = _invoke_with_cwd(
        ["solution", "extract", "--run", "run-recover", "--from-checkpoint"],
        tmp_project,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "sol-" in output

    # The recovered code was materialized to rank-1.py.
    rank1 = run_dir / "programs" / "rank-1.py"
    assert rank1.read_text(encoding="utf-8") == recovered_code

    # The recovered score is the combined_score, not the sum of all metrics.
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        row = conn.execute(
            "SELECT best_score FROM solutions WHERE run_id = ?", ("run-recover",)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == pytest.approx(0.87)


@pytest.mark.integration
def test_extract_from_checkpoint_leaves_no_stray_file_on_abort(tmp_project: Path) -> None:
    """A validation failure under --from-checkpoint leaves no rank-1.py (finding #2).

    Recovery is read-only; the recovered code is materialized only after the
    alias/duplicate/force validation passes. Here a duplicate (run_id, rank)
    without --force aborts the command, so ``programs/rank-1.py`` must NOT be
    created.
    """
    run_dir = _seed_interrupted_run(tmp_project, "run-abort", write_rank1=False)
    recovered_code = "def solve():\n    return 7  # would be recovered\n"
    _write_oe_checkpoint(run_dir, recovered_code, best_score=0.5)

    # Pre-existing solution for (run-abort, rank 1): the extract must abort as a
    # duplicate before any file is written.
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        insert_solution(
            conn,
            solution_id="sol-preexisting",
            run_id="run-abort",
            rank=1,
            best_score=0.1,
            alias=None,
        )
    finally:
        conn.close()

    rank1 = run_dir / "programs" / "rank-1.py"
    assert not rank1.exists()  # precondition: no rank-1.py yet

    result = _invoke_with_cwd(
        ["solution", "extract", "--run", "run-abort", "--from-checkpoint"],
        tmp_project,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "already exists" in output.lower()

    # No stray rank-1.py was left behind by the aborted command.
    assert not rank1.exists()


@pytest.mark.integration
def test_extract_from_checkpoint_on_completed_run_notes_ignored(tmp_project: Path) -> None:
    """--from-checkpoint on a COMPLETED run notes the flag is ignored (finding #3).

    The flag is a no-op on a completed run (it already has extractable
    programs), but the command must say so on stderr rather than silently
    ignoring the flag, and still succeed via the normal rank-1 path.
    """
    run_dir = _seed_interrupted_run(tmp_project, "run-done", status="completed", write_rank1=True)
    # A checkpoint exists but must NOT be used (completed run -> normal path).
    _write_oe_checkpoint(
        run_dir, "def solve():\n    return 999  # checkpoint, unused\n", best_score=0.99
    )

    result = _invoke_with_cwd(
        ["solution", "extract", "--run", "run-done", "--from-checkpoint"],
        tmp_project,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "--from-checkpoint ignored" in output
    assert "sol-" in output

    # The normal rank-1.py (the placeholder) was used, not the checkpoint code.
    rank1 = run_dir / "programs" / "rank-1.py"
    assert "checkpoint, unused" not in rank1.read_text(encoding="utf-8")


@pytest.mark.integration
def test_extract_from_checkpoint_no_checkpoint_yet_errors(tmp_project: Path) -> None:
    """``--from-checkpoint`` errors cleanly when no checkpoint exists yet (B7).

    A run interrupted before its first checkpoint has no state to recover; the
    command must fail with a clear, non-zero-exit error rather than crash.
    """
    _seed_interrupted_run(tmp_project, "run-tooshort")
    # No checkpoint written (run too short).

    result = _invoke_with_cwd(
        ["solution", "extract", "--run", "run-tooshort", "--from-checkpoint"],
        tmp_project,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "no checkpoint" in output.lower()


@pytest.mark.integration
def test_solution_extract_force(project_with_solutions: Path) -> None:
    """``solution extract --force`` replaces an existing (run_id, rank) extraction.

    Validates: FR-SOL-011, FR-SOL-012, S9-06, S9-07.
    """
    # rank-1 already extracted for run-20260301-100000 (sol-20260301-100000)
    # Using --force should delete the old solution and insert a new one
    result = _invoke_with_cwd(
        [
            "solution",
            "extract",
            "--run",
            "run-20260301-100000",
            "--force",
            "--alias",
            "replaced-sol",
        ],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "replaced-sol" in output

    # Verify in DB: old solution is gone, new one exists
    db_path = project_with_solutions / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # Old solution should be deleted
        cursor = conn.execute(
            "SELECT id FROM solutions WHERE id = ?",
            ("sol-20260301-100000",),
        )
        assert cursor.fetchone() is None

        # New solution should exist with rank=1
        cursor = conn.execute(
            "SELECT id, run_id, rank, alias FROM solutions WHERE run_id = ? AND rank = 1",
            ("run-20260301-100000",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "run-20260301-100000"
        assert row[2] == 1
        assert row[3] == "replaced-sol"
        assert row[0].startswith("sol-")
        # New ID should differ from old
        assert row[0] != "sol-20260301-100000"
    finally:
        conn.close()


@pytest.mark.integration
def test_solution_extract_no_rank_flag(project_with_solutions: Path) -> None:
    """``--rank`` is absent from ``solution extract --help`` output.

    Validates: S9-07 — rank removed from CLI.
    """
    result = _invoke_with_cwd(
        ["solution", "extract", "--help"],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)
    assert "--rank" not in output
    # --force and --run should still be present
    assert "--force" in output
    assert "--run" in output


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


# ── solution show / export / diff tests (Sprint 009 — S9-01..S9-05) ─────


@pytest.fixture()
def project_with_show_solutions(tmp_project: Path) -> Path:
    """Set up a project with two solutions having different program content.

    - sol-alpha: alias "alpha", code = "def alpha(): return 1\\n"
    - sol-beta:  alias "beta",  code = "def beta(): return 2\\n"
    """
    _create_problem_version_in_db(tmp_project, "v1.0")
    _create_dataset_in_db(tmp_project, "train-small")

    _create_run_with_solution_content(
        tmp_project,
        run_id="run-alpha",
        solution_id="sol-alpha",
        program_content="def alpha(): return 1\n",
        alias="alpha",
    )
    _create_run_with_solution_content(
        tmp_project,
        run_id="run-beta",
        solution_id="sol-beta",
        program_content="def beta(): return 2\n",
        alias="beta",
    )
    return tmp_project


@pytest.mark.integration
def test_solution_show_stdout(project_with_show_solutions: Path) -> None:
    """``solution show`` prints source code to stdout.

    Validates: S9-01, S9-03 — FR-SOL-003, FR-SOL-004
    """
    result = _invoke_with_cwd(
        ["solution", "show", "alpha"],
        project_with_show_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = getattr(result, "output", "")
    assert "def alpha(): return 1" in output


@pytest.mark.integration
def test_solution_show_json(project_with_show_solutions: Path) -> None:
    """``solution show --json`` outputs code as a string field.

    Validates: S9-03 — FR-SOL-003
    """
    result = _invoke_with_cwd(
        ["--json", "solution", "show", "alpha"],
        project_with_show_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    data = _parse_json_output(result)
    assert isinstance(data, dict)
    assert "code" in data
    assert "def alpha(): return 1" in data["code"]
    assert data["alias"] == "alpha"


@pytest.mark.integration
def test_solution_show_not_found(project_with_show_solutions: Path) -> None:
    """``solution show`` with unknown alias → exit 1.

    Validates: S9-03 — error handling
    """
    result = _invoke_with_cwd(
        ["solution", "show", "nonexistent"],
        project_with_show_solutions,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]


@pytest.mark.integration
def test_solution_export_default(
    project_with_show_solutions: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``solution export`` copies to default ./<alias>.py.

    Validates: S9-04 — FR-SOL-003, FR-SOL-004
    """
    # Change to a temp directory for default export (monkeypatch is test-safe)
    export_dir = project_with_show_solutions / "export-test"
    export_dir.mkdir()
    monkeypatch.chdir(export_dir)

    result = _invoke_with_cwd(
        ["solution", "export", "alpha"],
        project_with_show_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]

    exported_file = export_dir / "alpha.py"
    assert exported_file.exists()
    content = exported_file.read_text(encoding="utf-8")
    assert "def alpha(): return 1" in content


@pytest.mark.integration
def test_solution_export_explicit_path(project_with_show_solutions: Path) -> None:
    """``solution export -o <path>`` copies to explicit path.

    Validates: S9-04 — FR-SOL-003, FR-SOL-004
    """
    target = project_with_show_solutions / "my-output.py"

    result = _invoke_with_cwd(
        ["solution", "export", "alpha", "-o", str(target)],
        project_with_show_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]

    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "def alpha(): return 1" in content


@pytest.mark.integration
def test_solution_export_not_found(project_with_show_solutions: Path) -> None:
    """``solution export`` with unknown alias → exit 1.

    Validates: S9-04 — error handling
    """
    result = _invoke_with_cwd(
        ["solution", "export", "nonexistent"],
        project_with_show_solutions,
    )
    assert result.exit_code == 1  # type: ignore[union-attr]


@pytest.mark.integration
def test_solution_diff_different(project_with_show_solutions: Path) -> None:
    """``solution diff`` shows unified diff for two different solutions.

    Validates: S9-02, S9-05 — diff on stdout, exit 0
    """
    result = _invoke_with_cwd(
        ["solution", "diff", "alpha", "beta"],
        project_with_show_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = getattr(result, "output", "")
    # Should contain diff markers
    assert "---" in output
    assert "+++" in output
    assert "-def alpha" in output
    assert "+def beta" in output


@pytest.mark.integration
def test_solution_diff_identical(project_with_show_solutions: Path) -> None:
    """``solution diff`` with two identical programs → empty diff, exit 0.

    Validates: S9-05 — identical programs, exit 0
    """
    # Create a second solution pointing to the same content
    _create_run_with_solution_content(
        project_with_show_solutions,
        run_id="run-alpha-copy",
        solution_id="sol-alpha-copy",
        program_content="def alpha(): return 1\n",
        alias="alpha-copy",
    )

    result = _invoke_with_cwd(
        ["solution", "diff", "alpha", "alpha-copy"],
        project_with_show_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = getattr(result, "output", "")
    # Identical files → no diff markers
    assert "---" not in output
    assert "+++" not in output


@pytest.mark.integration
def test_solution_diff_json(project_with_show_solutions: Path) -> None:
    """``solution diff --json`` returns diff text + identical flag.

    Validates: S9-05 — JSON output format
    """
    result = _invoke_with_cwd(
        ["--json", "solution", "diff", "alpha", "beta"],
        project_with_show_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    data = _parse_json_output(result)
    assert isinstance(data, dict)
    assert "diff" in data
    assert "identical" in data
    assert data["identical"] is False
    assert "---" in data["diff"]


# ── Resume chain tests (F6, S12-08, S12-09) ──────────────────────────────────


def _create_resumed_run_chain(
    project_root: Path,
) -> tuple[str, str, str]:
    """Create a chain of 3 runs: original -> resumed1 -> resumed2.

    Returns (original_run_id, resumed1_run_id, resumed2_run_id).
    """
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    now = datetime.now(UTC)
    try:
        # Original run
        insert_run(
            conn,
            run_id="run-original",
            problem_version="v1.0",
            llm="llm-a",
            dataset="train-small",
            iterations=10,
            problem_hash="phash-v1.0",
            dataset_hash="dhash-train",
            llm_model="model-a",
            created_at=now,
            status="completed",
            generation_time_s=30.0,
        )
        # First resume
        insert_run(
            conn,
            run_id="run-resumed1",
            problem_version="v1.0",
            llm="llm-b",
            dataset="train-small",
            iterations=10,
            problem_hash="phash-v1.0",
            dataset_hash="dhash-train",
            llm_model="model-b",
            created_at=now,
            status="completed",
            generation_time_s=25.0,
            resumed_from="run-original",
        )
        # Second resume
        insert_run(
            conn,
            run_id="run-resumed2",
            problem_version="v1.0",
            llm="llm-c",
            dataset="train-small",
            iterations=10,
            problem_hash="phash-v1.0",
            dataset_hash="dhash-train",
            llm_model="model-c",
            created_at=now,
            status="completed",
            generation_time_s=20.0,
            resumed_from="run-resumed1",
        )
        # Solution for the last run
        insert_solution(
            conn,
            solution_id="sol-resumed",
            run_id="run-resumed2",
            rank=1,
            best_score=0.99,
        )
    finally:
        conn.close()

    # Create program file
    programs_dir = project_root / REVOLVER_DIR / RUNS_DIR / "run-resumed2" / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    (programs_dir / "rank-1.py").write_text("def solve(): pass\n", encoding="utf-8")

    return ("run-original", "run-resumed1", "run-resumed2")


@pytest.fixture()
def project_with_resume_chain(tmp_project: Path) -> Path:
    """Set up a project with a 3-run resume chain and a solution on the last run."""
    _create_problem_version_in_db(tmp_project, "v1.0")
    _create_dataset_in_db(tmp_project, "train-small")
    _create_resumed_run_chain(tmp_project)
    return tmp_project


@pytest.mark.integration
def test_solution_info_resume_chain(project_with_resume_chain: Path) -> None:
    """solution info shows resumed_from and resume_chain for a resumed run.

    Validates: F6, S12-08, S12-09 — resume chain display.
    """
    result = _invoke_with_cwd(
        ["solution", "info", "sol-resumed"],
        project_with_resume_chain,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    output = _get_all_output(result)

    # Should show resumed_from
    assert "run-resumed1" in output, f"Expected resumed_from in output: {output}"
    # Should show the chain with arrow notation
    assert "\u2192" in output, f"Expected arrow in resume chain: {output}"
    assert "run-original" in output, f"Expected root run in chain: {output}"


@pytest.mark.integration
def test_solution_info_resume_chain_json(project_with_resume_chain: Path) -> None:
    """solution info --json includes resumed_from and resume_chain fields.

    Validates: F6, S12-09 — JSON output includes resume chain.
    """
    result = _invoke_with_cwd(
        ["--json", "solution", "info", "sol-resumed"],
        project_with_resume_chain,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    data = _parse_json_output(result)
    assert isinstance(data, dict)

    assert data["resumed_from"] == "run-resumed1"
    assert "resume_chain" in data
    chain = data["resume_chain"]
    assert isinstance(chain, list)
    assert chain == ["run-original", "run-resumed1", "run-resumed2"]


@pytest.mark.integration
def test_solution_info_no_resume_chain(project_with_solutions: Path) -> None:
    """solution info for a non-resumed run does NOT show resume fields.

    Validates: F6 — resume fields are only shown when the run was resumed.
    """
    result = _invoke_with_cwd(
        ["--json", "solution", "info", "sol-20260301-100000"],
        project_with_solutions,
    )
    assert result.exit_code == 0  # type: ignore[union-attr]
    data = _parse_json_output(result)
    assert isinstance(data, dict)

    assert "resumed_from" not in data, f"Non-resumed run should not have resumed_from: {data}"
    assert "resume_chain" not in data, f"Non-resumed run should not have resume_chain: {data}"
