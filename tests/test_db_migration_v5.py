"""L1 unit tests for DB migration v4→v5 — ON DELETE CASCADE on FK constraints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from revolver.infra.db import (
    CURRENT_SCHEMA_VERSION,
    _migrate_v4_to_v5,
    get_project_db,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_v4_database(db_path: Path) -> sqlite3.Connection:
    """Create a v4-schema database WITHOUT ON DELETE CASCADE.

    This manually creates the v4 schema so we can test the migration path.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""\
CREATE TABLE schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE problem_versions (
    tag             TEXT PRIMARY KEY,
    hash            TEXT NOT NULL UNIQUE,
    message         TEXT DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE TABLE datasets (
    name            TEXT PRIMARY KEY,
    path            TEXT NOT NULL,
    split           TEXT CHECK (split IN ('train', 'eval')),
    storage         TEXT NOT NULL DEFAULT 'reference'
                    CHECK (storage IN ('reference', 'snapshot')),
    description     TEXT DEFAULT '',
    global_hash     TEXT NOT NULL,
    instance_count  INTEGER NOT NULL,
    registered_at   TEXT NOT NULL
);

CREATE TABLE dataset_instances (
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    instance_id     TEXT NOT NULL,
    hash            TEXT NOT NULL,
    PRIMARY KEY (dataset_name, instance_id)
);

CREATE TABLE dataset_compat (
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    problem_version TEXT NOT NULL REFERENCES problem_versions(tag),
    PRIMARY KEY (dataset_name, problem_version)
);

CREATE TABLE runs (
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
    valid_iterations  INTEGER,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_version ON runs(problem_version);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_resumed ON runs(resumed_from);

CREATE TABLE solutions (
    id         TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES runs(id),
    rank       INTEGER NOT NULL,
    best_score REAL,
    alias      TEXT UNIQUE,
    UNIQUE(run_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_solutions_run ON solutions(run_id);

CREATE TABLE eval_metadata (
    eval_id          TEXT PRIMARY KEY,
    solution_id      TEXT NOT NULL REFERENCES solutions(id),
    dataset_name     TEXT NOT NULL REFERENCES datasets(name),
    instance_count   INTEGER NOT NULL,
    instances_solved INTEGER NOT NULL,
    eval_time_s      REAL,
    user_aggregates  TEXT,
    evaluated_at     TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_unique
    ON eval_metadata(solution_id, dataset_name);

CREATE TABLE eval_instances (
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

CREATE TABLE benchmarks (
    id              TEXT PRIMARY KEY,
    alias           TEXT,
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_benchmarks_created ON benchmarks(created_at DESC);

CREATE TABLE benchmark_solutions (
    benchmark_id    TEXT NOT NULL REFERENCES benchmarks(id),
    solution_id     TEXT NOT NULL REFERENCES solutions(id),
    PRIMARY KEY (benchmark_id, solution_id)
);
""")

    # Mark as v4
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (4, now),
    )
    conn.commit()
    return conn


def _seed_v4_data(conn: sqlite3.Connection) -> None:
    """Insert representative test data into a v4 database."""
    now = datetime.now(UTC).isoformat()

    # Problem version
    conn.execute(
        "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
        ("v1.0", "sha256:pvhash", "test", now),
    )

    # Dataset + instances + compat
    conn.execute(
        "INSERT INTO datasets (name, path, split, storage, description, global_hash, "
        "instance_count, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("ds1", "/data/ds1", "train", "reference", "", "sha256:dshash", 2, now),
    )
    conn.execute(
        "INSERT INTO dataset_instances (dataset_name, instance_id, hash) VALUES (?, ?, ?)",
        ("ds1", "inst-01", "sha256:i1"),
    )
    conn.execute(
        "INSERT INTO dataset_instances (dataset_name, instance_id, hash) VALUES (?, ?, ?)",
        ("ds1", "inst-02", "sha256:i2"),
    )
    conn.execute(
        "INSERT INTO dataset_compat (dataset_name, problem_version) VALUES (?, ?)",
        ("ds1", "v1.0"),
    )

    # Run
    conn.execute(
        "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
        "problem_hash, dataset_hash, llm_model, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "run-001",
            "v1.0",
            "llm1",
            "ds1",
            100,
            "sha256:pvhash",
            "sha256:dshash",
            "model1",
            "completed",
            now,
        ),
    )

    # Solutions
    conn.execute(
        "INSERT INTO solutions (id, run_id, rank, best_score) VALUES (?, ?, ?, ?)",
        ("sol-001", "run-001", 1, 0.95),
    )
    conn.execute(
        "INSERT INTO solutions (id, run_id, rank, best_score) VALUES (?, ?, ?, ?)",
        ("sol-002", "run-001", 2, 0.90),
    )

    # Eval metadata + instances
    conn.execute(
        "INSERT INTO eval_metadata (eval_id, solution_id, dataset_name, "
        "instance_count, instances_solved, evaluated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("eval-001", "sol-001", "ds1", 2, 2, now),
    )
    conn.execute(
        "INSERT INTO eval_instances (eval_id, instance_id, metric_name, value, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("eval-001", "inst-01", "score", 0.95, "solved"),
    )
    conn.execute(
        "INSERT INTO eval_instances (eval_id, instance_id, metric_name, value, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("eval-001", "inst-02", "score", 0.90, "solved"),
    )

    # Benchmark + benchmark_solutions
    conn.execute(
        "INSERT INTO benchmarks (id, alias, dataset_name, created_at) VALUES (?, ?, ?, ?)",
        ("bench-001", "baseline", "ds1", now),
    )
    conn.execute(
        "INSERT INTO benchmark_solutions (benchmark_id, solution_id) VALUES (?, ?)",
        ("bench-001", "sol-001"),
    )

    conn.commit()


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_migration_v4_to_v5(tmp_path: Path) -> None:
    """Migration v4→v5 must succeed and preserve all data."""
    db_path = tmp_path / "revolver.db"
    conn = _create_v4_database(db_path)
    _seed_v4_data(conn)

    # Run migration
    _migrate_v4_to_v5(conn)

    # Verify schema version is 5
    cursor = conn.execute("SELECT MAX(version) FROM schema_version")
    assert cursor.fetchone()[0] == 5

    # Verify all data is preserved
    assert conn.execute("SELECT COUNT(*) FROM problem_versions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dataset_instances").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM dataset_compat").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM solutions").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM eval_metadata").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM eval_instances").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM benchmarks").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM benchmark_solutions").fetchone()[0] == 1

    # Verify specific data values
    sol = conn.execute("SELECT id, best_score FROM solutions WHERE id = 'sol-001'").fetchone()
    assert sol == ("sol-001", 0.95)

    conn.close()


@pytest.mark.unit
def test_cascade_delete_run(tmp_path: Path) -> None:
    """Deleting a run must cascade to solutions, eval_metadata, eval_instances."""
    db_path = tmp_path / "revolver.db"
    conn = get_project_db(db_path)

    now = datetime.now(UTC).isoformat()

    # Seed problem + dataset
    conn.execute(
        "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
        ("v1.0", "sha256:pvhash", "test", now),
    )
    conn.execute(
        "INSERT INTO datasets (name, path, split, storage, description, global_hash, "
        "instance_count, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("ds1", "/data/ds1", "train", "reference", "", "sha256:dshash", 1, now),
    )

    # Insert run + solution + eval
    conn.execute(
        "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
        "problem_hash, dataset_hash, llm_model, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "run-001",
            "v1.0",
            "llm1",
            "ds1",
            100,
            "sha256:pvhash",
            "sha256:dshash",
            "model1",
            "completed",
            now,
        ),
    )
    conn.execute(
        "INSERT INTO solutions (id, run_id, rank, best_score) VALUES (?, ?, ?, ?)",
        ("sol-001", "run-001", 1, 0.95),
    )
    conn.execute(
        "INSERT INTO eval_metadata (eval_id, solution_id, dataset_name, "
        "instance_count, instances_solved, evaluated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("eval-001", "sol-001", "ds1", 1, 1, now),
    )
    conn.execute(
        "INSERT INTO eval_instances (eval_id, instance_id, metric_name, value, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("eval-001", "inst-01", "score", 0.95, "solved"),
    )
    conn.commit()

    # Verify data exists before delete
    assert conn.execute("SELECT COUNT(*) FROM solutions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM eval_metadata").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM eval_instances").fetchone()[0] == 1

    # Delete the run — should cascade
    conn.execute("DELETE FROM runs WHERE id = 'run-001'")
    conn.commit()

    # Verify cascade: all child rows removed
    assert conn.execute("SELECT COUNT(*) FROM solutions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM eval_metadata").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM eval_instances").fetchone()[0] == 0

    conn.close()


@pytest.mark.unit
def test_cascade_delete_dataset(tmp_path: Path) -> None:
    """Deleting a dataset must cascade to dataset_instances and dataset_compat."""
    db_path = tmp_path / "revolver.db"
    conn = get_project_db(db_path)

    now = datetime.now(UTC).isoformat()

    # Seed problem version (needed for dataset_compat FK)
    conn.execute(
        "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
        ("v1.0", "sha256:pvhash", "test", now),
    )

    # Insert dataset + instances + compat
    conn.execute(
        "INSERT INTO datasets (name, path, split, storage, description, global_hash, "
        "instance_count, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("ds1", "/data/ds1", "train", "reference", "", "sha256:dshash", 2, now),
    )
    conn.execute(
        "INSERT INTO dataset_instances (dataset_name, instance_id, hash) VALUES (?, ?, ?)",
        ("ds1", "inst-01", "sha256:i1"),
    )
    conn.execute(
        "INSERT INTO dataset_instances (dataset_name, instance_id, hash) VALUES (?, ?, ?)",
        ("ds1", "inst-02", "sha256:i2"),
    )
    conn.execute(
        "INSERT INTO dataset_compat (dataset_name, problem_version) VALUES (?, ?)",
        ("ds1", "v1.0"),
    )
    conn.commit()

    # Verify data exists
    assert conn.execute("SELECT COUNT(*) FROM dataset_instances").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM dataset_compat").fetchone()[0] == 1

    # Delete dataset — should cascade
    conn.execute("DELETE FROM datasets WHERE name = 'ds1'")
    conn.commit()

    # Verify cascade
    assert conn.execute("SELECT COUNT(*) FROM dataset_instances").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM dataset_compat").fetchone()[0] == 0

    conn.close()


@pytest.mark.unit
def test_foreign_keys_enabled(tmp_path: Path) -> None:
    """PRAGMA foreign_keys must return 1 on project DB connections."""
    db_path = tmp_path / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("PRAGMA foreign_keys")
        fk = cursor.fetchone()[0]
        assert fk == 1, f"Expected foreign_keys=1, got {fk}"
    finally:
        conn.close()


@pytest.mark.unit
def test_fresh_db_has_cascade(tmp_path: Path) -> None:
    """A fresh database (no migration) should have CASCADE FKs from the schema."""
    db_path = tmp_path / "revolver.db"
    conn = get_project_db(db_path)

    # Check the solutions table FK has CASCADE by inspecting the SQL
    cursor = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='solutions'")
    sql = cursor.fetchone()[0]
    assert "ON DELETE CASCADE" in sql, f"solutions table missing CASCADE: {sql}"

    # Check eval_metadata
    cursor = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='eval_metadata'"
    )
    sql = cursor.fetchone()[0]
    assert "ON DELETE CASCADE" in sql, f"eval_metadata table missing CASCADE: {sql}"

    # Check dataset_instances
    cursor = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='dataset_instances'"
    )
    sql = cursor.fetchone()[0]
    assert "ON DELETE CASCADE" in sql, f"dataset_instances table missing CASCADE: {sql}"

    conn.close()


@pytest.mark.unit
def test_schema_version_is_7(tmp_path: Path) -> None:
    """CURRENT_SCHEMA_VERSION must be 7 after migration v7 (failed status)."""
    assert CURRENT_SCHEMA_VERSION == 7

    db_path = tmp_path / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == 7
    finally:
        conn.close()
