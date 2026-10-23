# Sprint 010 — Resume, Robustness & UX (v0.10.0)

**Status**: Planning
**Goal**: Deliver resume workflow improvements (--llm, --config-override on resume), run robustness fixes (zombie detection, 100%-error status), quick UX wins (B8 Revolver key filter, B12 llm update --model, F4 --rewrite-mode), and optionally population inspection (B13). Targeting v0.10.0 release.
**Demo**: `revolver run resume --run <id> --llm pro-model --config-override reasoning_effort=low` switches LLM mid-evolution; `revolver run start --rewrite-mode` injects full-rewrite config in one flag; `revolver run list` auto-detects and marks zombie runs as `interrupted`; a run with 100% LLM errors ends as `failed` instead of `completed`.

---

## Source

- Demo feedback: `feedback.md` of the beamforming demo v0.9.0 (private demo repository)
- Feedback summary: `feedback-summary.md` (private demo repository)
- Predecessor: Sprint 009a (v0.9.1)

---

## Bugs / features addressed

| ID | Item | Severity | Origin |
|---|---|---|---|
| B8 | Filter Revolver-specific keys from OE config validator | Medium | v0.9.1 demo |
| B9 | Run 100% LLM errors → status `failed` or `completed_with_errors` | High | v0.9.1 demo |
| B10 | `run resume --llm` — change LLM model on resume | High | v0.9.1 demo |
| B11 | `run resume --config-override` — pass overrides on resume | High | v0.9.1 demo |
| B12 | `llm update --model` — update model identifier | Medium | v0.9.1 demo |
| B13 | MAP-Elites population inspection command | Medium | v0.9.1 demo |
| B14 | Zombie run detection and `interrupted` marking | High | v0.9.1 demo |
| F4 | `--rewrite-mode` shortcut on `run start` and `run resume` | Medium | v0.9.1 POC |
| Doc-A | Guide: full-rewrite mode section in `tuning-oe-config.md` | Medium | v0.9.1 POC |
| Doc-B | Guide: problem.md enrichment as key lever in `initial-program-structure.md` | Medium | v0.9.1 POC |

---

## Scope

### Command groups affected

- `revolver run` — resume --llm, resume --config-override, zombie detection, 100%-error status, --rewrite-mode, population inspection
- `revolver llm` — update --model
- `revolver infra` — validate_oe_config() Revolver key filter
- `docs/guides` — full-rewrite and problem.md enrichment sections

### Key FRs covered

- FR-RUN-013 — `resume` creates a new run from parent checkpoint
- FR-RUN-023 — `--dry-run` validates all inputs and displays resolved config
- FR-RUN-034 — `resume` accepts `completed_with_errors` as valid parent status
- FR-LLM-019 — LLM temperature stored in registry and injected into OE config

---

## Tasks

