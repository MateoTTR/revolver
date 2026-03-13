# Sprint 005 — Solution Management & Evaluation Loop

**Status**: Planning
**Goal**: Deliver the `revolver solution` command group (list, info, alias, extract) and the `revolver eval` command group (evaluate solutions against datasets, display stored results with aggregates). These commands consume run output and produce the evaluation data needed by benchmarks in Sprint 006.
**Demo**: Browse solutions with `solution list`; extract a rank-2 program into a new named solution; evaluate a solution against an eval dataset with per-instance progress; view aggregate statistics and per-instance breakdown; demonstrate re-evaluation confirmation and legacy evaluator support.

---

## Scope

### Command groups included
- `revolver solution {list,info,alias,extract}` — full implementation
- `revolver eval {<default>,results}` — full implementation (DES-006)

### Key FRs covered

**Solution (13 FRs)**:
- FR-SOL-001 — `list` shows all solutions: ID, alias, version, LLM, score, rank
- FR-SOL-002 — `list --version` / `--llm` / `--rank` filters
- FR-SOL-003 — `info` displays full lineage via JOIN with `runs` table
- FR-SOL-004 — `info` shows program file path (derived: `.revolver/runs/<run_id>/programs/rank-<N>.py`)
- FR-SOL-005 — `info` shows evaluation results if available
- FR-SOL-006 — `alias` sets unique name on solution
- FR-SOL-007 — Aliases unique within project; duplicate rejected
- FR-SOL-008 — Solutions referenced by ID or alias across all commands
- FR-SOL-009 — `info` shows sibling solutions from same run
- FR-SOL-010 — Solution lineage traces to parent run via `run_id`
- FR-SOL-011 — `extract` promotes stored program (run_id, rank) to new solution DB entry
- FR-SOL-012 — `extract` prevents duplicate (run_id, rank) — `UNIQUE(run_id, rank)` constraint
- FR-SOL-013 — `extract` generates unique `sol-YYYYMMDD-HHMMSS` ID

