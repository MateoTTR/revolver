# Sprint 009a — Bugfix delta: Resume, Config validation, UX polish (v0.9.1)

**Status**: In Progress
**Goal**: Fix 5 bugs found during demo v0.9.0 that block or degrade the incremental-resume workflow and MAP-Elites configuration. Delivers a stable v0.9.1 release.
**Demo**: `revolver run resume --run <id> --iterations 200` resumes from the correct checkpoint and restores the MAP-Elites population; `revolver run --dry-run` displays the resolved OE config (islands, feature_dimensions, temperature); `config.yaml` with misplaced `num_islands` triggers a warning at `problem version` and at `run` start; the tuning guide shows correct `database:` namespacing.

---

## Source

- Demo feedback: `feedback.md` of the beamforming demo v0.9.0 (private demo repository)
- Predecessor: Sprint 009 (v0.9.0)
- Delta sprint — scope frozen by user before file creation

---

## Bugs fixed

| # | Bug | Severity | Root cause |
|---|---|---|---|
| B1 | Resume doesn't restore checkpoint | Blocking | `resume_run()` looks for `oe-checkpoint/` (nonexistent); correct path is `oe-output/checkpoints/checkpoint_N/` (highest N) |
| B2 | Config DB params silently ignored | Blocking | `num_islands`, `feature_dimensions`, etc. are under OE's `database:` namespace; top-level keys are unknown and silently dropped |
| B3 | `run resume` CLI missing `--iterations` | Important | Core `resume_run()` accepts the param but CLI never passes it |
| B4 | `run resume` CLI missing `--temperature` / `--parallel` | Important | Core `build_config()` accepts both but resume CLI path bypasses them |
| B6 | `--dry-run` doesn't show resolved OE config | Important | Dry-run only prints a short summary; OE config is never built or displayed |

## Bugs deferred

| # | Bug | Reason |
|---|---|---|
| B5 | `run list` column truncation | Cosmetic, exists since v0.6.0, separate scope |
| B7 | `valid_iterations` missing from `run info` | Nice-to-have, non-blocking |

---

## Scope

### Command groups affected

- `revolver run` — resume checkpoint fix, resume CLI flags, dry-run verbose
- `revolver problem` — OE config validation warning on `problem version`
- `revolver infra` — new `validate_oe_config()` function, `build_config()` `checkpoint_interval` guard
- `docs/guides` — `tuning-oe-config.md` namespace fix

### Key FRs covered

