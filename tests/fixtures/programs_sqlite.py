"""Fixture factory for a ShinkaEvolve ``programs.sqlite`` database (S14-01).

Builds — in a test-provided directory, typically ``tmp_path`` — a SQLite
file whose schema is byte-compatible with the ``CREATE TABLE programs``
statement of ``shinka-evolve 0.0.7`` (``shinka/database/dbase.py``,
verified in the ``shinka-spike`` env, session 049 — see
``docs/sprints/sprint-014.md`` §"Verified shinka-evolve 0.0.7 schema facts").

Design decision (documented per issue #190): the fixture DB is **built on
demand by this factory** rather than checked in as a binary file. This
keeps the schema reviewable in diffs, avoids opaque binaries in git, and
lets tests customize rows when needed. The default row set
(:data:`FIXTURE_PROGRAM_ROWS`) is shared by all L2-Shinka contract tests,
with expected aggregates exposed as module constants so the tests and the
fixture can never drift apart.

Verified schema facts encoded here:

- The ``programs`` table has **no token or cost columns**. Tokens and
  costs live in the ``metadata`` column (JSON-serialized dict).
- Per-program USD cost is the top-level metadata key ``api_costs``
  (float; total across retry attempts; written for both LLM-generated
  and init programs).
- Per-program token counts are nested under ``metadata.llm_result`` —
  the ``QueryResult.to_dict()`` of the last LLM response
  (``input_tokens``, ``output_tokens``, ``thinking_tokens``, ``cost``,
  ``model_name``, …). The ``llm_result`` key is **absent** for file-based
  init programs (``async_runner.py`` ~L1583 writes only ``api_costs`` +
  ``patch_*`` keys), explicitly ``null`` on the LLM-init-without-response
  path, and the whole ``metadata`` column may be SQL ``NULL`` (Shinka's
  own ``_get_total_api_costs()`` guards against it). Readers must treat
  every field as best-effort with default 0.
- Completion-side totals must be computed as ``output_tokens +
  thinking_tokens``. Provider behavior differs (verified in
  shinka/llm/providers/* 0.0.7): openai/deepseek/local_openai subtract
  reasoning tokens from ``output_tokens``, gemini reports the two counts
  natively disjoint, anthropic reports ``thinking_tokens = 0`` with an
  inclusive ``output_tokens`` — in all cases the sum equals the total
  completion-side token count.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

# ── Schema DDL — byte-copied from shinka-evolve 0.0.7 dbase.py ───────────────

PROGRAMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS programs (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    language TEXT NOT NULL,
    parent_id TEXT,
    archive_inspiration_ids TEXT,  -- JSON serialized List[str]
    top_k_inspiration_ids TEXT,    -- JSON serialized List[str]
    generation INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    code_diff TEXT,     -- Stores edit difference
    combined_score REAL,
    public_metrics TEXT, -- JSON serialized Dict[str, Any]
    private_metrics TEXT, -- JSON serialized Dict[str, Any]
    text_feedback TEXT, -- Text feedback for the program
    complexity REAL,   -- Calculated complexity metric
    embedding TEXT,    -- JSON serialized List[float]
    embedding_pca_2d TEXT, -- JSON serialized List[float]
    embedding_pca_3d TEXT, -- JSON serialized List[float]
    embedding_cluster_id INTEGER,
    correct BOOLEAN DEFAULT 0,  -- Correct (0=False, 1=True)
    children_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT,      -- JSON serialized Dict[str, Any]
    migration_history TEXT, -- JSON of migration events
    island_idx INTEGER,  -- Add island_idx to the schema
    system_prompt_id TEXT  -- ID of system prompt that generated this program
)
"""

_COMPANION_TABLES_SQL = (
    """
    CREATE TABLE IF NOT EXISTS archive (
        program_id TEXT PRIMARY KEY,
        FOREIGN KEY (program_id) REFERENCES programs(id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metadata_store (
        key TEXT PRIMARY KEY, value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generation_event_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        generation INTEGER NOT NULL,
        status TEXT NOT NULL,
        source_job_id TEXT,
        details TEXT,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attempt_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        generation INTEGER NOT NULL,
        stage TEXT NOT NULL,
        status TEXT NOT NULL,
        details TEXT,
        created_at REAL NOT NULL
    )
    """,
)

#: Backend output sub-directory convention (S14): ``<run_dir>/shinka-output``.
#: Exported for reuse by the PR-C engine-tier tests.
SHINKA_OUTPUT_SUBDIR = "shinka-output"

# ── Default fixture rows ──────────────────────────────────────────────────────

