"""L1 unit tests for benchmark CRUD in revolver.infra.db (S6-02)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
import sqlite3

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
    def test_empty_solution_ids_raises(self, db_conn: sqlite3.Connection) -> None:
        """Passing an empty solution_ids list raises ValueError."""
        _seed_prerequisites(db_conn)

        insert_benchmark(
            db_conn,
            benchmark_id="bench-20260316-100000",
            alias=None,
            dataset_name="eval-bench",
            created_at=datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC),
        )

        with pytest.raises(ValueError, match="solution_ids must not be empty"):
            insert_benchmark_solutions(db_conn, "bench-20260316-100000", [])

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
    def test_dataset_name_mismatch_returns_empty(self, db_conn: sqlite3.Connection) -> None:
        """get_benchmark_solutions returns [] when dataset_name does not match eval_metadata."""
        _seed_prerequisites(db_conn)
        _seed_eval_metadata(db_conn)  # eval_metadata uses "eval-bench"

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

        # Querying with a different dataset_name: INNER JOIN filters out all rows
        rows = get_benchmark_solutions(db_conn, "bench-20260316-100000", "other-dataset")
        assert rows == []

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

# Minimal v2 project schema (no benchmarks tables) used to simulate an
# existing database that must be upgraded to v3 by _run_migrations.
_V2_PROJECT_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS problem_versions (
    tag             TEXT PRIMARY KEY,
    hash            TEXT NOT NULL UNIQUE,
    message         TEXT DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    name            TEXT PRIMARY KEY,
    path            TEXT NOT NULL,
    split           TEXT CHECK (split IN ('train', 'eval')),
    storage         TEXT NOT NULL DEFAULT 'reference' CHECK (storage IN ('reference', 'snapshot')),
    description     TEXT DEFAULT '',
    global_hash     TEXT NOT NULL,
    instance_count  INTEGER NOT NULL,
    registered_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_instances (
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    instance_id     TEXT NOT NULL,
    hash            TEXT NOT NULL,
    PRIMARY KEY (dataset_name, instance_id)
);

CREATE TABLE IF NOT EXISTS dataset_compat (
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    problem_version TEXT NOT NULL REFERENCES problem_versions(tag),
    PRIMARY KEY (dataset_name, problem_version)
);

CREATE TABLE IF NOT EXISTS runs (
    id                TEXT PRIMARY KEY,
    problem_version   TEXT NOT NULL REFERENCES problem_versions(tag),
    llm               TEXT NOT NULL,
    dataset           TEXT NOT NULL REFERENCES datasets(name),
    iterations        INTEGER NOT NULL,
    generation_time_s REAL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    config_snapshot   TEXT,
    problem_hash      TEXT NOT NULL,
    dataset_hash      TEXT NOT NULL,
    llm_model         TEXT NOT NULL,
    resumed_from      TEXT REFERENCES runs(id),
    status            TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'completed',
                             'interrupted', 'completed_with_errors')),
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_version ON runs(problem_version);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_resumed ON runs(resumed_from);

CREATE TABLE IF NOT EXISTS solutions (
    id         TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES runs(id),
    rank       INTEGER NOT NULL,
    best_score REAL,
    alias      TEXT UNIQUE,
    UNIQUE(run_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_solutions_run ON solutions(run_id);

CREATE TABLE IF NOT EXISTS eval_metadata (
    eval_id          TEXT PRIMARY KEY,
    solution_id      TEXT NOT NULL REFERENCES solutions(id),
    dataset_name     TEXT NOT NULL REFERENCES datasets(name),
    instance_count   INTEGER NOT NULL,
    instances_solved INTEGER NOT NULL,
    eval_time_s      REAL,
    user_aggregates  TEXT,
    evaluated_at     TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_unique ON eval_metadata(solution_id, dataset_name);

CREATE TABLE IF NOT EXISTS eval_instances (
    eval_id         TEXT NOT NULL REFERENCES eval_metadata(eval_id),
    instance_id     TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    value           REAL,
    status          TEXT NOT NULL CHECK (status IN ('solved', 'failed', 'timeout')),
    error_message   TEXT,
    compute_time_s  REAL,
    PRIMARY KEY (eval_id, instance_id, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_eval_inst_eval ON eval_instances(eval_id);
"""


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
    def test_schema_version_is_current(self, db_conn: sqlite3.Connection) -> None:
        """schema_version table must contain current version after migration."""
        from revolver.infra.db import CURRENT_SCHEMA_VERSION

        cursor = db_conn.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 4

    @pytest.mark.unit
    def test_migration_v3_upgrades_existing_v2_db(self, tmp_path: Path) -> None:
        """Migration v3 adds benchmark tables to an existing v2 database.

        Simulates a pre-existing project DB at schema version 2 (no benchmark
        tables) and confirms that re-opening it via get_project_db() applies
        migration 3 and creates the expected tables and index.
        """
        from revolver.infra.db import _configure_connection, get_project_db

        # Build a v2 database manually (schema without benchmark tables).
        db_path = tmp_path / "old.db"
        conn_v2 = sqlite3.connect(str(db_path))
        _configure_connection(conn_v2)
        conn_v2.executescript(_V2_PROJECT_SCHEMA_SQL)
        conn_v2.execute(
            "INSERT INTO schema_version (version, applied_at)"
            " VALUES (2, '2026-01-01T00:00:00+00:00')"
        )
        conn_v2.commit()

        # Verify benchmark tables are absent at v2.
        cursor = conn_v2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='benchmarks'"
        )
        assert cursor.fetchone() is None, "benchmarks table should not exist before migration"
        conn_v2.close()

        # Re-open via get_project_db — should apply migration 3.
        conn_v3 = get_project_db(db_path)

        cursor = conn_v3.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='benchmarks'"
        )
        assert cursor.fetchone() is not None, "benchmarks table must exist after migration v3"

        cursor = conn_v3.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='benchmark_solutions'"
        )
        assert cursor.fetchone() is not None, (
            "benchmark_solutions table must exist after migration v3"
        )

        cursor = conn_v3.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_benchmarks_created'"
        )
        assert cursor.fetchone() is not None, (
            "idx_benchmarks_created index must exist after migration v3"
        )

        cursor = conn_v3.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] >= 3, "schema_version must be at least 3 after migration"

        conn_v3.close()
