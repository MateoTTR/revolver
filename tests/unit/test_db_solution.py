"""L1 unit tests for solution DB extensions (S5-03).

Tests cover:
- update_solution_alias: set alias, verify stored
- Alias uniqueness: two solutions with same alias → IntegrityError
- get_solution_by_alias: resolve alias to solution
- get_solution_by_alias not found: returns None
- get_solutions_for_run: sibling query (2 solutions from same run)
- list_solutions no filter: all solutions returned
- list_solutions with filters: version/llm/rank filters work
- get_solution_detail with eval: JOIN includes eval data
- get_solution_detail without eval: eval fields are None

Traceable to: FR-SOL-001..013, DES-001 §3.6, sprint-005 S5-03.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.infra.db import (
    get_project_db,
    get_solution,
    get_solution_by_alias,
    get_solution_detail,
    get_solutions_for_run,
    insert_dataset,
    insert_problem_version,
    insert_run,
    insert_solution,
    list_solutions,
    update_solution_alias,
)
from revolver.models.dataset import DatasetRegistration
from revolver.models.problem import ProblemVersion


@pytest.fixture()
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a project DB for testing."""
    conn = get_project_db(tmp_path / "revolver.db")
    yield conn  # type: ignore[misc]
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
    status: str = "completed",
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
        config_snapshot=config_snapshot,
    )


def _insert_eval_metadata(
    conn: sqlite3.Connection,
    eval_id: str,
    solution_id: str,
    dataset_name: str = "train-small",
    instance_count: int = 10,
    instances_solved: int = 8,
    eval_time_s: float = 5.0,
) -> None:
    """Directly insert eval_metadata for testing JOIN queries."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """\
        INSERT INTO eval_metadata (
            eval_id, solution_id, dataset_name,
            instance_count, instances_solved, eval_time_s, evaluated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_id, solution_id, dataset_name, instance_count, instances_solved, eval_time_s, now),
    )
    conn.commit()


# ── update_solution_alias tests ──────────────────────────────────────────────


class TestUpdateSolutionAlias:
    """Tests for update_solution_alias."""

    @pytest.mark.unit
    def test_update_alias(self, db_conn: sqlite3.Connection) -> None:
        """Set alias on a solution, verify it's stored."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
        )
        update_solution_alias(db_conn, "sol-1", "my-best")

        result = get_solution(db_conn, "sol-1")
        assert result is not None
        assert result.alias == "my-best"

    @pytest.mark.unit
    def test_alias_uniqueness(self, db_conn: sqlite3.Connection) -> None:
        """Two solutions with same alias raises IntegrityError."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
            alias="taken-alias",
        )
        insert_solution(
            db_conn,
            solution_id="sol-2",
            run_id="run-20260314-120000",
            rank=2,
            best_score=0.90,
        )
        with pytest.raises(sqlite3.IntegrityError):
            update_solution_alias(db_conn, "sol-2", "taken-alias")

    @pytest.mark.unit
    def test_update_alias_not_found(self, db_conn: sqlite3.Connection) -> None:
        """Updating alias on a non-existent solution raises KeyError."""
        with pytest.raises(KeyError, match="Solution not found"):
            update_solution_alias(db_conn, "nonexistent", "my-alias")


# ── get_solution_by_alias tests ──────────────────────────────────────────────


class TestGetSolutionByAlias:
    """Tests for get_solution_by_alias."""

    @pytest.mark.unit
    def test_get_by_alias(self, db_conn: sqlite3.Connection) -> None:
        """Resolve alias to solution."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
            alias="best-v1",
        )
        result = get_solution_by_alias(db_conn, "best-v1")
        assert result is not None
        assert result.id == "sol-1"
        assert result.alias == "best-v1"
        assert result.best_score == 0.95

    @pytest.mark.unit
    def test_get_by_alias_not_found(self, db_conn: sqlite3.Connection) -> None:
        """get_solution_by_alias returns None when alias doesn't exist."""
        result = get_solution_by_alias(db_conn, "nonexistent")
        assert result is None


# ── get_solutions_for_run (siblings) tests ───────────────────────────────────