_BASE_TIMESTAMP = 1718000000.0

_PROGRAM_CODE = "def solve(data):\n    return sum(data)\n"


def _llm_result(
    input_tokens: int,
    output_tokens: int,
    thinking_tokens: int,
    cost: float,
) -> dict[str, Any]:
    """Build a realistic ``QueryResult.to_dict()`` payload (shinka 0.0.7)."""
    return {
        "content": "<diff>...</diff>",
        "msg": "Improve the solver",
        "system_msg": "You are an expert programmer.",
        "new_msg_history": [],
        "model_name": "local/test-model",
        "kwargs": {"temperature": 0.8},
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "cost": cost,
        "input_cost": cost / 2,
        "output_cost": cost / 2,
        "thought": "",
        "model_posteriors": None,
        "num_tool_calls": 0,
        "num_total_queries": 1,
    }


#: Six program rows: a file-based init program (**no** ``llm_result`` key —
#: the shape every real Revolver Shinka run produces for generation 0),
#: two generation-1 children (one invalid), the generation-2 best program,
#: a generation-2 failed program with a NULL ``combined_score``, and a row
#: whose ``metadata`` column is SQL ``NULL``.
FIXTURE_PROGRAM_ROWS: tuple[dict[str, Any], ...] = (
    {
        "id": "prog-init",
        "code": _PROGRAM_CODE,
        "language": "python",
        "parent_id": None,
        "generation": 0,
        "timestamp": _BASE_TIMESTAMP,
        "combined_score": 0.40,
        "public_metrics": {"combined_score": 0.40},
        "private_metrics": {},
        "correct": 1,
        "island_idx": 0,
        # File-based init program (async_runner.py ~L1583): api_costs +
        # patch_* keys only — NO llm_result key at all.
        "metadata": {
            "api_costs": 0.0,
            "patch_type": "init",
            "patch_name": "initial_program",
            "patch_description": "Initial program setup",
        },
    },
    {
        "id": "prog-gen1-a",
        "code": _PROGRAM_CODE,
        "language": "python",
        "parent_id": "prog-init",
        "generation": 1,
        "timestamp": _BASE_TIMESTAMP + 60.0,
        "combined_score": 0.55,
        "public_metrics": {"combined_score": 0.55},
        "private_metrics": {"runtime_s": 0.2},
        "correct": 1,
        "island_idx": 0,
        "metadata": {
            "api_costs": 0.012,
            "llm_result": _llm_result(1200, 340, 0, 0.011),
        },
    },
    {
        "id": "prog-gen1-b",
        "code": _PROGRAM_CODE,
        "language": "python",
        "parent_id": "prog-init",
        "generation": 1,
        "timestamp": _BASE_TIMESTAMP + 65.0,
        "combined_score": 0.10,
        "public_metrics": {"combined_score": 0.10},
        "private_metrics": {},
        "correct": 0,
        "island_idx": 1,
        "metadata": {
            "api_costs": 0.008,
            "llm_result": _llm_result(900, 210, 64, 0.007),
        },
    },
    {
        "id": "prog-gen2-best",
        "code": _PROGRAM_CODE,
        "language": "python",
        "parent_id": "prog-gen1-a",
        "generation": 2,
        "timestamp": _BASE_TIMESTAMP + 120.0,
        "combined_score": 0.91,
        "public_metrics": {"combined_score": 0.91},
        "private_metrics": {"runtime_s": 0.1},
        "correct": 1,
        "island_idx": 0,
        "metadata": {
            "api_costs": 0.021,
            "llm_result": _llm_result(1500, 480, 128, 0.019),
        },
    },
    {
        "id": "prog-gen2-broken",
        "code": _PROGRAM_CODE,
        "language": "python",
        "parent_id": "prog-gen1-a",
        "generation": 2,
        "timestamp": _BASE_TIMESTAMP + 125.0,
        "combined_score": None,
        "public_metrics": {},
        "private_metrics": {},
        "correct": 0,
        "island_idx": 1,
        "metadata": {
            "api_costs": 0.005,
            "llm_result": _llm_result(700, 0, 0, 0.004),
        },
    },
    {
        "id": "prog-gen2-meta-null",
        "code": _PROGRAM_CODE,
        "language": "python",
        "parent_id": "prog-gen1-b",
        "generation": 2,
        "timestamp": _BASE_TIMESTAMP + 130.0,
        "combined_score": None,
        "public_metrics": {},
        "private_metrics": {},
        "correct": 0,
        "island_idx": 1,
        # Defensive case: the metadata column itself can be SQL NULL —
        # Shinka's own _get_total_api_costs() guards against it.
        "metadata": None,
    },
)

