"""L1 unit tests for ensemble DB tables and CRUD helpers (S11-01, S11-02).

Tests cover:
- Migration v8 creates ensemble tables in global DB
- Migration v8 adds llm_type/llm_snapshot columns to runs in project DB
- Migration from v7 to v8 works without data loss
- insert_ensemble / get_ensemble / list_ensembles / delete_ensemble
- add_ensemble_member / get_ensemble_members
- Edge cases: duplicate ensemble name, duplicate member, delete nonexistent

Traceable to: DES-001, sprint-011 S11-01, S11-02.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from revolver.core.exceptions import DuplicateNameError
from revolver.infra.db import (
    CURRENT_SCHEMA_VERSION,
    add_ensemble_member,
    delete_ensemble,
    get_ensemble,
    get_ensemble_members,
    get_global_db_at,
    get_project_db,
    insert_ensemble,
    list_ensembles,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def global_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a global DB for testing."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    yield conn  # type: ignore[misc]
    conn.close()


@pytest.fixture()
def project_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a project DB for testing."""
    db_path = tmp_path / "project.db"
    conn = get_project_db(db_path)
    yield conn  # type: ignore[misc]
    conn.close()


# ── Migration v8: Schema ────────────────────────────────────────────────────


@pytest.mark.unit
def test_schema_version_is_at_least_8() -> None:
    """CURRENT_SCHEMA_VERSION should be at least 8 (v8 features present)."""
    assert CURRENT_SCHEMA_VERSION >= 8


@pytest.mark.unit
def test_global_db_has_ensembles_table(global_conn: sqlite3.Connection) -> None:
    """Global DB must contain the ensembles table after migration v8."""
    cursor = global_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ensembles'"
    )
    assert cursor.fetchone() is not None, "ensembles table not found in global DB"


@pytest.mark.unit
def test_global_db_has_ensemble_members_table(global_conn: sqlite3.Connection) -> None:
    """Global DB must contain the ensemble_members table after migration v8."""
    cursor = global_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ensemble_members'"
    )
    assert cursor.fetchone() is not None, "ensemble_members table not found in global DB"


