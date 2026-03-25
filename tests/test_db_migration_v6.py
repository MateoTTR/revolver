"""L1 unit tests for DB migration v5->v6 — temperature column on llms table."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from revolver.infra.db import (
    CURRENT_SCHEMA_VERSION,
    get_global_db_at,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_v5_global_database(db_path: Path) -> sqlite3.Connection:
    """Create a v5-schema global database WITHOUT the temperature column.

    This manually creates the v5 global schema so we can test the v5->v6
    migration path.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""\
CREATE TABLE schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE llms (
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
    registered_at   TEXT NOT NULL
);
""")

    # Mark as v5
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (5, now),
    )
    conn.commit()
    return conn


def _seed_v5_llm_rows(conn: sqlite3.Connection) -> None:
    """Insert representative LLM rows into a v5 global database."""
    now = datetime.now(UTC).isoformat()

    conn.execute(
        "INSERT INTO llms (name, provider, model, source, base_url, api_key_env, "
        "input_cost_per_mtok, output_cost_per_mtok, max_tokens, timeout_s, registered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "claude-sonnet",
            "anthropic",
            "claude-sonnet-4-20250514",
            "remote",
            "https://api.anthropic.com/v1",
            "ANTHROPIC_API_KEY",
            3.0,
            15.0,
            4096,
            60,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO llms (name, provider, model, source, base_url, api_key_env, "
        "input_cost_per_mtok, output_cost_per_mtok, max_tokens, timeout_s, registered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "gpt-4o",
            "openai",
            "gpt-4o",
            "remote",
            "https://api.openai.com/v1",
            "OPENAI_API_KEY",
            2.5,
            10.0,
            None,
            None,
            now,
        ),
    )
    conn.commit()


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_migration_v5_to_v6_adds_temperature_column(tmp_path: Path) -> None:
    """Migration v5->v6 must add temperature column to llms table."""
    db_path = tmp_path / "global.db"
    conn = _create_v5_global_database(db_path)
    _seed_v5_llm_rows(conn)
    conn.close()

    # Re-open via get_global_db_at which triggers migrations
    conn = get_global_db_at(db_path)

    # Verify schema version is current (all migrations applied)
    cursor = conn.execute("SELECT MAX(version) FROM schema_version")
    assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

    # Verify temperature column exists by querying it
    cursor = conn.execute("SELECT temperature FROM llms WHERE name = 'claude-sonnet'")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] is None, "Existing LLM rows should have temperature=NULL after migration"

    conn.close()


@pytest.mark.unit
def test_migration_v5_to_v6_existing_rows_get_null(tmp_path: Path) -> None:
    """Existing LLM rows must have temperature=NULL after v5->v6 migration."""
    db_path = tmp_path / "global.db"
    conn = _create_v5_global_database(db_path)
    _seed_v5_llm_rows(conn)
    conn.close()

    # Re-open to trigger migration
    conn = get_global_db_at(db_path)

    # Both existing rows should have NULL temperature
    cursor = conn.execute("SELECT name, temperature FROM llms ORDER BY name")
    rows = cursor.fetchall()
    assert len(rows) == 2
    for name, temp in rows:
        assert temp is None, f"LLM '{name}' should have temperature=NULL, got {temp}"

    conn.close()


@pytest.mark.unit
def test_migration_v5_to_v6_new_llm_with_temperature(tmp_path: Path) -> None:
    """After v5->v6 migration, new LLMs can be inserted with a temperature value."""
    db_path = tmp_path / "global.db"
    conn = _create_v5_global_database(db_path)
    _seed_v5_llm_rows(conn)
    conn.close()

    # Re-open to trigger migration
    conn = get_global_db_at(db_path)

    # Insert a new LLM with temperature
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO llms (name, provider, model, source, base_url, api_key_env, "
        "input_cost_per_mtok, output_cost_per_mtok, max_tokens, timeout_s, "
        "temperature, registered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "new-llm",
            "openai",
            "gpt-4o-mini",
            "remote",
            "https://api.openai.com/v1",
            "OPENAI_API_KEY",
            0.15,
            0.6,
            2048,
            30,
            0.7,
            now,
        ),
    )
    conn.commit()

    # Verify the new row has temperature=0.7
    cursor = conn.execute("SELECT temperature FROM llms WHERE name = 'new-llm'")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == 0.7

    # Verify old rows still have NULL
    cursor = conn.execute("SELECT temperature FROM llms WHERE name = 'claude-sonnet'")
    assert cursor.fetchone()[0] is None

    conn.close()


@pytest.mark.unit
def test_migration_v5_to_v6_preserves_existing_data(tmp_path: Path) -> None:
    """Migration v5->v6 must preserve all existing LLM data."""
    db_path = tmp_path / "global.db"
    conn = _create_v5_global_database(db_path)
    _seed_v5_llm_rows(conn)
    conn.close()

    # Re-open to trigger migration
    conn = get_global_db_at(db_path)

    # Verify all data preserved
    assert conn.execute("SELECT COUNT(*) FROM llms").fetchone()[0] == 2

    # Verify specific field values
    cursor = conn.execute(
        "SELECT provider, model, source, base_url, max_tokens, timeout_s "
        "FROM llms WHERE name = 'claude-sonnet'"
    )
    row = cursor.fetchone()
    assert row == (
        "anthropic",
        "claude-sonnet-4-20250514",
        "remote",
        "https://api.anthropic.com/v1",
        4096,
        60,
    )

    conn.close()