**Eval (20 FRs)**:
- FR-EVL-001 — Iterate over all non-hidden instances in dataset directory
- FR-EVL-002 — Set `REVOLVER_INSTANCE_PATH` and `REVOLVER_INSTANCE_ID` per instance
- FR-EVL-003 — Use evaluator from immutable problem version snapshot (not working copy)
- FR-EVL-004 — Collect `dict[str, float]` metrics + wall-clock time per instance
- FR-EVL-005 — Store raw per-instance results immediately in SQLite `eval_instances`
- FR-EVL-006 — Compute aggregates (mean, min, max, p10, p50, p90, std) at read time only
- FR-EVL-007 — Quick dataset integrity check before evaluation (warn, not block)
- FR-EVL-008 — Warn if dataset incompatible with solution's problem version
- FR-EVL-009 — Warn if dataset split != `eval`
- FR-EVL-010 — Handle per-instance exceptions without aborting full evaluation
- FR-EVL-011 — Record failed instances with `status="failed"` and error message
- FR-EVL-012 — Progress bar (rich) showing instance count and elapsed time
- FR-EVL-013 — Per-instance timeout via `ProcessPoolExecutor`
- FR-EVL-014 — `--parallelism N` for concurrent instances (MAY — implement if time allows)
- FR-EVL-015 — `results` retrieves stored aggregates for a solution
- FR-EVL-016 — `results --per-instance` shows full breakdown by instance
- FR-EVL-017 — `results --per-instance --json` exports raw per-instance data as JSON
- FR-EVL-018 — Confirmation required before re-evaluating (D-006-a); `--force` bypasses
- FR-EVL-019 — Legacy evaluator (`evaluate()` mode) triggers global aggregation call
- FR-EVL-020 — Display both Revolver aggregates and user aggregates when present

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S5-01 | Implement `revolver.models.eval` — `InstanceResult`, `MetricAggregate` (frozen), `EvalMetadata` (frozen), `ComputeTimeSummary` (frozen), `EvalResult`, `EvalDetailResult` Pydantic models (DES-006 §6); status literals `"solved"/"failed"/"timeout"` | models | Sprint 001 | [ ] | Models validate; `frozen=True` on immutable entities; `EvalResult.user_aggregates` nullable for non-legacy mode |
| S5-02 | Add eval CRUD to `revolver.infra.db` — `insert_eval_metadata()`, `insert_eval_instance()` (immediate per-instance), `get_eval_metadata(solution_id, dataset_name)`, `get_eval_instances(eval_id)`, `delete_eval(eval_id)` (cascades to instances); unique index `(solution_id, dataset_name)` enforced | infra | Sprint 001 | [ ] | Unit tests: insert/query/delete; UNIQUE constraint enforced; cascade delete verified; `test_wal_mode_enabled` (re-verify with eval writes) |
| S5-03 | Extend solution queries in `revolver.infra.db` — `update_solution_alias(id, alias)`, `get_solution_by_alias(alias)`, `get_solutions_by_run(run_id)` (sibling query), `insert_solution_extract()` | infra | Sprint 004 | [ ] | Unit tests: alias update; alias uniqueness constraint; sibling query returns correct solutions |
| S5-04 | Implement `revolver.core.eval` — `evaluate_solution()` (main orchestration), `_evaluate_instance()` (subprocess via evaluator_runner), `generate_eval_id()`, `compute_aggregates()` (DES-006 §8, §4.3); dual-mode evaluator detection (`evaluate()` vs `evaluate_instance()`); immediate per-instance storage; progress callback | domain | S5-01, S5-02 | [ ] | Unit tests: `test_iterates_all_instances`, `test_sets_instance_env_vars`, `test_uses_version_evaluator`, `test_collects_metrics_and_time`, `test_aggregates_computed_at_read_time`, `test_handles_per_instance_exception`, `test_records_unsolved_instances`, `test_per_instance_timeout` |
| S5-05 | Implement `revolver.core.eval` — legacy evaluator support (DES-006 D-006-g): detect `evaluate()` mode, run global aggregation call (with `REVOLVER_DATASET_DIR`, without `REVOLVER_INSTANCE_PATH`), store `user_aggregates` JSON in `eval_metadata` | domain | S5-04 | [ ] | Unit tests: `test_legacy_evaluator_global_call`; `user_aggregates` stored correctly; `evaluate_instance()` mode → NULL user_aggregates |
| S5-06 | Implement `revolver.core.eval` — re-evaluation handling (DES-006 D-006-a, §5): check for existing eval, interactive confirmation prompt (`[y/N]`), `--force` bypass, JSON mode error | domain | S5-04 | [ ] | Unit tests: existing results require confirmation; `--force` overrides; JSON mode raises error without `--force`; `test_re_eval_requires_confirmation` integration test |
| S5-07 | Implement `revolver.core.solution` — `list_solutions()` (with filters), `get_solution_info()` (full lineage JOIN + eval results + siblings), `set_alias()` (uniqueness check), `extract_solution()` (creates new solution from existing program file); program path derivation: `.revolver/runs/<run_id>/programs/rank-<N>.py` | domain | S5-03, S5-04 | [ ] | Unit tests: `test_program_path_derived`, `test_lineage_via_run_id`, `test_extract_generates_id`; alias uniqueness enforced |
| S5-08 | Refactor `revolver.core.run._post_run_evaluation()` to call `core.eval.evaluate_solution(force=True, on_progress=None)` — eliminate inline eval code from Sprint 004; verify no regression on Sprint 004 tests | domain | S5-04 | [ ] | Sprint 004 integration tests still pass; `_post_run_evaluation` is now a thin wrapper |
| S5-09 | Implement `revolver.cli.solution` — 4 Typer commands: `list`, `info`, `alias`, `extract`; `--version`, `--llm`, `--rank` filters on `list`; `--run`, `--rank`, `--alias` on `extract` | cli | S5-07 | [ ] | CliRunner tests for all 4 commands; exit 1 on duplicate alias; exit 1 on duplicate extract |
| S5-10 | Implement `revolver.cli.eval` — 2 Typer commands: default eval (callback with `--solution`, `--dataset`, `--timeout`, `--force`, `--per-instance`) and `results` (DES-006 §9); display both Revolver aggregates and user aggregates | cli | S5-04, S5-05, S5-06 | [ ] | CliRunner tests for both commands; exit 1 on non-existent solution; interactive confirmation works |
| S5-11 | Write L2 integration tests for `solution` (9 scenarios from val-integration-tests §2.7) | test | S5-09 | [ ] | All 9 solution scenarios pass |
| S5-12 | Write L2 integration tests for `eval` (10 scenarios from val-integration-tests §2.6) | test | S5-10 | [ ] | All 10 eval scenarios pass |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md §2.6–2.7` that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `solution list` | After 2 runs — solutions listed with ID, alias, version, LLM, score, rank | `test_list_shows_all_solutions` | Planned |
| `solution list --version v1.0` | Only matching solutions | `test_list_filters` | Planned |
| `solution info` | Full lineage via run JOIN, program path, eval results if available | `test_info_full_lineage` | Planned |
| `solution info` | Sibling solutions from same run shown | `test_info_shows_sibling_solutions` | Planned |
| `solution alias` | Alias set — DB updated | `test_alias_set` | Planned |
| `solution alias` | Duplicate alias — exit code 1 | `test_alias_unique` | Planned |
| `solution list` | Reference by alias in filters | `test_reference_by_alias` | Planned |
| `solution extract` | Promote rank #2 — new solution entry, unique ID | `test_extract_promotes_program` | Planned |
| `solution extract` | Same (run_id, rank) already extracted — exit code 1 | `test_extract_duplicate_blocked` | Planned |
| `eval` | Valid solution + 3 instances — per-instance in DB, aggregates displayed | `test_stores_per_instance_results` | Planned |
| `eval` | One instance fails — recorded as unsolved, eval continues | `test_handles_instance_failure` | Planned |
| `eval` | Non-existent solution — exit code 1 | `test_nonexistent_solution` | Planned |
| `eval` | Integrity check fails — warning, eval proceeds | `test_integrity_warning` | Planned |
| `eval` | Incompatible version — warning on stderr | `test_warns_incompatible_version` | Planned |
| `eval` | Split=train — warning on stderr | `test_warns_non_eval_split` | Planned |
| `eval` | Results already exist — confirmation required; `--force` skips | `test_re_eval_requires_confirmation` | Planned |
| `eval results` | After eval, human mode — aggregates + per-instance breakdown | `test_results_command` + `test_results_per_instance` | Planned |
| `eval results --json` | Full raw per-instance JSON | `test_results_per_instance_json` | Planned |
| `eval` | Legacy evaluator — global aggregation, `user_aggregates` stored | `test_results_shows_user_aggregates` | Planned |

**Cumulative L2 tests passing: 71 / 71 (sprints 001–005)**

---

## Parallelization

### Dependency graph

```
Sprint 004 (run + solutions DB rows exist) ──┬──> S5-01 (models: eval)
                                              │
                                              ├──> S5-02 (infra: db/eval) ─────┐
                                              │                                  │
                                              ├──> S5-03 (infra: db/sol++)────┐ │
                                              │                                │ │
                                              │                                ├─┼──> S5-04 (domain: eval core)
                                              │                                │ │         ↓
                                              │                                │ │    S5-05 (domain: legacy eval)
                                              │                                │ │         ↓
                                              │                                │ │    S5-06 (domain: re-eval)
                                              │                                │ │         ↓
                                              │                                │ │    S5-10 (cli: eval)
                                              │                                │ │         ↓
                                              │                                │ │    S5-12 (test: eval — 10 scenarios)
                                              │                                │ │
                                              │                                └─┤
                                              │                                  └──> S5-07 (domain: solution)
                                              │                                        ↓
                                              │                              S5-08 (refactor: post-run eval)
                                              │                                        ↓
                                              │                                   S5-09 (cli: solution)
                                              │                                        ↓
                                              └────────────────────────────────── S5-11 (test: solution — 9 scenarios)
