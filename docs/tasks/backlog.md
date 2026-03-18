# Revolver — Task Backlog

## Phase 1 — Cadrage

| # | Task | Status | Session |
|---|---|---|---|
| 1 | ConOps — Initial brainstorm and draft | [x] | 001 |
| 2 | ConOps — User review and refinements | [x] | 002 |
| 3 | Functional specifications — Draft | [x] | 003 |
| 4 | Functional specifications — Review | [x] | 004 |

## Phase 2 — Architecture

| # | Task | Status | Session |
|---|---|---|---|
| 5 | ADR-001 — Ollama as local LLM backend (decision + tradeoffs from POC) | [x] | 004 |
| 6 | ADR-002 — Programming language (Python >= 3.11) | [x] | 004 |
| 7 | ADR-003 — CLI framework (Typer) | [x] | 005 |
| 8 | Design `revolver llm` subcommands based on Ollama API mapping | [x] | 006 |
| 9 | Architecture overview — Draft | [x] | 005 |
| 10 | Data model — Detailed design | [x] | 005 |
| 18 | ADR-004 — SQLite as structured storage | [x] | 006 |
| 19 | ADR-005 — Pydantic v2 for data models | [x] | 006 |
| 20 | DES-003 — `revolver problem` testing & versioning design | [x] | 006 |
| 21 | DES-004 — `revolver dataset` registration & integrity design | [x] | 006 |
| 22 | Restructure architecture docs (DES-NNN convention) | [x] | 006 |
| 23 | Update spec-dataset with `dataset remove` command | [x] | 006 |
| 24 | DES-005 — `revolver run` design (unblocked by ADR-006) | [x] | 008 |
| 25 | DES-006 — `revolver eval` design (unblocked by ADR-006) | [x] | 008 |
| 26 | ~~Implement wrapper evaluator generator~~ → moved to Phase 5 (Sprint 004, task S4-03) | — | |
| 27 | Update ConOps §4.1 directory structure for DD-07 (top-N → separate solution dirs) | [x] | 010 |
| 28 | Review remaining spec-reviewer WARNs (ER diagram, benchmark JSON rank/run_id) | [x] | 010 |
| 29 | Refactor: introduce Run entity + Solution as reference (per refactor-run-solution.md) | [x] | 010 |
| 30 | DES-007 — `revolver benchmark` design (after run/solution refactor) | [x] | 011 |
| 31 | Review DES-005/006 decisions (D-005-a..h, D-006-a..f) into updated docs | [x] | 010 |
| 32 | Integrate `problem.md` feature into ConOps, spec-problem, DES-003, DES-005 | [x] | 012 |
| 33 | Refactor top-N → extract on demand (spec-run, DES-005, spec-solution, DES-001, ConOps) | [x] | 013 |
| 34 | Token/cost tracking — lightweight requirement + design integration | [x] | 014 |

## Phase 3 — POCs

| # | Task | Status | Session |
|---|---|---|---|
| 11 | POC — Local LLM deployment and inference | [x] | 003 |
| 12 | POC — OpenEvolve integration with instance injection | [x] | 007 |
| 13 | POC — OpenEvolve + Claude API | [x] | 012 |
| 14 | POC — Code generation quality with OpenEvolve + local LLM (quantization impact) | [~] Covered by POC #11/12/13 | |
| 15 | POC — End-to-end OpenEvolve + Ollama endpoint integration | [~] Covered by POC #11/12/13 | |

## Phase 4 — Validation

| # | Task | Status | Session |
|---|---|---|---|
| 16 | Validation strategy and test plan | [x] | 015 |
| 17 | Traceability matrix (specs → design → tests) | [x] | 015 |

## Phase 5 — Implementation

### Sprint 001 — Foundation: Project Scaffolding, DB, Shared Infrastructure

