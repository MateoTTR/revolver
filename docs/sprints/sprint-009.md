# Sprint 009 — Solution UX + Config fluide + Run robustness

**Status**: Planning
**Goal**: Deliver `solution show/export/diff` for direct source-code access, robust run failure handling, workspace detection, and fluent OE config via CLI flags (`--temperature`, `--parallel`) and LLM-level temperature field. Also adds JSON/list support to `--config-override` and two documentation guides driven by beamforming feedback.
**Demo**: `revolver solution show my-solution` prints the generated program to stdout; a crashed run appears as `failed` in `run list` instead of `running`; `revolver run --temperature 0.5 --parallel 4` tunes OE without editing config.yaml; `revolver run list` outside a workspace shows "Not in a Revolver workspace" instead of empty output.

---

## Source

- Demo feedback: `/home/mathi/revolver-demos/beamforming/demos/demo-v0.8.1/feedback.md`
- Consolidated feedback: `/home/mathi/revolver-demos/feedback-summary.md`
- Architecture discussion: session preceding Sprint 009 planning
- Predecessor: Sprint 008a (v0.8.1)

---

## Scope

### Command groups included

- `revolver solution` — new `show`, `export`, `diff` subcommands; `--force` on `extract`; remove `--rank` flag from extract
- `revolver run` — failed-run status, workspace detection, `--temperature`, `--parallel` flags
- `revolver solution list / run list / benchmark list` — workspace detection guard
- `revolver llm` — `temperature` field on `llm add` and `llm update`
- `revolver infra` — `--config-override` JSON/list parsing; `build_config()` `--temperature` + `--parallel` + LLM temperature injection

### Key FRs covered