```

### Critical path
Sprint 004 → S5-01 + S5-02 → S5-04 → S5-05 → S5-06 → S5-10 → S5-12
Estimated sequential depth: 6 steps after prerequisites.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Eval models + infra | S5-01, S5-02 | Sprint 004 done | Agent 1 |
| B — Solution infra extension | S5-03 | Sprint 004 done | Agent 2 |
| C — Eval domain (core + legacy + re-eval) + CLI + tests | S5-04, S5-05, S5-06, S5-10, S5-12 | Streams A+B done | Agent 1 |
| D — Solution domain + refactor + CLI + tests | S5-07, S5-08, S5-09, S5-11 | Streams A+B done | Agent 2 |

Peak parallelism: 2 agents simultaneously (Streams A and B in parallel, then C and D in parallel).

### Conflict risks
- `infra/db.py` — Stream A adds eval CRUD, Stream B adds solution alias queries; different tables but same file; coordinate with care
- `core/run.py` — S5-08 modifies `_post_run_evaluation()` which was written in Sprint 004; test Sprint 004 scenarios again after refactor to verify no regression
- `infra/evaluator_runner.py` — shared from Sprint 002; no changes expected; Stream C reads only
- `cli/__init__.py` — registering 2 new Typer sub-apps (`solution` and `eval`) concurrently; trivial merge

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- 0 / 19 integration tests passing (this sprint)
- 0 / 71 total cumulative integration tests

### Demo-able features
- [ ] `revolver solution list` shows all solutions from previous runs
- [ ] `revolver solution list --version v1.0` filters by problem version
- [ ] `revolver solution info sol-xxx` shows full lineage, program path, eval results, siblings
- [ ] `revolver solution alias sol-xxx my-best-solution` sets alias
- [ ] `revolver solution extract --run run-xxx --rank 2 --alias rank2-solution`
- [ ] `revolver eval --solution my-best-solution --dataset eval-bench` with progress bar
- [ ] `revolver eval results --solution my-best-solution` shows aggregates (mean, p10, p50, p90)
- [ ] `revolver eval results --solution my-best-solution --per-instance` shows instance breakdown
- [ ] Re-evaluation confirmation prompt prevents accidental data loss
- [ ] Legacy evaluator with `user_aggregates` displayed alongside Revolver aggregates

### Carry-over
- FR-EVL-014 (`--parallelism N`) deferred to v2 (MAY priority per spec)
