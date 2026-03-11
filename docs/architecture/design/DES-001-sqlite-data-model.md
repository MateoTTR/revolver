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
    │ dataset_  │  │eval_results ││  │solution_lineage│  │
    │ instances │  │(PK: eval_id,││  │(PK: solution_id│  │
    └───────────┘  │metric_name) ││  └────────────────┘  │
                   └──────┬──────┘│                       │
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
    config_snapshot TEXT                    -- verbatim OpenEvolve YAML config (NFR-023)
);
```

**Constraints**: Fully immutable. Written once at run completion.

### 3.7 `eval_results`

Aggregate evaluation statistics per (solution, dataset, metric).

```sql
CREATE TABLE eval_results (
    eval_id         TEXT NOT NULL,          -- "eval-YYYYMMDD-HHMMSS"
    solution_id     TEXT NOT NULL REFERENCES solutions(id),
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    metric_name     TEXT NOT NULL,          -- "combined_score", "makespan", etc.
    mean            REAL NOT NULL,
    min             REAL NOT NULL,
    max             REAL NOT NULL,
    p10             REAL NOT NULL,
    p50             REAL NOT NULL,
    p90             REAL NOT NULL,
    std             REAL NOT NULL,
    instance_count  INTEGER NOT NULL,
    instances_solved INTEGER NOT NULL,
    eval_time_s     REAL,                   -- total wall-clock time
    evaluated_at    TEXT NOT NULL,           -- ISO 8601
    PRIMARY KEY (eval_id, metric_name)
);

CREATE INDEX idx_eval_solution ON eval_results(solution_id, dataset_name);
CREATE UNIQUE INDEX idx_eval_unique ON eval_results(solution_id, dataset_name, metric_name);
```

**Note**: `idx_eval_unique` ensures at most one aggregate per (solution, dataset, metric). Re-evaluation replaces the previous result (INSERT OR REPLACE on this unique index).

### 3.8 `eval_instances`

Raw per-instance results. Stored for post-processing (histograms, plots, per-instance comparison).

```sql
CREATE TABLE eval_instances (
    eval_id         TEXT NOT NULL,
    instance_id     TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    value           REAL,                   -- NULL if failed/timeout
    status          TEXT NOT NULL CHECK (status IN ('solved', 'failed', 'timeout')),
    error_message   TEXT,                   -- if status != 'solved'
    compute_time_s  REAL,                   -- wall-clock time for this instance
    PRIMARY KEY (eval_id, instance_id, metric_name),
    FOREIGN KEY (eval_id, metric_name) REFERENCES eval_results(eval_id, metric_name)
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
       sl.top_n, sl.config_snapshot
FROM solutions s
JOIN solution_lineage sl ON s.id = sl.solution_id
WHERE s.id = :id_or_alias OR s.alias = :id_or_alias;
```

### 6.2 Solution list with filters (`revolver solution list`)

```sql
SELECT s.id, s.alias, s.problem_version, s.llm, s.dataset,
       s.best_score, s.created_at
FROM solutions s
WHERE (:version IS NULL OR s.problem_version = :version)
  AND (:llm IS NULL OR s.llm = :llm)
ORDER BY
    CASE :sort
        WHEN 'created_at' THEN s.created_at
        WHEN 'score' THEN s.best_score
        WHEN 'alias' THEN s.alias
    END;
```

### 6.3 Benchmark comparison (`revolver benchmark results`)

```sql
SELECT s.id, s.alias,
       er.metric_name, er.mean, er.min, er.max, er.p10, er.p50, er.p90, er.std,
       sl.generation_time_s, er.eval_time_s
FROM benchmark_solutions bs
JOIN solutions s ON bs.solution_id = s.id
JOIN eval_results er ON s.id = er.solution_id AND er.dataset_name = :dataset
LEFT JOIN solution_lineage sl ON s.id = sl.solution_id
WHERE bs.benchmark_id = :bench_id
  AND (:metric IS NULL OR er.metric_name = :metric)
ORDER BY er.metric_name, er.mean DESC;
```

### 6.4 Per-instance comparison (`revolver benchmark results --per-instance`)

```sql
SELECT ei.instance_id, s.alias, ei.metric_name, ei.value, ei.compute_time_s
FROM benchmark_solutions bs
JOIN solutions s ON bs.solution_id = s.id
JOIN eval_results er ON s.id = er.solution_id AND er.dataset_name = :dataset
JOIN eval_instances ei ON er.eval_id = ei.eval_id AND ei.metric_name = er.metric_name
WHERE bs.benchmark_id = :bench_id
ORDER BY ei.instance_id, ei.metric_name, ei.value DESC;
```

### 6.5 Check existing eval results (benchmark reuse)

```sql
SELECT eval_id FROM eval_results
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

---

## 7. ID Generation

| Entity | Pattern | Example | Collision handling |
|---|---|---|---|
| Problem version | User-provided tag | `v1.0` | UNIQUE constraint, reject on duplicate |
| Dataset | User-provided name | `train-small` | UNIQUE constraint, reject on duplicate |
| Solution | `sol-{YYYYMMDD}-{HHMMSS}` | `sol-20260310-143000` | Append counter if needed: `sol-20260310-143000-1` |
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

The evaluator returns `dict[str, float]` — one row per metric per instance in `eval_instances`, one row per metric in `eval_results`. This enables:
- SQL filtering by metric name
- Aggregate queries without JSON parsing
- Index on metric_name for fast lookups
- Simpler schema (no JSON functions required)

### Why store aggregates AND raw data?

- **Raw data** (`eval_instances`): enables post-processing, histograms, per-instance comparison
- **Aggregates** (`eval_results`): fast reads for listing/comparing without recomputing from thousands of rows
- Aggregates are computed at eval time and stored as a cache. They could be recomputed from raw data if needed.

### Why separate project and global DBs?

- **Project DB** travels with the project (git, backup, sharing)
- **Global DB** contains machine-specific LLM configs (API keys env vars, local model paths)
- A solution references an LLM by name — if the project moves to another machine, the user re-registers the same LLM name with local config

---

## 10. Resolved Design Questions

- [x] **DM-01**: `eval_results` aggregates are **materialized** (written once at eval time). Fast reads for listing/comparing (NFR-032). Can be recomputed from `eval_instances` if needed.
- [x] **DM-02**: LLM registry uses **SQLite** (`~/.revolver/revolver.db`), not YAML. Prevents manual edits that could introduce inconsistencies with actual LLM state. All mutations go through `revolver llm add/remove`. Inspection via `revolver llm list --json`.
- [x] **DM-03**: Timestamp-based IDs use **counter suffix** for collision handling (`sol-20260310-143000`, then `sol-20260310-143000-1`). In practice, collisions are near-impossible (runs take minutes/hours).
