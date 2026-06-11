"""L1 unit tests for DB migration v9 — runs.backend column (S13-06).

Tests cover:
- Fresh project DB lands at schema v9 with the backend column
- A v8 project DB upgrades to v9 with existing runs backfilled to 'openevolve'
- A v8 global DB upgrades to v9 (version bump only, no runs table)
- insert_run / get_run / get_latest_run / list_runs include backend
  (default and explicit values)

Traceable to: ADR-007 D4, DES-001 §3.5/§5.8, FR-RUN-047, sprint-013 S13-06.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from revolver.infra.db import (
    CURRENT_SCHEMA_VERSION,
    get_global_db_at,
    get_latest_run,
    get_project_db,
    get_run,
    insert_dataset,
    insert_problem_version,
    insert_run,
    list_runs,
)
from revolver.models.dataset import DatasetRegistration
from revolver.models.problem import ProblemVersion

# ── Fixtures and helpers ─────────────────────────────────────────────────────


@pytest.fixture()
def project_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a project DB for testing."""
    db_path = tmp_path / "project.db"
    conn = get_project_db(db_path)
    yield conn  # type: ignore[misc]
    conn.close()


def _seed_problem_and_dataset(conn: sqlite3.Connection) -> None:
    """Insert a problem version and dataset required by FK constraints."""
    pv = ProblemVersion(
        tag="v1.0",
        hash="sha256:pvhash",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    insert_problem_version(conn, pv)
    reg = DatasetRegistration(
        name="train-small",
        path="/data/train",
        storage="reference",
        split="train",
        instance_count=10,
        global_hash="sha256:dshash",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    insert_dataset(conn, reg)


def _insert_test_run(
    conn: sqlite3.Connection,
    run_id: str = "run-20260601-120000",
    *,
    backend: str | None = None,
    created_at: datetime | None = None,
) -> None:
    """Helper to insert a run, optionally with an explicit backend."""
    kwargs: dict[str, str] = {}
    if backend is not None:
        kwargs["backend"] = backend
    insert_run(
        conn,
        run_id=run_id,
        problem_version="v1.0",
        llm="test-llm",
        dataset="train-small",
        iterations=100,
        problem_hash="sha256:pvhash",
        dataset_hash="sha256:dshash",
        llm_model="test-model",
        created_at=created_at or datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        **kwargs,
    )


# v8-era project schema (pre-v9: no backend column on runs).
_V8_PROJECT_SCHEMA_SQL = """\
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
    storage         TEXT NOT NULL DEFAULT 'reference'
                    CHECK (storage IN ('reference', 'snapshot')),
    description     TEXT DEFAULT '',
    global_hash     TEXT NOT NULL,
    instance_count  INTEGER NOT NULL,
    registered_at   TEXT NOT NULL
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
                             'interrupted', 'failed', 'completed_with_errors')),
    valid_iterations  INTEGER,
    llm_type          TEXT NOT NULL DEFAULT 'single',
    llm_snapshot      TEXT,
    created_at        TEXT NOT NULL
);
"""


def _create_v8_project_db(db_path: Path) -> None:
    """Create a v8-era project DB with one pre-existing run row."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_V8_PROJECT_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (8, "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO problem_versions (tag, hash, created_at) VALUES (?, ?, ?)",
        ("v1.0", "sha256:pvhash", "2026-01-01T00:00:00"),
    )
    conn.execute(
        """\
        INSERT INTO datasets (name, path, split, storage, global_hash,
                              instance_count, registered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "train-small",
            "/data/train",
            "train",
            "reference",
            "sha256:dshash",
            10,
            "2026-01-01T00:00:00",
        ),
    )
    conn.execute(
        """\
        INSERT INTO runs (id, problem_version, llm, dataset, iterations,
                          problem_hash, dataset_hash, llm_model, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "run-pre-v9",
            "v1.0",
            "test-llm",
            "train-small",
            50,
            "sha256:pvhash",
            "sha256:dshash",
            "test-model",
            "completed",
            "2026-01-02T00:00:00",
        ),
    )
    conn.commit()
    conn.close()


# ── Migration v9: fresh DB ───────────────────────────────────────────────────


@pytest.mark.unit
def test_current_schema_version_is_9() -> None:
    """CURRENT_SCHEMA_VERSION should be 9 after migration v9 (runs.backend)."""
    assert CURRENT_SCHEMA_VERSION == 9


@pytest.mark.unit
def test_fresh_project_db_schema_version_9(project_conn: sqlite3.Connection) -> None:
    """A fresh project DB lands at schema version 9."""
    cursor = project_conn.execute("SELECT MAX(version) FROM schema_version")
    row = cursor.fetchone()
    assert row is not None and row[0] == 9


@pytest.mark.unit
def test_fresh_project_db_has_backend_column(project_conn: sqlite3.Connection) -> None:
    """A fresh project DB runs table must have the backend column."""
    cursor = project_conn.execute("PRAGMA table_info(runs)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "backend" in columns, "backend column not found in runs table"


@pytest.mark.unit
def test_fresh_project_db_backend_default(project_conn: sqlite3.Connection) -> None:
    """The backend column should default to 'openevolve'."""
    cursor = project_conn.execute("PRAGMA table_info(runs)")
    for row in cursor.fetchall():
        if row[1] == "backend":
            # row[4] is the default value
            assert row[4] == "'openevolve'", f"Expected default 'openevolve', got {row[4]}"
            return
    pytest.fail("backend column not found")


# ── Migration v9: upgrade from v8 ────────────────────────────────────────────


@pytest.mark.unit
def test_migration_v8_to_v9_adds_backend_column(tmp_path: Path) -> None:
    """Re-opening a v8 project DB applies migration v9 and adds the column."""
    db_path = tmp_path / "migrate.db"
    _create_v8_project_db(db_path)

    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("PRAGMA table_info(runs)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "backend" in columns, "backend column not added by migration v9"

        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == 9
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_v8_to_v9_backfills_existing_runs(tmp_path: Path) -> None:
    """Pre-v9 run rows are backfilled with backend='openevolve'."""
    db_path = tmp_path / "migrate.db"
    _create_v8_project_db(db_path)

    conn = get_project_db(db_path)
    try:
        result = get_run(conn, "run-pre-v9")
        assert result is not None, "pre-existing run lost during migration"
        assert result["backend"] == "openevolve"
        # Pre-existing data must be preserved.
        assert result["iterations"] == 50
        assert result["status"] == "completed"
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_v8_to_v9_global_db(tmp_path: Path) -> None:
    """A v8 global DB (no runs table) just gets the version bump."""
    db_path = tmp_path / "global.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""\
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llms (
    name            TEXT PRIMARY KEY,
    provider        TEXT,
    model           TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('local', 'remote')),
    base_url        TEXT,
    api_key_env     TEXT,
    input_cost_per_mtok  REAL,
    output_cost_per_mtok REAL,
    max_tokens      INTEGER,
    timeout_s       INTEGER,
    temperature     REAL,
    registered_at   TEXT NOT NULL
);
""")
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (8, "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    conn = get_global_db_at(db_path)
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == 9
    finally:
        conn.close()


# ── insert_run / get_run / list_runs with backend ────────────────────────────


@pytest.mark.unit
def test_insert_run_default_backend_roundtrip(project_conn: sqlite3.Connection) -> None:
    """insert_run without backend stores and returns 'openevolve'."""
    _seed_problem_and_dataset(project_conn)
    _insert_test_run(project_conn)
    result = get_run(project_conn, "run-20260601-120000")
    assert result is not None
    assert result["backend"] == "openevolve"


@pytest.mark.unit
def test_insert_run_explicit_backend_roundtrip(project_conn: sqlite3.Connection) -> None:
    """insert_run with an explicit backend stores and returns it."""
    _seed_problem_and_dataset(project_conn)
    _insert_test_run(project_conn, backend="shinka")
    result = get_run(project_conn, "run-20260601-120000")
    assert result is not None
    assert result["backend"] == "shinka"


@pytest.mark.unit
def test_get_latest_run_includes_backend(project_conn: sqlite3.Connection) -> None:
    """get_latest_run returns the backend column."""
    _seed_problem_and_dataset(project_conn)
    _insert_test_run(project_conn)
    result = get_latest_run(project_conn)
    assert result is not None
    assert result["backend"] == "openevolve"


@pytest.mark.unit
def test_list_runs_includes_backend(project_conn: sqlite3.Connection) -> None:
    """list_runs rows include the backend column."""
    _seed_problem_and_dataset(project_conn)
    _insert_test_run(project_conn, "run-a")
    _insert_test_run(
        project_conn,
        "run-b",
        backend="shinka",
        created_at=datetime(2026, 6, 1, 13, 0, 0, tzinfo=UTC),
    )
    rows = list_runs(project_conn)
    assert len(rows) == 2
    backends = {row["id"]: row["backend"] for row in rows}
    assert backends == {"run-a": "openevolve", "run-b": "shinka"}
