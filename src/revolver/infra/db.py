"""SQLite database connection factory and schema management.

Provides connection factories for both the project-level database
(.revolver/revolver.db) and the global user-level database
(~/.revolver/revolver.db). Both use WAL mode and enforce foreign keys.

Traceable to: DES-001 (SQLite Data Model), NFR-013, NFR-016.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from revolver.core.exceptions import DuplicateNameError
from revolver.models.dataset import (
    DatasetInstance,
    DatasetRegistration,
    DatasetSummary,
)
from revolver.models.eval import EvalMetadata, InstanceResult
from revolver.models.llm import LLMEntry
from revolver.models.problem import ProblemVersion
from revolver.models.solution import Solution

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
    split           TEXT CHECK (split IN ('train', 'eval')),
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


def get_problem_version_by_hash(
    conn: sqlite3.Connection, content_hash: str
) -> ProblemVersion | None:
    """Retrieve a problem version by content hash.

    Args:
        conn: An open project database connection.
        content_hash: The snapshot hash to look up.

    Returns:
        The :class:`ProblemVersion` if found, otherwise ``None``.
    """
    cursor = conn.execute(
        "SELECT tag, hash, message, created_at FROM problem_versions WHERE hash = ?",
        (content_hash,),
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

_LLM_COLUMNS = (
    "name, provider, model, source, base_url, api_key_env, "
    "input_cost_per_mtok, output_cost_per_mtok, registered_at"
)


def _row_to_llm_entry(row: tuple[object, ...]) -> LLMEntry:
    """Map a database row (with columns in ``_LLM_COLUMNS`` order) to an :class:`LLMEntry`."""
    return LLMEntry(
        name=row[0],  # type: ignore[arg-type]
        provider=row[1],  # type: ignore[arg-type]
        model=row[2],  # type: ignore[arg-type]
        source=row[3],  # type: ignore[arg-type]
        base_url=row[4],  # type: ignore[arg-type]
        api_key_env=row[5],  # type: ignore[arg-type]
        input_cost_per_mtok=row[6],  # type: ignore[arg-type]
        output_cost_per_mtok=row[7],  # type: ignore[arg-type]
        registered_at=row[8],  # type: ignore[arg-type]
    )


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
    cursor = conn.execute(
        f"SELECT {_LLM_COLUMNS} FROM llms WHERE name = ?",
        (name,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_llm_entry(row)


def list_llms(conn: sqlite3.Connection) -> list[LLMEntry]:
    """List all registered LLMs, ordered by name.

    Args:
        conn: A connection to the global database.

    Returns:
        A list of :class:`LLMEntry` instances sorted alphabetically by name.
    """
    cursor = conn.execute(f"SELECT {_LLM_COLUMNS} FROM llms ORDER BY name")
    return [_row_to_llm_entry(row) for row in cursor.fetchall()]


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


# ── Dataset CRUD operations ────────────────────────────────────────────────


def insert_dataset(
    conn: sqlite3.Connection,
    registration: DatasetRegistration,
    *,
    commit: bool = True,
) -> None:
    """Insert a dataset registration into the project database.

    Args:
        conn: An open project database connection.
        registration: The :class:`DatasetRegistration` to insert.
        commit: If ``True`` (default), commit the transaction immediately.
            Pass ``False`` when the caller manages the transaction.

    Raises:
        DuplicateNameError: If a dataset with the same name already exists.
    """
    try:
        conn.execute(
            """\
            INSERT INTO datasets (
                name, path, split, storage, description,
                global_hash, instance_count, registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                registration.name,
                registration.path,
                registration.split,
                registration.storage,
                registration.description or "",
                registration.global_hash,
                registration.instance_count,
                registration.created_at.isoformat(),
            ),
        )
        if commit:
            conn.commit()
    except sqlite3.IntegrityError as exc:
        raise DuplicateNameError(f"A dataset named '{registration.name}' already exists") from exc


