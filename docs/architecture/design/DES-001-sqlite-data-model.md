# DES-001 — SQLite Data Model

**Version**: 0.6 — runs.backend column + planned migration v9 (ADR-007)
**Date**: 2026-03-25
**Status**: Draft
**Traceable to**: [Architecture Overview](../architecture.md) §5, [Specifications](../../specs/specifications.md) NFR-013/016

---

## 1. Overview

Revolver uses two SQLite databases:

| Database | Location | Scope | Contents |
|---|---|---|---|
| **Project DB** | `.revolver/revolver.db` | Per-project | Problem versions, datasets, runs, solutions, evaluations, benchmarks |
| **Global DB** | `~/.revolver/revolver.db` | Per-user | LLM registry |

Both databases use **WAL mode** (NFR-016) for concurrent read access.

### What goes in SQLite vs files

| SQLite | Files (YAML/code) |
|---|---|
| Structured metadata, metrics, lineage | Source code artifacts (programs, evaluators) |
| Queryable data (filter, sort, aggregate) | OpenEvolve checkpoints |
| Per-instance evaluation results | Config snapshots (human-readable) |
| Relationships and foreign keys | Directory-based manifests |

---

## 2. Entity-Relationship Diagram

```
                        ┌──────────────────┐
                        │ problem_versions │
                        │ (PK: tag)        │
                        └────────▲─────────┘
                                 │ 1
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
                    │ N          │ N          │ N
           ┌───────┴──────┐  ┌──┴───────┐  ┌┴───────────┐
           │dataset_compat│  │   runs   │  │            │
           └───────┬──────┘  └──┬───┬───┘  │            │
                   │ N          │   │       │            │
                   │         1  │   │self   │            │
            ┌──────▼──────┐    │   │(resume)│            │
            │  datasets   │◄───┘   │       │            │
            │ (PK: name)  │        │       │            │
            └──┬──────┬───┘     N  │       │            │
               │      │     ┌─────┘       │            │
            1  │      │  1  │              │            │
               │      │     │              │            │
    ┌──────────▼┐  ┌──▼──┐ ┌▼───────────┐ │            │
    │ dataset_  │  │eval_│ │ solutions  │ │            │
    │ instances │  │meta │ │(PK: id)    │ │            │
    └───────────┘  │data │ └──┬─────────┘ │            │
                   └──┬──┘    │            │            │
                      │    1  │            │            │
                   1  │       │            │            │
                      │  ┌────▼──────────┐ │            │
               ┌──────▼┐ │benchmark_    │ │            │
               │eval_  │ │solutions     │ │            │
               │inst.  │ └────┬─────────┘ │            │
               └───────┘      │            │            │
                           N  │            │            │
                              │            │            │
                     ┌────────▼──────┐     │            │
                     │  benchmarks   │     │            │
                     │ (PK: id)      │     │            │
                     └───────────────┘     │            │
                                           │            │
                              ~/.revolver/ │            │
                              ┌────────────┘            │
                              │  ┌───────────────┐      │
                              └──│     llms      │◄──┐  │
                                 │ (PK: name)    │   │  │
                                 └───────────────┘   │  │
                                                     │  │
                                 ┌───────────────┐   │  │
                                 │  ensembles    │   │  │
                                 │ (PK: name)    │   │  │
                                 └──────┬────────┘   │  │
                                        │ 1          │  │
                                        │            │  │
                                 ┌──────▼────────┐   │  │
                                 │  ensemble_    │   │  │
                                 │  members      ├───┘  │
                                 │ (ensemble,llm)│      │
                                 └───────────────┘      │
```

---

## 3. Schema Definition (Project DB)

### 3.1 `problem_versions`

Immutable snapshots of problem definitions. Files stored in `.revolver/problem/<tag>/`.

```sql
CREATE TABLE problem_versions (
    tag             TEXT PRIMARY KEY,       -- "v1.0", "v1.1"
    hash            TEXT NOT NULL UNIQUE,   -- SHA-256 of snapshot contents
    message         TEXT DEFAULT '',        -- user description
    created_at      TEXT NOT NULL           -- ISO 8601
);
```

**Constraints**: Fully immutable. No UPDATE or DELETE.

### 3.2 `datasets`

Dataset registrations. Manifests stored in `.revolver/datasets/<name>/manifest.yaml`.

