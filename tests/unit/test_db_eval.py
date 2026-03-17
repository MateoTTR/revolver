"""L1 unit tests for eval CRUD in revolver.infra.db (S5-02)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.infra.db import (
    delete_eval,
    get_eval_instances,
    get_eval_metadata,
    get_project_db,
    insert_dataset,
    insert_eval_instance,
    insert_eval_metadata,
    insert_problem_version,
    insert_run,
    insert_solution,
)
from revolver.models.dataset import DatasetRegistration
from revolver.models.eval import EvalMetadata
from revolver.models.problem import ProblemVersion


@pytest.fixture()
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a project DB for testing."""
    conn = get_project_db(tmp_path / "revolver.db")
    yield conn  # type: ignore[misc]
    conn.close()


def _seed_prerequisites(conn: sqlite3.Connection) -> None:
    """Insert problem version, dataset, run, and solution required by FK constraints."""
    pv = ProblemVersion(
        tag="v1.0",
        hash="sha256:pvhash",
        created_at=datetime(2026, 3, 14, tzinfo=UTC),
    )
    insert_problem_version(conn, pv)

    reg = DatasetRegistration(
        name="eval-bench",
        path="/data/eval",
        storage="reference",
        split="eval",
        instance_count=100,
        global_hash="sha256:dshash",
        created_at=datetime(2026, 3, 14, tzinfo=UTC),
    )
    insert_dataset(conn, reg)

    insert_run(
        conn,
        run_id="run-20260314-120000",
        problem_version="v1.0",
        llm="test-llm",
        dataset="eval-bench",
        iterations=100,
        problem_hash="sha256:pvhash",
        dataset_hash="sha256:dshash",
        llm_model="test-model",
        created_at=datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC),
        status="completed",
    )

    insert_solution(
        conn,
        solution_id="sol-20260314-120000",
        run_id="run-20260314-120000",
        rank=1,
        best_score=0.95,
    )


def _make_eval_metadata(
    eval_id: str = "eval-20260315-100000",
    solution_id: str = "sol-20260314-120000",
    dataset_name: str = "eval-bench",
    instance_count: int = 3,
    instances_solved: int = 2,
    eval_time_s: float | None = 5.0,
    user_aggregates: dict[str, float] | None = None,
) -> EvalMetadata:
    """Helper to create an EvalMetadata instance with sensible defaults."""
    return EvalMetadata(
        eval_id=eval_id,
        solution_id=solution_id,
        dataset_name=dataset_name,
        instance_count=instance_count,
        instances_solved=instances_solved,
        eval_time_s=eval_time_s,
        evaluated_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
        user_aggregates=user_aggregates,
    )


# ── insert_eval_metadata / get_eval_metadata ────────────────────────────────


class TestInsertAndGetEvalMetadata:
    """Tests for insert_eval_metadata and get_eval_metadata."""

    @pytest.mark.unit
    def test_insert_and_get_round_trip(self, db_conn: sqlite3.Connection) -> None:
        """Insert eval metadata, then retrieve it by (solution_id, dataset_name)."""
        _seed_prerequisites(db_conn)
        meta = _make_eval_metadata()
        insert_eval_metadata(db_conn, meta)

        result = get_eval_metadata(db_conn, "sol-20260314-120000", "eval-bench")
        assert result is not None
        assert result.eval_id == "eval-20260315-100000"
        assert result.solution_id == "sol-20260314-120000"
        assert result.dataset_name == "eval-bench"
        assert result.instance_count == 3
        assert result.instances_solved == 2
        assert result.eval_time_s == 5.0
        assert result.user_aggregates is None
        assert result.evaluated_at == datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)

    @pytest.mark.unit
    def test_with_user_aggregates(self, db_conn: sqlite3.Connection) -> None:
        """Eval metadata with user_aggregates is stored and retrieved as dict."""
        _seed_prerequisites(db_conn)
        meta = _make_eval_metadata(
            user_aggregates={"combined_score": 0.72, "makespan": 155.3},
        )
        insert_eval_metadata(db_conn, meta)

        result = get_eval_metadata(db_conn, "sol-20260314-120000", "eval-bench")
        assert result is not None
        assert result.user_aggregates == {"combined_score": 0.72, "makespan": 155.3}

    @pytest.mark.unit
    def test_nullable_eval_time(self, db_conn: sqlite3.Connection) -> None:
        """Eval metadata with None eval_time_s is stored and retrieved."""
        _seed_prerequisites(db_conn)
        meta = _make_eval_metadata(eval_time_s=None)
        insert_eval_metadata(db_conn, meta)

        result = get_eval_metadata(db_conn, "sol-20260314-120000", "eval-bench")
        assert result is not None
        assert result.eval_time_s is None

    @pytest.mark.unit
    def test_nonexistent_returns_none(self, db_conn: sqlite3.Connection) -> None:
        """get_eval_metadata returns None when no evaluation exists."""
        result = get_eval_metadata(db_conn, "nonexistent-sol", "nonexistent-ds")
        assert result is None

    @pytest.mark.unit
    def test_unique_constraint_enforced(self, db_conn: sqlite3.Connection) -> None:
        """Inserting duplicate (solution_id, dataset_name) raises IntegrityError."""
        _seed_prerequisites(db_conn)
        meta1 = _make_eval_metadata(eval_id="eval-1")
        insert_eval_metadata(db_conn, meta1)

        meta2 = _make_eval_metadata(eval_id="eval-2")
        with pytest.raises(sqlite3.IntegrityError):
            insert_eval_metadata(db_conn, meta2)


