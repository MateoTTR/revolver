# Sprint 016 — Technical Debt Paydown + CLI/UX Polish

**Status**: Planning
**Goal**: Pay down the technical debt accumulated since Sprint 013 (inert pricing machinery, accumulated CLI/UX inconsistencies, doc gap on the backend abstraction) and ship the polished quality-of-life improvements surfaced by the demo sessions. No flagship feature — those ship in Sprint 017.
**Demo**: `revolver llm add` no longer accepts `--input-cost`/`--output-cost` flags; `revolver run info` shows a correct `programs_stored` count matching the DB; `revolver problem version create v1.0` works without `--tag`; a `--source local` Shinka run auto-limits to `max_proposal_jobs=1`; the CI tag-push gate catches a mismatched version before a bad release ships.
**Source**: Backlog carry-over from sprint-015.md §Carry-over → Sprint 016: #300 (pricing removal + migration), #308 (doc note), #303, #304, #305, #306, #309; plus backlog #110 (CI version guard) and the S14-13 resume-clone-parity carry-over.
**Predecessor**: Sprint 015 (v0.15.0, ShinkaEvolve P3 — token honesty + bridge robustness).

---

## Scope

### In scope

| Scope | Backlog ref | Content |
|---|---|---|
| **TD-1 — Pricing removal + DB migration v10** | #300 (final layer) | Remove `estimate_cost()` from `infra/token_proxy.py`, `--input-cost`/`--output-cost` CLI flags from `cli/llm.py`, `input_cost_per_mtok`/`output_cost_per_mtok` params from `core/llm.py` `add_llm()`/`update_llm()`, corresponding columns from `infra/db.py` schema + SELECT/INSERT/update_llm helpers, and the inert `LLMEntry` Pydantic fields. Requires a **DB migration v10** on the global DB (drop columns from `llms` table via recreate pattern; existing data preserved sans cost columns). Update all tests that reference the removed fields. |
| **TD-2 — CI version/tag guard** | #110 | Add a new CI job (`version-check`) triggered on `v*` tag pushes: reads `pyproject.toml` version and `src/revolver/__init__.py __version__`, compares both to the pushed tag, fails if they diverge. Small pure-bash job in `.github/workflows/`. |
| **TD-3 — Resume clone parity (spike-gated)** | S14-13 carry-over | **SPIKE-FIRST**: investigate whether `ShinkaEvolveRunner` truly supports resuming from a pre-populated `results_dir` (cloned copy, not the live parent dir). The spike outcome gates all implementation tasks in this scope. If the spike shows clone-resume is feasible, implement `resume_precheck` hook on `EvolutionBackend` + `ShinkaBackend` clone logic. If not feasible, write a documented limitation comment instead — the implementation tasks become N/A. |
| **TD-4 — DES-005 §4 full rewrite** | doc debt (FR-RUN-036..039, FR-RUN-042) | Replace DES-005 §4 (and its "OpenEvolve-specific" framing) with a full rewrite reflecting the `EvolutionBackend` abstraction (both OE and Shinka), clearing the FR-RUN-036..039/FR-RUN-042 doc debt. Run spec-reviewer + validation-reviewer after. |
| **UX-1 — #303 Neutralize OE-specific wording** | #303 | Change `run_app` help in `cli/__init__.py` from "Solution generation via OpenEvolve" to "Solution generation via the configured evolution backend." Change `run_population` docstring in `cli/run.py` from "Display the MAP-Elites population of a run" to "Display the program population of a run." |
| **UX-2 — #304 Positional tag on `problem version create`** | #304 | Accept `TAG` as a positional argument on `problem_version_create` while keeping `--tag` as a backward-compat alias. The positional takes priority; if both are supplied the positional wins (or raise a clear error). |
| **UX-3 — #305 Dataset split dual-use** | #305 | **Design decision**: the current `Literal["train", "eval"]` model is over-constrained for single-dataset demos. Add `"both"` as a valid split value (DB CHECK constraint, `core/dataset.py` validator, `models/dataset.py` `Literal`). On `revolver run`, a `split="both"` dataset is treated as `train`-eligible without a warning. Existing `split=None` (unspecified) behaviour is unchanged. Requires a DB migration **on the project DB** (extend the `datasets.split` CHECK) → **migration v11**, distinct from TD-1's v10 (which targets the global `llms` table). The two migrations target different databases but share the `MIGRATIONS` version counter, so v11 must be numbered after v10 lands. |
| **UX-4 — #306 `run info` programs_stored / rank-1 score** | #306 | Investigate why `programs_stored` in `run info` showed 3 while the DB held 11 (2 init + 9 children). `programs_stored = len(programs)` in `core/run.py` is set at launch time from `collect_results()` / Shinka's `_materialize_best_programs()`; the displayed figure comes from `RunResult.programs_stored`, not from a DB count. Reconcile: either show the total DB program count on `run info` (reading from `programs.sqlite` or the OE checkpoint), or surface both "extracted" and "stored" counts. Also fix `score = -` for the rank-1 solution on `run info`: the `best_score` column in `solutions` is populated by post-run eval; if eval was skipped/failed the score is `None` → show the score from the run's `best_score` (DB column populated in `update_run()`) as a fallback. |
| **UX-5 — #309 Local-endpoint concurrency lever (Shinka)** | #309 | In `ShinkaBackend.build_config()`, when `spec.llm_entry.source == "local"` and `max_proposal_jobs` is not already set in `spec.config_overrides`, inject `job_config.max_proposal_jobs = 1`. Add a note to `docs/guides/tuning-oe-config.md` "Subscription-backed and single-GPU local endpoints" advising `--parallel 1` (OE path) and noting the Shinka auto-pin behaviour. |
| **UX-6 — #308 Doc note: Max-subscription spend** | #308 | One-line note in `docs/guides/tuning-oe-config.md` (or the relevant section): "Spend on Claude Max subscription is tracked on the Anthropic console, not by Revolver — Revolver does not capture the `total_cost_usd` field returned by the bridge." |

