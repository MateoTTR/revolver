"""L1 unit tests for run/solution DB CRUD (S4-06)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.infra.db import (
    get_latest_run,
    get_project_db,
    get_resume_chain,
    get_run,
    get_solution,
    get_solutions_for_run,
    insert_dataset,
    insert_problem_version,
    insert_run,
    insert_solution,
    list_runs,
    list_solutions,
    update_run_generation_time,
    update_run_status,
    update_run_tokens,
)
from revolver.models.dataset import DatasetRegistration
from revolver.models.problem import ProblemVersion


@pytest.fixture()
def db_conn(tmp_path: Path):
    """Create a project DB for testing."""
    conn = get_project_db(tmp_path / "revolver.db")
    yield conn
    conn.close()


def _seed_problem_and_dataset(conn: sqlite3.Connection) -> None:
    """Insert a problem version and dataset required by FK constraints."""
    pv = ProblemVersion(
        tag="v1.0",
        hash="sha256:pvhash",
        created_at=datetime(2026, 3, 14, tzinfo=UTC),
    )
    insert_problem_version(conn, pv)
    reg = DatasetRegistration(
        name="train-small",
        path="/data/train",
        storage="reference",
        split="train",
        instance_count=10,
        global_hash="sha256:dshash",
        created_at=datetime(2026, 3, 14, tzinfo=UTC),
    )
    insert_dataset(conn, reg)


def _insert_test_run(
    conn: sqlite3.Connection,
    run_id: str = "run-20260314-120000",
    *,
    problem_version: str = "v1.0",
    llm: str = "test-llm",
    dataset: str = "train-small",
    iterations: int = 100,
    problem_hash: str = "sha256:pvhash",
    dataset_hash: str = "sha256:dshash",
    llm_model: str = "test-model",
    created_at: datetime | None = None,
    resumed_from: str | None = None,
    status: str = "running",
    generation_time_s: float | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    config_snapshot: str | None = None,
) -> None:
    """Helper to insert a run with defaults."""
    insert_run(
        conn,
        run_id=run_id,
        problem_version=problem_version,
        llm=llm,
        dataset=dataset,
        iterations=iterations,
        problem_hash=problem_hash,
        dataset_hash=dataset_hash,
        llm_model=llm_model,
        created_at=created_at or datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC),
        resumed_from=resumed_from,
        status=status,
        generation_time_s=generation_time_s,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        config_snapshot=config_snapshot,
    )


# ── Run CRUD tests ───────────────────────────────────────────────────────────


class TestInsertAndGetRun:
    """Tests for insert_run and get_run."""

    @pytest.mark.unit
    def test_insert_and_get_round_trip(self, db_conn: sqlite3.Connection) -> None:
        """Insert a run, then retrieve it by ID."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, config_snapshot="llm:\n  model: test")
        result = get_run(db_conn, "run-20260314-120000")
        assert result is not None
        assert result["id"] == "run-20260314-120000"
        assert result["problem_version"] == "v1.0"
        assert result["llm"] == "test-llm"
        assert result["dataset"] == "train-small"
        assert result["iterations"] == 100
        assert result["status"] == "running"
        assert result["problem_hash"] == "sha256:pvhash"
        assert result["dataset_hash"] == "sha256:dshash"
        assert result["llm_model"] == "test-model"
        assert result["config_snapshot"] == "llm:\n  model: test"

    @pytest.mark.unit
    def test_nonexistent_returns_none(self, db_conn: sqlite3.Connection) -> None:
        """Getting a non-existent run returns None."""
        result = get_run(db_conn, "nonexistent")
        assert result is None

    @pytest.mark.unit
    def test_with_resumed_from(self, db_conn: sqlite3.Connection) -> None:
        """Insert a run with resumed_from referencing a parent run."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, run_id="run-parent", status="completed")
        _insert_test_run(
            db_conn,
            run_id="run-child",
            resumed_from="run-parent",
            created_at=datetime(2026, 3, 14, 13, 0, 0, tzinfo=UTC),
        )
        result = get_run(db_conn, "run-child")
        assert result is not None
        assert result["resumed_from"] == "run-parent"


class TestUpdateRunStatus:
    """Tests for update_run_status."""

    @pytest.mark.unit
    def test_status_transitions(self, db_conn: sqlite3.Connection) -> None:
        """Update run status from running to completed."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        result = get_run(db_conn, "run-20260314-120000")
        assert result is not None
        assert result["status"] == "running"

        update_run_status(db_conn, "run-20260314-120000", "completed")
        result = get_run(db_conn, "run-20260314-120000")
        assert result is not None
        assert result["status"] == "completed"

    @pytest.mark.unit
    def test_status_to_interrupted(self, db_conn: sqlite3.Connection) -> None:
        """Update run status to interrupted."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        update_run_status(db_conn, "run-20260314-120000", "interrupted")
        result = get_run(db_conn, "run-20260314-120000")
        assert result is not None
        assert result["status"] == "interrupted"

    @pytest.mark.unit
    def test_status_to_completed_with_errors(self, db_conn: sqlite3.Connection) -> None:
        """Update run status to completed_with_errors."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        update_run_status(db_conn, "run-20260314-120000", "completed_with_errors")
        result = get_run(db_conn, "run-20260314-120000")
        assert result is not None
        assert result["status"] == "completed_with_errors"