| # | Task | Layer | Depends on | PR | Status | Acceptance criteria |
|---|---|---|---|---|---|---|
| S10-01 | `validate_oe_config()` — add `REVOLVER_KEYS` set: `{"initial_program", "num_generations", "timeout_per_instance"}`. Skip validation for keys in this set instead of emitting "Unknown OE config key" warning. Remove `num_generations` passe-plat logic (deprecate it: emit a deprecation notice suggesting `max_iterations` instead, still pass through to maintain backwards compat). | infra | — | PR-A | [ ] | `validate_oe_config()` returns no warning for `initial_program`, `num_generations`, `timeout_per_instance`; emits deprecation notice for `num_generations`; unknown OE keys still warned; existing tests still pass |
| S10-02 | `infra.db.update_llm()` — add `model: str | None = None` parameter. Update SQL helper to include `model` column update when provided. | infra | — | PR-B | [ ] | `update_llm(name, model="new-id")` updates the `model` column in the `llms` table; `model=None` leaves the column unchanged; returns updated `LLMEntry` |
| S10-03 | `core.llm.update_llm()` — add `model: str | None = None` parameter, propagate to `infra.db.update_llm()`. | domain | S10-02 | PR-B | [ ] | `update_llm("flash", model="gemini-2.5-flash-lite")` changes the model field; function returns updated `LLMEntry`; other fields unchanged |
| S10-04 | `cli.llm.llm_update` — add `--model TEXT` option, pass to `core.llm.update_llm()`. Update help text. | cli | S10-03 | PR-B | [ ] | `revolver llm update flash --model gemini-2.5-flash-lite` succeeds and displays updated record; `--help` lists `--model`; `revolver llm list` shows updated model name |
| S10-05 | `core.run.resume_run()` — add `llm_name: str | None = None` parameter. When provided, look up the new LLM entry from DB (global DB), resolve its API key env, and use it in `build_config()` instead of the parent run's LLM. Store the new LLM name in the child run's metadata. | domain | — | PR-C | [ ] | `resume_run(run_id, llm_name="pro")` uses `pro` LLM in OE config; parent run's LLM unchanged; child run `run info` shows new LLM name; `RevolverError` raised if new LLM not found |
| S10-06 | `cli.run.run_resume` — add `--llm TEXT` option. Pass to `core.run.resume_run()`. | cli | S10-05 | PR-C | [ ] | `revolver run resume --run X --llm pro` invokes resume with new LLM; `--help` lists `--llm`; `--dry-run` shows new LLM in resolved config |
| S10-07 | `core.run.resume_run()` — add `config_overrides: list[str] | None = None` parameter. Parse and apply via existing `_parse_config_overrides()` logic (reuse from `launch_run`). Overrides applied on top of parent config. | domain | — | PR-C | [ ] | `resume_run(run_id, config_overrides=["reasoning_effort=low"])` injects the override into OE config; multiple overrides supported; invalid override format raises `ValidationError` |
| S10-08 | `cli.run.run_resume` — add `--config-override TEXT` option (multiple / `list[str]`). Pass to `core.run.resume_run()`. | cli | S10-07 | PR-C | [ ] | `revolver run resume --run X --config-override reasoning_effort=low --config-override max_code_length=15000` passes both overrides; `--help` documents the option; `--dry-run` reflects overrides |
| S10-09 | `infra.openevolve.build_config()` — add `rewrite_mode: bool = False` parameter. When `True`, inject `diff_based_evolution: false` and `max_code_length: 50000` (unless already overridden by `config_overrides`). Config overrides take precedence over rewrite_mode defaults. | infra | — | PR-D | [ ] | `build_config(rewrite_mode=True)` sets `diff_based_evolution=false` and `max_code_length=50000` in OE config; explicit `--config-override max_code_length=30000` overrides the rewrite_mode default; `rewrite_mode=False` (default) leaves config unchanged |
| S10-10 | `core.run.launch_run()` and `core.run.resume_run()` — add `rewrite_mode: bool = False` parameter, pass to `build_config()`. | domain | S10-09 | PR-D | [ ] | `launch_run(rewrite_mode=True)` produces OE config with `diff_based_evolution: false`; same for `resume_run`; no regression on existing tests |
| S10-11 | `cli.run.run_start` and `cli.run.run_resume` — add `--rewrite-mode` boolean flag. Pass to respective core functions. Update `--help` with explanation: "Equivalent to --config-override diff_based_evolution=false --config-override max_code_length=50000". | cli | S10-10 | PR-D | [ ] | `revolver run start --rewrite-mode` flag visible in `--help`; `--dry-run --rewrite-mode` shows `diff_based_evolution: false`; `revolver run resume --rewrite-mode` same |
| S10-12 | `core.run.launch_run()` — after OE completes, if `valid_iterations == 0`, set run status to `failed` (not `completed`). If `valid_iterations > 0` but `valid_iterations / total_iterations < 0.1` (less than 10%), set status to `completed_with_errors`. Threshold constant `MIN_VALID_ITERATION_RATIO = 0.1` in `core/run.py`. | domain | — | PR-E | [ ] | A mock run with `valid_iterations=0` / `total_iterations=3` → status `failed`; `valid_iterations=1` / `total_iterations=20` → `completed_with_errors`; `valid_iterations=15` / `total_iterations=20` → `completed`; existing behavior unchanged for normal runs |
| S10-13 | `core.run.list_runs()` (or a new `core.run.detect_zombie_runs()` helper) — iterate runs with `status=running`, check if the PID stored in the lock file is still alive (`psutil.pid_exists(pid)` or `os.kill(pid, 0)`). Mark runs with dead PIDs as `interrupted` in DB. | domain | — | PR-F | [ ] | After calling `detect_zombie_runs()`, a run whose PID no longer exists is marked `interrupted`; a run whose PID is alive remains `running`; runs with no lock file are also marked `interrupted` |
| S10-14 | `cli.run.run_list` — call `detect_zombie_runs()` automatically at the start of `run list`, before fetching the list. Display a warning if zombies were detected and cleaned: "2 zombie run(s) detected and marked as interrupted". | cli | S10-13 | PR-F | [ ] | `revolver run list` after a zombie run prints the zombie count warning and shows the run as `interrupted`; normal listing unaffected; `--json` output includes the cleanup count in metadata |
| S10-15 | New command `revolver run cleanup` — explicit cleanup: calls `detect_zombie_runs()`, reports results, with `--force` to skip confirmation. Adds `run_cleanup` Typer subcommand to `cli/run.py`. | cli | S10-13 | PR-F | [ ] | `revolver run cleanup` marks zombie runs as `interrupted` and reports count; `--force` skips confirmation; `revolver run cleanup` with no zombies prints "No zombie runs found"; `--help` works |
| S10-16 | New command `revolver run population <run_id>` — parse OE checkpoint `database.json` from the run's `oe-output/checkpoints/checkpoint_N/` (highest-N checkpoint), extract programs with scores and feature values, display as a rich table. Columns: rank, score, features (key=val pairs), program_file. New `core.run.get_population()` function. | domain + cli | — | PR-G | [ ] | `revolver run population <id>` displays table with program entries, scores, and MAP-Elites features; `--json` outputs array; `RevolverError` if no checkpoint found; empty population shows empty table without crash |
| S10-17 | Update `docs/guides/tuning-oe-config.md` — add "Full-rewrite mode" section: when to use it (paradigm exploration vs diff tuning), required config (`diff_based_evolution: false`, `max_code_length: 50000`), `--rewrite-mode` CLI shortcut, Gemini model compatibility table (Flash-Lite OK, Flash thinking NOT OK, Pro with reasoning_effort=low OK). | docs | S10-11 | PR-H | [ ] | Guide has a "Full-rewrite mode" section; mentions `--rewrite-mode` flag; includes model compatibility table; linked from main guide index |
| S10-18 | Update `docs/guides/initial-program-structure.md` — add "Problem.md as key lever" section: enriching problem.md with mathematical formulation, known approaches, domain hints (softmin, continuation, scipy). Add "When to enrich problem.md" decision guide. Reference the beamforming POC as evidence. | docs | — | PR-H | [ ] | Guide has new "Problem.md enrichment" section; includes concrete examples (math formulation, solver hints); references full-rewrite POC; no broken links |
| S10-19 | L2 integration tests for Sprint 010 features — cover all blocs A through G. See Integration Tests table below. | test | S10-01..S10-16 | PR-H | [ ] | All integration tests in Sprint 010 test table pass; no regression on ~909 existing tests |

