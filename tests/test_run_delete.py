"""L1/L2 tests for ``revolver run delete`` command.

Tests the run delete functionality at both DB level and CLI level
using Typer's CliRunner with real SQLite databases in ``tmp_path``.

Traceable to: FR-RUN-027, issue #92 (S8-08/S8-09/S8-10).
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.exceptions import ActiveRunError
from revolver.core.project import init_project
from revolver.core.run import delete_run as core_delete_run
from revolver.infra.db import (
    count_evals_for_run,
    delete_run as db_delete_run,
    get_project_db,
    get_run,
    get_solutions_for_run,
    insert_eval_metadata,
    insert_run,
    insert_solution,
)
from revolver.infra.store import REVOLVER_DIR, RUNS_DIR

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
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a project DB for unit-level testing."""
    conn = get_project_db(tmp_path / "revolver.db")
    yield conn  # type: ignore[misc]
    conn.close()


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with init_project and return the root."""
    init_project(tmp_path, "test-project")
    return tmp_path


def _seed_problem_and_dataset(conn: sqlite3.Connection) -> None:
    """Insert a problem version and dataset required by FK constraints."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO problem_versions (tag, hash, message, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("v1.0", "sha256:pvhash", "Version 1.0", now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO datasets (name, path, split, storage, description, "
        "global_hash, instance_count, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("train-small", "/data/train", "train", "reference", "", "sha256:dshash", 10, now),
    )
    conn.commit()


def _create_run_with_solutions(
    project_root: Path,
    run_id: str = "run-20260314-120000",
    *,
    num_solutions: int = 2,
    add_evals: bool = False,
) -> None:
    """Create a run with solutions (and optionally evals) in DB and on disk."""
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    now = datetime.now(UTC)
    try:
        _seed_problem_and_dataset(conn)

        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="sha256:pvhash",
            dataset_hash="sha256:dshash",
            llm_model="gpt-4",
            created_at=now,
            status="completed",
            generation_time_s=30.0,
        )
        for rank in range(1, num_solutions + 1):
            sol_id = f"sol-{run_id}-rank{rank}"
            insert_solution(
                conn,
                solution_id=sol_id,
                run_id=run_id,
                rank=rank,
                best_score=0.95 - (rank - 1) * 0.05,
            )
            if add_evals:
                insert_eval_metadata(
                    conn,
                    eval_id=f"eval-{sol_id}",
                    solution_id=sol_id,
                    dataset_name="train-small",
                    instance_count=3,
                    instances_solved=2,
                    eval_time_s=1.5,
                    evaluated_at=now,
                )
    finally:
        conn.close()

    # Create run directory with program files on disk
    programs_dir = project_root / REVOLVER_DIR / RUNS_DIR / run_id / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    for rank in range(1, num_solutions + 1):
        (programs_dir / f"rank-{rank}.py").write_text(
            f"def solve_{rank}(): pass\n", encoding="utf-8"
        )


# ── L1 Unit tests: DB helpers ──────────────────────────────────────────────


