# DES-001 — SQLite Data Model

**Version**: 0.1 — Initial draft
**Date**: 2026-03-10
**Status**: Draft
**Traceable to**: [Architecture Overview](../architecture.md) §5, [Specifications](../../specs/specifications.md) NFR-013/016

---

## 1. Overview

Revolver uses two SQLite databases:

| Database | Location | Scope | Contents |
|---|---|---|---|
| **Project DB** | `.revolver/revolver.db` | Per-project | Problem versions, datasets, solutions, evaluations, benchmarks |
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
           ┌───────┴──────┐  ┌──┴───────┐  ┌┴─────────────┐
           │dataset_compat│  │ solutions │  │              │
           └───────┬──────┘  └──┬───┬───┘  │              │
                   │ N          │   │       │              │
                   │         1  │   │ 1     │              │
            ┌──────▼──────┐    │   │       │              │
            │  datasets   │◄───┘   │       │              │
            │ (PK: name)  │        │       │              │
            └──┬──────┬───┘        │       │              │
               │      │            │       │              │
            1  │      │ 1          │       │              │
               │      │            │       │              │
    ┌──────────▼┐  ┌──▼──────────┐│  ┌────▼───────────┐  │
    │ dataset_  │  │eval_metadata││  │solution_lineage│  │
    │ instances │  │(PK: eval_id)││  │(PK: solution_id│  │
    └───────────┘  └──────┬──────┘│  └────────────────┘  │
                          │       │                       │
                       1  │       │                       │
                          │       │                       │
                   ┌──────▼──────┐│  ┌───────────────────┐│
                   │eval_instance││  │benchmark_solutions││
                   │    s        ││  └────────┬──────────┘│
                   └─────────────┘│           │           │
                                  │        N  │           │
                                  │           │           │
                                  │  ┌────────▼──────┐    │
                                  │  │  benchmarks   │    │
                                  │  │ (PK: id)      │    │
                                  │  └───────────────┘    │
                                  │                       │
                                  │  ~/.revolver/         │
                                  │  ┌───────────────┐    │
                                  └──│     llms      │    │
                                     │ (PK: name)    │    │
                                     └───────────────┘    │
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

### 3.5 `solutions`

Solution metadata created by `revolver run`.

```sql
CREATE TABLE solutions (
    id              TEXT PRIMARY KEY,       -- "sol-YYYYMMDD-HHMMSS"
    alias           TEXT UNIQUE,            -- nullable, user-friendly name
    problem_version TEXT NOT NULL REFERENCES problem_versions(tag),
    llm             TEXT NOT NULL,          -- LLM name from registry
    dataset         TEXT NOT NULL REFERENCES datasets(name),
    best_score      REAL,                   -- best combined_score from training
    created_at      TEXT NOT NULL           -- ISO 8601
);

CREATE INDEX idx_solutions_version ON solutions(problem_version);
CREATE INDEX idx_solutions_llm ON solutions(llm);
CREATE INDEX idx_solutions_created ON solutions(created_at DESC);
```

**Constraints**: ID, problem_version, llm, dataset immutable. Alias updateable.

### 3.6 `solution_lineage`

Full provenance for traceability (NFR-020).

```sql
CREATE TABLE solution_lineage (
    solution_id     TEXT PRIMARY KEY REFERENCES solutions(id),
    problem_hash    TEXT NOT NULL,          -- hash of problem snapshot used
    dataset_hash    TEXT NOT NULL,          -- hash of dataset at registration
    llm_model       TEXT NOT NULL,          -- full model ID (e.g., "claude-opus-4-6")
    iterations      INTEGER NOT NULL,       -- OpenEvolve iterations completed
    generation_time_s REAL,                 -- wall-clock seconds
    top_n           INTEGER NOT NULL DEFAULT 1,
    run_id          TEXT NOT NULL,          -- shared ID across top-N solutions from same run
    rank            INTEGER NOT NULL DEFAULT 1, -- 1 = best, 2 = second best, etc.
    config_snapshot TEXT                    -- verbatim OpenEvolve YAML config (NFR-023)
);

CREATE INDEX idx_lineage_run ON solution_lineage(run_id);
```

**Constraints**: Fully immutable. Written once at run completion. When `--top-n > 1`, all N solutions from the same run share the same `run_id` (equal to the first solution's ID). `rank` = 1 is the best program.

### 3.7 `eval_metadata`

Evaluation session metadata. Aggregate statistics (mean, min, max, p10, p50, p90, std) are **not stored** — they are computed at read time from raw `eval_instances` data in Python ([DES-006 §4](DES-006-eval-loop.md)).

```sql
CREATE TABLE eval_metadata (
    eval_id         TEXT PRIMARY KEY,       -- "eval-YYYYMMDD-HHMMSS"
    solution_id     TEXT NOT NULL REFERENCES solutions(id),
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    instance_count  INTEGER NOT NULL,
    instances_solved INTEGER NOT NULL,
    eval_time_s     REAL,                   -- total wall-clock time
    evaluated_at    TEXT NOT NULL            -- ISO 8601
);

CREATE UNIQUE INDEX idx_eval_unique ON eval_metadata(solution_id, dataset_name);
```

**Note**: `idx_eval_unique` ensures at most one evaluation per (solution, dataset). Re-evaluation replaces the previous result (DELETE old + INSERT new in a transaction).

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
    registered_at   TEXT NOT NULL           -- ISO 8601
);
```

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

---

## 6. Key Queries

### 6.1 Solution detail (`revolver solution info`)

```sql
SELECT s.id, s.alias, s.problem_version, s.llm, s.dataset,
       s.best_score, s.created_at,
       sl.llm_model, sl.iterations, sl.generation_time_s,
       sl.top_n, sl.run_id, sl.rank, sl.config_snapshot
FROM solutions s
JOIN solution_lineage sl ON s.id = sl.solution_id
WHERE s.id = :id_or_alias OR s.alias = :id_or_alias;
```

### 6.2 Solution list with filters (`revolver solution list`)

```sql
SELECT s.id, s.alias, s.problem_version, s.llm, s.dataset,
       s.best_score, s.created_at, sl.rank, sl.run_id
FROM solutions s
JOIN solution_lineage sl ON s.id = sl.solution_id
WHERE (:version IS NULL OR s.problem_version = :version)
  AND (:llm IS NULL OR s.llm = :llm)
  AND (:rank IS NULL OR sl.rank = :rank)
ORDER BY
    CASE :sort
        WHEN 'created_at' THEN s.created_at
        WHEN 'score' THEN s.best_score
        WHEN 'alias' THEN s.alias
    END;
```

### 6.3 Benchmark: raw per-instance data (`revolver benchmark results`)

Benchmark comparison loads raw per-instance data from `eval_instances` and computes aggregates in Python (see [DES-006 §4](DES-006-eval-loop.md)).

```sql
SELECT ei.instance_id, s.id AS solution_id, s.alias,
       ei.metric_name, ei.value, ei.status, ei.compute_time_s,
       sl.generation_time_s
FROM benchmark_solutions bs
JOIN solutions s ON bs.solution_id = s.id
JOIN eval_metadata em ON s.id = em.solution_id AND em.dataset_name = :dataset
JOIN eval_instances ei ON em.eval_id = ei.eval_id
LEFT JOIN solution_lineage sl ON s.id = sl.solution_id
WHERE bs.benchmark_id = :bench_id
  AND (:metric IS NULL OR ei.metric_name = :metric)
ORDER BY ei.instance_id, ei.metric_name, s.id;
```

Aggregates (mean, min, max, p10, p50, p90, std) are computed per (solution, metric) in Python from this result set.

### 6.4 Per-instance comparison (`revolver benchmark results --per-instance`)

```sql
SELECT ei.instance_id, s.alias, ei.metric_name, ei.value, ei.compute_time_s
FROM benchmark_solutions bs
JOIN solutions s ON bs.solution_id = s.id
JOIN eval_metadata em ON s.id = em.solution_id AND em.dataset_name = :dataset
JOIN eval_instances ei ON em.eval_id = ei.eval_id
WHERE bs.benchmark_id = :bench_id
ORDER BY ei.instance_id, ei.metric_name, ei.value DESC;
```

### 6.5 Check existing eval results (benchmark reuse)

```sql
SELECT eval_id FROM eval_metadata
WHERE solution_id = :solution_id AND dataset_name = :dataset_name
LIMIT 1;
```

### 6.6 Dataset integrity verification

```sql
SELECT instance_id, hash
FROM dataset_instances
WHERE dataset_name = :dataset_name
ORDER BY instance_id;
```

### 6.7 Sibling solutions from same run (`revolver solution info`)

```sql
SELECT s.id, s.alias, sl.rank, s.best_score
FROM solution_lineage sl
JOIN solutions s ON s.id = sl.solution_id
WHERE sl.run_id = :run_id AND sl.solution_id != :current_id
ORDER BY sl.rank;
```

---

## 7. ID Generation

| Entity | Pattern | Example | Collision handling |
|---|---|---|---|
| Problem version | User-provided tag | `v1.0` | UNIQUE constraint, reject on duplicate |
| Dataset | User-provided name | `train-small` | UNIQUE constraint, reject on duplicate |
| Solution | `sol-{YYYYMMDD}-{HHMMSS}` | `sol-20260310-143000` | Append counter if needed: `sol-20260310-143000-1` |
| Run ID | First solution's ID | `sol-20260310-143000` | Same as solution (shared across top-N) |
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
    2: "add_eval_tags.sql",     # hypothetical future change
}
```

---

## 9. Design Decisions

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

### Why separate project and global DBs?

- **Project DB** travels with the project (git, backup, sharing)
- **Global DB** contains machine-specific LLM configs (API keys env vars, local model paths)
- A solution references an LLM by name — if the project moves to another machine, the user re-registers the same LLM name with local config

---

## 10. Resolved Design Questions

- [x] **DM-01**: Evaluation aggregates are **computed at read time** from raw `eval_instances` data in Python. Only `eval_metadata` (session info) and `eval_instances` (raw per-instance results) are stored in SQLite. See [DES-006 §4](DES-006-eval-loop.md) for rationale (FR-EVL-006).
- [x] **DM-02**: LLM registry uses **SQLite** (`~/.revolver/revolver.db`), not YAML. Prevents manual edits that could introduce inconsistencies with actual LLM state. All mutations go through `revolver llm add/remove`. Inspection via `revolver llm list --json`.
- [x] **DM-03**: Timestamp-based IDs use **counter suffix** for collision handling (`sol-20260310-143000`, then `sol-20260310-143000-1`). In practice, collisions are near-impossible (runs take minutes/hours).
