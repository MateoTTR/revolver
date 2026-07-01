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

### Hotfix (post-v0.12.0) — Typer/click dependency drift + CI conda runner

Not a sprint — a single hotfix bundled in one PR, tracked here for traceability. **Released as v0.12.1** (session 047, tag `v0.12.1` on `main`).

| # | Task | Status | Ref |
|---|---|---|---|
| 263 | Declare `click>=8` in `pyproject.toml` dependencies (direct import in `_global_options.py`, previously masked by Typer transitive dep; Typer 0.26.x dropped it) | [x] | Hotfix — PR #181 (#180) |
| 264 | Fix `_global_options.py` `parse_args` typing for Typer's vendored Click context (`ctx: Any`) — resolves 5 mypy override/arg-type errors | [x] | Hotfix — PR #181 (#180) |
| 265 | Refactor `ci.yml`: venv → ephemeral conda env per run (`mamba create -c conda-forge`), `actions/checkout@v5`, concurrency cancel-in-progress. Self-hosted runner provisioned (`revolver-runner` systemd user service + `revolver-ci` helper) | [x] | Hotfix — PR #181 (#180) |

### Investigation — Multi-backend support (OpenEvolve + ShinkaEvolve)

Goal: make Revolver target either OpenEvolve (default) or ShinkaEvolve as a pluggable evolution backend. Analyses done 2026-06-02: see [shinka-vs-openevolve.md](../analysis/shinka-vs-openevolve.md) (comparison) and [shinka-backend-impact.md](../analysis/shinka-backend-impact.md) (impact, incl. a draft `EvolutionBackend` interface §3.2). Direction: additive backend behind an adapter, OpenEvolve stays default; ShinkaEvolve dependency-isolated. Sequenced — do NOT write ADRs/specs before the spike.

The first impact analysis is strong but **bottom-up** (from `infra/`). The complement (267) must be **top-down** (from the CLI) and broaden beyond code architecture. Open questions raised in discussion, to fold into 267:
- **CLI workflow partition** — confirm which commands are engine-coupled (`run`/`resume`/`status`/`population`) vs engine-neutral (`eval`, `solution show/diff/export`, `benchmark`, `problem test` — they reuse the snapshot evaluator, not the engine). This sizes the whole refactor.
- **LLM registration model** — Revolver registers LLMs as-is (`llm`/`ensemble`: local Ollama + remote API, `api_key_env`, weighted ensemble) for an OpenAI-compatible world. ShinkaEvolve uses model-name strings + native per-provider SDKs + `local/<model>@<url>?api_key_env=` syntax + bandit ensemble (UCB/Thompson). Does Revolver's LLM registry need to evolve, and how does it map per backend?
- **Parameter/config surface** — the current surface is very OE-specific (`ResolvedOEConfig`, `--temperature`/`--parallel`/`--rewrite-mode`/`--config-override`, `config.yaml` shape). Decide the neutral subset vs per-backend extras.
- **Cross-engineering impact** — not just architecture: specs (FR/NFR), design (architecture + DES-005/006), and the validation plan (test strategy L1-L3, traceability matrix).

