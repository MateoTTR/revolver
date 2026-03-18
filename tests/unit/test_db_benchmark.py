"""L1 unit tests for benchmark CRUD in revolver.infra.db (S6-02)."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.infra.db import (
    get_benchmark,
    get_benchmark_solutions,
    get_latest_benchmark,
    get_project_db,
    insert_benchmark,
    insert_benchmark_solutions,
    insert_dataset,
    insert_eval_metadata,
    insert_problem_version,
    insert_run,
    insert_solution,
    list_benchmarks_with_count,
)
from revolver.models.dataset import DatasetRegistration
from revolver.models.problem import ProblemVersion


@pytest.fixture()
def db_conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Create a project DB for testing."""
    conn = get_project_db(tmp_path / "revolver.db")
    yield conn
    conn.close()


def _seed_prerequisites(conn: sqlite3.Connection) -> None:
    """Insert problem version, dataset, run, and solutions required by FK constraints."""
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
        alias="sol-a",
    )
    insert_solution(
        conn,
        solution_id="sol-20260314-130000",
        run_id="run-20260314-120000",
        rank=2,
        best_score=0.88,
        alias="sol-b",
    )


def _seed_eval_metadata(conn: sqlite3.Connection) -> None:
    """Insert eval_metadata rows for both seeded solutions."""
    insert_eval_metadata(
        conn,
        eval_id="eval-20260315-100000",
        solution_id="sol-20260314-120000",
        dataset_name="eval-bench",
        instance_count=100,
        instances_solved=95,
        eval_time_s=60.0,
        user_aggregates=None,
        evaluated_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
    )
    insert_eval_metadata(
        conn,
        eval_id="eval-20260315-110000",
        solution_id="sol-20260314-130000",
        dataset_name="eval-bench",
        instance_count=100,
        instances_solved=88,
        eval_time_s=65.0,
        user_aggregates=None,
        evaluated_at=datetime(2026, 3, 15, 11, 0, 0, tzinfo=UTC),
    )


# ── insert_benchmark / get_benchmark ────────────────────────────────────────


