"""L1 unit tests for DB migration v13 — add reasoning_effort to ensemble_members (S17-11).

Tests cover:
- CURRENT_SCHEMA_VERSION is at least 13
- A fresh global DB lands at the current schema version with the
  ``reasoning_effort`` column on the ``ensemble_members`` table
- A v12 global DB (ensemble_members without the column, with an existing member
  row) upgrades to v13: the column is added, the existing row is preserved with
  ``NULL``
- A v12 project DB (no ensemble_members table) upgrades to v13 (version bump
  only, no-op)

Kept separate from migration v12 per the one-column-per-migration discipline.

Traceable to: sprint-017 S17-11 (ADR-007 Amendment A3.2), DES-001 §5.12.
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

# v12-era global schema: llms already has reasoning_effort (v12), but
# ensemble_members does NOT yet (v13 adds it).
_V12_GLOBAL_SCHEMA_SQL = """\
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
    reasoning_effort TEXT,
    registered_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ensembles (
    name        TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ensemble_members (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ensemble_name       TEXT NOT NULL REFERENCES ensembles(name) ON DELETE CASCADE,
    llm_name            TEXT NOT NULL,
    weight              REAL NOT NULL DEFAULT 1.0,
    temperature_override REAL,
    max_tokens_override INTEGER,
    UNIQUE(ensemble_name, llm_name)
);
"""


def _members_columns(conn: sqlite3.Connection) -> set[str]:
    """Return the set of column names on the ensemble_members table."""
    cursor = conn.execute("PRAGMA table_info(ensemble_members)")
    return {row[1] for row in cursor.fetchall()}


def _create_v12_global_db(db_path: Path) -> None:
    """Create a v12-era global DB (ensemble_members w/o reasoning_effort) with one member row."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_V12_GLOBAL_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (12, "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO ensembles (name, created_at) VALUES (?, ?)",
        ("my-ensemble", "2026-01-02T00:00:00"),
    )
    conn.execute(
        """\
        INSERT INTO ensemble_members
            (ensemble_name, llm_name, weight, temperature_override, max_tokens_override)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("my-ensemble", "gpt-4o", 0.7, 0.5, 4096),
    )
    conn.commit()
    conn.close()


# ── Migration v13: version + fresh DB ────────────────────────────────────────


@pytest.mark.unit
def test_current_schema_version_at_least_13() -> None:
    """CURRENT_SCHEMA_VERSION is at least 13 (v13 adds ensemble_members.reasoning_effort)."""
    assert CURRENT_SCHEMA_VERSION >= 13


@pytest.mark.unit
def test_fresh_global_db_has_member_reasoning_effort_column(tmp_path: Path) -> None:
    """A fresh global DB lands at the current version with member reasoning_effort column."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        assert "reasoning_effort" in _members_columns(conn)

        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION
    finally:
        conn.close()


# ── Migration v13: upgrade from v12 ──────────────────────────────────────────


@pytest.mark.unit
def test_migration_v12_to_v13_adds_column_preserves_rows(tmp_path: Path) -> None:
    """A v12 global DB upgrades to v13: member column added, existing row preserved with NULL."""
    db_path = tmp_path / "migrate.db"
    _create_v12_global_db(db_path)

    conn = get_global_db_at(db_path)
    try:
        assert "reasoning_effort" in _members_columns(conn)

        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # The pre-existing member row survives with a NULL reasoning_effort.
        row = conn.execute(
            """\
            SELECT ensemble_name, llm_name, weight, temperature_override,
                   max_tokens_override, reasoning_effort
            FROM ensemble_members WHERE ensemble_name = ? AND llm_name = ?
            """,
            ("my-ensemble", "gpt-4o"),
        ).fetchone()
        assert row is not None, "pre-existing ensemble member row lost during migration"
        assert row[1] == "gpt-4o"
        assert row[2] == 0.7
        assert row[3] == 0.5
        assert row[4] == 4096
        assert row[5] is None

        # The new column accepts a per-member reasoning_effort value.
        conn.execute(
            "UPDATE ensemble_members SET reasoning_effort = ? "
            "WHERE ensemble_name = ? AND llm_name = ?",
            ("high", "my-ensemble", "gpt-4o"),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT reasoning_effort FROM ensemble_members "
            "WHERE ensemble_name = ? AND llm_name = ?",
            ("my-ensemble", "gpt-4o"),
        ).fetchone()
        assert updated[0] == "high"
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_v12_to_v13_project_db(tmp_path: Path) -> None:
    """A v12 project DB (no ensemble_members table) just gets the version bump to v13."""
    db_path = tmp_path / "project.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""\
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);
""")
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (12, "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # ensemble_members is global-only; it must not appear on the project DB.
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ensemble_members'"
        )
        assert cursor.fetchone() is None
    finally:
        conn.close()
