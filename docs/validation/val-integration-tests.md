# Revolver — Integration Tests (Level 2)

**Version**: 0.1 — Initial draft
**Date**: 2026-03-13
**Status**: Draft
**Traceable to**: [Validation Overview](validation.md), [Specifications](../specs/specifications.md)

---

## 1. Scope

Integration tests exercise each CLI command end-to-end through Typer's `CliRunner`, with a real SQLite database and real filesystem (in `tmp_path`). External services (Ollama, LLM APIs, OpenEvolve) are mocked at the `revolver.infra` boundary.

Each `revolver <command> <subcommand>` gets at least one integration test validating the happy path and key error cases.

**28 commands** across 8 command groups + 2 top-level commands (`doctor`, `setup`).

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
| `llm add` (API) | Register remote LLM with pricing | DB entry, provider, cost fields, api-key-env name stored | FR-LLM-001, 017, 018 |
| `llm add` (openai-compat) | Register custom endpoint | DB entry, base_url stored | FR-LLM-016 |
| `llm add` | Duplicate name | Exit code 1 | — |
| `llm list` | After 2 adds | Both listed, correct columns | — |
| `llm remove` | Remove existing | DB entry removed | FR-LLM-014 |
| `llm remove` | Remove non-existent | Exit code 1 | — |
| `llm status` | Mock Ollama response | Status displayed, VRAM info, remote=ready if env set | FR-LLM-009, 015 |
| `llm start` | Mock Ollama load | Success message, VRAM info, health check | FR-LLM-006, 013 |
| `llm start` | Another model already loaded | Previous model unloaded first | FR-LLM-008 |
| `llm stop` | Mock Ollama unload | Success message | FR-LLM-007 |

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
| `run` | Unknown LLM name | Exit code 1 | FR-RUN-001 |
| `run` | Dataset integrity failure (tampered file) | Exit code 2, warning message | FR-RUN-004 |
| `run` | Dataset split=eval | Warning on stderr, run proceeds | FR-RUN-002 |
| `run` | Dataset incompatible with version | Warning on stderr, run proceeds | FR-RUN-003 |
| `run` | Completion with tokens | Token usage displayed, stored in DB | FR-RUN-028, 029 |
| `run` | LLM has pricing set | Estimated cost displayed | FR-RUN-030 |
| `run` | Post-run eval on train set | Rank-1 program evaluated, results in DB | FR-RUN-019, 020 |
| `run list` | After 2 runs | Both listed with status, filterable | FR-RUN-021 |
| `run info` | Existing run | Full details: lineage, tokens, solution, stored programs | FR-RUN-022 |
| `run resume` | Existing checkpoint | New run from parent, wrapper copied | FR-RUN-013, 024 |

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

### 2.10 Cross-Cutting

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
└── instance_bad.json           # Malformed: missing "jobs" key → triggers KeyError
```

**Principles**:
- Scenarios must be trivially fast (no real LLM, no real evolution)
- Fixtures are committed to the repo and versioned with the tests
- OpenEvolve is mocked at the `infra.openevolve` boundary — integration tests never run real evolution
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
  └── test_cross_cutting.py
  ```
- **Pattern**: each test creates a temporary project via `tmp_project` fixture, runs CLI commands through `CliRunner`, asserts on stdout/stderr/exit code and DB state
- **Markers**: `@pytest.mark.integration` — allows running unit-only or integration-only via `-m`
- **Speed**: full integration suite must run in under 2 minutes
- **No network**: all HTTP calls (Ollama, LLM APIs) are mocked via `mock_ollama` / `mock_openevolve` fixtures