def insert_dataset_instances(
    conn: sqlite3.Connection,
    name: str,
    instances: list[DatasetInstance],
    *,
    commit: bool = True,
) -> None:
    """Batch-insert dataset instance hashes.

    Uses ``executemany`` for performance with large instance counts (DD-05).

    Args:
        conn: An open project database connection.
        name: Dataset name (foreign key to ``datasets``).
        instances: List of :class:`DatasetInstance` to insert.
        commit: If ``True`` (default), commit the transaction immediately.
            Pass ``False`` when the caller manages the transaction.
    """
    conn.executemany(
        "INSERT INTO dataset_instances (dataset_name, instance_id, hash) VALUES (?, ?, ?)",
        [(name, inst.filename, inst.hash) for inst in instances],
    )
    if commit:
        conn.commit()


def insert_dataset_compat(
    conn: sqlite3.Connection,
    name: str,
    problem_version_tag: str,
    *,
    commit: bool = True,
) -> None:
    """Insert a dataset compatibility entry.

    Args:
        conn: An open project database connection.
        name: Dataset name.
        problem_version_tag: Problem version tag this dataset is compatible with.
        commit: If ``True`` (default), commit the transaction immediately.
            Pass ``False`` when the caller manages the transaction.
    """
    conn.execute(
        "INSERT INTO dataset_compat (dataset_name, problem_version) VALUES (?, ?)",
        (name, problem_version_tag),
    )
    if commit:
        conn.commit()