| # | Task | Status | Sprint |
|---|---|---|---|
| 35 | Create `pyproject.toml`, `src/revolver/` layout, pip-installable package, CI pipeline | [x] | S1 — session 016, PR #1 |
| 36 | Implement root Typer app with `--json`, `--verbose`, `--quiet` callback | [x] | S1 — session 017, PR #3 |
| 37 | Implement `infra.db` — SQLite connection, WAL, schema creation (DES-001), migration | [x] | S1 — session 017, PR #2 |
| 38 | Implement `infra.hashing` — `file_hash()`, `tree_hash()`, `global_hash()`, `compute_snapshot_hash()` | [x] | S1 — session 017, PR #2 |
| 39 | Implement `infra.store` — `.revolver/` management, `find_project_root()`, `write_manifest()` | [x] | S1 — session 017, PR #2 |
| 40 | Implement `infra.config` — 5-level config hierarchy resolution | [x] | S1 — session 017, PR #2 |
| 41 | Implement `infra.output` — `render()` for human tables (rich) and JSON | [x] | S1 — session 017, PR #2 |
| 42 | Implement `models.project` — `ProjectConfig` Pydantic model | [x] | S1 — session 017, PR #2 |
| 43 | Implement `core.project` — `init_project()` | [x] | S1 — session 017, PR #4 |
| 44 | Implement `cli.project` — `project init` Typer command | [x] | S1 — session 017, PR #4 |
| 45 | Implement typed exceptions and CLI error mapping (exit codes 0-4) | [x] | S1 — session 017, PR #3 |
| 46 | Create test fixtures (`tests/fixtures/`) | [x] | S1 — session 017, PR #2 |
| 47 | Write L2 integration tests for `project init` (4 scenarios) | [x] | S1 — session 017, PR #4 |
| 48 | Write L1 unit tests for infra modules (db, hashing, store, config, output) | [x] | S1 — session 017, PR #2 |

### Sprint 002 — LLM Registration & Problem Versioning

| # | Task | Status | Sprint |
|---|---|---|---|
| 49 | Implement `infra.ollama` — `OllamaClient` (DES-002 §3) | [x] | S2 — session 018, PR #5 |
| 50 | Implement `infra.gpu` — `get_gpu_info()` via nvidia-smi (DES-002 §4) | [x] | S2 — session 018, PR #5 |
| 51 | Implement `models.llm` — LLM Pydantic models (DES-002) | [x] | S2 — session 018, PR #5 |
| 52 | Add LLM CRUD queries to `infra.db` (global DB) | [x] | S2 — session 018, PR #5 |
| 53 | Implement `core.llm` — 6 orchestration functions (DES-002 §5) | [x] | S2 — session 019, PR #9 |
| 54 | Implement `cli.llm` — 6 Typer commands (DES-002 §6) | [x] | S2 — session 019, PR #9 |
| 55 | Implement `infra.evaluator_loader` — dynamic module loading (DES-003 §7) | [x] | S2 — session 018, PR #6 |
| 56 | Implement `infra.evaluator_runner` — subprocess evaluator execution with timeout (DES-006 DD-05) | [x] | S2 — session 018, PR #6 |
| 57 | Implement `models.problem` — Problem Pydantic models (DES-003 §3) | [x] | S2 — session 018, PR #6 |
| 58 | Add problem CRUD queries to `infra.db` | [x] | S2 — session 018, PR #6 |
| 59 | Implement `core.problem` — test, version, list (DES-003 §5) | [x] | S2 — session 019, PR #10 |
| 60 | Implement `cli.problem` — 3 Typer commands (DES-003 §6) | [x] | S2 — session 019, PR #10 |
| 61 | Write L2 integration tests for `llm` (11 scenarios) | [x] | S2 — session 019, PR #9 |
| 62 | Write L2 integration tests for `problem` (10 scenarios) | [x] | S2 — session 019, PR #10 |

### Sprint 003 — Dataset Registration & Integrity