---

## Integration Tests (L2)

New scenarios added for Sprint 010. All must pass at sprint end.

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `infra validate_oe_config` | `initial_program` key → no warning (filtered) | `test_validate_oe_config_initial_program_filtered` | Planned |
| `infra validate_oe_config` | `timeout_per_instance` key → no warning (filtered) | `test_validate_oe_config_timeout_per_instance_filtered` | Planned |
| `infra validate_oe_config` | `num_generations` key → deprecation notice, no error warning | `test_validate_oe_config_num_generations_deprecated` | Planned |
| `llm update --model` | `--model new-id` updates model field in DB | `test_llm_update_model` | Planned |
| `llm update --model` | `revolver llm list` shows updated model name | `test_llm_update_model_visible_in_list` | Planned |
| `run resume --llm` | `--llm new-model` resolves new LLM in OE config | `test_resume_llm_override` | Planned |
| `run resume --llm` | `--llm nonexistent` raises RevolverError | `test_resume_llm_not_found` | Planned |
| `run resume --llm` | `--dry-run --llm new` shows new LLM in resolved config | `test_resume_dry_run_llm_override` | Planned |
| `run resume --config-override` | Single override propagated to OE config | `test_resume_config_override_single` | Planned |
| `run resume --config-override` | Multiple overrides applied cumulatively | `test_resume_config_override_multiple` | Planned |
| `infra build_config` | `rewrite_mode=True` sets `diff_based_evolution=false`, `max_code_length=50000` | `test_build_config_rewrite_mode` | Planned |
| `infra build_config` | `rewrite_mode=True` + `max_code_length` override → override wins | `test_build_config_rewrite_mode_override_wins` | Planned |
| `run start --rewrite-mode` | `--dry-run --rewrite-mode` shows `diff_based_evolution: false` | `test_run_dry_run_rewrite_mode` | Planned |
| `core.run` | `valid_iterations=0` after OE → run status `failed` | `test_run_all_errors_status_failed` | Planned |
| `core.run` | `valid_iterations=1`, `total=20` → status `completed_with_errors` | `test_run_low_valid_ratio_status_completed_with_errors` | Planned |
| `core.run` | `valid_iterations=15`, `total=20` → status `completed` | `test_run_normal_valid_ratio_status_completed` | Planned |
| `run list` | Zombie run (dead PID) detected and marked `interrupted` | `test_run_list_detects_zombie` | Planned |
| `run list` | Non-zombie run (alive PID) not changed | `test_run_list_no_false_positive_zombie` | Planned |
| `run cleanup` | `--force` marks zombies and reports count | `test_run_cleanup_force` | Planned |
| `run cleanup` | No zombies → "No zombie runs found" message | `test_run_cleanup_no_zombies` | Planned |
| `run population` | Parses checkpoint `database.json`, displays programs table | `test_run_population_shows_table` | Planned |
| `run population` | `--json` outputs array | `test_run_population_json_output` | Planned |
| `run population` | Non-existent run → RevolverError | `test_run_population_run_not_found` | Planned |
| `run population` | Run with no checkpoint → RevolverError | `test_run_population_no_checkpoint` | Planned |

