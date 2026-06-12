# Sprint 014 — ShinkaEvolve MVP (P2, v0.14.0)

**Status**: Planning
**Goal**: Implement the real `ShinkaBackend` adapter (replacing the S13 stub) so that `revolver run --backend shinka` completes a genuine mini-evolution end-to-end; front-load the evaluator-wrapper contract tests (R4 risk) in the first wave.
**Demo**: `revolver run --backend shinka --iterations 3 --llm <local-model> ...` completes on a dev env with `pip install 'revolver[shinka]'`, writes `programs/rank-1.py` + manifest with `backend: shinka`, and the full downstream chain (`solution list`, `eval`, `benchmark`) is unaffected. The existing suite (1175+ tests) stays green on an env without Shinka installed.
**Source**: ADR-007 (P2 phase, decisions D1–D6), [shinka-topdown-267.md](../analysis/shinka-topdown-267.md) §6 (S14 scope), [shinka-backend-impact.md](../analysis/shinka-backend-impact.md) (risks R1-R4), sprint-013 carry-over.
**Predecessor**: Sprint 013 (v0.13.0) — backend abstraction, OE wrapped, Shinka stub.

---

## Source

- ADR: [ADR-007](../architecture/adr/ADR-007-pluggable-evolution-backend.md) — decisions D1–D6
- Analysis: [shinka-topdown-267.md](../analysis/shinka-topdown-267.md) §6 (S14 scope detail)
- Impact analysis: [shinka-backend-impact.md](../analysis/shinka-backend-impact.md) (risks R1-R4, sizing)
- Design: [DES-005 §14.1](../architecture/design/DES-005-run-orchestration.md) (backend mediation), [DES-006 §1.3](../architecture/design/DES-006-eval-loop.md) (per-backend evaluator contract)
- Specs: FR-RUN-047/048, NFR-024 (seed warning), NFR-061 (opt-in extra), FR-SET-002 (doctor)
- Validation: [val-integration-tests.md §L2-Shinka](../validation/val-integration-tests.md), [val-e2e-tests.md Scenario 3](../validation/val-e2e-tests.md)
- Sprint 013 carry-over: four seams to absorb (see below)

---

## Scope

### In scope

| Theme | Content |
|---|---|
| **pyproject.toml extra** | `[project.optional-dependencies] shinka = ["shinka-evolve>=0.0.7,<0.1"]`; test extras updated |
| **Orchestrator seam fixes (S13 carry-over)** | Neutral staging/output-dir hook; `_determine_crash_status()` dispatched via backend; iterations-fallback single-owner in orchestrator |
| **`infra/backends/shinka.py` — config + wrapper** | `build_config()` (single-LLM projection: `EvolutionConfig`/`DatabaseConfig`/`LocalJobConfig`; `llm_dynamic_selection="fixed"`; Python; `patch_types=["diff","full"]`); `resolved_config()`; `config_template()`; `validate_config()`; `generate_wrapper()` → Shinka `evaluate.py` calling `run_shinka_eval`, adapting `evaluate_instance()` over dataset |
| **`infra/backends/shinka.py` — engine + inspection** | `launch()` → `ShinkaEvolveRunner.run()`; `resume()` (reuse `results_dir`/`programs.sqlite`); `read_progress()` from `programs.sqlite`; `parse_population()` from DB; `count_valid()` from DB; `collect_token_usage()` reading per-program tokens (`metadata.llm_result.*`) + USD cost (`metadata.api_costs`) from DB; `is_available()` returns `(True, None)` when shinka importable |
| **Orchestrator neutralization** | `_determine_crash_status()` takes the backend and delegates counting; `output_dir` naming injected by the backend; iterations fallback owns one place; OE-specific path hard-codes guarded per-backend |
| **LLM projection (D5)** | Local Ollama → `local/<model>@<base_url>?api_key_env=…` syntax; remote → export provider-standard env var from Revolver's resolved key; document remote model-id constraint (pricing.csv recognition) |
| **`doctor` / `setup` / `project init`** | `is_available()` real (import-based); `pip install revolver[shinka]` path documented in setup entry; `config_template()` returns a Shinka-shaped scaffold |
| **Dry-run support** | `--backend shinka --dry-run` shows neutral `ResolvedConfig` with Shinka `backend_extras` |
| **L2-Shinka contract tests** | Mock-only: mocked `ShinkaEvolveRunner` + fixture `programs.sqlite`; `pytest.importorskip("shinka.database")`; non-blocking CI step (mirror L2-OE pattern) |
| **L3 E2E Scenario 3** | `tests/e2e/test_shinka_backend.py`; `@pytest.mark.e2e` + `pytest.importorskip("shinka.database")`; fake LLM server (local OpenAI-compat); non-blocking, nightly |

