"""L1 unit tests for DB migration v12 — add reasoning_effort to llms (S17-10).

Tests cover:
- CURRENT_SCHEMA_VERSION is at least 12
- A fresh global DB lands at the current schema version with the
  ``reasoning_effort`` column on the ``llms`` table
- A v11 global DB (without the column, with an existing llm row) upgrades to
  v12: the column is added, the existing row is preserved with ``NULL``
- A round-trip insert of an LLMEntry carrying reasoning_effort persists and
  reads back the value
- A v11 project DB (no llms table) upgrades to v12 (version bump only, no-op)

Traceable to: sprint-017 S17-10 (ADR-007 Amendment A3.2, FR-LLM-026),
DES-001 §5.11.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from revolver.infra.db import (
    CURRENT_SCHEMA_VERSION,
    get_global_db_at,
    get_llm,
    get_project_db,
    insert_llm,
)
from revolver.models.llm import LLMEntry

# v11-era global schema: the llms table has no reasoning_effort column yet.
_V11_GLOBAL_LLMS_SQL = """\
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
"""


def _llms_columns(conn: sqlite3.Connection) -> set[str]:
    """Return the set of column names on the llms table."""
    cursor = conn.execute("PRAGMA table_info(llms)")
    return {row[1] for row in cursor.fetchall()}


def _create_v11_global_db(db_path: Path) -> None:
    """Create a v11-era global DB (no reasoning_effort) with one llm row."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_V11_GLOBAL_LLMS_SQL)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (11, "2026-01-01T00:00:00"),
    )
    conn.execute(
        """\
        INSERT INTO llms (name, provider, model, source, base_url, api_key_env,
                          max_tokens, timeout_s, temperature, registered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "gpt-test",
            "openai",
            "gpt-4o",
            "remote",
            None,
            "OPENAI_API_KEY",
            4096,
            120,
            0.7,
            "2026-01-02T00:00:00",
        ),
    )
    conn.commit()
    conn.close()


# ── Migration v12: version + fresh DB ────────────────────────────────────────


@pytest.mark.unit
def test_current_schema_version_at_least_12() -> None:
    """CURRENT_SCHEMA_VERSION should be at least 12 (migration v12 adds llms.reasoning_effort)."""
    assert CURRENT_SCHEMA_VERSION >= 12


@pytest.mark.unit
def test_fresh_global_db_has_reasoning_effort_column(tmp_path: Path) -> None:
    """A fresh global DB lands at the current version with the reasoning_effort column."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        assert "reasoning_effort" in _llms_columns(conn)

        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION
    finally:
        conn.close()


# ── Migration v12: upgrade from v11 ──────────────────────────────────────────


@pytest.mark.unit
def test_migration_v11_to_v12_adds_column_preserves_rows(tmp_path: Path) -> None:
    """A v11 global DB upgrades to v12: column added, existing row preserved with NULL."""
    db_path = tmp_path / "migrate.db"
    _create_v11_global_db(db_path)

    conn = get_global_db_at(db_path)
    try:
        assert "reasoning_effort" in _llms_columns(conn)

        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # The pre-existing llm row survives with a NULL reasoning_effort.
        row = conn.execute(
            "SELECT name, model, max_tokens, reasoning_effort FROM llms WHERE name = ?",
            ("gpt-test",),
        ).fetchone()
        assert row is not None, "pre-existing llm row lost during migration"
        assert row[0] == "gpt-test"
        assert row[1] == "gpt-4o"
        assert row[2] == 4096
        assert row[3] is None
    finally:
        conn.close()


@pytest.mark.unit
def test_reasoning_effort_round_trips_through_crud(tmp_path: Path) -> None:
    """insert_llm/get_llm round-trip the reasoning_effort value on the migrated schema."""
    db_path = tmp_path / "roundtrip.db"
    conn = get_global_db_at(db_path)
    try:
        entry = LLMEntry(
            name="reasoner",
            provider="openai",
            model="o3",
            source="remote",
            api_key_env="OPENAI_API_KEY",
            reasoning_effort="high",
            registered_at=datetime.now(UTC),
        )
        insert_llm(conn, entry)

        fetched = get_llm(conn, "reasoner")
        assert fetched is not None
        assert fetched.reasoning_effort == "high"

        # A default (unset) LLM reads back None.
        default_entry = LLMEntry(
            name="plain",
            model="gpt-4o",
            source="remote",
            registered_at=datetime.now(UTC),
        )
        insert_llm(conn, default_entry)
        plain = get_llm(conn, "plain")
        assert plain is not None
        assert plain.reasoning_effort is None
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_v11_to_v12_project_db(tmp_path: Path) -> None:
    """A v11 project DB (no llms table) just gets the version bump to v12."""
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
        (11, "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # The llms table is global-only; it must not appear on the project DB.
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llms'")
        assert cursor.fetchone() is None
    finally:
        conn.close()