class TestUpdateRunTokens:
    """Tests for update_run_tokens."""

    @pytest.mark.unit
    def test_token_columns_updated(self, db_conn: sqlite3.Connection) -> None:
        """Update token usage columns for a run."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        # Initially no tokens
        result = get_run(db_conn, "run-20260314-120000")
        assert result is not None
        assert result["prompt_tokens"] is None
        assert result["completion_tokens"] is None

        update_run_tokens(db_conn, "run-20260314-120000", 5000, 2000)
        result = get_run(db_conn, "run-20260314-120000")
        assert result is not None
        assert result["prompt_tokens"] == 5000
        assert result["completion_tokens"] == 2000


class TestListRuns:
    """Tests for list_runs."""

    @pytest.mark.unit
    def test_list_no_filter(self, db_conn: sqlite3.Connection) -> None:
        """list_runs returns all runs when no filter applied."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(
            db_conn,
            run_id="run-1",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-2",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        result = list_runs(db_conn)
        assert len(result) == 2
        # Ordered by created_at DESC
        assert result[0]["id"] == "run-2"
        assert result[1]["id"] == "run-1"

    @pytest.mark.unit
    def test_list_filter_by_version(self, db_conn: sqlite3.Connection) -> None:
        """list_runs filters by problem version."""
        _seed_problem_and_dataset(db_conn)
        # Add second problem version and dataset
        pv2 = ProblemVersion(
            tag="v2.0",
            hash="sha256:pv2hash",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
        )
        insert_problem_version(db_conn, pv2)
        _insert_test_run(
            db_conn,
            run_id="run-v1",
            problem_version="v1.0",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-v2",
            problem_version="v2.0",
            problem_hash="sha256:pv2hash",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        result = list_runs(db_conn, version="v1.0")
        assert len(result) == 1
        assert result[0]["id"] == "run-v1"

    @pytest.mark.unit
    def test_list_filter_by_llm(self, db_conn: sqlite3.Connection) -> None:
        """list_runs filters by LLM name."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(
            db_conn,
            run_id="run-llm1",
            llm="llm-a",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-llm2",
            llm="llm-b",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        result = list_runs(db_conn, llm="llm-a")
        assert len(result) == 1
        assert result[0]["id"] == "run-llm1"

    @pytest.mark.unit
    def test_list_filter_by_status(self, db_conn: sqlite3.Connection) -> None:
        """list_runs filters by status."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(
            db_conn,
            run_id="run-running",
            status="running",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-completed",
            status="completed",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        result = list_runs(db_conn, status="completed")
        assert len(result) == 1
        assert result[0]["id"] == "run-completed"

    @pytest.mark.unit
    def test_list_filter_combined(self, db_conn: sqlite3.Connection) -> None:
        """list_runs combines multiple filters."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(
            db_conn,
            run_id="run-match",
            llm="llm-x",
            status="completed",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-nomatch",
            llm="llm-y",
            status="completed",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        result = list_runs(db_conn, llm="llm-x", status="completed")
        assert len(result) == 1
        assert result[0]["id"] == "run-match"

    @pytest.mark.unit
    def test_list_empty(self, db_conn: sqlite3.Connection) -> None:
        """list_runs returns empty list when no runs exist."""
        result = list_runs(db_conn)
        assert result == []

    @pytest.mark.unit
    def test_list_includes_best_score(self, db_conn: sqlite3.Connection) -> None:
        """list_runs includes best_score from solutions JOIN."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
        )
        result = list_runs(db_conn)
        assert len(result) == 1
        assert result[0]["best_score"] == 0.95

    @pytest.mark.unit
    def test_list_includes_alias(self, db_conn: sqlite3.Connection) -> None:
        """list_runs includes alias from rank-1 solution (FB-07)."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
            alias="best-v1",
        )
        result = list_runs(db_conn)
        assert len(result) == 1
        assert result[0]["alias"] == "best-v1"

    @pytest.mark.unit
    def test_list_alias_none_when_no_alias(self, db_conn: sqlite3.Connection) -> None:
        """list_runs returns None alias when rank-1 solution has no alias."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
        )
        result = list_runs(db_conn)
        assert len(result) == 1
        assert result[0]["alias"] is None

    @pytest.mark.unit
    def test_list_alias_none_when_no_solutions(self, db_conn: sqlite3.Connection) -> None:
        """list_runs returns None alias when run has no solutions."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="running")
        result = list_runs(db_conn)
        assert len(result) == 1
        assert result[0]["alias"] is None


class TestGetLatestRun:
    """Tests for get_latest_run."""

    @pytest.mark.unit
    def test_returns_most_recent(self, db_conn: sqlite3.Connection) -> None:
        """get_latest_run returns the most recent run by created_at."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(
            db_conn,
            run_id="run-old",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-new",
            created_at=datetime(2026, 3, 14, 14, 0, 0, tzinfo=UTC),
        )
        result = get_latest_run(db_conn)
        assert result is not None
        assert result["id"] == "run-new"

    @pytest.mark.unit
    def test_empty_returns_none(self, db_conn: sqlite3.Connection) -> None:
        """get_latest_run returns None when no runs exist."""
        result = get_latest_run(db_conn)
        assert result is None


