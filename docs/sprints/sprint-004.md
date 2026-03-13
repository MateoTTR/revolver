# Sprint 004 — Run Orchestration (OpenEvolve Integration)

**Status**: Planning
**Goal**: Deliver the `revolver run` command group — the core of Revolver. This sprint implements OpenEvolve orchestration: input validation, wrapper evaluator generation, environment setup (`REVOLVER_*` env vars), OpenEvolve launch via controller class, result collection, post-run training evaluation (rank-1), token/cost tracking via HTTP proxy, and run management commands (`status`, `resume`, `list`, `info`).
**Demo**: Launch a mocked OpenEvolve run with a problem version + LLM + dataset; observe progress; inspect the completed run with `run info` showing lineage, token usage, program paths, and auto-created solution; resume an interrupted run.

---

## Scope

### Command groups included
- `revolver run {<default>,status,resume,list,info}` — full implementation (DES-005)

### Key FRs covered
- FR-RUN-001 — Validate problem version, LLM, dataset existence before launching
- FR-RUN-002 — Warn if dataset split != `train` (not block)
- FR-RUN-003 — Warn if dataset incompatible with problem version (not block)
- FR-RUN-004 — Verify dataset integrity before launch; exit 2 on mismatch
- FR-RUN-005 — Set `REVOLVER_DATASET_DIR` env var (ADR-006 Strategy A)
- FR-RUN-006 — Configure OpenEvolve LLM endpoint from registry (base_url, model, api_key_env)
- FR-RUN-007 — Generate unique run ID (`run-YYYYMMDD-HHMMSS`) and solution ID
- FR-RUN-008 — Store all top-ranked programs in `.revolver/runs/<run_id>/programs/`; auto-create rank-1 solution reference in DB
- FR-RUN-009 — Record full lineage in run manifest (problem_hash, dataset_hash, llm_model, config_snapshot)
- FR-RUN-010 — Store run metadata and best_score in SQLite `runs` table
- FR-RUN-011 — Store OpenEvolve checkpoint for resume
- FR-RUN-012 — `--alias` sets alias on auto-created solution
- FR-RUN-013 — `resume` creates new run (`resumed_from: <parent>`) from parent checkpoint
- FR-RUN-014 — Local LLM runs execute sequentially (lock file in `.revolver/runs/locks/`)
- FR-RUN-015 — Remote LLM runs can execute in parallel (no global lock)
- FR-RUN-016 — Progress display: iteration count, best score, elapsed time (stderr)
- FR-RUN-017 — Store verbatim OpenEvolve YAML config in `config_snapshot` column (NFR-023)
- FR-RUN-018 — Record generation wall-clock time in `generation_time_s`
- FR-RUN-019 — Post-run evaluation: evaluate rank-1 program on training instances
- FR-RUN-020 — Training evaluation results accessible via `revolver eval results`
- FR-RUN-021 — `run list` filterable by version, LLM, status
- FR-RUN-022 — `run info` shows full details: lineage, token usage, solution, stored programs
- FR-RUN-023 — `--dry-run` displays resolved config without launching
- FR-RUN-024 — Resume copies wrapper evaluator from parent run
- FR-RUN-025 — Per-run lock files prevent concurrent local LLM usage
- FR-RUN-026 — Set `REVOLVER_INSTANCE_LOG` side-channel (ADR-006 Strategy B)
- FR-RUN-027 — Set `REVOLVER_EVAL_LOG` for per-evaluation logging
- FR-RUN-028 — Track `prompt_tokens` + `completion_tokens` via HTTP proxy (DES-005 DD-14)
- FR-RUN-029 — Display token usage on run completion
- FR-RUN-030 — Estimate cost from LLM pricing at run completion