```sql
CREATE TABLE datasets (
    name            TEXT PRIMARY KEY,       -- "train-small", "eval-benchmark"
    path            TEXT NOT NULL,          -- absolute path to dataset directory
    split           TEXT NOT NULL CHECK (split IN ('train', 'eval')),
    storage         TEXT NOT NULL DEFAULT 'reference' CHECK (storage IN ('reference', 'snapshot')),
    description     TEXT DEFAULT '',
    global_hash     TEXT NOT NULL,          -- SHA-256 of sorted instance hashes
    instance_count  INTEGER NOT NULL,
    registered_at   TEXT NOT NULL           -- ISO 8601
);
```

**Constraints**: Core metadata immutable. Description updateable.

### 3.3 `dataset_instances`

Per-instance hashes for integrity verification at usage time.

```sql
CREATE TABLE dataset_instances (
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    instance_id     TEXT NOT NULL,          -- filename or directory name
    hash            TEXT NOT NULL,          -- SHA-256 of instance
    PRIMARY KEY (dataset_name, instance_id)
);
```

### 3.4 `dataset_compat`

Which problem versions each dataset is compatible with. Mutable (add/remove).

```sql
CREATE TABLE dataset_compat (
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    problem_version TEXT NOT NULL REFERENCES problem_versions(tag),
    PRIMARY KEY (dataset_name, problem_version)
);
```

### 3.5 `runs`

Run metadata created by `revolver run`. A run is the physical unit of an evolution session on the selected backend (ADR-007): it owns the resume state, config, wrapper evaluator, and stored programs. A single solution (rank-1) is auto-created on completion; additional solutions can be extracted on demand via `revolver solution extract`. Full provenance for traceability (NFR-020). The `backend` column (migration v9, planned for S13) records which evolution backend produced the run; solutions derive their backend via the `run_id` join.

```sql
CREATE TABLE runs (
    id                TEXT PRIMARY KEY,       -- "run-YYYYMMDD-HHMMSS"
    problem_version   TEXT NOT NULL REFERENCES problem_versions(tag),
    llm               TEXT NOT NULL,          -- LLM name from registry
    dataset           TEXT NOT NULL REFERENCES datasets(name),
    iterations        INTEGER NOT NULL,
    generation_time_s REAL,
    prompt_tokens     INTEGER,               -- total input tokens consumed (NULL if unavailable)
    completion_tokens INTEGER,               -- total output tokens consumed (NULL if unavailable)
    config_snapshot   TEXT,                   -- verbatim backend config used for the run (NFR-023, ADR-007)
    problem_hash      TEXT NOT NULL,          -- hash of problem snapshot used
    dataset_hash      TEXT NOT NULL,          -- hash of dataset at registration
    llm_model         TEXT NOT NULL,          -- full model ID (e.g., "claude-opus-4-6")
    resumed_from      TEXT REFERENCES runs(id), -- NULL if fresh run, parent run_id if resumed
    status            TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'completed', 'interrupted',
                             'failed', 'completed_with_errors')),
    llm_type          TEXT NOT NULL DEFAULT 'single', -- 'single' or 'ensemble'
    llm_snapshot      TEXT,                   -- JSON snapshot of LLM/ensemble config for traceability
    backend           TEXT NOT NULL DEFAULT 'openevolve', -- evolution backend (ADR-007, migration v9 — S13)
    created_at        TEXT NOT NULL           -- ISO 8601
);

CREATE INDEX idx_runs_version ON runs(problem_version);
CREATE INDEX idx_runs_created ON runs(created_at DESC);
CREATE INDEX idx_runs_resumed ON runs(resumed_from);
```

**Constraints**: Fully immutable once completed. A completed run never changes — its programs, lineage, and files are frozen. `resumed_from` links to the parent run whose checkpoint was used to seed this run (resume = new run, not mutation of the old one).

**Status values**: `running` (in progress), `completed` (success), `interrupted` (OE failure or user cancellation), `failed` (run failed before completing any iterations), `completed_with_errors` (OE completed but post-processing failed — e.g., program collection, solution creation, or training eval). The `completed_with_errors` status was added in schema version 2; `failed` was added in schema version 7 (see §5).

### 3.6 `solutions`