class TestGetResumeChain:
    """Tests for get_resume_chain."""

    @pytest.mark.unit
    def test_three_level_chain(self, db_conn: sqlite3.Connection) -> None:
        """get_resume_chain resolves a 3-level ancestry chain."""
        _seed_problem_and_dataset(db_conn)
        # grandparent -> parent -> child
        _insert_test_run(
            db_conn,
            run_id="run-grandparent",
            status="completed",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-parent",
            resumed_from="run-grandparent",
            status="completed",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-child",
            resumed_from="run-parent",
            created_at=datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC),
        )
        chain = get_resume_chain(db_conn, "run-child")
        assert chain == ["run-grandparent", "run-parent", "run-child"]

    @pytest.mark.unit
    def test_single_run_no_ancestry(self, db_conn: sqlite3.Connection) -> None:
        """get_resume_chain returns just the run itself when no ancestry."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, run_id="run-solo")
        chain = get_resume_chain(db_conn, "run-solo")
        assert chain == ["run-solo"]

    @pytest.mark.unit
    def test_two_level_chain(self, db_conn: sqlite3.Connection) -> None:
        """get_resume_chain resolves a 2-level ancestry chain."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(
            db_conn,
            run_id="run-parent",
            status="completed",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-child",
            resumed_from="run-parent",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        chain = get_resume_chain(db_conn, "run-child")
        assert chain == ["run-parent", "run-child"]

    @pytest.mark.unit
    def test_resume_chain_nonexistent(self, db_conn: sqlite3.Connection) -> None:
        """get_resume_chain returns empty list for a non-existent run ID."""
        chain = get_resume_chain(db_conn, "nonexistent-run")
        assert chain == []


