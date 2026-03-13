# Sprint 002 — LLM Registration & Problem Versioning

**Status**: Planning
**Goal**: Deliver the `revolver llm` command group (global LLM registry with Ollama integration, GPU monitoring) and the `revolver problem` command group (evaluator testing in subprocess with timeout, immutable version snapshotting). These are two independent command groups that both depend only on Sprint 001 infrastructure.
**Demo**: Register a local Ollama LLM and a remote API LLM; test an evaluator against instances and a dataset; create an immutable problem version snapshot with SHA-256 manifest.

---

## Scope

### Command groups included
- `revolver llm {add,start,stop,status,list,remove}` — full implementation (DES-002)
- `revolver problem {test,version,versions}` — full implementation (DES-003)

### Key FRs covered

**LLM (18 FRs)**:
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

**Problem (15 FRs)**:
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
- FR-PRB-015 — `problem.md` injected into OpenEvolve system prompt at `run` time (implementation in Sprint 004)

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S2-01 | Implement `revolver.infra.ollama` — `OllamaClient` class (DES-002 §3): `health_check()`, `version()`, `list_local_models()`, `show_model()`, `pull_model()` (streaming), `delete_model()`, `list_running()`, `load_model()`, `unload_model()`, `wait_loaded()`, `health_prompt()`; all typed with dataclasses (`LocalModel`, `RunningModel`, `ModelInfo`, `PullProgress`) | infra | Sprint 001 | [ ] | Unit tests with mocked `httpx.Client`; all methods return expected types; connection error → `OllamaNotRunningError` |
| S2-02 | Implement `revolver.infra.gpu` — `get_gpu_info()` via `nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader,nounits`; returns `GpuInfo | None`; handles subprocess failure gracefully (DES-002 §4) | infra | Sprint 001 | [ ] | Unit test: parses known nvidia-smi CSV output correctly; returns None when nvidia-smi unavailable; raises no exceptions |
| S2-03 | Implement `revolver.models.llm` — `LLMEntry` (frozen), `LLMStatus`, `StartResult`, `StopResult`, `LLMStatusReport` Pydantic models (DES-002 architecture impact) | models | Sprint 001 | [ ] | Models validate all fields; `model_dump()` produces correct JSON; `frozen=True` on `LLMEntry` |
| S2-04 | Add LLM CRUD to `revolver.infra.db` — global DB initialization (separate from project DB: `~/.revolver/revolver.db`), `insert_llm()`, `get_llm(name)`, `list_llms()`, `delete_llm(name)`, `update_llm_stats(name, vram_mib, throughput_tps)` | infra | Sprint 001 | [ ] | Unit tests: all CRUD operations; global DB path resolves to `~/.revolver/revolver.db`; WAL mode active; `test_global_data_in_home` |
| S2-05 | Implement `revolver.core.llm` — `register_llm()`, `remove_llm()`, `start_llm()`, `stop_llm()`, `list_llms()`, `get_llm_status()` (DES-002 §5); handle all error cases: duplicate name, Ollama unavailable, model not found, timeout | domain | S2-01, S2-02, S2-03, S2-04 | [ ] | Unit tests with mocked infra; all 6 functions tested; `test_api_key_never_stored`, `test_model_pinned_by_digest`, `test_single_model_at_a_time` |
| S2-06 | Implement `revolver.cli.llm` — 6 Typer commands: `add`, `start`, `stop`, `status`, `list`, `remove` (DES-002 §6); wire to `core.llm`; format output via `infra.output.render()` | cli | S2-05 | [ ] | CliRunner tests for all 6 commands; exit 0 on success; exit 1/3/4 on expected errors |
| S2-07 | Implement `revolver.infra.evaluator_loader` — `load_evaluator(path) -> ModuleType`; uses `importlib.util`; validates `evaluate()` callable exists; raises `EvaluatorLoadError` if not (DES-003 §7) | infra | Sprint 001 | [ ] | Unit test: loads valid evaluator; raises on missing `evaluate()`; raises `FileNotFoundError` if path missing |
| S2-08 | Implement `revolver.infra.evaluator_runner` — subprocess-based instance evaluation: `run_instance(evaluator_path, program_path, instance_path, timeout_s) -> InstanceRunResult`; sets `REVOLVER_INSTANCE_PATH` + `REVOLVER_INSTANCE_ID` env vars; enforces timeout via `ProcessPoolExecutor`; handles exceptions and timeout (DES-006 DD-05) | infra | S2-07 | [ ] | Unit tests: successful evaluation returns metrics dict; timeout → `status="timeout"`; exception → `status="failed"` with error; env vars set in subprocess |
| S2-09 | Implement `revolver.models.problem` — `FileSnapshot` (frozen), `ProblemVersion` (frozen), `InstanceTestResult`, `TestResult` Pydantic models (DES-003 §3) | models | Sprint 001 | [ ] | Models validate; `frozen=True` on immutable entities; datetime fields serialize correctly |
| S2-10 | Add problem CRUD to `revolver.infra.db` — `insert_problem_version()`, `get_problem_version(tag)`, `list_problem_versions()` for the `problem_versions` table | infra | Sprint 001 | [ ] | Unit tests: insert/get/list operations; duplicate tag → SQLite UNIQUE constraint error |
| S2-11 | Implement `revolver.core.problem` — `test_problem()`, `create_version()`, `list_versions()`, `get_version()` (DES-003 §5); dual-mode evaluator detection; read-only snapshot files (0o444); manifest YAML write | domain | S2-07, S2-08, S2-09, S2-10 | [ ] | Unit tests with mocked infra; `test_per_instance_timeout`, `test_validates_return_dict`, `test_warns_missing_combined_score` |
| S2-12 | Implement `revolver.cli.problem` — 3 Typer commands: `test`, `version`, `versions` (DES-003 §6); wire to `core.problem`; progress bar for dataset test | cli | S2-11 | [ ] | CliRunner tests for all 3 commands; exit 4 on evaluator crash |
| S2-13 | Write L2 integration tests for `llm` (11 scenarios from val-integration-tests §2.2) | test | S2-06 | [ ] | All 11 LLM scenarios pass: `test_add_ollama_llm`, `test_add_remote_llm`, `test_add_openai_compat`, `test_add_duplicate_fails`, `test_list_after_adds`, `test_remove_existing`, `test_remove_nonexistent`, `test_status_shows_vram`, `test_start_loads_model`, `test_start_unloads_previous`, `test_stop_unloads_model` |
| S2-14 | Write L2 integration tests for `problem` (10 scenarios from val-integration-tests §2.3) | test | S2-12 | [ ] | All 10 problem scenarios pass: `test_test_single_instance`, `test_test_dataset`, `test_test_catches_evaluator_error`, `test_test_timeout`, `test_test_verbose_output`, `test_version_creates_snapshot`, `test_version_includes_problem_md`, `test_version_missing_file_fails`, `test_version_duplicate_tag_fails`, `test_versions_list` |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md §2.2–2.3` that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `llm add` (Ollama) | Register local LLM with `--pull`; digest stored | `test_add_ollama_llm` | Planned |
| `llm add` (API) | Register remote LLM with pricing; provider, cost fields stored | `test_add_remote_llm` | Planned |
| `llm add` (openai-compat) | Register custom endpoint; base_url stored | `test_add_openai_compat` | Planned |
| `llm add` | Duplicate name — exit code 1 | `test_add_duplicate_fails` | Planned |
| `llm list` | After 2 adds — both listed | `test_list_after_adds` | Planned |
| `llm remove` | Remove existing — DB entry removed | `test_remove_existing` | Planned |
| `llm remove` | Remove non-existent — exit code 1 | `test_remove_nonexistent` | Planned |
| `llm status` | Mock Ollama response — VRAM info, remote=ready | `test_status_shows_vram` | Planned |
| `llm start` | Mock Ollama load — success, health check | `test_start_loads_model` | Planned |
| `llm start` | Another model already loaded — previous unloaded first | `test_start_unloads_previous` | Planned |
| `llm stop` | Mock Ollama unload — success | `test_stop_unloads_model` | Planned |
| `problem test --instance` | Valid evaluator + single instance — metrics + exit 0 | `test_test_single_instance` | Planned |
| `problem test --dataset` | Valid evaluator + 3 instances — summary | `test_test_dataset` | Planned |
| `problem test` | Evaluator raises exception — exit 4, no crash | `test_test_catches_evaluator_error` | Planned |
| `problem test` | Instance exceeds timeout — timeout reported | `test_test_timeout` | Planned |
| `problem test --verbose` | Full stdout/stderr + traces | `test_test_verbose_output` | Planned |
| `problem version` | Create v1.0 — snapshot dir, manifest.yaml, DB entry, SHA-256 | `test_version_creates_snapshot` | Planned |
| `problem version` | `problem.md` present — included in snapshot | `test_version_includes_problem_md` | Planned |
| `problem version` | Missing `evaluator.py` — exit code 1 | `test_version_missing_file_fails` | Planned |
| `problem version` | Duplicate tag — exit code 1 | `test_version_duplicate_tag_fails` | Planned |
| `problem versions` | After 2 versions — both listed chronologically | `test_versions_list` | Planned |

**Cumulative L2 tests passing: 25 / 25 (sprints 001+002)**

---

## Parallelization

### Dependency graph

```
Sprint 001 (foundation) ──┬──> S2-01 (infra: OllamaClient)
                           │
                           ├──> S2-02 (infra: gpu)
                           │         \
                           ├──> S2-03 (models: llm) ────────────┐
                           │                                      │
                           ├──> S2-04 (infra: db/llm global) ───┼──> S2-05 (domain: llm)
                           │                                      │         ↓
                           │                              S2-06 (cli: llm)
                           │                                           ↓
                           │                              S2-13 (test: llm L2 — 11 scenarios)
                           │
                           ├──> S2-07 (infra: evaluator_loader)
                           │         ↓
                           ├──> S2-08 (infra: evaluator_runner)
                           │         \
                           ├──> S2-09 (models: problem) ─────────┐
                           │                                       │
                           └──> S2-10 (infra: db/problem) ───────┼──> S2-11 (domain: problem)
                                                                   │         ↓
                                                          S2-12 (cli: problem)
                                                                        ↓
                                                          S2-14 (test: problem L2 — 10 scenarios)