- FR-RUN-011 — Store OE checkpoint in run directory for resume capability
- FR-RUN-013 — `resume` creates a new run from parent checkpoint
- FR-RUN-023 — `--dry-run` validates all inputs and displays resolved config without launching
- FR-RUN-040 — `--temperature` overrides `llm.temperature` in resolved OE config
- FR-RUN-041 — `--parallel` overrides `evaluator.parallel_evaluations` in resolved OE config
- FR-PRB-006 — `version` creates immutable snapshot of config.yaml

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S9a-01 | `core/run.py:resume_run()` — Replace search for `oe-checkpoint/` with discovery of latest `oe-output/checkpoints/checkpoint_N/` (highest N by numeric sort). Update post-run `valid_iters` counting that searches the same path. | domain | — | [ ] | Resume passes `checkpoint_dir` pointing to the highest-N checkpoint; `valid_iters` counting uses the same resolved path; `RevolverError` raised if no checkpoint directory exists |
| S9a-02 | `infra/openevolve.py:build_config()` — After resolving `checkpoint_interval`: if `checkpoint_interval` > `iterations` (or OE default 100 > `iterations` when absent), emit a warning via `console.print("[yellow]Warning...")` and override `checkpoint_interval` to equal `iterations` to guarantee a final checkpoint. | infra | — | [ ] | `build_config(iterations=5)` with absent `checkpoint_interval` sets it to 5; same when explicitly > iterations; correct value kept when <= iterations; warning message printed |
| S9a-03 | `infra/openevolve.py` — New function `validate_oe_config(config_path: Path) -> list[str]`. Parse config YAML, attempt strict dacite parse against `OEConfig` excluding `output_dir` and `llm.api_key_env`. Return a list of warning strings for unknown keys (e.g. `"Unknown OE config key: num_islands (did you mean database.num_islands?)"` for known misplaced keys). | infra | — | [ ] | `validate_oe_config()` returns non-empty list for config with top-level `num_islands`; returns empty list for valid config; does not raise exceptions; at minimum detects the six known misplaced keys (`num_islands`, `migration_interval`, `population_size`, `feature_dimensions`, `feature_bins`, `elites_per_island`) |
| S9a-04 | `core/problem.py:create_version()` + `cli/problem.py` — After config.yaml snapshot, call `validate_oe_config()` with conditional import (`try: from revolver.infra.openevolve import validate_oe_config`; skip if OE not installed). Display each warning from the returned list in the CLI output. | domain + cli | S9a-03 | [ ] | `revolver problem version` with misplaced `num_islands` prints warning; proceeds without error; warning absent when config is valid; no crash when OE not installed |
| S9a-05 | `infra/openevolve.py:_init_controller()` — Before the non-strict `OEConfig.from_dict()` call, call `validate_oe_config()`. Print each returned warning. OE is guaranteed installed at this point. | infra | S9a-03 | [ ] | `revolver run` with misplaced `num_islands` in config.yaml prints warning before run starts; valid config prints nothing; does not block the run |
| S9a-06 | `cli/run.py:run_resume` — Add `--iterations INT`, `--temperature FLOAT`, `--parallel INT` flags to the `resume` subcommand. Validate `--temperature` range 0.0–2.0. Pass all three to `core/run.py:resume_run()`. | cli | S9a-07 | [ ] | `revolver run resume --help` lists all three flags; `revolver run resume --run X --iterations 200` passes 200 to core; `--temperature` and `--parallel` visible in `--help`; invalid temperature triggers exit 1 |
| S9a-07 | `core/run.py:resume_run()` — Add `temperature: float | None = None` and `parallel: int | None = None` parameters. Pass both to `build_config()` in the resume path alongside existing `iterations` override. | domain | — | [ ] | `resume_run(..., temperature=0.9, parallel=4)` passes values to `build_config`; `None` values leave existing config unchanged; `iterations` override already present continues to work |
| S9a-08 | `core/run.py:launch_run()` + `cli/run.py` — In dry-run mode, resolve the full OE config via `build_config()` and display key parameters: `iterations`, `checkpoint_interval`, `num_islands` (from `database`), `feature_dimensions` (from `database`), `temperature` (from `llm`), `parallel_evaluations` (from `evaluator`). Apply the same display logic in `resume` dry-run if applicable. | domain + cli | S9a-02 | [ ] | `revolver run --dry-run` output includes all six key params; `revolver run resume --dry-run` same; no OE process launched; parameters reflect CLI overrides (e.g. `--temperature`) |
| S9a-09 | `docs/guides/tuning-oe-config.md` — Fix all examples that place `num_islands`, `feature_dimensions`, `feature_bins`, `migration_interval`, `population_size`, `elites_per_island` at top-level. Move them under the `database:` namespace. Add a note box explaining the namespace requirement and the warning message users will see. | docs | — | [ ] | Every example in the guide uses `database:` namespace for the six params; a callout explains the mapping; guide links to `revolver problem version` warning behavior |
| S9a-10 | L2 integration tests — Write tests for each of the five bug fixes. See Integration Tests table below. | test | S9a-01..S9a-09 | [ ] | All 9 new test scenarios pass; no regression on existing test suite |

---

## Integration Tests (L2)

New scenarios added for Sprint 009a. All must pass at sprint end.

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `run resume` (internal) | `resume_run()` resolves highest-N checkpoint dir from `oe-output/checkpoints/` | `test_resume_finds_latest_checkpoint` | Planned |
| `run resume` (internal) | `resume_run()` raises `RevolverError` when no checkpoint directory exists | `test_resume_no_checkpoint_raises` | Planned |
| `infra build_config` | `checkpoint_interval` absent + `iterations=5` → override to 5, warning emitted | `test_build_config_checkpoint_interval_override` | Planned |
| `infra build_config` | `checkpoint_interval=50` + `iterations=10` → override to 10, warning emitted | `test_build_config_checkpoint_interval_gt_iterations` | Planned |
| `infra build_config` | `checkpoint_interval=10` + `iterations=50` → kept as 10, no warning | `test_build_config_checkpoint_interval_ok` | Planned |
| `infra validate_oe_config` | Config with top-level `num_islands` → returns warning about `database.num_islands` | `test_validate_oe_config_misplaced_num_islands` | Planned |
| `infra validate_oe_config` | Valid config (all keys under correct namespaces) → returns empty list | `test_validate_oe_config_valid` | Planned |
| `problem version` | Config with `num_islands` at top-level → `problem version` prints warning, succeeds | `test_problem_version_config_warning` | Planned |
| `run` (internal) | `_init_controller()` with misplaced key → warning printed before run | `test_run_init_config_warning` | Planned |
| `run resume --iterations` | `--iterations 200` passed through CLI to `resume_run()` | `test_resume_cli_iterations_flag` | Planned |
| `run resume --temperature` | `--temperature 0.9` passed through to `build_config()` in resume | `test_resume_cli_temperature_flag` | Planned |
| `run resume --parallel` | `--parallel 4` passed through to `build_config()` in resume | `test_resume_cli_parallel_flag` | Planned |
| `run --dry-run` | Displays `iterations`, `checkpoint_interval`, `num_islands`, `feature_dimensions`, `temperature`, `parallel_evaluations` | `test_run_dry_run_shows_resolved_config` | Planned |
| `run --dry-run` | `--temperature 0.5` reflected in dry-run output | `test_run_dry_run_temperature_override` | Planned |

