# Revolver — Integration Tests (Level 2)

**Version**: 0.1 — Initial draft
**Date**: 2026-03-13
**Status**: Draft
**Traceable to**: [Validation Overview](validation.md), [Specifications](../specs/specifications.md)

---

## 1. Scope

Integration tests exercise each CLI command end-to-end through Typer's `CliRunner`, with a real SQLite database and real filesystem (in `tmp_path`). External services (Ollama, LLM APIs, OpenEvolve) are mocked at the `revolver.infra` boundary.

Each `revolver <command> <subcommand>` gets at least one integration test validating the happy path and key error cases.

**33 commands** across 8 command groups + 2 top-level commands (`doctor`, `setup`).

### L2-OE: OpenEvolve Contract Tests

A separate sub-level (L2-OE) validates the contract between Revolver and the real OpenEvolve package. These tests import and exercise real OpenEvolve classes (`Config`, `Controller`) with test fixtures -- no LLM server or GPU required. They are skipped automatically when `openevolve` is not installed (via `pytest.importorskip`) and run as a **non-blocking** CI step.

L2-OE tests catch field-mapping bugs (e.g., `base_url` vs `api_base`) that are silently swallowed by `dacite.from_dict()` when the dict keys don't match OpenEvolve's dataclass fields.

### L2-Shinka: ShinkaEvolve Contract Tests (**implemented — S14**, ADR-007)

A mirror track for the ShinkaEvolve backend, delivered in S14 across three files:

- `tests/integration/test_shinka_wrapper.py` — the generated `evaluate.py` wrapper contract
  (`metrics.json`/`correct.json` output — the top silent-bug risk of the backend initiative):
  5 golden scenarios executed against the **real** `shinka.core.run_shinka_eval` plus the same
  5 scenarios against `ShinkaBackend.generate_wrapper()` output.
- `tests/integration/test_shinka_db.py` — `programs.sqlite` reading contract (token/cost
  collection from `metadata.api_costs` + nested `metadata.llm_result`, population ranking
  without MAP-Elites fields, valid count, progress) against the shared fixture factory
  (`tests/fixtures/programs_sqlite.py`, schema verified against shinka-evolve 0.0.7).
- `tests/integration/test_run_shinka.py` — CLI-level scenarios with a mocked
  `ShinkaEvolveRunner` (launch, dry-run, resume inheritance, token storage, population, and the
  zero-scored-programs regression guarding against bogus solution collection).

Auto-skip via `pytest.importorskip("shinka.database")`; non-blocking CI step like L2-OE. The
"shinka not installed" tests force un-importability via the shared `no_shinka` conftest fixture,
so the whole suite passes identically with or without the `[shinka]` extra installed.

**Backend impact on the existing matrix (ADR-007)**: the engine-neutral command tests (§2.1–2.4,
§2.6–2.9, and the `run list`/`info`/`delete`/`cleanup` rows of §2.5) are unaffected. The
engine-coupled rows of §2.5 (launch, resume, status active-path, population) get a per-backend
variant in S14. S13 (refactor, no behavior change) adds tests asserting `backend='openevolve'` is
recorded end-to-end by default.

---

## 2. Command Test Matrix

### 2.1 `revolver project`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `project init` | Create project in empty dir | Directory structure, project.yaml, revolver.db created | FR-PRJ-001..005 |
| `project init` | Dir already has `.revolver/` | Exit code 1, error message | FR-PRJ-006 |
| `project init --path` | Create and init new dir | Dir created at target path | FR-PRJ-007 |
| `project init` | Check `.revolver/` permissions | Mode 700 on `.revolver/` dir | FR-PRJ-008, NFR-051 |

