# Sprint 002 — LLM Registration & Problem Versioning

**Status**: Planning
**Goal**: Deliver the `revolver llm` command group (6 subcommands — register, start, stop, status, list, remove) and the `revolver problem` command group (3 subcommands — test, version, versions). These are two independent command groups that both depend only on Sprint 001 infrastructure. At sprint end, a user can register LLMs in the global DB, manage their Ollama lifecycle, test an evaluator against instances with subprocess isolation, and create immutable problem snapshots with SHA-256 manifest.
**Demo**: `revolver llm add claude-opus --provider anthropic --model claude-opus-4-6 --api-key-env ANTHROPIC_API_KEY` registers a remote LLM; `revolver llm list` shows it; `revolver problem test --instance tests/fixtures/instances/instance_001.json` validates an evaluator; `revolver problem version --tag v1.0 -m "Initial"` creates `.revolver/problem/v1.0/` with manifest.

---

## Scope

### Command groups included
- `revolver llm {add,start,stop,status,list,remove}` — full implementation (DES-002)
- `revolver problem {test,version,versions}` — full implementation (DES-003)

### Key FRs covered

**LLM**:
- FR-LLM-001 — Register remote LLMs (provider, model, API key env name)
- FR-LLM-002 — Register local Ollama LLMs
- FR-LLM-003 — Global SQLite storage (`~/.revolver/revolver.db`)
- FR-LLM-004 — Ollama `--pull` at registration time
- FR-LLM-005 — Store Ollama model digest for pinning
- FR-LLM-006 — `start` loads model into GPU via Ollama API
- FR-LLM-007 — `stop` unloads model from GPU
- FR-LLM-008 — Single-model-at-a-time enforcement (unload previous)
- FR-LLM-009 — `status` shows VRAM usage (nvidia-smi)
- FR-LLM-010 — Expose OpenAI-compatible base URL
- FR-LLM-011 — Warn when model VRAM > available VRAM
- FR-LLM-012 — Record measured throughput/VRAM after load
- FR-LLM-013 — Health check after `start` (minimal prompt)
- FR-LLM-014 — `remove` unregisters + optional model delete
- FR-LLM-015 — Remote LLM status: ready if api key env set, unconfigured otherwise
- FR-LLM-016 — `--provider openai-compat` for custom endpoints
- FR-LLM-017 — API keys never stored (only env var name)
- FR-LLM-018 — Optional pricing (`--input-cost`, `--output-cost` per M tokens)

**Problem**:
- FR-PRB-001 — `test --instance` invokes evaluator with `REVOLVER_INSTANCE_PATH` env var
- FR-PRB-002 — `test --dataset` iterates all instances, returns summary
- FR-PRB-003 — Catch and display evaluator exceptions without crashing
- FR-PRB-004 — Per-instance timeout enforcement (subprocess)
- FR-PRB-005 — Validate `dict[str, float]` return type with `combined_score` key
- FR-PRB-006 — `version` creates immutable snapshot of problem files
- FR-PRB-007 — SHA-256 hash of snapshot content
- FR-PRB-008 — Refuse duplicate version tags
- FR-PRB-009 — Write `manifest.yaml` with per-file hashes
- FR-PRB-010 — Fail clearly if required files (`evaluator.py`, `initial_program.py`, `config.yaml`) are missing
- FR-PRB-011 — `--verbose` shows full stdout/stderr and stack traces
- FR-PRB-012 — Progress bar when testing dataset (multiple instances)
- FR-PRB-013 — Warn if `combined_score` key is missing from return dict
- FR-PRB-014 — Include `problem.md` in snapshot if present
- FR-PRB-015 — `problem.md` injected into OpenEvolve system prompt at `run` time (implementation deferred to Sprint 004)