class TestUpdateRunGenerationTime:
    """Tests for update_run_generation_time with completed_with_errors status."""

    @pytest.mark.unit
    def test_generation_time_with_completed_with_errors(self, db_conn: sqlite3.Connection) -> None:
        """update_run_generation_time sets both time and completed_with_errors status."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        update_run_generation_time(
            db_conn, "run-20260314-120000", 42.5, status="completed_with_errors"
        )
        result = get_run(db_conn, "run-20260314-120000")
        assert result is not None
        assert result["status"] == "completed_with_errors"
        assert result["generation_time_s"] == 42.5


class TestUpdateRunTokensEdgeCases:
    """Edge-case tests for update_run_tokens."""

    @pytest.mark.unit
    def test_update_tokens_nonexistent_run(self, db_conn: sqlite3.Connection) -> None:
        """update_run_tokens on a non-existent run is a no-op (0 rows affected)."""
        # Should not raise — just updates zero rows.
        update_run_tokens(db_conn, "nonexistent-run", 1000, 500)
        # Verify no run was created
        result = get_run(db_conn, "nonexistent-run")
        assert result is None


# ── Solution CRUD tests ──────────────────────────────────────────────────────


class TestInsertAndGetSolution:
    """Tests for insert_solution and get_solution."""

    @pytest.mark.unit
    def test_insert_and_get_round_trip(self, db_conn: sqlite3.Connection) -> None:
        """Insert a solution, then retrieve it by ID."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-20260314-120000",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
            alias="best-v1",
        )
        result = get_solution(db_conn, "sol-20260314-120000")
        assert result is not None
        assert result.id == "sol-20260314-120000"
        assert result.run_id == "run-20260314-120000"
        assert result.rank == 1
        assert result.best_score == 0.95
        assert result.alias == "best-v1"

    @pytest.mark.unit
    def test_nonexistent_returns_none(self, db_conn: sqlite3.Connection) -> None:
        """Getting a non-existent solution returns None."""
        result = get_solution(db_conn, "nonexistent")
        assert result is None

    @pytest.mark.unit
    def test_nullable_alias(self, db_conn: sqlite3.Connection) -> None:
        """Solution with None alias is stored and retrieved."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.90,
        )
        result = get_solution(db_conn, "sol-1")
        assert result is not None
        assert result.alias is None

    @pytest.mark.unit
    def test_nullable_best_score(self, db_conn: sqlite3.Connection) -> None:
        """Solution with None best_score is stored and retrieved."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
        )
        result = get_solution(db_conn, "sol-1")
        assert result is not None
        assert result.best_score is None


class TestGetSolutionByAlias:
    """Tests for get_solution alias resolution."""

    @pytest.mark.unit
    def test_resolves_by_alias(self, db_conn: sqlite3.Connection) -> None:
        """get_solution falls back to alias when ID not found."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-20260314-120000",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
            alias="my-alias",
        )
        result = get_solution(db_conn, "my-alias")
        assert result is not None
        assert result.id == "sol-20260314-120000"
        assert result.alias == "my-alias"

    @pytest.mark.unit
    def test_id_takes_precedence(self, db_conn: sqlite3.Connection) -> None:
        """get_solution prefers ID lookup over alias."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            alias="sol-1-alias",
        )
        # Should find by ID, not alias
        result = get_solution(db_conn, "sol-1")
        assert result is not None
        assert result.id == "sol-1"


class TestGetSolutionsForRun:
    """Tests for get_solutions_for_run."""

    @pytest.mark.unit
    def test_multiple_solutions_for_run(self, db_conn: sqlite3.Connection) -> None:
        """get_solutions_for_run returns all solutions ordered by rank."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-2",
            run_id="run-20260314-120000",
            rank=2,
            best_score=0.90,
        )
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
        )
        result = get_solutions_for_run(db_conn, "run-20260314-120000")
        assert len(result) == 2
        assert result[0].rank == 1
        assert result[1].rank == 2

    @pytest.mark.unit
    def test_empty_when_no_solutions(self, db_conn: sqlite3.Connection) -> None:
        """get_solutions_for_run returns empty list when run has no solutions."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        result = get_solutions_for_run(db_conn, "run-20260314-120000")
        assert result == []


