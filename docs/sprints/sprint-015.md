# Sprint 015 — ShinkaEvolve Parity Push + Hardening (ADR-007 P3)

**Status**: Planning
**Goal**: Close the gap between S14's Shinka MVP and full parity with the OpenEvolve path, anchored by three demo-surfaced correctness issues: cost/token accounting completeness (#300), LLM-setting surface and thinking-model control (#301), and unproductive-run detection (#302). Simultaneously pay down the S14 carry-over debt (resume clone parity, doc/spec drift, orchestrator cleanups, shim removal) and deliver minor CLI/UX polish (#303–306).
**Demo**: `revolver run --backend shinka` on a Gemini thinking-model run reports a cost within 10% of the provider bill; a run where every proposal fails reports `status: completed_with_errors`; `run resume` on a Shinka parent creates an independent artifact tree (separate `shinka-output/` with a copied `programs.sqlite`); `revolver run --help` shows backend-neutral wording; the `infra/openevolve.py` re-export shim is gone; DES-005 is rewritten and the spec/validation doc cascade is closed.
**Source**: ADR-007 (P3 phase), sprint-014.md §Sprint Review →Carry-over (canonical S14 list, superseded by this document as the S15 plan of record), backlog #299–306 (2026-06-13).
**Predecessor**: Sprint 014 (v0.14.0) — ShinkaEvolve MVP, real engine E2E.

> **Note**: This sprint plan supersedes the informal carry-over list in `sprint-014.md §Sprint Review → Carry-over` as the S15 plan of record. All items from that list are absorbed here, either as explicit tasks or explicitly de-scoped to S16/TBD.

---

## Source

- ADR: [ADR-007](../architecture/adr/ADR-007-pluggable-evolution-backend.md) — decisions D1–D6, roadmap P3 phase
- Backlog: #299 (top-N promotion), #300–306 (demo-surfaced smoke-test issues, 2026-06-13)
- Sprint 014 carry-over: `sprint-014.md §Sprint Review → Carry-over` (all items absorbed below)
- Design: [DES-005](../architecture/design/DES-005-run-orchestration.md) (planned full rewrite), [DES-006](../architecture/design/DES-006-eval-loop.md) §1.3
- Specs: FR-RUN-047/048, NFR-024, spec-run (resume semantics, `--backend` on `project init` / `problem version create`)
- Validation: [val-e2e-tests.md](../validation/val-e2e-tests.md) (Scenario 3 status, fake-server details), [traceability-matrix.md](../validation/traceability-matrix.md) (FR-RUN-036..039 rows)

---

## Scope

### In scope

| Theme | Backlog / carry-over ref | Content |
|---|---|---|
| **Cost/token accounting — Shinka** | #300 (🔴 critical) | Capture attempt/failure costs from `gen_*/attempts/**/metadata.json` and `gen_*/failure.json`; capture thinking/reasoning output tokens; fold all into the `TokenUsage` aggregate reported per run |
| **LLM-setting surface** | #301 (🟠 major); extends #120 to Shinka | Expose `max_patch_attempts`, `max_tokens`, and `reasoning_efforts` in `ShinkaBackend.build_config()`; propagate from the registered `LLMEntry` and/or a `--config-override`; document the correctness-vs-cost tension |
| **Unproductive-run status** | #302 (🟠 major) | Detect "0 successful child programs" post-run on Shinka; map to `completed_with_errors` status with a user-visible warning |
| **Resume clone parity** | S14 carry-over item 1 | Copy `programs.sqlite` + `gen_*` dirs from the parent `shinka-output/` into the new run's `shinka-output/` before calling `ShinkaEvolveRunner.run()`; remove the shared-mutable-DB limitation documented in `ShinkaBackend.resume()` |
| **`resume_precheck` hook** | S14 carry-over item 2 | Replace `backend.name == "openevolve"` string guard in the orchestrator resume staging with a `backend.resume_precheck(parent_run_dir, new_run_dir)` hook or equivalent backend-polymorphic dispatch |
| **Resume `--iterations` semantics** | S14 carry-over item 3 | Pin "N more on top of the parent chain" in DES-005 §2 and spec-run §2.3 resume step |
| **`--backend` in spec/DES for `project init` and `problem version create`** | S14 carry-over item 4 | Document the `--backend` flag in spec-project and DES-003; add FR cross-reference |
| **val-e2e-tests.md drift** | S14 carry-over item 5 | Update Scenario 3 status, fake-server latency default, content-based responses, `--source local` notation |
| **Defensive `iterations` fallback removal** | S14 carry-over item 6 | Remove the now-dead backend-side defensive fallback in `openevolve.py` `launch()`/`resume()`; bind removal comment to `core.run.DEFAULT_ITERATIONS` |
| **`PYTHONUNBUFFERED` env restore** | S14 carry-over item 7 | After the engine subprocess exits, restore `os.environ["PYTHONUNBUFFERED"]` in both backends (or use a context manager) |
| **`--config-override` typo at launch** | S14 carry-over item 8 | Validate `--config-override` keys against the Shinka config schema at dry-run time (currently silently dropped via `_dataclass_kwargs`) |
| **Ensemble→bandit mapping** | S14 carry-over item 9 | In `ShinkaBackend.build_config()`, map a weighted `EnsembleEntry` to Shinka's bandit selection (`llm_dynamic_selection="ucb"`); warn that member weights and per-member overrides are dropped |
| **Multi-language passthrough** | S14 carry-over item 10; #132 | Pass `language` field from `BackendRunSpec` through Shinka's `EvolutionConfig.language`; surface via `capabilities().multi_language = True` for Shinka |
| **Richer cost mapping / `max_api_costs`** | S14 carry-over item 11 + #300 | Expose Shinka's `max_api_costs` budget cap as a `--config-override`-reachable `backend_extras` key; document in config template; folded into #300's accounting task |
| **`infra/openevolve.py` re-export shim removal** | S14 carry-over item 12 | Delete `infra/openevolve.py` shim; update all internal imports and tests that still reference it |
| **DES-005 rewrite** | S14 carry-over item 13 | Full rewrite of DES-005 as a backend-neutral run orchestration design (title rename; remove the rank-N-on-demand promotion narrative; capture actual S9-B2 rank-1-only model; add §Shinka path; backend capability matrix); remove stale §run-dir layout |
| **Pre-existing doc debts** | S14 carry-over item 14 | FR-RUN-042 numbering gap; FR-RUN-036..039 traceability rows; DES-005 title |
| **Top-N extraction** | #299 | Gate `_BEST_PROGRAMS_COUNT` behaviour behind `capabilities().top_n_extraction`; for Shinka, materialize rank-2..N from `programs.sqlite` `code` column; expose as `solution extract --rank N`; OE scope: assess what `database.json` exposes and document gap |
| **CLI/UX polish** | #303–306 | Neutralize OE-specific wording in `run --help` and `run population` help; `problem version create` positional tag; `programs_stored` counter reconcile; rank-1 score display in `run info` |