**Cumulative L2 tests at sprint end: ~909 total (895 previous + ~14 new)**

---

## Parallelization

### Dependency graph

```
Sprint 009 complete ──┬──> S9a-01 (domain: resume checkpoint path)         ← independent
                       │         ↓
                       │    S9a-08 (domain+cli: dry-run verbose) ◄── also needs S9a-02
                       │
                       ├──> S9a-02 (infra: checkpoint_interval guard)       ← independent
                       │         ↓
                       │    S9a-08 (domain+cli: dry-run verbose)
                       │
                       ├──> S9a-03 (infra: validate_oe_config function)     ← independent
                       │         ↓
                       │    S9a-04 (domain+cli: problem version warning)     ← depends S9a-03
                       │         ↓
                       │    S9a-05 (infra: _init_controller warning)         ← depends S9a-03
                       │
                       ├──> S9a-07 (domain: resume_run temperature/parallel) ← independent
                       │         ↓
                       │    S9a-06 (cli: resume flags)                       ← depends S9a-07
                       │
                       ├──> S9a-09 (docs: tuning guide fix)                  ← fully independent
                       │
                       └──> S9a-10 (tests) ◄── all implementation tasks complete
```

### Critical path

Sprint 009 → S9a-03 → S9a-04 → S9a-10

Estimated sequential depth: 3 steps.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Resume checkpoint | S9a-01, S9a-02, S9a-08 | Sprint 009 done | Agent 1 |
| B — Config validation | S9a-03, S9a-04, S9a-05 | Sprint 009 done | Agent 2 |
| C — Resume CLI flags | S9a-07, S9a-06 | Sprint 009 done | Agent 3 |
| D — Docs | S9a-09 | Sprint 009 done | Agent 2 (after S9a-05) or Agent 3 (after S9a-06) |
| E — Tests | S9a-10 | All streams complete | Any agent |

Peak parallelism: 3 agents (Streams A, B, C simultaneously at sprint start).

### Conflict risks

- **`src/revolver/infra/openevolve.py`** — Streams A (S9a-02 modifies `build_config`) and B (S9a-03 adds `validate_oe_config`, S9a-05 modifies `_init_controller`) both touch this file. Coordinate: S9a-02 adds a guard block inside `build_config()` (additive); S9a-03 adds a new top-level function; S9a-05 inserts a call in `_init_controller()`. Changes are in distinct function bodies — low conflict risk. Merge A before B or apply both via separate non-overlapping hunks.
- **`src/revolver/core/run.py`** — Streams A (S9a-01, S9a-08) and C (S9a-07) both touch this file. S9a-01 modifies `resume_run()` checkpoint search; S9a-07 adds parameters to `resume_run()`; S9a-08 modifies `launch_run()` dry-run branch. All changes are in distinct functions or distinct regions of `resume_run()`. Merge C (S9a-07) before A (S9a-01) since S9a-01's changes and S9a-07's signature change are both in `resume_run()`.
- **`src/revolver/cli/run.py`** — Stream C (S9a-06) and Stream A (S9a-08 touches dry-run display in CLI) both modify this file. Apply A's dry-run change in the `run_start` command function; apply C's changes in the `run_resume` command function. Non-overlapping by function — coordinate merge order.

---

## PR Decomposition

| PR | Tasks | Files modified | Depends on |
|---|---|---|---|
| PR-A: Resume checkpoint fix | S9a-01, S9a-02 | `core/run.py`, `infra/openevolve.py` | — |
| PR-B: Config validation | S9a-03, S9a-04, S9a-05 | `infra/openevolve.py`, `core/problem.py`, `cli/problem.py` | — |
| PR-C: Resume CLI flags | S9a-06, S9a-07 | `cli/run.py`, `core/run.py` | — |
| PR-D: Dry-run verbose | S9a-08 | `core/run.py`, `cli/run.py` | — |
| PR-E: Guide fix + tests | S9a-09, S9a-10 | `docs/guides/tuning-oe-config.md`, `tests/` | PR-A, PR-B, PR-C, PR-D |

PR-A, PR-B, PR-C, PR-D are independent and can be developed and reviewed in parallel. PR-E depends on all four being merged into `develop` first.

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / 14 new integration tests passing

### Demo-able features
- [ ] `revolver run resume --run <id>` restores MAP-Elites population from `oe-output/checkpoints/checkpoint_N/`
- [ ] `revolver run resume --run <id> --iterations 200` resumes for an explicit additional iteration count
- [ ] `revolver run resume --run <id> --temperature 0.9 --parallel 4` tunes OE on resume
- [ ] `revolver problem version` with misplaced `num_islands` in config.yaml prints actionable warning
- [ ] `revolver run` with misplaced `num_islands` in config.yaml prints same warning before starting
- [ ] `revolver run --dry-run` displays resolved OE config: islands, feature_dimensions, temperature, parallel_evaluations
- [ ] `docs/guides/tuning-oe-config.md` examples all use `database:` namespace

### Carry-over
_TBD at sprint end._
