# Sprint 001 — Foundation: Project Scaffolding, DB, Shared Infrastructure

**Status**: Planning
**Goal**: Establish the project skeleton (`pyproject.toml`, package layout, Typer root app), shared infrastructure modules (SQLite, hashing, config, output, store), Pydantic base models, typed exceptions, and the `revolver project init` command. This sprint delivers the foundation that every subsequent sprint depends on.
**Demo**: `revolver project init my-project` creates a working project with `.revolver/`, `project.yaml`, template files (`initial_program.py`, `evaluator.py`, `config.yaml`), and an initialized SQLite database. `revolver --help` displays the command structure.

---

## Scope

### Command groups included
- `revolver` (root) — Typer app skeleton with `--json`, `--verbose`, `--quiet` global options
- `revolver project init` — full implementation

### Key FRs covered
- FR-PRJ-001 — Create `.revolver/` directory with SQLite DB and subdirectories
- FR-PRJ-002 — Generate `project.yaml` with name, description, timestamp
- FR-PRJ-003 — Generate template `initial_program.py` with `EVOLVE-BLOCK` markers
- FR-PRJ-004 — Generate template `evaluator.py` with dual-mode pattern (`evaluate_instance` / `evaluate`)
- FR-PRJ-005 — Generate template `config.yaml` with OpenEvolve defaults
- FR-PRJ-006 — Refuse `init` if `.revolver/` already exists (exit code 1)
- FR-PRJ-007 — Support `--path` for new directory creation
- FR-PRJ-008 — Set `.revolver/` permissions to 700

### NFRs covered
- NFR-001 — Exit codes (0 success, non-zero failure)
- NFR-002 — `--help` on all commands
- NFR-003 — `--json` flag for JSON output
- NFR-004 — Errors to stderr
- NFR-007 — Single `revolver` command with subcommands
- NFR-010 — Project data in `.revolver/`
- NFR-013 — SQLite for metrics/lineage data
- NFR-014 — SHA-256 hashing
- NFR-016 — SQLite WAL mode
- NFR-051 — `.revolver/` directory permissions 700
- NFR-060 — pip-installable package (`pyproject.toml`)

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S1-01 | Create `pyproject.toml` with all declared dependencies (typer>=0.21, pydantic>=2, pyyaml, rich, httpx, openevolve) and `src/revolver/` layout; `__init__.py`, `__main__.py` entry point | project | — | [ ] | `pip install -e .` succeeds; `python -m revolver --help` runs; package imports work |
| S1-02 | Implement `revolver.cli.__init__` — root Typer app with `@app.callback()` for `--json`, `--verbose`, `--quiet`; global state via `typer.Context.obj`; register all future command groups via `app.add_typer()` stubs | cli | S1-01 | [ ] | `revolver --help` shows command structure; global options accessible via context |
| S1-03 | Implement `revolver.infra.db` — SQLite connection factory, WAL mode (`PRAGMA journal_mode=WAL`), foreign keys (`PRAGMA foreign_keys=ON`), full schema creation from DES-001 (all tables: problem_versions, datasets, dataset_instances, dataset_compat, runs, solutions, eval_metadata, eval_instances, benchmarks, benchmark_solutions, schema_version); migration framework | infra | S1-01 | [ ] | Unit test: project DB created with all tables; WAL mode confirmed; `schema_version.version = 1`; global DB (llms table) separate file |
| S1-04 | Implement `revolver.infra.hashing` — `file_hash(path) -> str`, `tree_hash(path) -> str`, `global_hash(instance_hashes) -> str`, `compute_snapshot_hash(files) -> str` (DES-003 §2.2.1, DES-004 §3) | infra | S1-01 | [ ] | Unit tests: deterministic SHA-256 for known inputs; sorted order; prefix "sha256:"; `test_sha256_used`, `test_per_instance_hashes`, `test_subdirectory_tree_hash`, `test_snapshot_hash_sha256`, `test_dataset_hash_computation` |
| S1-05 | Implement `revolver.infra.store` — `.revolver/` directory management: `find_project_root()` (walks upward), `init_project_store(path)`, `write_manifest(path, data)`, `read_manifest(path)`, subdirectory constants (problem/, datasets/, runs/) | infra | S1-01 | [ ] | Unit tests: `find_project_root()` walks upward correctly; raises `ProjectNotFoundError` if not found; creates dir structure with 700 permissions |
| S1-06 | Implement `revolver.infra.config` — 5-level config hierarchy resolution (defaults → `~/.revolver/config.yaml` → `project.yaml` → CLI args → `REVOLVER_*` env vars); `load_config()` → merged dict | infra | S1-01 | [ ] | Unit test: last-wins resolution confirmed across all 5 levels; env vars override CLI args override project config |
| S1-07 | Implement `revolver.infra.output` — `render(data, json_mode)` for human tables via `rich.Table` and JSON output via `json.dumps`; `render_error(msg)` to stderr; progress bar factory | infra | S1-01 | [ ] | Unit tests: human mode renders rich table; JSON mode dumps valid JSON dict; errors go to stderr |
| S1-08 | Implement `revolver.models.project` — `ProjectConfig` Pydantic model (frozen=True): name, description, created_at, revolver_version | models | S1-01 | [ ] | Model validates; `model_dump()` serializes; `model_validate()` from YAML dict; frozen prevents mutation |
| S1-09 | Implement typed exceptions hierarchy: `RevolverError` (base), `ProjectNotFoundError`, `IntegrityError`, `ResourceError`, `ExternalError`, `ValidationError`, `DuplicateNameError`; CLI error mapper: exception type → exit code (0-4) | domain/cli | S1-02 | [ ] | Unit test: each exception class maps to correct exit code per NFR-001 / specs §4.2 |
| S1-10 | Implement `revolver.core.project` — `init_project(path, name, description)`: create `.revolver/` (mode 700), initialize SQLite DB, write `project.yaml`, generate template files (`initial_program.py` with EVOLVE-BLOCK, `evaluator.py` with dual-mode, `config.yaml` with defaults) | domain | S1-03, S1-04, S1-05, S1-08 | [ ] | Integration test: all 4 L2 project scenarios pass |
| S1-11 | Implement `revolver.cli.project` — `project init` Typer command: positional `name`, `--path`, `--description`; calls `core.project.init_project()`; output via `infra.output.render()` | cli | S1-02, S1-09, S1-10 | [ ] | CliRunner: exit 0 on success; exit 1 on existing project; `--json` outputs valid JSON |
| S1-12 | Create test infrastructure: `tests/conftest.py` with `tmp_project` fixture; `tests/fixtures/` with `evaluator_simple.py` (returns `{"combined_score": len(solution)/100}`), `evaluator_legacy.py` (global `evaluate()`), `initial_program_simple.py` (EVOLVE-BLOCK), `problem_simple.md`, `config_simple.yaml`, `instances/` (3 JSON files), `instance_bad.json` | test | S1-01 | [ ] | Fixtures committed; `tmp_project` fixture creates initialized project; `CliRunner` wrapper available |
| S1-13 | Write L2 integration tests for `project init` (4 scenarios from val-integration-tests §2.1): happy path, existing project, `--path`, permissions | test | S1-11, S1-12 | [ ] | `test_init_creates_structure`, `test_init_existing_project_fails`, `test_init_with_path_option`, `test_init_directory_permissions` all pass |
| S1-14 | Write L1 unit tests for infra modules: `test_db.py` (`test_wal_mode_enabled`), `test_hashing.py` (all 5 hash tests), `test_store.py`, `test_config.py`, `test_output.py` | test | S1-03, S1-04, S1-05, S1-06, S1-07 | [ ] | Coverage >80% on all infra modules; CI runs cleanly |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md §2.1` that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `project init` | Create project in empty dir — `.revolver/`, `project.yaml`, `revolver.db` created | `test_init_creates_structure` | Planned |
| `project init` | Dir already has `.revolver/` — exit code 1, error message | `test_init_existing_project_fails` | Planned |
| `project init --path` | Create and init new dir at target path | `test_init_with_path_option` | Planned |
| `project init` | Check `.revolver/` permissions — mode 700 | `test_init_directory_permissions` | Planned |

**Cumulative L2 tests passing: 4 / 4 (this sprint)**

---

## Parallelization

### Dependency graph

```
S1-01 (pyproject.toml + package layout)
  │
  ├──> S1-02 (cli: root Typer app)
  │      ↓
  │    S1-09 (typed exceptions + error mapping)
  │      ↓
  │    S1-11 (cli: project init) ──────────────────┐
  │                                                  │
  ├──> S1-03 (infra: db) ──────┐                    │
  │                             │                    │
  ├──> S1-04 (infra: hashing)  ├──> S1-10 (domain)──┘
  │                             │         ↓
  ├──> S1-05 (infra: store) ───┘    S1-13 (test: L2 integration)
  │
  ├──> S1-06 (infra: config)           [parallel to domain stream]
  │
  ├──> S1-07 (infra: output)           [parallel to domain stream]
  │
  ├──> S1-08 (models: ProjectConfig)   [parallel to infra stream]
  │
  └──> S1-12 (test fixtures)
       ↓
     S1-14 (test: L1 unit tests) ← depends on S1-03..S1-07