### Explicitly out of scope (S16/TBD)

- SLURM `LocalJobConfig` alternatives
- Prompt evolution / novelty judge / embedding model configuration
- `revolver problem test --wrapper` (backlog #122)
- Multi-language evaluator pattern docs (backlog #135)
- Program support files (#133), dependency traceability (#134)
- Typed `OEExtras`/`ShinkaExtras` (deferred per ADR-007 D4 note — dict first)

---

## Prioritization

| Priority | Items | Rationale |
|---|---|---|
| **Must-do (demo-blocking / correctness)** | #300, #301, #302 | Cost figures are ~20× wrong; empty-content LLM responses from thinking models break runs silently; 0-children runs are invisible failures. These block credible production use. |
| **Must-do (parity / integrity)** | Resume clone parity, `resume_precheck`, shim removal, `PYTHONUNBUFFERED` restore | The shared-DB resume is a correctness hazard (cost/population over-attribution to child runs). Shim removal is a maintenance gate. |
| **Should-do (spec completeness)** | DES-005 rewrite, resume semantics doc, `--backend` in spec/project/problem, val-e2e drift, FR-RUN-036..039, defensive fallback removal, ensemble→bandit, `--config-override` validation | Necessary for the documentation cascade before the next release. Parallel-workable. |
| **Should-do (capability)** | #299 top-N extraction, multi-language passthrough | High user value; Shinka's SQLite makes top-N reliable for the first time. |
| **Nice-to-have (polish)** | #303–306 (help wording, positional tag, counter reconcile, rank-1 score) | Low risk, low effort; include in CLI polish PR if time allows. |

---

## Tasks

### Functional scope A — Cost / token accounting (backlog #300)

| # | Task | Layer | PR | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| S15-01 | **Shinka attempt/failure cost sweep**: extend `ShinkaBackend.collect_token_usage()` to walk `run_dir/shinka-output/gen_*/attempts/**/metadata.json` (key `llm_cost` float) and `gen_*/failure.json` (key `api_costs` float) in addition to the `programs.sqlite` rows; aggregate all found costs into the `estimated_cost_usd` total. Handle missing files gracefully (best-effort). | infra | PR-A | — | `test_shinka_cost_attempt_failure` passes; total cost with fixture attempt/failure files matches expected sum; no crash on absent dirs |
| S15-02 | **Thinking/reasoning token capture**: in `collect_token_usage()`, extract `thinking_tokens` from each `metadata.llm_result` row in `programs.sqlite` and from attempt metadata if present; accumulate into a new `thinking_tokens` field on `TokenUsage` (or into `completion_tokens` with a separate `thinking_tokens` supplementary counter); report in `run info` token breakdown. | infra | PR-A | S15-01 | `test_shinka_thinking_tokens` passes; `run info` shows thinking-token line on Shinka runs; `thinking_tokens > 0` when fixture includes a thinking-model row |
| S15-03 | **`max_api_costs` exposure**: add `max_api_costs: float \| None` to the `ShinkaBackend` config template and wire it through `build_config()` into Shinka's `EvolutionConfig`; expose as a `backend_extras` key in `ResolvedConfig` so dry-run shows it. Allow override via `--config-override backend_extras.max_api_costs=<float>`. | infra | PR-A | S15-01 | Dry-run shows `backend_extras.max_api_costs` when set; `launch()` passes it to `ShinkaEvolveRunner`; existing tests unaffected |
| S15-04 | **Cost accounting tests**: add/extend L2-Shinka contract tests (`test_shinka_db.py` or new file) covering: (a) attempt-dir cost sweep with fixture `gen_*` directory tree; (b) thinking-token sum across rows; (c) `max_api_costs` present in dry-run output. | test | PR-A | S15-01, S15-02, S15-03 | All 3 new scenarios pass with shinka installed; auto-skip without |

### Functional scope B — LLM-setting surface + thinking control (backlog #301, extends #120)

| # | Task | Layer | PR | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| S15-05 | **`max_patch_attempts` default**: in `ShinkaBackend.build_config()`, inject `max_patch_attempts` defaulting to `10` (Shinka's own example default) unless overridden; expose in the config template with a comment explaining the single-attempt failure risk. | infra | PR-B | — | `build_config()` output contains `max_patch_attempts: 10` by default; `--config-override max_patch_attempts=1` reduces it |
| S15-06 | **`max_tokens` propagation**: propagate the registered `LLMEntry.max_tokens` (if set) into Shinka's `llm_kwargs.max_tokens`; when `max_tokens` is not set on the LLM entry, default to `16384` for the Shinka path (not `4096`) to avoid `None`-content responses from thinking models. Document the tension: higher `max_tokens` → more thinking-token spend. | infra | PR-B | — | `build_config()` sets `max_tokens >= 16384` when not explicitly set; `LLMEntry.max_tokens` value propagated when present |
| S15-07 | **`reasoning_efforts` exposure**: add `reasoning_efforts` as a per-model LLM config key in `ShinkaBackend.build_config()` (`llm_kwargs.reasoning_effort` map from Shinka's per-provider naming); expose as a `--config-override`-reachable parameter; document as the primary cost lever for thinking models. | infra | PR-B | S15-05 | Dry-run shows `reasoning_efforts` in `backend_extras` when set; `launch()` passes it through; a `reasoning_efforts=low` override reduces reported thinking tokens in a mock test |
| S15-08 | **LLM-setting tests**: L2-Shinka contract tests: (a) `build_config()` with default `max_patch_attempts=10`; (b) `max_tokens` escalation from 4096 to 16384 when not set; (c) `reasoning_efforts` present in config when override applied. | test | PR-B | S15-05, S15-06, S15-07 | All 3 new config-projection scenarios pass |

### Functional scope C — Unproductive-run status (backlog #302)

| # | Task | Layer | PR | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| S15-09 | **Shinka unproductive-run detection**: in `core/run.py` post-run path (after `ShinkaBackend` engine exits), call `backend.count_valid(run_dir)` and compare vs the init program count (1 for single init); if `count_valid == 0` (or `== initial_program_count` — only init programs ever stored) and at least one generation was attempted, mark status `completed_with_errors` and emit a warning message "Run completed but no successful child programs were generated". | domain | PR-C | — | `test_shinka_unproductive_run` passes: mocked runner exits, fixture DB has only init row, status is `completed_with_errors`, warning logged |
| S15-10 | **`run info` unproductive-run display**: add a visible warning line in `run info` output when `status == completed_with_errors` and `valid_iterations == 0`; differentiate from the existing "some evaluations failed" path. | cli | PR-C | S15-09 | `run info` on an unproductive-run record shows `WARNING: 0 successful child programs` line |
| S15-11 | **Unproductive-run test coverage**: L2 test `test_run_shinka_unproductive`: fixture DB with only the init program row; mock runner; assert status `completed_with_errors` and `run info` warning. | test | PR-C | S15-09, S15-10 | Test passes with shinka installed; auto-skip without |

### Functional scope D — Resume clone parity + `resume_precheck` hook

| # | Task | Layer | PR | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| S15-12 | **`ShinkaBackend.resume()` clone implementation**: copy `parent_run_dir/shinka-output/programs.sqlite` and all `gen_*` dirs into `new_run_dir/shinka-output/` before calling `ShinkaEvolveRunner.run()`; update the `results_dir` in the Shinka config accordingly. Remove the "in-place continuation" docstring limitation note from S14. | infra | PR-D | — | Mocked resume test shows a new `shinka-output/` populated with copied DB + gen dirs; parent `shinka-output/` is unmodified after resume |
| S15-13 | **`resume_precheck` backend hook**: introduce `backend.resume_precheck(parent_run_dir: Path, new_run_dir: Path) -> None` (raises `BackendError` on precondition failure) in `EvolutionBackend` protocol; implement for `OpenEvolveBackend` (wraps the existing OE checkpoint-existence check) and `ShinkaBackend` (verifies `parent/shinka-output/programs.sqlite` exists); replace the `backend.name == "openevolve"` string guard in `core/run.py` resume staging. | infra/domain | PR-D | S15-12 | The string guard `if backend.name == "openevolve"` is gone from `core/run.py`; `test_resume_precheck_oe` and `test_resume_precheck_shinka` pass; missing DB raises clear error |
| S15-14 | **Resume semantics documentation**: pin "N more on top of the parent chain" in `spec-run.md §2.3` resume step (applies to both backends); add the same clarification to DES-005 §5 (resume section). | doc | PR-D | S15-12 | `spec-run.md` and DES-005 both state the uniform resume-iterations semantics |
| S15-15 | **Resume clone parity tests**: L2-Shinka test `test_shinka_resume_clone`: fixture parent run dir with `shinka-output/` containing a `programs.sqlite`; resume creates a new run dir with an independent copy of the DB; mocked runner receives the new `results_dir`. L2-OE regression: `test_resume_precheck_oe` still passes. | test | PR-D | S15-12, S15-13 | Both tests pass; auto-skip for Shinka test without shinka installed |

### Functional scope E — Top-N extraction (backlog #299)

| # | Task | Layer | PR | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| S15-16 | **`capabilities().top_n_extraction` gate**: update `ShinkaBackend.capabilities()` to return `top_n_extraction=True`; update `OpenEvolveBackend.capabilities()` to reflect the real OE state (single best program from checkpoint, no reliable top-N from `database.json` — return `top_n_extraction=False` with a docstring explaining why). | infra | PR-E | — | `capabilities()` return values match the declared state; no runtime behavior change |
| S15-17 | **Shinka `get_top_programs(k)` extraction**: extend `ShinkaBackend.parse_population()` (or add a dedicated `extract_top_n(run_dir, n) -> list[dict]`) to retrieve the top-N programs by `combined_score` from `programs.sqlite` `code` column; expose via `core/run.py` `get_population()` path for downstream extraction. | infra | PR-E | S15-16 | `extract_top_n(run_dir, 3)` returns 3 dicts with `code`, `combined_score`, `id` from fixture DB ordered by score desc |
| S15-18 | **`solution extract --rank N` revival (Shinka only)**: in `core/solution.py`, add `extract_top_n_solutions(run_id, n)` that calls the backend's top-N extraction and materializes `programs/rank-1.py` … `programs/rank-N.py` + inserts multiple solution records; gate on `capabilities().top_n_extraction` (raise `CapabilityError` on OE runs). Update `cli/solution.py` `solution extract` to accept `--rank N` option (default 1; `N > 1` on OE → clear error with capability hint). | domain/cli | PR-E | S15-17 | `revolver solution extract --rank 3` on a Shinka run writes `rank-1.py`, `rank-2.py`, `rank-3.py`; `solution list` shows all three; same command on an OE run exits with `CapabilityError` and hint |
| S15-19 | **Top-N tests**: L2-Shinka: `test_shinka_top_n_extraction` (fixture DB with 5 programs; extract rank 1..3; files written); `test_solution_extract_rank_oe_capability_error` (OE run; `--rank 2` → exit with message). | test | PR-E | S15-17, S15-18 | Both tests pass |

### Functional scope F — Shim removal + env cleanup

| # | Task | Layer | PR | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| S15-20 | **Delete `infra/openevolve.py` re-export shim**: remove the file; update all internal imports and all test files that still reference `infra.openevolve` (including L2-OE test imports, if any survived the S13 shim). Verify no public API was exported from this shim that is not already available via `infra.backends.openevolve`. | infra | PR-F | — | `infra/openevolve.py` file does not exist; `ruff` + `mypy` clean; all L2-OE tests pass without the shim |
| S15-21 | **`PYTHONUNBUFFERED` env restore**: wrap the `os.environ["PYTHONUNBUFFERED"] = "1"` mutation in both `OpenEvolveBackend.launch()` and `ShinkaBackend.launch()` in a `try/finally` or a `contextlib.contextmanager` that restores the original value (or deletes the key if it was absent) after the engine call. | infra | PR-F | — | After `launch()` returns, `PYTHONUNBUFFERED` is restored to its pre-launch state; unit test covers both "was absent" and "had a prior value" cases |
| S15-22 | **Defensive `iterations` fallback removal**: remove the dead fallback `cfg.get("max_iterations", 10)` from `OpenEvolveBackend.launch()` and `resume()` (bound to `core.run.DEFAULT_ITERATIONS` since S14-05); add a comment referencing the canonical resolution point. | infra | PR-F | — | The fallback line is gone; `grep -r "max_iterations.*10"` returns no hits in `infra/`; existing OE tests pass |

### Functional scope G — `--config-override` validation + ensemble→bandit

| # | Task | Layer | PR | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| S15-23 | **`--config-override` typo-at-dry-run**: in `ShinkaBackend.validate_config()` (called from the orchestrator during dry-run), cross-check `--config-override` keys against the Shinka `EvolutionConfig`/`DatabaseConfig`/`LocalJobConfig` dataclass field names; warn (not fatal) on unknown keys instead of silently dropping them at `_dataclass_kwargs` filtering. | infra | PR-G | — | `revolver run --backend shinka --dry-run --config-override nonexistent_key=1` emits a WARNING about the unknown key at dry-run time; known keys pass silently |
| S15-24 | **Ensemble→bandit mapping**: in `ShinkaBackend.build_config()`, when `BackendRunSpec.llm` is an `EnsembleEntry`, emit `llm_dynamic_selection="ucb"` and pass all member models (weighted→bandit, weights dropped); emit a WARNING that member weights and per-member overrides are not supported on the Shinka backend. | infra | PR-G | — | `test_shinka_ensemble_bandit_mapping` passes: ensemble with 3 members → `llm_dynamic_selection="ucb"` + 3 model strings + warning logged; weights absent from Shinka config |
| S15-25 | **Multi-language passthrough**: in `ShinkaBackend.build_config()`, pass `spec.language` to `EvolutionConfig.language` (already a field); update `ShinkaBackend.capabilities()` to set `multi_language=True`; document that OE's `file_suffix` equivalent for Shinka is `language`. | infra | PR-G | — | `build_config()` with `spec.language="cpp"` produces `language: "cpp"` in the Shinka config; `capabilities().multi_language` is `True` for Shinka |

### Functional scope H — CLI/UX polish (backlog #303–306)

| # | Task | Layer | PR | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| S15-26 | **Neutralize OE-specific CLI wording** (#303): change the `run` group help string from "Solution generation via OpenEvolve" to "Solution generation via the configured evolution backend"; change `run population` help from "MAP-Elites population" to "Current program population" (or "island population" for Shinka). | cli | PR-H | — | `revolver run --help` does not mention "OpenEvolve"; `revolver run population --help` does not mention "MAP-Elites"; existing tests unaffected |
| S15-27 | **`problem version create` positional tag** (#304): accept `TAG` as an optional positional argument in addition to `--tag TEXT`; if both are given, the positional takes priority (or errors); keep `--tag` for backward compat. | cli | PR-H | — | `revolver problem version create v1.2 --description "..."` works; `revolver problem version create --tag v1.2 --description "..."` still works; L2 test updated |
| S15-28 | **`programs_stored` counter reconcile** (#306): fix the discrepancy between the displayed `programs_stored` counter in `run info` and the actual count in `programs.sqlite`; ensure the counter reflects all stored programs (init + successful children); also populate `rank-1 score` in `run info` from `best_score` in the run record or via `ShinkaBackend.read_progress()` on demand. | domain/cli | PR-H | — | `run info` shows `programs_stored` equal to the DB row count; rank-1 score displayed when available |
| S15-29 | **Dataset split dual-use clarification** (#305): remove or relax the `train`-split-only warning in `revolver run` when the dataset has a single split; update help text to clarify that any split name is acceptable. | cli | PR-H | — | `revolver run` with a dataset registered under `all` or `both` split does not emit a confusing warning; help text updated |

### Functional scope I — Doc/spec debt (DES-005 rewrite + pre-existing debts)

| # | Task | Layer | PR | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| S15-30 | **DES-005 full rewrite**: rename DES-005 to "Run Orchestration (Backend-Neutral)" in the file header and in CLAUDE.md / architecture.md index; rewrite content as a backend-neutral orchestration design: remove the rank-N-on-demand promotion narrative (stale since S9-B2), capture the real rank-1-only model (or rank-N when `top_n_extraction = True`); add §Shinka path (wrapper contract, `generate_wrapper()`, `results_dir`); add backend capability matrix (table of `BackendCapabilities` fields and values per backend); add §resume semantics (uniform "N more" model); remove OE-specific §run-dir layout. | doc | PR-I | S15-14 | DES-005 title and content match the implemented design; spec-reviewer agent reports 0 FAIL / 0 WARN on DES-005 |
| S15-31 | **val-e2e-tests.md Scenario 3 update**: update Scenario 3 status from "Planned" to "Passing"; correct fake-server details (latency default 0, content-based responses, `--source local` notation); add `thinking_tokens` to the token-assertion section. | doc | PR-I | — | val-e2e-tests.md Scenario 3 status = Passing; fake-server description matches the S14 implementation |
| S15-32 | **FR-RUN-042 numbering gap + FR-RUN-036..039 traceability rows**: fill in any remaining numbering gap at FR-RUN-042 in spec-run.md (mark `[DELETED]` or reassign if appropriate); add traceability rows for FR-RUN-036..039 in the traceability matrix. | doc | PR-I | — | spec-run.md has no unexplained gaps in the FR-RUN-03x..04x range; traceability matrix has rows for FR-RUN-036..039 |
| S15-33 | **`--backend` in spec-project and DES-003**: document the `--backend` option on `project init` (affecting which config template is generated) and on `problem version create` (affecting which `validate_config()` implementation is called) in `spec-project.md` and `DES-003`. Add FR cross-references. | doc | PR-I | — | spec-project.md and DES-003 both mention `--backend` in the relevant command sections |

---

## PR Breakdown and Waves

### PR-A — Cost/token accounting (🔴 #300)

**Tasks**: S15-01, S15-02, S15-03, S15-04

Contents:
- Extended `ShinkaBackend.collect_token_usage()` (attempt-dir sweep + thinking tokens)
- `max_api_costs` wired through `build_config()` and `backend_extras`
- New `TokenUsage.thinking_tokens` field (or supplementary counter)
- L2-Shinka cost contract tests (3 new scenarios)

**Can start**: immediately (no dependency on other S15 tasks).

### PR-B — LLM-setting surface (🟠 #301)

**Tasks**: S15-05, S15-06, S15-07, S15-08

Contents:
- `max_patch_attempts=10` default in `build_config()`
- `max_tokens` escalation to 16384 default for Shinka + `LLMEntry.max_tokens` propagation
- `reasoning_efforts` via `--config-override` and config template
- L2-Shinka config-projection tests (3 new scenarios)

**Can start**: immediately (parallel with PR-A).

### PR-C — Unproductive-run status (🟠 #302)

**Tasks**: S15-09, S15-10, S15-11

Contents:
- `core/run.py` post-run `count_valid` check for Shinka; `completed_with_errors` branching
- `cli/run.py` `run info` unproductive-run warning line
- L2-Shinka unproductive-run test

**Can start**: immediately (parallel with PR-A and PR-B; touches `core/run.py` but in a different function from PR-D).

### PR-D — Resume clone parity + `resume_precheck` (carry-over)

**Tasks**: S15-12, S15-13, S15-14, S15-15

Contents:
- `ShinkaBackend.resume()` clone logic (copy DB + gen dirs)
- New `backend.resume_precheck()` protocol method + OE + Shinka implementations
- `core/run.py` string guard removed
- spec-run.md + DES-005 §5 resume semantics note
- L2 resume clone test + OE precheck regression

**Can start**: immediately (parallel with PR-A/B/C; the only `core/run.py` touch is the string guard removal — no conflict with PR-C which touches the post-run path).

### PR-E — Top-N extraction (#299)

**Tasks**: S15-16, S15-17, S15-18, S15-19

Contents:
- `capabilities().top_n_extraction` updated for both backends
- `ShinkaBackend.extract_top_n()` from `programs.sqlite`
- `core/solution.py` `extract_top_n_solutions()` + `cli/solution.py` `--rank N` option
- L2 tests: top-N extraction + OE capability error

**Can start**: immediately (independent of PR-A through PR-D; depends only on S15-16 being done before S15-17/18).

### PR-F — Shim removal + env cleanup (carry-over)

**Tasks**: S15-20, S15-21, S15-22

Contents:
- Delete `infra/openevolve.py`; update internal imports
- `PYTHONUNBUFFERED` context manager in both backends
- Defensive fallback removal

**Can start**: immediately. Note: if any other PR in this sprint adds imports to `infra.openevolve`, coordinate — but no S15 tasks should be adding new shim imports.

### PR-G — Config-override validation + ensemble→bandit + multi-language (carry-over)

**Tasks**: S15-23, S15-24, S15-25

Contents:
- `validate_config()` warning on unknown `--config-override` keys
- `ShinkaBackend.build_config()` ensemble→bandit mapping with warning
- Multi-language `spec.language` passthrough

**Can start**: immediately (parallel with all above; touches `infra/backends/shinka.py` only — no conflict with PR-A/B if they are also in `shinka.py`, so merge order within the Wave must be managed; see Conflict Risks below).

### PR-H — CLI/UX polish (#303–306)

**Tasks**: S15-26, S15-27, S15-28, S15-29

Contents:
- `cli/run.py` help string neutralization
- `cli/problem.py` positional tag
- `run info` programs_stored counter + rank-1 score
- Dataset split warning relaxation

**Can start**: after PR-F is merged (PR-F removes the shim; PR-H touching `cli/run.py` is safe after that; the two do not conflict if order is respected).

### PR-I — Doc/spec debt (carry-over + pre-existing)

**Tasks**: S15-30, S15-31, S15-32, S15-33

Contents:
- DES-005 full rewrite
- val-e2e-tests.md Scenario 3 update
- FR-RUN-042 gap + FR-RUN-036..039 traceability rows
- spec-project.md + DES-003 `--backend` doc

**Can start**: S15-30 after S15-14 (DES-005 resume section needs the semantics from PR-D first); S15-31/32/33 immediately.

---

## Wave Structure

```
Wave 1 (parallel — no shared state):
    PR-A  Cost/token accounting       — infra/backends/shinka.py + tests
    PR-B  LLM-setting surface         — infra/backends/shinka.py + tests
    PR-C  Unproductive-run status     — core/run.py (post-run path) + cli + tests
    PR-D  Resume clone parity         — infra/backends/shinka.py + core/run.py (resume path) + doc
    PR-E  Top-N extraction            — infra/backends/shinka.py + core/solution.py + cli + tests
    PR-F  Shim removal + env cleanup  — infra/backends/{oe,shinka}.py, delete infra/openevolve.py

Wave 2 (after Wave 1 merged, parallel):
    PR-G  Config-override + ensemble→bandit + multi-language  — infra/backends/shinka.py
    PR-H  CLI/UX polish                                       — cli/run.py, cli/problem.py
    PR-I  Doc/spec debt (DES-005, val-e2e, FR gaps)           — docs only
```

**Wave 1 caveat**: PR-A, PR-B, PR-D, PR-E, and PR-F all touch `infra/backends/shinka.py`. They must be merged in sequence within Wave 1 (not developed concurrently against the same branch). Recommended merge order within Wave 1: PR-F first (shim deletion clears the decks), then PR-A, PR-B, PR-D, PR-E in any order. PR-C and PR-H touch `core/run.py` and `cli/run.py` respectively but in disjoint functions — no conflict.

---

## Integration Tests (L2)

Tests from `val-integration-tests.md` and new scenarios that must pass at sprint end:

| Command / Area | Scenario | Test ID | Status |
|---|---|---|---|
| `run` (shinka, cost) | Attempt/failure dirs contribute to reported cost | `test_shinka_cost_attempt_failure` | Planned |
| `run` (shinka, cost) | Thinking tokens captured from `llm_result.thinking_tokens` | `test_shinka_thinking_tokens` | Planned |
| `run` (shinka, dry-run) | `max_api_costs` appears in `backend_extras` when set | `test_shinka_max_api_costs_dryrun` | Planned |
| `run` (shinka, config) | `build_config()` sets `max_patch_attempts=10` by default | `test_shinka_max_patch_attempts_default` | Planned |
| `run` (shinka, config) | `max_tokens` ≥ 16384 when not set on LLM entry | `test_shinka_max_tokens_escalation` | Planned |
| `run` (shinka, config) | `reasoning_efforts` present when override applied | `test_shinka_reasoning_efforts_override` | Planned |
| `run` (shinka, unproductive) | 0 successful children → `completed_with_errors` status | `test_shinka_unproductive_run` | Planned |
| `run info` | Unproductive-run warning visible | `test_run_info_unproductive_warning` | Planned |
| `run resume` (shinka) | Clone: new run dir has independent copy of programs.sqlite + gen dirs | `test_shinka_resume_clone` | Planned |
| `run resume` | `resume_precheck` OE: missing checkpoint → clear error | `test_resume_precheck_oe` | Planned |
| `run resume` | `resume_precheck` Shinka: missing programs.sqlite → clear error | `test_resume_precheck_shinka` | Planned |
| `solution extract --rank N` | Top-N extraction on Shinka run writes rank-1..N files | `test_shinka_top_n_extraction` | Planned |
| `solution extract --rank 2` | OE run raises CapabilityError with hint | `test_solution_extract_rank_oe_capability_error` | Planned |
| `run --config-override unknown=1 --dry-run` | Warning about unknown key at dry-run | `test_shinka_config_override_typo_warn` | Planned |
| `run --llm <ensemble>` (shinka) | Ensemble→bandit mapping with warning | `test_shinka_ensemble_bandit_mapping` | Planned |
| `run --help` | No mention of "OpenEvolve" in group help | `test_run_help_oe_neutral` | Planned |
| `problem version create <tag>` | Positional tag accepted | `test_problem_version_create_positional_tag` | Planned |
| Full OE regression | Existing 1248+ tests pass unmodified without shinka | regression run | Planned |
| Full Shinka suite | All Shinka L2 tests (14 S14 + ~16 S15 new) pass with shinka | shinka regression | Planned |

---

## Parallelization

### Dependency graph

```
v0.14.0 (Sprint 014 complete) ─────────────────────────────────────────────
    │
    ├──> PR-F  Shim removal + env cleanup      ← independent; recommended first
    │
    ├──> PR-A  Cost/token accounting           ← independent of PR-F
    │         │
    │         └── S15-01 → S15-02 → S15-04
    │                  └──> S15-03 → S15-04
    │
    ├──> PR-B  LLM-setting surface             ← independent
    │         │
    │         └── S15-05 → S15-07 → S15-08
    │                  └──> S15-06 → S15-08
    │
    ├──> PR-C  Unproductive-run status         ← independent
    │         │
    │         └── S15-09 → S15-10 → S15-11
    │
    ├──> PR-D  Resume clone parity             ← independent
    │         │
    │         ├── S15-12 → S15-13 → S15-15
    │         └── S15-14 (doc, after S15-12)
    │
    ├──> PR-E  Top-N extraction                ← independent
    │         │
    │         └── S15-16 → S15-17 → S15-18 → S15-19
    │
    ├──────── Wave 1 merge point ─────────────────────────────────────────
    │
    ├──> PR-G  Config-override + ensemble→bandit + multi-language
    │
    ├──> PR-H  CLI/UX polish
    │
    └──> PR-I  Doc/spec debt (S15-30 after S15-14; S15-31..33 immediately)
```

### Critical path

```
S15-01 → S15-02 → S15-04 (PR-A cost accounting, 3 sequential tasks)
```
or
```
S15-16 → S15-17 → S15-18 → S15-19 (PR-E top-N, 4 sequential tasks)
```

PR-E has the longest sequential chain (4 tasks). Minimum sprint depth = 4 tasks after Wave 1 setup. Wave 2 PRs (G, H, I) add 1–2 more layers but are largely doc/config and can overlap with Wave 1 late-stage review.

### Parallel work streams

| Stream | PR(s) | Tasks | Can start after | Agent assignment |
|---|---|---|---|---|
| A — Cost accounting | PR-A | S15-01 → S15-02, S15-03, S15-04 | v0.14.0 | Agent 1 |
| B — LLM settings | PR-B | S15-05 → S15-06, S15-07, S15-08 | v0.14.0 | Agent 2 |
| C — Run status | PR-C | S15-09 → S15-10 → S15-11 | v0.14.0 | Agent 3 |
| D — Resume parity | PR-D | S15-12 → S15-13, S15-14, S15-15 | v0.14.0 | Agent 4 |
| E — Top-N | PR-E | S15-16 → S15-17 → S15-18 → S15-19 | v0.14.0 | Agent 5 |
| F — Shim cleanup | PR-F | S15-20 → S15-21 → S15-22 | v0.14.0 | Agent 1 or 6 (first, before A) |
| G — Config/ensemble | PR-G | S15-23, S15-24, S15-25 | Wave 1 merged | Agent 2 |
| H — UX polish | PR-H | S15-26, S15-27, S15-28, S15-29 | Wave 1 merged | Agent 3 |
| I — Doc debt | PR-I | S15-30 (after S15-14), S15-31, S15-32, S15-33 | Wave 1 merged (S15-30 after PR-D) | Agent 4 |

Peak parallelism: 6 agents in Wave 1 (streams A through F). Wave 2: 3 agents (G, H, I).

### Conflict risks

- **`infra/backends/shinka.py`**: PR-A, PR-B, PR-D, PR-E, and PR-G all extend this file. **Wave 1 must merge these in sequence** (not developed against the same branch simultaneously): recommended order within Wave 1 is PR-F → PR-A → PR-B → PR-D → PR-E. Each PR must be rebased on the previous before merging. PR-G (Wave 2) goes after all Wave 1 Shinka edits are merged.
- **`core/run.py`**: PR-C (post-run path) and PR-D (resume path) both touch this file in disjoint functions. Can be developed in parallel as long as each PR is rebased before merge. No semantic conflict expected.
- **`cli/run.py`**: PR-H only (Wave 2). No Wave 1 conflict.
- **`infra/openevolve.py`** (shim): PR-F deletes it. No other PR should import it. If any Wave 1 PR adds a new import to it — flag as a conflict and resolve before PR-F merges.
- **`core/solution.py`** + **`cli/solution.py`**: PR-E only. No conflict.
- **Doc files**: PR-D touches spec-run.md and DES-005 (resume section only); PR-I does the full DES-005 rewrite. PR-I must start from PR-D's version. **Recommended**: PR-D adds the single resume-semantics paragraph; PR-I merges on top for the full rewrite.

**Recommended merge order**: PR-F → (PR-A, PR-B, PR-C, PR-D, PR-E in sequence, each rebased) → (PR-G, PR-H, PR-I in parallel).

---

## Exit Criteria

The sprint is complete when ALL of the following hold:

1. **Cost accuracy**: on a Gemini thinking-model run (or a fixture approximating one), the cost reported by `revolver run info` is within **10% of the provider bill** (cross-validated by summing `api_costs` + attempt/failure costs from the filesystem). At minimum: the attempt-dir sweep and thinking-token capture are implemented and covered by L2 contract tests.

2. **Unproductive run detected**: a Shinka run where 0 successful child programs are produced (only the init seed in `programs.sqlite`) is recorded as `status: completed_with_errors`; `run info` displays a visible warning. L2 test `test_shinka_unproductive_run` passes.

3. **Resume creates an independent artifact tree**: `revolver run resume` on a Shinka parent copies `programs.sqlite` + `gen_*` dirs into the child run's `shinka-output/`; mutating the child's DB does not affect the parent's. L2 test `test_shinka_resume_clone` passes.

4. **Thinking-model runs complete**: `max_tokens >= 16384` default and `max_patch_attempts=10` default prevent the empty-content failure mode; `reasoning_efforts` is configurable as a cost lever. L2 config-projection tests (S15-08) pass.

5. **Top-N works on Shinka**: `revolver solution extract --rank 3` on a Shinka run writes `programs/rank-1.py`, `rank-2.py`, `rank-3.py`; `solution list` shows all three; `--rank 2` on an OE run exits with a capability error. L2 tests S15-19 pass.

6. **`infra/openevolve.py` shim gone**: the file does not exist; `ruff` and `mypy` clean; all 1248+ tests pass.

7. **`PYTHONUNBUFFERED` restored**: after any `launch()` call, the env var is in its pre-call state (L1 unit test covers both backends).

8. **Ensemble→bandit mapping works**: a run with a weighted ensemble on `--backend shinka` completes without error, uses `llm_dynamic_selection="ucb"`, and emits a warning about dropped weights. L2 test S15-24 passes.

9. **Full regression green**: the full existing suite (1248+ tests) passes without modification on a no-shinka env; all Shinka L2 tests pass on a shinka-installed env; CI green.

10. **Doc cascade complete**: DES-005 rewrites to backend-neutral design; val-e2e-tests.md Scenario 3 = Passing; spec-run.md has resume semantics pinned; spec-project.md + DES-003 document `--backend`; FR-RUN-042 gap and FR-RUN-036..039 traceability rows closed. Run spec-reviewer agent after doc PRs merge; 0 FAIL expected.

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / Y integration tests passing (target: 1248 + ~16 new S15 L2 scenarios = ~1264+ on no-shinka env; all Shinka L2 tests on shinka env)

### Demo-able features
- [ ] Cost reported within 10% of provider bill on a thinking-model Shinka run
- [ ] Unproductive run shows `status: completed_with_errors` + visible warning in `run info`
- [ ] `run resume` on a Shinka parent creates an independent artifact tree
- [ ] `revolver solution extract --rank 3` materializes 3 programs from a Shinka run
- [ ] `revolver run --help` and `run population --help` are backend-neutral in wording
- [ ] `infra/openevolve.py` shim deleted; imports clean
- [ ] DES-005 rewritten as backend-neutral doc; spec-reviewer reports 0 FAIL

### Carry-over
_To be filled at sprint end._