### Explicitly out of scope (S15)

- Ensemble → bandit mapping (weighted ensemble on Shinka backend)
- Prompt evolution, novelty judge, embedding model configuration
- Multi-language passthrough (non-Python programs)
- SLURM job config
- Full token-count parity for auxiliary Shinka LLM spend (embed/novelty/meta)
- Resume parity: cloning parent `programs.sqlite` + `gen_*` dirs into new run dir (S15)
- DES-005/006 title rename and full rewrite
- `infra/openevolve.py` re-export shim removal (S15)

---

## S13 Carry-Over Seams (must be absorbed in S14)

Four seams flagged in the S13 sprint review (review #188 W1/W2) and the S13 carry-over section:

1. **OE layout still hardcoded in orchestrator** — `_determine_crash_status()` calls `find_latest_checkpoint()` and `count_valid_programs()` directly on the OE checkpoint path (`oe-output/`) in `core/run.py`. For Shinka this would silently find nothing and mis-classify a crash. Fix: `_determine_crash_status()` must accept the resolved `backend` and delegate to `backend.count_valid(run_dir)`.

2. **Hard-coded `oe-output/` staging** — `core/run.py` currently writes `oe_output_dir = run_dir / "oe-output"` and sets `oe_config["output_dir"]`. For Shinka the output dir is `shinka-output/`. Fix: introduce `backend.output_dir_name()` (returns `"oe-output"` or `"shinka-output"`) **or** let `build_config()` return the correct `results_dir` key and have the orchestrator read it back. Simpler: add a `default_output_subdir: str` property to the backend (one-liner).

3. **Iterations fallback duplicated** — the fallback `iterations = config.iterations or oe_config.get("max_iterations", 10)` in `core/run.py` reads an OE-specific key. For Shinka the key is `num_generations`. Fix: the orchestrator should read the iterations from `spec.iterations` after `build_config()` populates it (or backends expose a `resolved_iterations(cfg) -> int` helper). Preferred: orchestrator resolves `iterations` before calling `build_config()` (passing it in `spec.iterations`), then reads `spec.iterations`; `build_config()` never needs to supply the fallback.

4. **Token path ready but native collection must be implemented** — `core/run.py` already calls `backend.collect_token_usage(run_dir)` when `not backend.wants_http_proxy()`. `ShinkaBackend.collect_token_usage()` must implement the DB query against `programs.sqlite` per the verified schema below (§"Verified shinka-evolve 0.0.7 schema facts"): tokens are nested under `metadata.llm_result`, USD cost is the top-level `metadata.api_costs` key.

---

## CI Strategy for L2-Shinka and L3 Scenario 3

The CI runner does **not** have `shinka-evolve` installed by default (mirrors the L2-OE situation).

Two tiers of Shinka tests are introduced:

| Tier | File(s) | Mechanism | Requires shinka | CI |
|---|---|---|---|---|
| **L2-Shinka contract** | `tests/integration/test_run_shinka.py` | Mocked `ShinkaEvolveRunner` + fixture `programs.sqlite` (pre-built); `pytest.importorskip("shinka.database")` at module level | Only for import-skip guard; mocks do the real work | Non-blocking step (same as L2-OE) |
| **L3 E2E Scenario 3** | `tests/e2e/test_shinka_backend.py` | Real `ShinkaEvolveRunner` + fake LLM server; `pytest.importorskip("shinka.database")` + `@pytest.mark.e2e` | Yes (real install) | Nightly, non-blocking |

Decision: **mock-only for contract tests, real-engine for E2E**. This mirrors the L2-OE pattern exactly and keeps the contract tests (which catch the R4 silent-bug risk) runnable without installing the engine — the mocked `ShinkaEvolveRunner` and the fixture `programs.sqlite` are enough to verify the wrapper's `metrics.json`/`correct.json` output format and the token-collection DB queries.

The fixture `programs.sqlite` is a pre-built SQLite file checked into `tests/fixtures/` with realistic program rows matching the verified 0.0.7 schema below. It is backend-version-agnostic and does not require a running Shinka process.

### Verified shinka-evolve 0.0.7 schema facts (checked in the `shinka-spike` env, session 049)

Source: `shinka/database/dbase.py` (`CREATE TABLE programs`), `shinka/core/async_runner.py` (metadata writers), `shinka/llm/providers/result.py` (`QueryResult.to_dict()`).

- The `programs` table has **no token or cost columns**. Tokens and costs live in the `metadata` column (JSON-serialized dict). Relevant other columns: `id TEXT PK`, `code`, `language`, `parent_id`, `generation INTEGER`, `combined_score REAL`, `public_metrics`/`private_metrics` (JSON), `correct BOOLEAN (0/1)`, `island_idx INTEGER`, `metadata TEXT (JSON)`.
- Per-program **USD cost** is the top-level metadata key **`api_costs`** (float; total across retry attempts; written for both LLM-generated and init programs; canonical — Shinka's own `_get_total_api_costs()` and display code read this key).
- Per-program **token counts** are nested under **`metadata.llm_result`** — the full `QueryResult.to_dict()` of the *last* LLM response: `input_tokens`, `output_tokens`, `thinking_tokens`, `cost`, `input_cost`, `output_cost`, `model_name`, `num_total_queries`, … `llm_result` may be `null` (failed attempts, file-based init program) — treat all fields as best-effort with default 0.
- `_extract_llm_metadata()` in `prompt_evolver.py` belongs to the **prompt-evolution** subsystem (separate `prompt_dbase.py` tables) — do NOT use it as the reference for program metadata keys.
- Extraction pattern for `collect_token_usage()`: `SELECT metadata FROM programs`, then per row `json.loads`: cost += `m.get("api_costs", 0.0)`; tokens += `(m.get("llm_result") or {}).get("input_tokens", 0)` etc. (or the `json_extract()` SQL equivalent: `$.api_costs`, `$.llm_result.input_tokens`).
- Note: `llm_result.cost` is the last-response cost only; `api_costs` includes retries — always use `api_costs` for USD totals. Token counts therefore slightly undercount on retried generations (acceptable best-effort per ADR-007 D2).

---

## Tasks

| # | Task | Layer | PR | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|---|
| S14-01 | `tests/fixtures/programs_sqlite.py` (or `conftest.py`): factory that creates a fixture `programs.sqlite` with 3–5 program rows (schema per §"Verified shinka-evolve 0.0.7 schema facts": `id`, `generation`, `combined_score`, `correct`, `public_metrics`, `private_metrics`, `metadata` JSON with top-level `api_costs` and nested `llm_result.{input_tokens,output_tokens,thinking_tokens}`; include one row with `llm_result: null` to cover the init-program case); stored at `tests/fixtures/shinka_programs.sqlite` or built in `tmp_path`. Companion `tests/fixtures/shinka_evaluate_py.py`: reference Shinka `evaluate.py` wrapper content for golden-file comparison. | test/infra | PR-A | — | [ ] | Fixture file usable by all L2-Shinka tests; schema matches `shinka-evolve 0.0.7` `dbase.py` |
| S14-02 | **R4 front-loaded**: `tests/integration/test_shinka_wrapper.py` — contract tests for `ShinkaBackend.generate_wrapper()`: (a) generated `evaluate.py` calls `run_shinka_eval` with correct args; (b) generated wrapper imports and calls `evaluate_instance()` (not `evaluate()`) from the user evaluator; (c) wrapper writes `metrics.json` (including `combined_score`) and `correct.json` to `results_dir`; (d) wrapper with a failing evaluator writes `correct: false`; (e) wrapper with missing `combined_score` in metrics raises or marks incorrect. Uses `pytest.importorskip("shinka.database")`; no real runner. | test | PR-A | S14-01 | [ ] | All 5 contract scenarios pass; auto-skipped when shinka not installed |
| S14-03 | `tests/integration/test_shinka_db.py` — contract tests for `ShinkaBackend` DB-reading methods: (a) `collect_token_usage()` sums tokens from `metadata.llm_result.*` and USD cost from `metadata.api_costs` across fixture DB rows (incl. the `llm_result: null` row → no crash, tokens counted as 0); (b) `parse_population()` returns programs ranked by `combined_score` desc, no `cell_indices` field; (c) `count_valid()` counts rows where `correct=1`; (d) `read_progress()` returns `(last_generation, best_combined_score)`. Uses fixture `programs.sqlite`; `pytest.importorskip("shinka.database")`. | test | PR-A | S14-01 | [ ] | All 4 DB-reading scenarios pass with fixture data; auto-skipped without shinka |
| S14-04 | `pyproject.toml`: add `[project.optional-dependencies] shinka = ["shinka-evolve>=0.0.7,<0.1"]`; update `[project.optional-dependencies] dev` / `test` to NOT include shinka (stays opt-in); add note in `[project]` metadata. Verify `pip install -e '.[shinka]'` clean install path. | infra | PR-A | — | [ ] | `pip install 'revolver[shinka]'` resolves without conflicts (confirmed by spike #266); `pip check` clean |
| S14-05 | **Orchestrator seam 2+3**: `core/run.py` — (a) replace hard-coded `oe-output` sub-dir with `backend.default_output_subdir` (or equivalent backend property); (b) resolve `iterations` before `build_config()`: pass `spec.iterations` non-None when `config.iterations` is set, else backend's default from its config schema; remove the dual `oe_config.get("max_iterations", 10)` fallback — one canonical resolution point in the orchestrator. No behavior change for OE. | domain | PR-B | — | [ ] | OE dry-run + launch tests still pass; the fallback line `cfg.get("max_iterations", 10)` is removed |
| S14-06 | **Orchestrator seam 1**: `core/run.py` — `_determine_crash_status()` accepts the `backend: EvolutionBackend` parameter and calls `backend.count_valid(run_dir)` instead of OE-specific `find_latest_checkpoint` + `count_valid_programs`. `OpenEvolveBackend.count_valid()` already wraps those; the crash-status logic in the orchestrator becomes backend-agnostic. | domain | PR-B | — | [ ] | `test_run_oe_failure_status` regression still passes; function signature updated with backward-compatible default |
| S14-07 | `infra/backends/shinka.py` — `is_available()`: attempt `import shinka.core` and return `(True, None)` on success, `(False, _INSTALL_HINT)` on `ImportError`; `config_template()`: return a Shinka-flavored `config.yaml` scaffold (sections `evo_config`, `db_config`, `job_config` with documented keys and defaults); `validate_config()`: dataclass-key check (attempt to instantiate `EvolutionConfig`/`DatabaseConfig` from config dict keys, return list of error strings). | infra | PR-B | S14-04 | [ ] | `is_available()` returns True in a shinka-installed env; template parseable as YAML; `validate_config` catches unknown keys |
| S14-08 | `infra/backends/shinka.py` — `build_config()`: translate `BackendRunSpec` into `EvolutionConfig`/`DatabaseConfig`/`LocalJobConfig` dicts (stored as nested dict, not dataclass instances, for YAML serialisation): `llm_models=[<model_string>]` (local → `local/<model>@<url>?api_key_env=…`, remote → model name + env var export); `llm_dynamic_selection="fixed"`; `num_generations=spec.iterations`; `task_sys_msg` from problem description; `patch_types=["diff","full"]`; `language="python"`; `results_dir=<run_dir>/shinka-output`; `num_islands` from config extras. `resolved_config()`: map to neutral `ResolvedConfig` with Shinka extras in `backend_extras`. | infra | PR-B | S14-04, S14-05 | [ ] | `build_config()` output contains correct key structure; `resolved_config()` neutral fields populated; no OE keys in output |
| S14-09 | `infra/backends/shinka.py` — `generate_wrapper()`: write `_shinka_evaluator.py` to `run_dir` that (a) is a valid Shinka CLI evaluator script (`argparse` / `sys.argv`: `--program_path`, `--results_dir`); (b) imports and calls user's `evaluate_instance()` over the dataset (env var `REVOLVER_DATASET_DIR`); (c) aggregates metrics (mean per key); (d) writes `results_dir/metrics.json` with `combined_score` and `results_dir/correct.json`. This task is the R4 risk materializer — its output is the contract tested in S14-02. | infra | PR-B | S14-04 | [ ] | Generated wrapper passes the S14-02 contract tests (run them against the real generated file); standalone execution writes well-formed JSON |
| S14-10 | `infra/backends/shinka.py` — `launch()`: construct `ShinkaEvolveRunner(evo_config=…, job_config=…, db_config=…)` from the config dict built in S14-08, passing `evaluate_str` (generated wrapper content) and `init_program_str` (initial program content); call `runner.run()` (sync wrapper); catch `RuntimeError` and re-raise as `ExternalError`. `default_output_subdir` property returns `"shinka-output"`. | infra | PR-C | S14-08, S14-09 | [ ] | With a mocked `ShinkaEvolveRunner`, `launch()` constructs the runner with correct args and calls `.run()`; `ExternalError` raised on `RuntimeError` |
| S14-11 | `infra/backends/shinka.py` — `collect_token_usage()`: open `run_dir/shinka-output/programs.sqlite`, `SELECT metadata FROM programs`, per-row `json.loads`: sum `metadata.api_costs` (USD, top-level) and `metadata.llm_result.{input_tokens,output_tokens,thinking_tokens}` (nested, best-effort, `llm_result` may be null — see §"Verified shinka-evolve 0.0.7 schema facts"); return `TokenUsage(prompt_tokens=..., completion_tokens=..., estimated_cost_usd=...)`. Handle missing DB (run failed before any programs) → return `None`. | infra | PR-C | S14-08 | [ ] | Contract test S14-03a passes against real implementation; `None` returned when DB absent |
| S14-12 | `infra/backends/shinka.py` — `parse_population()`, `count_valid()`, `read_progress()`: query `programs.sqlite` as verified by S14-03b/c/d; `parse_population()` returns list of dicts with `id`, `generation`, `combined_score`, `correct`, `public_metrics` — **no `cell_indices` or `island` fields** (warn in docstring that callers must not assume these). | infra | PR-C | S14-08 | [ ] | Contract tests S14-03b/c/d pass against real implementation |
| S14-13 | `infra/backends/shinka.py` — `resume()`: for Shinka, resume means reusing the existing `results_dir` (DB-driven: if `programs.sqlite` exists, `ShinkaEvolveRunner` auto-resumes from `last_iteration`). Implementation: same as `launch()` but do not create a new `shinka-output/` dir; instead point `results_dir` at the existing one in `parent_run_dir`. Note: full clone-based resume parity (copying `programs.sqlite` + `gen_*` dirs) is deferred to S15; the S14 implementation reuses the parent dir directly, which means resume creates a logical continuation but not a separate artifact tree. Document this limitation in the method docstring. | infra | PR-C | S14-10 | [ ] | `resume()` reuses `parent_run_dir/shinka-output`; a mocked runner receives the correct `results_dir`; behavior documented |
| S14-14 | `tests/integration/test_run_shinka.py` — L2-Shinka integration tests (mocked `ShinkaEvolveRunner` + fixture DB): (a) `test_shinka_launch_mocked`: `revolver run --backend shinka` with mocked runner completes, inserts run record with `backend='shinka'`, manifest written with `backend: shinka`; (b) `test_shinka_dry_run`: `--dry-run` shows Shinka `backend_extras` fields; (c) `test_shinka_resume_mocked`: resume inherits `backend='shinka'`, reuses parent `shinka-output/`; (d) `test_shinka_token_collection`: after a mocked run, `collect_token_usage()` reads fixture DB and stores tokens in run record; (e) `test_shinka_population_no_cell_indices`: `run population` for a Shinka run does not include `cell_indices`, exits 0. All auto-skip via `pytest.importorskip("shinka.database")`. | test | PR-C | S14-10, S14-11, S14-12 | [ ] | All 5 scenarios pass with shinka installed; auto-skipped without; existing OE tests unaffected |
| S14-15 | `core/doctor.py` + `core/setup.py`: `ShinkaBackend.is_available()` now returns `True` when shinka is installed — verify the doctor output changes from "informational (not installed)" to "OK (installed)" when the extra is present; `setup` entry lists `pip install 'revolver[shinka]'`. Also: `core/project.py` `config_template()` for Shinka returns the Shinka-shaped scaffold from S14-07; `core/problem.py` `validate_config` dispatches to `ShinkaBackend.validate_config()` when `--backend shinka` provided. | domain | PR-D | S14-07 | [ ] | `test_doctor_shinka_installed` (new) passes when shinka importable; `test_doctor_shinka_informational` (S13) still passes without shinka |
| S14-16 | `tests/e2e/test_shinka_backend.py` — L3 E2E Scenario 3 (Shinka happy path): full workflow mirror of Scenario 1 steps 1–13 using `--backend shinka`; fake LLM server registered as `local/<model>@http://localhost:<port>/v1`; 3 iterations; asserts `programs/rank-1.py` exists, manifest has `backend: shinka`, `solution list` shows solution, `eval` runs downstream. `@pytest.mark.e2e` + `pytest.importorskip("shinka.database")`. | test | PR-D | S14-10, S14-13, S14-14 | [ ] | Test file exists; passes with shinka installed + fake LLM server; auto-skipped without shinka |

---

## PR Grouping

### PR-A — Contract Test Fixtures + Package Extra (front-load R4 risk)

**Tasks**: S14-01, S14-02, S14-03, S14-04

Contents:
- `tests/fixtures/shinka_programs.sqlite` (pre-built fixture DB)
- `tests/fixtures/shinka_evaluate_py.py` (golden wrapper content helper)
- `tests/integration/test_shinka_wrapper.py` (R4 wrapper contract tests)
- `tests/integration/test_shinka_db.py` (DB-reading method contract tests)
- `pyproject.toml` optional extra

These tests will fail (stub raises `BackendUnavailableError`) until PR-B/C implement the real methods, but the fixture and test skeletons are established first. The test file for the wrapper tests can be merged as a `pytest.importorskip` module-level skip: they pass structurally once the implementation exists.

Alternatively: the wrapper tests in S14-02 can be written to import and call `generate_wrapper()` directly (unit-style) against the stub's placeholder — they will `xfail` until the implementation lands. This is the recommended approach so PR-A is independently mergeable.

### PR-B — Orchestrator Seam Fixes + Config/Wrapper Implementation

**Tasks**: S14-05, S14-06, S14-07, S14-08, S14-09

Contents:
- `core/run.py` seam fixes (output-dir neutralization, crash-status dispatch, iterations-fallback single owner)
- `infra/backends/shinka.py` — config tier: `is_available()`, `config_template()`, `validate_config()`, `build_config()`, `resolved_config()`, `generate_wrapper()`

This PR makes the contract tests from PR-A pass (the `generate_wrapper()` output satisfies S14-02; the config projection satisfies S14-08 assertions in unit tests). No real `ShinkaEvolveRunner` call yet.

### PR-C — Engine Integration + L2-Shinka Tests

**Tasks**: S14-10, S14-11, S14-12, S14-13, S14-14

Contents:
- `infra/backends/shinka.py` — engine tier: `launch()`, `resume()`, `collect_token_usage()`, `parse_population()`, `count_valid()`, `read_progress()`, `default_output_subdir`
- `tests/integration/test_run_shinka.py` — L2-Shinka mocked integration tests

This is the integration point where all Shinka backend methods are real. The L2-Shinka tests run in the same PR (mocked runner — no real shinka-evolve execution needed for CI).

### PR-D — Shims, Doctor, E2E

**Tasks**: S14-15, S14-16

Contents:
- `core/doctor.py` + `core/setup.py` + `core/project.py` + `core/problem.py` shim updates
- `tests/e2e/test_shinka_backend.py` — L3 Scenario 3

This PR closes the user-facing surface (doctor reports availability correctly, project init gives a Shinka config template) and adds the E2E scenario file.

---

## Integration Tests (L2)

Tests from `val-integration-tests.md` that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `run --backend shinka` | Full run with mocked runner, `backend='shinka'` in DB + manifest | `test_shinka_launch_mocked` | Planned |
| `run --backend shinka --dry-run` | Resolved config shows Shinka `backend_extras` | `test_shinka_dry_run` | Planned |
| `run resume` (shinka) | Resumed run inherits `backend='shinka'`, reuses parent `shinka-output/` | `test_shinka_resume_mocked` | Planned |
| `run` (shinka, post-run) | Token usage collected from fixture `programs.sqlite`, stored in DB | `test_shinka_token_collection` | Planned |
| `run population` (shinka) | Population output has no `cell_indices` field, exits 0 | `test_shinka_population_no_cell_indices` | Planned |
| `doctor` | ShinkaEvolve present → OK; absent → informational (unchanged) | `test_doctor_shinka_installed` / `test_doctor_shinka_informational` | Planned |
| Wrapper contract | Generated `evaluate.py` writes `metrics.json` + `correct.json` correctly | `test_shinka_wrapper_*` (5 cases) | Planned |
| DB reading contract | `collect_token_usage`, `parse_population`, `count_valid`, `read_progress` against fixture DB | `test_shinka_db_*` (4 cases) | Planned |
| Full OE suite | Existing 1175+ tests pass unmodified — zero regression | regression run | Planned |

---

## Parallelization

### Dependency graph

```
Sprint 013 complete (v0.13.0) ─────────────────────────────────────────────
          │
          ├──> PR-A (fixtures + extra + contract test skeletons)  ← independent
          │         │
          │         └── S14-01 ──> S14-02, S14-03 (parallel)
          │                         S14-04 (extra, independent)
          │
          ├──> PR-B (orchestrator seams + config/wrapper impl)    ← independent
          │         │
          │         ├── S14-05, S14-06 (orchestrator, parallel)
          │         └── S14-07 ──> S14-08 ──> S14-09              ← sequential (config → wrapper)
          │
          ├──────────── PR-C (engine integration + L2 tests)       ← needs PR-A + PR-B
          │                   │
          │                   ├── S14-10 (launch)
          │                   ├── S14-11, S14-12 (token + population, parallel, after S14-10)
          │                   ├── S14-13 (resume, after S14-10)
          │                   └── S14-14 (L2 tests, after S14-10..13)
          │
          └──────────── PR-D (shims + E2E)                         ← needs PR-B (S14-07); PR-C for E2E
                              │
                              ├── S14-15 (shims, after S14-07)
                              └── S14-16 (E2E, after PR-C)
```

### Critical path

```
S14-01 → S14-02/03 (PR-A)
    → S14-04 (extra, parallel with S14-01)
    → S14-07 → S14-08 → S14-09 (PR-B config chain)
    → S14-10 → S14-11 → S14-14 (PR-C engine chain)
    → S14-16 (PR-D E2E)
```

Minimum sequential depth: 7 tasks (S14-01 → S14-08 → S14-09 → S14-10 → S14-11 → S14-14 → S14-16).

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Fixtures & Extra | S14-01, S14-02, S14-03, S14-04 | Sprint 013 merged | Agent 1 |
| B1 — Orchestrator seams | S14-05, S14-06 | Sprint 013 merged | Agent 2 |
| B2 — Config + Wrapper | S14-07, S14-08, S14-09 | S14-04 done | Agent 2 (or Agent 3) |
| C — Engine + L2 tests | S14-10, S14-11, S14-12, S14-13, S14-14 | PR-A + PR-B merged | Agent 3 |
| D — Shims + E2E | S14-15 after S14-07; S14-16 after PR-C | PR-B (S14-07) + PR-C | Agent 4 |

Peak parallelism: 3 agents (streams A, B1, and B2 when B2 has a separate agent) in Wave 1.

### Wave structure

- **Wave 1 (parallel)**: PR-A, PR-B — 2–3 agents, no shared files
- **Wave 2 (parallel)**: PR-C (after A+B merged), PR-D/S14-15 (after B merged) — 2 agents
- **Wave 2 merge point**: PR-C and PR-D/S14-16 converge at the final integration test run

### Conflict risks

- **`pyproject.toml`** — S14-04 only (in PR-A). PR-B and later PRs do not touch it. No conflict.
- **`core/run.py`** — S14-05 and S14-06 (in PR-B). No other PR touches this file. No conflict.
- **`infra/backends/shinka.py`** — PR-B (config tier) and PR-C (engine tier) both extend this file. **Managed by wave ordering**: PR-B must be merged before PR-C starts. The implementation is additive (PR-B fills the stub methods for config/wrapper; PR-C fills the engine methods). No concurrent edit risk if the wave ordering is respected.
- **`core/doctor.py` + `core/setup.py`** — PR-D only (S14-15). None.
- **`tests/integration/test_run_shinka.py`** — new file, PR-C creates it. None.
- **`tests/e2e/test_shinka_backend.py`** — new file, PR-D creates it. None.

**Recommended merge order**: PR-A → PR-B → PR-C → PR-D. PR-A and PR-B can be reviewed in parallel; PR-C waits for both to merge.

---

## Exit Criteria

The sprint is complete when ALL of the following hold:

1. **End-to-end Shinka run**: `revolver run --backend shinka --iterations 3 --llm <local-or-fake> ...` completes (non-mock, real `ShinkaEvolveRunner`) in a dev env with `pip install -e '.[shinka]'`; run record has `backend='shinka'`; `programs/rank-1.py` written; manifest has `backend: shinka`.

2. **Full OE regression green**: the full existing test suite (1175+ tests) passes without modification on an env WITHOUT shinka installed; the 7 L2-OE skips are unchanged.

3. **L2-Shinka suite green**: all L2-Shinka contract tests (14 scenarios across wrapper + DB + integration test file) pass with shinka installed; auto-skip correctly activates without shinka.

4. **L3 Scenario 3 file exists and passes**: `tests/e2e/test_shinka_backend.py` exists, runs to completion with shinka installed + fake LLM server, auto-skips without shinka.

5. **Orchestrator seams resolved**: `_determine_crash_status()` no longer contains OE-specific path references; `oe-output` string no longer hard-coded in the orchestrator; iterations fallback has one canonical resolution point.

6. **`revolver doctor`**: correctly reports ShinkaEvolve as "OK" when installed, "informational (not installed)" when absent.

7. **Dry-run**: `revolver run --backend shinka --dry-run` exits 0, shows Shinka config template fields, no OE-specific keys in neutral section.

8. **`revolver[shinka]` extra** declared in `pyproject.toml`; `pip install 'revolver[shinka]'` installs cleanly (verified by spike #266).

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / Y L2-Shinka contract tests passing
- X / X existing (non-Shinka) tests passing (regression)

### Demo-able features
- [ ] `revolver run --backend shinka` completes a real mini-evolution
- [ ] `revolver run --backend shinka --dry-run` shows Shinka config surface
- [ ] `revolver doctor` correctly reports Shinka availability
- [ ] `solution list` / `eval` / `benchmark` work unchanged on Shinka-generated artifacts

### Carry-over
_Deferred items and open issues to feed into Sprint 015._
