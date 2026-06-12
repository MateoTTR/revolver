# Sprint 013 — Backend Abstraction Refactor (v0.13.0)

**Status**: Done — v0.13.0 (session 048; PRs #184/#185/#188/#189 merged)
**Goal**: Introduce the `EvolutionBackend` abstraction (ADR-007) behind the 4 engine-coupled commands and the 4 single-call shims, wrap the existing OpenEvolve code as `OpenEvolveBackend`, add `runs.backend` traceability (migration v9) and the `--backend` CLI flag — with **zero behavior change**: the full pre-existing L0/L1/L2 suite passes unmodified (imports excepted where files move).
**Source**: ADR-007 (P1 phase), top-down analysis #267 §6 (S13 plan) and §2.2 (interface), DES-005 §14.1, DES-001 §5.8, spec-run FR-RUN-047/048.
**Predecessor**: Sprint 012 (v0.12.0) + hotfix v0.12.1

---

## Source

- ADR: [ADR-007](../architecture/adr/ADR-007-pluggable-evolution-backend.md) — decisions D1–D6, roadmap S13→S15
- Analysis: [shinka-topdown-267.md](../analysis/shinka-topdown-267.md) §2.2 (refined `EvolutionBackend` interface), §6 (S13 scope)
- Design: [DES-005 §14.1](../architecture/design/DES-005-run-orchestration.md) (backend mediation), [DES-001 §5.8](../architecture/design/DES-001-sqlite-data-model.md) (migration v9)
- Specs: [spec-run.md](../../docs/specs/spec-run.md) FR-RUN-047/048 + error cases (`--backend` unknown → exit 1; shinka not installed → exit 3)
- Validation: [traceability-matrix.md](../validation/traceability-matrix.md) FR-RUN-047 planned tests

---

## Scope

### In scope

| Theme | Content |
|---|---|
| **Backend package** | `infra/backends/{base,openevolve,shinka}.py`: protocol + capabilities + factory; `OpenEvolveBackend` wraps the existing `infra/openevolve.py` code (move, don't rewrite); `ShinkaBackend` **stub only** (registered, reports not-installed) |
| **Core mediation** | `core/run.py` routes launch / resume / live-progress / population / token collection through `backend.*` |
| **Neutral config** | `models/run.py`: `ResolvedConfig` + `backend_extras` replaces `ResolvedOEConfig`; `backend` field on run models |
| **DB** | Migration v9: `runs.backend TEXT NOT NULL DEFAULT 'openevolve'` (backfills all pre-v9 runs correctly) |
| **CLI** | `--backend {openevolve,shinka}` on `run` (default `openevolve`); backend surfaced in `run info` / `run list` / dry-run (FR-RUN-047); backend-aware copy in progress/help text |
| **Shims** | `core/doctor.py` (per-backend availability, ShinkaEvolve informational), `core/setup.py` (install entries), `core/project.py` (config template via backend), `core/problem.py` (validate-config dispatch) |
| **Tests** | New L2 tests asserting `backend='openevolve'` default end-to-end; full regression green |

### Explicitly out of scope (S14/S15)

- **ShinkaBackend implementation** (config projection, `evaluate.py` wrapper, `programs.sqlite` parsing, `revolver[shinka]` extra in `pyproject.toml`) — S14
- L2-Shinka contract tests, E2E Scenario 3 — S14
- Ensemble→bandit mapping, top-N extraction capability, cost/token columns in `benchmark`, backend surfaced in `solution info`/`benchmark results` — S15
- DES-005/006 full rewrite and title rename — S15

### Recommendation — ShinkaBackend stub in S13 (not deferred)

Create `infra/backends/shinka.py` as a **stub registered in the factory**: `is_available()` returns `(False, "Install with pip install revolver[shinka]")`, `capabilities()` returns the ADR-007 matrix, every engine method raises a typed `BackendUnavailableError`. Rationale: the spec'd error paths (`--backend shinka` not installed → exit 3; unknown backend → exit 1) and the `doctor` informational line (FR-SET-002) become testable in S13, and S14 fills in the methods without touching the factory or CLI again.

---

## Tasks

| # | Task | Layer | PR | Status |
|---|---|---|---|---|
| S13-01 | `infra/backends/base.py`: `EvolutionBackend` protocol (per #267 §2.2: `capabilities`, `is_available`, `config_template`, `validate_config`, `build_config`, `resolved_config`, `generate_wrapper`, `launch`, `resume`, `read_progress`, `parse_population`, `count_valid`, `wants_http_proxy`, `collect_token_usage`), `BackendCapabilities`, `BackendRunSpec`, `BackendRunResult`, `BackendUnavailableError`, `get_backend()` factory | infra | PR-A | [x] |
| S13-02 | `infra/backends/openevolve.py`: `OpenEvolveBackend` — move `infra/openevolve.py` content behind the interface (`wants_http_proxy()=True`); `infra/openevolve.py` becomes a thin re-export shim with deprecation comment (removal in S15) | infra | PR-A | [x] |
| S13-03 | `infra/backends/shinka.py`: stub backend registered in the factory — `is_available()=(False, install hint)`, `capabilities()` per ADR-007, engine methods raise `BackendUnavailableError` | infra | PR-A | [x] |
| S13-04 | `models/run.py`: neutral `ResolvedConfig` (`backend`, `iterations`, `num_islands`, `temperature`, `language`, `llm_models`, `config_overrides`, `backend_extras: dict`) replacing `ResolvedOEConfig`; `RunResult.resolved_config` type updated | domain | PR-B | [x] |
| S13-05 | `models/run.py`: `backend: str = "openevolve"` field on `RunConfig`, `RunManifest`, `RunSummary`, `RunInfo` | domain | PR-B | [x] |
| S13-06 | `infra/db.py`: migration v9 (`ALTER TABLE runs ADD COLUMN backend TEXT NOT NULL DEFAULT 'openevolve'`); `insert_run()`/`get_run()`/`list_runs()` updated | infra | PR-B | [x] |
| S13-07 | `core/run.py`: `launch_run()` resolves the backend via `get_backend(name)`; config build, validation, wrapper generation, launch, proxy decision (`wants_http_proxy()`) and token collection (`collect_token_usage()`) go through `backend.*`; backend stored in run record + manifest | domain | PR-C | [x] |
| S13-08 | `core/run.py`: `resume_run()` inherits the parent run's backend (cross-backend resume rejected with a clear error); `get_run_status()` active-path via `backend.read_progress()`; `get_population()` via `backend.parse_population()` | domain | PR-C | [x] |
| S13-09 | `core/run.py`: `_extract_resolved_config()` produces the neutral `ResolvedConfig`, OE-only keys (`checkpoint_interval`, `feature_dimensions`, `max_code_length`, …) routed into `backend_extras` | domain | PR-C | [x] |
| S13-10 | `cli/run.py`: `--backend TEXT` option on `run` (default `openevolve`; unknown name → exit 1; stub backend not installed → exit 3 with install hint); OE-hardcoded progress/help copy made backend-aware | cli | PR-C | [x] |
| S13-11 | `cli/run.py`: surface backend in `run info` (line), `run list` (column), dry-run output (neutral fields + generic `backend_extras` loop) — FR-RUN-047 | cli | PR-C | [x] |
| S13-12 | `core/doctor.py`: replace `_check_openevolve()` with a per-backend `is_available()` loop (OpenEvolve required, ShinkaEvolve informational); `core/setup.py`: per-backend install entries | domain | PR-D | [x] |
| S13-13 | `core/project.py`: `config.yaml` template served by `backend.config_template()`; `core/problem.py`: `validate_oe_config()` call dispatched via `backend.validate_config()` | domain | PR-D | [x] |
| S13-14 | L2 integration tests: `test_run_backend_flag_and_default`, `test_resume_inherits_parent_backend`, `test_run_unknown_backend_exit1`, `test_run_shinka_stub_not_installed_exit3`, `test_doctor_shinka_informational` + **full regression (zero behavior change)** | test | all PRs | [x] |

---

## Key implementation details

### Move, don't rewrite (PR-A)

`OpenEvolveBackend` is a mechanical relocation of `infra/openevolve.py` (`OpenEvolveRunner`, `build_config`, `resolve_api_keys`, `find_latest_checkpoint`, `count_valid_programs`, `read_checkpoint_best_score`, `parse_population`, `validate_oe_config`, `_parse_value`) behind the protocol methods. `infra/token_proxy.py` stays where it is — the backend only *decides* (`wants_http_proxy()`); `core/run.py` keeps owning the proxy lifecycle. `infra/openevolve.py` survives as a re-export shim so existing imports (notably L2-OE tests `test_run_oe.py`) keep passing unmodified; the shim is removed in S15.

### Zero behavior change — exit criterion

The refactor is proven by the existing suite: all L0 (ruff/mypy), L1, L2 and L2-OE tests pass **without modification** (import paths excepted if a test imports `infra.openevolve` internals directly — the re-export shim should make even that unnecessary). Any test that needs a semantic change is a red flag to investigate, not to patch.

### Migration v9 (PR-B)

```sql
ALTER TABLE runs ADD COLUMN backend TEXT NOT NULL DEFAULT 'openevolve';
UPDATE schema_version SET version = 9, applied_at = datetime('now');
```

All pre-v9 runs are OpenEvolve runs — the default backfills them correctly (DES-001 §5.8).

### ResolvedConfig mapping (PR-C)

Neutral fields = concepts shared by both engines (#267 §4): `iterations`, `num_islands`, `temperature`, `language`, `llm_models`, `config_overrides`. Everything OE-specific read today by `_extract_resolved_config()` (`checkpoint_interval`, `feature_dimensions`, `max_code_length`, `diff_based_evolution`, `population_size`, `cascade_evaluation`) moves into `backend_extras`. The dry-run renderer iterates neutral fields then a generic `key: value` loop over extras — no OE knowledge left in `cli/run.py`.

### Resume inherits the parent backend (PR-C)

`resume_run()` reads `runs.backend` from the parent record and resolves the same backend; a `--backend` mismatch on resume is an error (cross-backend resume is meaningless — the resume state formats differ). FR-RUN-047, spec-run §2.3 step 4.

---

## Integration Tests (L2)

| Command | Scenario | Test ID |
|---|---|---|
| `run` (mocked) | Default run records `backend='openevolve'` in DB + manifest, shown in `run info`/`run list` | `test_run_backend_flag_and_default` |
| `run --backend openevolve` | Explicit flag behaves identically to default | `test_run_backend_flag_and_default` |
| `run --backend nope` | Unknown backend → exit 1, message lists available backends | `test_run_unknown_backend_exit1` |
| `run --backend shinka` | Stub not installed → exit 3, install hint `pip install revolver[shinka]` | `test_run_shinka_stub_not_installed_exit3` |
| `run resume` | Resumed run inherits parent backend | `test_resume_inherits_parent_backend` |
| `run --dry-run` | Resolved config shows neutral fields + `backend_extras` (OE keys present there) | extend `test_run_dry_run` assertions |
| `doctor` | ShinkaEvolve absent reported as informational, not FAIL | `test_doctor_shinka_informational` |
| Full suite | Existing L0/L1/L2/L2-OE pass unmodified | regression run |

---

## Parallelization

### Dependency graph

```
Sprint 012 / v0.12.1 complete ────────────────────────────────
          |
          ├──> PR-A (backends package: base + OE move + stub)   ← independent
          |
          ├──> PR-B (models ResolvedConfig/backend + migration v9) ← independent
          |
          ├──────────────┬──> PR-C (core mediation + CLI --backend/surfacing)  ← needs A + B
          |              |
          └──> PR-D (4 shims: doctor/setup/project/problem)     ← needs A only
```

- **Wave 1 (parallel)**: PR-A, PR-B — 2 agents
- **Wave 2 (parallel)**: PR-C (after A+B), PR-D (after A) — 2 agents

### Conflict risks

- **`core/run.py`** — PR-C only (the import switch from `infra.openevolve` to `infra.backends` lands with PR-C, the re-export shim keeps PR-A merge-safe before that). Low risk.
- **`cli/run.py`** — PR-C only. None.
- **`infra/db.py`** — PR-B only (migration). None.
- **`core/doctor.py` / `core/setup.py` / `core/project.py` / `core/problem.py`** — PR-D only. None.

**Recommended merge order**: PR-A → PR-B → PR-D → PR-C (PR-C last: it is the integration point and its tests exercise everything).

---

## Sprint Review

**Completed in session 048 (2026-06-11/12).** Delivery: 4 PRs (#184 PR-A, #185 PR-B, #188 PR-C, #189 PR-D), each issue → worktree dev agent → draft PR → code review → fixes → CI → user merge. Waves as planned (A+B parallel, then C+D parallel; one merge conflict C↔D in `backends/openevolve.py`, resolved by keeping both inserted sections).

### Tests passing
- **91 new tests** (47 PR-A + 24 PR-B + 9 PR-C + 11 PR-D) — final suite **1175 passed, 7 skipped** (the 7 = L2-OE auto-skip without `openevolve`), coverage ~87%.
- Zero-behavior-change criterion **held**: no pre-existing test modified outside three traced categories (mechanical `patch()`-target relocation, additive backend surfacing, removed legacy `ResolvedOEConfig`).
- CI green on 3.12 + 3.14 for all four PRs (one transient 10-min hang of the 3.14 job on the self-hosted runner, attempt 2 passed).
- Code reviews: #184 0C/4W/5S, #185 0C/1W/4S, #188 0C/2W/3S, #189 0C/1W/4S — all CRITICAL-free; actionable findings fixed in-PR, S14-seam WARNINGs carried over below.

### Demo-able features
- [x] `revolver run` unchanged for users — same outputs, same artifacts (regression green)
- [x] `run info` / `run list` / dry-run show `backend: openevolve` (FR-RUN-047)
- [x] `run --backend shinka` fails cleanly with the install hint (stub, exit 3); unknown backend → exit 1
- [x] `revolver doctor` reports ShinkaEvolve availability as informational
- [x] DB migration v9 applied transparently on first command

### Carry-over (feed into the S14 issue)
- **OE layout still hardcoded in the orchestrator** (`oe-output/`, crash-status counting, resume staging precheck in `core/run.py`) — S14 needs a neutral staging/counting hook or per-backend prechecks (review #188 W1).
- **Iterations fallback duplicated** between orchestrator and backend (`max_iterations` default) — make the orchestrator the single owner in S14 (review #188 W2).
- `launch_run` fallback reads `cfg.get("max_iterations", 10)`: Shinka's `build_config` must populate it or the fallback must be generalized (PR-C dev note).
- Token path ready for Shinka: when `wants_http_proxy()` is False, core already calls `collect_token_usage(run_dir)` and stores via `update_run_tokens`; native `cost_usd` is the backend's responsibility (ADR-007 D2).
- Dist-name mapping `shinka` → `shinka-evolve` already in place in doctor (review #189 W1, fixed in-PR).
- Pre-existing minor doc debts (deferred): FR-RUN-042 numbering gap, FR-RUN-036..039 traceability rows, DES-005 title rename (S15).