# ── insert_eval_instance / get_eval_instances ───────────────────────────────


class TestInsertAndGetEvalInstances:
    """Tests for insert_eval_instance and get_eval_instances."""

    @pytest.mark.unit
    def test_insert_and_get_solved(self, db_conn: sqlite3.Connection) -> None:
        """Insert a solved instance row and retrieve it."""
        _seed_prerequisites(db_conn)
        insert_eval_metadata(db_conn, _make_eval_metadata())

        insert_eval_instance(
            db_conn,
            eval_id="eval-20260315-100000",
            instance_id="inst-001",
            metric_name="score",
            value=0.95,
            status="solved",
            error_message=None,
            compute_time_s=1.5,
        )

        rows = get_eval_instances(db_conn, "eval-20260315-100000")
        assert len(rows) == 1
        instance_id, metric_name, value, status, error_msg, compute_time = rows[0]
        assert instance_id == "inst-001"
        assert metric_name == "score"
        assert value == 0.95
        assert status == "solved"
        assert error_msg is None
        assert compute_time == 1.5

    @pytest.mark.unit
    def test_insert_failed_instance(self, db_conn: sqlite3.Connection) -> None:
        """Insert a failed instance row with error message and null value."""
        _seed_prerequisites(db_conn)
        insert_eval_metadata(db_conn, _make_eval_metadata())

        insert_eval_instance(
            db_conn,
            eval_id="eval-20260315-100000",
            instance_id="inst-002",
            metric_name="score",
            value=None,
            status="failed",
            error_message="ZeroDivisionError",
            compute_time_s=0.1,
        )

        rows = get_eval_instances(db_conn, "eval-20260315-100000")
        assert len(rows) == 1
        _, _, value, status, error_msg, _ = rows[0]
        assert value is None
        assert status == "failed"
        assert error_msg == "ZeroDivisionError"

    @pytest.mark.unit
    def test_insert_timeout_instance(self, db_conn: sqlite3.Connection) -> None:
        """Insert a timeout instance row."""
        _seed_prerequisites(db_conn)
        insert_eval_metadata(db_conn, _make_eval_metadata())

        insert_eval_instance(
            db_conn,
            eval_id="eval-20260315-100000",
            instance_id="inst-003",
            metric_name="score",
            value=None,
            status="timeout",
            error_message=None,
            compute_time_s=300.0,
        )

        rows = get_eval_instances(db_conn, "eval-20260315-100000")
        assert len(rows) == 1
        _, _, _, status, _, _ = rows[0]
        assert status == "timeout"

    @pytest.mark.unit
    def test_multiple_metrics_per_instance(self, db_conn: sqlite3.Connection) -> None:
        """Multiple metrics for the same instance produce multiple rows."""
        _seed_prerequisites(db_conn)
        insert_eval_metadata(db_conn, _make_eval_metadata())

        insert_eval_instance(
            db_conn,
            eval_id="eval-20260315-100000",
            instance_id="inst-001",
            metric_name="makespan",
            value=155.0,
            status="solved",
            error_message=None,
            compute_time_s=1.5,
        )
        insert_eval_instance(
            db_conn,
            eval_id="eval-20260315-100000",
            instance_id="inst-001",
            metric_name="score",
            value=0.95,
            status="solved",
            error_message=None,
            compute_time_s=1.5,
        )

        rows = get_eval_instances(db_conn, "eval-20260315-100000")
        assert len(rows) == 2
        # Ordered by instance_id, metric_name
        assert rows[0][1] == "makespan"
        assert rows[1][1] == "score"

    @pytest.mark.unit
    def test_multiple_instances(self, db_conn: sqlite3.Connection) -> None:
        """Multiple instances are stored and retrieved in order."""
        _seed_prerequisites(db_conn)
        insert_eval_metadata(db_conn, _make_eval_metadata())

        for i in range(3):
            insert_eval_instance(
                db_conn,
                eval_id="eval-20260315-100000",
                instance_id=f"inst-{i:03d}",
                metric_name="score",
                value=0.8 + i * 0.05,
                status="solved",
                error_message=None,
                compute_time_s=1.0,
            )

        rows = get_eval_instances(db_conn, "eval-20260315-100000")
        assert len(rows) == 3
        assert rows[0][0] == "inst-000"
        assert rows[1][0] == "inst-001"
        assert rows[2][0] == "inst-002"

    @pytest.mark.unit
    def test_empty_when_no_instances(self, db_conn: sqlite3.Connection) -> None:
        """get_eval_instances returns empty list when no instances exist."""
        rows = get_eval_instances(db_conn, "nonexistent-eval")
        assert rows == []