@pytest.mark.unit
def test_project_db_runs_has_llm_type_column(project_conn: sqlite3.Connection) -> None:
    """Project DB runs table must have llm_type column after migration v8."""
    cursor = project_conn.execute("PRAGMA table_info(runs)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "llm_type" in columns, "llm_type column not found in runs table"


@pytest.mark.unit
def test_project_db_runs_has_llm_snapshot_column(project_conn: sqlite3.Connection) -> None:
    """Project DB runs table must have llm_snapshot column after migration v8."""
    cursor = project_conn.execute("PRAGMA table_info(runs)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "llm_snapshot" in columns, "llm_snapshot column not found in runs table"


@pytest.mark.unit
def test_project_db_llm_type_default(project_conn: sqlite3.Connection) -> None:
    """llm_type column should default to 'single'."""
    cursor = project_conn.execute("PRAGMA table_info(runs)")
    for row in cursor.fetchall():
        if row[1] == "llm_type":
            # row[4] is the default value
            assert row[4] == "'single'", f"Expected default 'single', got {row[4]}"
            return
    pytest.fail("llm_type column not found")


@pytest.mark.unit
def test_global_db_schema_version_current(global_conn: sqlite3.Connection) -> None:
    """Global DB schema_version should be the current version."""
    cursor = global_conn.execute("SELECT MAX(version) FROM schema_version")
    row = cursor.fetchone()
    assert row is not None and row[0] == CURRENT_SCHEMA_VERSION


@pytest.mark.unit
def test_project_db_schema_version_current(project_conn: sqlite3.Connection) -> None:
    """Project DB schema_version should be the current version."""
    cursor = project_conn.execute("SELECT MAX(version) FROM schema_version")
    row = cursor.fetchone()
    assert row is not None and row[0] == CURRENT_SCHEMA_VERSION


# ── Migration from v7: no data loss ────────────────────────────────────────


@pytest.mark.unit
def test_migration_v7_to_v8_preserves_llm_data(tmp_path: Path) -> None:
    """Migrating a v7 global DB to v8 must preserve existing LLM registrations."""
    db_path = tmp_path / "migrate.db"
    # Create a v7-era DB manually (global schema without ensembles).
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
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
        (7, "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO llms (name, model, source, registered_at) VALUES (?, ?, ?, ?)",
        ("test-llm", "test-model", "remote", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    # Re-open via get_global_db_at — should trigger migration to v8.
    conn = get_global_db_at(db_path)
    try:
        # LLM data must still be there.
        cursor = conn.execute("SELECT name, model FROM llms WHERE name = 'test-llm'")
        row = cursor.fetchone()
        assert row is not None, "LLM data lost during migration"
        assert row[0] == "test-llm"
        assert row[1] == "test-model"

        # Ensemble tables must exist.
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ensembles'"
        )
        assert cursor.fetchone() is not None

        # Schema version must reach the current version (chain continues past 8).
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION
    finally:
        conn.close()


# ── Ensemble CRUD ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_insert_ensemble(global_conn: sqlite3.Connection) -> None:
    """insert_ensemble creates an ensemble record."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)

    result = get_ensemble(global_conn, "alphevo")
    assert result is not None
    assert result["name"] == "alphevo"


@pytest.mark.unit
def test_insert_ensemble_duplicate(global_conn: sqlite3.Connection) -> None:
    """Inserting an ensemble with a duplicate name raises DuplicateNameError."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)
    with pytest.raises(DuplicateNameError):
        insert_ensemble(global_conn, "alphevo", ts)


@pytest.mark.unit
def test_get_ensemble_not_found(global_conn: sqlite3.Connection) -> None:
    """get_ensemble returns None for a nonexistent name."""
    assert get_ensemble(global_conn, "nonexistent") is None


@pytest.mark.unit
def test_list_ensembles_empty(global_conn: sqlite3.Connection) -> None:
    """list_ensembles returns empty list when no ensembles exist."""
    assert list_ensembles(global_conn) == []


@pytest.mark.unit
def test_list_ensembles(global_conn: sqlite3.Connection) -> None:
    """list_ensembles returns all ensembles ordered by name."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "beta", ts)
    insert_ensemble(global_conn, "alpha", ts)

    result = list_ensembles(global_conn)
    assert len(result) == 2
    assert result[0]["name"] == "alpha"
    assert result[1]["name"] == "beta"


@pytest.mark.unit
def test_delete_ensemble(global_conn: sqlite3.Connection) -> None:
    """delete_ensemble removes an ensemble and returns 1."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)

    count = delete_ensemble(global_conn, "alphevo")
    assert count == 1
    assert get_ensemble(global_conn, "alphevo") is None


@pytest.mark.unit
def test_delete_ensemble_not_found(global_conn: sqlite3.Connection) -> None:
    """delete_ensemble returns 0 when the ensemble does not exist."""
    count = delete_ensemble(global_conn, "nonexistent")
    assert count == 0


@pytest.mark.unit
def test_delete_ensemble_cascades_members(global_conn: sqlite3.Connection) -> None:
    """Deleting an ensemble must CASCADE-delete its members."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)
    add_ensemble_member(global_conn, "alphevo", "flash-lite", 0.8)
    add_ensemble_member(global_conn, "alphevo", "pro", 0.2)

    delete_ensemble(global_conn, "alphevo")

    # Members should be gone.
    members = get_ensemble_members(global_conn, "alphevo")
    assert members == []


# ── Ensemble member CRUD ────────────────────────────────────────────────────


@pytest.mark.unit
def test_add_ensemble_member(global_conn: sqlite3.Connection) -> None:
    """add_ensemble_member inserts a member record."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)
    add_ensemble_member(global_conn, "alphevo", "flash-lite", 0.8)

    members = get_ensemble_members(global_conn, "alphevo")
    assert len(members) == 1
    assert members[0]["llm_name"] == "flash-lite"
    assert members[0]["weight"] == 0.8
    assert members[0]["temperature_override"] is None
    assert members[0]["max_tokens_override"] is None


@pytest.mark.unit
def test_add_ensemble_member_with_overrides(global_conn: sqlite3.Connection) -> None:
    """add_ensemble_member stores temperature and max_tokens overrides."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)
    add_ensemble_member(
        global_conn,
        "alphevo",
        "pro",
        0.2,
        temperature_override=0.5,
        max_tokens_override=4096,
    )

    members = get_ensemble_members(global_conn, "alphevo")
    assert len(members) == 1
    assert members[0]["temperature_override"] == 0.5
    assert members[0]["max_tokens_override"] == 4096
    assert members[0]["reasoning_effort"] is None


@pytest.mark.unit
def test_add_ensemble_member_reasoning_effort_round_trip(
    global_conn: sqlite3.Connection,
) -> None:
    """A per-member reasoning_effort override survives insert → get (S17-25)."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)
    add_ensemble_member(
        global_conn,
        "alphevo",
        "pro",
        0.2,
        reasoning_effort_override="high",
    )

    members = get_ensemble_members(global_conn, "alphevo")
    assert len(members) == 1
    assert members[0]["reasoning_effort"] == "high"


@pytest.mark.unit
def test_add_ensemble_member_reasoning_effort_defaults_none(
    global_conn: sqlite3.Connection,
) -> None:
    """A member added without a reasoning_effort override reads back as None."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)
    add_ensemble_member(global_conn, "alphevo", "flash-lite", 0.8)

    members = get_ensemble_members(global_conn, "alphevo")
    assert members[0]["reasoning_effort"] is None


@pytest.mark.unit
def test_add_ensemble_member_duplicate(global_conn: sqlite3.Connection) -> None:
    """Adding the same LLM twice to an ensemble raises DuplicateNameError."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)
    add_ensemble_member(global_conn, "alphevo", "flash-lite", 0.8)

    with pytest.raises(DuplicateNameError):
        add_ensemble_member(global_conn, "alphevo", "flash-lite", 0.5)


@pytest.mark.unit
def test_get_ensemble_members_empty(global_conn: sqlite3.Connection) -> None:
    """get_ensemble_members returns empty list for ensemble with no members."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "empty-ens", ts)

    members = get_ensemble_members(global_conn, "empty-ens")
    assert members == []


@pytest.mark.unit
def test_get_ensemble_members_ordered(global_conn: sqlite3.Connection) -> None:
    """get_ensemble_members returns members ordered by llm_name."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    insert_ensemble(global_conn, "alphevo", ts)
    add_ensemble_member(global_conn, "alphevo", "pro", 0.2)
    add_ensemble_member(global_conn, "alphevo", "flash-lite", 0.8)

    members = get_ensemble_members(global_conn, "alphevo")
    assert len(members) == 2
    assert members[0]["llm_name"] == "flash-lite"
    assert members[1]["llm_name"] == "pro"


@pytest.mark.unit
def test_get_ensemble_members_nonexistent_ensemble(
    global_conn: sqlite3.Connection,
) -> None:
    """get_ensemble_members returns empty list for nonexistent ensemble."""
    members = get_ensemble_members(global_conn, "nonexistent")
    assert members == []
