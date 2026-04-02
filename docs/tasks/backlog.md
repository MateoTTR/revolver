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

### Sprint 006a — Demo v0.6.0 Feedback Fixes

| # | Task | Status | Sprint |
|---|---|---|---|
| 141 | F1-fix — `generate_eval_id(suffix)` + retry loop on `IntegrityError` (BLOCKING) | [x] | S6a — session 031, PR #68 |
| 142 | F4/F5-fix — Default `benchmark` + `benchmark results` to `combined_score` only, `--metric all` | [x] | S6a — session 031, PR #69 |
| 143 | F6-fix — Default `benchmark results --per-instance` to `combined_score` | [x] | S6a — session 031, PR #69 |
| 144 | F7-fix — Add `--all` flag, comma-separated `--solutions`, mutual exclusion guard | [x] | S6a — session 031, PR #69 |

### Sprint 006b — Demo v0.6.1 Feedback Fixes

| # | Task | Status | Sprint |
|---|---|---|---|
| 145 | F4b-fix — Add tip in `--metric all` help text for wide table handling | [x] | S6b — session 032, PR #71 |
| 146 | F8-fix — `benchmark delete` command with confirmation and `--force` | [x] | S6b — session 032, PR #71 |
| 147 | F9/F10-fix — Dynamic alias column width in list views (rich Table `no_wrap`) | [x] | S6b — session 032, PR #71 |
| 148 | Pull-timeout-fix — Override httpx timeout to `None` for `pull_model()` | [x] | S6b — session 032, PR #71 |

### Sprint 006c — LLM Config & Iteration Tracking

| # | Task | Status | Sprint |
|---|---|---|---|
| 149 | Add `max_tokens` and `timeout_s` fields to LLMEntry model + DB migration v4 | [x] | S6c — session 033, PR #73 |
| 150 | Add `--max-tokens` and `--timeout` CLI options to `llm add`, inject in `build_config()` | [x] | S6c — session 033, PR #73 |
| 151 | Add `valid_iterations` to run models + DB, parse OpenEvolve checkpoint `database.json` | [x] | S6c — session 033, PR #73 |
| 152 | Display iteration success rate in `run info` and `run list` | [x] | S6c — session 033, PR #73 |
| 153 | Update README.md to reflect v0.6.2 feature completeness | [x] | S6c — session 033, PR #72 |

### Sprint 007 — Doctor, Setup & Cross-Cutting Polish

| # | Task | Status | Sprint |
|---|---|---|---|
| 98 | Implement `core.doctor` — dependency health checks | [x] | S7 — session 034, PR #76 |
| 99 | Implement `core.setup` — assisted installation | [x] | S7 — session 034, PR #76 |
| 100 | Implement `cli.doctor` — Typer command with `--fix` | [x] | S7 — session 034, PR #76 |
| 101 | Implement `cli.setup` — Typer command with `--dry-run`, `--force` | [x] | S7 — session 034, PR #76 |
| 102 | Cross-cutting: audit `--json` output consistency on all commands | [x] | S7 — session 034, PR #77 |
| 103 | Cross-cutting: audit error handling (stderr + exit codes) | [x] | S7 — session 034, PR #77 |
| 104 | Cross-cutting: add progress indicators to long commands | [x] | S7 — session 034, PR #77 |
| 105 | Cross-cutting: add confirmation summaries to state-modifying commands | [x] | S7 — session 034, PR #77 |
| 106 | Implement tab completion for bash/zsh | [x] | S7 — session 034, PR #77 |
| 107 | Write L2 integration tests for `doctor` and `setup` (8 scenarios) | [x] | S7 — session 034, PR #79 |
| 108 | Write L2 cross-cutting integration tests (6 scenarios) | [x] | S7 — session 034, PR #79 |
| 109 | Full regression: run all ~80 L2 integration tests (4+21+14+13+19+9+14 = 94 scenarios) | [x] | S7 — session 034, PR #79 |

### Sprint 007a — Post-Demo Fixes (v0.7.1)

| # | Task | Status | Sprint |
|---|---|---|---|
| 154 | Fix `--json`/`--verbose`/`--quiet` flag propagation to subcommands (GlobalOptionGroup) | [x] | S7a — session 035, PR #81 |

### Sprint 008 — Reliability & Lifecycle Management (v0.8.0)

