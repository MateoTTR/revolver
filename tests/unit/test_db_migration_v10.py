"""L1 unit tests for DB migration v10 — drop inert pricing columns from llms (S16-05).

Tests cover:
- CURRENT_SCHEMA_VERSION is 10
- A fresh global DB lands at schema v10 with no pricing columns on the llms table
- A v9 global DB (with the two inert cost columns + an existing llm row) upgrades
  to v10: the cost columns are dropped and the existing row is preserved
- A v9 project DB (no llms table) upgrades to v10 (version bump only, no-op)

Traceable to: sprint-016 S16-05 (TD-1), backlog #300 / #310.
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

# v9-era global schema: the llms table still carries the two inert pricing columns.
_V9_GLOBAL_LLMS_WITH_COST_SQL = """\
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
"""

_COST_COLUMNS = {"input_cost_per_mtok", "output_cost_per_mtok"}


def _llms_columns(conn: sqlite3.Connection) -> set[str]:
    """Return the set of column names on the llms table."""
    cursor = conn.execute("PRAGMA table_info(llms)")
    return {row[1] for row in cursor.fetchall()}


def _create_v9_global_db(db_path: Path) -> None:
    """Create a v9-era global DB with the cost columns and one llm row carrying cost values."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_V9_GLOBAL_LLMS_WITH_COST_SQL)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (9, "2026-01-01T00:00:00"),
    )
    conn.execute(
        """\
        INSERT INTO llms (name, provider, model, source, base_url, api_key_env,
                          input_cost_per_mtok, output_cost_per_mtok,
                          max_tokens, timeout_s, temperature, registered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "gpt-test",
            "openai",
            "gpt-4o",
            "remote",
            None,
            "OPENAI_API_KEY",
            2.5,
            10.0,
            4096,
            120,
            0.7,
            "2026-01-02T00:00:00",
        ),
    )
    conn.commit()
    conn.close()


# ── Migration v10: version + fresh DB ────────────────────────────────────────


@pytest.mark.unit
def test_current_schema_version_is_10() -> None:
    """CURRENT_SCHEMA_VERSION should be 10 after migration v10 (drop pricing columns)."""
    assert CURRENT_SCHEMA_VERSION == 10


@pytest.mark.unit
def test_fresh_global_db_has_no_cost_columns(tmp_path: Path) -> None:
    """A fresh global DB lands at v10 with no pricing columns on the llms table."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        columns = _llms_columns(conn)
        assert not (_COST_COLUMNS & columns), f"pricing columns still present: {columns}"

        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == 10
    finally:
        conn.close()


# ── Migration v10: upgrade from v9 ───────────────────────────────────────────


@pytest.mark.unit
def test_migration_v9_to_v10_drops_cost_columns(tmp_path: Path) -> None:
    """A v9 global DB with cost columns upgrades to v10: columns dropped, rows preserved."""
    db_path = tmp_path / "migrate.db"
    _create_v9_global_db(db_path)

    conn = get_global_db_at(db_path)
    try:
        columns = _llms_columns(conn)
        assert not (_COST_COLUMNS & columns), f"cost columns not dropped: {columns}"

        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == 10

        # The pre-existing llm row must survive the table recreate (sans cost columns).
        row = conn.execute(
            "SELECT name, provider, model, source, api_key_env, max_tokens, "
            "timeout_s, temperature, registered_at FROM llms WHERE name = ?",
            ("gpt-test",),
        ).fetchone()
        assert row is not None, "pre-existing llm row lost during migration"
        assert row[0] == "gpt-test"
        assert row[2] == "gpt-4o"
        assert row[5] == 4096
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_v9_to_v10_project_db(tmp_path: Path) -> None:
    """A v9 project DB (no llms table) just gets the version bump to v10."""
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
        (9, "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == 10

        # The llms table is global-only; it must not appear on the project DB.
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llms'")
        assert cursor.fetchone() is None
    finally:
        conn.close()