```

### Critical path
Sprint 001 → S2-01 + S2-04 → S2-05 → S2-06 → S2-13 (LLM critical path, 5 steps)
Sprint 001 → S2-07 → S2-08 → S2-11 → S2-12 → S2-14 (Problem critical path, 6 steps)

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — LLM infra + models | S2-01, S2-02, S2-03, S2-04 | Sprint 001 done | Agent 1 |
| B — Problem infra + models | S2-07, S2-08, S2-09, S2-10 | Sprint 001 done | Agent 2 |
| C — LLM domain + CLI + tests | S2-05, S2-06, S2-13 | Stream A done | Agent 1 |
| D — Problem domain + CLI + tests | S2-11, S2-12, S2-14 | Stream B done | Agent 2 |

Peak parallelism: 2 agents simultaneously across LLM and Problem streams.
Streams A and B can start in parallel immediately after Sprint 001.

### Conflict risks
- `infra/db.py` — Stream A adds global DB queries (llms table), Stream B adds project DB queries (problem_versions table); different tables but same file — coordinate merge or split into separate modules early
- `cli/__init__.py` — both streams register new Typer sub-apps (`llm` and `problem`); trivial merge but must not conflict on the same lines
- `infra/hashing.py` — Stream B reuses `file_hash()` and `compute_snapshot_hash()` from Sprint 001; no changes needed, read-only dependency

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- 0 / 21 integration tests passing (this sprint)
- 0 / 25 total cumulative integration tests

### Demo-able features
- [ ] `revolver llm add claude --provider anthropic --model claude-opus-4-6 --api-key-env ANTHROPIC_API_KEY`
- [ ] `revolver llm add codestral --source ollama --model codestral:22b --pull` (mocked Ollama)
- [ ] `revolver llm list` shows both LLMs
- [ ] `revolver llm status` shows VRAM info
- [ ] `revolver llm start codestral` / `revolver llm stop`
- [ ] `revolver problem test --instance instances/instance_001.json`
- [ ] `revolver problem test --dataset ./instances/` with progress bar
- [ ] `revolver problem version --tag v1.0 -m "Initial formulation"` creates snapshot
- [ ] `revolver problem versions` lists versions

### Carry-over
- FR-PRB-015 (`problem.md` → OpenEvolve system prompt injection) deferred to Sprint 004 per backlog