| # | Task | Status | Sprint |
|---|---|---|---|
| 155 | Fix `evaluator_loader.py`: accept `evaluate_instance()` as valid signature (B4) | [x] | S8 — session 037, PR #86 |
| 156 | Fix `resolve_api_keys()`: convert missing-key warning to fatal `ValidationError` (F1) | [x] | S8 — session 037, PR #88 |
| 157 | Add "Running post-run evaluation..." message to `cli/run.py` (P3) | [x] | S8 — session 037, PR #88 |
| 158 | Propagate `timeout_per_instance` into `_WRAPPER_TEMPLATE` in `core/run.py` (B3) | [x] | S8 — session 037, PR #87 |
| 159 | ~~OE watchdog timeout~~ → **Upstream issue**: file issue on OpenEvolve for `ProcessPoolExecutor.shutdown(wait=True)` hang (B1). Repro script at `revolver-demos/tsp/demos/benchmark-multimodel/repro-b1-hang.py` | [~] | S8 — upstream |
| 160 | Add `--force`/`--yes` flag to `revolver llm remove` (FR4) | [x] | S8 — session 037, PR #89 |
| 161 | Add `--force`/`--yes` flag to `revolver dataset remove` (FR4) | [x] | S8 — session 037, PR #89 |
| 162 | DB migration v5: `ON DELETE CASCADE` on FK constraints (FR5) | [x] | S8 — session 037, PR #91 |
| 163 | `infra.db` helpers: `delete_run()`, `count_evals_for_run()` | [x] | S8 — session 037, PR #93 |
| 164 | `core.run.delete_run()` domain function | [x] | S8 — session 037, PR #93 |
| 165 | `cli.run.run_delete` command: `revolver run delete <id> [--force]` (FR1) | [x] | S8 — session 037, PR #93 |
| 166 | Write L2 integration tests for Sprint 008 features | [x] | S8 — session 037, included in PRs |

### Sprint 008a — Scriptability & UX Polish (v0.8.1)

| # | Task | Status | Sprint |
|---|---|---|---|
| 167 | `infra.db.update_llm()` SQL helper (FR6) | [x] | S8a — session 038, PR #104 |
| 168 | `core.llm.update_llm()` domain function (FR6) | [x] | S8a — session 038, PR #104 |
| 169 | `cli.llm.llm_update` command: `revolver llm update <name> [--max-tokens N] [--timeout N]` (FR6) | [x] | S8a — session 038, PR #104 |
| 170 | `core.run.delete_all_runs()` domain function (FR2) | [x] | S8a — session 038, PR #99 |
| 171 | Add `--all` flag to `revolver run delete` (FR2) | [x] | S8a — session 038, PR #99 |
| 172 | `infra.db` helpers: `delete_problem_version()`, `count_runs_for_version()` (FR3) | [x] | S8a — session 038, PR #105 |
| 173 | `core.problem.delete_version()` domain function with dependency check (FR3) | [x] | S8a — session 038, PR #105 |
| 174 | `cli.problem.problem_version_delete` command: `revolver problem version delete <tag> [--force]` (FR3) | [x] | S8a — session 038, PR #105 |
| 175 | Real-time run progress: stream OE output line-by-line in `cli/run.py` (FR7) | [x] | S8a — session 038, PR #113 |
| 176 | Smart default for `--version` in `revolver run` (P4) | [x] | S8a — session 038, PR #112 |
| 177 | Smart default for `--dataset` in `revolver run` (P5) | [x] | S8a — session 038, PR #112 |
| 178 | Add `--no-templates` flag to `revolver project init` (P2) | [x] | S8a — session 038, PR #103 |
| 179 | Fix misleading `--format csv` tip in `benchmark results --help` (P6) | [x] | S8a — session 038, PR #108 |
| 180 | Clarify `-s local` vs `--provider ollama` in `llm add --help` (P7) | [x] | S8a — session 038, PR #108 |
| 182 | Update spec-llm: `--source local` (not `ollama`), document `--max-tokens`/`--timeout` (C1, C2) | [x] | S8a — session 038, PR #114 |
| 183 | Update spec-dataset: positional `NAME`, align `--split`/`--compatible-with` required/optional (C4-C6) | [x] | S8a — session 038, PR #114 |
| 184 | Update spec-benchmark (add `delete`), spec index (add `list`/`delete`), spec-project (`name` required), remove `--sort` from spec-solution/spec-run (W5-W6, W9-W11) | [x] | S8a — session 038, PR #114 |
| 186 | Fix conops.md §5.1: `--source huggingface` → `--source local`, align workflow with implementation | [x] | S8a — session 038, PR #114 |
| 187 | Update architecture.md §3 package tree: add `delete` to run.py and solution.py comments | [x] | S8a — session 038, PR #114 |
| 188 | Update README.md: fix features list, sprint table, test count, remove "Planned" doctor/setup | [x] | S8a — session 038, PR #115 |
| 189 | Rewrite user-story-e2e.md: fix CLI syntax (`--source local`, positional `name`), update outputs | [x] | S8a — session 038, PR #115 |
| 190 | Refactor `cli/eval.py`: route re-eval check through `core.eval` instead of direct `infra.db` calls (F7) | [x] | S8a — session 038, PR #111 |
| 191 | Update traceability matrix: add `run delete`/`benchmark delete` entries + update 199 "Planned" statuses | [x] | S8a — session 038, PR #116 |
| 185 | Write L2 integration tests for Sprint 008a features | [x] | S8a — session 038, included in PRs |

