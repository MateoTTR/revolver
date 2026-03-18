# Sprint 006 — Benchmark: Multi-Solution Comparison & Export

**Status**: Complete (v0.6.0)
**Goal**: Deliver the `revolver benchmark` command group — comparative multi-solution benchmarking with eval reuse, aggregate computation (reusing `compute_aggregates()` from eval), per-instance comparison with best-per-instance identification, and CSV/JSON export matching ConOps §8 schemas. This is the capstone of the evaluation pipeline.
**Demo**: Benchmark 3 solutions against an eval dataset; one already evaluated (reused), one triggers new evaluation; view comparative aggregate table; per-instance side-by-side comparison with wins summary; export to CSV and JSON without secrets.

---

## Scope

### Command groups included
- `revolver benchmark {<default>,results,export,list}` — full implementation (DES-007)

### Key FRs covered
- FR-BEN-001 — Accept multiple solution IDs/aliases and a single eval dataset
- FR-BEN-002 — Reuse existing eval results for solutions already evaluated on the dataset
- FR-BEN-003 — Trigger `core.eval.evaluate_solution()` for solutions missing results
- FR-BEN-004 — Comparative table with per-metric aggregate statistics
- FR-BEN-005 — Include full lineage per solution (problem version, LLM, train dataset, gen time)
- FR-BEN-006 — Store benchmark metadata + solution references in SQLite (single source of truth)
- FR-BEN-007 — CSV export matching ConOps §8.1 schema; one row per (solution, metric)
- FR-BEN-008 — JSON export matching ConOps §8.2 schema; nested lineage and metrics
- FR-BEN-009 — Include `eval_time_s` and `instances_solved` in results
- FR-BEN-010 — Sort comparative table by configurable metric (default: `combined_score` mean)
- FR-BEN-011 — Include `generation_time_s` in lineage display
- FR-BEN-012 — `list` shows all benchmarks with date, dataset, solution count
- FR-BEN-013 — No secrets (paths, API keys, env vars) in exports (DES-007 §6.3)
- FR-BEN-014 — `results --per-instance` side-by-side per-instance comparison matrix
- FR-BEN-015 — Identify best solution per instance with wins summary
- FR-BEN-016 — `export --per-instance` raw per-instance CSV/JSON rows
- FR-BEN-017 — Include `run_id` in exports for traceability

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S6-01 | Implement `revolver.models.benchmark` — 8 Pydantic models (DES-007 §7) | models | Sprint 001 | [x] | PR #60, session 030 |
| S6-02 | Add benchmark CRUD to `revolver.infra.db` — 6 functions + migration v3 (DES-007 §9) | infra | Sprint 001 | [x] | PR #61, session 030 |
| S6-03 | Implement `core.benchmark.run_benchmark()` — orchestration, eval reuse, partial failure (DES-007 §2.1, §3, §10) | domain | S6-01, S6-02, Sprint 005 | [x] | PR #64, session 030 |
| S6-04 | Implement `core.benchmark.get_benchmark_results()` — aggregates + per-instance comparison (DES-007 §2.2, §5) | domain | S6-03 | [x] | PR #64, session 030 |
| S6-05 | Implement `core.benchmark.export_benchmark()` + `list_benchmarks()` — CSV/JSON export (DES-007 §2.3-4, §6) | domain | S6-03 | [x] | PR #64, session 030 |
| S6-06 | Implement `cli.benchmark` — 4 Typer commands (DES-007 §11) | cli | S6-03, S6-04, S6-05 | [x] | PR #65, session 030 |
| S6-07 | Write L2 integration tests for `benchmark` (9 scenarios from val-integration-tests §2.8) | test | S6-06 | [x] | PR #65, session 030 |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md §2.8` that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `benchmark` | 2 solutions + eval dataset — comparison table, DB entries, lineage | `test_accepts_multiple_solutions` + `test_metadata_stored_in_db` | Planned |
| `benchmark` | One solution already evaluated — reuses results, no redundant eval | `test_runs_missing_evals` (verifies reuse path) | Planned |
| `benchmark` | One solution not yet evaluated — triggers evaluation | `test_runs_missing_evals` | Planned |
| `benchmark results` | After benchmark, human mode — aggregate table with eval_time, instances_solved | `test_comparative_table` | Planned |
| `benchmark results --per-instance` | Side-by-side, best per instance highlighted | `test_results_per_instance` | Planned |
| `benchmark export --format csv` | Valid CSV, no secrets, run_id included | `test_export_csv` | Planned |
| `benchmark export --format json` | Valid JSON matching ConOps §8.2 schema | `test_export_json` | Planned |
| `benchmark export --per-instance` | Per-instance rows for all solutions | `test_export_per_instance` | Planned |
| `benchmark list` | After 2 benchmarks — both listed with date, dataset, solution count | `test_list_benchmarks` | Planned |