Lightweight logical entity referencing a program within a run. A solution is a pointer `(run_id, rank)` with an optional alias. It has no directory of its own — the program file is resolved via `.revolver/runs/<run_id>/programs/rank-<N>.py`.

```sql
CREATE TABLE solutions (
    id         TEXT PRIMARY KEY,       -- "sol-YYYYMMDD-HHMMSS"
    run_id     TEXT NOT NULL REFERENCES runs(id),
    rank       INTEGER NOT NULL,       -- 1 = best
    best_score REAL,
    alias      TEXT UNIQUE,
    UNIQUE(run_id, rank)
);

CREATE INDEX idx_solutions_run ON solutions(run_id);
```

**Constraints**: ID, run_id, rank immutable. Alias updateable. `UNIQUE(run_id, rank)` ensures each rank appears only once per run.

### 3.7 `eval_metadata`

Evaluation session metadata. Aggregate statistics (mean, min, max, p10, p50, p90, std) are **not stored** — they are computed at read time from raw `eval_instances` data in Python ([DES-006 §4](DES-006-eval-loop.md)).

```sql
CREATE TABLE eval_metadata (
    eval_id          TEXT PRIMARY KEY,       -- "eval-YYYYMMDD-HHMMSS"
    solution_id      TEXT NOT NULL REFERENCES solutions(id),
    dataset_name     TEXT NOT NULL REFERENCES datasets(name),
    instance_count   INTEGER NOT NULL,
    instances_solved INTEGER NOT NULL,
    eval_time_s      REAL,                   -- total wall-clock time
    user_aggregates  TEXT,                   -- JSON: {"combined_score": 0.72, "makespan": 155.3}
                                             -- NULL if evaluate_instance() mode (no custom aggregator)
                                             -- Populated by global evaluate() call for legacy evaluators (D-006-g)
    evaluated_at     TEXT NOT NULL            -- ISO 8601
);

CREATE UNIQUE INDEX idx_eval_unique ON eval_metadata(solution_id, dataset_name);
```

**Note**: `idx_eval_unique` ensures at most one evaluation per (solution, dataset). Re-evaluation replaces the previous result (DELETE old + INSERT new in a transaction). `user_aggregates` stores the raw result of a global `evaluate()` call (legacy mode only) — see [DES-006](DES-006-eval-loop.md) D-006-g.

### 3.8 `eval_instances`

Raw per-instance results. Stored for post-processing (histograms, plots, per-instance comparison).

```sql
CREATE TABLE eval_instances (
    eval_id         TEXT NOT NULL REFERENCES eval_metadata(eval_id),
    instance_id     TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    value           REAL,                   -- NULL if failed/timeout
    status          TEXT NOT NULL CHECK (status IN ('solved', 'failed', 'timeout')),
    error_message   TEXT,                   -- if status != 'solved'
    compute_time_s  REAL,                   -- wall-clock time for this instance
    PRIMARY KEY (eval_id, instance_id, metric_name)
);

CREATE INDEX idx_eval_inst_eval ON eval_instances(eval_id);
```

### 3.9 `benchmarks`

Benchmark metadata (multi-solution comparison).

```sql
CREATE TABLE benchmarks (
    id              TEXT PRIMARY KEY,       -- "bench-YYYYMMDD-HHMMSS"
    alias           TEXT,
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    created_at      TEXT NOT NULL           -- ISO 8601
);

CREATE INDEX idx_benchmarks_created ON benchmarks(created_at DESC);
```

### 3.10 `benchmark_solutions`

Which solutions are part of each benchmark.

```sql
CREATE TABLE benchmark_solutions (
    benchmark_id    TEXT NOT NULL REFERENCES benchmarks(id),
    solution_id     TEXT NOT NULL REFERENCES solutions(id),
    PRIMARY KEY (benchmark_id, solution_id)
);
```

---

## 4. Schema Definition (Global DB)

### 4.1 `llms`

LLM registry, shared across all projects.