```

### Critical path
S1-01 → S1-03 + S1-04 + S1-05 → S1-10 → S1-11 → S1-13

Estimated sequential depth: 5 steps.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Package scaffold + CLI skeleton | S1-01, S1-02, S1-09 | — (S1-01 first) | Agent 1 |
| B — Infra modules (concurrent) | S1-03, S1-04, S1-05, S1-06, S1-07 | S1-01 done | Agent 2 |
| C — Models + fixtures | S1-08, S1-12 | S1-01 done | Agent 3 |
| D — Domain + CLI + tests | S1-10, S1-11, S1-13, S1-14 | Streams A+B+C done | Agent 1 or 2 |

Peak parallelism: 3 agents simultaneously (after S1-01, before S1-10).

### Conflict risks
- `infra/db.py` — full schema is defined here; must be stable before S1-10; all future sprints build on this schema
- `cli/__init__.py` — root app and global callback; all future CLI modules import from here; stabilize early
- `pyproject.toml` — dependency additions from concurrent agents need coordination

---

## Sprint Review

**Completed**: 2026-03-14 (session 017)

### Tests passing
- 4 / 4 integration tests passing
- 64 total tests (30 infra L1 + 25 exceptions + 5 CLI + 4 L2 integration)
- Coverage: 95%

### Demo-able features
- [x] `revolver --help` shows command groups with global options
- [x] `revolver project init my-project` creates complete project structure
- [x] `revolver project init --path ./new-dir` creates and initializes new directory
- [x] `revolver project init my-project --json` outputs structured JSON
- [x] Re-init of existing project exits with code 1 and error message on stderr
- [x] `.revolver/` directory has 700 permissions

### PRs merged
- PR #1: Scaffold + CI (S1-01)
- PR #2: Infra + Models + Fixtures + L1 tests (S1-03..08, S1-12, S1-14)
- PR #3: CLI skeleton + Exceptions (S1-02, S1-09)
- PR #4: Project init domain + CLI + L2 tests (S1-10, S1-11, S1-13)

### Carry-over
- None — all 14 tasks completed