- FR-SOL-003 / FR-SOL-004 — solution program path accessibility (show/export)
- FR-SOL-011 / FR-SOL-012 — extract with `--force` override
- FR-RUN-031 / FR-RUN-032 — failed/interrupted run status tracking
- FR-LLM-001 / FR-LLM-007 — LLM temperature field (add + update)
- FR-RUN-005 / FR-RUN-006 — OE config builder flags (temperature, parallel)

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S9-01 | `core.solution.show_solution(id_or_alias)` — resolve solution, read program file from `program_path`, return source code as string. Raise `RevolverError` if file missing. | domain | — | [ ] | Returns full source text; `RevolverError` if program file absent; used by `solution show` and `solution export` |
| S9-02 | `core.solution.diff_solutions(a, b)` — resolve both aliases/IDs, read both program files, call `difflib.unified_diff()`, return list of diff lines. | domain | S9-01 | [ ] | Returns non-empty diff for two different programs; empty diff for identical programs; `RevolverError` if either solution missing |
| S9-03 | `cli.solution.solution_show` — `revolver solution show <alias>`. Print source to stdout (plain). `--json` outputs `{"alias": ..., "code": ...}`. | cli | S9-01 | [ ] | Source visible on stdout; `--json` emits valid JSON; exit 1 if alias not found |
| S9-04 | `cli.solution.solution_export` — `revolver solution export <alias> [-o <path>]`. Copy program file to `<path>` (default `./<alias>.py`). Print confirmation to stderr. | cli | S9-01 | [ ] | File created at target path; default name `<alias>.py` if no `-o`; exit 1 if alias not found; `--json` returns `{"exported_to": "<path>"}` |
| S9-05 | `cli.solution.solution_diff` — `revolver solution diff <a> <b>`. Print unified diff to stdout. Exit 0 on success (whether identical or different), exit 1 on error (Revolver convention). | cli | S9-02 | [ ] | Diff printed to stdout; exit 0 on success (identical or different); `--json` returns `{"diff": "<text>", "identical": bool}` |
| S9-06 | `core.solution.extract_solution()` — add `force: bool = False` parameter. When `force=True` and `(run_id, rank)` already exists, delete the existing solution (via `db_delete_solution`) then proceed with insertion. Remove the `rank` parameter from the CLI (keep in domain layer; hardcode `rank=1` in CLI). | domain | — | [ ] | `force=True` replaces existing solution; `force=False` still raises `DuplicateNameError`; rank=1 hardcoded in CLI; rank column still in DB |
| S9-07 | `cli.solution.solution_extract` — remove `--rank` flag entirely, add `--force` flag. Update help text to mention `--force` for replacement. | cli | S9-06 | [ ] | `--rank` option absent from `--help`; `--force` present; `revolver solution extract --run X --force` replaces existing; old behavior without `--force` unchanged |
| S9-08 | `core.run.launch_run()` — wrap the OpenEvolve runner call in `try/except Exception` + `except KeyboardInterrupt`. On `Exception`: mark run `failed` in DB, write `run-error.log`, remove lock. On `KeyboardInterrupt`: mark `interrupted`. Distinct from `_handle_post_run_failure` (which covers post-processing, not OE itself). | domain | — | [ ] | Run that throws during OE execution gets status `failed` in DB; `run-error.log` written; lock file removed; `KeyboardInterrupt` → `interrupted`; run that fails post-processing still → `completed_with_errors` |
| S9-09 | Workspace detection guard — `infra.store.find_project_root()` already raises `ProjectNotFoundError` when `.revolver/` is absent. Add a helper `is_in_workspace(cwd)` → `bool` in `infra.store`. In `cli.run`, `cli.solution`, `cli.benchmark`, catch `ProjectNotFoundError` (or the store equivalent) and print "Not in a Revolver workspace. Run `revolver project init` first." to stderr with exit 1. | infra + cli | — | [ ] | `revolver run list` outside workspace → exit 1 + clear message on stderr; `revolver solution list` same; `revolver benchmark list` same; inside workspace, behavior unchanged |
| S9-10 | `infra.openevolve.build_config()` — add `temperature: float | None = None` parameter. When provided, set `config["llm"]["temperature"] = temperature`. Inject after step 2b (LLM per-model config) so it overrides LLM-level temperature. | infra | — | [ ] | `build_config(..., temperature=0.5)` → `config["llm"]["temperature"] == 0.5`; `None` leaves existing value; overrides LLM registry value |
| S9-11 | `infra.openevolve.build_config()` — add `parallel: int | None = None` parameter. When provided, set `config["evaluator"]["parallel_evaluations"] = parallel`. Inject after evaluator defaults (step after cascade_evaluation). | infra | S9-10 | [ ] | `build_config(..., parallel=4)` → `config["evaluator"]["parallel_evaluations"] == 4`; `None` leaves existing value |
| S9-12 | `infra.openevolve._parse_value()` — add JSON array/object support: try `json.loads(value)` when value starts with `[` or `{`. Fallback to existing scalar parsing on parse error. | infra | — | [ ] | `_parse_value("[1,2,3]")` → `[1, 2, 3]`; `_parse_value('{"a":1}')` → `{"a": 1}`; malformed JSON → treated as string (no crash) |
| S9-13 | `models.llm.LLMEntry` — add `temperature: float | None = None` field. Update `infra.db`: add `temperature REAL` column to `llms` table in schema, add DB migration v6, update `insert_llm()` and `get_llm()` (and `update_llm()`) to handle the new column. | models + infra | — | [ ] | `LLMEntry.temperature` field present; DB migration v5→v6 adds column; existing LLMs get `temperature=NULL`; round-trip test passes |
| S9-14 | `core.llm` — pass `temperature` through `register_llm()` and `update_llm()`. `infra.openevolve.build_config()`: inject `llm.temperature` into `config["llm"]["temperature"]` in step 2b (alongside `max_tokens` and `timeout_s`), before `--temperature` CLI flag (step 2c) so CLI overrides LLM registry value. | domain + infra | S9-13, S9-10 | [ ] | `llm.temperature` injected in config; `--temperature` CLI overrides registry value; LLM with `temperature=None` leaves config unchanged |
| S9-15 | `cli.llm` — add `--temperature` option to `llm add` and `llm update`. Range validation: 0.0–2.0. Display temperature in `llm list` output. | cli | S9-13 | [ ] | `revolver llm add ... --temperature 0.7` stores value; `revolver llm update ... --temperature 1.0` updates; `revolver llm list` shows temperature column |
| S9-16 | `cli.run` — add `--temperature FLOAT` and `--parallel INT` flags to `revolver run`. Pass through to `build_config()` via `launch_run()` (extend `RunConfig` model if needed). | cli + models | S9-10, S9-11 | [ ] | `revolver run --temperature 0.5` passes value to `build_config`; `revolver run --parallel 4` same; flags visible in `--help`; dry-run shows resolved config with values |
| S9-17 | Write L2 integration tests for all Sprint 009 features. | test | S9-01..S9-16 | [ ] | See Integration Tests table below — all listed tests pass; no regression on existing 870 tests |
| S9-18 | New guide `docs/guides/tuning-oe-config.md` — covers MAP-Elites feature dimensions, islands, `parallel_evaluations`, recommended profiles for 50/500/2000 iterations, multi-objective setup (`feature_dimensions` with custom metrics like `execution_time`). | docs | — | [ ] | File exists at `docs/guides/tuning-oe-config.md`; covers all topics listed; linked from CLAUDE.md guides table |
| S9-19 | Update `docs/guides/initial-program-structure.md` — add beamforming learnings: stronger baseline = less improvement margin; allow scipy for complex optimization; guidance on problem difficulty calibration. | docs | — | [ ] | Beamforming section added; scipy guidance present; guidance on baseline strength vs LLM margin |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md` that must pass at sprint end, plus new scenarios added for Sprint 009:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `solution show` | Display source code on stdout | `test_solution_show_stdout` | Planned |
| `solution show` | `--json` outputs code as string field | `test_solution_show_json` | Planned |
| `solution show` | Alias not found → exit 1 | `test_solution_show_not_found` | Planned |
| `solution export` | Copy to default `./<alias>.py` | `test_solution_export_default` | Planned |
| `solution export -o <path>` | Copy to explicit path | `test_solution_export_explicit_path` | Planned |
| `solution export` | Alias not found → exit 1 | `test_solution_export_not_found` | Planned |
| `solution diff` | Two different solutions → diff on stdout | `test_solution_diff_different` | Planned |
| `solution diff` | Two identical solutions → empty diff, exit 0 | `test_solution_diff_identical` | Planned |
| `solution diff` | `--json` returns diff text + identical flag | `test_solution_diff_json` | Planned |
| `solution extract --force` | Replace existing (run_id, rank) extraction | `test_solution_extract_force` | Planned |
| `solution extract` | `--rank` flag absent from CLI | `test_solution_extract_no_rank_flag` | Planned |
| `run` (internal) | OE raises exception → status `failed` in DB | `test_run_oe_failure_marks_failed` | Planned |
| `run` (internal) | KeyboardInterrupt → status `interrupted` in DB | `test_run_keyboard_interrupt_marks_interrupted` | Planned |
| `run list` | Outside workspace → exit 1 + clear message | `test_run_list_outside_workspace` | Planned |
| `solution list` | Outside workspace → exit 1 + clear message | `test_solution_list_outside_workspace` | Planned |
| `benchmark list` | Outside workspace → exit 1 + clear message | `test_benchmark_list_outside_workspace` | Planned |
| `run --temperature` | Injects into `config["llm"]["temperature"]` | `test_run_temperature_flag` | Planned |
| `run --parallel` | Injects into `config["evaluator"]["parallel_evaluations"]` | `test_run_parallel_flag` | Planned |
| `--config-override` | JSON array value parsed correctly | `test_config_override_json_array` | Planned |
| `--config-override` | JSON object value parsed correctly | `test_config_override_json_object` | Planned |
| `llm add --temperature` | Temperature stored in DB | `test_llm_add_temperature` | Planned |
| `llm update --temperature` | Temperature updated in DB | `test_llm_update_temperature` | Planned |
| `llm add` + `run` | LLM temperature injected into OE config | `test_llm_temperature_injected_in_build_config` | Planned |
| `run --temperature` | CLI flag overrides LLM registry temperature | `test_run_temperature_overrides_llm_registry` | Planned |

**Cumulative L2 tests at sprint end: ~895 total (870 previous + ~25 new)**

---

## Parallelization

### Dependency graph

```
Sprint 008a complete ──┬──> S9-01 (domain: show_solution)
                       │         ↓
                       │    S9-02 (domain: diff_solutions)     ← depends on S9-01
                       │         ↓
                       │    S9-03 (cli: solution show)
                       │    S9-04 (cli: solution export)        ← parallel with S9-03
                       │    S9-05 (cli: solution diff)          ← depends on S9-02
                       │
                       ├──> S9-06 (domain: extract --force, remove --rank)
                       │         ↓
                       │    S9-07 (cli: extract --force, drop --rank)
                       │
                       ├──> S9-08 (domain: run failure status)  ← independent
                       │
                       ├──> S9-09 (infra+cli: workspace detection)  ← independent
                       │
                       ├──> S9-10 (infra: build_config --temperature)
                       │         ↓
                       │    S9-11 (infra: build_config --parallel)
                       │         ↓
                       │    S9-16 (cli: run --temperature --parallel)  ← depends S9-10+S9-11
                       │
                       ├──> S9-12 (infra: _parse_value JSON support)  ← independent
                       │
                       ├──> S9-13 (models+infra: LLMEntry.temperature + DB migration)
                       │         ↓
                       │    S9-14 (domain+infra: llm.temperature → build_config)  ← dep S9-13+S9-10
                       │         ↓
                       │    S9-15 (cli: llm add/update --temperature)  ← dep S9-13
                       │
                       ├──> S9-18 (docs: tuning guide)  ← fully independent
                       │
                       ├──> S9-19 (docs: initial-program update)  ← fully independent
                       │
                       └──> S9-17 (tests) ◄── all implementation tasks complete