| # | Task | Status | Sprint |
|---|---|---|---|
| 63 | Implement `models.dataset` — Dataset Pydantic models (DES-004 §5) | [x] | S3 — session 020, PR #13 |
| 64 | Add dataset CRUD queries to `infra.db` (DES-004) | [x] | S3 — session 020, PR #13 |
| 65 | Add dataset manifest ops to `infra.store` (DES-004) | [x] | S3 — session 020, PR #13 |
| 66 | Implement `core.dataset` — register, update, remove, list, info, verify (DES-004 §7) | [x] | S3 — session 020, PR #14 |
| 67 | Implement `cli.dataset` — 5 Typer commands (DES-004 §8) | [x] | S3 — session 020, PR #14 |
| 68 | Write L2 integration tests for `dataset` (14 scenarios) | [x] | S3 — session 020, PR #14 |

### Sprint 004 — Run Orchestration (OpenEvolve Integration)

| # | Task | Status | Sprint |
|---|---|---|---|
| 69 | Implement `infra.openevolve` — OpenEvolve wrapper (DES-005 §4-6) | [x] | S4 — session 022, PR #20 |
| 70 | Implement `infra.token_proxy` — HTTP proxy for token tracking (DES-005 DD-14) | [x] | S4 — session 022, PR #20 |
| 26 | Implement wrapper evaluator generator (DES-005 §3) | [x] | S4 — session 022, PR #20 |
| 71 | Implement `models.run` — Run Pydantic models (DES-005) | [x] | S4 — session 022, PR #19 |
| 72 | Implement `models.solution` — Solution model | [x] | S4 — session 022, PR #19 |
| 73 | Add run/solution CRUD queries to `infra.db` | [x] | S4 — session 022, PR #19 |
| 74 | Implement `core.run` — `launch_run()`: full orchestration (DES-005 §4-7) | [x] | S4 — session 023, PR #22 |
| 75 | Implement `core.run` — `_post_run_evaluation()` (FR-RUN-019) | [x] | S4 — session 023, PR #22 |
| 76 | Implement `core.run` — resume, status, list, info | [x] | S4 — session 023, PR #22 |
| 77 | Implement `cli.run` — 5 Typer commands | [x] | S4 — session 024, PR #24 |
| 78 | Write L2 integration tests for `run` (13 scenarios) | [x] | S4 — session 024, PR #24 |

### Sprint 004a — Demo Feedback Fixes (v0.4.1 → v0.4.4)

| # | Task | Status | Sprint |
|---|---|---|---|
| 111 | Fix dict→Config conversion in `OpenEvolveRunner._init_controller()` (CRITICAL) | [x] | S4a — session 025, PR #25 |
| 112 | Fix `dry-run iterations=0` fallback + `generation_time_s` null default | [x] | S4a — session 025, PR #25 |
| 113 | Add L2-OE integration tests (real OpenEvolve) + fix config field mapping | [x] | S4a — session 025/025b, PR #26 |
| 114 | Strip Revolver-specific keys in `build_config()` + map `num_generations` | [x] | S4a — session 025b, PR #27 |
| 115 | Inject `api_key` for local LLMs, force `cascade_evaluation: false`, extract `best_score` | [x] | S4a — session 026, PR #31 |
| 116 | Fix program collection, post-run eval `evaluate_instance()` mode, wrapper error logging | [x] | S4a — session 026, PR #32 |
| 117 | Add pre-flight evaluation check before OpenEvolve launch | [x] | S4a — session 026, PR #33 |
| 118 | Fix evaluator template: correct `evaluate_instance` signature | [x] | S4a — session 026, PR #35 |
| 119 | Update DES-005 + specs/validation docs for v0.4.4 features | [x] | S4a — session 026, PR #36/#37 |

### Sprint 004b — Proxy Robustness & UX Fixes (v0.4.5)