| # | Task | Status | Ref |
|---|---|---|---|
| 266 | **Phase 0 spike** — dependency cohabitation test: fresh conda env, `pip install` Revolver + `shinka-evolve`, observe conflicts (`httpx==0.27`, `hydra-core==1.3.2`, heavy stack). Decide the founding question: co-install (`revolver[shinka]` extra) vs isolated subprocess. This determines `launch()` shape, dep strategy, async/token handling. **DONE (session 047)** → co-install VIABLE (pip check clean, +75 deps), recommend opt-in `revolver[shinka]` extra + in-process programmatic launch. See [shinka-spike-266.md](../analysis/shinka-spike-266.md) | [x] | 047 |
| 267 | **Top-down complementary analysis** (post-spike) — walk each Revolver CLI command to (a) confirm the engine-coupled vs engine-neutral partition, (b) validate/finalize the draft `EvolutionBackend` interface against real command needs, (c) resolve the LLM-registration mapping and the parameter/config-surface questions above. Then extend to the **full engineering impact**: proposed changes to specs (FR/NFR), design (architecture + DES-005/006), and validation (strategy + traceability), plus a **preliminary incremental dev+validation sprint plan**. Output = preliminary material ready to feed the project agents. **DONE (session 047)** → only 4 commands engine-coupled (~82% CLI neutral); no LLM-registry schema change; neutral `ResolvedConfig`+`backend_extras`; refined interface (capabilities/resume/config_template); specs/design/validation impact + S13→S14→S15 sprint plan. See [shinka-topdown-267.md](../analysis/shinka-topdown-267.md) | [x] | 047 |
| 268 | **Formalize the plan via the project agents** — from 266/267, drive structuring with the existing agents: backend-abstraction **ADR(s)**, spec updates (→ spec-reviewer), design/architecture/DES-005/006 revisions, validation updates (→ validation-reviewer), sprint structuring (→ scrum-master), user-doc pass (→ doc-reviewer). Then phased implementation (P1 refactor no-behavior-change → P2 Shinka MVP → P3 parity). **IN PROGRESS (session 048, 2026-06-11)**: 3 open questions arbitrated (Q1 repro per-backend; Q2 **token-primary kept** — reverses #267, Shinka persists per-program tokens in `programs.sqlite`; Q3 `backend_extras` dict first) → **ADR-007 written (Accepted)** → specs updated (FR-RUN-047/048, NFR-024, conops v0.4) → design updated (DES-005 §14.1, DES-006 §1.3, DES-001 migration v9, architecture) → validation updated (L2-Shinka planned, traceability v0.4) → spec-reviewer (0 FAIL/5 WARN) + validation-reviewer (3 FAIL/5 WARN) findings fixed. Commits 528f5c1..f26069a. Sprint S13 planned → [sprint-013.md](../sprints/sprint-013.md) + tasks 269–282 below — **all implemented and merged** (session 048). Doc-reviewer pass folded into the v0.13.0 release checklist. **DONE** | [x] | 048 |

### Sprint 013 — Backend Abstraction Refactor (v0.13.0)

Per ADR-007 (P1 phase — zero behavior change). Plan: [sprint-013.md](../sprints/sprint-013.md). **Complete** — 4 PRs merged (session 048), 91 new tests, suite 1175 passed. **Released as v0.13.0** (tag on `main`, session 048).

| # | Task | Status | Sprint |
|---|---|---|---|
| 269 | `infra/backends/base.py` — `EvolutionBackend` protocol, `BackendCapabilities`, `BackendRunSpec`/`BackendRunResult`, `BackendUnavailableError`, `get_backend()` factory (S13-01) | [x] | S13 — session 048, PR #184 |
| 270 | `infra/backends/openevolve.py` — `OpenEvolveBackend` (move `infra/openevolve.py` behind the interface); re-export shim kept until S15 (S13-02) | [x] | S13 — session 048, PR #184 |
| 271 | `infra/backends/shinka.py` — registered stub: `is_available()=(False, install hint)`, capabilities per ADR-007, methods raise `BackendUnavailableError` (S13-03) | [x] | S13 — session 048, PR #184 |
| 272 | `models/run.py` — neutral `ResolvedConfig` + `backend_extras` replacing `ResolvedOEConfig` (S13-04) | [x] | S13 — session 048, PR #185 |
| 273 | `models/run.py` — `backend` field on `RunConfig`/`RunManifest`/`RunSummary`/`RunInfo` (S13-05) | [x] | S13 — session 048, PR #185 |
| 274 | `infra/db.py` — migration v9: `runs.backend TEXT NOT NULL DEFAULT 'openevolve'`; run queries updated (S13-06) | [x] | S13 — session 048, PR #185 |
| 275 | `core/run.py` — `launch_run()` backend-mediated (build/validate/wrapper/launch/proxy decision/token via `backend.*`); backend stored in record + manifest (S13-07) | [x] | S13 — session 048, PR #188 |
| 276 | `core/run.py` — `resume_run()` inherits parent backend (cross-backend rejected); `get_run_status()` active-path + `get_population()` via backend (S13-08) | [x] | S13 — session 048, PR #188 |
| 277 | `core/run.py` — `_extract_resolved_config()` → neutral `ResolvedConfig`, OE-only keys into `backend_extras` (S13-09) | [x] | S13 — session 048, PR #188 |
| 278 | `cli/run.py` — `--backend` option (default `openevolve`; unknown → exit 1; stub → exit 3 + install hint); backend-aware copy (S13-10) | [x] | S13 — session 048, PR #188 |
| 279 | `cli/run.py` — surface backend in `run info`/`run list`/dry-run (FR-RUN-047) (S13-11) | [x] | S13 — session 048, PR #188 |
| 280 | `core/doctor.py` per-backend `is_available()` loop (ShinkaEvolve informational) + `core/setup.py` install entries (S13-12) | [x] | S13 — session 048, PR #189 |
| 281 | `core/project.py` config template via `backend.config_template()` + `core/problem.py` validate dispatch via `backend.validate_config()` (S13-13) | [x] | S13 — session 048, PR #189 |
| 282 | L2 tests: backend default end-to-end, resume inheritance, unknown/not-installed errors, doctor informational + full regression zero-behavior-change (S13-14) | [x] | S13 — session 048, included in PRs #184/#185/#188/#189 |

### Sprint 014 — ShinkaEvolve MVP (v0.14.0)

Per ADR-007 (P2 phase — real `ShinkaBackend`, opt-in `revolver[shinka]` extra). Plan: [sprint-014.md](../sprints/sprint-014.md). R4 risk (wrapper correctness) front-loaded in PR-A; S13 carry-over seams absorbed in PR-B.

| # | Task | Status | Sprint |
|---|---|---|---|
| 283 | Fixture `programs.sqlite` factory (verified 0.0.7 schema: `metadata.api_costs` + nested `llm_result` tokens) + golden wrapper helper (S14-01) | [x] | S14 — session 049, PR #192 |
| 284 | R4 contract tests for `generate_wrapper()` — 5 scenarios on generated `evaluate.py` (S14-02) | [x] | S14 — session 049, PR #192 |
| 285 | Contract tests for DB-reading methods — tokens/population/count/progress vs fixture DB (S14-03) | [x] | S14 — session 049, PR #192 |
| 286 | `pyproject.toml` — `[project.optional-dependencies] shinka = ["shinka-evolve>=0.0.7,<0.1"]` (S14-04) | [x] | S14 — session 049, PR #192 |
| 287 | Orchestrator seams 2+3 — `backend.default_output_subdir`, single-owner iterations resolution (S14-05) | [x] | S14 — session 049, PR #193 |
| 288 | Orchestrator seam 1 — `_determine_crash_status()` delegates to `backend.count_valid()` (S14-06) | [x] | S14 — session 049, PR #193 |
| 289 | `ShinkaBackend.is_available()` real import check + `config_template()` + `validate_config()` (S14-07) | [x] | S14 — session 049, PR #193 |
| 290 | `ShinkaBackend.build_config()` — spec→`EvolutionConfig`/`DatabaseConfig`/`LocalJobConfig` projection + `resolved_config()` (S14-08) | [x] | S14 — session 049, PR #193 |
| 291 | `ShinkaBackend.generate_wrapper()` — Shinka `evaluate.py` adapting `evaluate_instance()` over dataset (S14-09) | [x] | S14 — session 049, PR #193 |
| 292 | `ShinkaBackend.launch()` via `ShinkaEvolveRunner` + `default_output_subdir` (S14-10) | [x] | S14 — session 049, PR #196 |
| 293 | `ShinkaBackend.collect_token_usage()` — `metadata.api_costs` + `metadata.llm_result.*` from `programs.sqlite` (S14-11) | [x] | S14 — session 049, PR #196 |
| 294 | `ShinkaBackend.parse_population()`, `count_valid()`, `read_progress()` from `programs.sqlite` (S14-12) | [x] | S14 — session 049, PR #196 |
| 295 | `ShinkaBackend.resume()` — reuse parent `results_dir` (clone parity → S15) (S14-13) | [x] | S14 — session 049, PR #196 |
| 296 | L2-Shinka integration tests — 5 mocked-runner scenarios in `test_run_shinka.py` (S14-14) | [x] | S14 — session 049, PR #196 |
| 297 | Doctor/setup/project/problem shims reflect real Shinka availability + install path (S14-15) | [x] | S14 — session 049, PR #197 |
| 298 | L3 E2E Scenario 3 — Shinka happy path with fake LLM server (S14-16) | [x] | S14 — session 049, PR #197 |

### Sprint 016 — Technical Debt Paydown + CLI/UX Polish

Plan: [sprint-016.md](../sprints/sprint-016.md). Dette technique + polish CLI/UX — **no flagship feature** (top-N #299 → S17). 6 scopes, 22 tasks (S16-01..22), 5 PRs + 1 spike across 3 waves. DB migrations v10 (global `llms`) then v11 (project `datasets.split`) kept separate.

| # | Task | Status | Sprint |
|---|---|---|---|
| 310 | **TD-1 — Pricing removal + DB migration v10.** Remove the inert pricing machinery left by S15: `estimate_cost()` (`infra/token_proxy.py`), `--input-cost`/`--output-cost` flags (`cli/llm.py`), `input/output_cost_per_mtok` params (`core/llm.py`) + `LLMEntry` fields + `llms` columns (`infra/db.py`); migration v10 drops the global-DB columns. (S16-01..07) | [x] | S16 — PR #208 (TD-1) |
| 311 | **TD-3 — Resume clone parity (spike-gated).** SPIKE first (S16-09): does `ShinkaEvolveRunner` 0.0.7 resume from a cloned `results_dir`? GO → `resume_precheck` hook + clone logic (S16-10..12); NO-GO → documented limitation (S16-13). **DONE — spike GO (upstream shinka 0.0.7); clone-resume implemented.** | [x] | S16 — PR #212 (TD-3) |
| 312 | **TD-4 — DES-005 §4 full rewrite.** Replace the OE-specific framing with the `EvolutionBackend` abstraction (OE + Shinka); clear FR-RUN-036..039 / FR-RUN-042 doc debt; run spec-reviewer + validation-reviewer. (S16-14..15) | [x] | S16 — PR #207 (TD-4) |

### Unscheduled — Release Process

| # | Task | Status | Sprint |
|---|---|---|---|
| 110 | CI guard: version-tag consistency check on `v*` tag push (compare pyproject.toml version vs tag) | [x] | S16 — PR #206 (TD-2) |

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
| 299 | Top-N / arbitrary-program solution promotion (revisit the rank-1-only model): ShinkaEvolve persists the FULL population **with source code** in `programs.sqlite` (`code` column), so materializing rank-N programs and promoting them to solutions (`solution extract --rank N` revival, or promotion by population program id) is genuinely feasible there; on OpenEvolve, scope what the checkpoint `database.json` exposes. Gate per backend via `capabilities().top_n_extraction` (ADR-007); ties into the `_BEST_PROGRAMS_COUNT = 1` seam and the S15 carry-over in [sprint-014.md](../sprints/sprint-014.md) §Sprint Review. | [ ] | S17 (deferred from S16 — highest-value carry-over) |

### Demo-surfaced — `revolver-demos` Shinka TSP smoke test (2026-06-13)

Found while running `revolver run --backend shinka` on a real TSP problem against the Gemini API (separate `~/projects/revolver-demos` repo, `ISSUES.md` journal). The smoke test proved the engine works end-to-end (best_score 1.213 = +21% vs baseline) but exposed accounting/UX gaps. Severities: 🔴 critical · 🟠 major · 🟡/⚪ minor.

| # | Task | Status | Sprint |
|---|---|---|---|
| 300 | 🔴→reframed **Token accounting + cost removal (Shinka).** **Spike (session 051, see [spike-300-token-accounting.md](../analysis/spike-300-token-accounting.md)) settles the founding question**: the per-attempt/failure token counts are **never written to disk** by Shinka — `gen_*/attempts/**/metadata.json` and `gen_*/failure.json` carry only a derived `llm_cost`/`api_costs`, **zero token fields** (`grep -i token` empty across all 4 demo runs); and `llm_result.thinking_tokens` exists but is **always 0** for Gemini/Claude. The ~20× under-report is the invisible thinking tokens, irrecoverable without monkeypatching Shinka internals (fragile → dropped per robustness rule). **Decision (session 051)**: (a) **remove `estimated_cost_usd` from output** (no realistic cost is reachable; user does not need cost); (b) **keep token counting limited to stored `programs.sqlite` rows** (already implemented, robust) + surface prompt/completion/total in `run info`; (c) add a **caveat** that retry/failed-attempt and thinking tokens are not counted (watch the provider console). No attempt/failure sweep. **DONE (session 052)** — `estimated_cost_usd` removed from `TokenUsage`/output/manifest; `estimate_cost()` + pricing fields left inert (removal + DB migration → S16); `run info` shows prompt/completion/total + caveat. PR #202. | [x] | S15 (Scope A) — PR #202 |
| 301 | 🟠 **Surface/raise ShinkaBackend LLM settings** (extends [#120] to the Shinka backend). `build_config()` never sets `max_patch_attempts` (Shinka default 1 → one malformed patch loses a generation), only sets `max_tokens` when registered (else default 4096 → thinking models return `None` content), and never sets `reasoning_efforts` (→ no thinking control). Shinka's own example configs use `max_patch_attempts=10`, `max_tokens=16384`, per-provider reasoning. Expose these as neutral params / sane defaults. Direct tension to resolve: raising `max_tokens` fixes correctness but inflates thinking-token cost — `reasoning_efforts` is the missing cost lever. **Highest-value S15 scope** (makes thinking-models usable; demo recipe validated). **DONE (session 051)** — `max_patch_attempts=10`/`max_tokens=16384`/`reasoning_efforts` defaults + dry-run surfacing + template. | [x] | S15 (Scope B) — PR #199 |
| 302 | 🟠 **Unproductive-run status.** A run where every proposal fails / 0 successful child programs are produced still reports `status: completed`, `best_score: 1.0` (the init seed), `$0.00`. No signal the run did nothing. Detect "0 successful children / N failed proposals" and mark a distinct status (cf. OE `completed_with_errors`) + warn. **DONE (session 051)** — `count_evolved_children()` (Shinka counts `llm_result` rows; OE→None), `_apply_unproductive_override()` in launch/resume → `completed_with_errors` + warning, `RunInfo.produced_no_children` + `run info` line. | [x] | S15 (Scope C) — PR #201 |
| 303 | ⚪ Neutralize OE-specific wording in `cli/run.py` help after the backend abstraction: group help reads "Solution generation via OpenEvolve"; `run population` described as "MAP-Elites population" (misleading on `--backend shinka`, which has islands not MAP-Elites cells). | [x] | S16 — PR #210 (UX-1) |
| 304 | ⚪ CLI consistency: `revolver problem version create` requires `--tag` (option) while sibling commands take a positional `NAME` (`project init`, `dataset add`, `llm add`). Accept a positional tag. | [x] | S16 — PR #210 (UX-2) |
| 305 | 🟡 Dataset split dual-use: `revolver run` warns when split≠`train`, but a single small demo dataset is naturally used for both evolution and eval/benchmark. Allow a both/any split or clarify the model. **Decision: add `split="both"` + migration v11.** | [x] | S16 — PR #210 (UX-3) |
| 306 | ⚪ `run info` display: `programs_stored` showed 3 while the DB held 11 programs (2 init + 9 children); materialized rank-1 solution shows `score = -`. Reconcile the counter and populate the rank-1 score. **Decision: two counters (`programs_extracted`/`programs_in_db`) + score fallback to run `best_score`.** | [x] | S16 — PR #210 (UX-4) |

### Demo-surfaced — Claude Max via `claude-ollama-bridge` (2026-06-15)

Found while validating the `claude-ollama-bridge` (v0.1.0, separate repo) end-to-end: a local HTTP shim exposing the Claude Max subscription (Agent SDK OAuth) as an Ollama/OpenAI-compatible endpoint, registered via `llm add --source local`. Both backends evolved for real through it (Shinka best 1.218, OE best 1.196 on the TSP demo) — Claude follows the patch format reliably, no cheap-Gemini failure modes. Journaled in `revolver-demos/ISSUES.md`. These are Revolver-side gaps the integration exposed.

| # | Task | Status | Sprint |
|---|---|---|---|
| 307 | 🟠 **LLM request timeout too low for slow local endpoints (OE path).** The OpenEvolve path routes LLM calls through Revolver's HTTP `TokenCountingProxy` (`infra/token_proxy.py`); OpenEvolve's OpenAI client defaults to a 60s timeout, and Revolver only injects `config.llm.timeout` when the `LLMEntry.timeout` is explicitly set. A slow endpoint (Claude-via-bridge: 50–530s/call) therefore aborts at 60s → 4× retry storm → proxy `BrokenPipeError` (writing the late response into the closed connection). Workaround proven: `revolver llm update <name> --timeout 600`. Fix: raise the default (or warn at `run`/dry-run) for `--source local` entries, and document the proxy/timeout interaction. Shinka path is unaffected (no proxy, reads `programs.sqlite`). **Pulled into S15 (Scope #307)** — real correctness bug on the bridge direction now in active use. **DONE (session 052)** — `build_config()` injects a 600 s default `llm.timeout` (`DEFAULT_LOCAL_LLM_TIMEOUT_S`) for `--source local` LLMs without an explicit timeout (config.yaml + `--config-override` still win; remote unaffected); tuning-guide note added. PR #202. | [x] | S15 (Scope #307) — PR #202 |
| 308 | 🟡 **Local/bridge per-call cost not captured.** The bridge returns a notional cost in the OpenAI response `usage.total_cost_usd` (non-standard), but neither the OE token path nor `ShinkaBackend.collect_token_usage()` reads it → `estimated_cost_usd: $0.00` on bridge runs (compounds #300). Capture the `total_cost_usd` field when present, or document that Max-subscription spend must be tracked on the Anthropic console / monthly Agent SDK credit. **Deprioritized**: cost is being removed from Revolver output (#300/session 051) — reduces to a one-line doc note. | [x] | S16 — PR #210 (UX-6) |
| 309 | ⚪ **Local-endpoint concurrency guidance/lever.** Measured: on Claude Max via the bridge, `--parallel 3` inflates per-call latency ~3.5× (76s→262s) and causes >600s timeouts vs a clean `--parallel 1` (Anthropic serializes concurrent requests from one subscription). Relatedly, `ShinkaBackend.build_config()` does not pin `max_proposal_jobs` for local endpoints (defaults to 6) — so Shinka fans out regardless. Consider: pin `max_proposal_jobs=1` (and recommend `--parallel 1`) for `--source local` endpoints, or document the "serialize for subscription-backed/single-GPU local endpoints" guidance in the tuning guide. **Decision: auto-pin `max_proposal_jobs=1` for `--source local` + guide note.** | [x] | S16 — PR #210 (UX-5) |

### Demo-surfaced — `revolver-demos` v0.16.0 validation (TSP + beamforming, 2026-06-22)

Found while validating Revolver 0.16.0 through the **TSP + beamforming** demos (gemma4 on a network Ollama via `sirius`/Tailscale; Claude Opus/Sonnet via the `claude-ollama-bridge`). Triaged in [sprint-016a.md](../sprints/sprint-016a.md) → **v0.16.1** corrective. Severities: 🟠 important · 🟡 minor · ⚪ cosmetic. **Provisional** — the frequency-planning demo has not yet run through Revolver; its items (A8+) will be triaged into a separate `sprint-016b` (v0.16.2) once the feedback report is extended.

| # | Task | Status | Sprint |
|---|---|---|---|
| 313 | 🟡 (A1; reframed from 🟠) **Network/local Ollama probe ignores `--base-url`.** `cli/llm.py:106` builds the validation probe as `OllamaClient()` (no arg) → hardcoded `localhost:11434` (`infra/ollama.py:76`), so a `--source local --base-url <remote>` registration aborts before the (already-correct, `cli/llm.py:116`) entry is stored. Storage + both backends (OE `api_base`, Shinka `local/<model>@<url>`) already route correctly — cosmetic validation bug, not an architecture limit (demos refinement 2026-06-22). Fix: pass the resolved **root** URL (strip a trailing `/v1`) from `--base-url` to the probe; `OLLAMA_HOST` as optional default. | [x] | S16a — PR #220 |
| 314 | 🟠 (A2) **Shinka run busy-loops after completion.** After `Done: … completed` (result persisted), a child `revolver run` process busy-loops at ~100% CPU (State R, 1 thread, `wchan 0`) and never exits; the OE path exits cleanly. `infra/backends/shinka.py:1377` runs `ShinkaEvolveRunner.run()` in-process (asyncio + JobScheduler pool) with no orchestrator-owned teardown. **Spike-first** (needs the shinka env) to pin the lingering process; fix via explicit teardown or a Revolver-owned subprocess we reap; file upstream (cf. #159). **Spike done (upstream v0.0.7): leaked per-call async LLM clients spin asyncio teardown; fix = orchestrator-owned `_shutdown_runner` + `_reap_run_children`.** **Demos verdict (2026-06-23): #224 safe / no regression (empirical); busy-loop not re-demonstrable (`gemma4:8b` deleted) → anti-hang confirmed by code review only. Defensive fix ships.** | [~] | S16a — PR #224 (validated safe; ready to merge) |
| 315 | 🟠 (A3; **extends #309**) **OE `--parallel` auto-pin for `--source local`.** `infra/backends/openevolve.py:548-556` maps `--parallel → evaluator.parallel_evaluations` with no auto-pin; on a serialized subscription endpoint (Claude Max bridge) `--parallel >1` → staggered calls → 600s-timeout retry storm → `BrokenPipeError` → multi-hour hang. #309 fixed only the Shinka side + OE doc-only guidance. Fix: auto-pin `parallel_evaluations=1` for all `--source local` when `--parallel` unset & not overridden; warn-but-honour an explicit `--parallel >1`; surface in dry-run. | [x] | S16a — PR #222 |
| 316 | 🟡 (A4; **composes #308**) **Bridge token under-count caveat.** The bridge returns OpenAI `usage` 2/4 while real Agent-SDK spend (hidden Claude-Code context + thinking tokens) is far higher → Revolver records under-counted token totals on bridge/local runs. Cost already removed (#300). Fix: surface a caveat in `run info` (for `--source local` runs) + the tuning guide (mirrors the #300 thinking-token caveat); no change to the counting path. | [x] | S16a — PR #221 |
| 317 | 🟡 (A5; **external** — bridge repo) **Bridge 502 under sustained load (transient).** During the A3 retry storm the bridge returned repeated `502`/`UpstreamError` then recovered → transient rate-limiting, surfaced confusingly. Revolver-side: verify the proxy surfaces a bridge 502 legibly (FB-01/#123 path); the real fix (backoff + error mapping) is bridge-side. Revolver mitigation = A3 (`--parallel 1` avoids the trigger). No Revolver code change expected. **Verified (PR #221): the proxy forwards the upstream 502 status+body verbatim (`test_proxy_forwards_502_status`); bridge-side backoff/error-mapping remains an external follow-up.** | [x] | S16a — PR #221 (verify) / external |
| 318 | ⚪ (A6) **OE `config.yaml` scaffold triggers its own validator warnings.** `infra/backends/openevolve.py:1229-1249` `_CONFIG_TEMPLATE` emits top-level `num_iterations`/`population_size` and `evaluation:` → `validate_oe_config()` warns ("Did you mean 'database.population_size'", "Unknown OE config key"; OE schema uses `max_iterations`/`evaluator:`). **Decision (P2): rewrite the scaffold to OE-schema-correct keys** (validator stays strict); investigate which keys `build_config()` consumes first so semantics are preserved. *(PR #222: `evaluation:` kept as a Revolver-owned section stripped before the strict parse — `EvaluatorConfig.timeout != timeout_per_instance` — symmetric with Shinka.)* | [x] | S16a — PR #222 |
| 319 | ⚪ (A7) **CLI/doc consistency.** (a) `run resume --run ID` (option, `cli/run.py:323`) is the outlier vs sibling positionals `run info`/`delete`/`population` → add a positional `RUN_ID`, keep `--run` as a backward-compat alias (mirror #304). (b) README Quick Start uses `version create --tag v1.0` though #304 made TAG positional → update to `version create v1.0`. | [x] | S16a — PR #219 (a) + #221 (b) |
| 320 | 🟠 (annex; surfaced during the A2 eval on `revolver-demos`, 2026-06-23) **Shinka mid-run deadlock with `qwen15`.** Distinct from A2/#314: a hang **during** a Shinka run (not the post-run teardown), observed with the `qwen15` model. **Not covered by PR #224.** Needs repro + diagnosis (is it the patch-apply loop, an LLM-call stall/timeout, or a scheduler deadlock? model-specific to qwen15 or broader?). Likely → sprint-016b. | [ ] | S16b (TBD) |

### Sprint 017 — Multi-LLM Ensemble (v0.17.0)

Plan: [sprint-017.md](../sprints/sprint-017.md). Per [ADR-007 — v0.17 Amendment](../architecture/adr/ADR-007-pluggable-evolution-backend.md#amendment--v017-multi-llm-ensemble-selection-2026-07-01) and the source-verified [v017-multi-llm-research.md](../analysis/v017-multi-llm-research.md). Front-loads a correctness slice (B1/B2/B7) then delivers the multi-LLM ensemble flagship (weighted OE + full adaptive-bandit Shinka), gated by two verified capability asymmetries (weights fixed-only, `reasoning_effort` OE-only). 33 tasks (S17-01..33), 7 PRs across 4 waves. DB migrations v12 (`llms.reasoning_effort`) then v13 (`ensemble_members.reasoning_effort`), kept separate per the project's one-column-per-migration discipline. Top-N (#299) explicitly deferred to **S18**.

| # | Task | Status | Sprint |
|---|---|---|---|
| 321 | **B1 — OE wrapper aggregation crash on non-numeric metric.** Copy the numeric guard from `shinka.py:322-331` into the OE `_WRAPPER_TEMPLATE` aggregation loop (`openevolve.py:1140-1144`) + harden the `combined_score` mean (L1133). (S17-01) | [ ] | S17 — PR-W0 |
| 322 | **B1 — test the generated OE wrapper aggregation** (none existed before): mixed numeric/non-numeric metrics dict does not crash, numeric result returned. (S17-02) | [ ] | S17 — PR-W0 |
| 323 | **B2 — wrap `OpenEvolveRunner.run()` in try/finally**; snapshot pre-run child PIDs (mirror `shinka.py:1377`). (S17-03) | [ ] | S17 — PR-W0 |
| 324 | **B2 — hoist `_current_child_pids`/`_reap_run_children`** from `ShinkaBackend` to `infra/backends/base.py`; both backends reuse. (S17-04) | [ ] | S17 — PR-W0 |
| 325 | **B2 — OE-specific `_shutdown_runner()`**: guarded `getattr` on the controller's executor(s), `shutdown(wait=False)` + `contextlib.suppress` (never `wait=True` — cf. #159). (S17-05) | [ ] | S17 — PR-W0 |
| 326 | **B2 — regression test `test_openevolve_shutdown.py`** (mirror `test_shinka_shutdown.py`): teardown+reap runs even on exception; no leftover children. (S17-06) | [ ] | S17 — PR-W0 |
| 327 | **B7 — `EvolutionBackend.recover_best_from_checkpoint()` method**: OE reads latest `oe-output/checkpoints/checkpoint_N/` `best_program_id` + program code; clear error when no checkpoint exists yet. (S17-07) | [ ] | S17 — PR-W0 |
| 328 | **B7 — `solution extract --from-checkpoint` flag**: dispatches to the backend recovery method for `interrupted`/`failed` runs; default (flag unset) behavior unchanged. (S17-08) | [ ] | S17 — PR-W0 |
| 329 | **B7 — revise `test_extract_rejects_interrupted_run`** (`test_solution.py:643`, conscious F3 policy revision) + add `--from-checkpoint` success/no-checkpoint-yet tests. (S17-09) | [ ] | S17 — PR-W0 |
| 330 | **DB migration v12 — `reasoning_effort` column on `llms`** (global DB, simple `ALTER TABLE ADD COLUMN`); `CURRENT_SCHEMA_VERSION = 12`. (S17-10) | [ ] | S17 — PR-W1a |
| 331 | **DB migration v13 — `reasoning_effort` column on `ensemble_members`** (both DDL copies kept in sync); `CURRENT_SCHEMA_VERSION = 13`. (S17-11) | [ ] | S17 — PR-W1a |
| 332 | **`models/llm.py` — `reasoning_effort` field** on `LLMEntry` and `EnsembleMember`. (S17-12) | [ ] | S17 — PR-W1a |
| 333 | **A4 — widen `BackendCapabilities`**: `selection_strategies` (OE `("weighted",)`, Shinka `("fixed","ucb","ucb1","thompson")`) + `per_member_reasoning_effort` (OE `True`, Shinka `False`). (S17-13) | [ ] | S17 — PR-W1a |
| 334 | **Widen `BackendRunSpec`**: `selection`, `selection_kwargs`, `llm_weight_overrides` fields. (S17-14) | [ ] | S17 — PR-W1a |
| 335 | **Mirror the new levers on `RunConfig`** (`models/run.py`): `selection`, `selection_kwargs`, `llm_weight_overrides`. (S17-15) | [ ] | S17 — PR-W1a |
| 336 | **`cli/run.py` — `--selection`/`--selection-kwarg`/`--llm-weight` flags on `run_launch`**, threaded into `RunConfig`. (S17-16) | [ ] | S17 — PR-W1c |
| 337 | **Mirror the three flags on `run_resume`**; both `launch_run`/`resume_run` copy the new fields into `BackendRunSpec`. (S17-17) | [ ] | S17 — PR-W1c |
| 338 | **`core/run.py` — validate `--selection` against `capabilities().selection_strategies`** before `build_config()`; OE rejects non-`fixed` (A2). (S17-18) | [ ] | S17 — PR-W1c |
| 339 | **M1 — Shinka: lift the ensemble hard-raise, project all members** → `evo_config.llm_models[]`; `llm_dynamic_selection` from `--selection` (default `fixed`, zero behavior change for single-LLM). (S17-19) | [ ] | S17 — PR-W1b |
| 340 | **M1/A3 — Shinka weights → `prior_probs` under `fixed` only**; warn when weights supplied under `ucb`/`ucb1`/`thompson` (FACT B). (S17-20) | [ ] | S17 — PR-W1b |
| 341 | **A5/M4 — per-sampler `--selection-kwarg` routing** on Shinka; `cost_aware_coef` ucb/ucb1-only, default **0** (not Shinka's 0.5). (S17-21) | [ ] | S17 — PR-W1b |
| 342 | **M3 — OE `--llm-weight` override** in `_build_ensemble_llm_config()`; defensive `--selection` non-fixed rejection at the OE adapter level. (S17-22) | [ ] | S17 — PR-W1c |
| 343 | **L2 tests — selection-strategy validation + `--llm-weight`** across OE/Shinka-fixed/Shinka-bandit. (S17-23) | [ ] | S17 — PR-W1b/c |
| 344 | **B4/M2 — `--reasoning-effort` on `llm add`/`llm update`**, threaded through `core/llm.py` → DB. (S17-24) | [ ] | S17 — PR-W2a |
| 345 | **B4/M2 — `--reasoning-effort` on `ensemble add`** (per-member override, same precedence pattern as temperature/max_tokens). (S17-25) | [ ] | S17 — PR-W2a |
| 346 | **OE — per-member `reasoning_effort` mapping** in `_build_ensemble_llm_config()` + single-LLM path. (S17-26) | [ ] | S17 — PR-W2a |
| 347 | **Shinka — global `reasoning_efforts` pool + disagreement/local-inert warnings** (FACT A). (S17-27) | [ ] | S17 — PR-W2a |
| 348 | **L2 tests — `reasoning_effort` projection** (OE per-member, Shinka global-pool, disagreement warning, local-inert warning). (S17-28) | [ ] | S17 — PR-W2a |
| 349 | **OE ensemble dry-run example + doc section** — cross-engine comparison (OE-weighted vs Shinka-fixed vs Shinka-ucb). (S17-29) | [ ] | S17 — PR-W2b |
| 350 | **B9 — warn on no-op `--config-override` key** (generalizes the A5 per-sampler routing check to the rest of `--config-override`). (S17-30) | [ ] | S17 — PR-W2b |
| 351 | **A6/M5 — OE config template: surface `feature_dimensions`/`feature_bins`** (extends the #318 `database.*` realignment). (S17-31) | [ ] | S17 — PR-W3 |
| 352 | **B6 — finish `REVOLVER_HOME`**: `config.py:68` consistent with `db.py`'s existing resolution; document; optional `--global-db` flag. (S17-32) | [ ] | S17 — PR-W3 |
| 353 | **Full regression sweep + doc-edit follow-up issue** listing every FR/DES/validation edit from the research doc §4 (FR-RUN-049/050/051, FR-LLM-026, FR-EVL-021, ADR-007 D5/spec-run FR-RUN-046 supersession) for the spec-reviewer/validation-reviewer pass before the v0.17.0 tag. (S17-33) | [ ] | S17 — PR-W3 |
