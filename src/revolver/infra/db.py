"""SQLite database connection factory and schema management.

Provides connection factories for both the project-level database
(.revolver/revolver.db) and the global user-level database
(~/.revolver/revolver.db). Both use WAL mode and enforce foreign keys.

Traceable to: DES-001 (SQLite Data Model), NFR-013, NFR-016.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from revolver.core.exceptions import DuplicateNameError
from revolver.models.llm import LLMEntry
from revolver.models.problem import ProblemVersion

# Current schema version — bump when adding migrations.
CURRENT_SCHEMA_VERSION = 1

# ── Project DB schema ────────────────────────────────────────────────────────

_PROJECT_SCHEMA_SQL = """\
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
    split           TEXT NOT NULL CHECK (split IN ('train', 'eval')),
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
                      CHECK (status IN ('running', 'completed', 'interrupted')),
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

CREATE TABLE IF NOT EXISTS benchmarks (
    id              TEXT PRIMARY KEY,
    alias           TEXT,
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_benchmarks_created ON benchmarks(created_at DESC);

CREATE TABLE IF NOT EXISTS benchmark_solutions (
    benchmark_id    TEXT NOT NULL REFERENCES benchmarks(id),
    solution_id     TEXT NOT NULL REFERENCES solutions(id),
    PRIMARY KEY (benchmark_id, solution_id)
);
"""

# ── Global DB schema ─────────────────────────────────────────────────────────

_GLOBAL_SCHEMA_SQL = """\
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
    registered_at   TEXT NOT NULL
);
"""

# ── Migrations ───────────────────────────────────────────────────────────────

# Forward-only migrations. Key = target version, value = SQL to apply.
# Version 1 is the initial schema (handled by _apply_schema above).
MIGRATIONS: dict[int, str] = {}


def _configure_connection(conn: sqlite3.Connection) -> None:
    """Apply standard PRAGMAs to a connection."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")


def _ensure_schema_version(conn: sqlite3.Connection) -> None:
    """Insert schema_version row if not present."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
        (CURRENT_SCHEMA_VERSION, now),
    )
    conn.commit()


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply any pending forward-only migrations."""
    cursor = conn.execute("SELECT MAX(version) FROM schema_version")
    row = cursor.fetchone()
    current = row[0] if row[0] is not None else 0

    for target_version in sorted(MIGRATIONS.keys()):
        if target_version > current:
            conn.executescript(MIGRATIONS[target_version])
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (target_version, now),
            )
            conn.commit()


def get_project_db(path: Path) -> sqlite3.Connection:
    """Open (or create) the project SQLite database.

    Args:
        path: Path to the SQLite database file (e.g. ``.revolver/revolver.db``).

    Returns:
        A configured ``sqlite3.Connection`` with WAL mode and foreign keys enabled.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    _configure_connection(conn)
    conn.executescript(_PROJECT_SCHEMA_SQL)
    _ensure_schema_version(conn)
    _run_migrations(conn)
    return conn


def get_global_db() -> sqlite3.Connection:
    """Open (or create) the global user-level database at ``~/.revolver/revolver.db``.

    Returns:
        A configured ``sqlite3.Connection`` with WAL mode and foreign keys enabled.
    """
    global_dir = Path.home() / ".revolver"
    global_dir.mkdir(parents=True, exist_ok=True)
    db_path = global_dir / "revolver.db"
    conn = sqlite3.connect(str(db_path))
    _configure_connection(conn)
    conn.executescript(_GLOBAL_SCHEMA_SQL)
    _ensure_schema_version(conn)
    _run_migrations(conn)
    return conn


def get_global_db_at(path: Path) -> sqlite3.Connection:
    """Open (or create) a global-schema database at a custom *path*.

    This is primarily intended for testing, so tests can avoid touching
    the real ``~/.revolver/`` directory.

    Args:
        path: Full path to the SQLite database file.

    Returns:
        A configured ``sqlite3.Connection`` with WAL mode and foreign keys enabled.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    _configure_connection(conn)
    conn.executescript(_GLOBAL_SCHEMA_SQL)
    _ensure_schema_version(conn)
    _run_migrations(conn)
    return conn


# ── Problem version CRUD ────────────────────────────────────────────────────