| # | Task | Status | Sprint |
|---|---|---|---|
| 123 | FB-01 — Forward upstream HTTP status code + body in proxy (NF7) | [x] | S4b — session 027, PR #42 |
| 124 | FB-02 — Detect Google provider in `build_config()`, set `random_seed=None` (NF5) | [x] | S4b — session 027, PR #42 |
| 125 | FB-03 — Forward `Retry-After` header from upstream responses (NF8 partial) | [x] | S4b — session 027, PR #42 |
| 126 | FB-04 — Optional proxy-level backoff on 429 with Retry-After (stretch) | [x] | S4b — session 027, PR #42 |
| 127 | FB-05 — Add `null`/`none` → `None` support in `_parse_value()` (NF6) | [x] | S4b — session 027, PR #43 |
| 128 | FB-06 — Suppress false-positive dual-function warning on generated wrapper (NF1) | [x] | S4b — session 027, PR #43 |
| 129 | FB-07 — Include alias (rank-1 solution) in `run list` and `run list --json` (NF2) | [x] | S4b — session 027, PR #43 |
| 130 | FB-08 — `problem version` duplicate content → friendly error message (bonus) | [x] | S4b — already implemented (prior sprint) |
| 131 | FB-09 — Write guide on initial program structure best practices (NF4) | [x] | S4b — session 027, PR #41 |

### Sprint 005 — Solution Management & Evaluation Loop

| # | Task | Status | Sprint |
|---|---|---|---|
| 79 | Implement `models.eval` — Eval Pydantic models (DES-006 §6) | [x] | S5 — session 028, PR #47 |
| 80 | Add eval CRUD queries to `infra.db` | [x] | S5 — session 028, PR #47 |
| 81 | Add solution extended queries to `infra.db` (alias, run-based) | [x] | S5 — session 028, PR #46 |
| 82 | Implement `core.eval` — `evaluate_solution()`, `get_eval_results()`, `compute_aggregates()` (DES-006 §8) | [x] | S5 — session 028, PR #51 |
| 83 | Implement `core.eval` — legacy evaluator support + global aggregation (D-006-g) | [x] | S5 — session 028, PR #51 |
| 84 | Implement `core.eval` — re-evaluation handling with confirmation (D-006-a) | [x] | S5 — session 028, PR #51 |
| 85 | Implement `core.solution` — list, info, alias, extract | [x] | S5 — session 028, PR #50 |
| 86 | Refactor `core.run._post_run_evaluation()` to reuse `core.eval` | [~] | S5 — session 028, PR #50 (prepared, TODO for final wiring) |
| 87 | Implement `cli.solution` — 4 Typer commands | [x] | S5 — session 028, PR #50 |
| 88 | Implement `cli.eval` — 2 Typer commands (DES-006 §9) | [x] | S5 — session 028, PR #51 |
| 89 | Write L2 integration tests for `solution` (9 scenarios) | [x] | S5 — session 028, PR #50 |
| 90 | Write L2 integration tests for `eval` (10 scenarios) | [x] | S5 — session 028, PR #51 |

### Sprint 005a — Demo v0.5.0 Feedback Fixes

| # | Task | Status | Sprint |
|---|---|---|---|
| 136 | F1-fix — Store `api_key_env` in `build_config()` + `resolve_api_keys()` helper (SECURITY) | [x] | S5a — session 029, PR #56 |
| 137 | F2-fix — Set top-level `random_seed=None` for Google providers (BLOCKING) | [x] | S5a — session 029, PR #56 |
| 138 | F3-fix — `completed_with_errors` status + `run-error.log` + schema migration v2 (MAJOR) | [x] | S5a — session 029, PR #57 |
| 139 | F3-extract — Relax `extract_solution()` for `completed_with_errors` runs | [x] | S5a — session 029, PR #57 |
| 140 | F4-delete — `solution delete` with confirmation, `--force`, cascade eval (MEDIUM) | [x] | S5a — session 029, PR #55 |

### Sprint 006 — Benchmark: Multi-Solution Comparison & Export