### NFRs covered
- NFR-001 — Exit codes (0 success, non-zero failure)
- NFR-002 — `--help` on all commands
- NFR-003 — `--json` flag for JSON output
- NFR-004 — Errors to stderr
- NFR-013 — SQLite for LLM registry (global DB)
- NFR-014 — SHA-256 hashing for problem snapshots
- NFR-020 — Full traceability (problem version hash anchors runs)
- NFR-050 — API keys never stored in files

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S2-01 | Implement `revolver.infra.ollama` — `OllamaClient` class (DES-002 §3): `health_check()`, `version()`, `list_local_models()`, `show_model()`, `pull_model()` (streaming iterator), `delete_model()`, `list_running()`, `load_model()`, `unload_model()`, `wait_loaded()`, `health_prompt()`; typed dataclasses `LocalModel`, `RunningModel`, `ModelInfo`, `PullProgress` (DES-002 §3.2); all HTTP errors mapped to domain exceptions (DES-002 §8) | infra | Sprint 001 | [ ] | Unit tests with mocked `httpx.Client`: all methods call correct endpoints; `pull_model()` yields `PullProgress`; `wait_loaded()` raises `TimeoutError` after N polls; `httpx.ConnectError` → `OllamaNotRunningError`; HTTP 404 → `ModelNotFoundError` |
| S2-02 | Implement `revolver.infra.gpu` — `GpuInfo` dataclass, `get_gpu_info() -> GpuInfo \| None` via `nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader,nounits` (DES-002 §4); handles missing `nvidia-smi` gracefully | infra | Sprint 001 | [ ] | Unit tests: parses known CSV output into correct `GpuInfo` fields; returns `None` when nvidia-smi absent; no exception raised in any case |
| S2-03 | Implement `revolver.models.llm` — `LLMEntry` (frozen Pydantic), `LLMStatus`, `StartResult`, `StopResult`, `LLMStatusReport` models (DES-002 §5); `source` field: `"local" \| "remote"`; pricing fields nullable (`input_cost_per_mtok`, `output_cost_per_mtok`) | models | Sprint 001 | [ ] | Models validate with valid data; `model_dump()` produces JSON matching DES-002 §3.2 / spec-llm §5 field names; `LLMEntry` frozen prevents mutation |
| S2-04 | Add LLM CRUD to `revolver.infra.db` — global DB initialization: create `~/.revolver/revolver.db` if not exists, WAL mode, `llms` table (DES-001 §4.1); functions: `insert_llm(entry)`, `get_llm(name) -> LLMEntry \| None`, `list_llms() -> list[LLMEntry]`, `delete_llm(name)`, `update_llm_stats(name, vram_mib, throughput_tps)` | infra | S2-03 | [ ] | Unit tests: CRUD round-trip on temp global DB; `insert_llm()` raises `DuplicateNameError` on name conflict; WAL mode confirmed; global DB path is `~/.revolver/revolver.db`; `test_api_key_env_stored_not_key_value` |
| S2-05 | Implement `revolver.core.llm` — 6 functions (DES-002 §5): `register_llm()`, `remove_llm()`, `start_llm()`, `stop_llm()`, `list_llms()`, `get_llm_status()`; all error paths handled: duplicate name → `DuplicateNameError`, Ollama down → `OllamaNotRunningError`, not found → `ResourceError`, timeout → `ModelLoadTimeoutError` | domain | S2-01, S2-02, S2-03, S2-04 | [ ] | Unit tests with fully mocked infra layer: `test_register_remote_llm_no_ollama_call`, `test_register_local_triggers_pull`, `test_model_pinned_by_digest`, `test_single_model_at_a_time_enforcement`, `test_api_key_never_stored`, `test_remote_status_ready_when_env_set` |
| S2-06 | Implement `revolver.cli.llm` — 6 Typer commands matching DES-002 §6 and spec-llm §2: `add` (validates `--source ollama` XOR `--provider`), `start`, `stop`, `status`, `list`, `remove`; format output via `infra.output.render()`; add `app.add_typer(llm_app)` in `cli/__init__.py` | cli | S2-05 | [ ] | CliRunner: `revolver llm --help` shows 6 subcommands; `revolver llm add` with valid args → exit 0; `--json` produces valid JSON on `list`, `status`, `add`; exit 1 on duplicate; exit 3 on Ollama down (mocked); exit 4 on pull failure (mocked) |
| S2-07 | Implement `revolver.infra.evaluator_loader` — `load_evaluator(path: Path) -> ModuleType` using `importlib.util.spec_from_file_location`; validates `evaluate()` callable exists; raises `EvaluatorLoadError` if callable absent or import fails; add `EvaluatorLoadError` to `revolver.exceptions` | infra | Sprint 001 | [ ] | Unit tests: loads `tests/fixtures/evaluator_simple.py` successfully; raises `EvaluatorLoadError` when `evaluate()` absent; raises `FileNotFoundError` on missing path |
| S2-08 | Implement `revolver.infra.evaluator_runner` — `run_instance(evaluator_path, program_path, instance_path, timeout_s) -> InstanceRunResult`; spawns worker via `concurrent.futures.ProcessPoolExecutor(max_workers=1)`; sets `REVOLVER_INSTANCE_PATH` and `REVOLVER_INSTANCE_ID` in child process; enforces timeout via `future.result(timeout=timeout_s)`; catches exception and timeout (DES-003 §2.1.1 DD-01) | infra | S2-07 | [ ] | Unit tests: successful evaluation returns `status="pass"` with metrics dict; evaluator exception → `status="fail"` with `error` field; `timeout_s=0.001` → `status="timeout"`; env vars present in subprocess |
| S2-09 | Implement `revolver.models.problem` — `FileSnapshot` (frozen), `ProblemVersion` (frozen), `InstanceTestResult`, `TestResult` Pydantic models (DES-003 §3); `InstanceTestResult.status` in `{"pass", "fail", "timeout"}`; `TestResult` fields: `total`, `passed`, `failed`, `mean_time_s`, `max_time_s` | models | Sprint 001 | [ ] | Models validate; frozen models reject mutation; `TestResult` serializes to JSON matching spec-problem §2.1 output schema; `ProblemVersion` datetime field round-trips correctly |
| S2-10 | Add problem CRUD to `revolver.infra.db` — `insert_problem_version(version)`, `get_problem_version(tag) -> ProblemVersion \| None`, `list_problem_versions() -> list[ProblemVersion]` for `problem_versions` table in project DB | infra | S2-09 | [ ] | Unit tests: insert + get round-trip; duplicate tag → `DuplicateNameError` (from UNIQUE constraint); `list_problem_versions()` returns ascending `created_at` order |
| S2-11 | Implement `revolver.core.problem` — `test_problem()`, `create_version()`, `list_versions()`, `get_version()` (DES-003 §5); `create_version()`: check required files, check tag uniqueness, `mkdir`, `shutil.copy2()`, `chmod(0o444)`, `file_hash()` per file, `compute_snapshot_hash()`, write `manifest.yaml` (read-only), `insert_problem_version()`; dual-mode evaluator detection (DES-003 §2.1 step 4) | domain | S2-07, S2-08, S2-09, S2-10 | [ ] | Unit tests with `tmp_project` fixture: `test_per_instance_timeout`, `test_validates_return_dict`, `test_warns_missing_combined_score`, `test_snapshot_files_read_only`, `test_manifest_yaml_content`, `test_duplicate_tag_rejected` |
| S2-12 | Implement `revolver.cli.problem` — 3 Typer commands: `test` (validates `--instance` XOR `--dataset`), `version`, `versions` (DES-003 §6); `test` shows progress bar via `infra.output` when `--dataset`; add `app.add_typer(problem_app)` in `cli/__init__.py` | cli | S2-11 | [ ] | CliRunner: `revolver problem --help` shows 3 subcommands; `test --instance` exit 0 on pass, exit 1 on fail; `test` without args exits 1 with usage error; `version --tag v1.0` exit 0; `--json` valid on all commands |
| S2-13 | Write L2 integration tests for `llm` — 11 scenarios from val-integration-tests §2.2; mock Ollama at `revolver.infra.ollama.OllamaClient` boundary using `pytest-mock`; tests in `tests/integration/test_llm.py` | test | S2-06 | [ ] | All 11 test functions pass: `test_llm_add_ollama_with_pull`, `test_llm_add_remote_with_pricing`, `test_llm_add_openai_compat`, `test_llm_add_duplicate_name`, `test_llm_list_after_two_adds`, `test_llm_remove_existing`, `test_llm_remove_nonexistent`, `test_llm_status_with_mock_ollama`, `test_llm_start_mock_load`, `test_llm_start_unloads_previous`, `test_llm_stop_mock_unload`; `@pytest.mark.integration` on each |
| S2-14 | Write L2 integration tests for `problem` — 10 scenarios from val-integration-tests §2.3; use existing `tests/fixtures/` evaluators and instances; tests in `tests/integration/test_problem.py` | test | S2-12 | [ ] | All 10 test functions pass: `test_problem_test_single_instance`, `test_problem_test_dataset`, `test_problem_test_evaluator_exception`, `test_problem_test_timeout`, `test_problem_test_verbose`, `test_problem_version_creates_snapshot`, `test_problem_version_includes_problem_md`, `test_problem_version_missing_evaluator`, `test_problem_version_duplicate_tag`, `test_problem_versions_list`; `@pytest.mark.integration` on each |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md §2.2–2.3` that must pass at sprint end:

### `revolver llm` (§2.2) — 11 scenarios

| Command | Scenario | Test function | Status |
|---|---|---|---|
| `llm add` (Ollama) | Register local LLM with `--pull` — DB entry, source=ollama, digest stored | `test_llm_add_ollama_with_pull` | Planned |
| `llm add` (API) | Register remote LLM with pricing — provider, cost fields, api-key-env stored | `test_llm_add_remote_with_pricing` | Planned |
| `llm add` (openai-compat) | Register custom endpoint — DB entry, base_url stored | `test_llm_add_openai_compat` | Planned |
| `llm add` | Duplicate name — exit code 1 | `test_llm_add_duplicate_name` | Planned |
| `llm list` | After 2 adds — both listed, correct columns | `test_llm_list_after_two_adds` | Planned |
| `llm remove` | Remove existing — DB entry removed | `test_llm_remove_existing` | Planned |
| `llm remove` | Remove non-existent — exit code 1 | `test_llm_remove_nonexistent` | Planned |
| `llm status` | Mock Ollama response — status displayed, VRAM info, remote=ready if env set | `test_llm_status_with_mock_ollama` | Planned |
| `llm start` | Mock Ollama load — success message, VRAM info, health check | `test_llm_start_mock_load` | Planned |
| `llm start` | Another model already loaded — previous unloaded first | `test_llm_start_unloads_previous` | Planned |
| `llm stop` | Mock Ollama unload — success message | `test_llm_stop_mock_unload` | Planned |

### `revolver problem` (§2.3) — 10 scenarios

| Command | Scenario | Test function | Status |
|---|---|---|---|
| `problem test --instance` | Valid evaluator + single instance — metrics output with `combined_score`, exit code 0 | `test_problem_test_single_instance` | Planned |
| `problem test --dataset` | Valid evaluator + 3 instances — summary with pass/fail counts | `test_problem_test_dataset` | Planned |
| `problem test` | Evaluator raises exception — exit code 4, error displayed, Revolver does not crash | `test_problem_test_evaluator_exception` | Planned |
| `problem test` | Instance exceeds timeout — timeout reported per instance | `test_problem_test_timeout` | Planned |
| `problem test --verbose` | Valid evaluator — full stdout/stderr and stack traces | `test_problem_test_verbose` | Planned |
| `problem version` | Create v1.0 from valid files — snapshot dir, manifest.yaml, DB entry, SHA-256 hash | `test_problem_version_creates_snapshot` | Planned |
| `problem version` | `problem.md` exists — included in snapshot | `test_problem_version_includes_problem_md` | Planned |
| `problem version` | Missing `evaluator.py` — exit code 1, clear error | `test_problem_version_missing_evaluator` | Planned |
| `problem version` | Duplicate tag — exit code 1 | `test_problem_version_duplicate_tag` | Planned |
| `problem versions` | After 2 versions — both listed chronologically | `test_problem_versions_list` | Planned |

**Cumulative L2 tests passing: 25 / 25 (4 from Sprint 001 + 21 this sprint)**

---

## Parallelization

### Dependency graph

```
Sprint 001 (foundation)
  │
  ├──> S2-01 (infra: OllamaClient) ─────────────────────────────┐
  │                                                               │
  ├──> S2-02 (infra: gpu) ──────────────────────────────────────┤
  │                                                               │
  ├──> S2-03 (models: llm) ──────> S2-04 (infra: db LLM CRUD) ──┴──> S2-05 (domain: llm)
  │                                                                           ↓
  │                                                               S2-06 (cli: llm)
  │                                                                           ↓
  │                                                               S2-13 (test: llm L2 — 11 scenarios)
  │
  ├──> S2-07 (infra: evaluator_loader) ──> S2-08 (infra: evaluator_runner) ─┐
  │                                                                            │
  ├──> S2-09 (models: problem) ──────> S2-10 (infra: db problem CRUD) ───────┴──> S2-11 (domain: problem)
  │                                                                                        ↓
  └─────────────────────────────────────────────────────────────      S2-12 (cli: problem)
                                                                                   ↓
                                                                       S2-14 (test: problem L2 — 10 scenarios)