class TestInsertAndGetBenchmark:
    """Tests for insert_benchmark and get_benchmark."""

    @pytest.mark.unit
    def test_insert_and_get_round_trip(self, db_conn: sqlite3.Connection) -> None:
        """Insert a benchmark and retrieve it by ID."""
        _seed_prerequisites(db_conn)
        created_at = datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias="baseline",
            dataset_name="eval-bench",
            created_at=created_at,
        )

        result = get_benchmark(db_conn, "bench-20260316-100000")
        assert result is not None
        assert result["id"] == "bench-20260316-100000"
        assert result["alias"] == "baseline"
        assert result["dataset_name"] == "eval-bench"
        assert result["created_at"] == created_at.isoformat()

    @pytest.mark.unit
    def test_insert_with_null_alias(self, db_conn: sqlite3.Connection) -> None:
        """Benchmark with None alias is stored and retrieved correctly."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias=None,
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )

        result = get_benchmark(db_conn, "bench-20260316-100000")
        assert result is not None
        assert result["alias"] is None

    @pytest.mark.unit
    def test_nonexistent_returns_none(self, db_conn: sqlite3.Connection) -> None:
        """get_benchmark returns None for an unknown ID."""
        result = get_benchmark(db_conn, "bench-nonexistent")
        assert result is None

    @pytest.mark.unit
    def test_primary_key_enforced(self, db_conn: sqlite3.Connection) -> None:
        """Inserting a duplicate benchmark ID raises IntegrityError."""
        _seed_prerequisites(db_conn)
        created_at = datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias=None,
            dataset_name="eval-bench",
            created_at=created_at,
        )

        with pytest.raises(sqlite3.IntegrityError):
            insert_benchmark(
                db_conn,
                benchmark_id="bench-20260316-100000",
                alias="duplicate",
                dataset_name="eval-bench",
                created_at=created_at,
            )

    @pytest.mark.unit
    def test_fk_violation_on_unknown_dataset(self, db_conn: sqlite3.Connection) -> None:
        """Inserting a benchmark with an unknown dataset_name raises IntegrityError."""
        with pytest.raises(sqlite3.IntegrityError):
            insert_benchmark(
                db_conn,
                benchmark_id="bench-20260316-100000",
                alias=None,
                dataset_name="nonexistent-dataset",
                created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
            )


# ── get_latest_benchmark ─────────────────────────────────────────────────────


class TestGetLatestBenchmark:
    """Tests for get_latest_benchmark."""

    @pytest.mark.unit
    def test_returns_none_when_empty(self, db_conn: sqlite3.Connection) -> None:
        """get_latest_benchmark returns None when no benchmarks exist."""
        result = get_latest_benchmark(db_conn)
        assert result is None

    @pytest.mark.unit
    def test_returns_only_benchmark(self, db_conn: sqlite3.Connection) -> None:
        """get_latest_benchmark returns the single existing benchmark."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias="only-one",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )

        result = get_latest_benchmark(db_conn)
        assert result is not None
        assert result["id"] == "bench-20260316-100000"

    @pytest.mark.unit
    def test_returns_most_recent(self, db_conn: sqlite3.Connection) -> None:
        """get_latest_benchmark returns the benchmark with the latest created_at."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260315-100000",
            alias="older",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
        )
        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias="newer",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )

        result = get_latest_benchmark(db_conn)
        assert result is not None
        assert result["id"] == "bench-20260316-100000"
        assert result["alias"] == "newer"


# ── insert_benchmark_solutions / get_benchmark_solutions ────────────────────


class TestInsertAndGetBenchmarkSolutions:
    """Tests for insert_benchmark_solutions and get_benchmark_solutions."""

    @pytest.mark.unit
    def test_batch_insert_and_get(self, db_conn: sqlite3.Connection) -> None:
        """Batch insert solutions and retrieve them with eval metadata."""
        _seed_prerequisites(db_conn)
        _seed_eval_metadata(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias="baseline",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )
        insert_benchmark_solutions(
            db_conn,
            "bench-20260316-100000",
            ["sol-20260314-120000", "sol-20260314-130000"],
        )

        rows = get_benchmark_solutions(db_conn, "bench-20260316-100000", "eval-bench")
        assert len(rows) == 2

        # Ordered by alias then ID
        assert rows[0]["solution_id"] == "sol-20260314-120000"
        assert rows[0]["alias"] == "sol-a"
        assert rows[0]["run_id"] == "run-20260314-120000"
        assert rows[0]["rank"] == 1
        assert rows[0]["best_score"] == pytest.approx(0.95)
        assert rows[0]["eval_id"] == "eval-20260315-100000"
        assert rows[0]["instance_count"] == 100
        assert rows[0]["instances_solved"] == 95
        assert rows[0]["eval_time_s"] == pytest.approx(60.0)
        assert rows[0]["user_aggregates"] is None

        assert rows[1]["solution_id"] == "sol-20260314-130000"
        assert rows[1]["alias"] == "sol-b"

    @pytest.mark.unit
    def test_empty_when_no_solutions(self, db_conn: sqlite3.Connection) -> None:
        """get_benchmark_solutions returns empty list when no solutions are linked."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias=None,
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )

        rows = get_benchmark_solutions(db_conn, "bench-20260316-100000", "eval-bench")
        assert rows == []

    @pytest.mark.unit
    def test_empty_for_nonexistent_benchmark(self, db_conn: sqlite3.Connection) -> None:
        """get_benchmark_solutions returns empty list for unknown benchmark_id."""
        rows = get_benchmark_solutions(db_conn, "bench-nonexistent", "eval-bench")
        assert rows == []

    @pytest.mark.unit
    def test_fk_violation_on_unknown_solution(self, db_conn: sqlite3.Connection) -> None:
        """Inserting a benchmark_solution with unknown solution_id raises IntegrityError."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias=None,
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )

        with pytest.raises(sqlite3.IntegrityError):
            insert_benchmark_solutions(
                db_conn,
                "bench-20260316-100000",
                ["nonexistent-solution"],
            )

    @pytest.mark.unit
    def test_primary_key_enforced(self, db_conn: sqlite3.Connection) -> None:
        """Inserting a duplicate (benchmark_id, solution_id) pair raises IntegrityError."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias=None,
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )
        insert_benchmark_solutions(
            db_conn,
            "bench-20260316-100000",
            ["sol-20260314-120000"],
        )

        with pytest.raises(sqlite3.IntegrityError):
            insert_benchmark_solutions(
                db_conn,
                "bench-20260316-100000",
                ["sol-20260314-120000"],
            )


