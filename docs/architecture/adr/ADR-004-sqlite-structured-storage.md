# ADR-004 — SQLite for Structured Storage

**Date**: 2026-03-11
**Status**: Accepted
**Deciders**: Project team

---

## Context

Revolver needs to store structured, queryable data: solution metadata, evaluation metrics (per-instance and aggregates), lineage records, benchmark comparisons, and the global LLM registry. This data needs:

- **Querying**: filter solutions by version/LLM, sort by score, aggregate metrics (NFR-032)
- **Atomic writes**: concurrent CLI invocations must not corrupt data (NFR-016)
- **Relationships**: solutions reference problem versions, datasets, and LLMs via foreign keys
- **Portability**: the project DB (`.revolver/revolver.db`) travels with the project (git, backup)

File-based artifacts (source code, evaluators, checkpoints, YAML manifests) remain on the filesystem — SQLite is only for structured metadata and metrics.

## Decision

Use **SQLite** (via Python's `sqlite3` stdlib module) with **WAL mode** for all structured storage:

- **Project DB** (`.revolver/revolver.db`): problem versions, datasets, solutions, evaluations, benchmarks
- **Global DB** (`~/.revolver/revolver.db`): LLM registry

Schema details are in [DES-001 — SQLite Data Model](../design/DES-001-sqlite-data-model.md).

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| **SQLite** | Zero-server, stdlib support, single-file DB, SQL queries, WAL for concurrent reads, portable | Not suited for multi-process writes (acceptable for CLI), limited to ~1TB (far beyond our needs) |
| **Individual YAML/JSON files** | Human-readable, easy git diffs, no binary files | No querying (must load all files to filter/sort), no atomic writes, no relationships, poor performance at scale (thousands of eval results) |
| **TinyDB / shelve** | Simple key-value, Python-native | No SQL, no foreign keys, no concurrent access guarantees, limited querying |
| **DuckDB** | Columnar analytics, fast aggregates | Overkill for our data volumes, heavier dependency, less mature for OLTP patterns |

## Consequences

### Positive
- SQL enables powerful queries for `solution list --sort score`, `benchmark results --metric X`, per-instance comparisons
- WAL mode allows concurrent reads (e.g., `revolver solution list` while a run is writing)
- Single-file DB is trivially portable — copy `.revolver/` to share a project
- `sqlite3` is in Python's stdlib — zero extra dependency
- Schema migrations are straightforward (sequential version numbers, forward-only)
- Foreign keys enforce referential integrity at the DB level

### Negative
- SQL schema requires upfront design and migration strategy
- No built-in full-text search (not needed for V1)

### Risks
- Schema evolution: mitigated by the `schema_version` table and forward-only migrations (DES-001 §8)
- DB corruption on crash during write: mitigated by WAL mode and SQLite's built-in journaling
- Global DB (`~/.revolver/`) not backed up by project git: acceptable — it contains machine-specific LLM config, not project data

## References

- [DES-001 — SQLite Data Model](../design/DES-001-sqlite-data-model.md) — full schema definition
- [Architecture Overview §5](../architecture.md) — dual storage strategy
- [Specifications NFR-013](../../specs/specifications.md) — immutability constraints
- [Specifications NFR-016](../../specs/specifications.md) — concurrent access (WAL mode)
- [Specifications NFR-032](../../specs/specifications.md) — query performance for listings