### Sprint 009 — Solution UX + Config fluide + Run robustness

| # | Task | Status | Sprint |
|---|---|---|---|
| 192 | `core.solution.show_solution(id_or_alias)` — read program file, return source code as string (Bloc A1) | [x] | S9 — session 040, PR #124 |
| 193 | `core.solution.diff_solutions(a, b)` — unified diff via `difflib.unified_diff()` (Bloc A3) | [x] | S9 — session 040, PR #124 |
| 194 | `cli.solution.solution_show` — `revolver solution show <alias>`, `--json` support (Bloc A1) | [x] | S9 — session 040, PR #124 |
| 195 | `cli.solution.solution_export` — `revolver solution export <alias> [-o <path>]`, default `./<alias>.py` (Bloc A2) | [x] | S9 — session 040, PR #124 |
| 196 | `cli.solution.solution_diff` — `revolver solution diff <a> <b>`, Revolver exit codes (Bloc A3) | [x] | S9 — session 040, PR #124 |
| 197 | `core.solution.extract_solution()` — add `force=True` param (delete existing), hardcode `rank=1` in CLI (Bloc B2) | [x] | S9 — session 040, PR #122 |
| 198 | `cli.solution.solution_extract` — remove `--rank` flag, add `--force` flag (Bloc B2) | [x] | S9 — session 040, PR #122 |
| 199 | `core.run.launch_run()` — wrap OE call in try/except, mark `failed`/`interrupted` in DB (Bloc B1) | [x] | S9 — session 040, PR #130 |
| 200 | Workspace detection guard — centralized in `cli_error_boundary()` + explicit error message (Bloc B3) | [x] | S9 — session 040, PR #123 |
| 201 | `infra.openevolve.build_config()` — add `temperature` parameter, inject into `config["llm"]["temperature"]` (Bloc C1) | [x] | S9 — session 040, PR #133 |
| 202 | `infra.openevolve.build_config()` — add `parallel` parameter, inject into `config["evaluator"]["parallel_evaluations"]` (Bloc C2) | [x] | S9 — session 040, PR #133 |
| 203 | `cli.run` — add `--temperature FLOAT` and `--parallel INT` flags, pass to `build_config()` (Bloc C1+C2) | [x] | S9 — session 040, PR #133 |
| 204 | `infra.openevolve._parse_value()` — JSON array/object support via `json.loads()` (Bloc C3) | [x] | S9 — session 040, PR #128 |
| 205 | `models.llm.LLMEntry` — add `temperature` field; DB migration v6; update `insert_llm`, `get_llm`, `update_llm` (Bloc C4) | [x] | S9 — session 040, PR #121 |
| 206 | `core.llm` + `infra.openevolve.build_config()` — inject `llm.temperature` into OE config, CLI `--temperature` overrides (Bloc C4) | [x] | S9 — session 040, PR #121 |
| 207 | `cli.llm` — add `--temperature` to `llm add` and `llm update`; display in `llm list` (Bloc C4) | [x] | S9 — session 040, PR #121 |
| 208 | Write L2 integration tests for Sprint 009 features (~50 new tests) | [x] | S9 — session 040, included in PRs |
| 209 | New guide `docs/guides/tuning-oe-config.md` — MAP-Elites, islands, parallel_evaluations, iteration profiles, multi-objective (Bloc D1) | [x] | S9 — session 040, PR #131 |
| 210 | Update `docs/guides/initial-program-structure.md` — beamforming learnings, baseline calibration, scipy guidance (Bloc D2) | [x] | S9 — session 040, PR #132 |