```

### Critical path

**LLM path**: Sprint 001 → (S2-01 ∥ S2-03 → S2-04) → S2-05 → S2-06 → S2-13
Sequential depth: 5 steps (S2-01 and S2-03+S2-04 converge at S2-05)

**Problem path**: Sprint 001 → S2-07 → S2-08 → (S2-09 → S2-10 converge) → S2-11 → S2-12 → S2-14
Sequential depth: 6 steps — this is the longer path and determines minimum sprint duration.

Both paths are **fully independent** and can proceed in parallel from sprint start.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — LLM infra | S2-01 (OllamaClient), S2-02 (gpu), S2-03 (models.llm), S2-04 (db LLM CRUD) | Sprint 001 done | Agent 1 |
| B — Problem infra | S2-07 (evaluator_loader), S2-09 (models.problem) | Sprint 001 done | Agent 2 |
| B-seq | S2-08 (evaluator_runner), S2-10 (db problem CRUD) | S2-07 done (S2-08), S2-09 done (S2-10) | Agent 2 |
| C — LLM domain + CLI + tests | S2-05, S2-06, S2-13 | Stream A done | Agent 1 |
| D — Problem domain + CLI + tests | S2-11, S2-12, S2-14 | Streams B + B-seq done | Agent 2 |

Peak parallelism: 2 agents working independently after Sprint 001 (Streams A and B).
Internal to each stream, tasks are mostly sequential due to layer dependencies.

### Conflict risks

| Risk | Files at risk | Mitigation |
|---|---|---|
| Both streams extend `infra/db.py` | `src/revolver/infra/db.py` | Stream A adds global DB functions (LLM); Stream B adds project DB functions (problem). Different function groups, same file. Merge PR #5 (LLM infra) before starting PR #6 (problem infra) to avoid conflicts. |
| Both streams add Typer sub-apps to CLI root | `src/revolver/cli/__init__.py` | Trivial: one `app.add_typer(llm_app)` and one `app.add_typer(problem_app)` — coordinate by adding them in separate PRs (PR #7 adds LLM, PR #8 adds problem). |
| Both streams add to exceptions hierarchy | `src/revolver/exceptions.py` | S2-07 adds `EvaluatorLoadError`; LLM stream may add `OllamaNotRunningError`, `ModelNotFoundError`, etc. Keep both additions in separate PRs; exceptions file is small, conflicts are trivial to resolve. |

---

## PR Decomposition

Sprint 002 maps to **4 PRs** following Git Flow (`feature/s2-*` → `develop`). PRs #5 and #6 are pure infrastructure (no user-visible CLI) and can be developed in parallel. PRs #7 and #8 depend on their respective infra PRs.

### PR #5 — `feature/s2-infra-llm`

**Tasks**: S2-01, S2-02, S2-03, S2-04

**Deliverable**: Ollama HTTP client, GPU info module, LLM Pydantic models, global DB LLM CRUD. No CLI changes.

**Files**:
- `src/revolver/infra/ollama.py` (new)
- `src/revolver/infra/gpu.py` (new)
- `src/revolver/models/llm.py` (new)
- `src/revolver/infra/db.py` (extend: add global DB init + LLM CRUD)
- `tests/test_ollama.py`, `tests/test_gpu.py`, `tests/test_models_llm.py`, `tests/test_db_llm.py` (new)

### PR #6 — `feature/s2-infra-problem`

**Tasks**: S2-07, S2-08, S2-09, S2-10

**Deliverable**: Dynamic evaluator loader, subprocess evaluator runner, problem Pydantic models, problem DB CRUD. No CLI changes.

**Can start**: In parallel with PR #5 (no shared files at this layer).

**Files**:
- `src/revolver/infra/evaluator_loader.py` (new)
- `src/revolver/infra/evaluator_runner.py` (new)
- `src/revolver/models/problem.py` (new)
- `src/revolver/infra/db.py` (extend: add problem CRUD — merge PR #5 into `develop` first to avoid conflict)
- `src/revolver/exceptions.py` (extend: add `EvaluatorLoadError`)
- `tests/test_evaluator_loader.py`, `tests/test_evaluator_runner.py`, `tests/test_models_problem.py`, `tests/test_db_problem.py` (new)

### PR #7 — `feature/s2-llm-commands`

**Tasks**: S2-05, S2-06, S2-13

**Deliverable**: `revolver llm` fully functional (6 commands), 11 L2 integration tests passing.

**Depends on**: PR #5 merged to `develop`.

**Files**:
- `src/revolver/core/llm.py` (new)
- `src/revolver/cli/llm.py` (new)
- `src/revolver/cli/__init__.py` (add `app.add_typer(llm_app)`)
- `tests/integration/test_llm.py` (new — introduces `tests/integration/` directory)

### PR #8 — `feature/s2-problem-commands`

**Tasks**: S2-11, S2-12, S2-14

**Deliverable**: `revolver problem` fully functional (3 commands), 10 L2 integration tests passing.

**Depends on**: PR #6 merged to `develop`.

**Files**:
- `src/revolver/core/problem.py` (new)
- `src/revolver/cli/problem.py` (new)
- `src/revolver/cli/__init__.py` (add `app.add_typer(problem_app)`)
- `tests/integration/test_problem.py` (new)

**Note on test layout**: val-integration-tests §4 specifies `tests/integration/` as the directory for L2 tests. PR #7 introduces this directory. The existing `tests/test_project_integration.py` from Sprint 001 should be migrated to `tests/integration/test_project.py` as a cleanup task — either in PR #7 or as a separate carry-over PR.

---

## Fixtures Required

The existing `tests/fixtures/` from Sprint 001 already provides what is needed:

| Fixture | Used by | Already exists |
|---|---|---|
| `evaluator_simple.py` — `{"combined_score": len(solution) / 100}` | S2-13, S2-14: problem test scenarios | Yes |
| `evaluator_legacy.py` — global `evaluate()` | S2-14: legacy evaluator test | Yes |
| `initial_program_simple.py` — EVOLVE-BLOCK markers | S2-14: version creates snapshot | Yes |
| `instances/instance_001.json`, `instance_002.json`, `instance_003.json` | S2-14: dataset test | Yes |
| `instance_bad.json` — triggers `KeyError` | S2-14: evaluator exception test | Yes |

All additional fixtures are already committed:
- `config_simple.yaml` — minimal OpenEvolve config (already present)
- `problem_simple.md` — minimal problem description for `test_problem_version_includes_problem_md` (already present)

**Note on dual-mode detection**: Both `evaluator_simple.py` and `evaluator_legacy.py` currently expose only `evaluate()` (global mode). Neither has an `evaluate_instance()` function. DES-003 §2.1 step 4 describes detecting dual-mode evaluators at load time. PR #6 should add a third fixture `evaluator_dualmode.py` with both `evaluate_instance()` and `evaluate()` to cover this test path. This fixture can be added as part of S2-07 (evaluator_loader unit tests).

---

## Sprint Review

_To be filled at sprint end._

### Tests passing
- 0 / 21 integration tests passing (this sprint)
- 0 / 25 total cumulative L2 integration tests

### Demo-able features
- [ ] `revolver llm add claude --provider anthropic --model claude-opus-4-6 --api-key-env ANTHROPIC_API_KEY`
- [ ] `revolver llm add codestral --source ollama --model codestral:22b --pull` (mocked Ollama)
- [ ] `revolver llm list` shows both LLMs
- [ ] `revolver llm status` shows runtime state and VRAM info
- [ ] `revolver llm start codestral` / `revolver llm stop` (mocked Ollama)
- [ ] `revolver problem test --instance instances/instance_001.json` — metrics displayed
- [ ] `revolver problem test --dataset ./instances/` — progress bar + summary
- [ ] `revolver problem version --tag v1.0 -m "Initial formulation"` — snapshot created
- [ ] `revolver problem versions` — lists versions chronologically

### Carry-over
- FR-PRB-015 (`problem.md` injection into OpenEvolve system prompt) deferred to Sprint 004 per backlog
- Migrate `tests/test_project_integration.py` → `tests/integration/test_project.py` (test layout cleanup from Sprint 001)
