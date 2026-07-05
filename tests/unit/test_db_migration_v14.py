"""L1 unit tests for DB migration v14 — add backend to problem_versions (S18-08).

Tests cover:
- CURRENT_SCHEMA_VERSION is at least 14
- A fresh project DB lands at the current schema version with the
  ``backend`` column on the ``problem_versions`` table
- A v13 project DB (problem_versions without the column, with an existing
  version row) upgrades to v14: the column is added, the existing row is
  preserved and backfilled to ``'openevolve'`` by the column default
- A v13 global DB (no problem_versions table) upgrades to v14 (version
  bump only, no-op)

Kept separate from prior migrations per the one-column-per-migration
discipline (mirrors the v13 migration test's structure).

Traceable to: sprint-018 S18-08 (U4 / #369, FR-PRB-016), DES-001 §3.1/§5.13,
DES-003 §2.2.2.
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

# v13-era project schema: problem_versions does NOT yet have the backend
# column (v14 adds it). Minimal shape — the other project tables are not
# involved in this migration.
_V13_PROJECT_SCHEMA_SQL = """\
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
"""


def _version_columns(conn: sqlite3.Connection) -> set[str]:
    """Return the set of column names on the problem_versions table."""
    cursor = conn.execute("PRAGMA table_info(problem_versions)")
    return {row[1] for row in cursor.fetchall()}


def _create_v13_project_db(db_path: Path) -> None:
    """Create a v13-era project DB (problem_versions w/o backend) with one version row."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_V13_PROJECT_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (13, "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
        ("v1.0", "sha256:abc123", "first version", "2026-01-02T00:00:00"),
    )
    conn.commit()
    conn.close()


# ── Migration v14: version + fresh DB ────────────────────────────────────────


@pytest.mark.unit
def test_current_schema_version_at_least_14() -> None:
    """CURRENT_SCHEMA_VERSION is at least 14 (v14 adds problem_versions.backend)."""
    assert CURRENT_SCHEMA_VERSION >= 14


@pytest.mark.unit
def test_db_migration_v14_problem_versions_backend(tmp_path: Path) -> None:
    """A fresh project DB lands at the current version with the backend column."""
    db_path = tmp_path / "project.db"
    conn = get_project_db(db_path)
    try:
        assert "backend" in _version_columns(conn)

        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # The column default backfills 'openevolve' when backend is omitted.
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
            ("v1.0", "sha256:fresh", "", "2026-01-02T00:00:00"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT backend FROM problem_versions WHERE tag = ?", ("v1.0",)
        ).fetchone()
        assert row[0] == "openevolve"
    finally:
        conn.close()


# ── Migration v14: upgrade from v13 ──────────────────────────────────────────


@pytest.mark.unit
def test_migration_v13_to_v14_adds_column_backfills_openevolve(tmp_path: Path) -> None:
    """A v13 project DB upgrades to v14: column added, existing row backfilled."""
    db_path = tmp_path / "migrate.db"
    _create_v13_project_db(db_path)

    conn = get_project_db(db_path)
    try:
        assert "backend" in _version_columns(conn)

        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # The pre-existing version row survives, backfilled to 'openevolve'
        # (all pre-v14 versions were validated against OpenEvolve).
        row = conn.execute(
            "SELECT tag, hash, message, backend FROM problem_versions WHERE tag = ?",
            ("v1.0",),
        ).fetchone()
        assert row is not None, "pre-existing problem version row lost during migration"
        assert row[1] == "sha256:abc123"
        assert row[2] == "first version"
        assert row[3] == "openevolve"

        # The new column accepts a non-default backend value.
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, backend, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("v2.0", "sha256:def456", "", "shinka", "2026-01-03T00:00:00"),
        )
        conn.commit()
        stored = conn.execute(
            "SELECT backend FROM problem_versions WHERE tag = ?", ("v2.0",)
        ).fetchone()
        assert stored[0] == "shinka"
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_v13_to_v14_global_db_noop_bump(tmp_path: Path) -> None:
    """A v13 global DB (no problem_versions table) just gets the version bump to v14."""
    db_path = tmp_path / "global.db"
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
        (13, "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    conn = get_global_db_at(db_path)
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

        # problem_versions is project-only; it must not appear on the global DB.
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='problem_versions'"
        )
        assert cursor.fetchone() is None
    finally:
        conn.close()