class TestDeleteRunDB:
    """Unit tests for delete_run and count_evals_for_run DB helpers."""

    @pytest.mark.unit
    def test_delete_run_returns_true(self, db_conn: sqlite3.Connection) -> None:
        """delete_run returns True when a run is deleted."""
        _seed_problem_and_dataset(db_conn)
        insert_run(
            db_conn,
            run_id="run-to-delete",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="sha256:pvhash",
            dataset_hash="sha256:dshash",
            llm_model="gpt-4",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
            status="completed",
        )
        assert db_delete_run(db_conn, "run-to-delete") is True

    @pytest.mark.unit
    def test_delete_run_returns_false_not_found(self, db_conn: sqlite3.Connection) -> None:
        """delete_run returns False when run does not exist."""
        assert db_delete_run(db_conn, "ghost-run") is False

    @pytest.mark.unit
    def test_delete_run_cascades_solutions(self, db_conn: sqlite3.Connection) -> None:
        """Deleting a run cascades to solutions."""
        _seed_problem_and_dataset(db_conn)
        insert_run(
            db_conn,
            run_id="run-cascade",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="sha256:pvhash",
            dataset_hash="sha256:dshash",
            llm_model="gpt-4",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
            status="completed",
        )
        insert_solution(
            db_conn,
            solution_id="sol-cascade-1",
            run_id="run-cascade",
            rank=1,
            best_score=0.9,
        )
        db_delete_run(db_conn, "run-cascade")

        assert get_run(db_conn, "run-cascade") is None
        assert get_solutions_for_run(db_conn, "run-cascade") == []

    @pytest.mark.unit
    def test_count_evals_for_run(self, db_conn: sqlite3.Connection) -> None:
        """count_evals_for_run returns correct count."""
        _seed_problem_and_dataset(db_conn)
        now = datetime(2026, 3, 14, tzinfo=UTC)
        insert_run(
            db_conn,
            run_id="run-evals",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="sha256:pvhash",
            dataset_hash="sha256:dshash",
            llm_model="gpt-4",
            created_at=now,
            status="completed",
        )
        insert_solution(
            db_conn,
            solution_id="sol-evals-1",
            run_id="run-evals",
            rank=1,
            best_score=0.9,
        )
        insert_eval_metadata(
            db_conn,
            eval_id="eval-1",
            solution_id="sol-evals-1",
            dataset_name="train-small",
            instance_count=3,
            instances_solved=2,
            eval_time_s=1.0,
            evaluated_at=now,
        )
        assert count_evals_for_run(db_conn, "run-evals") == 1

    @pytest.mark.unit
    def test_count_evals_for_run_zero(self, db_conn: sqlite3.Connection) -> None:
        """count_evals_for_run returns 0 when no evals exist."""
        _seed_problem_and_dataset(db_conn)
        insert_run(
            db_conn,
            run_id="run-no-evals",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="sha256:pvhash",
            dataset_hash="sha256:dshash",
            llm_model="gpt-4",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
            status="completed",
        )
        assert count_evals_for_run(db_conn, "run-no-evals") == 0

    @pytest.mark.unit
    def test_run_delete_running_run_raises(self, tmp_path: Path) -> None:
        """delete_run raises ActiveRunError when the target run is active."""
        init_project(tmp_path, "test-project")
        _create_run_with_solutions(tmp_path, "run-active", num_solutions=1)

        fake_lock = {"run_id": "run-active", "pid": str(os.getpid())}

        with (
            patch("revolver.core.run.get_active_locks", return_value=[fake_lock]),
            patch("revolver.core.run._is_pid_alive", return_value=True),
            pytest.raises(ActiveRunError, match="currently active"),
        ):
            core_delete_run("run-active", project_root=tmp_path)


# ── L2 Integration tests: CLI ──────────────────────────────────────────────