def insert_problem_version(conn: sqlite3.Connection, version: ProblemVersion) -> None:
    """Insert a problem version into the project database.

    Args:
        conn: An open project database connection.
        version: The :class:`ProblemVersion` to insert.

    Raises:
        DuplicateNameError: If a version with the same tag already exists.
    """
    try:
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
            (
                version.tag,
                version.hash,
                version.message,
                version.created_at.isoformat(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise DuplicateNameError(f"Problem version conflict: {exc}") from exc


def get_problem_version(conn: sqlite3.Connection, tag: str) -> ProblemVersion | None:
    """Retrieve a problem version by tag.

    Args:
        conn: An open project database connection.
        tag: The version tag to look up.

    Returns:
        The :class:`ProblemVersion` if found, otherwise ``None``.
    """
    cursor = conn.execute(
        "SELECT tag, hash, message, created_at FROM problem_versions WHERE tag = ?",
        (tag,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return ProblemVersion(
        tag=row[0],
        hash=row[1],
        message=row[2] or "",
        created_at=datetime.fromisoformat(row[3]),
    )


def list_problem_versions(conn: sqlite3.Connection) -> list[ProblemVersion]:
    """List all problem versions ordered by creation time (ascending).

    Args:
        conn: An open project database connection.

    Returns:
        A list of :class:`ProblemVersion` instances, oldest first.
    """
    cursor = conn.execute(
        "SELECT tag, hash, message, created_at FROM problem_versions ORDER BY created_at ASC"
    )
    return [
        ProblemVersion(
            tag=row[0],
            hash=row[1],
            message=row[2] or "",
            created_at=datetime.fromisoformat(row[3]),
        )
        for row in cursor.fetchall()
    ]


# ── LLM CRUD operations ─────────────────────────────────────────────────────


def insert_llm(conn: sqlite3.Connection, entry: LLMEntry) -> None:
    """Insert an LLM entry into the ``llms`` table.

    Args:
        conn: A connection to the global database.
        entry: The LLM entry to insert.

    Raises:
        DuplicateNameError: If an LLM with the same *name* already exists.
    """
    try:
        conn.execute(
            """\
            INSERT INTO llms (
                name, provider, model, source, base_url, api_key_env,
                input_cost_per_mtok, output_cost_per_mtok, registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.name,
                entry.provider,
                entry.model,
                entry.source,
                entry.base_url,
                entry.api_key_env,
                entry.input_cost_per_mtok,
                entry.output_cost_per_mtok,
                entry.registered_at.isoformat(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise DuplicateNameError(f"An LLM named '{entry.name}' already exists") from exc


def get_llm(conn: sqlite3.Connection, name: str) -> LLMEntry | None:
    """Retrieve an LLM entry by name.

    Args:
        conn: A connection to the global database.
        name: The unique LLM name.

    Returns:
        The matching :class:`LLMEntry`, or ``None`` if not found.
    """
    cursor = conn.execute("SELECT * FROM llms WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row is None:
        return None

    # Map columns by position (matches CREATE TABLE order).
    return LLMEntry(
        name=row[0],
        provider=row[1],
        model=row[2],
        source=row[3],
        base_url=row[4],
        api_key_env=row[5],
        input_cost_per_mtok=row[6],
        output_cost_per_mtok=row[7],
        registered_at=row[8],
    )


def list_llms(conn: sqlite3.Connection) -> list[LLMEntry]:
    """List all registered LLMs, ordered by name.

    Args:
        conn: A connection to the global database.

    Returns:
        A list of :class:`LLMEntry` instances sorted alphabetically by name.
    """
    cursor = conn.execute("SELECT * FROM llms ORDER BY name")
    return [
        LLMEntry(
            name=row[0],
            provider=row[1],
            model=row[2],
            source=row[3],
            base_url=row[4],
            api_key_env=row[5],
            input_cost_per_mtok=row[6],
            output_cost_per_mtok=row[7],
            registered_at=row[8],
        )
        for row in cursor.fetchall()
    ]


def delete_llm(conn: sqlite3.Connection, name: str) -> None:
    """Delete an LLM by name.

    Args:
        conn: A connection to the global database.
        name: The unique LLM name to delete.
    """
    conn.execute("DELETE FROM llms WHERE name = ?", (name,))
    conn.commit()


def update_llm_stats(
    conn: sqlite3.Connection,
    name: str,
    vram_mib: int | None = None,
    throughput_tps: float | None = None,
) -> None:
    """Update measured runtime stats for an LLM after loading.

    Currently a no-op placeholder — the ``llms`` table does not yet have
    stat columns.  This function is provided so that calling code can
    record stats without breaking when the schema is extended.

    Args:
        conn: A connection to the global database.
        name: The unique LLM name.
        vram_mib: Measured VRAM usage in MiB (reserved for future use).
        throughput_tps: Measured tokens-per-second (reserved for future use).
    """
    # Placeholder: schema extension for stats columns is planned.
    _ = conn, name, vram_mib, throughput_tps