```

### Critical path

Sprint 008a → S9-13 → S9-14 (+ S9-10) → S9-16 → S9-17

Estimated sequential depth: 5 steps.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Solution UX (show/export/diff) | S9-01, S9-02, S9-03, S9-04, S9-05 | Sprint 008a done | Agent 1 |
| B — Extract robustness | S9-06, S9-07 | Sprint 008a done | Agent 2 |
| C — Run robustness (failure status) | S9-08 | Sprint 008a done | Agent 2 (after S9-06) |
| D — Workspace detection | S9-09 | Sprint 008a done | Agent 3 |
| E — OE config flags (temperature + parallel) | S9-10, S9-11, S9-16 | Sprint 008a done | Agent 1 (after S9-05) |
| F — JSON override parsing | S9-12 | Sprint 008a done | Agent 3 (after S9-09) |
| G — LLM temperature field | S9-13, S9-14, S9-15 | Sprint 008a done | Agent 4 |
| H — Docs | S9-18, S9-19 | Sprint 008a done | Agent 4 (after S9-15) |
| I — Tests | S9-17 | All streams complete | Any agent |

Peak parallelism: 4 agents (Streams A, B, D, G simultaneously at sprint start).

### Conflict risks

- **`src/revolver/cli/solution.py`** — Streams A (S9-03/04/05) and B (S9-07) both modify this file. Merge B first (extract changes are in the `solution_extract` function only), then A (adds new functions `solution_show`, `solution_export`, `solution_diff`).
- **`src/revolver/core/solution.py`** — Stream A (S9-01/02) and B (S9-06) both modify. Merge B first (`extract_solution` change), then A (adds new `show_solution`, `diff_solutions` functions).
- **`src/revolver/infra/openevolve.py`** — Streams E (S9-10/11) and F (S9-12) and G (S9-14) all modify `build_config()` or `_parse_value()`. Coordinate: apply changes as additive insertions in non-overlapping regions; G adds a line in the 2b block, E adds parameters and lines in 2b, F modifies `_parse_value()` only. Low conflict risk if changes are in distinct function/block locations.
- **`src/revolver/infra/db.py`** — Stream G (S9-13) adds DB migration v6 and updates `insert_llm`, `get_llm`, `update_llm`. No other stream touches `db.py`. No conflict.
- **`src/revolver/cli/run.py`** — Stream E (S9-16) and C (S9-08 touches `core/run.py`, not `cli/run.py`). Stream D (S9-09) touches the workspace detection at the top of run subcommands. Merge D before E to avoid collision on the import / error-handling preamble.

---

## PR Decomposition

| PR | Scope | Files modified | Can parallelize |
|---|---|---|---|
| PR-A | `solution show/export/diff` | `core/solution.py`, `cli/solution.py`, `tests/` | Independent |
| PR-B | `solution extract --force`, drop `--rank` | `core/solution.py`, `cli/solution.py`, `tests/` | Independent (non-overlapping fns from PR-A) |
| PR-C | Run failure status | `core/run.py`, `tests/` | Independent |
| PR-D | Workspace detection | `infra/store.py`, `cli/run.py`, `cli/solution.py`, `cli/benchmark.py`, `tests/` | Independent |
| PR-E | OE config flags (`--temperature`, `--parallel`) | `infra/openevolve.py`, `cli/run.py`, `models/run.py` (RunConfig), `tests/` | Independent |
| PR-F | JSON/list `--config-override` parsing | `infra/openevolve.py`, `tests/` | Independent (touches `_parse_value` only) |
| PR-G | LLM temperature field | `models/llm.py`, `infra/db.py`, `core/llm.py`, `cli/llm.py`, `infra/openevolve.py`, `tests/` | Independent; coordinate infra/openevolve.py merge with PR-E/PR-F |
| PR-H | Guide: tuning OE config | `docs/guides/tuning-oe-config.md`, `CLAUDE.md` | Independent |
| PR-I | Update initial-program guide | `docs/guides/initial-program-structure.md` | Independent |
| PR-J | Full regression + sprint L2 tests | `tests/` | Depends on all PRs merged |

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / 25 new integration tests passing

### Demo-able features
- [ ] `revolver solution show my-solution` — prints program source to stdout
- [ ] `revolver solution export my-solution -o ./best.py` — copies program file
- [ ] `revolver solution diff sol-a sol-b` — shows unified diff between two programs
- [ ] `revolver solution extract --run X --force` — re-extracts replacing existing solution
- [ ] Failed run (e.g. missing API key) → status `failed` in `run list` instead of `running`
- [ ] `revolver run list` outside `.revolver/` workspace → explicit "Not in a Revolver workspace" message
- [ ] `revolver run --temperature 0.7 --parallel 4` — OE config tuned without editing config.yaml
- [ ] `--config-override feature_dimensions=[0,1]` — JSON array accepted in override
- [ ] `revolver llm add ... --temperature 0.5` — temperature stored and injected into OE config
- [ ] Guide `docs/guides/tuning-oe-config.md` available with recommended profiles

### Carry-over
_TBD at sprint end._