# ── list_benchmarks_with_count ───────────────────────────────────────────────


class TestListBenchmarksWithCount:
    """Tests for list_benchmarks_with_count."""

    @pytest.mark.unit
    def test_empty_when_no_benchmarks(self, db_conn: sqlite3.Connection) -> None:
        """list_benchmarks_with_count returns empty list when no benchmarks exist."""
        result = list_benchmarks_with_count(db_conn)
        assert result == []

    @pytest.mark.unit
    def test_single_benchmark_zero_solutions(self, db_conn: sqlite3.Connection) -> None:
        """A benchmark with no solutions shows solution_count=0."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias="empty",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )

        result = list_benchmarks_with_count(db_conn)
        assert len(result) == 1
        assert result[0]["id"] == "bench-20260316-100000"
        assert result[0]["alias"] == "empty"
        assert result[0]["dataset_name"] == "eval-bench"
        assert result[0]["solution_count"] == 0

    @pytest.mark.unit
    def test_solution_count_correct(self, db_conn: sqlite3.Connection) -> None:
        """solution_count reflects the actual number of linked solutions."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias="two-solutions",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )
        insert_benchmark_solutions(
            db_conn,
            "bench-20260316-100000",
            ["sol-20260314-120000", "sol-20260314-130000"],
        )

        result = list_benchmarks_with_count(db_conn)
        assert len(result) == 1
        assert result[0]["solution_count"] == 2

    @pytest.mark.unit
    def test_ordered_by_created_at_desc(self, db_conn: sqlite3.Connection) -> None:
        """list_benchmarks_with_count returns benchmarks newest first."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260315-100000",
            alias="older",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
        )
        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias="newer",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )

        result = list_benchmarks_with_count(db_conn)
        assert len(result) == 2
        assert result[0]["id"] == "bench-20260316-100000"
        assert result[1]["id"] == "bench-20260315-100000"

    @pytest.mark.unit
    def test_multiple_benchmarks_independent_counts(self, db_conn: sqlite3.Connection) -> None:
        """Each benchmark has its own independent solution count."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260315-100000",
            alias="one-solution",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC),
        )
        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias="two-solutions",
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )
        insert_benchmark_solutions(
            db_conn,
            "bench-20260315-100000",
            ["sol-20260314-120000"],
        )
        insert_benchmark_solutions(
            db_conn,
            "bench-20260316-100000",
            ["sol-20260314-120000", "sol-20260314-130000"],
        )

        result = list_benchmarks_with_count(db_conn)
        # Newest first
        two_sol = next(r for r in result if r["id"] == "bench-20260316-100000")
        one_sol = next(r for r in result if r["id"] == "bench-20260315-100000")
        assert two_sol["solution_count"] == 2
        assert one_sol["solution_count"] == 1


# ── Schema migration ─────────────────────────────────────────────────────────


class TestSchemaMigrationV3:
    """Tests for schema migration v3 (benchmark tables)."""

    @pytest.mark.unit
    def test_benchmark_tables_exist(self, db_conn: sqlite3.Connection) -> None:
        """Schema migration v3 creates benchmarks and benchmark_solutions tables."""
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('benchmarks', 'benchmark_solutions')"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "benchmarks" in tables
        assert "benchmark_solutions" in tables

    @pytest.mark.unit
    def test_benchmarks_index_exists(self, db_conn: sqlite3.Connection) -> None:
        """Schema migration v3 creates the idx_benchmarks_created index."""
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_benchmarks_created'"
        )
        assert cursor.fetchone() is not None

    @pytest.mark.unit
    def test_schema_version_is_3(self, db_conn: sqlite3.Connection) -> None:
        """schema_version table must contain version=3 after migration."""
        from revolver.infra.db import CURRENT_SCHEMA_VERSION

        cursor = db_conn.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 3