**Cumulative L2 tests at sprint end: ~933 total (~909 previous + ~24 new)**

---

## PR Decomposition

| PR | Bloc | Tasks | Files modified | Depends on | Parallelizable? |
|---|---|---|---|---|---|
| PR-A | Bloc C (B8 filter) | S10-01 | `infra/openevolve.py` | — | Yes |
| PR-B | Bloc C (B12 llm update) | S10-02, S10-03, S10-04 | `infra/db.py`, `core/llm.py`, `cli/llm.py` | — | Yes |
| PR-C | Bloc A (resume --llm + --config-override) | S10-05, S10-06, S10-07, S10-08 | `core/run.py`, `cli/run.py` | — | Yes |
| PR-D | Bloc C (F4 --rewrite-mode) | S10-09, S10-10, S10-11 | `infra/openevolve.py`, `core/run.py`, `cli/run.py` | — | Yes, but conflicts with PR-C on same files |
| PR-E | Bloc B (B9 error status) | S10-12 | `core/run.py` | — | Yes |
| PR-F | Bloc B (B14 zombie cleanup) | S10-13, S10-14, S10-15 | `core/run.py`, `cli/run.py` | — | Conflicts with PR-C/PR-D/PR-E |
| PR-G | Bloc D (B13 population) | S10-16 | `core/run.py`, `cli/run.py` | — | Conflicts with PR-C/PR-D/PR-E/PR-F |
| PR-H | Docs + Tests | S10-17, S10-18, S10-19 | `docs/guides/*.md`, `tests/` | PR-A..PR-G merged | Sequential last |

**Recommended merge order for `run.py`-touching PRs**: PR-E first (smallest change), then PR-C, then PR-D, then PR-F, then PR-G.

---

## Parallelization

### Dependency graph