def get_dataset(conn: sqlite3.Connection, name: str) -> DatasetRegistration | None:
    """Retrieve a dataset registration by name.

    Args:
        conn: An open project database connection.
        name: The dataset name to look up.

    Returns:
        The :class:`DatasetRegistration` if found, otherwise ``None``.
    """
    cursor = conn.execute(
        """\
        SELECT name, path, split, storage, description,
               global_hash, instance_count, registered_at
        FROM datasets WHERE name = ?
        """,
        (name,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return DatasetRegistration(
        name=row[0],
        path=row[1],
        split=row[2],
        storage=row[3],
        description=row[4] or None,
        global_hash=row[5],
        instance_count=row[6],
        created_at=datetime.fromisoformat(row[7]),
    )


def get_dataset_instances(
    conn: sqlite3.Connection,
    name: str,
) -> list[DatasetInstance]:
    """Retrieve all instance hashes for a dataset.

    Args:
        conn: An open project database connection.
        name: The dataset name.

    Returns:
        List of :class:`DatasetInstance` sorted by instance_id.
    """
    cursor = conn.execute(
        """\
        SELECT instance_id, hash
        FROM dataset_instances
        WHERE dataset_name = ?
        ORDER BY instance_id
        """,
        (name,),
    )
    return [
        DatasetInstance(
            filename=row[0],
            relative_path=row[0],
            hash=row[1],
            size_bytes=0,
        )
        for row in cursor.fetchall()
    ]


def get_dataset_compat(conn: sqlite3.Connection, name: str) -> list[str]:
    """Retrieve compatible problem version tags for a dataset.

    Args:
        conn: An open project database connection.
        name: The dataset name.

    Returns:
        List of problem version tags.
    """
    cursor = conn.execute(
        "SELECT problem_version FROM dataset_compat "
        "WHERE dataset_name = ? ORDER BY problem_version",
        (name,),
    )
    return [row[0] for row in cursor.fetchall()]


def list_datasets(conn: sqlite3.Connection) -> list[DatasetSummary]:
    """List all registered datasets ordered by name.

    Args:
        conn: An open project database connection.

    Returns:
        A list of :class:`DatasetSummary` instances sorted alphabetically.
    """
    cursor = conn.execute(
        """\
        SELECT name, split, instance_count, storage, registered_at
        FROM datasets
        ORDER BY name
        """
    )
    return [
        DatasetSummary(
            name=row[0],
            split=row[1],
            instance_count=row[2],
            storage=row[3],
            created_at=datetime.fromisoformat(row[4]),
        )
        for row in cursor.fetchall()
    ]


def update_dataset_description(
    conn: sqlite3.Connection,
    name: str,
    description: str,
    *,
    commit: bool = True,
) -> None:
    """Update the description of a dataset.

    Args:
        conn: An open project database connection.
        name: The dataset name.
        description: New description text.
        commit: If ``True`` (default), commit the transaction immediately.
            Pass ``False`` when the caller manages the transaction.
    """
    conn.execute(
        "UPDATE datasets SET description = ? WHERE name = ?",
        (description, name),
    )
    if commit:
        conn.commit()


def delete_dataset(conn: sqlite3.Connection, name: str) -> None:
    """Delete a dataset registration.

    Args:
        conn: An open project database connection.
        name: The dataset name to delete.
    """
    conn.execute("DELETE FROM datasets WHERE name = ?", (name,))
    conn.commit()


def delete_dataset_instances(conn: sqlite3.Connection, name: str) -> None:
    """Delete all instance hashes for a dataset.

    Args:
        conn: An open project database connection.
        name: The dataset name whose instances to delete.
    """
    conn.execute("DELETE FROM dataset_instances WHERE dataset_name = ?", (name,))
    conn.commit()


def delete_dataset_compat_all(conn: sqlite3.Connection, name: str) -> None:
    """Delete all compatibility entries for a dataset.

    Args:
        conn: An open project database connection.
        name: The dataset name whose compat entries to delete.
    """
    conn.execute("DELETE FROM dataset_compat WHERE dataset_name = ?", (name,))
    conn.commit()


def delete_dataset_compat(
    conn: sqlite3.Connection,
    name: str,
    problem_version_tag: str,
    *,
    commit: bool = True,
) -> None:
    """Delete a single compatibility entry for a dataset.

    Args:
        conn: An open project database connection.
        name: The dataset name.
        problem_version_tag: Problem version tag to remove from compat.
        commit: If ``True`` (default), commit the transaction immediately.
            Pass ``False`` when the caller manages the transaction.
    """
    conn.execute(
        "DELETE FROM dataset_compat WHERE dataset_name = ? AND problem_version = ?",
        (name, problem_version_tag),
    )
    if commit:
        conn.commit()


def get_solutions_by_dataset(conn: sqlite3.Connection, name: str) -> list[str]:
    """Get solution IDs that reference a dataset (via runs).

    Args:
        conn: An open project database connection.
        name: The dataset name.

    Returns:
        List of solution IDs referencing this dataset.
    """
    cursor = conn.execute(
        """\
        SELECT s.id
        FROM solutions s
        JOIN runs r ON s.run_id = r.id
        WHERE r.dataset = ?
        ORDER BY s.id
        """,
        (name,),
    )
    return [row[0] for row in cursor.fetchall()]


# ── Run CRUD operations ──────────────────────────────────────────────────────


def insert_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    problem_version: str,
    llm: str,
    dataset: str,
    iterations: int,
    problem_hash: str,
    dataset_hash: str,
    llm_model: str,
    created_at: datetime,
    resumed_from: str | None = None,
    status: str = "running",
    generation_time_s: float | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    config_snapshot: str | None = None,
) -> None:
    """Insert a run record into the project database.

    Args:
        conn: An open project database connection.
        run_id: Unique run identifier (e.g. ``"run-20260310-143000"``).
        problem_version: Problem version tag.
        llm: LLM registry name.
        dataset: Dataset name.
        iterations: Number of OpenEvolve iterations.
        problem_hash: Hash of the problem snapshot used.
        dataset_hash: Hash of the dataset at registration.
        llm_model: Full model identifier.
        created_at: Timestamp of run creation.
        resumed_from: Parent run ID if this is a resumed run.
        status: Initial status (default ``"running"``).
        generation_time_s: Wall-clock generation time in seconds.
        prompt_tokens: Total input tokens consumed.
        completion_tokens: Total output tokens consumed.
        config_snapshot: Verbatim OpenEvolve YAML config.
    """
    conn.execute(
        """\
        INSERT INTO runs (
            id, problem_version, llm, dataset, iterations,
            generation_time_s, prompt_tokens, completion_tokens,
            config_snapshot, problem_hash, dataset_hash, llm_model,
            resumed_from, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            problem_version,
            llm,
            dataset,
            iterations,
            generation_time_s,
            prompt_tokens,
            completion_tokens,
            config_snapshot,
            problem_hash,
            dataset_hash,
            llm_model,
            resumed_from,
            status,
            created_at.isoformat(),
        ),
    )
    conn.commit()


def update_run_status(
    conn: sqlite3.Connection,
    run_id: str,
    status: Literal["running", "completed", "interrupted"],
) -> None:
    """Update the status of a run.

    Args:
        conn: An open project database connection.
        run_id: The run ID to update.
        status: New status (``"running"``, ``"completed"``, or ``"interrupted"``).
    """
    conn.execute(
        "UPDATE runs SET status = ? WHERE id = ?",
        (status, run_id),
    )
    conn.commit()


def update_run_tokens(
    conn: sqlite3.Connection,
    run_id: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Update token usage columns for a run.

    Args:
        conn: An open project database connection.
        run_id: The run ID to update.
        prompt_tokens: Total input tokens consumed.
        completion_tokens: Total output tokens consumed.
    """
    conn.execute(
        "UPDATE runs SET prompt_tokens = ?, completion_tokens = ? WHERE id = ?",
        (prompt_tokens, completion_tokens, run_id),
    )
    conn.commit()


def update_run_generation_time(
    conn: sqlite3.Connection,
    run_id: str,
    generation_time_s: float,
    status: Literal["running", "completed", "interrupted"] = "completed",
) -> None:
    """Atomically update generation time and status for a run.

    Combines the ``generation_time_s`` and ``status`` updates in a single
    statement to avoid partial DB state when one succeeds and the other fails.

    Args:
        conn: An open project database connection.
        run_id: The run ID to update.
        generation_time_s: Total wall-clock generation time in seconds.
        status: New status (defaults to ``"completed"``).
    """
    conn.execute(
        "UPDATE runs SET generation_time_s = ?, status = ? WHERE id = ?",
        (generation_time_s, status, run_id),
    )
    conn.commit()


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, object] | None:
    """Retrieve a single run by ID.

    Args:
        conn: An open project database connection.
        run_id: The run ID to look up.

    Returns:
        A dict with run column values, or ``None`` if not found.
    """
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    conn.row_factory = None
    if row is None:
        return None
    return dict(row)


def get_latest_run(conn: sqlite3.Connection) -> dict[str, object] | None:
    """Retrieve the most recent run by creation time.

    Args:
        conn: An open project database connection.

    Returns:
        A dict with run column values, or ``None`` if no runs exist.
    """
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1")
    row = cursor.fetchone()
    conn.row_factory = None
    if row is None:
        return None
    return dict(row)


def list_runs(
    conn: sqlite3.Connection,
    *,
    version: str | None = None,
    llm: str | None = None,
    status: str | None = None,
) -> list[dict[str, object]]:
    """List runs with optional filters.

    Args:
        conn: An open project database connection.
        version: Filter by problem version tag.
        llm: Filter by LLM registry name.
        status: Filter by run status.

    Returns:
        A list of dicts with run column values, ordered by ``created_at DESC``.
    """
    clauses: list[str] = []
    params: list[object] = []

    if version is not None:
        clauses.append("r.problem_version = ?")
        params.append(version)
    if llm is not None:
        clauses.append("r.llm = ?")
        params.append(llm)
    if status is not None:
        clauses.append("r.status = ?")
        params.append(status)

    where = ""
    if clauses:
        # `clauses` contains only hardcoded column-name fragments;
        # values are parameterized via `params`.
        where = "WHERE " + " AND ".join(clauses)

    query = f"""\
        SELECT r.*, MAX(s.best_score) AS best_score,
               (SELECT s2.alias FROM solutions s2
                WHERE s2.run_id = r.id AND s2.rank = 1 LIMIT 1) AS alias
        FROM runs r
        LEFT JOIN solutions s ON s.run_id = r.id
        {where}
        GROUP BY r.id
        ORDER BY r.created_at DESC
    """

    conn.row_factory = sqlite3.Row
    cursor = conn.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.row_factory = None
    return rows


def get_resume_chain(conn: sqlite3.Connection, run_id: str) -> list[str]:
    """Resolve the full resume ancestry of a run using a recursive CTE.

    Walks the ``resumed_from`` chain upward from the given run,
    returning an ordered list of ancestor run IDs (oldest first).

    Args:
        conn: An open project database connection.
        run_id: The run ID whose ancestry to resolve.

    Returns:
        A list of ancestor run IDs ordered from oldest to newest,
        starting with the root ancestor. The given *run_id* itself
        is included as the last element.
    """
    cursor = conn.execute(
        """\
        WITH RECURSIVE chain(id, resumed_from, depth) AS (
            SELECT id, resumed_from, 0 FROM runs WHERE id = ?
            UNION ALL
            SELECT r.id, r.resumed_from, c.depth + 1
            FROM runs r JOIN chain c ON r.id = c.resumed_from
        )
        SELECT id FROM chain ORDER BY depth DESC
        """,
        (run_id,),
    )
    return [row[0] for row in cursor.fetchall()]


# ── Solution CRUD operations ─────────────────────────────────────────────────


def insert_solution(
    conn: sqlite3.Connection,
    *,
    solution_id: str,
    run_id: str,
    rank: int,
    best_score: float | None = None,
    alias: str | None = None,
) -> None:
    """Insert a solution record into the project database.

    Args:
        conn: An open project database connection.
        solution_id: Unique solution identifier.
        run_id: ID of the run that produced this solution.
        rank: Program rank within the run (1 = best).
        best_score: Best score achieved (``None`` if unavailable).
        alias: Optional user-given alias (must be unique across all solutions).

    Raises:
        sqlite3.IntegrityError: If ``UNIQUE(run_id, rank)`` or alias
            uniqueness is violated.
    """
    conn.execute(
        "INSERT INTO solutions (id, run_id, rank, best_score, alias) VALUES (?, ?, ?, ?, ?)",
        (solution_id, run_id, rank, best_score, alias),
    )
    conn.commit()


def get_solution(conn: sqlite3.Connection, id_or_alias: str) -> Solution | None:
    """Retrieve a solution by ID or alias.

    Looks up by ``id`` first; if not found, falls back to ``alias``.

    Args:
        conn: An open project database connection.
        id_or_alias: Solution ID or alias to look up.

    Returns:
        The :class:`Solution` if found, otherwise ``None``.
    """
    cursor = conn.execute(
        "SELECT id, run_id, rank, best_score, alias FROM solutions WHERE id = ?",
        (id_or_alias,),
    )
    row = cursor.fetchone()
    if row is None:
        cursor = conn.execute(
            "SELECT id, run_id, rank, best_score, alias FROM solutions WHERE alias = ?",
            (id_or_alias,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return Solution(
        id=row[0],
        run_id=row[1],
        rank=row[2],
        best_score=row[3],
        alias=row[4],
    )


def get_solutions_for_run(conn: sqlite3.Connection, run_id: str) -> list[Solution]:
    """Retrieve all solutions for a run, ordered by rank.

    Args:
        conn: An open project database connection.
        run_id: The run ID whose solutions to retrieve.

    Returns:
        A list of :class:`Solution` instances sorted by rank.
    """
    cursor = conn.execute(
        "SELECT id, run_id, rank, best_score, alias FROM solutions WHERE run_id = ? ORDER BY rank",
        (run_id,),
    )
    return [
        Solution(
            id=row[0],
            run_id=row[1],
            rank=row[2],
            best_score=row[3],
            alias=row[4],
        )
        for row in cursor.fetchall()
    ]


def list_solutions(
    conn: sqlite3.Connection,
    *,
    version: str | None = None,
    llm: str | None = None,
    rank: int | None = None,
) -> list[dict[str, object]]:
    """List solutions with optional filters via JOIN on runs.

    Args:
        conn: An open project database connection.
        version: Filter by problem version tag (via run).
        llm: Filter by LLM registry name (via run).
        rank: Filter by solution rank.

    Returns:
        A list of dicts with solution and run columns,
        ordered by ``created_at DESC``, then by rank.
    """
    clauses: list[str] = []
    params: list[object] = []

    if version is not None:
        clauses.append("r.problem_version = ?")
        params.append(version)
    if llm is not None:
        clauses.append("r.llm = ?")
        params.append(llm)
    if rank is not None:
        clauses.append("s.rank = ?")
        params.append(rank)

    where = ""
    if clauses:
        # `clauses` contains only hardcoded column-name fragments;
        # values are parameterized via `params`.
        where = "WHERE " + " AND ".join(clauses)

    query = f"""\
        SELECT s.id, s.alias, s.rank, s.best_score,
               r.id AS run_id, r.problem_version, r.llm, r.dataset, r.created_at
        FROM solutions s
        JOIN runs r ON s.run_id = r.id
        {where}
        ORDER BY r.created_at DESC, s.rank
    """

    conn.row_factory = sqlite3.Row
    cursor = conn.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.row_factory = None
    return rows


# ── Eval CRUD operations ──────────────────────────────────────────────────────


def insert_eval_metadata(
    conn: sqlite3.Connection,
    *,
    eval_id: str,
    solution_id: str,
    dataset_name: str,
    instance_count: int,
    instances_solved: int,
    eval_time_s: float | None = None,
    user_aggregates: str | None = None,
    evaluated_at: datetime,
) -> None:
    """Insert an evaluation metadata record into the project database.

    Args:
        conn: An open project database connection.
        eval_id: Unique evaluation identifier.
        solution_id: ID of the evaluated solution.
        dataset_name: Name of the evaluation dataset.
        instance_count: Total number of instances evaluated.
        instances_solved: Number of instances that solved successfully.
        eval_time_s: Total wall-clock evaluation time in seconds.
        user_aggregates: JSON string of user-defined aggregates (legacy mode).
        evaluated_at: Timestamp of evaluation completion.

    Raises:
        sqlite3.IntegrityError: If the ``(solution_id, dataset_name)``
            unique constraint is violated.
    """
    conn.execute(
        """\
        INSERT INTO eval_metadata (
            eval_id, solution_id, dataset_name,
            instance_count, instances_solved, eval_time_s,
            user_aggregates, evaluated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            eval_id,
            solution_id,
            dataset_name,
            instance_count,
            instances_solved,
            eval_time_s,
            user_aggregates,
            evaluated_at.isoformat(),
        ),
    )
    conn.commit()


def insert_eval_instance(
    conn: sqlite3.Connection,
    *,
    eval_id: str,
    instance_id: str,
    metric_name: str,
    value: float | None,
    status: str,
    error_message: str | None = None,
    compute_time_s: float | None = None,
    commit: bool = True,
) -> None:
    """Insert a single eval instance result row.

    Each row represents one (instance, metric) pair. An instance with
    multiple metrics results in multiple rows.

    Args:
        conn: An open project database connection.
        eval_id: Evaluation ID (foreign key to ``eval_metadata``).
        instance_id: Instance identifier (filename or directory name).
        metric_name: Name of the metric.
        value: Metric value (``None`` if failed/timeout).
        status: Instance status (``"solved"``, ``"failed"``, or ``"timeout"``).
        error_message: Error message when ``status != "solved"``.
        compute_time_s: Wall-clock time for this instance in seconds.
        commit: If ``True`` (default), commit the transaction immediately.
            Pass ``False`` when the caller manages the transaction.
    """
    conn.execute(
        """\
        INSERT INTO eval_instances (
            eval_id, instance_id, metric_name, value,
            status, error_message, compute_time_s
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_id, instance_id, metric_name, value, status, error_message, compute_time_s),
    )
    if commit:
        conn.commit()


def get_eval_metadata(
    conn: sqlite3.Connection,
    solution_id: str,
    dataset_name: str | None = None,
) -> EvalMetadata | None:
    """Retrieve evaluation metadata for a (solution, dataset) pair.

    Args:
        conn: An open project database connection.
        solution_id: The solution ID to look up.
        dataset_name: Optional dataset name filter. If ``None``,
            returns the most recent evaluation for the solution.

    Returns:
        The :class:`EvalMetadata` if found, otherwise ``None``.
    """
    conn.row_factory = sqlite3.Row
    try:
        if dataset_name is not None:
            cursor = conn.execute(
                """\
                SELECT eval_id, solution_id, dataset_name,
                       instance_count, instances_solved, eval_time_s,
                       user_aggregates, evaluated_at
                FROM eval_metadata
                WHERE solution_id = ? AND dataset_name = ?
                ORDER BY evaluated_at DESC
                LIMIT 1
                """,
                (solution_id, dataset_name),
            )
        else:
            cursor = conn.execute(
                """\
                SELECT eval_id, solution_id, dataset_name,
                       instance_count, instances_solved, eval_time_s,
                       user_aggregates, evaluated_at
                FROM eval_metadata
                WHERE solution_id = ?
                ORDER BY evaluated_at DESC
                LIMIT 1
                """,
                (solution_id,),
            )
        row = cursor.fetchone()
    finally:
        conn.row_factory = None

    if row is None:
        return None

    user_agg: dict[str, float] | None = None
    if row["user_aggregates"] is not None:
        user_agg = json.loads(row["user_aggregates"])

    return EvalMetadata(
        eval_id=row["eval_id"],
        solution_id=row["solution_id"],
        dataset_name=row["dataset_name"],
        instance_count=row["instance_count"],
        instances_solved=row["instances_solved"],
        eval_time_s=row["eval_time_s"],
        user_aggregates=user_agg,
        evaluated_at=datetime.fromisoformat(row["evaluated_at"]),
    )


def get_eval_instances(
    conn: sqlite3.Connection,
    eval_id: str,
) -> list[InstanceResult]:
    """Retrieve all per-instance results for an evaluation.

    Groups rows by instance_id, collecting all metrics into a single
    :class:`InstanceResult` per instance.

    Args:
        conn: An open project database connection.
        eval_id: The evaluation ID to look up.

    Returns:
        A list of :class:`InstanceResult` sorted by instance_id.
    """
    cursor = conn.execute(
        """\
        SELECT instance_id, metric_name, value, status,
               error_message, compute_time_s
        FROM eval_instances
        WHERE eval_id = ?
        ORDER BY instance_id, metric_name
        """,
        (eval_id,),
    )

    # Group by instance_id
    instances: dict[str, InstanceResult] = {}
    for row in cursor.fetchall():
        iid = row[0]
        metric_name = row[1]
        value = row[2]
        # SQLite CHECK constraint guarantees valid status values
        status = cast(Literal["solved", "failed", "timeout"], row[3])
        error_msg = row[4]
        compute_time = row[5]

        if iid not in instances:
            instances[iid] = InstanceResult(
                instance_id=iid,
                status=status,
                metrics={},
                error=error_msg,
                compute_time_s=compute_time,
            )

        if value is not None:
            instances[iid].metrics[metric_name] = value

    return sorted(instances.values(), key=lambda r: r.instance_id)


def update_eval_metadata(
    conn: sqlite3.Connection,
    *,
    eval_id: str,
    instances_solved: int,
    eval_time_s: float | None = None,
    user_aggregates: str | None = None,
) -> None:
    """Update evaluation metadata after the evaluation loop completes.

    Updates the solved count, total time, and user aggregates fields.

    Args:
        conn: An open project database connection.
        eval_id: The evaluation ID to update.
        instances_solved: Final count of solved instances.
        eval_time_s: Total wall-clock evaluation time in seconds.
        user_aggregates: JSON string of user-defined aggregates (legacy mode).
    """
    conn.execute(
        """\
        UPDATE eval_metadata
        SET instances_solved = ?, eval_time_s = ?, user_aggregates = ?
        WHERE eval_id = ?
        """,
        (instances_solved, eval_time_s, user_aggregates, eval_id),
    )
    conn.commit()


def delete_eval(conn: sqlite3.Connection, eval_id: str) -> None:
    """Delete an evaluation and all its instance results.

    Both DELETEs run inside an explicit transaction so that the
    operation is atomic: either both tables are cleaned or neither is.

    Args:
        conn: An open project database connection.
        eval_id: The evaluation ID to delete.
    """
    with conn:
        conn.execute("DELETE FROM eval_instances WHERE eval_id = ?", (eval_id,))
        conn.execute("DELETE FROM eval_metadata WHERE eval_id = ?", (eval_id,))


# ── Solution extended queries ────────────────────────────────────────────────


def update_solution_alias(
    conn: sqlite3.Connection,
    solution_id: str,
    alias: str,
) -> None:
    """Set or update the alias of an existing solution.

    Args:
        conn: An open project database connection.
        solution_id: The solution ID whose alias to set.
        alias: The new alias (must be unique across all solutions).

    Raises:
        KeyError: If no solution with the given *solution_id* exists.
        DuplicateNameError: If *alias* is already used by another solution.
    """
    try:
        cursor = conn.execute(
            "UPDATE solutions SET alias = ? WHERE id = ?",
            (alias, solution_id),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateNameError(f"Alias already in use: {alias!r}") from exc
    if cursor.rowcount == 0:
        raise KeyError(f"Solution not found: {solution_id}")
    conn.commit()


def get_solution_by_alias(
    conn: sqlite3.Connection,
    alias: str,
) -> Solution | None:
    """Retrieve a solution by its alias.

    Unlike :func:`get_solution`, this performs a direct alias lookup
    without falling back to ID matching.

    Args:
        conn: An open project database connection.
        alias: The alias to look up.

    Returns:
        The :class:`Solution` if found, otherwise ``None``.
    """
    cursor = conn.execute(
        "SELECT id, run_id, rank, best_score, alias FROM solutions WHERE alias = ?",
        (alias,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return Solution(
        id=row[0],
        run_id=row[1],
        rank=row[2],
        best_score=row[3],
        alias=row[4],
    )


def get_solution_detail(
    conn: sqlite3.Connection,
    id_or_alias: str,
) -> dict[str, object] | None:
    """Retrieve full solution lineage via JOIN on runs and eval_metadata.

    Returns solution data enriched with run lineage (problem_version,
    llm, dataset, status, config) and optional evaluation metadata
    (eval_id, instances_solved, instance_count).

    Args:
        conn: An open project database connection.
        id_or_alias: Solution ID or alias to look up.

    Returns:
        A dict with solution, run, and eval columns, or ``None`` if not found.
    """
    query = """\
        SELECT s.id, s.run_id, s.rank, s.best_score, s.alias,
               r.problem_version, r.llm, r.dataset, r.status AS run_status,
               r.config_snapshot, r.llm_model, r.problem_hash, r.dataset_hash,
               r.created_at, r.iterations, r.generation_time_s,
               r.prompt_tokens, r.completion_tokens,
               em.eval_id, em.instances_solved, em.instance_count
        FROM solutions s
        JOIN runs r ON s.run_id = r.id
        LEFT JOIN eval_metadata em ON s.id = em.solution_id
        WHERE {where_clause}
    """
    conn.row_factory = sqlite3.Row
    try:
        # Look up by ID first, then fall back to alias (same pattern as get_solution).
        cursor = conn.execute(query.format(where_clause="s.id = ?"), (id_or_alias,))
        row = cursor.fetchone()
        if row is None:
            cursor = conn.execute(query.format(where_clause="s.alias = ?"), (id_or_alias,))
            row = cursor.fetchone()
    finally:
        conn.row_factory = None
    if row is None:
        return None
    return dict(row)