class TestSolutionUniqueRunRank:
    """Tests for UNIQUE(run_id, rank) constraint."""

    @pytest.mark.unit
    def test_unique_run_rank_enforced(self, db_conn: sqlite3.Connection) -> None:
        """Inserting duplicate (run_id, rank) raises IntegrityError."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
        )
        with pytest.raises(sqlite3.IntegrityError):
            insert_solution(
                db_conn,
                solution_id="sol-2",
                run_id="run-20260314-120000",
                rank=1,
                best_score=0.90,
            )


class TestListSolutions:
    """Tests for list_solutions."""

    @pytest.mark.unit
    def test_list_no_filter(self, db_conn: sqlite3.Connection) -> None:
        """list_solutions returns all solutions when no filter applied."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
        )
        insert_solution(
            db_conn,
            solution_id="sol-2",
            run_id="run-20260314-120000",
            rank=2,
            best_score=0.90,
        )
        result = list_solutions(db_conn)
        assert len(result) == 2

    @pytest.mark.unit
    def test_list_filter_by_version(self, db_conn: sqlite3.Connection) -> None:
        """list_solutions filters by problem version via run JOIN."""
        _seed_problem_and_dataset(db_conn)
        pv2 = ProblemVersion(
            tag="v2.0",
            hash="sha256:pv2hash",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
        )
        insert_problem_version(db_conn, pv2)
        _insert_test_run(
            db_conn,
            run_id="run-v1",
            problem_version="v1.0",
            status="completed",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-v2",
            problem_version="v2.0",
            problem_hash="sha256:pv2hash",
            status="completed",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        insert_solution(
            db_conn,
            solution_id="sol-v1",
            run_id="run-v1",
            rank=1,
        )
        insert_solution(
            db_conn,
            solution_id="sol-v2",
            run_id="run-v2",
            rank=1,
        )
        result = list_solutions(db_conn, version="v1.0")
        assert len(result) == 1
        assert result[0]["id"] == "sol-v1"

    @pytest.mark.unit
    def test_list_filter_by_llm(self, db_conn: sqlite3.Connection) -> None:
        """list_solutions filters by LLM name via run JOIN."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(
            db_conn,
            run_id="run-a",
            llm="llm-a",
            status="completed",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-b",
            llm="llm-b",
            status="completed",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        insert_solution(
            db_conn,
            solution_id="sol-a",
            run_id="run-a",
            rank=1,
        )
        insert_solution(
            db_conn,
            solution_id="sol-b",
            run_id="run-b",
            rank=1,
        )
        result = list_solutions(db_conn, llm="llm-a")
        assert len(result) == 1
        assert result[0]["id"] == "sol-a"

    @pytest.mark.unit
    def test_list_filter_by_rank(self, db_conn: sqlite3.Connection) -> None:
        """list_solutions filters by rank."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn, status="completed")
        insert_solution(
            db_conn,
            solution_id="sol-r1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
        )
        insert_solution(
            db_conn,
            solution_id="sol-r2",
            run_id="run-20260314-120000",
            rank=2,
            best_score=0.90,
        )
        result = list_solutions(db_conn, rank=1)
        assert len(result) == 1
        assert result[0]["id"] == "sol-r1"

    @pytest.mark.unit
    def test_list_empty(self, db_conn: sqlite3.Connection) -> None:
        """list_solutions returns empty list when no solutions exist."""
        result = list_solutions(db_conn)
        assert result == []

    @pytest.mark.unit
    def test_list_filter_combined(self, db_conn: sqlite3.Connection) -> None:
        """list_solutions combines multiple filters."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(
            db_conn,
            run_id="run-match",
            llm="llm-x",
            status="completed",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-nomatch",
            llm="llm-y",
            status="completed",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        insert_solution(
            db_conn,
            solution_id="sol-match",
            run_id="run-match",
            rank=1,
        )
        insert_solution(
            db_conn,
            solution_id="sol-nomatch",
            run_id="run-nomatch",
            rank=1,
        )
        result = list_solutions(db_conn, version="v1.0", llm="llm-x", rank=1)
        assert len(result) == 1
        assert result[0]["id"] == "sol-match"