```
Sprint 009a complete ──┬──> S10-01 (infra: filter Revolver keys)           ← independent, PR-A
                        │
                        ├──> S10-02 (infra: db update_llm model)            ← independent
                        │         ↓
                        │    S10-03 (domain: core llm update_llm model)
                        │         ↓
                        │    S10-04 (cli: llm update --model)              ← PR-B
                        │
                        ├──> S10-05 (domain: resume_run llm_name)           ← independent
                        │         ↓
                        │    S10-06 (cli: run resume --llm)
                        ├──> S10-07 (domain: resume_run config_overrides)   ← independent
                        │         ↓
                        │    S10-08 (cli: run resume --config-override)    ← PR-C
                        │         (S10-05 + S10-07 can be in same PR)
                        │
                        ├──> S10-09 (infra: build_config rewrite_mode)      ← independent
                        │         ↓
                        │    S10-10 (domain: launch_run/resume_run rewrite_mode)
                        │         ↓
                        │    S10-11 (cli: --rewrite-mode flag)             ← PR-D
                        │
                        ├──> S10-12 (domain: error status threshold)        ← independent, PR-E
                        │
                        ├──> S10-13 (domain: detect_zombie_runs)            ← independent
                        │         ↓
                        │    S10-14 (cli: run list zombie detection)
                        │         ↓
                        │    S10-15 (cli: run cleanup command)             ← PR-F
                        │
                        ├──> S10-16 (domain+cli: run population)            ← independent, PR-G
                        │
                        └──> S10-17/18 (docs) ← independent, PR-H
                                  ↓
                             S10-19 (tests) ← depends on all PRs merged
```

### Critical path

Sprint 009a → S10-05/S10-07 → S10-06/S10-08 → S10-19 (tests)

Estimated sequential depth: 3 steps.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Config filter (B8) | S10-01 | Sprint 009a done | Agent 1 |
| B — LLM update --model (B12) | S10-02, S10-03, S10-04 | Sprint 009a done | Agent 2 |
| C — Resume --llm + --config-override (B10/B11) | S10-05, S10-06, S10-07, S10-08 | Sprint 009a done | Agent 3 |
| D — Rewrite mode (F4) | S10-09, S10-10, S10-11 | Sprint 009a done | Agent 4 (or Agent 1 after PR-A) |
| E — Error status (B9) | S10-12 | Sprint 009a done | Agent 1 (after PR-A) or Agent 5 |
| F — Zombie cleanup (B14) | S10-13, S10-14, S10-15 | Sprint 009a done | Agent 2 (after PR-B) or Agent 5 |
| G — Population (B13) | S10-16 | Sprint 009a done | Agent 2 or Agent 6 |
| H — Docs + Tests | S10-17, S10-18, S10-19 | All PRs A-G merged | Any agent |

Peak parallelism: 4-6 agents after sprint start (Streams A, B, C, D, E/F/G simultaneously).

### Conflict risks

- **`src/revolver/core/run.py`** — Streams C (S10-05, S10-07), D (S10-10), E (S10-12), F (S10-13, S10-14), G (S10-16) all modify this file. Each change targets distinct functions (`resume_run`, `launch_run`, `list_runs`/new helper, new `get_population`). **Merge order**: PR-E → PR-C → PR-D → PR-F → PR-G.
- **`src/revolver/cli/run.py`** — Streams C (S10-06, S10-08), D (S10-11), F (S10-14, S10-15), G (S10-16 CLI part) all modify this file. Changes are in distinct command functions. Merge in same order as `core/run.py`.
- **`src/revolver/infra/openevolve.py`** — Stream A (S10-01) modifies `validate_oe_config()`; Stream D (S10-09) modifies `build_config()`. Non-overlapping functions, low conflict risk.

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / 24 new integration tests passing

### Demo-able features
- [ ] `revolver run resume --run <id> --llm pro --config-override reasoning_effort=low` — switch LLM and tune on resume
- [ ] `revolver run start --rewrite-mode` — full-rewrite mode in one flag
- [ ] `revolver run list` — zombie runs auto-marked as `interrupted` with count warning
- [ ] `revolver run cleanup` — explicit cleanup command
- [ ] `revolver run population <id>` — MAP-Elites population table
- [ ] A 100%-error run ends with status `failed`, not `completed`
- [ ] `revolver llm update flash --model gemini-2.5-flash-lite` — fix model name without delete/re-add
- [ ] `problem version` with `initial_program` / `timeout_per_instance` in config → no spurious warning

### Carry-over
_TBD at sprint end._