### Sprint 009a — Delta bugfix: Resume, Config validation, UX polish (v0.9.1)

| # | Task | Status | Sprint |
|---|---|---|---|
| 211 | Fix checkpoint path resolution in `resume_run()` — search `oe-output/checkpoints/checkpoint_N/` | [x] | S9a — session 042, PR #139 |
| 212 | Checkpoint interval guard in `build_config()` — warn + override when interval > iterations | [x] | S9a — session 042, PR #139 |
| 213 | New `validate_oe_config()` — dacite strict parse, detect misplaced config keys | [x] | S9a — session 042, PR #141 |
| 214 | Call validation at `problem version` (conditional import, skip if OE absent) | [x] | S9a — session 042, PR #141 |
| 215 | Add `--iterations`, `--temperature`, `--parallel` flags to `run resume` CLI | [x] | S9a — session 042, PR #142 |
| 216 | Pass `temperature` and `parallel` through `resume_run()` to `build_config()` | [x] | S9a — session 042, PR #142 |
| 217 | Dry-run shows resolved OE config (iterations, checkpoint_interval, num_islands, etc.) | [x] | S9a — session 042, PR #140 |
| 218 | Fix tuning guide: all examples use `database:` namespace | [x] | S9a — session 042, PR #143 |
| 219 | L2 integration tests for Sprint 009a (11 new tests) | [x] | S9a — session 042, PR #143 |

### Sprint 010 — Resume, Robustness & UX (v0.10.0)

| # | Task | Status | Sprint |
|---|---|---|---|
| 220 | `validate_oe_config()` — filter `initial_program`, `num_generations`, `timeout_per_instance`; deprecation notice for `num_generations` | [x] | S10 — session 043, PR #147 |
| 221 | `infra.db.update_llm()` — add `model: str \| None` parameter, update SQL | [x] | S10 — session 043, PR #148 |
| 222 | `core.llm.update_llm()` — add `model` parameter, propagate to db | [x] | S10 — session 043, PR #148 |
| 223 | `cli.llm.llm_update` — add `--model TEXT` option | [x] | S10 — session 043, PR #148 |
| 224 | `core.run.resume_run()` — add `llm_name` parameter, resolve new LLM from global DB | [x] | S10 — session 043, PR #151 |
| 225 | `cli.run.run_resume` — add `--llm TEXT` option | [x] | S10 — session 043, PR #151 |
| 226 | `core.run.resume_run()` — add `config_overrides` parameter, apply via `_parse_config_overrides()` | [x] | S10 — session 043, PR #151 |
| 227 | `cli.run.run_resume` — add `--config-override TEXT` option (multi-value) | [x] | S10 — session 043, PR #151 |
| 228 | `infra.openevolve.build_config()` — add `rewrite_mode: bool = False`, inject `diff_based_evolution=false` + `max_code_length=50000` | [x] | S10 — session 043, PR #153 |
| 229 | `core.run.launch_run()` + `resume_run()` — add `rewrite_mode` parameter, pass to `build_config()` | [x] | S10 — session 043, PR #153 |
| 230 | `cli.run.run_start` + `run_resume` — add `--rewrite-mode` flag | [x] | S10 — session 043, PR #153 |
| 231 | `core.run.launch_run()` — after OE: `valid_iterations==0` → status `failed`; `<10%` → `completed_with_errors` | [x] | S10 — session 043, PR #149 |
| 232 | `core.run.detect_zombie_runs()` — check PID alive, mark orphaned runs `interrupted` | [x] | S10 — session 043, PR #155 |
| 233 | `cli.run.run_list` — auto-call `detect_zombie_runs()`, display cleanup warning | [x] | S10 — session 043, PR #155 |
| 234 | `cli.run.run_cleanup` — new `run cleanup` command with `--force` | [x] | S10 — session 043, PR #155 |
| 235 | `core.run.get_population()` + `cli.run.run_population` — new `run population <run_id>` command, parse OE checkpoint programs | [x] | S10 — session 043, PR #157 |
| 236 | Update `docs/guides/tuning-oe-config.md` — full-rewrite mode section + Gemini model compatibility table | [x] | S10 — session 043, PR #159 |
| 237 | Update `docs/guides/initial-program-structure.md` — problem.md enrichment section with POC evidence | [x] | S10 — session 043, PR #159 |
| 238 | L2 integration tests for Sprint 010 (~56 new tests across PRs A-G) | [x] | S10 — session 043, included in PRs |