### Explicitly out of scope (deferred to Sprint 017)

| Deferred item | Why deferred |
|---|---|
| Top-N extraction (#299) | Largest task chain; gates on `capabilities().top_n_extraction`; fits a dedicated sprint. |
| `--config-override` validation + ensemble→bandit + multi-language passthrough | Should-do completeness, not demo-blocking. |
| Any new evolution feature | This sprint is debt + polish only. |

---

## Prioritization

| Priority | Scopes | Rationale |
|---|---|---|
| **Must-do (correctness / legal debt)** | TD-1 | `estimate_cost()` is deprecated since 0.15.0 with an explicit "removal → S16" docstring. The inert pricing flags (`--input-cost`/`--output-cost`) are user-visible dead code. The DB columns occupy schema space and bloat `LLMEntry`. |
| **Must-do (release process guard)** | TD-2 | The CI version check prevents the recurring "tagged the wrong version" class of error. Low implementation cost, high protection value. |
| **Spike-gated (engine semantics unclear)** | TD-3 | The clone-resume design assumption (S14-13 docstring) was never validated end-to-end against shinka 0.0.7. The spike answers it before any code is written. |
| **Should-do (doc integrity)** | TD-4 | DES-005 still refers to "OpenEvolve" in §4 headers post-ADR-007. The FR-RUN-036..039/FR-RUN-042 doc debt should be cleared before S017 adds more features on top. |
| **Should-do (UX polish)** | UX-1, UX-2, UX-3, UX-4, UX-5 | Demo-surfaced annoyances; each is a small, bounded change. UX-4 (programs_stored) is arguably a display bug. |
| **Nice-to-have (1 line)** | UX-6 | Single sentence in a guide; zero risk. |

---

## Tasks

### Scope TD-1 — Pricing removal + DB migration v10

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S16-01 | **Remove `estimate_cost()` from `infra/token_proxy.py`**: delete the function and its deprecation docstring. Update the module docstring if it mentions cost estimation. | infra | PR-TD1 | — | Function absent from file; `grep -r "estimate_cost" src/` returns empty; `ruff`/`mypy` clean |
| S16-02 | **Remove pricing fields from `models/llm.py` `LLMEntry`**: drop `input_cost_per_mtok: float \| None` and `output_cost_per_mtok: float \| None` from the Pydantic model. Remove them from `model_fields` documentation if present. | models | PR-TD1 | S16-01 | `LLMEntry` has no pricing fields; `mypy` clean on all callers |
| S16-03 | **Remove pricing params from `core/llm.py` `add_llm()` and `update_llm()`**: drop the `input_cost_per_mtok` / `output_cost_per_mtok` keyword arguments (~L129, ~L261), their docstring entries, and the pass-through to `db.insert_llm()` / `db.update_llm()`. | domain | PR-TD1 | S16-02 | Functions have no pricing params; `mypy` clean |
| S16-04 | **Remove pricing params from `infra/db.py`**: (a) `_LLM_COLUMNS` string — remove the two cost columns; (b) `_row_to_llm_entry()` — update column indices; (c) `insert_llm()` — drop cost columns from INSERT; (d) `update_llm()` — drop cost kwargs; (e) schema `_GLOBAL_SCHEMA_SQL` — remove `input_cost_per_mtok REAL` / `output_cost_per_mtok REAL` from the `llms` CREATE TABLE. | infra | PR-TD1 | S16-02 | All DB helpers compile and are `mypy`-clean; no cost column in fresh schema |
| S16-05 | **DB migration v10**: add entry `10: <SQL>` to `MIGRATIONS` dict in `infra/db.py`. Migration targets the **global DB** only (cost columns are on `llms`, a global-DB table). Use the SQLite column-drop-via-recreate pattern (same as migration v2). Backfill strategy: no data to preserve (the columns were inert — always `NULL`). Update `CURRENT_SCHEMA_VERSION = 10`. | infra | PR-TD1 | S16-04 | `CURRENT_SCHEMA_VERSION == 10`; re-opening a v9 global DB applies the migration cleanly; fresh DB has no cost columns; test mirrors `test_db_migration_v9.py` structure |
| S16-06 | **Remove pricing CLI flags from `cli/llm.py`**: drop `--input-cost` and `--output-cost` from `llm_add` and `llm_update` Typer commands; remove the args passed to `core.llm.add_llm()` / `core.llm.update_llm()`. | cli | PR-TD1 | S16-03 | `revolver llm add --help` shows no pricing flags; `revolver llm update --help` shows no pricing flags; `ruff`/`mypy` clean |
| S16-07 | **Update all tests**: fix / delete test cases that set `input_cost_per_mtok` or `output_cost_per_mtok`, assert on `LLMEntry.input_cost_per_mtok`, or call `estimate_cost()`. | test | PR-TD1 | S16-01..06 | Full test suite passes on no-shinka env (1271+ tests); `grep -r "cost_per_mtok\|estimate_cost" tests/` returns empty |

### Scope TD-2 — CI version/tag consistency guard

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S16-08 | **Add `version-check` CI job to `.github/workflows/ci.yml`**: triggered only on `push` to refs matching `v*`. The job: checks out the repo at the pushed commit, extracts `version` from `pyproject.toml` (using `grep` + `sed`), extracts `__version__` from `src/revolver/__init__.py`, extracts the tag from `GITHUB_REF`, compares all three. If any diverge → `exit 1` with a descriptive message. No conda env needed (pure bash + Python stdlib). | ci | PR-TD2 | — | Pushing a tag `v0.16.0` on a commit where `pyproject.toml` version = `0.16.0` and `__version__ = "0.16.0"` → job passes. If any field differs → job fails with message. Manually verified with a simulated mismatch. |

### Scope TD-3 — Resume clone parity (spike-gated)

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S16-09 | **SPIKE: validate ShinkaEvolveRunner resume semantics** — in the `revolver-demos` conda env (shinka 0.0.7), run a minimal ShinkaEvolve experiment to completion, then: (a) copy the resulting `shinka-output/` directory to a new path, (b) construct a `ShinkaEvolveRunner` pointing at the **copy** with `num_generations` extended, (c) observe whether it continues or restarts from generation 0. Record the answer (feasible / not feasible) and any required preconditions (e.g. `last_iteration` field must exist, paths must be absolute). Output: a spike-note comment in this sprint file (§Spike Result) and a go/no-go decision for S16-10..12. | infra (investigation) | — | — | Spike note written in §Spike Result below; go/no-go decision recorded; no code committed unless the spike is pure test scaffolding |
| S16-10 | **[CONDITIONAL on spike GO] Add `resume_precheck` to `EvolutionBackend` protocol**: add an optional `resume_precheck(parent_run_dir: Path) -> None` method to `infra/backends/base.py` with a default no-op implementation. The orchestrator (`core/run.py resume_run()`) calls it before the run-record insert (fail-fast, consistent with the existing `RevolverError` pattern). | infra | PR-TD3 | S16-09 (GO) | `EvolutionBackend` has `resume_precheck`; `OpenEvolveBackend` no-ops; `ShinkaBackend` raises if preconditions fail; `mypy` clean |
| S16-11 | **[CONDITIONAL on spike GO] `ShinkaBackend.resume()` clone logic**: before calling `_run_engine`, copy the parent `shinka-output/` to the new run's `shinka-output/` (clone the `programs.sqlite` + `gen_*/` dirs). Extend `num_generations` against the clone's `last_iteration`. The parent run's output dir is no longer mutated in place. | infra | PR-TD3 | S16-10 | A resumed Shinka run no longer mutates the parent `shinka-output/`; `run population` on the parent shows only its own generations; the resumed run's DB contains the cloned programs plus the new generations |
| S16-12 | **[CONDITIONAL on spike GO] L2 test: resume clone isolation** — parametrized test: run A (mocked, 5 iterations) → clone → run B (5 more) → assert parent DB unchanged after B. | test | PR-TD3 | S16-11 | Test passes on shinka env; auto-skip without shinka |
| S16-13 | **[FALLBACK if spike NO-GO] Document clone-resume limitation**: update the `ShinkaBackend.resume()` docstring to replace the "clone-based parity → Sprint 015" note with a permanent "clone-resume not supported by shinka 0.0.7 — cumulative accounting is intentional; see §Known Limitations" note. Update `docs/architecture/design/DES-005-run-orchestration.md` §14.1 accordingly. | doc | — | S16-09 (NO-GO) | Docstring and DES-005 §14.1 accurately describe the behaviour; no "TODO" or "deferred" notes remain |

### Scope TD-4 — DES-005 §4 full rewrite

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S16-14 | **Rewrite DES-005 §4 to reflect the backend abstraction**: rename §4 from "OpenEvolve Integration" to "Backend Integration"; describe the `EvolutionBackend` protocol (config/wrapper/launch/resume/token tiers), document how `OpenEvolveBackend` and `ShinkaBackend` implement each tier, include the `token_proxy` DD-14 note as an OE-specific sub-section. Cross-reference FR-RUN-036..039 and FR-RUN-042; mark them as "Covered" in the doc. Version bump to `0.7.0` in the doc header. | doc | PR-TD4 | — | `grep "FR-RUN-036\|FR-RUN-037\|FR-RUN-038\|FR-RUN-039\|FR-RUN-042" docs/architecture/design/DES-005-run-orchestration.md` returns coverage entries; no "OpenEvolve-specific" framing in §4 heading or §4 intro |
| S16-15 | **Run spec-reviewer and validation-reviewer** after S16-14 is committed. Address all FAIL findings; address WARNINGs at discretion (sprint scope). Commit fixes. | doc | PR-TD4 | S16-14 | spec-reviewer: 0 FAIL on touched docs; validation-reviewer: 0 FAIL on touched docs |

### Scope UX-1 — #303 Neutralize OE-specific wording

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S16-16 | **`cli/__init__.py`**: change `run_app` help string from `"Solution generation via OpenEvolve."` to `"Solution generation via the configured evolution backend."`. **`cli/run.py`**: change `run_population` docstring from `"Display the MAP-Elites population of a run."` to `"Display the program population of a run."` | cli | PR-UX | — | `revolver run --help` shows backend-neutral wording; `revolver run population --help` shows neutral docstring; `ruff` clean |

### Scope UX-2 — #304 Positional tag on `problem version create`

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S16-17 | **`cli/problem.py` `problem_version_create`**: make `tag` accept both a positional `Argument` and a `--tag` `Option`. Typer does not natively support "optional positional with fallback to option"; implement as: (1) add `tag_positional: str \| None = typer.Argument(None, help="Version tag (e.g. v1.0).")`, (2) keep `tag_option: str \| None = typer.Option(None, "--tag", help="Version tag (e.g. v1.0). Deprecated: prefer positional.")`, (3) resolve with `tag = tag_positional or tag_option` and raise `ValidationError` if both are `None`. | cli | PR-UX | — | `revolver problem version create v1.0` works; `revolver problem version create --tag v1.0` still works; `revolver problem version create` (no tag) raises a clear error; L2 regression test covers both invocations |

### Scope UX-3 — #305 Dataset split dual-use

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S16-18 | **Design decision (recorded here)**: add `"both"` as a third valid split value meaning "usable for training and evaluation". Datasets with `split="both"` are treated as train-eligible by `core/run.py` (no warning) and eval-eligible by `core/eval.py` (no warning). `split=None` continues to mean "unspecified". Implementation: update `models/dataset.py` `Literal["train", "eval"] \| None` → `Literal["train", "eval", "both"] \| None`; update `core/dataset.py` validator; update `core/run.py` train-dataset filter and split warning; add **migration v11** extending the `datasets.split` CHECK (project-DB table, via the recreate pattern) and bump `CURRENT_SCHEMA_VERSION = 11`. This is a *separate* migration from TD-1's v10 (different DB), numbered after it. | models/domain/infra | PR-UX | S16-05 (migration v10 must land first so v11 follows in sequence) | `revolver dataset add --split both` succeeds; `revolver run --dataset <both-dataset>` triggers no split warning; `core/run.py` smart-default picks a `split="both"` dataset when no `split="train"` dataset exists; L2 test covers the no-warning path |

### Scope UX-4 — #306 `run info` programs_stored / rank-1 score

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S16-19 | **Investigate and fix `programs_stored` count on `run info`**: `RunResult.programs_stored` is set at launch time as `len(programs)` where `programs` is the list returned by `backend.collect_results()` / Shinka's `_materialize_best_programs()`. On OE this collects only the top-ranked files in `programs/`; on Shinka it returns only the best files. The discrepancy with "DB held 11" comes from `programs.sqlite` containing ALL attempted programs (init + all children). The fix: display the backend-native "stored count" (all programs in `programs.sqlite` on Shinka, all checkpoint entries on OE) as `total_programs_in_db`, and keep `programs_stored` (extracted to `programs/` dir) as a separate field. Add a `RunInfo.total_programs` field (populated by reading `programs.sqlite` count on Shinka via `backend.count_valid()` or equivalent full-count method; leave as `None` on OE where this requires checkpoint parsing). | domain/cli | PR-UX | — | `run info` on a Shinka run shows both `programs_extracted` (files in `programs/`) and `programs_in_db` (total rows in `programs.sqlite`); they agree when all programs are extracted; L2 test covers both fields |
| S16-20 | **Fix `score = -` for rank-1 solution in `run info`**: when `solution.best_score` is `None` (post-run eval was skipped or failed), fall back to the run's `best_score` DB column (already stored by `update_run_best_score()` or equivalent during result collection). Surface it in `run info` solution table with an asterisk or "(from run)" note. | cli | PR-UX | — | `run info` shows a numeric score for rank-1 solution even when post-run eval was skipped; the source indicator (direct eval vs run best_score) is visible; L2 test exercises the fallback path |

### Scope UX-5 — #309 Local-endpoint concurrency lever (Shinka)

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S16-21 | **`ShinkaBackend.build_config()`**: when `spec.llm_entry` is not `None` and `spec.llm_entry.source == "local"`, and `max_proposal_jobs` is not already set in `spec.config_overrides`, inject `job_config.max_proposal_jobs = 1` into the built config. This prevents Shinka from fanning out 6 parallel proposal jobs to a serialized subscription endpoint. Add a dry-run note showing the injected value. | infra | PR-UX | — | A Shinka dry-run with `--source local` LLM shows `max_proposal_jobs: 1` in `backend_extras`; a `--config-override job_config.max_proposal_jobs=3` overrides the default; `ruff`/`mypy` clean; L2 test |
| S16-22 | **Guide note**: add a "Subscription-backed and single-GPU local endpoints" sub-section to `docs/guides/tuning-oe-config.md` documenting: (a) OE path — use `--parallel 1` or `llm update --timeout`; (b) Shinka path — `max_proposal_jobs` auto-pinned to 1 for `--source local`, configurable via `--config-override`; (c) the #308 doc note: "Anthropic Max subscription spend is tracked on the Anthropic console, not by Revolver." | doc | PR-UX | S16-21 | Section present in guide; references both backends; no typos; `ruff` (markdown lint if configured) clean |

---

## PR Breakdown and Waves

```
Wave 1 — independent groundwork (no shared-file conflicts across streams):
    PR-TD1   Pricing removal + DB migration v10    — infra/db.py, models/llm.py, core/llm.py,
                                                      cli/llm.py, infra/token_proxy.py, tests/
    PR-TD2   CI version/tag guard                  — .github/workflows/ci.yml only
    PR-TD4   DES-005 §4 rewrite                   — docs only (run reviewers after)

Wave 1b — spike (no code, blocks TD-3 implementation):
    SPIKE    TD-3 resume semantics investigation   — investigation only, no file changes

Wave 2 — after Wave 1 lands (conflict: PR-UX touches cli/run.py + infra/backends/shinka.py
         which TD-1 also touches — merge TD-1 first, rebase UX branch):
    PR-UX    All UX scopes (UX-1..6)              — cli/__init__.py, cli/run.py, cli/problem.py,
                                                      cli/dataset.py, models/dataset.py,
                                                      core/dataset.py, core/run.py,
                                                      infra/backends/shinka.py,
                                                      docs/guides/tuning-oe-config.md
             UX-3 (#305 split="both") depends on S16-05 (migration v10) landing in PR-TD1.
             Merge PR-TD1 first, rebase PR-UX on top.

Wave 3 — after spike resolves:
    PR-TD3   Resume clone parity (GO path)         — infra/backends/base.py,
                                                      infra/backends/shinka.py, core/run.py,
                                                      tests/integration/
          OR
    (no PR)  TD-3 NO-GO fallback                  — docstring + DES-005 §14.1 update
             (fold into PR-UX doc section or PR-TD4 if still open)
```

**Conflict management**:

- `infra/db.py`: touched by PR-TD1 (columns removal + migration v10) and potentially PR-TD3 (no schema change, but imports `CURRENT_SCHEMA_VERSION`). Merge PR-TD1 first; rebase PR-TD3 after.
- `infra/backends/shinka.py`: touched by PR-TD1 indirectly (if `ShinkaBackend.collect_token_usage` referenced pricing fields — verify before branching) and PR-UX (UX-5, `build_config`) and PR-TD3 (resume clone). Recommended merge order: PR-TD1 → PR-UX → PR-TD3, each rebased.
- `core/llm.py`: touched only by PR-TD1 (pricing param removal). No other PR should touch this file.
- `cli/run.py`: touched by PR-UX (UX-1 docstring, UX-4 `programs_stored` display). No conflict with TD-1 (which only touches `cli/llm.py`).
- `models/dataset.py` + `core/run.py` + `infra/db.py`: UX-3 (`split="both"`) touches all three. The DB part is a **new migration v11** on the project `datasets` table — distinct from TD-1's v10 (global `llms`), but sharing the `MIGRATIONS`/`CURRENT_SCHEMA_VERSION` counter. PR-UX must therefore land **after** PR-TD1 so v11 follows v10 in sequence (rebase PR-UX on TD-1).

**Recommended merge order**: PR-TD2 (CI, no conflicts) → PR-TD4 (docs, no conflicts) → PR-TD1 (DB migration + code removal) → PR-UX (rebased on TD1) → PR-TD3 (rebased on UX, conditional on spike GO).

---

## Spike Result

**Executed** (S16-09, session 053). Shinka is **not installed on this machine**, so the spike was answered against the **upstream engine source** (`SakanaAI/ShinkaEvolve`, tag **`v0.0.7`**, commit `c4568ad`) rather than empirically.

**Question**: Does `ShinkaEvolveRunner` (shinka 0.0.7) continue from a pre-populated `results_dir` (a fresh copy of a prior run's `shinka-output/`) when `num_generations` is set higher than the cloned `last_iteration`?

**Answer**: ✅ **GO — Feasible. Implementation tasks S16-10..12 proceed; the S16-13 fallback is dropped.**

The engine continues from a pre-populated, **path-independent** `results_dir`. Evidence (upstream source):

- **CONTINUE, not restart** — `shinka/core/async_runner.py:1133-1178`: `db_path` is derived from `results_dir` at runtime (`db_path = Path(f"{self.results_dir}/programs.sqlite")`), then `resuming_run = db_path.exists() and self.db.last_iteration > 0`; the initial-program seeding runs only in the `else` (non-resume) branch. `shinka/database/dbase.py:478-627` opens the DB (`CREATE TABLE IF NOT EXISTS`, never `DROP`/truncate) and reads `last_iteration` back from `metadata_store`.
- **`num_generations` is a TOTAL target** — `async_runner.py:4924-4940` restores `completed_generations`/`next_generation_to_submit = last_iteration + 1`; every stop/cap condition (`:2166`, `:2485`) compares the absolute counter to `num_generations`. This **validates Revolver's existing** `num_generations = last_iteration + spec.iterations`.
- **Path-independent / clone-safe** — the resolved absolute path is never written into the DB; `programs` rows hold code/scores/metadata only, `gen_*/` dirs are built relative to `results_dir`. A `shutil.copytree` of a cleanly-stopped run resumes correctly at a new path.

**Preconditions** (for S16-11 clone logic): clone the *entire* `results_dir` (programs.sqlite + any `-wal`/`-shm` + all `gen_*/`, plus `bandit_state.pkl` / `prompts.sqlite` if present); repoint `evo_config.results_dir` at the clone; keep `num_generations = last_iteration + additional`; clone only a **cleanly-stopped** run (consistent SQLite file); same engine schema (0.0.7 ↔ 0.0.7). Add a 2-gen → copytree → resume-2-more → assert-4-total smoke test (S16-12) to lock the guarantee.

---

## Integration Tests (L2)

| Area | Scenario | Test ID | Status |
|---|---|---|---|
| DB migration v10 | Fresh global DB lands at schema v10 (no cost columns) | `test_db_migration_v10_fresh_global` | Planned |
| DB migration v10 | v9 global DB upgrades to v10; existing LLM rows preserved | `test_db_migration_v10_from_v9` | Planned |
| DB migration v10 | v9 project DB upgrades to v10 (version bump only, no llms table) | `test_db_migration_v10_project_db` | Planned |
| DB migration v11 | v10 project DB upgrades to v11; `datasets.split` CHECK now accepts `both`; existing rows preserved | `test_db_migration_v11_datasets_split` | Planned |
| LLM registration (no pricing) | `llm add` succeeds without `--input-cost`/`--output-cost` | `test_llm_add_no_pricing_flags` | Planned |
| LLM registration (no pricing) | `LLMEntry` has no pricing fields; round-trip insert/get clean | `test_llm_entry_no_pricing_fields` | Planned |
| CI guard | Version check script: matching tag passes | `test_version_check_match` (manual / shell) | Planned |
| CI guard | Version check script: mismatched tag fails with message | `test_version_check_mismatch` (manual / shell) | Planned |
| `problem version create` (positional) | `revolver problem version create v1.0` works (no `--tag`) | `test_problem_version_create_positional` | Planned |
| `problem version create` (option compat) | `revolver problem version create --tag v1.0` still works | `test_problem_version_create_option` | Planned |
| Dataset split `both` | `dataset add --split both` accepted; no warning on `run` | `test_dataset_split_both_no_run_warning` | Planned |
| `run info` programs_stored | `programs_extracted` vs `programs_in_db` both shown correctly | `test_run_info_programs_count_split` | Planned |
| `run info` rank-1 score | Score falls back to run `best_score` when eval was skipped | `test_run_info_rank1_score_fallback` | Planned |
| Shinka local concurrency | `build_config()` injects `max_proposal_jobs=1` for `--source local` | `test_shinka_local_max_proposal_jobs_pin` | Planned |
| Shinka local concurrency | `--config-override job_config.max_proposal_jobs=3` overrides auto-pin | `test_shinka_local_max_proposal_jobs_override` | Planned |
| CLI wording | `run population --help` shows neutral docstring (no MAP-Elites) | `test_run_population_help_neutral` | Planned |
| Resume clone (if spike GO) | Resumed Shinka run does not mutate parent `programs.sqlite` | `test_shinka_resume_clone_isolation` | Planned (conditional) |
| Full regression (no-shinka env) | Existing 1271+ tests pass after pricing removal | regression | Planned |
| Full regression (shinka env) | All Shinka L2 tests pass with shinka 0.0.7 | shinka regression | Planned |

---

## Exit Criteria

The sprint is complete when ALL hold:

1. **Pricing dead code gone**: `estimate_cost()` does not exist in `infra/token_proxy.py`; `LLMEntry` has no `input_cost_per_mtok`/`output_cost_per_mtok` fields; `cli/llm.py` shows no `--input-cost`/`--output-cost` options in `--help`; `grep -r "cost_per_mtok\|estimate_cost" src/` returns empty. DB migrations v10 (global `llms`) and v11 (project `datasets.split`) apply cleanly on both fresh and upgraded databases. L2 migration tests pass.
2. **CI version guard active**: the `version-check` job exists in `ci.yml`; it triggers on `v*` tags; a simulated mismatch produces a non-zero exit; the job does not block normal `push`/PR CI runs.
3. **Resume clone parity resolved**: either S16-10..12 are implemented and tested (GO path), or S16-13 documentation accurately describes the limitation (NO-GO path). No "TODO sprint-015" or "TODO sprint-016" notes remain in `ShinkaBackend.resume()` docstring or DES-005.
4. **DES-005 §4 reflects backend abstraction**: section heading is backend-neutral; FR-RUN-036..039 and FR-RUN-042 are referenced and marked covered; spec-reviewer and validation-reviewer each report 0 FAIL on touched docs.
5. **CLI polish landed**: `revolver run --help` shows backend-neutral wording; `revolver run population --help` shows neutral docstring; `revolver problem version create v1.0` works without `--tag`; `--split both` accepted on `dataset add`; Shinka dry-run with `--source local` shows `max_proposal_jobs: 1`.
6. **`run info` display correct**: `programs_extracted` and `programs_in_db` match reality; rank-1 score falls back to run `best_score` when post-run eval is absent.
7. **Full regression green**: existing 1271+ tests pass on no-shinka env; all Shinka L2 tests pass on the shinka (`revolver-demos`) env; CI green (Lint + Test 3.12/3.14).

---

## Parallelization

### Dependency graph

```
S16-08 (CI guard)                   ── no deps ──> PR-TD2 (Wave 1, standalone)

S16-14 (DES-005 §4 rewrite)
    └──> S16-15 (spec/val reviewers) ── PR-TD4 (Wave 1, docs-only)

S16-09 (SPIKE: resume semantics)    ── no deps, investigation only
    └──> S16-10..12 (clone impl, GO) ──> PR-TD3 (Wave 3)
         OR S16-13 (doc fallback)

S16-01 (remove estimate_cost)
    └──> S16-02 (LLMEntry no pricing)
         └──> S16-03 (core/llm params)
              └──> S16-04 (infra/db columns)
                   └──> S16-05 (migration v10 + CURRENT_SCHEMA_VERSION=10)
                        └──> S16-06 (cli/llm flags)
                             └──> S16-07 (tests)   ──> PR-TD1 (Wave 1)
                                  │
                                  └─── S16-18 (UX-3 split="both") can start
                                       after S16-05 migration is merged

After PR-TD1 merged:
    S16-16 (UX-1 wording)          ──┐
    S16-17 (UX-2 positional tag)   ──┤
    S16-18 (UX-3 split both)       ──┤──> PR-UX (Wave 2, parallel within PR)
    S16-19 (UX-4 programs_stored)  ──┤
    S16-20 (UX-4 rank-1 score)     ──┤
    S16-21 (UX-5 Shinka concurrency)──┤
    S16-22 (UX-6 guide note)       ──┘
```

### Critical path

S16-01 → S16-02 → S16-03 → S16-04 → S16-05 → S16-06 → S16-07 (PR-TD1) → S16-18 → PR-UX merge

Estimated length: 8 sequential tasks in the TD-1 chain, then a parallel UX wave.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Pricing removal | S16-01..07 | — | Agent 1 |
| B — CI guard | S16-08 | — | Agent 2 |
| C — DES-005 rewrite | S16-14..15 | — | Agent 3 |
| D — Resume spike | S16-09 | — | Agent 1 or 2 (low effort) |
| E — UX polish | S16-16..22 | PR-TD1 merged | Agent 1 or new agent |
| F — Resume implementation | S16-10..12 or S16-13 | Spike result known | Agent per spike outcome |

### Conflict risks

- `infra/db.py`: **highest conflict risk** — TD-1 (S16-04/05) and UX-3 (S16-18, extend CHECK) both modify it. Sequence: TD-1 PR merged first; UX-3 rebased on top. Do NOT develop both in the same branch.
- `infra/backends/shinka.py`: TD-3 (S16-11, `resume()` clone logic) and UX-5 (S16-21, `build_config()`) both modify it. If both proceed simultaneously, assign to the same agent or coordinate a clear PR order (UX-5 first → TD-3 rebased).
- `core/run.py`: UX-4 (S16-19 `programs_stored` display path) and TD-3 (S16-10, `resume_precheck` call) both touch it. Order: merge UX first, rebase TD-3 after.
- `cli/__init__.py`: only UX-1 (S16-16, one line change). No other PR should touch this file.

---

## Sprint Review

_To be filled at sprint close._

### Tests passing
- X / Y integration tests passing

### Demo-able features
- [ ] `revolver llm add --help` shows no pricing flags
- [ ] `revolver problem version create v1.0` works without `--tag`
- [ ] `revolver run info` shows correct `programs_in_db` count
- [ ] Shinka dry-run with `--source local` shows `max_proposal_jobs: 1`
- [ ] CI tag-push job blocks on version mismatch

### Spike result
- [ ] Resume clone parity: GO (S16-10..12 implemented) / NO-GO (S16-13 documented)

### Carry-over
_To be filled at sprint close._