### 2.2 `revolver llm`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `llm add` (Ollama) | Register local LLM with `--pull` | DB entry (global), source=ollama, digest stored | FR-LLM-002, 004, 005 |
| `llm add` (API) | Register remote LLM | DB entry, provider, api-key-env name stored (pricing fields removed — #300) | FR-LLM-001, 017 |
| `llm add` (openai-compat) | Register custom endpoint | DB entry, base_url stored | FR-LLM-016 |
| `llm add` | Duplicate name | Exit code 1 | — |
| `llm list` | After 2 adds | Both listed, correct columns | — |
| `llm remove` | Remove existing | DB entry removed | FR-LLM-014 |
| `llm remove` | Remove non-existent | Exit code 1 | — |
| `llm status` | Mock Ollama response | Status displayed, VRAM info, remote=ready if env set | FR-LLM-009, 015 |
| `llm start` | Mock Ollama load | Success message, VRAM info, health check | FR-LLM-006, 013 |
| `llm start` | Another model already loaded | Previous model unloaded first | FR-LLM-008 |
| `llm stop` | Mock Ollama unload | Success message | FR-LLM-007 |
| `llm add --temperature 0.7` | Temperature stored in DB | DB entry includes temperature=0.7 | FR-LLM-019 |
| `llm update --temperature 1.0` | Temperature updated in DB | DB entry updated to temperature=1.0 | FR-LLM-019 |

### 2.2b `revolver llm ensemble`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `llm ensemble create` | Create named ensemble | DB entry created, 0 members | FR-LLM-020 |
| `llm ensemble add` | Add registered LLM with weight | Member row created, weight stored | FR-LLM-021 |
| `llm ensemble add` | Add non-existent LLM | Exit code 1, error message | FR-LLM-021 |
| `llm ensemble list` | After 2 creates | Both listed with member counts | FR-LLM-022 |
| `llm ensemble info` | Existing ensemble with 2 members | Members, weights, per-member overrides displayed | FR-LLM-023 |
| `llm ensemble remove` | Remove existing ensemble | DB entry and members cascade-deleted | FR-LLM-024 |
| `llm ensemble remove` | Remove non-existent ensemble | Exit code 1 | FR-LLM-024 |

### 2.2c Ensemble `build_config()` integration

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `run --dry-run --llm <ensemble>` | Ensemble resolves to `llm.models` array | OE config contains models array with correct fields | FR-RUN-046 |
| `run --dry-run --llm <ensemble>` | Per-member temperature override | OE config member has overridden temperature | FR-RUN-046 |

### 2.2d Run with ensemble

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `run --llm <ensemble>` | Full run with mocked OE | Run record stores `llm_type=ensemble` and `llm_snapshot` JSON | FR-RUN-044, 045 |
| `run info` | Ensemble run | Displays ensemble name and member models | FR-RUN-044 |
| `run resume --llm <ensemble>` | Override LLM on resume | New run uses ensemble config | FR-RUN-046 |
| `run` | Single LLM (no regression) | Run record stores `llm_type=single` and `llm_snapshot` JSON | FR-RUN-044, 045 |

### 2.3 `revolver problem`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `problem test --instance` | Valid evaluator + single instance | Metrics output (`dict[str, float]` with `combined_score`), exit code 0 | FR-PRB-001, 005 |
| `problem test --dataset` | Valid evaluator + 3 instances | Summary with pass/fail counts | FR-PRB-002 |
| `problem test` | Evaluator raises exception | Exit code 4, error displayed, Revolver does not crash | FR-PRB-003 |
| `problem test` | Instance exceeds timeout | Timeout reported per instance | FR-PRB-004 |
| `problem test --verbose` | Valid evaluator | Full stdout/stderr and stack traces | FR-PRB-011 |
| `problem version` | Create v1.0 from valid files | Snapshot dir, manifest.yaml, DB entry, SHA-256 hash | FR-PRB-006, 007, 009 |
| `problem version` | `problem.md` exists | Included in snapshot | FR-PRB-014 |
| `problem version` | Missing `evaluator.py` | Exit code 1, clear error | FR-PRB-010 |
| `problem version` | Duplicate tag | Exit code 1 | FR-PRB-008 |
| `problem versions` | After 2 versions | Both listed chronologically | — |

### 2.4 `revolver dataset`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `dataset add` | Valid directory, 3 JSON files | DB entry, per-instance hashes, global hash, absolute path, count=3 | FR-DAT-001..004 |
| `dataset add --snapshot` | Copy files into `.revolver/` | Snapshot dir created with copies | FR-DAT-005 |
| `dataset add --split train` | Specify split | Split stored in DB | FR-DAT-006 |
| `dataset add --split both` | Dual-use split | `both` accepted and stored (migration v11); usable for train and eval, no run split-warning | FR-DAT-006 |
| `dataset add --split bogus` | Invalid split | Exit code 1, "Must be 'train', 'eval', or 'both'" | FR-DAT-006 |
| `dataset add --compatible-with v1.0` | Declare compat | Compat entry in DB | FR-DAT-007 |
| `dataset add` | Non-existent path | Exit code 1 | — |
| `dataset add` | Duplicate name | Exit code 1 | FR-DAT-011 |
| `dataset list` | After 2 adds | Both listed with counts, splits | — |
| `dataset info` | Existing dataset | Detail view: hash, instances, compat | — |
| `dataset info --verify` | After modifying a file | Hash mismatch reported | FR-DAT-009 |
| `dataset update` | Add compat version | DB updated | FR-DAT-008 |
| `dataset remove` | Existing dataset, no references | DB entry + manifest removed | FR-DAT-014 |
| `dataset remove` | Dataset referenced by solution | Exit code 1 (blocked) | FR-DAT-015 |
| `dataset remove --force` | Force remove despite references | Removed | FR-DAT-015 |
| `dataset remove` | Snapshot storage | Copied files also deleted | FR-DAT-016 |

### 2.5 `revolver run`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `run` | Valid config, mocked OpenEvolve | Run dir created, DB entries (run + solution), lineage, env vars set | FR-RUN-001, 005..010 |
| `run --alias` | User-friendly name | Solution alias set | FR-RUN-012 |
| `run --dry-run` | Valid config | Config displayed, no run launched | FR-RUN-023 |
| `run --dry-run` | Pre-flight skipped | No pre-flight check executed | FR-RUN-023 |
| `run` | Unknown LLM name | Exit code 1 | FR-RUN-001 |
| `run` | Dataset integrity failure (tampered file) | Exit code 2, warning message | FR-RUN-004 |
| `run` | Dataset split=eval | Warning on stderr, run proceeds | FR-RUN-002 |
| `run` | Dataset incompatible with version | Warning on stderr, run proceeds | FR-RUN-003 |
| `run` | Completion with tokens | Token usage displayed (tokens only — **no cost**, #300), stored in DB | FR-RUN-028, 029 |
| `run` | Post-run eval on train set | Rank-1 program evaluated, results in DB | FR-RUN-019, 020 |
| `run` (pre-flight) | Evaluator returns score > 0 on first instance | Pre-flight passes, run proceeds | FR-RUN-001 |
| `run` (pre-flight) | Evaluator raises exception | Run aborts with RevolverError | FR-RUN-001 |
| `run` (pre-flight) | Evaluator hangs | Run aborts after 60s timeout | FR-RUN-001 |
| `run` (pre-flight) | Evaluator returns 0.0 | Warning emitted, run proceeds | FR-RUN-001 |
| `run` (collect) | Programs in `oe-output/best/` dir | `best_program.py` collected as rank-1.py | FR-RUN-008 |
| `run list` | After 2 runs | Both listed with status, filterable | FR-RUN-021 |
| `run info` | Existing run | Full details: lineage, tokens, solution, stored programs | FR-RUN-022 |
| `run resume` | Existing checkpoint | New run from parent, wrapper copied | FR-RUN-013, 024 |
| `run --temperature 0.5` | Temperature injected into OE config | OE config contains temperature=0.5 | FR-RUN-040 |
| `run --parallel 4` | Parallel evaluations injected into OE config | OE config contains num_parallel=4 | FR-RUN-041 |
| `run` (internal) | Post-processing failure | Status set to `completed_with_errors`, `run-error.log` written | FR-RUN-043, 032 |
| `run` (internal) | OE failure (regression) | Status set to `failed` | FR-RUN-031 |

### 2.6 `revolver eval`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `eval` | Valid solution + 3 instances | Per-instance results in DB, aggregates displayed | FR-EVL-001..006 |
| `eval` | One instance fails | Recorded as unsolved, eval continues | FR-EVL-010, 011 |
| `eval` | Non-existent solution | Exit code 1 | — |
| `eval` | Integrity check fails | Warning, eval proceeds | FR-EVL-007 |
| `eval` | Incompatible version | Warning on stderr | FR-EVL-008 |
| `eval` | Split=train (not eval) | Warning on stderr | FR-EVL-009 |
| `eval` | Results already exist | Confirmation required; `--force` skips | FR-EVL-018 |
| `eval results` | After eval, human mode | Aggregates + per-instance breakdown | FR-EVL-015, 016 |
| `eval results --json` | After eval, JSON mode | Full raw per-instance data | FR-EVL-017 |
| `eval` | Legacy evaluator (`evaluate()`) | Global aggregation call, `user_aggregates` stored | FR-EVL-019, 020 |
| `eval` | Evaluator with only `evaluate_instance()` | Per-instance function called correctly | FR-EVL-001, 002 |
| `eval` | Evaluator with only `evaluate()` (legacy) | Legacy global function called correctly | FR-EVL-019 |
| `eval` | Evaluator with both functions | Warning emitted, `evaluate()` used (legacy mode) | FR-EVL-019 |

### 2.7 `revolver solution`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `solution list` | After 2 runs | Solutions listed with ID, alias, version, LLM, score, rank | FR-SOL-001 |
| `solution list --version v1.0` | Filter by version | Only matching solutions | FR-SOL-002 |
| `solution info` | Existing solution | Full lineage (via run JOIN), program path, eval results if available | FR-SOL-003..005 |
| `solution info` | Solution with siblings | Other solutions from same run shown | FR-SOL-009 |
| `solution alias` | Set alias | DB updated, alias unique | FR-SOL-006, 007 |
| `solution alias` | Duplicate alias | Exit code 1 | FR-SOL-007 |
| `solution list` | Reference by alias | Alias works in filters | FR-SOL-008 |
| `solution extract` | Promote rank #2 from run | New solution entry in DB, unique ID | FR-SOL-011, 013 |
| `solution extract` | Same (run_id, rank) already extracted | Exit code 1, blocked | FR-SOL-012 |
| `solution delete` | Delete by alias | Removed from DB | FR-SOL-014 |
| `solution delete` | Delete by ID with `--force` | No confirmation prompt, removed | FR-SOL-015 |
| `solution delete` | Non-existent alias | Exit code 1 | — |
| `solution delete` | JSON mode without `--force` | Exit code 1 (interactive prompt forbidden) | FR-SOL-017 |
| `solution delete` | User cancels at prompt | No deletion | — |
| `solution delete` | Cascade-deletes eval data | Eval entries removed with solution | FR-SOL-016 |
| `solution extract` | `completed_with_errors` run with program | Extraction succeeds | FR-RUN-033 |
| `solution extract` | `interrupted` run | Extraction rejected | FR-RUN-033 |
| `solution show` | Display source code of existing solution on stdout | Source code printed to stdout | FR-SOL-018 |
| `solution show --json` | JSON output with alias and code fields | Valid JSON with alias and code keys | FR-SOL-018 |
| `solution show` | Exit 1 if alias not found | Exit code 1, error message | FR-SOL-018 |
| `solution export` | Copy program file to default path (`<alias>.py`) | File created at `<alias>.py` | FR-SOL-019 |
| `solution export -o <path>` | Copy to explicit path | File created at specified path | FR-SOL-019 |
| `solution export` | Exit 1 if alias not found | Exit code 1, error message | FR-SOL-019 |
| `solution diff` | Unified diff between two different solutions | Diff output on stdout | FR-SOL-020 |
| `solution diff` | Empty diff, exit 0 for identical solutions | No output, exit code 0 | FR-SOL-020 |
| `solution diff --json` | JSON with diff text and identical flag | Valid JSON with diff and identical fields | FR-SOL-020 |

### 2.8 `revolver benchmark`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `benchmark` | 2 solutions + eval dataset | Comparison table, DB entries, lineage included | FR-BEN-001, 004, 005, 006 |
| `benchmark` | One solution already evaluated | Reuses existing results, no redundant eval | FR-BEN-002 |
| `benchmark` | One solution not yet evaluated | Runs evaluation for that solution | FR-BEN-003 |
| `benchmark results` | After benchmark, human mode | Aggregate table with eval_time, instances_solved | FR-BEN-004, 009 |
| `benchmark results --per-instance` | Per-instance comparison | Side-by-side, best per instance highlighted | FR-BEN-014, 015 |
| `benchmark export --format csv` | After benchmark | Valid CSV, no secrets, run_id included | FR-BEN-007, 013, 017 |
| `benchmark export --format json` | After benchmark | Valid JSON matching ConOps §8.2 schema | FR-BEN-008 |
| `benchmark export --per-instance` | Raw data export | Per-instance rows for all solutions | FR-BEN-016 |
| `benchmark list` | After 2 benchmarks | Both listed with date, dataset, solution count | FR-BEN-012 |

### 2.9 `revolver doctor` / `revolver setup`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `doctor` | All deps present (mocked) | All checks pass, versions reported | FR-SET-001..005, 013 |
| `doctor` | Ollama missing | Warn/fail status, actionable message | FR-SET-003, 005, 006 |
| `doctor` | Outside project dir | Still works (global health check) | FR-SET-012 |
| `setup --dry-run` | Missing OpenEvolve | Preview of install commands | FR-SET-011 |
| `setup` | Missing pip package | Installs via pip, asks confirmation | FR-SET-007, 008 |
| `setup` | System-level dep missing | Instructions only, never installs | FR-SET-009, 010 |
| `setup` | Conda available, Ollama missing | Proposes `conda install conda-forge::ollama` | FR-SET-015, 016 |
| `setup` | No conda, Ollama missing | Manual instructions, suggests conda activation | FR-SET-017 |

### 2.10 L2-OE: `revolver run` — OpenEvolve Contract

These tests use real OpenEvolve classes (`Config`, `Controller`) and are located in `tests/integration/test_run_oe.py`. They are marked with `@pytest.mark.openevolve` and skipped when `openevolve` is not installed.

| Test | Scenario | Validates | FRs |
|---|---|---|---|
| `test_build_config_roundtrip_to_oe_config` | `build_config()` dict round-trips through `OEConfig.from_dict()` | Field mapping: `api_base`, `primary_model`, `max_iterations`, `system_message` | FR-RUN-005, FR-RUN-006 |
| `test_oe_controller_instantiation` | Real `OpenEvolve(program, evaluator, config, output_dir)` with fixtures | Controller accepts our config and fixture files without crash | FR-RUN-001 |
| `test_openevolve_runner_init_controller` | `OpenEvolveRunner._init_controller()` with real OpenEvolve | The exact code path that crashed in v0.4.0 works end-to-end | FR-RUN-005, FR-RUN-006 |
| `test_build_config_local_llm_api_key` | `build_config()` with local LLM | `api_key="ollama"` injected in config | FR-RUN-006 |
| `test_build_config_cascade_evaluation_default` | `build_config()` default output | `evaluator.cascade_evaluation=false` | FR-RUN-006 |
| `test_build_config_cascade_evaluation_override` | User config.yaml has `cascade_evaluation: true` | User override preserved in merged config | FR-RUN-006 |
| `test_best_score_from_program` | Program object with metrics | Score extracted from `Program.metrics` | FR-RUN-008 |

### 2.11 Cross-Cutting

| Scenario | Validates | FRs / NFRs |
|---|---|---|
| Any command with `--json` | Valid JSON to stdout, no human formatting | NFR-003 |
| Any command with `--help` | Usage text displayed | NFR-002 |
| Any error case | Message on stderr, correct exit code (0-4) | NFR-001, 004 |
| Any state-modifying command | Confirmation summary displayed | NFR-006 |
| Progress on long commands | Progress indicator on stderr | NFR-005 |
| `revolver` (root) | Subcommand structure accessible | NFR-007 |

---

## 3. Test Data

Integration tests use a **minimal test fixture set** stored in `tests/fixtures/`:

```
tests/fixtures/
├── evaluator_simple.py         # Trivial evaluator: returns {"combined_score": len(solution) / 100}
├── evaluator_legacy.py         # Legacy evaluator with evaluate() (global mode) for FR-EVL-019
├── initial_program_simple.py   # Trivial program with EVOLVE-BLOCK markers
├── problem_simple.md           # Minimal problem description
├── config_simple.yaml          # OpenEvolve config with 1 iteration
├── instances/                  # 3-5 tiny JSON instances
│   ├── instance_001.json       # {"jobs": [[1,2],[3,4]], "machines": 2}
│   ├── instance_002.json       # {"jobs": [[5,6]], "machines": 1}
│   └── instance_003.json       # {"jobs": [[1],[2],[3]], "machines": 3}
├── evaluator_instance.py       # Evaluator with only evaluate_instance() function
├── evaluator_both.py           # Evaluator with both evaluate() and evaluate_instance()
├── evaluator_neither.py        # Evaluator with neither function (triggers error)
└── instance_bad.json           # Malformed: missing "jobs" key → triggers KeyError
```

**Principles**:
- Scenarios must be trivially fast (no real LLM, no real evolution)
- Fixtures are committed to the repo and versioned with the tests
- OpenEvolve is mocked at the `infra.backends.openevolve` boundary — integration tests never run real evolution
- Mock OpenEvolve returns deterministic program code and scores

---

## 4. Conventions

- **File layout**: `tests/integration/` organized by command group
  ```
  tests/integration/
  ├── test_project.py
  ├── test_llm.py
  ├── test_problem.py
  ├── test_dataset.py
  ├── test_run.py
  ├── test_eval.py
  ├── test_solution.py
  ├── test_benchmark.py
  ├── test_doctor.py
  ├── test_setup.py
  ├── test_cross_cutting.py
  ├── test_run_shinka.py        # L2-Shinka CLI scenarios (implemented — S14, ADR-007)
  ├── test_shinka_wrapper.py    # L2-Shinka wrapper contract (implemented — S14)
  └── test_shinka_db.py         # L2-Shinka programs.sqlite contract (implemented — S14)
  ```
- **Pattern**: each test creates a temporary project via `tmp_project` fixture, runs CLI commands through `CliRunner`, asserts on stdout/stderr/exit code and DB state
- **Markers**: `@pytest.mark.integration` — allows running unit-only or integration-only via `-m`
- **Speed**: full integration suite must run in under 2 minutes
- **No network**: all HTTP calls (Ollama, LLM APIs) are mocked via `mock_ollama` / `mock_openevolve` fixtures
- **L2-OE tests**: use `pytest.importorskip("openevolve.config")` at module level for auto-skip when `openevolve` is not installed. Marked with `@pytest.mark.openevolve` in addition to `@pytest.mark.integration`. A dummy `OPENAI_API_KEY` is set via `monkeypatch` for tests that instantiate the OpenEvolve controller (it requires an API key even though no LLM call is made).
- **L2-Shinka tests** (implemented — S14): use `pytest.importorskip("shinka.database")` at module level for auto-skip when the `shinka` extra is not installed. Marked with `@pytest.mark.shinkaevolve` in addition to `@pytest.mark.integration`.