### Includes existing backlog task
- **Task 26 (backlog)** — Implement wrapper evaluator generator: transforms user's `evaluate_instance()` / `evaluate()` into OpenEvolve-compatible `evaluate(program_path)` wrapper (DES-005 §3)

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S4-01 | Implement `revolver.infra.openevolve` — OpenEvolve wrapper: import via `importlib`, configure `EvolutionConfig` programmatically, launch via `OpenEvolveController` class (not `run_evolution()`), monitor progress via callback, collect top-N programs; handle `OpenEvolveError` (DES-005 §4-6) | infra | Sprint 001 | [ ] | Unit tests with mocked OpenEvolve controller class; launch/monitor/collect works; progress callback invoked per iteration |
| S4-02 | Implement `revolver.infra.token_proxy` — transparent HTTP proxy for token tracking (DES-005 DD-14): intercepts responses to LLM API calls, extracts `usage.prompt_tokens` / `usage.completion_tokens` from JSON responses, accumulates totals; proxy runs as local HTTP server on a free port | infra | Sprint 001 | [ ] | Unit test: proxy captures token counts from mock API response bodies; `test_token_extraction` |
| S4-03 | Implement wrapper evaluator generator (Task 26) — `generate_wrapper(evaluator_path, output_path, mode)`: generates a valid OpenEvolve-compatible `evaluate(program_path)` wrapper from user's evaluator; handles both `evaluate_instance()` mode (iterates instances) and `evaluate()` mode (sets env vars per instance) (DES-005 §3) | infra | S4-01 | [ ] | Unit tests: generated wrapper is valid Python; test with evaluator_simple.py and evaluator_legacy.py fixtures; wrapper iterates instances correctly |
| S4-04 | Implement `revolver.models.run` — `Run` (frozen for completed), `RunManifest`, `TokenUsage`, `RunResult` Pydantic models; `status` field with `Literal["running", "completed", "interrupted"]` | models | Sprint 001 | [ ] | Models validate; datetime fields serialize to ISO 8601; `TokenUsage` nullable fields for unavailable data |
| S4-05 | Implement `revolver.models.solution` — `Solution` Pydantic model: `id`, `run_id`, `rank`, `best_score`, `alias` (nullable); `UNIQUE(run_id, rank)` invariant documented | models | Sprint 001 | [ ] | Model validates; `model_dump()` serializes; alias uniqueness constraint is domain-level responsibility |
| S4-06 | Add run/solution CRUD to `revolver.infra.db` — `insert_run()`, `update_run_status()`, `update_run_tokens()`, `get_run(id)`, `list_runs(version, llm, status)`, `insert_solution()`, `get_solution(id_or_alias)`, `list_solutions(version, llm, rank)` | infra | Sprint 001 | [ ] | Unit tests: all CRUD operations; `list_runs` filter combinations; `get_solution` resolves alias; `test_metrics_stored_in_db` |
| S4-07 | Implement `revolver.core.run` — `launch_run()`: full orchestration (DES-005 §4-7): validate inputs, generate wrapper evaluator, resolve `problem.md` for system prompt injection (FR-PRB-015), configure OpenEvolve, set env vars, start token proxy if applicable, launch run, collect programs, insert solution DB row, write run manifest, update run status | domain | S4-01, S4-02, S4-03, S4-04, S4-05, S4-06 | [ ] | Unit tests with mocked infra; `test_sets_dataset_dir_env`, `test_configures_openevolve_llm`, `test_unique_run_id_format`, `test_sets_instance_log_env`, `test_sets_eval_log_env`, `test_local_llm_sequential`, `test_remote_llm_parallel` |
| S4-08 | Implement `revolver.core.run` — `_post_run_evaluation()`: evaluate rank-1 program on training instances (FR-RUN-019); inline implementation using `evaluator_runner` from Sprint 002; stores results in `eval_metadata` and `eval_instances` tables; refactored to use `core.eval.evaluate_solution()` in Sprint 005 | domain | S4-07 | [ ] | Unit test: post-run eval creates eval_metadata row for rank-1 solution; `test_wallclock_recorded`, `test_cost_estimation` |
| S4-09 | Implement `revolver.core.run` — `resume_run()`: creates new run with `resumed_from=<parent_id>`, copies checkpoint and wrapper evaluator; `get_run_status()`, `list_runs()`, `get_run_info()` | domain | S4-07 | [ ] | Unit tests: `test_resume_creates_new_run`, `test_resume_copies_wrapper`, `test_lock_file_management`; list and info queries work |
| S4-10 | Implement `revolver.cli.run` — 5 Typer commands: default (`run`), `status`, `resume`, `list`, `info`; `--version`, `--llm`, `--dataset`, `--alias`, `--dry-run`, `--iterations` options; progress display on stderr | cli | S4-07, S4-08, S4-09 | [ ] | CliRunner tests for all 5 commands; exit 1 on unknown LLM; exit 2 on integrity failure; `--dry-run` no side effects |
| S4-11 | Write L2 integration tests for `run` (13 scenarios from val-integration-tests §2.5) | test | S4-10 | [ ] | All 13 run scenarios pass |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md §2.5` that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `run` | Valid config, mocked OpenEvolve — run dir, DB entries, lineage, env vars | `test_run_validates_inputs` + `test_run_stores_programs_and_solution` | Planned |
| `run --alias` | Solution alias set on completion | `test_run_with_alias` | Planned |
| `run --dry-run` | Config displayed, no run launched | `test_dry_run_no_launch` | Planned |
| `run` | Unknown LLM name — exit code 1 | `test_run_validates_inputs` | Planned |
| `run` | Dataset integrity failure (tampered file) — exit code 2 | `test_run_integrity_check_fails` | Planned |
| `run` | Dataset split=eval — warning on stderr, run proceeds | `test_warns_non_train_split` | Planned |
| `run` | Dataset incompatible with version — warning on stderr | `test_warns_incompatible_dataset` | Planned |
| `run` | Completion with tokens — usage displayed, stored in DB | `test_run_displays_tokens` | Planned |
| `run` | LLM has pricing — estimated cost displayed | `test_cost_estimation` | Planned |
| `run` | Post-run eval on train set — rank-1 evaluated, results in DB | `test_run_evaluates_rank1_on_train` | Planned |
| `run list` | After 2 runs — both listed, filterable | `test_run_list_with_filters` | Planned |
| `run info` | Existing run — full details: lineage, tokens, solution, programs | `test_run_info_full_details` | Planned |
| `run resume` | Existing checkpoint — new run from parent, wrapper copied | `test_resume_creates_new_run` | Planned |

**Cumulative L2 tests passing: 52 / 52 (sprints 001+002+003+004)**

---

## Parallelization

### Dependency graph

```
Sprint 001-003 (project + llm + problem + dataset — all prerequisites)
  │
  ├──> S4-01 (infra: openevolve wrapper)
  │         ↓
  │    S4-03 (infra: wrapper evaluator generator)  ──────────────────┐
  │                                                                    │
  ├──> S4-02 (infra: token proxy) ─────────────────────────────────┐  │
  │                                                                  │  │
  ├──> S4-04 (models: run) ─────────────────────────────────────┐  │  │
  │                                                              │  │  │
  ├──> S4-05 (models: solution) ───────────────────────────────┤  │  │
  │                                                              │  │  │
  └──> S4-06 (infra: db/run+solution) ─────────────────────────┼──┼──┼──> S4-07 (domain: launch_run)
                                                                │  │  │         ↓
                                                                └──┘  └──  S4-08 (domain: post-run eval)
                                                                                ↓
                                                                      S4-09 (domain: resume, list, info)
                                                                                ↓
                                                                      S4-10 (cli: run commands)
                                                                                ↓
                                                                      S4-11 (test: L2 — 13 scenarios)