class TestRunDeleteCLI:
    """Integration tests for ``revolver run delete`` CLI command."""

    pytestmark = pytest.mark.integration

    def test_run_delete_by_id(self, tmp_project: Path) -> None:
        """Delete an existing run with --force, verify DB + files gone.

        Validates: S8-10 acceptance — basic delete by ID.
        """
        run_id = "run-del-test"
        _create_run_with_solutions(tmp_project, run_id, num_solutions=2, add_evals=True)

        # Verify run directory exists before delete
        run_dir = tmp_project / REVOLVER_DIR / RUNS_DIR / run_id
        assert run_dir.exists()

        result = _invoke_with_cwd(
            ["run", "delete", run_id, "--force"],
            tmp_project,
        )
        assert result.exit_code == 0  # type: ignore[union-attr]
        output = _get_all_output(result)
        assert run_id in output
        assert "deleted" in output.lower()

        # Verify run is gone from DB
        db_path = tmp_project / REVOLVER_DIR / "revolver.db"
        conn = get_project_db(db_path)
        try:
            assert get_run(conn, run_id) is None
            assert get_solutions_for_run(conn, run_id) == []
        finally:
            conn.close()

        # Verify run directory is gone from disk
        assert not run_dir.exists()

    def test_run_delete_force_skips_prompt(self, tmp_project: Path) -> None:
        """--force removes without interactive prompt.

        Validates: S8-10 acceptance — --force skips confirmation.
        """
        run_id = "run-force-test"
        _create_run_with_solutions(tmp_project, run_id, num_solutions=1)

        result = _invoke_with_cwd(
            ["run", "delete", run_id, "--force"],
            tmp_project,
        )
        assert result.exit_code == 0  # type: ignore[union-attr]

        # Verify deleted
        db_path = tmp_project / REVOLVER_DIR / "revolver.db"
        conn = get_project_db(db_path)
        try:
            assert get_run(conn, run_id) is None
        finally:
            conn.close()

    def test_run_delete_not_found(self, tmp_project: Path) -> None:
        """Unknown run → exit code 1.

        Validates: S8-10 acceptance — error on nonexistent run.
        """
        result = _invoke_with_cwd(
            ["run", "delete", "ghost-run-id", "--force"],
            tmp_project,
        )
        assert result.exit_code == 1  # type: ignore[union-attr]

    def test_run_delete_json_mode_requires_force(self, tmp_project: Path) -> None:
        """JSON mode without --force → exit code 1.

        Validates: S8-10 acceptance — JSON mode rejects without --force.
        """
        run_id = "run-json-noforce"
        _create_run_with_solutions(tmp_project, run_id, num_solutions=1)

        result = _invoke_with_cwd(
            ["--json", "run", "delete", run_id],
            tmp_project,
        )
        assert result.exit_code == 1  # type: ignore[union-attr]
        output = _get_all_output(result)
        assert "--force" in output

    def test_run_delete_json_mode_with_force(self, tmp_project: Path) -> None:
        """JSON mode with --force → JSON output with deleted status.

        Validates: S8-10 acceptance — JSON mode + --force works.
        """
        run_id = "run-json-force"
        _create_run_with_solutions(tmp_project, run_id, num_solutions=2, add_evals=True)

        result = _invoke_with_cwd(
            ["--json", "run", "delete", run_id, "--force"],
            tmp_project,
        )
        assert result.exit_code == 0  # type: ignore[union-attr]
        data = _parse_json_output(result)
        assert isinstance(data, dict)
        assert data["run_id"] == run_id
        assert data["status"] == "deleted"
        assert data["solutions_deleted"] == 2
        assert data["evals_deleted"] == 2

    def test_run_delete_missing_directory(self, tmp_project: Path) -> None:
        """Delete works when run directory is missing from disk (partial state).

        Validates: S8-10 acceptance — tolerates missing run directory.
        """
        run_id = "run-no-dir"
        _create_run_with_solutions(tmp_project, run_id, num_solutions=1)

        # Remove the directory manually to simulate partial state
        run_dir = tmp_project / REVOLVER_DIR / RUNS_DIR / run_id
        shutil.rmtree(run_dir)
        assert not run_dir.exists()

        result = _invoke_with_cwd(
            ["run", "delete", run_id, "--force"],
            tmp_project,
        )
        assert result.exit_code == 0  # type: ignore[union-attr]

        # Verify DB is cleaned up
        db_path = tmp_project / REVOLVER_DIR / "revolver.db"
        conn = get_project_db(db_path)
        try:
            assert get_run(conn, run_id) is None
        finally:
            conn.close()

    def test_run_delete_user_cancels(self, tmp_project: Path) -> None:
        """User declines confirmation prompt → run is NOT deleted.

        Validates: S8-10 acceptance — interactive cancellation aborts delete.
        """
        run_id = "run-cancel-test"
        _create_run_with_solutions(tmp_project, run_id, num_solutions=1)

        interactive_runner = CliRunner()
        with patch("pathlib.Path.cwd", return_value=tmp_project):
            result = interactive_runner.invoke(
                app,
                ["run", "delete", run_id],
                input="n\n",
            )

        # Typer's confirm with abort=True causes exit code 1
        assert result.exit_code == 1

        # Verify run still exists
        db_path = tmp_project / REVOLVER_DIR / "revolver.db"
        conn = get_project_db(db_path)
        try:
            assert get_run(conn, run_id) is not None
        finally:
            conn.close()