# ── Expected aggregates over FIXTURE_PROGRAM_ROWS (contract constants) ────────

#: Sum of top-level ``metadata.api_costs`` across all rows (USD, canonical).
EXPECTED_COST_USD = 0.0 + 0.012 + 0.008 + 0.021 + 0.005

#: Sum of ``metadata.llm_result.input_tokens`` (rows without an
#: ``llm_result`` key or with a NULL ``metadata`` column count 0).
EXPECTED_PROMPT_TOKENS = 1200 + 900 + 1500 + 700

#: Sum of ``output_tokens + thinking_tokens`` (the sum equals the total
#: completion-side token count across all shinka 0.0.7 providers — see
#: the module docstring for the per-provider invariant).
EXPECTED_COMPLETION_TOKENS = (340 + 0) + (210 + 64) + (480 + 128) + (0 + 0)

#: Number of rows with ``correct = 1``.
EXPECTED_VALID_COUNT = 3

#: Number of evolved children — rows carrying a ``metadata.llm_result`` dict
#: (the file-based init seed and the NULL-metadata row are excluded). Used by
#: the unproductive-run check (#302): ``count_evolved_children``.
EXPECTED_CHILDREN_COUNT = 4

#: ``(last_generation, best_combined_score)`` for read_progress().
EXPECTED_LAST_GENERATION = 2
EXPECTED_BEST_SCORE = 0.91

#: Program ids with a non-NULL ``combined_score``, ranked descending.
EXPECTED_RANKED_IDS = ("prog-gen2-best", "prog-gen1-a", "prog-init", "prog-gen1-b")


# ── Factory ───────────────────────────────────────────────────────────────────


def build_programs_db(
    db_path: Path,
    rows: tuple[dict[str, Any], ...] = FIXTURE_PROGRAM_ROWS,
) -> Path:
    """Create a fixture ``programs.sqlite`` at *db_path* and return it.

    The schema replicates shinka-evolve 0.0.7 (``programs`` plus the
    companion ``archive`` / ``metadata_store`` / ``generation_event_log``
    / ``attempt_log`` tables). ``metadata_store.last_iteration`` is set
    to the max generation, mirroring Shinka's own bookkeeping.

    Args:
        db_path: Target SQLite file path (parent dirs created).
        rows: Program rows to insert (defaults to the shared fixture set).

    Returns:
        *db_path*, for chaining.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(PROGRAMS_TABLE_SQL)
        for ddl in _COMPANION_TABLES_SQL:
            conn.execute(ddl)
        for row in rows:
            conn.execute(
                """
                INSERT INTO programs (
                    id, code, language, parent_id,
                    archive_inspiration_ids, top_k_inspiration_ids,
                    generation, timestamp, code_diff, combined_score,
                    public_metrics, private_metrics, text_feedback,
                    complexity, embedding, embedding_pca_2d,
                    embedding_pca_3d, embedding_cluster_id, correct,
                    children_count, metadata, migration_history,
                    island_idx, system_prompt_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["code"],
                    row["language"],
                    row["parent_id"],
                    json.dumps([]),
                    json.dumps([]),
                    row["generation"],
                    row["timestamp"],
                    None,
                    row["combined_score"],
                    json.dumps(row["public_metrics"]),
                    json.dumps(row["private_metrics"]),
                    "",
                    None,
                    None,
                    None,
                    None,
                    None,
                    row["correct"],
                    0,
                    json.dumps(row["metadata"]) if row["metadata"] is not None else None,
                    None,
                    row["island_idx"],
                    None,
                ),
            )
        last_iteration = max(row["generation"] for row in rows) if rows else 0
        conn.execute(
            "INSERT OR REPLACE INTO metadata_store (key, value) VALUES (?, ?)",
            ("last_iteration", str(last_iteration)),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def build_shinka_run_dir(
    run_dir: Path,
    rows: tuple[dict[str, Any], ...] = FIXTURE_PROGRAM_ROWS,
) -> Path:
    """Create a Shinka-shaped run directory with a fixture programs DB.

    Layout matches the S14 backend convention:
    ``<run_dir>/shinka-output/programs.sqlite``.

    Args:
        run_dir: Run directory root (created if missing).
        rows: Program rows for the fixture DB.

    Returns:
        *run_dir*, for chaining.
    """
    build_programs_db(run_dir / SHINKA_OUTPUT_SUBDIR / "programs.sqlite", rows=rows)
    return run_dir