```sql
CREATE TABLE llms (
    name            TEXT PRIMARY KEY,       -- "claude-opus", "codestral-local"
    provider        TEXT,                   -- "anthropic", "openai", "google", "openai-compat"
    model           TEXT NOT NULL,          -- model ID
    source          TEXT NOT NULL CHECK (source IN ('local', 'remote')),
    base_url        TEXT,                   -- e.g., "http://localhost:11434/v1"
    api_key_env     TEXT,                   -- env var name (e.g., "ANTHROPIC_API_KEY")
    input_cost_per_mtok  REAL,             -- USD per million input tokens (NULL = no pricing)
    output_cost_per_mtok REAL,             -- USD per million output tokens (NULL = no pricing)
    temperature     REAL,                   -- default sampling temperature (NULL = use provider default)
    registered_at   TEXT NOT NULL           -- ISO 8601
);
```

### 4.2 `ensembles`

Named LLM ensembles for multi-model evolution runs. Shared across all projects (global DB).

```sql
CREATE TABLE ensembles (
    name            TEXT PRIMARY KEY,       -- "multi-model-v1"
    created_at      TEXT NOT NULL           -- ISO 8601
);
```

### 4.3 `ensemble_members`

Members of an ensemble, each referencing a registered LLM with a sampling weight.

```sql
CREATE TABLE ensemble_members (
    ensemble_name   TEXT NOT NULL REFERENCES ensembles(name) ON DELETE CASCADE,
    llm_name        TEXT NOT NULL REFERENCES llms(name),
    weight          REAL NOT NULL,          -- sampling weight (0.0–1.0)
    temperature     REAL,                   -- per-member temperature override (optional)
    max_tokens      INTEGER,               -- per-member max tokens override (optional)
    UNIQUE(ensemble_name, llm_name)
);
```

**Constraints**: `ON DELETE CASCADE` ensures removing an ensemble deletes all its members. The `UNIQUE(ensemble_name, llm_name)` constraint prevents duplicate members.

---

## 5. Initialization SQL

```sql
-- Project DB initialization
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Schema version for future migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_version (version, applied_at)
VALUES (1, datetime('now'));
```

The `schema_version` table enables future schema migrations. On startup, Revolver checks the current version and applies any pending migrations sequentially.

### 5.1 Migration: v1 → v2 (Sprint 005a)

Schema version 2 adds `completed_with_errors` to the `runs.status` CHECK constraint. Because SQLite does not support `ALTER TABLE ... ALTER COLUMN`, the migration recreates the `runs` table with the updated constraint:

```sql
-- Migration v2: Add 'completed_with_errors' to runs.status CHECK constraint.
-- SQLite cannot ALTER a CHECK constraint, so we recreate the table.
ALTER TABLE runs RENAME TO _runs_old;
CREATE TABLE runs (
    -- same columns as v1, with updated CHECK:
    status TEXT NOT NULL DEFAULT 'running'
           CHECK (status IN ('running', 'completed', 'interrupted', 'completed_with_errors')),
    -- ... (all other columns unchanged)
);
INSERT INTO runs SELECT * FROM _runs_old;
DROP TABLE _runs_old;
-- Recreate indexes
UPDATE schema_version SET version = 2, applied_at = datetime('now');
```

### 5.2 Migration: v2 → v3 (Sprint 006c)

Schema version 3 adds the `cascade_evaluation` column to the `runs` table:

```sql
ALTER TABLE runs ADD COLUMN cascade_evaluation INTEGER;
UPDATE schema_version SET version = 3, applied_at = datetime('now');
```

### 5.3 Migration: v3 → v4 (Sprint 006c)

Schema version 4 adds `max_tokens` and `timeout_s` columns to the `llms` table:

```sql
ALTER TABLE llms ADD COLUMN max_tokens INTEGER;
ALTER TABLE llms ADD COLUMN timeout_s INTEGER;
UPDATE schema_version SET version = 4, applied_at = datetime('now');
```

Each `ALTER TABLE` is executed individually with error suppression (SQLite does not support `ADD COLUMN IF NOT EXISTS`).

### 5.4 Migration: v4 → v5 (Sprint 008)

Schema version 5 recreates all tables that have foreign key constraints, adding `ON DELETE CASCADE` to every FK. SQLite does not support `ALTER CONSTRAINT`, so each table is recreated with the updated FK definitions. Affected tables: `solutions`, `eval_metadata`, `eval_instances`, `benchmark_solutions`, `dataset_instances`, `dataset_compat`.

FK enforcement is temporarily disabled (`PRAGMA foreign_keys=OFF`) during the migration.

### 5.5 Migration: v5 → v6 (Sprint 009)

Schema version 6 adds the `temperature` column to the `llms` table:

```sql
ALTER TABLE llms ADD COLUMN temperature REAL;
UPDATE schema_version SET version = 6, applied_at = datetime('now');
```

### 5.6 Migration: v6 → v7 (Sprint 009)

Schema version 7 adds `'failed'` to the `runs.status` CHECK constraint. Because SQLite does not support `ALTER CHECK`, the `runs` table is recreated with the updated constraint:

```sql
-- Migration v7: Add 'failed' to runs.status CHECK constraint.
ALTER TABLE runs RENAME TO _runs_old;
CREATE TABLE runs (
    -- same columns as v6, with updated CHECK:
    status TEXT NOT NULL DEFAULT 'running'
           CHECK (status IN ('running', 'completed', 'interrupted',
                  'failed', 'completed_with_errors')),
    -- ... (all other columns unchanged)
);
INSERT INTO runs SELECT * FROM _runs_old;
DROP TABLE _runs_old;
-- Recreate indexes
UPDATE schema_version SET version = 7, applied_at = datetime('now');
```

### 5.7 Migration: v7 → v8 (Sprint 011)

Schema version 8 adds ensemble support (global DB) and run-level LLM traceability columns (project DB).

**Global DB**: Creates `ensembles` and `ensemble_members` tables (idempotent via `IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS ensembles (
    name            TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ensemble_members (
    ensemble_name   TEXT NOT NULL REFERENCES ensembles(name) ON DELETE CASCADE,
    llm_name        TEXT NOT NULL REFERENCES llms(name),
    weight          REAL NOT NULL,
    temperature     REAL,
    max_tokens      INTEGER,
    UNIQUE(ensemble_name, llm_name)
);
```

**Project DB**: Adds `llm_type` and `llm_snapshot` columns to the `runs` table:

```sql
ALTER TABLE runs ADD COLUMN llm_type TEXT NOT NULL DEFAULT 'single';
ALTER TABLE runs ADD COLUMN llm_snapshot TEXT;
UPDATE schema_version SET version = 8, applied_at = datetime('now');
```

Each `ALTER TABLE` is executed individually with error suppression (SQLite does not support `ADD COLUMN IF NOT EXISTS`).

### 5.8 Migration: v8 → v9 (Sprint 013 — planned)

Schema version 9 adds the `backend` column to the `runs` table (project DB) for evolution-backend
traceability (ADR-007, FR-RUN-047):

```sql
ALTER TABLE runs ADD COLUMN backend TEXT NOT NULL DEFAULT 'openevolve';
UPDATE schema_version SET version = 9, applied_at = datetime('now');
```

All pre-v9 runs are OpenEvolve runs, so the default backfills them correctly.

---

## 6. Key Queries

### 6.1 Solution detail (`revolver solution info`)

```sql
SELECT s.id, s.alias, s.rank, s.best_score,
       r.id AS run_id, r.problem_version, r.llm, r.dataset,
       r.llm_model, r.iterations, r.generation_time_s,
       r.config_snapshot, r.resumed_from, r.created_at
FROM solutions s
JOIN runs r ON s.run_id = r.id
WHERE s.id = :id_or_alias OR s.alias = :id_or_alias;
```

### 6.2 Solution list with filters (`revolver solution list`)

```sql
SELECT s.id, s.alias, s.rank, s.best_score,
       r.id AS run_id, r.problem_version, r.llm, r.dataset, r.created_at
FROM solutions s
JOIN runs r ON s.run_id = r.id
WHERE (:version IS NULL OR r.problem_version = :version)
  AND (:llm IS NULL OR r.llm = :llm)
  AND (:rank IS NULL OR s.rank = :rank)
ORDER BY r.created_at DESC, s.rank;
```

### 6.3 Run list (`revolver run list`)

```sql
SELECT r.id, r.problem_version, r.llm, r.dataset,
       r.iterations, r.generation_time_s, r.status, r.resumed_from,
       r.prompt_tokens, r.completion_tokens,
       r.created_at,
       MAX(s.best_score) AS best_score
FROM runs r
LEFT JOIN solutions s ON s.run_id = r.id
GROUP BY r.id
ORDER BY r.created_at DESC;
```

### 6.4 Solutions from same run

```sql
SELECT s.id, s.alias, s.rank, s.best_score
FROM solutions s
WHERE s.run_id = :run_id
ORDER BY s.rank;
```

### 6.5 Resume chain (run lineage)

```sql
-- Recursive: all ancestors of a run
WITH RECURSIVE chain(id, resumed_from, depth) AS (
    SELECT id, resumed_from, 0 FROM runs WHERE id = :run_id
    UNION ALL
    SELECT r.id, r.resumed_from, c.depth + 1
    FROM runs r JOIN chain c ON r.id = c.resumed_from
)
SELECT * FROM chain ORDER BY depth;
```

### 6.6 Benchmark: raw per-instance data (`revolver benchmark results`)

Benchmark comparison loads raw per-instance data from `eval_instances` and computes aggregates in Python (see [DES-006 §4](DES-006-eval-loop.md)).

```sql
SELECT ei.instance_id, s.id AS solution_id, s.alias,
       ei.metric_name, ei.value, ei.status, ei.compute_time_s,
       r.generation_time_s
FROM benchmark_solutions bs
JOIN solutions s ON bs.solution_id = s.id
JOIN runs r ON s.run_id = r.id
JOIN eval_metadata em ON s.id = em.solution_id AND em.dataset_name = :dataset
JOIN eval_instances ei ON em.eval_id = ei.eval_id
WHERE bs.benchmark_id = :bench_id
  AND (:metric IS NULL OR ei.metric_name = :metric)
ORDER BY ei.instance_id, ei.metric_name, s.id;
```

Aggregates (mean, min, max, p10, p50, p90, std) are computed per (solution, metric) in Python from this result set.

### 6.7 Per-instance comparison (`revolver benchmark results --per-instance`)

```sql
SELECT ei.instance_id, s.alias, ei.metric_name, ei.value, ei.compute_time_s
FROM benchmark_solutions bs
JOIN solutions s ON bs.solution_id = s.id
JOIN eval_metadata em ON s.id = em.solution_id AND em.dataset_name = :dataset
JOIN eval_instances ei ON em.eval_id = ei.eval_id
WHERE bs.benchmark_id = :bench_id
ORDER BY ei.instance_id, ei.metric_name, ei.value DESC;
```

### 6.8 Check existing eval results (benchmark reuse)

```sql
SELECT eval_id FROM eval_metadata
WHERE solution_id = :solution_id AND dataset_name = :dataset_name
LIMIT 1;
```

### 6.9 Dataset integrity verification

```sql
SELECT instance_id, hash
FROM dataset_instances
WHERE dataset_name = :dataset_name
ORDER BY instance_id;
```

---

## 7. ID Generation

| Entity | Pattern | Example | Collision handling |
|---|---|---|---|
| Problem version | User-provided tag | `v1.0` | UNIQUE constraint, reject on duplicate |
| Dataset | User-provided name | `train-small` | UNIQUE constraint, reject on duplicate |
| Run | `run-{YYYYMMDD}-{HHMMSS}` | `run-20260310-143000` | Append counter if needed: `run-20260310-143000-1` |
| Solution | `sol-{YYYYMMDD}-{HHMMSS}` | `sol-20260310-143000` | Same counter strategy |
| Evaluation | `eval-{YYYYMMDD}-{HHMMSS}` | `eval-20260310-160000` | Same counter strategy |
| Benchmark | `bench-{YYYYMMDD}-{HHMMSS}` | `bench-20260310-170000` | Same counter strategy |

---

## 8. Migration Strategy

Schema migrations use a sequential version number:

1. On DB open, read `schema_version.version`
2. Compare with the expected version in code
3. Apply each migration in order (SQL scripts embedded in Python)
4. Update `schema_version`

Migrations are **forward-only** (no rollback). Each migration is a Python function that executes SQL within a transaction.

```python
MIGRATIONS = {
    1: "initial_schema.sql",    # V1 tables
    2: "add_completed_with_errors_status.sql",  # Add 'completed_with_errors' to runs.status CHECK
    3: "add_cascade_evaluation.sql",            # Add cascade_evaluation to runs (Sprint 006c)
    4: "add_llm_max_tokens_timeout.sql",        # Add max_tokens, timeout_s to llms (Sprint 006c)
    5: "add_fk_on_delete_cascade.sql",          # Recreate FK tables with ON DELETE CASCADE (Sprint 008)
    6: "add_llm_temperature.sql",               # Add temperature to llms (Sprint 009)
    7: "add_failed_run_status.sql",             # Add 'failed' to runs.status CHECK (Sprint 009)
    8: "add_ensemble_tables_and_llm_snapshot.sql",  # Ensemble tables (global) + llm_type/llm_snapshot (project) (Sprint 011)
}
```

---

## 9. Design Decisions

### Why `runs` as a first-class entity (not just a `run_id` in `solution_lineage`)?

The initial design stored lineage data in `solution_lineage` with a `run_id` column linking solutions. This had several problems:
- **Resume mutated the solution**: `run resume` updated the existing solution in-place, breaking traceability if eval results referenced the old program.
- **Lineage duplication**: every solution duplicated `iterations`, `config_snapshot`, `generation_time_s`, etc.
- **No run lifecycle**: no way to track run status (`running`/`completed`/`interrupted`).

With `runs` as a table, the run is the **physical** entity (owns files, checkpoint, config) and solutions are lightweight **logical** references. `revolver run` auto-creates a single rank-1 solution; additional solutions can be extracted on demand via `revolver solution extract`. Resume creates a new run (`resumed_from: <parent>`), preserving the old run and its eval results intact.

### Why `solutions` is a lightweight reference (not a directory)?

Solutions no longer have their own filesystem directory. The program file is resolved via `.revolver/runs/<run_id>/programs/rank-<N>.py`. This:
- **Eliminates duplication**: checkpoint, config, wrapper live once in the run directory, not copied per solution
- **Simplifies resume**: resume operates on the run (checkpoint), not on a solution
- **Keeps the model clean**: solution = pointer to (run, rank), not a filesystem artifact

### Why normalized tables for metrics (not JSON columns)?

The evaluator returns `dict[str, float]` — one row per metric per instance in `eval_instances`. This enables:
- SQL filtering by metric name
- Index on metric_name for fast lookups
- Simpler schema (no JSON functions required)

### Why raw data only (no stored aggregates)?

Only raw per-instance data is stored in `eval_instances`. Aggregates (mean, min, max, percentiles, std) are computed at read time in Python from the raw data ([DES-006 §4](DES-006-eval-loop.md)). This provides:
- **Single source of truth**: no risk of aggregates diverging from raw data
- **Flexibility**: if aggregate formulas change (e.g., add p25/p75), no migration needed
- **Acceptable performance**: computing aggregates from 10,000 instances takes <10ms in Python

### Why `user_aggregates` as a JSON column?

Legacy evaluators (`evaluate()`) may compute custom aggregation (e.g., weighted average, min-based) that differs from Revolver's standard mean/p10/p90 stats. The `user_aggregates` column in `eval_metadata` stores the raw result of a global `evaluate()` call, allowing both visions to coexist. It is NULL when using `evaluate_instance()` mode (no custom aggregator). See [DES-006](DES-006-eval-loop.md) D-006-g.

### Why separate project and global DBs?

- **Project DB** travels with the project (git, backup, sharing)
- **Global DB** contains machine-specific LLM configs (API keys env vars, local model paths)
- A solution references an LLM by name — if the project moves to another machine, the user re-registers the same LLM name with local config

---

## 10. Resolved Design Questions

- [x] **DM-01**: Evaluation aggregates are **computed at read time** from raw `eval_instances` data in Python. Only `eval_metadata` (session info + optional `user_aggregates`) and `eval_instances` (raw per-instance results) are stored in SQLite. See [DES-006 §4](DES-006-eval-loop.md) for rationale (FR-EVL-006).
- [x] **DM-02**: LLM registry uses **SQLite** (`~/.revolver/revolver.db`), not YAML. Prevents manual edits that could introduce inconsistencies with actual LLM state. All mutations go through `revolver llm add/remove`. Inspection via `revolver llm list --json`.
- [x] **DM-03**: Timestamp-based IDs use **counter suffix** for collision handling (`run-20260310-143000`, then `run-20260310-143000-1`). In practice, collisions are near-impossible (runs take minutes/hours).
- [x] **DM-04**: **Run is the first-class physical entity**; solution is a lightweight logical reference `(run_id, rank)`. Lineage, checkpoint, config all live on the run. Resume creates a new run (`resumed_from`), preserving the old run intact. See refactor-run-solution.md §1–2.