# ── delete_eval ─────────────────────────────────────────────────────────────


class TestDeleteEval:
    """Tests for delete_eval (cascade delete)."""

    @pytest.mark.unit
    def test_cascade_delete(self, db_conn: sqlite3.Connection) -> None:
        """delete_eval removes both metadata and all instance rows."""
        _seed_prerequisites(db_conn)
        insert_eval_metadata(db_conn, _make_eval_metadata())

        # Insert some instance rows
        for i in range(3):
            insert_eval_instance(
                db_conn,
                eval_id="eval-20260315-100000",
                instance_id=f"inst-{i:03d}",
                metric_name="score",
                value=0.9,
                status="solved",
                error_message=None,
                compute_time_s=1.0,
            )

        # Verify they exist
        assert get_eval_metadata(db_conn, "sol-20260314-120000", "eval-bench") is not None
        assert len(get_eval_instances(db_conn, "eval-20260315-100000")) == 3

        # Delete
        delete_eval(db_conn, "eval-20260315-100000")

        # Verify both are gone
        assert get_eval_metadata(db_conn, "sol-20260314-120000", "eval-bench") is None
        assert get_eval_instances(db_conn, "eval-20260315-100000") == []

    @pytest.mark.unit
    def test_delete_nonexistent_is_noop(self, db_conn: sqlite3.Connection) -> None:
        """delete_eval on a non-existent eval_id is a no-op (no error)."""
        # Should not raise
        delete_eval(db_conn, "nonexistent-eval")

    @pytest.mark.unit
    def test_delete_allows_reinsertion(self, db_conn: sqlite3.Connection) -> None:
        """After delete_eval, the same (solution_id, dataset_name) can be reinserted."""
        _seed_prerequisites(db_conn)
        meta1 = _make_eval_metadata(eval_id="eval-1")
        insert_eval_metadata(db_conn, meta1)

        # Delete
        delete_eval(db_conn, "eval-1")

        # Re-insert with a new eval_id
        meta2 = _make_eval_metadata(eval_id="eval-2")
        insert_eval_metadata(db_conn, meta2)

        result = get_eval_metadata(db_conn, "sol-20260314-120000", "eval-bench")
        assert result is not None
        assert result.eval_id == "eval-2"


# ── Edge cases ──────────────────────────────────────────────────────────────


class TestEvalEdgeCases:
    """Edge-case tests for eval CRUD."""

    @pytest.mark.unit
    def test_status_check_constraint(self, db_conn: sqlite3.Connection) -> None:
        """Inserting an instance with invalid status raises IntegrityError."""
        _seed_prerequisites(db_conn)
        insert_eval_metadata(db_conn, _make_eval_metadata())

        with pytest.raises(sqlite3.IntegrityError):
            insert_eval_instance(
                db_conn,
                eval_id="eval-20260315-100000",
                instance_id="inst-bad",
                metric_name="score",
                value=0.5,
                status="invalid_status",
                error_message=None,
                compute_time_s=1.0,
            )

    @pytest.mark.unit
    def test_primary_key_enforced_on_instances(self, db_conn: sqlite3.Connection) -> None:
        """Inserting duplicate (eval_id, instance_id, metric_name) raises IntegrityError."""
        _seed_prerequisites(db_conn)
        insert_eval_metadata(db_conn, _make_eval_metadata())

        insert_eval_instance(
            db_conn,
            eval_id="eval-20260315-100000",
            instance_id="inst-001",
            metric_name="score",
            value=0.9,
            status="solved",
            error_message=None,
            compute_time_s=1.0,
        )

        with pytest.raises(sqlite3.IntegrityError):
            insert_eval_instance(
                db_conn,
                eval_id="eval-20260315-100000",
                instance_id="inst-001",
                metric_name="score",
                value=0.8,
                status="solved",
                error_message=None,
                compute_time_s=1.0,
            )

    @pytest.mark.unit
    def test_second_dataset_for_same_solution(self, db_conn: sqlite3.Connection) -> None:
        """Same solution evaluated on different datasets creates separate entries."""
        _seed_prerequisites(db_conn)

        # Register a second dataset
        reg2 = DatasetRegistration(
            name="eval-bench-2",
            path="/data/eval2",
            storage="reference",
            split="eval",
            instance_count=50,
            global_hash="sha256:dshash2",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
        )
        insert_dataset(db_conn, reg2)

        # Insert eval for first dataset
        meta1 = _make_eval_metadata(eval_id="eval-1", dataset_name="eval-bench")
        insert_eval_metadata(db_conn, meta1)

        # Insert eval for second dataset
        meta2 = _make_eval_metadata(eval_id="eval-2", dataset_name="eval-bench-2")
        insert_eval_metadata(db_conn, meta2)

        # Both should be retrievable
        result1 = get_eval_metadata(db_conn, "sol-20260314-120000", "eval-bench")
        result2 = get_eval_metadata(db_conn, "sol-20260314-120000", "eval-bench-2")
        assert result1 is not None
        assert result1.eval_id == "eval-1"
        assert result2 is not None
        assert result2.eval_id == "eval-2"