class TestGetSolutionsSiblings:
    """Tests for get_solutions_for_run (sibling query)."""

    @pytest.mark.unit
    def test_siblings(self, db_conn: sqlite3.Connection) -> None:
        """Two solutions from same run are returned, ordered by rank."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
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
        assert result[0].id == "sol-1"
        assert result[1].rank == 2
        assert result[1].id == "sol-2"


# ── list_solutions tests ────────────────────────────────────────────────────


class TestListSolutions:
    """Tests for list_solutions with filters."""

    @pytest.mark.unit
    def test_list_solutions_no_filter(self, db_conn: sqlite3.Connection) -> None:
        """All solutions returned when no filter applied."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
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
    def test_list_solutions_with_filters(self, db_conn: sqlite3.Connection) -> None:
        """version/llm/rank filters correctly narrow results."""
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
            llm="llm-a",
            created_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        )
        _insert_test_run(
            db_conn,
            run_id="run-v2",
            problem_version="v2.0",
            problem_hash="sha256:pv2hash",
            llm="llm-b",
            created_at=datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC),
        )
        insert_solution(db_conn, solution_id="sol-v1-r1", run_id="run-v1", rank=1)
        insert_solution(db_conn, solution_id="sol-v1-r2", run_id="run-v1", rank=2)
        insert_solution(db_conn, solution_id="sol-v2-r1", run_id="run-v2", rank=1)

        # Filter by version
        result = list_solutions(db_conn, version="v1.0")
        assert len(result) == 2
        assert all(r["problem_version"] == "v1.0" for r in result)

        # Filter by llm
        result = list_solutions(db_conn, llm="llm-b")
        assert len(result) == 1
        assert result[0]["id"] == "sol-v2-r1"

        # Filter by rank
        result = list_solutions(db_conn, rank=1)
        assert len(result) == 2

        # Combined filters
        result = list_solutions(db_conn, version="v1.0", rank=1)
        assert len(result) == 1
        assert result[0]["id"] == "sol-v1-r1"


# ── get_solution_detail tests ───────────────────────────────────────────────


class TestGetSolutionDetail:
    """Tests for get_solution_detail."""

    @pytest.mark.unit
    def test_solution_detail_with_eval(self, db_conn: sqlite3.Connection) -> None:
        """JOIN includes eval data when eval_metadata exists."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(
            db_conn,
            config_snapshot="llm:\n  model: test",
        )
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
            alias="best-v1",
        )
        _insert_eval_metadata(
            db_conn,
            eval_id="eval-1",
            solution_id="sol-1",
            instance_count=10,
            instances_solved=8,
        )

        result = get_solution_detail(db_conn, "sol-1")
        assert result is not None
        assert result["id"] == "sol-1"
        assert result["run_id"] == "run-20260314-120000"
        assert result["rank"] == 1
        assert result["best_score"] == 0.95
        assert result["alias"] == "best-v1"
        # Run lineage
        assert result["problem_version"] == "v1.0"
        assert result["llm"] == "test-llm"
        assert result["dataset"] == "train-small"
        assert result["run_status"] == "completed"
        assert result["config_snapshot"] == "llm:\n  model: test"
        assert result["llm_model"] == "test-model"
        # Eval metadata
        assert result["eval_id"] == "eval-1"
        assert result["instances_solved"] == 8
        assert result["instance_count"] == 10

    @pytest.mark.unit
    def test_solution_detail_without_eval(self, db_conn: sqlite3.Connection) -> None:
        """Eval fields are None when no eval_metadata exists."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            best_score=0.95,
        )

        result = get_solution_detail(db_conn, "sol-1")
        assert result is not None
        assert result["id"] == "sol-1"
        assert result["problem_version"] == "v1.0"
        # Eval fields should be None (LEFT JOIN)
        assert result["eval_id"] is None
        assert result["instances_solved"] is None
        assert result["instance_count"] is None

    @pytest.mark.unit
    def test_solution_detail_by_alias(self, db_conn: sqlite3.Connection) -> None:
        """get_solution_detail resolves by alias."""
        _seed_problem_and_dataset(db_conn)
        _insert_test_run(db_conn)
        insert_solution(
            db_conn,
            solution_id="sol-1",
            run_id="run-20260314-120000",
            rank=1,
            alias="my-sol",
        )

        result = get_solution_detail(db_conn, "my-sol")
        assert result is not None
        assert result["id"] == "sol-1"
        assert result["alias"] == "my-sol"

    @pytest.mark.unit
    def test_solution_detail_not_found(self, db_conn: sqlite3.Connection) -> None:
        """get_solution_detail returns None when solution doesn't exist."""
        result = get_solution_detail(db_conn, "nonexistent")
        assert result is None