**Cumulative L2 tests passing: 80 / 80 (sprints 001–006)**

---

## Parallelization

### Dependency graph

```
Sprint 005 (eval + solution commands delivered) ──┬──> S6-01 (models: benchmark)
                                                   │
                                                   └──> S6-02 (infra: db/benchmark) ─┐
                                                                                       │
                                                                  S6-01 ──────────────┼──> S6-03 (domain: run_benchmark)
                                                                                       │         ↓
                                                                                       │    S6-04 (domain: results + per-instance)
                                                                                       │         ↓
                                                                                       │    S6-05 (domain: export + list)
                                                                                       │         ↓
                                                                                       │    S6-06 (cli: benchmark commands)
                                                                                       │         ↓
                                                                                       └──  S6-07 (test: L2 — 9 scenarios)
```

### Critical path
Sprint 005 → S6-01 + S6-02 (parallel) → S6-03 → S6-04 → S6-05 → S6-06 → S6-07
Estimated sequential depth: 6 steps after prerequisites.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Models + infra | S6-01, S6-02 | Sprint 005 done | Agent 1 (models) + Agent 2 (infra) |
| B — Core benchmark logic | S6-03, S6-04, S6-05 | Stream A done | Agent 1 |
| C — CLI + tests | S6-06, S6-07 | Stream B done | Agent 2 |

Note: this sprint has limited internal parallelism because benchmark domain logic is a single chain (run → results → export). The main parallelization opportunity is overlapping Stream A with late Sprint 005 testing tasks.

Peak parallelism: 2 agents briefly on Stream A (models + infra simultaneously), then sequential.

### Conflict risks
- `infra/db.py` — adds benchmark queries; the file is large by now; consider extracting tables into a query module per entity (e.g., `db_queries/benchmarks.py`) if maintainability suffers
- `core/eval.py` — benchmark calls `evaluate_solution()` and imports `compute_aggregates()`; no changes to eval expected; read-only dependency from Sprint 005
- `cli/__init__.py` — registering benchmark Typer sub-app; trivial merge

---

## Sprint Review

### Tests passing
- 9 / 9 integration tests passing (this sprint)
- 697 total tests (unit + integration)

### PRs delivered

| PR | Tasks | Title |
|---|---|---|
| #60 | S6-01 | Benchmark Pydantic models (8 models) |
| #61 | S6-02 | Benchmark DB CRUD + migration v3 |
| #64 | S6-03/04/05 | core.benchmark — run, results, export, list |
| #65 | S6-06/07 | cli.benchmark + 9 L2 integration tests |

### Demo-able features
- [x] `revolver benchmark --solutions sol-A sol-B sol-C --dataset eval-bench`
- [x] Reuse of existing eval results for previously evaluated solutions (shown in output)
- [x] New evaluation triggered for unevaluated solutions during benchmark
- [x] `revolver benchmark results --latest` shows comparative aggregate table sorted by metric
- [x] `revolver benchmark results --latest --per-instance --metric combined_score` with wins summary
- [x] `revolver benchmark export --latest --format csv --output results.csv` — valid ConOps schema
- [x] `revolver benchmark export --latest --format json --output results.json` — valid ConOps §8.2
- [x] `revolver benchmark list` shows all benchmarks with metadata
- [x] No secrets (no file paths, no API key env names) in any export

### Carry-over
- Parquet export format deferred indefinitely (AQ-05 resolved: CSV + JSON only in v1, per DES-007 DD-03)