| # | Task | Status | Sprint |
|---|---|---|---|
| 91 | Implement `models.benchmark` — Benchmark Pydantic models (DES-007 §7) | [x] | S6 — session 030, PR #60 |
| 92 | Add benchmark CRUD queries to `infra.db` (DES-007 §9) | [x] | S6 — session 030, PR #61 |
| 93 | Implement `core.benchmark` — `run_benchmark()` with eval reuse (DES-007 §2.1, §3) | [x] | S6 — session 030, PR #64 |
| 94 | Implement `core.benchmark` — `get_benchmark_results()` with per-instance comparison (DES-007 §2.2, §5) | [x] | S6 — session 030, PR #64 |
| 95 | Implement `core.benchmark` — `export_benchmark()` CSV/JSON + `list_benchmarks()` (DES-007 §2.3-4, §6) | [x] | S6 — session 030, PR #64 |
| 96 | Implement `cli.benchmark` — 4 Typer commands (DES-007 §11) | [x] | S6 — session 030, PR #65 |
| 97 | Write L2 integration tests for `benchmark` (9 scenarios) | [x] | S6 — session 030, PR #65 |

### Sprint 007 — Doctor, Setup & Cross-Cutting Polish

| # | Task | Status | Sprint |
|---|---|---|---|
| 98 | Implement `core.doctor` — dependency health checks | [ ] | S7 |
| 99 | Implement `core.setup` — assisted installation | [ ] | S7 |
| 100 | Implement `cli.doctor` — Typer command with `--fix` | [ ] | S7 |
| 101 | Implement `cli.setup` — Typer command with `--dry-run`, `--force` | [ ] | S7 |
| 102 | Cross-cutting: audit `--json` output consistency on all commands | [ ] | S7 |
| 103 | Cross-cutting: audit error handling (stderr + exit codes) | [ ] | S7 |
| 104 | Cross-cutting: add progress indicators to long commands | [ ] | S7 |
| 105 | Cross-cutting: add confirmation summaries to state-modifying commands | [ ] | S7 |
| 106 | Implement tab completion for bash/zsh | [ ] | S7 |
| 107 | Write L2 integration tests for `doctor` and `setup` (8 scenarios) | [ ] | S7 |
| 108 | Write L2 cross-cutting integration tests (6 scenarios) | [ ] | S7 |
| 109 | Full regression: run all ~80 L2 integration tests (4+21+14+13+19+9+14 = 94 scenarios) | [ ] | S7 |

### Unscheduled — Release Process

| # | Task | Status | Sprint |
|---|---|---|---|
| 110 | CI guard: version-tag consistency check on `v*` tag push (compare pyproject.toml version vs tag) | [ ] | TBD |

### Unscheduled — v2 Improvements

| # | Task | Status | Sprint |
|---|---|---|---|
| 120 | Gemini thinking mode auto-config: detect thinking-enabled models in `build_config()`, auto-set `reasoning_effort: "none"` and/or increase `max_tokens` to prevent silent token budget exhaustion. Root cause validated (session 029): thinking tokens consume `max_tokens` silently, not bavardage in response. | [ ] | TBD |
| 121 | ~~LLM response post-processing~~ — **Deprioritized**: thinking tokens are invisible in response content, proxy-level filtering would not help. Keep as low-priority defense-in-depth only. | [~] | — |
| 122 | `revolver problem test --wrapper` — validate OE wrapper evaluator interface before run | [ ] | TBD |
| 132 | Multi-language support: make program filename and extension configurable (`solver.cpp`, `main.rs`, etc.) instead of hardcoded `initial_program.py`. Propagate to OE `file_suffix`, snapshot, solution collection. | [ ] | TBD |
| 133 | Program support files: allow a `program_dir/` with auxiliary files (headers, local modules, data) copied alongside the program temp file during OE evaluation. Solves local `import`/`#include` breakage. | [ ] | TBD |
| 134 | Dependency traceability: optional `requirements.txt` (or `dependencies` section in `config.yaml`) versioned in problem snapshot for reproducibility. Documentation only — no auto-install. | [ ] | TBD |
| 135 | Document multi-language evaluator patterns: examples of `evaluate()` that compiles C++/Rust/Julia before scoring. Extend initial-program-structure guide. | [ ] | TBD |
