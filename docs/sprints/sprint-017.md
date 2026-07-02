# Sprint 017 — Multi-LLM Ensemble, Validated End-to-End (v0.17.0)

**Status**: Planning
**Goal**: Close the long-standing `multimodel-not-validated` gap. Front-load a correctness slice (B1 OE wrapper aggregation crash, B2 OE post-run teardown hang, B7 OE best-of-interrupted-run recovery), then deliver the multi-LLM ensemble as a first-class, honestly-gated feature: `--selection {fixed,ucb,ucb1,thompson}`, `--llm-weight`, per-LLM `reasoning_effort`, and the two verified capability asymmetries (weights fixed-only, reasoning_effort OE-only) surfaced via `capabilities()` instead of silently dropped.
**Demo**: `revolver run --backend openevolve --llm my-ensemble --llm-weight gpt4o=0.7 --llm-weight claude=0.3` runs a static weighted sampler; the *same* ensemble on `--backend shinka --selection fixed` reproduces the same weights (`FixedSampler.prior_probs`); `--backend shinka --selection ucb` runs the adaptive bandit and a `run info`/dry-run makes clear the weights were ignored (warn). `revolver llm add gpt4o --reasoning-effort high` + a second member `--reasoning-effort low` shows per-member effort on the OE dry-run and a single merged/warned value on the Shinka dry-run. A killed/interrupted OE run recovers its best program via `solution extract --from-checkpoint`. An OE wrapper fed a non-numeric metric no longer crashes the aggregation. A Shinka run no longer busy-loops after completion (parity with OE's own teardown).
**Source**: [ADR-007 — v0.17 Amendment](../architecture/adr/ADR-007-pluggable-evolution-backend.md#amendment--v017-multi-llm-ensemble-selection-2026-07-01) (decisions A1–A5), [v017-multi-llm-research.md](../analysis/v017-multi-llm-research.md) (source-verified facts, insertion map, B1/B2/B7 scoping, spec edit surface).
**Predecessor**: Sprint 016 / Sprint 016a (v0.16.1) — tech-debt paydown + demo-feedback corrective release.

---

## Source

- ADR: [ADR-007](../architecture/adr/ADR-007-pluggable-evolution-backend.md) — Amendment (A1–A5), superseded D5 bullet + Negative consequence + roadmap line
- Research: [v017-multi-llm-research.md](../analysis/v017-multi-llm-research.md) — §0 FACT A/B (adversarially verified), §1 corrected mapping table, §2 exact insertion map (file:line), §3 B1/B2/B7 scoping, §4 spec/design/validation edit surface, §5 open policy question (amendment vs new ADR — resolved: in-place amendment, already applied)
- Backlog: #299 (top-N, explicitly deferred to S18), #300/#301/#308/#309 (S15/S16 token-honesty/UX, prerequisite context only)
- Prior sprints for pattern reference: [sprint-013.md](sprint-013.md) (backend abstraction, zero-behavior-change discipline), [sprint-014.md](sprint-014.md) (R4 front-loaded contract tests, PR waves), [sprint-016.md](sprint-016.md) (scoped correctness + DB migration sequencing)

---

## Scope

### In scope — Wave 0 (correctness slice, front-loaded)

| Item | Backlog ref | Content |
|---|---|---|
| **B1 — OE wrapper aggregation crash on non-numeric metric** | new (this sprint) | Copy the numeric guard from `shinka.py:322-331` (`isinstance(m.get(key), (int, float)) and not isinstance(m.get(key), bool)`) into the OE `_WRAPPER_TEMPLATE` aggregation loop (`openevolve.py:1140-1144`) and harden the `combined_score` mean at L1133 the same way. Preserve the template's `{{`/`}}` brace escaping. No existing test execs the OE wrapper aggregation — add one that generates the wrapper, feeds an instance returning `{'combined_score': 0.5, 'error': 'boom'}` (a non-numeric value mixed in), and asserts a numeric result with no crash. |
| **B2 — OE post-run teardown hang** | new (this sprint) | Symmetric to #224 (Shinka A2). Wrap `OpenEvolveRunner.run()` (`openevolve.py:301-349`, currently no `finally`) in try/finally. Hoist `_current_child_pids()`/`_reap_run_children()` from `shinka.py:1448-1506` to `infra/backends/base.py` (shared helper, avoid duplication) and reuse from both backends. Add an OE-specific `_shutdown_runner()`: guard via `getattr` on the controller's executor(s), `shutdown(wait=False)` + `contextlib.suppress` (never `wait=True` — that reintroduces the #159 hang). The run's result is already persisted before teardown runs, so reaping/shutdown cannot truncate it. |
| **B7 — OE cannot expose the best of a killed/interrupted run** | new (this sprint) | `solution extract --from-checkpoint` recovers the best program from the latest `oe-output/checkpoints/checkpoint_N/` (`best_program_id` in `metadata.json` + `programs/{id}.json` code) for `interrupted`/`failed` runs, routed via a new `EvolutionBackend` method (backend-neutral signature; Shinka can no-op/raise "not needed" since its DB already survives). **Must consciously revise `test_extract_rejects_interrupted_run`** (`tests/integration/test_solution.py:643`): the default behavior still rejects interrupted runs; the new `--from-checkpoint` flag path succeeds. Gate cleanly on "no checkpoint yet" (run too short to checkpoint) with a clear error. |

### In scope — Wave 1 (ensemble core, flagship, full bandit)

| Item | Backlog ref | Content |
|---|---|---|
| **M1 — Full multi-LLM ensemble mapping (weighted + bandit)** | ADR-007 A1/A2 | Lift the Shinka ensemble hard-raise (`shinka.py:614-619`). Generalize the single-LLM projection (`shinka.py:633-638`) to loop **all** ensemble members → `evo_config.llm_models[]` (via `_project_llm_model()` per member). New neutral CLI flags on `run`/`run resume`: `--selection {fixed,ucb,ucb1,thompson}`, `--selection-kwarg k=v` (repeatable). Shinka: `--selection` → `evo_config.llm_dynamic_selection`; under `fixed`, member weights → `FixedSampler.prior_probs` (positional vector aligned to `llm_models` order, renormalized to sum 1); `--selection-kwarg` is branched **per selected sampler** (never spread as a union — Shinka's own `{cost_aware_coef: 0.5}` default is valid for ucb/ucb1, ignored by fixed, `TypeError`s under thompson). OE: `--selection` non-`fixed` → **rejected** with a clear error message (`capabilities().selection_strategies == ("weighted",)`); `fixed` (or unset) is the implicit/only mode. |
| **M4 — `cost_aware_coef` settable, default 0** | ADR-007 A5 | `--selection-kwarg cost_aware_coef=<v>` applies only to `ucb`/`ucb1` on Shinka; Revolver's own default (when unset) is **0** (flat-rate/bridge case), not Shinka's own `0.5`. Inert when per-model cost is undifferentiated (all-local/bridge) — low urgency but must default correctly and be documented as such. |
| **A4 — `capabilities()` widened, validation capability-driven** | ADR-007 A4 | Add `selection_strategies: tuple[str, ...]` (OE → `("weighted",)`; Shinka → `("fixed","ucb","ucb1","thompson")`) and `per_member_reasoning_effort: bool` (OE `True`, Shinka `False`) to `BackendCapabilities`. CLI validation of `--selection` and the `reasoning_effort` warn path reads these fields — no hard-coded backend-name branches for what should be a capability check. |

### In scope — Wave 2 (support)

| Item | Backlog ref | Content |
|---|---|---|
| **B4 + M2 — per-LLM `reasoning_effort` registry field** | ADR-007 A1/A3.2 | New `reasoning_effort: str \| None` field on `LLMEntry` (after `models/llm.py` L43) and `EnsembleMember` (after L117). CLI: `llm add --reasoning-effort`, `llm update --reasoning-effort`, `ensemble add --reasoning-effort`. OE maps it **per member** (`LLMModelConfig.reasoning_effort`, `openevolve.py` `_build_ensemble_llm_config` L355-423 — add an effort block mirroring the existing temperature/max_tokens per-member override pattern L408-419). Shinka maps it to the **single global** `llm_kwargs.reasoning_efforts` pool and **warns** if members disagree on the value (also warns it's inert for local/bridge models — Shinka classes them `is_reasoning_model=False`). One feature closes both B4 and M2's ask. |
| **M3 — `--llm-weight model=w` per-run override** | ADR-007 A1 | New repeatable CLI flag `--llm-weight model=w` on `run`/`run resume`. OE: honored, patches the resolved member's `weight` before `_build_ensemble_llm_config` runs. Shinka: honored **only under `--selection fixed`** (maps into the same `prior_probs` vector as registry weights); **warns** and is ignored under `ucb`/`ucb1`/`thompson`. Dedicated flag, explicitly **not** reachable via `--config-override` (`_set_nested` cannot address list members — `config-override-is-an-exception` principle). |
| **M2 (doc/example) — OE ensemble example** | ADR-007 scope note | A `--dry-run`-validated OE ensemble example (weighted, 2+ members) + a short doc section (guide or spec example) demonstrating the cross-engine comparison: OE-weighted vs Shinka-fixed (same weights) vs Shinka-ucb (adaptive). |
| **B9 — warn on no-op `--config-override` key** | backlog B9 | When a `--config-override key=value` key does not match any field the selected backend's config schema recognizes (post `_set_nested`/dataclass-kwargs filtering), emit a warning instead of silently accepting a no-op. Composes with the A5 per-sampler kwarg routing (an override landing in the wrong sampler's kwargs is exactly this case). |

### In scope — Wave 3 (polish)

| Item | Backlog ref | Content |
|---|---|---|
| **A6 / M5 — OE config template realignment** | backlog #318 follow-up | Realign the OE `config.yaml` scaffold to the `database.*` schema (the S16a #318 fix already stopped the scaffold from triggering its own validator warnings for `num_iterations`/`population_size`/`evaluation:` — this wave extends that to **surface** `feature_dimensions`/`feature_bins` in the template, completing the realignment rather than just silencing self-warnings). |
| **B6 — finish `REVOLVER_HOME`** | backlog carry-over (S16a commit 5a4d02d) | `REVOLVER_HOME` already exists in `db.py` for the global DB path since S16a. Make `config.py:68` consistent (same env var, same resolution order), document the variable, and add an optional `--global-db` override flag for power users / CI isolation. |

### Explicitly out of scope (deferred)

| Deferred item | Why deferred |
|---|---|
| **Top-N extraction (#299)** | Deferred to **S18** per the ADR-007 roadmap correction; largest task chain, gates on `capabilities().top_n_extraction`, deserves its own sprint. |
| **B3** (FR-RUN-014 spec change) | Off the v0.17 critical path — the v0.17 fleet is mono-bridge; revisit alongside a broader multi-provider timeout story. |
| **B5 / A4-token / A4-caveat polish (⚪🟡)** | Low-value cosmetic items; not blocking the ensemble validation goal. |
| **Judge ensemble** (`evaluator_models` / `use_llm_feedback`) | Known unexposed gap per the ADR-007 Amendment scope note — explicitly not in v0.17 scope. |

---

## Verified facts driving the design (do not re-derive — see research doc §0)

1. **FACT A (per-member `reasoning_effort` is OE-only)**: Shinka's `reasoning_efforts` is a single global sampling pool (`shinka/llm/kwargs.py:107`) drawn *independent* of which model the bandit picked (`llm/llm.py:349` stores one value). OpenEvolve's `LLMModelConfig.reasoning_effort` is genuinely per-model (`config.py:80`, inherited-if-None from `llm.reasoning_effort`). Extra Shinka caveat: local/bridge models are classed `is_reasoning_model=False` → effort forced to `"disabled"` regardless — inert for the demos' bridge fleet.
2. **FACT B (weights seed the bandit only under `fixed`)**: `prior_probs` exists only on `FixedSampler` (`prioritization.py:956`); `AsymmetricUCB`/`ThompsonSampler` accept **no** `prior_probs` and **no** `**kwargs` (`prioritization.py:297-314`, `:1107-1121`) → passing it raises `TypeError`. Under `ucb`/`ucb1`/`thompson` the arms start uniform and weights are ignored — by design, not a Revolver gap.
3. `llm_dynamic_selection` accepted values: `fixed`, `ucb`, `ucb1` (alias of `AsymmetricUCB`, same class), `thompson`, `None` (uniform); unknown → `ValueError` (`async_runner.py:361-383`).
4. `llm_dynamic_selection_kwargs` is spread **verbatim** into the selected sampler's constructor — a wrong key raises `TypeError`. Revolver must branch kwargs per sampler, never send a union.
5. `--config-override` cannot address array members (`_set_nested`, `shinka.py`/`openevolve.py` L683-693 equivalent, no `[i]` indexing) — per-member weight/effort **must** use the dedicated flags (`--llm-weight`, per-LLM registry field), reinforcing the "config-override is an exception" principle.

---

## Tasks

### Wave 0 — Correctness slice (PR-W0)

| # | Task | Layer | Depends on | Acceptance criteria |
|---|---|---|---|---|
| S17-01 | **B1 — numeric guard in OE wrapper aggregation.** In `infra/backends/openevolve.py`, add the `isinstance(x, (int, float)) and not isinstance(x, bool)` guard (copied from `shinka.py:327-328`) to the `_WRAPPER_TEMPLATE` per-instance aggregation loop (~L1140-1144) and to the `combined_score` mean computation (~L1133). Preserve `{{`/`}}` escaping in the f-string template. | infra | — | Generated wrapper, given one instance with `{'combined_score': 0.5, 'error': 'boom'}` (non-numeric `error` key mixed with numeric `combined_score`) and another with a fully numeric dict, aggregates without raising; non-numeric keys are dropped from the aggregate, not crashed on |
| S17-02 | **B1 — test the generated OE wrapper aggregation** (none exists today). New test execs the generated `_revolver_evaluator.py`'s `evaluate()` against a small on-disk dataset with a mixed-type metrics fixture; asserts numeric `combined_score` result, no exception. | test | S17-01 | Test fails before S17-01, passes after; runs without requiring OpenEvolve installed (pure wrapper exec) |
| S17-03 | **B2 — wrap `OpenEvolveRunner.run()` in try/finally.** `infra/backends/openevolve.py` L301-349: wrap the `asyncio.run(...)` call in try/finally; snapshot pre-run child PIDs before launch (mirror `shinka.py:1377`). | infra | — | `run()` always executes the finally block even when `asyncio.run` raises; existing OE launch/resume tests pass unmodified |
| S17-04 | **B2 — hoist `_current_child_pids`/`_reap_run_children` to `infra/backends/base.py`.** Move the two static/instance helpers out of `ShinkaBackend` into a shared module-level (or mixin) location; both backends import/reuse them. No behavior change to the existing Shinka teardown path. | infra | S17-03 | `grep -c "_current_child_pids" src/revolver/infra/backends/*.py` shows one definition (base.py) + two call sites (openevolve.py, shinka.py); Shinka teardown tests (`test_shinka_shutdown.py`) still pass unmodified |
| S17-05 | **B2 — OE-specific `_shutdown_runner()`.** Add an OE analogue of `ShinkaBackend._shutdown_runner()`: guarded `getattr` on the controller's process/thread pool executor(s) (whatever `OEController`/`asyncio` leaves reachable), `shutdown(wait=False)` wrapped in `contextlib.suppress(Exception)` — never `wait=True` (would reintroduce the #159 `ProcessPoolExecutor.shutdown(wait=True)` hang). Called from the `run()` finally block alongside `_reap_run_children`. | infra | S17-04 | A mocked controller with a stub executor exercises `_shutdown_runner` without raising; no `wait=True` call anywhere in the new code |
| S17-06 | **B2 — regression test: `test_openevolve_shutdown.py`** (mirror `tests/integration/test_shinka_shutdown.py`). Asserts: (a) `run()` calls the teardown+reap sequence even on a raised exception inside the controller; (b) no process left in the pre/post child-PID diff after a mocked run. | test | S17-05 | New test file passes; mirrors the Shinka test's structure per the research doc §3 |
| S17-07 | **B7 — `EvolutionBackend.recover_best_from_checkpoint()` method.** New protocol method on `infra/backends/base.py` (default: raise "not supported"/no-op for backends without checkpoint-based recovery). `OpenEvolveBackend` implementation: locate the latest `oe-output/checkpoints/checkpoint_N/`, read `best_program_id` from `metadata.json`, load `programs/{id}.json` for the code. Raise a clear, typed error when no checkpoint exists yet (run too short). | infra | — | Given a fixture checkpoint dir, the method returns the best program's code + score; given an empty checkpoints dir, raises a clear `RevolverError` subclass distinguishable from "not supported" |
| S17-08 | **B7 — `solution extract --from-checkpoint` flag.** `cli/solution.py` `solution_extract`: new `--from-checkpoint` boolean flag. When set and the run's status is `interrupted`/`failed`, dispatch to `backend.recover_best_from_checkpoint(run_dir)` instead of the normal `programs/rank-1.py` read path. Default behavior (flag unset) is **unchanged** — still rejects interrupted runs. | cli/domain | S17-07 | `solution extract --run <id>` on an interrupted run still exits non-zero (unchanged default); `solution extract --run <id> --from-checkpoint` on the same run succeeds and creates a solution from the recovered program |
| S17-09 | **B7 — revise `test_extract_rejects_interrupted_run`** (`tests/integration/test_solution.py:643`) + add `test_extract_from_checkpoint_recovers_interrupted_run` and `test_extract_from_checkpoint_no_checkpoint_yet_errors`. Consciously documents the F3 revision: default still rejects, flag path succeeds, "too short to checkpoint" still errors. | test | S17-08 | All three scenarios pass; the docstring of the revised test explicitly notes the v0.17 policy change vs the original F3 decision |

### Wave 1 — Ensemble core (PR-W1a models/DB, PR-W1b Shinka mapping, PR-W1c OE mapping + CLI)

| # | Task | Layer | Depends on | Acceptance criteria |
|---|---|---|---|---|
| S17-10 | **DB migration v12 — `reasoning_effort` column on `llms`.** `infra/db.py`: `ALTER TABLE llms ADD COLUMN reasoning_effort TEXT` (global DB, simple additive column per the v6/v9 pattern — no table recreation needed); bump `CURRENT_SCHEMA_VERSION = 12`; update `_LLM_COLUMNS`, `_row_to_llm_entry()`, `insert_llm()`, `update_llm()`. | infra | — | Fresh global DB has the column; a v11 DB upgrades cleanly (`test_db_migration_v12_llms_reasoning_effort`); existing LLM rows preserved with `NULL` |
| S17-11 | **DB migration v13 — `reasoning_effort` column on `ensemble_members`.** `infra/db.py`: `ALTER TABLE ensemble_members ADD COLUMN reasoning_effort TEXT` (both DDL copies: `_GLOBAL_SCHEMA_SQL` L181-189 and the `_migrate_v7_to_v8` inline copy L546-552 — the fresh-schema and migration-schema definitions must stay in sync); bump `CURRENT_SCHEMA_VERSION = 13`. Kept **separate** from v12 per one-column-per-migration discipline (mirrors v10/v11 in Sprint 016). | infra | S17-10 | Fresh global DB has the column on `ensemble_members`; a v12 DB upgrades cleanly (`test_db_migration_v13_ensemble_members_reasoning_effort`); existing ensemble member rows preserved with `NULL` |
| S17-12 | **`models/llm.py` — `reasoning_effort` field.** Add `reasoning_effort: str \| None = None` to `LLMEntry` (after L43) and `EnsembleMember` (after L117). | models | S17-10, S17-11 | Both models accept/round-trip the field; `mypy` clean |
| S17-13 | **`models/base.py` (or `backends/base.py`) — widen `BackendCapabilities`.** Add `selection_strategies: tuple[str, ...]` and `per_member_reasoning_effort: bool` fields (A4). Update `OpenEvolveBackend.capabilities()` → `("weighted",)` / `True`; `ShinkaBackend.capabilities()` → `("fixed","ucb","ucb1","thompson")` / `False`. | infra | — | `capabilities()` on both backends exposes the two new fields with the documented values; existing capability consumers (doctor, docs) unaffected |
| S17-14 | **`infra/backends/base.py` — widen `BackendRunSpec`.** Add `selection: str \| None`, `selection_kwargs: dict[str, Any] \| None`, `llm_weight_overrides: dict[str, float] \| None` after the existing `ensemble` field (L128). | infra | S17-13 | Fields present with correct types/defaults; `mypy` clean |
| S17-15 | **`models/run.py` — mirror the new levers on `RunConfig`.** Add `selection: str \| None`, `selection_kwargs: list[str] \| None` (raw `k=v` strings, parsed downstream), `llm_weight_overrides: list[str] \| None` (raw `model=w` strings) after L75. `ResolvedConfig` already exposes `llm_models`/`backend_extras` for dry-run surfacing — no change needed there beyond wiring. | domain | S17-14 | `RunConfig` round-trips the new fields; existing single-LLM runs unaffected (all default `None`) |
| S17-16 | **`cli/run.py` — `--selection` / `--selection-kwarg` / `--llm-weight` flags on `run_launch`.** New Typer options after the existing `rewrite_mode` option (L99): `--selection {fixed,ucb,ucb1,thompson}` (validated against `AVAILABLE_BACKENDS`-style choices, but the actual capability check happens against the *resolved backend's* `capabilities().selection_strategies` at build time, not at the Typer layer), `--selection-kwarg k=v` (repeatable `list[str]`), `--llm-weight model=w` (repeatable `list[str]`). Thread into `RunConfig` construction (L123-135). | cli | S17-15 | `revolver run --help` shows the three new flags; passing them constructs a `RunConfig` with the corresponding fields populated |
| S17-17 | **`cli/run.py` — mirror the same three flags on `run_resume`.** Both `launch_run` (spec build ~L596-607 pre-refactor line numbers, verify against current `core/run.py`) and `resume_run` (~L1307-1320) must copy the new fields into `BackendRunSpec`. | cli/domain | S17-16 | `revolver run resume --selection ucb ...` builds a spec carrying the override; resume without the flags inherits parent-run values unchanged (existing resume semantics preserved) |
| S17-18 | **`core/run.py` — validate `--selection` against the resolved backend's capabilities.** Before calling `backend.build_config()`, if `spec.selection` is set and not in `backend.capabilities().selection_strategies`, raise a clear `ValidationError` (exit 1) naming the backend and the supported strategies. This is the OE-rejects-non-`fixed` behavior (A2). | domain | S17-13, S17-16 | `run --backend openevolve --llm <ensemble> --selection ucb` exits 1 with a message naming `weighted` as the only supported OE strategy; `run --backend shinka --selection ucb` succeeds |
| S17-19 | **`infra/backends/shinka.py` — lift the ensemble hard-raise, project all members.** Remove the `ValidationError` at L614-619. Generalize the single-LLM projection (L633-638) to loop `ensemble.members` → `evo_config.llm_models[]` via `_project_llm_model()` per member (collecting per-member env exports). Set `evo_config.llm_dynamic_selection` from `spec.selection` (default `"fixed"` when unset, matching current single-LLM behavior — S14 MVP path stays a `fixed`, one-member case of this new code, zero behavior change for single-LLM runs). | infra | S17-14 | An ensemble with N members produces `llm_models` of length N; a single-LLM `BackendRunSpec` (no ensemble) still produces the identical config as before this change (regression-tested) |
| S17-20 | **`infra/backends/shinka.py` — weights → `prior_probs` under `fixed` only.** When `spec.selection in (None, "fixed")` and `spec.ensemble` (or `spec.llm_weight_overrides`) carries weights, build the `prior_probs` vector aligned to `llm_models` order (registry weights, then `--llm-weight` overrides applied on top), renormalized to sum 1, and set on the sampler's kwargs. When `spec.selection` is `ucb`/`ucb1`/`thompson` and weights are present (registry non-uniform, or `--llm-weight` passed), emit a warning that weights are ignored under the adaptive mode (FACT B). | infra | S17-19 | `--selection fixed` with 2 members weighted 0.7/0.3 → `prior_probs == [0.7, 0.3]` (order-matched); `--selection ucb` with the same weights → warning emitted, no `prior_probs` key sent to the sampler kwargs (avoids the verified `TypeError`) |
| S17-21 | **`infra/backends/shinka.py` — per-sampler `--selection-kwarg` routing.** Branch `spec.selection_kwargs` by the selected sampler: `cost_aware_coef` only valid for `ucb`/`ucb1` (default **0**, not Shinka's own 0.5 — M4); any kwarg not accepted by the selected sampler's constructor is dropped with a warning (never spread as a union, never passed to `fixed`/`thompson` if `ucb`-only). | infra | S17-20 | `--selection ucb --selection-kwarg cost_aware_coef=0.3` sets `llm_dynamic_selection_kwargs={"cost_aware_coef": 0.3}`; `--selection fixed --selection-kwarg cost_aware_coef=0.3` warns and drops the kwarg (would be silently ignored by `FixedSampler` otherwise — now explicit); `--selection thompson --selection-kwarg cost_aware_coef=0.3` warns and drops (would `TypeError` otherwise) |
| S17-22 | **`infra/backends/openevolve.py` — `--llm-weight` + `--selection` reject-non-fixed.** `_build_ensemble_llm_config()` (L355-423): before building each member's `entry`, apply `spec.llm_weight_overrides.get(member.llm_name)` on top of the registry `member.weight` if present (CLI override wins). `build_config()`/`resolved_config()`: `spec.selection` not in `(None, "fixed")` → the S17-18 orchestrator-level check already rejects it before reaching here, but add a defensive capability-consistent error here too (belt-and-braces, matches `capabilities().selection_strategies == ("weighted",)`). | infra | S17-14, S17-18 | `run --llm my-ensemble --llm-weight gpt4o=0.9 --llm-weight claude=0.1` on OE produces `llm.models[].weight` reflecting the override, not the registry weight |
| S17-23 | **L2 tests — selection-strategy validation + OE-rejects-non-weighted.** New scenarios in `tests/integration/test_run_shinka.py` and the OE equivalent: `--selection ucb` on OE → exit 1 with clear message; `--selection fixed` on Shinka with weights → `prior_probs` matches; `--selection ucb` on Shinka with weights → warning + uniform start; `--llm-weight` honored on both OE and Shinka-fixed; `--llm-weight` warned-and-ignored on Shinka-ucb/thompson. | test | S17-18, S17-20, S17-22 | All scenarios pass; mocked Shinka runner captures the constructed sampler kwargs for assertion |

### Wave 2 — Support (PR-W2a reasoning_effort, PR-W2b llm-weight polish + doc example, PR-W2c config-override warn)

| # | Task | Layer | Depends on | Acceptance criteria |
|---|---|---|---|---|
| S17-24 | **`cli/llm.py` — `--reasoning-effort` on `llm add`/`llm update`.** Add the flag after the existing options (~L98 for `llm_add`); thread through `core/llm.py` `register_llm()`/`update_llm()` (~L131/~L261) → `infra/db.py` `insert_llm()`/`update_llm()`. | cli/domain/infra | S17-12 | `revolver llm add gpt4o --reasoning-effort high` stores the value; `llm update gpt4o --reasoning-effort low` updates it; `llm info` displays it when set |
| S17-25 | **`cli/llm.py` — `--reasoning-effort` on `ensemble add`.** Add the flag after the existing options (~L596); thread through `core/llm.py` `add_ensemble_member()` (~L689) → `infra/db.py` ensemble member insert. Per-member override takes precedence over the member LLM's registry-level `reasoning_effort` (same precedence pattern as existing `temperature`/`max_tokens` overrides). | cli/domain/infra | S17-24 | `revolver llm ensemble add my-ensemble gpt4o --weight 0.7 --reasoning-effort high` stores a per-member override distinct from the LLM's own registry value |
| S17-26 | **`infra/backends/openevolve.py` — per-member `reasoning_effort` mapping.** `_build_ensemble_llm_config()` (L355-423): add an effort block mirroring the existing temperature/max_tokens per-member override pattern (L408-419) — `effective_reasoning_effort = member.reasoning_effort if member.reasoning_effort is not None else member_llm.reasoning_effort`; set `entry["reasoning_effort"]` when non-`None`. Single-LLM (non-ensemble) path: map `spec.llm.reasoning_effort` directly if present. | infra | S17-12 | An OE ensemble with per-member efforts (`high`/`low`) produces `llm.models[].reasoning_effort` matching each member; a single-LLM run with a registered `reasoning_effort` maps it too |
| S17-27 | **`infra/backends/shinka.py` — global `reasoning_efforts` + disagreement warning.** In the ensemble/LLM projection loop, collect each member's effective `reasoning_effort` (per-member override or registry value); if all agree (or only one is set), write `llm_kwargs.reasoning_efforts = [<value>]`; if members disagree, use the **highest** effort among them (total order `min < low < medium < high < max`; a conservative default that never under-thinks) **and warn** that Shinka cannot honor per-member effort (FACT A). Also warn (once) that `reasoning_effort` is inert for `local`/bridge-sourced members (Shinka's `is_reasoning_model=False` path). | infra | S17-19, S17-26 | Uniform-effort ensemble → no warning, `reasoning_efforts` set; disagreeing efforts → warning + the **highest** effort chosen (test asserts the `min<low<medium<high<max` highest-wins policy); all-local ensemble with effort set → inert-warning emitted |
| S17-28 | **L2 tests — reasoning_effort projection.** OE: per-member effort round-trips into `llm.models[]`. Shinka: uniform effort → global pool set silently; disagreeing effort → warning; local-source → inert warning. | test | S17-27 | All 4 scenarios pass |
| S17-29 | **OE ensemble dry-run example + doc section.** A `--dry-run`-validated example config/CLI invocation (2+ member ensemble, explicit weights) demonstrating OE-weighted output; a short doc addition (guide or spec example section) walking through the three-way comparison: OE-weighted vs Shinka-fixed (same weights) vs Shinka-ucb (adaptive, weights ignored). | doc | S17-22, S17-20 | Example runs with `--dry-run` and exits 0 on both backends; doc section committed under `docs/guides/` or as a spec-run example block |
| S17-30 | **B9 — warn on no-op `--config-override` key.** After `_set_nested`/`_dataclass_kwargs` filtering (both backends), if a supplied override key does not match any recognized field for the selected backend's config schema, emit a warning naming the dropped key (instead of silent no-op). Composes with the A5 per-sampler kwarg routing done in S17-21 (a kwarg routed to the wrong sampler is exactly this case, already warned there — this task generalizes the check to the rest of `--config-override`, not just `--selection-kwarg`). | infra | S17-21 | `--config-override evo_config.nonexistent_key=1` warns; a recognized key (e.g. `db_config.num_islands=4`) does not warn |

### Wave 3 — Polish (PR-W3)

| # | Task | Layer | Depends on | Acceptance criteria |
|---|---|---|---|---|
| S17-31 | **A6/M5 — OE config template: surface `feature_dimensions`/`feature_bins`.** Extend the `_CONFIG_TEMPLATE` scaffold (already realigned to `database.*` schema per #318) to include commented-out `feature_dimensions`/`feature_bins` entries under the `database:` section, with a one-line explanatory comment. | infra | — | `project init --backend openevolve` scaffold includes the new commented keys; `validate_oe_config()` still reports zero warnings on the generated template (regression) |
| S17-32 | **B6 — `REVOLVER_HOME` consistency + `--global-db` flag.** Make `config.py:68` consistent with `db.py`'s existing `REVOLVER_HOME` resolution (same env var name, same precedence order — env var wins, else default `~/.revolver`). Document `REVOLVER_HOME` in the relevant guide/README section. Add an optional `--global-db <path>` CLI flag (global option, mirrors the existing `--json`/`--quiet` global option pattern) for power users / CI isolation, taking precedence over `REVOLVER_HOME` when supplied. | infra/cli/doc | — | `config.py` and `db.py` resolve the global DB path identically given the same env; `--global-db /tmp/x.db revolver llm list` reads/writes the given path; doc note added |
| S17-33 | **Full regression sweep + doc cascade prep.** Run the full test suite (no-shinka env) and the Shinka L2 suite (shinka env); confirm zero regressions on the existing OE single-LLM default path (explicit exit criterion). Prepare (do not necessarily merge) the spec/DES/validation edit list from the research doc §4 as a follow-up issue for spec-reviewer/validation-reviewer (see "Deferred doc-edit follow-up" below). | test/doc | all prior waves | Full suite green; a follow-up GitHub issue or backlog entry lists every FR/DES/validation edit from research §4 |

---

## Doc-edit cascade — DONE spec-before-code (session 055)

**Update (session 055):** per the user's decision to do **spec-before-code**, the spec/DES/validation edits below were **completed before implementation** (not deferred), and both reviewers passed: **spec-reviewer** (0 FAIL / 3 WARN — all fixed) and **validation-reviewer** (2 FAIL / 9 WARN — all fixed). ADR-007 was amended in place (Amendment A1–A5). The implementation PRs (Waves 0–3) now land against a stable, reviewed doc baseline. What was done (research doc §4):

- **ADD**: FR-RUN-049 (`--selection`, incl. OE-rejects-non-weighted error case), FR-RUN-050 (`--llm-weight`), FR-RUN-051 (B7 OE best-on-interrupt), FR-LLM-026 (per-LLM `--reasoning-effort`, both backends), **FR-EVL-021** (B1 aggregation numeric guard — confirmed next free number), plus a normative principle in `specifications.md` §4.4/§4.5 ("neutral levers first-class; `--config-override` is the exception").
- **SUPERSEDE** (ADR-007 already amended in place, verbatim-confirmed edits carried into specs): FR-RUN-046 (`spec-run.md:322`, "weights dropped/warned" → weights honored under OE-weighted/Shinka-fixed, ADR-007 A2/A3) and the spec-llm projection note (`spec-llm.md:378-383`). ADR-007 said `ucb` singular → specs must widen to `ucb`/`ucb1`/`thompson`.
- **AMEND**: DES-005 (§2.1 opts, §4.2 merge order + Shinka mapping, §4.6 capabilities, §4.7/§7.1 teardown for B2/B7, §8 `RunConfig`, §11 CLI, §14.1 resume); DES-002 (§2.1/§2.8/§5/§6 for `--reasoning-effort`); DES-006 §4.3 `compute_aggregates` + §1.3 wrapper contract for B1; DES-001 §4.1/§4.3 schema for migrations v12/v13.
- **Validation**: traceability rows for each new FR + B1/B2/B7; `val-integration-tests.md` adds L2-Shinka bandit ensemble, selection-strategy validation (OE reject), reasoning_effort projection, B1/B2/B7 regression; `val-e2e-tests.md` adds a Shinka bandit-ensemble scenario against the fake server.

This is intentionally listed as a checklist rather than performed inline so the spec-reviewer/validation-reviewer agents run against a *stable* code diff (matches the project's documented release-checklist step 0 pattern).

---

## Integration Tests (L2)

Tests from `val-integration-tests.md` (to be added) that must pass at sprint end:

| Area | Scenario | Test ID | Status |
|---|---|---|---|
| B1 correctness | Generated OE wrapper aggregates mixed numeric/non-numeric metrics without crashing | `test_oe_wrapper_aggregation_mixed_types` | Planned |
| B2 correctness | OE run teardown reaps children / shuts down executors after completion and after an exception | `test_openevolve_shutdown_*` | Planned |
| B7 correctness | `solution extract --from-checkpoint` recovers best program from an interrupted OE run | `test_extract_from_checkpoint_recovers_interrupted_run` | Planned |
| B7 correctness | Default `solution extract` still rejects an interrupted run (unchanged) | `test_extract_rejects_interrupted_run` (revised) | Planned |
| B7 correctness | `--from-checkpoint` on a run with no checkpoint yet errors clearly | `test_extract_from_checkpoint_no_checkpoint_yet_errors` | Planned |
| Selection validation | `--selection ucb` on `--backend openevolve` → exit 1, clear message | `test_run_oe_rejects_non_weighted_selection` | Planned |
| Selection validation | `--selection fixed` on `--backend shinka` with weighted ensemble → `prior_probs` matches weights | `test_shinka_selection_fixed_prior_probs` | Planned |
| Selection validation | `--selection ucb` on `--backend shinka` with weighted ensemble → warning, uniform start | `test_shinka_selection_ucb_ignores_weights_warns` | Planned |
| Selection validation | `--selection thompson` + `--selection-kwarg cost_aware_coef=x` → warning + kwarg dropped (not passed to sampler ctor) | `test_shinka_selection_kwarg_routed_per_sampler` | Planned |
| `--llm-weight` | Honored on OE ensemble (overrides registry weight) | `test_run_oe_llm_weight_override` | Planned |
| `--llm-weight` | Honored on Shinka-fixed; warned-and-ignored on Shinka-ucb/thompson | `test_shinka_llm_weight_fixed_vs_bandit` | Planned |
| `reasoning_effort` | Per-member effort projects onto OE `llm.models[]` | `test_oe_ensemble_reasoning_effort_per_member` | Planned |
| `reasoning_effort` | Uniform effort → Shinka global pool set; disagreeing → warning + one value chosen | `test_shinka_reasoning_effort_global_pool` | Planned |
| `reasoning_effort` | Local/bridge-sourced member → inert warning on Shinka | `test_shinka_reasoning_effort_inert_local_warns` | Planned |
| `capabilities()` | `selection_strategies` and `per_member_reasoning_effort` correct per backend | `test_backend_capabilities_selection_and_effort_axes` | Planned |
| DB migration v12 | Fresh + v11-upgrade global DB gets `llms.reasoning_effort`; existing rows preserved | `test_db_migration_v12_llms_reasoning_effort` | Planned |
| DB migration v13 | Fresh + v12-upgrade global DB gets `ensemble_members.reasoning_effort`; existing rows preserved | `test_db_migration_v13_ensemble_members_reasoning_effort` | Planned |
| `--config-override` no-op warn | Unrecognized override key warns; recognized key is silent | `test_config_override_noop_key_warns` | Planned |
| E2E | Shinka bandit-ensemble scenario against the fake server (2+ members, `--selection ucb`) | `tests/e2e/test_shinka_ensemble_bandit.py` (new) | Planned |
| Zero-regression | Full existing suite (1289+ tests) passes unmodified on the OE single-LLM default path | regression run | Planned |

---

## PR Grouping

### PR-W0 — Correctness slice (B1 + B2 + B7)

**Tasks**: S17-01..09
**Files**: `infra/backends/openevolve.py`, `infra/backends/base.py` (hoisted helpers), `cli/solution.py`, `core/solution.py` (or wherever extract logic lives), `tests/integration/test_solution.py`, `tests/integration/test_openevolve_shutdown.py` (new), wrapper contract test (new).
Independent of Wave 1/2 — can merge first and be released standalone if needed, but the plan is to bundle the whole sprint into v0.17.0.

### PR-W1a — Models, DB migrations, capabilities widening

**Tasks**: S17-10..15
**Files**: `infra/db.py` (migrations v12+v13), `models/llm.py`, `models/run.py`, `infra/backends/base.py` (`BackendCapabilities`, `BackendRunSpec`).
Foundation for both W1b and W1c — must merge first within Wave 1.

### PR-W1b — Shinka ensemble + bandit mapping

**Tasks**: S17-19..21, S17-23 (Shinka half)
**Files**: `infra/backends/shinka.py`.
Depends on PR-W1a.

### PR-W1c — OE `--llm-weight` + CLI wiring + orchestrator validation

**Tasks**: S17-16..18, S17-22, S17-23 (OE half)
**Files**: `cli/run.py`, `core/run.py`, `infra/backends/openevolve.py`.
Depends on PR-W1a. **Parallel with PR-W1b** (different files: `shinka.py` vs `openevolve.py`+`cli/run.py`+`core/run.py`).

### PR-W2a — Per-LLM `reasoning_effort`

**Tasks**: S17-24..28
**Files**: `cli/llm.py`, `core/llm.py`, `infra/backends/openevolve.py`, `infra/backends/shinka.py`.
Depends on PR-W1a (needs the migrated `reasoning_effort` column + model field) and is independent of PR-W1b/W1c logic (different CLI surface — `llm`/`ensemble` commands, not `run`), though it touches the same two backend files as W1b/W1c — **sequence after both merge** to avoid conflicts in `openevolve.py`/`shinka.py`.

### PR-W2b — `--llm-weight` polish, doc example, B9 no-op warning

**Tasks**: S17-29..30
**Files**: `docs/guides/` (or spec example), `infra/backends/openevolve.py`, `infra/backends/shinka.py`.
Depends on PR-W1b, PR-W1c, PR-W2a (touches the same backend files — sequence last within Wave 2).

### PR-W3 — Polish

**Tasks**: S17-31..33
**Files**: `infra/backends/openevolve.py` (config template), `config.py`, `infra/db.py` (no schema change, just consistency), `cli/__init__.py` or global options module (`--global-db`), doc files.
Depends on all prior waves for the final regression sweep (S17-33).

---

## Parallelization

### Dependency graph

```
Sprint 016a (v0.16.1) complete
          │
          ├──> PR-W0 (correctness: B1+B2+B7)                     ← fully independent
          │        S17-01 → S17-02 (B1 fix + test)
          │        S17-03 → S17-04 → S17-05 → S17-06 (B2 chain)
          │        S17-07 → S17-08 → S17-09 (B7 chain)
          │        (B1/B2/B7 sub-chains are parallel to each other; share only
          │         infra/backends/openevolve.py — same agent or sequenced commits)
          │
          ├──> PR-W1a (models + DB migrations v12/v13 + capabilities)  ← independent
          │        S17-10 → S17-11 (migrations, sequential: v12 before v13)
          │        S17-12 (LLMEntry/EnsembleMember field) ── after S17-11
          │        S17-13 (BackendCapabilities) ── parallel with S17-10/11/12
          │        S17-14 (BackendRunSpec) ── after S17-13
          │        S17-15 (RunConfig) ── after S17-14
          │
          ├──────────┬──> PR-W1b (Shinka ensemble+bandit)   ← needs PR-W1a
          │          │        S17-19 → S17-20 → S17-21 → S17-23(Shinka half)
          │          │
          │          └──> PR-W1c (OE llm-weight + CLI + orchestrator validation) ← needs PR-W1a
          │                   S17-16 → S17-17 → S17-18 → S17-22 → S17-23(OE half)
          │              (PR-W1b and PR-W1c touch disjoint files — parallel)
          │
          ├──────────────────────> PR-W2a (reasoning_effort)  ← needs PR-W1a; sequence AFTER W1b+W1c merge
          │                             S17-24 → S17-25 → S17-26 → S17-27 → S17-28
          │
          ├──────────────────────────────> PR-W2b (llm-weight polish, doc, B9 warn) ← needs W1b+W1c+W2a
          │                                     S17-29, S17-30 (parallel with each other)
          │
          └──────────────────────────────────────> PR-W3 (polish + full regression) ← needs everything
                                                        S17-31, S17-32 (parallel) → S17-33 (final sweep)
```

### Critical path

```
S17-10 → S17-11 → S17-12 → S17-14 → S17-15 → S17-16 → S17-17 → S17-18 → S17-22 → S17-23
   → S17-24 → S17-25 → S17-26 → S17-27 → S17-28 → S17-29/30 → S17-33
```

Minimum sequential depth through the ensemble core + support chain: ~16 tasks. PR-W0 (correctness slice) runs fully in parallel with this chain — it touches only `openevolve.py`'s runner class and `solution.py`, not the config-builder functions the ensemble work touches, so the two waves can be developed by different agents simultaneously and merged in either order (front-load B1/B2/B7 merges first per the "front-load the correctness slice" instruction, but no code dependency forces it).

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Correctness (PR-W0) | S17-01..09 | Sprint 016a merged | Agent 1 |
| B — Models/DB/capabilities (PR-W1a) | S17-10..15 | Sprint 016a merged | Agent 2 |
| C — Shinka ensemble+bandit (PR-W1b) | S17-19..21, S17-23 (Shinka half) | PR-W1a merged | Agent 3 |
| D — OE llm-weight + CLI (PR-W1c) | S17-16..18, S17-22, S17-23 (OE half) | PR-W1a merged | Agent 4 |
| E — reasoning_effort (PR-W2a) | S17-24..28 | PR-W1b + PR-W1c merged | Agent 3 or 4 (same backend files) |
| F — llm-weight polish/doc/B9 (PR-W2b) | S17-29..30 | PR-W2a merged | Agent 2 or new |
| G — Polish + regression (PR-W3) | S17-31..33 | PR-W2b merged | Agent 1 |

Peak parallelism: **4 agents** (streams A, B, C, D) once PR-W1a is merged and PR-W0 is running concurrently. Streams C and D are the highest-value parallel pair — same wave, disjoint files.

### Conflict risks

- **`infra/backends/openevolve.py`** — touched by PR-W0 (B1/B2 fixes, `_shutdown_runner`), PR-W1c (`--llm-weight`, `--selection` reject, `_build_ensemble_llm_config`), PR-W2a (`reasoning_effort` per-member), PR-W3 (config template). **Highest conflict-risk file this sprint.** Recommended sequencing: PR-W0 merges first (touches only the `OpenEvolveRunner.run()` method and wrapper template, not the config builder) → PR-W1c rebases → PR-W2a rebases on W1c → PR-W3 rebases last.
- **`infra/backends/shinka.py`** — touched by PR-W1b (ensemble/bandit mapping) and PR-W2a (`reasoning_effort` global pool). Sequence: PR-W1b merges first, PR-W2a rebases.
- **`infra/backends/base.py`** — touched by PR-W0 (hoisted `_current_child_pids`/`_reap_run_children`), PR-W1a (`BackendCapabilities`, `BackendRunSpec` widening). These are additive in different sections; low risk, but merge PR-W1a before PR-W0 finalizes its hoist **or** coordinate — recommend PR-W1a merges first since it establishes the widened dataclasses, then PR-W0's hoist lands cleanly on top (or vice versa if PR-W0 is ready first — either order works since the changes are in different classes/functions).
- **`infra/db.py`** — touched only by PR-W1a (migrations v12/v13). No other PR should touch it this sprint. Low risk.
- **`cli/run.py`** — touched by PR-W1c only (new flags). No conflict.
- **`cli/llm.py`** — touched by PR-W2a only (`--reasoning-effort`). No conflict.
- **`core/run.py`** — touched by PR-W1c (validation dispatch) only. No conflict.
- **`tests/integration/test_solution.py`** — touched by PR-W0 only (B7 revision). No conflict.

**Recommended merge order**: PR-W1a → (PR-W0 ∥ PR-W1b ∥ PR-W1c, in any order relative to each other, each rebased on W1a) → PR-W2a (rebased on W1b+W1c) → PR-W2b (rebased on W2a) → PR-W3 (rebased on W2b, runs the final full regression).

---

## Exit Criteria

The sprint is complete when ALL of the following hold:

1. **Correctness slice shipped**: the OE wrapper aggregation no longer crashes on a non-numeric metric field (B1, with a passing exec test — none existed before); a completed/failed OE run's process does not busy-loop or hang after `run()` returns (B2, symmetric to #224); `solution extract --from-checkpoint` recovers the best program from an interrupted/failed OE run's latest checkpoint, while the **default** `solution extract` behavior on an interrupted run is unchanged (still rejects) (B7).
2. **Cross-engine ensemble comparison runnable end-to-end**: the same registered ensemble (2+ members, explicit weights) runs successfully on `--backend openevolve` (weighted), `--backend shinka --selection fixed` (same weights, apples-to-apples), and `--backend shinka --selection ucb` (adaptive, weights deliberately ignored with a warning) — the headline demo from ADR-007 A2.
3. **Zero behavior change on the OE single-LLM default path**: a `revolver run` with a single registered LLM (no ensemble, no `--selection`/`--llm-weight`/`--reasoning-effort` flags) produces byte-identical config output to pre-sprint behavior; the full pre-existing regression suite passes unmodified (imports/fixtures aside).
4. **Two capability asymmetries surfaced honestly, not silently**: `--selection` non-`fixed` on OpenEvolve is **rejected** with a clear message; `--llm-weight`/registry weights supplied under a Shinka adaptive mode (`ucb`/`ucb1`/`thompson`) **warn** that they are ignored; per-member `reasoning_effort` disagreement on Shinka **warns**; `reasoning_effort` on a local/bridge-sourced Shinka member **warns** it is inert. All four are `capabilities()`-driven, not hard-coded backend-name branches.
5. **DB migrations v12 (`llms.reasoning_effort`) and v13 (`ensemble_members.reasoning_effort`) apply cleanly** on both fresh and upgraded (v11→v12→v13) global databases; existing rows preserved.
6. **`--config-override` no-op keys warn** (B9) rather than silently doing nothing, composing with the per-sampler kwarg routing (A5).
7. **Full regression green**: existing suite (1289+ tests baseline) passes on the no-shinka env; all Shinka L2 tests (existing + new ensemble/bandit scenarios) pass on the shinka env; new L3 E2E Shinka bandit-ensemble scenario passes against the fake server; CI green (Lint + Test 3.12/3.14).
8. **Spec/DES/validation doc cascade complete** (done spec-before-code, session 055): ADR-007 amended (A1–A5), FR-RUN-049/050/051 + FR-RUN-046 rewrite, FR-LLM-026, FR-EVL-021, specifications §4.5, DES-005/002/006/001 (migrations v12/v13), traceability + val-integration + val-e2e — spec-reviewer + validation-reviewer both passed (findings fixed). Only the post-release doc-reviewer pass (README/guides vs shipped CLI) remains for the v0.17.0 release checklist.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Shinka bandit kwarg-per-sampler projection is a wrong-key `TypeError` minefield** — `llm_dynamic_selection_kwargs` is spread verbatim into whichever sampler class was selected; a single misrouted key crashes the run at launch, not at dry-run. | High | Front-load per-sampler branching (S17-21) with an explicit allow-list per sampler (`fixed`: none; `ucb`/`ucb1`: `cost_aware_coef` + Shinka's own documented ucb kwargs; `thompson`: its own documented kwargs) verified against `prioritization.py` constructors directly, not inferred; L2 test asserts the exact kwargs dict passed to each sampler class for all 4 `--selection` values. |
| **`reasoning_effort` global-pool limitation on Shinka is easy to under-communicate** — a user setting per-member effort on a Shinka ensemble gets a merged/warned value, and it is silently inert on local/bridge members regardless of the merge outcome. | Medium | Two distinct, always-checked warnings (disagreement warning + local-inert warning, S17-27) with test coverage for both (S17-28); doc example (S17-29) explicitly walks through the OE-only nature of per-member effort so the limitation is documented, not just warned at runtime. |
| **`infra/backends/openevolve.py` is the highest-conflict file this sprint** (touched by PR-W0, PR-W1c, PR-W2a, PR-W3). | Medium | Strict merge sequencing (see Conflict risks above); each PR rebases on the previous before opening; where possible, assign the same agent to sequential PRs touching this file to reduce rebase friction. |
| **DB migration ordering** (v12 must precede v13; both must land after the current head v11) — a mis-sequenced migration dict entry silently corrupts the upgrade path for any DB stuck between versions. | Low | Follow the exact `MIGRATIONS`/`_run_migrations()` pattern already established for v9/v10/v11 (simple `ALTER TABLE ADD COLUMN` wrapped in `contextlib.suppress(sqlite3.OperationalError)`, then `CURRENT_SCHEMA_VERSION` bump); dedicated migration tests per version (S17-10/S17-11) mirror `test_db_migration_v10`/`v11` structure exactly. |
| **B2's OE `_shutdown_runner` reintroduces the #159 `wait=True` hang** if a future OE upgrade changes which executor is reachable from the controller. | Low | Mirror the Shinka pattern exactly: `getattr`-guarded, `wait=False` always, wrapped in `contextlib.suppress(Exception)`; regression test (S17-06) explicitly asserts no `wait=True` call site exists in the new code. |
| **Reviewer-agent idle-timeout flakiness** (observed repeatedly in S16/S16a) may slow the PR review step for this sprint's 7 PRs. | Low | Per the S16 carry-over: run review agents in the foreground, prefer sonnet, raise `maxTurns`; fall back to main-session self-review against load-bearing risk areas if an agent dies mid-review (established workaround). |

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / Y integration tests passing

### Demo-able features
- [ ] Cross-engine ensemble comparison: OE-weighted vs Shinka-fixed vs Shinka-ucb on the same registered ensemble
- [ ] Per-LLM `reasoning_effort` honored per-member on OE, global-pooled-with-warning on Shinka
- [ ] `--llm-weight` per-run override honored on OE and Shinka-fixed, warned on Shinka-adaptive
- [ ] B1 — OE wrapper no longer crashes on a non-numeric metric field
- [ ] B2 — OE run no longer busy-loops/hangs after completion
- [ ] B7 — `solution extract --from-checkpoint` recovers the best of an interrupted OE run
- [ ] `--config-override` warns on a no-op key (B9)
- [ ] `REVOLVER_HOME` / `--global-db` consistent across `config.py` and `db.py` (B6)

### Carry-over
- Top-N extraction (#299) → S18
- Any items not completed within this sprint's waves