```

### Critical path
Sprint 003 → S4-01 → S4-03 → S4-07 → S4-08 → S4-09 → S4-10 → S4-11
Estimated sequential depth: 7 steps after prerequisites.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — OpenEvolve + wrapper generator | S4-01, S4-03 | Sprint 003 done | Agent 1 |
| B — Token proxy + models + DB | S4-02, S4-04, S4-05, S4-06 | Sprint 003 done | Agent 2 |
| C — Domain: launch_run + post-run eval | S4-07, S4-08 | Streams A+B done | Agent 1 |
| D — Domain: resume/list/info | S4-09 | S4-07 done | Agent 2 |
| E — CLI + tests | S4-10, S4-11 | S4-09 done | Agent 1 or 2 |

Peak parallelism: 2 agents simultaneously (Streams A and B after Sprint 003).

### Conflict risks
- `infra/db.py` — adds run + solution CRUD; most heavily expanded file in this sprint; consider splitting into `db/project_db.py` (project tables) and `db/global_db.py` (llms) if file becomes unmanageable
- `core/eval.py` — `_post_run_evaluation()` in S4-08 needs minimal inline eval; Sprint 005 will refactor to reuse `core.eval.evaluate_solution()`; coordinate the interface boundary now to minimize Sprint 005 rework
- `infra/evaluator_runner.py` — shared module from Sprint 002; no changes expected in Sprint 004
- `models/` — `run.py` and `solution.py` are new modules; no conflicts with existing models

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- 0 / 13 integration tests passing (this sprint)
- 0 / 52 total cumulative integration tests

### Demo-able features
- [ ] `revolver run --version v1.0 --llm claude --dataset train --alias my-solution` (mocked OpenEvolve)
- [ ] `revolver run --dry-run --version v1.0 --llm claude --dataset train` displays resolved config
- [ ] Run completion shows token usage and cost estimate
- [ ] `revolver run info run-20260313-120000` displays full lineage, programs, solution
- [ ] `revolver run list` shows completed runs with status and best score
- [ ] `revolver run resume --run run-20260313-120000` creates new run from checkpoint
- [ ] Post-run eval on training set automatically creates eval results

### Carry-over
- `core.run._post_run_evaluation()` refactored to use `core.eval.evaluate_solution()` in Sprint 005 (S5-08)