### Sprint 011 — Multi-Model Ensemble Support (v0.11.0)

| # | Task | Status | Sprint |
|---|---|---|---|
| 239 | DB migration v8: `ensembles` + `ensemble_members` tables (global DB); `llm_type` + `llm_snapshot` columns on `runs` (project DB) | [x] | S11 — session 044, PR #161 |
| 240 | `infra.db` helpers: ensemble CRUD (6 functions) | [x] | S11 — session 044, PR #161 |
| 241 | `models.llm` — `EnsembleMember` and `EnsembleEntry` Pydantic models | [x] | S11 — session 044, PR #161 |
| 242 | `core.llm` — `create_ensemble()`, `add_member()`, `remove_ensemble()`, `list_ensembles()`, `get_ensemble_info()` with weight sum warning | [x] | S11 — session 044, PR #164 |
| 243 | `cli.llm` — `ensemble` sub-app: `create`, `add`, `list`, `info`, `remove` with `--json` support | [x] | S11 — session 044, PR #164 |
| 244 | `core.llm.resolve_llm_or_ensemble()` — unified lookup returning `LLMEntry \| EnsembleEntry` | [x] | S11 — session 044, PR #165 |
| 245 | `infra.openevolve.build_config()` — emit `llm.models` array with OE field names (`name`, `api_base`); resolve `api_key_env` per member | [x] | S11 — session 044, PR #165 |
| 246 | `core.run.launch_run()` + `resume_run()` — resolve via ensemble; store `llm_type` and `llm_snapshot` JSON | [x] | S11 — session 044, PR #165 |
| 247 | `cli.run` — `--llm` resolves ensemble; `run info`/`run list` show ensemble indicator | [x] | S11 — session 044, PR #165 |
| 248 | L2 integration tests for Sprint 011 (17 scenarios covered across PRs A-D) | [x] | S11 — session 044, PR #167 |
| 249 | Update `docs/guides/tuning-oe-config.md` — ensemble strategies section | [x] | S11 — session 044, PR #167 |
| 251 | Documentation audit cascade: spec-reviewer (18F+7W) → validation-reviewer (3F+1W) → doc-reviewer (3F+3W) — all fixed | [x] | S11 — session 044, PR #169 |
| 252 | (POC finding) OE field mapping: `name` (not `model`), `api_base` (not `base_url`) — covered by task 245 | [~] | S11 — covered by 245 |

### Sprint 012 — Demo Feedback: UX & Reliability (v0.12.0)

| # | Task | Status | Sprint |
|---|---|---|---|
| 253 | Simplify `_determine_run_status()`: remove 10% threshold, binary valid/failed logic | [x] | S12 — session 045, PR #178 |
| 254 | Fix exception handlers in `launch_run()`/`resume_run()`: count valid programs before marking status | [x] | S12 — session 045, PR #178 |
| 255 | Extend `ResolvedOEConfig` with `diff_based_evolution`, `max_code_length`, `config_overrides`, `llm_models` | [x] | S12 — session 045, PR #176 |
| 256 | Update `_extract_resolved_config()` + dry-run CLI display for complete config | [x] | S12 — session 045, PR #176 |
| 257 | Change ensemble indicator from suffix `(E)` to prefix `(E)` in `run list` | [x] | S12 — session 045, PR #179 |
| 258 | Add `resume_chain` and `resumed_from` to `solution info` output | [x] | S12 — session 045, PR #179 |
| 259 | Populate `RunStatus.iterations_completed` + `best_score` from checkpoint in `get_run_status()` | [x] | S12 — session 045, PR #177 |
| 260 | Add `read_checkpoint_best_score()` helper to `infra.openevolve` | [x] | S12 — session 045, PR #177 |
| 261 | Read `metadata.json` `island_feature_maps` in `parse_population()`, add `cell_indices` + `island` per program | [x] | S12 — session 045, PR #175 |
| 262 | L2 integration tests for Sprint 012 (~30 new tests across PRs A-E) | [x] | S12 — session 045, included in PRs |

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
