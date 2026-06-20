"""L1 unit tests for DB migration v11 — widen datasets.split CHECK to accept 'both' (S16-18).

Tests cover:
- CURRENT_SCHEMA_VERSION is at least 11
- A fresh project DB lands at the current schema version and accepts a
  ``split='both'`` dataset insert
- A v10 project DB (with the narrow ``split IN ('train','eval')`` CHECK and an
  existing dataset row) upgrades to v11: the existing row is preserved, the
  CHECK is widened so a ``split='both'`` insert succeeds, and the old narrow
  CHECK rejected ``both`` before the migration
- A v10 global DB (no datasets table) upgrades to v11 (version bump only, no-op)

Traceable to: sprint-016 S16-18 (UX-3), backlog #305.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from revolver.infra.db import (
    CURRENT_SCHEMA_VERSION,
    get_global_db_at,
    get_project_db,
)

# v10-era project schema: the datasets table carries the narrow split CHECK.
_V10_PROJECT_DATASETS_NARROW_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
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
"""


def _create_v10_project_db(db_path: Path) -> None:
    """Create a v10-era project DB with the narrow split CHECK and one dataset row."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_V10_PROJECT_DATASETS_NARROW_SQL)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (10, "2026-01-01T00:00:00"),
    )
    conn.execute(
        """\
        INSERT INTO datasets (name, path, split, storage, description,
                              global_hash, instance_count, registered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "train-small",
            "/data/train-small",
            "train",
            "reference",
            "a training set",
            "sha256:abc",
            12,
            "2026-01-02T00:00:00",
        ),
    )
    conn.commit()
    # Sanity check: the narrow v10 CHECK must reject 'both' before migration.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """\
            INSERT INTO datasets (name, path, split, storage, description,
                                  global_hash, instance_count, registered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rejected",
                "/data/rejected",
                "both",
                "reference",
                "",
                "sha256:def",
                1,
                "2026-01-02T00:00:00",
            ),
        )
    conn.rollback()
    conn.close()


def _insert_both_dataset(conn: sqlite3.Connection, name: str = "dual") -> None:
    """Insert a dataset row with split='both' (must succeed at v11)."""
    conn.execute(
        """\
        INSERT INTO datasets (name, path, split, storage, description,
                              global_hash, instance_count, registered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            f"/data/{name}",
            "both",
            "reference",
            "dual-use",
            "sha256:ghi",
            3,
            "2026-01-03T00:00:00",
        ),
    )
    conn.commit()


# ── Migration v11: version + fresh DB ────────────────────────────────────────


@pytest.mark.unit
def test_current_schema_version_at_least_11() -> None:
    """CURRENT_SCHEMA_VERSION should be at least 11 (migration v11 widens split CHECK)."""
    assert CURRENT_SCHEMA_VERSION >= 11


@pytest.mark.unit
def test_fresh_project_db_accepts_split_both(tmp_path: Path) -> None:
    """A fresh project DB lands at the current version and accepts split='both'."""
    db_path = tmp_path / "project.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # The widened CHECK must accept a 'both' split insert.
        _insert_both_dataset(conn)
        row = conn.execute("SELECT name, split FROM datasets WHERE name = ?", ("dual",)).fetchone()
        assert row is not None
        assert row[1] == "both"
    finally:
        conn.close()


# ── Migration v11: upgrade from v10 ──────────────────────────────────────────


@pytest.mark.unit
def test_migration_v10_to_v11_widens_split_check(tmp_path: Path) -> None:
    """A v10 project DB upgrades to v11: rows preserved, split='both' now accepted."""
    db_path = tmp_path / "migrate.db"
    _create_v10_project_db(db_path)

    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # The pre-existing dataset row must survive the table recreate.
        row = conn.execute(
            "SELECT name, path, split, storage, description, global_hash, "
            "instance_count, registered_at FROM datasets WHERE name = ?",
            ("train-small",),
        ).fetchone()
        assert row is not None, "pre-existing dataset row lost during migration"
        assert row[0] == "train-small"
        assert row[2] == "train"
        assert row[6] == 12

        # The widened CHECK must now accept a 'both' split insert.
        _insert_both_dataset(conn)
        both_row = conn.execute("SELECT split FROM datasets WHERE name = ?", ("dual",)).fetchone()
        assert both_row is not None
        assert both_row[0] == "both"
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_v10_to_v11_global_db(tmp_path: Path) -> None:
    """A v10 global DB (no datasets table) just gets the version bump to v11."""
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
    max_tokens      INTEGER,
    timeout_s       INTEGER,
    temperature     REAL,
    registered_at   TEXT NOT NULL
);
""")
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (10, "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    conn = get_global_db_at(db_path)
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # The datasets table is project-only; it must not appear on the global DB.
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='datasets'"
        )
        assert cursor.fetchone() is None
    finally:
        conn.close()
