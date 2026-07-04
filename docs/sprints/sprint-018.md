# Sprint 018 — Eval Honesty Semantic Slice + Top-N Flagship (v0.18.0)

**Status**: Planning
**Target release**: **v0.18.0** (normal sprint release — Release Checklist per CLAUDE.md; `develop` → `main`, tag `v0.18.0`)
**Goal**: Ship the **semantic** half of the v0.17 demos-feedback triage — make timeout handling and best-score reporting *honest* (U13 → U11, strict order, default flips to `penalize`), persist the backend on a problem version (U4), fail fast when a seed lacks a declared feature metric (U8), and give killed runs a mid-run checkpoint by default (U6 phase 2). Around that committed slice, deliver the long-deferred **top-N solution promotion** flagship (Shinka-native, OE consciously deferred), harden the `base.py` child reap against grandchildren/PID-reuse, timebox the `qwen15` mid-run deadlock spike, and pay down the silent-doc-rot debt (#354–356).
**Demo**: an overnight-style Shinka run reports an **engine best_score labeled "single eval"** next to an **honest post-eval mean labeled with coverage** (`instances_valid/instances_total`) — the inflated survivorship number no longer masquerades as the headline; a run whose hardest instances *time out* now **penalizes** them (fitness pressure) instead of silently dropping them (`--config-override evaluation.on_timeout=drop` restores 0.17 behavior). `revolver problem version create v2 --backend shinka` then `revolver run v2 --llm …` picks Shinka **from the version** (no `--backend`), warning on an explicit mismatch. A seed program missing a `database.feature_dimensions` metric fails at **pre-flight**, not 40 iterations in. `revolver solution extract --run <id> --rank 2` promotes the **2nd-best** program from a Shinka run's `programs.sqlite` (OE gives a clear "not supported" message). A killed ≤100-iteration run now has a **mid-run checkpoint** to resume from.
**Source**: [triage-feedback-v017.md](../analysis/triage-feedback-v017.md) — §1 (eval-cluster causal graph), §3 (v0.18 semantic slice, strict order U13→U11→U4→U8→U6p2→reap), §4 (S18+/upstream). Backlog #364, #367–371 (v0.18 semantic), #299 (top-N, deferred to S18 since S16), #320 (qwen15 spike), #354–357 (doc maintenance). Scope arbitrated by Mathieu (sessions 056/057).
**Predecessor**: Sprint 017 (v0.17.0 — multi-LLM ensemble validated end-to-end) + Sprint 017a (v0.17.1 — defensive eval-teardown hotfix). This is the **semantic** counterpart to 017a's **defensive** slice.

> **Do-not-regress list** (verified working through 0.17.1 — no task below breaks these): the 017a killable eval primitive (`REVOLVER_EVAL_NUM_THREADS`, `killpg` kill-on-timeout, `InstanceTestResult` byte-identical), M1/M3/M4 ensemble→bandit, B6 `REVOLVER_HOME`, PID-aware self-healing run lock, Shinka placeholder key. **U13's default flip is the one deliberate _fitness-landscape_ change this sprint** — it must be release-noted and reversible via `evaluation.on_timeout=drop`. It is **not** the only deliberate default-path change: U6 phase 2 (cadence default), U11 (post-eval persistence + timeout, dual-score display), U8 (pre-flight fail-fast), and U13 commit (ii) (new wrapper `instances_*` keys) also change the default path — see Exit Criterion 10 for the full enumeration. U13 is singled out as the only change to the *fitness landscape* a run explores.

---

## Source

- Triage: [triage-feedback-v017.md](../analysis/triage-feedback-v017.md) — §1 (U11–U14 corrected causal graph), §2 (what already shipped in 0.17.1), §3 (v0.18 strict-order slice), §4 (upstream U9 / U12 grandchildren note)
- Backlog: #364 (checkpoint cadence phase 2), #367 (U13), #368 (U11), #369 (U4, migration v14), #370 (U8), #371 (U9 upstream — OUT), #299 (top-N), #320 (qwen15 deadlock), #354–357 (doc maintenance)
- Prior sprints for pattern reference: [sprint-016.md](sprint-016.md) (DB-migration sequencing), [sprint-017.md](sprint-017.md) (spec-before-code cascade, PR waves, disjoint-file parallelism), [sprint-017a.md](sprint-017a.md) (eval-teardown context, base.py reap seam, one-column-per-migration discipline)
- ADR-007 §capabilities (`top_n_extraction`), DES-005 §7 teardown / §capabilities table (line 647), sprint-014 §Sprint Review (stale top-N narrative to reconcile)

---

## Scope

### In scope — Wave A (committed semantic slice, strict order: honest fitness → honest score)

| Item | Backlog | Content |
|---|---|---|
| **U13 — honest timeout semantics** (default flips to `penalize`) | 367 | **One PR, 3 strict-order commits.** (i) **display guard**: `openevolve.py` `parse_population` (:1124-1129) and `read_checkpoint_best_score` (:1196-1201) prefer numeric `combined_score` over the sum-of-numeric-metrics; update `tests/test_run_population.py` (:202 et al.). Note (recon): the live-run/solution-DB path already uses `combined_score` (`recover_best_from_checkpoint` :1268-1276, `_extract_best_score`); the sum leaks **only via display/fallback** — smaller blast radius than "core of the problem", but it must land first so (ii)'s coverage keys aren't summed into the displayed score. (ii) **coverage keys** `instances_valid`/`instances_total` + a **timeout side-channel** in **BOTH** wrapper templates — OE `_WRAPPER_TEMPLATE` (:1334-1461, distinct `TimeoutError` branch already exists :1404) **and** the Shinka `_WRAPPER_TEMPLATE` (:296-470, which today catches ALL exceptions in one branch — **add a distinct `TimeoutError` branch**, per triage §3, not in the backlog line); exclude `instances_*` from the mean-aggregation loops (OE :1428-1435, Shinka :394-403); reserve the `instances_` metric prefix. (iii) **`evaluation.on_timeout: penalize\|drop` + `timeout_score`** (finite, default `0.0`) parsed at the shared `core/run.py:869-873` point, new `BackendRunSpec` fields (`base.py`), threaded into both `generate_wrapper` timeout branches, value-validated (`penalize\|drop`, finite score — **net-new**, neither validator inspects `evaluation.*` today) — **default flips to `penalize`** (fitness-landscape change → **release note**; `drop` restores 0.17). Resume bakes the policy at create/launch (inherits parent wrapper, :1497-1502). |
| **U11 — honest best-score display** (after U13) | 368 | **After PR-1 merges** (consumes U13's coverage keys). **Commit A**: finish Task-86 residue — replace `_run_post_eval` (`core/run.py:1242-1306`, hardcoded `timeout_s=300`, stores nothing) with `core.eval.evaluate_solution` (`core/eval.py:287`, writes eval_metadata/eval_instances); rewire both call sites (`launch_run` :1083-1100, `resume_run` ~:1775), thread `config.dataset_name` (today only `dataset_path` reaches `_post_run_evaluation`), pass `force=True`/has-existing-eval check (evaluate_solution raises if an eval exists :370-377), keep warn-only, add the **DB-contention guard** (commit `proj_conn`/WAL/busy_timeout before the call — launch still holds the connection). **Commit B**: one display pass — `get_run_info`/`RunInfo` show engine best (labeled **"engine, single eval"**) next to the post-eval **mean + U13 coverage**; `cli/run.py:721-722` labels; the #306 fallback (`get_run_info` step 6c, :2267-2277, display-time only — **not a DB write**) is labeled "engine, single eval" so the inflated number never renders bare. |

### In scope — Wave B (version-backend + OE run-launch robustness)

| Item | Backlog | Content |
|---|---|---|
| **U4 — persist backend on problem version** (migration v14) | 369 | **Migration v14, isolated, one column** (`problem_versions.backend TEXT NOT NULL DEFAULT 'openevolve'`, mirrors `runs.backend` v9 shape). Exactly two DDL edits (recon): fresh `_PROJECT_SCHEMA_SQL` (db.py:42-47) + new `if current < 14:` ALTER (after :479); **no-op-and-bump on the global DB** (`problem_versions` is project-DB-only, guard on table presence like v10/v12/v13); bump `CURRENT_SCHEMA_VERSION = 14`. Add `backend: str = "openevolve"` to `ProblemVersion` (models/problem.py:31-48) + the 4 CRUD copies (insert/get/get_by_hash/list). Persist the currently-discarded `--backend` at version-create (core/problem.py:165 — used only for validation today, :196). **Resolution order** `explicit --backend > version backend > default`: **contradicts backlog as-is** (recon) — both the CLI flag (cli/run.py:44-50) and `RunConfig.backend` (models/run.py:85) hard-default to `"openevolve"`, so explicit-vs-default is indistinguishable → change the CLI default (and `RunConfig.backend`) to a **`None` sentinel** (resume already models this: `resume_run(backend_name: str \| None`). Reorder `launch_run` to load the version row (:718) **before** resolving the backend (:707) so the version's backend is available; warn (not error) on mismatch (mirror the :747-751 stderr warning precedent). |
| **U8 — `validate_seed_metrics()` backend hook** | 370 | New `EvolutionBackend` protocol method (base.py:287-492, next to `validate_config`/`generate_wrapper`), called **right after** the existing pre-flight in **both** copies (`launch_run` :962-1006, `resume_run` :1650-1692 — or extract the block). OE impl: fail fast when `database.feature_dimensions` (read from `resolved_config` :1701) names a metric **absent or non-numeric** in the seed's pre-flight `InstanceTestResult.metrics`; **builtins `complexity`/`diversity`/`combined_score` allowed** (introduce this allowlist fresh in the OE backend — none exists today; the builtins are computed upstream inside OpenEvolve). Shinka: no-op (only metric contract is `combined_score`). Note (recon): a non-float-coercible metric already fails pydantic inside `run_instance` → the live case the hook adds is the **absent** metric. |
| **U6 phase 2 — smarter default checkpoint cadence** | 364 (part) | **OE-only** (Shinka has no `checkpoint_interval`). Insert between `build_config` step 5 and 5b (after openevolve.py:811), **gated on `"checkpoint_interval" not in config`** (absence = "unset"; presence in config.yaml or `--config-override` = explicit, **never touched**): set `max(1, min(100, iterations//10))`. This naturally defuses 5b's default-100-vs-small-iters clamp and leaves the S17a-12 phase-1 warn (5c) firing only on explicit equality. `effective_iters` = `config["max_iterations"]`. |

### In scope — Wave C (flagship + hardening + spike + docs — parallelizable)

| Item | Backlog | Content |
|---|---|---|
| **Top-N solution promotion** (flagship) | 299 | Revive `solution extract --rank N` (removed in tasks 197/198; `core.extract_solution` already accepts arbitrary rank — DB `UNIQUE(run_id, rank)` ready) + optional `--program-id` for Shinka. Resolve `run.backend` → `get_backend(...).capabilities().top_n_extraction` (**the field already exists** base.py:158 with correct per-backend values — Shinka `True`, OE `False`; the missing piece is a **consumer**, not the capability). **Shinka path**: new `extract_ranked_program(run_dir, rank\|program_id)` reading `programs.sqlite` (the :2012 `ORDER BY combined_score DESC` query without `LIMIT 1`), materialized to `programs/rank-<N>.py` via the existing `extract_solution` recovery flow (core/solution.py:447-452 pattern) — works **retroactively** on old runs, no run-dir layout change. **OE consciously deferred** (see below). |
| **base.py reap hardening** (carry-over #359) | — | Recursive-descendant enumeration + `killpg` in `ChildProcessReaperMixin` (base.py:35-105 — today DIRECT children only, per-PID `SIGTERM`→3s→`SIGKILL`, no recursion/killpg/PID-reuse guard). Reuse the S17a `evaluator_runner.py` pgid helpers (`_own_pgid` :266, `_signal_child` :288, `_reap_process_group` :326 — directly liftable, no import cycle: evaluator_runner imports only models.problem). Hardened `_current_child_pids` recurses `/proc/<pid>/task/*/children`; per-survivor `os.getpgid` + `_reap_process_group` covers grandchildren. **Decision (session 057 — supersedes the sprint-017a.md:60 "v0.18 only if evidence of need" gate)**: this ships **defensively regardless**, as an unconditional item in the committed v0.18 carry-over pool (2026-07-04-session-057.md:70-71). The #320 spike (S18-20) is a coupled evidence source that **informs which grandchild/PID-reuse cases the tests cover** but **does NOT gate shipping**. |
| **#320 — qwen15 mid-run Shinka deadlock spike** | 320 | **Timeboxed** repro/diagnosis. Test the **stall hypothesis first** (recon: Revolver's Shinka backend sets **no** LLM-request/client timeout anywhere — a stalled call blocks the scheduler indefinitely → reproducible **model-independently** via a stalling OpenAI-compatible fake endpoint, same technique as the L3 fake server), then the shinka 0.0.7 patch-apply retry loop (`max_patch_attempts`), then a scheduler deadlock. Do **not** assume `qwen15` is still pullable (precedent: `gemma4:8b` deletion killed the A2 repro). Output: findings + either a targeted fix (e.g. a Shinka LLM-request timeout lever) or a filed upstream issue; feeds the reap-hardening evidence gate. |
| **#354 — doc command-lint + code-triggered doc review** | 354 | CI test parsing **every fenced block containing a `revolver` invocation** (recon: **not** only ```` ```bash ```` — conops.md, DES-005/007, and several README blocks are untagged; a bash-only parser silently skips ~40 invocations), asserting each subcommand/flag resolves in the Typer tree. Shared **CLI-tree walker** helper on `revolver.cli.app` (root is `cli/__init__.py:24`, **not** `main.py`) walking the `.commands` dict (typer 0.26.6 vendors click as `typer._click` → `isinstance` vs real click **fails**; walk the attr), including **group-callback params** (`run`/`eval` are `invoke_without_command=True` groups) and a **deprecated-flag denylist** (`problem version create --tag` still resolves). Invert the doc-reviewer trigger to also fire on `src/revolver/cli/*.py` changes. |
| **#355 — per-guide freshness stamps** | 355 | `verified-against: vX.Y.Z` front-matter on the 3 guide/tutorial files (`docs/guides/initial-program-structure.md`, `docs/guides/tuning-oe-config.md`, and **`docs/specs/user-story-e2e.md`** — note the 3rd is under `docs/specs/`, **NOT** `docs/guides/`; none have front-matter today) + a release-checklist / CI version-lag check that flags any doc >N versions behind (**the check must scan `docs/guides/` _plus_ `docs/specs/user-story-e2e.md`, not glob `docs/guides/*` alone**). |
| **#356 — Shinka tuning guide restructure** | 356 | Restructure `tuning-oe-config.md` (996 L, OE-specific in name; already partially Shinka-aware — thread caps :196, known-issues :955) into a backend-neutral **concept** guide + per-backend knob reference (OE / Shinka: islands+archive, no MAP-Elites grid, bandit selection, `max_patch_attempts`, `reasoning_efforts`, `max_proposal_jobs`, novelty rejection); relocate the cross-engine ensemble section (currently wedged in at line 863, ~24% of the guide). |

### Explicitly out of scope (deferred, with rationale)

| Deferred item | Backlog | Rationale |
|---|---|---|
| **OE top-N extraction** (the OE half of #299) | 299 (part) | OE top-N would encode the sum-of-metrics ordering that **#367 is changing this same sprint** (ranking must ride on `combined_score` first); OE feasibility is checkpoint-*granularity*-limited (final population only if `checkpoint_interval` aligns — ties to #364). Keep `top_n_extraction=False`; document the checkpoint-granularity option in ADR-007/DES-005. Ship Shinka-only + the CLI gate now; revisit OE post-#367. |
| **#357 — executable e2e + generated CLI reference** | 357 | **Genuinely sprint-scale** (recon): transcript replay incl. the expensive run/resume/recovery phases + generated CLI reference + Diátaxis split + possible ADR-008. **Recommend OUT of S18 → S19.** De-risked by #354 landing the shared CLI-tree walker (the exact seam #357's help-generator + replay reuse), and most parse-only value is already delivered by #354's lint. |
| **#371 — U9 bandit warm-start** (upstream) | 371 | Genuine **upstream** gap (shinka 0.0.7 has no per-arm prior: AsymmetricUCB none, ThompsonSampler scalar-only). 0.17.1 already shipped the interim FACT-B/tuning-guide doc guidance. **Keep OUT** — demand-gated; no Revolver-side code lever exists. File upstream only if demand persists. |
| **Two-timeout-semantics reconciliation** | 367/368 | By design after v0.18 there are **two** timeout semantics: engine fitness *penalizes* timeouts (evolution pressure), post-eval reports *honest coverage-labeled* means (reporting). Labels carry the burden (triage §3 deliberate residual) — not a defect to "fix" this sprint. |

---

## Verified facts driving the design (recon-confirmed — do not re-derive)

1. **Schema head is v13** (`db.py:32`, spot-checked) — v14 is the next free slot; `problem_versions` is **project-DB-only** → v14 must no-op-and-bump the global DB.
2. **OE display path sums numeric metrics** (`openevolve.py:1124-1129`, spot-checked) — but the **solution-DB `best_score`** written at `core/run.py:1063-1071` is already `combined_score`-based (recovery path prefers it :1268-1276). #367 commit (i) is **display/fallback-only**; the survivorship bias in commits (ii)/(iii) is the bigger honesty lever.
3. **`top_n_extraction` already exists** (`base.py:158`, Shinka `True` / OE `False`, spot-checked) with **zero consumers** — #299 adds a consumer, not the capability.
4. **`evaluation.*` is un-validated today** — OE pops the whole section pre-parse (`openevolve.py:208-209`), Shinka treats it as a known top-level but never inspects keys → `evaluation.on_timeout` typos are currently *silent* (typo risk, **not** rejection risk); #367 commit (iii)'s value validation is net-new.
5. **`RunConfig.backend` / CLI `--backend` both hard-default `"openevolve"`** — the U4 resolution order is **unimplementable without a `None` sentinel** (recon contradiction flag).
6. **The Shinka wrapper has no distinct `TimeoutError` branch** (`shinka.py:369-376` catches all) — #367 commit (ii) must **add** it (triage §3; absent from the backlog line).
7. **`_run_post_eval` hardcodes `timeout_s=300` and stores nothing** (`core/run.py:1262-1270`, TODO(S5-08)) — #368 finishes exactly this Task-86 residue via `core.eval.evaluate_solution`.

---

## Tasks

### Wave A — Eval honesty semantic slice (strict serial)

| # | Task | Layer | Backlog | PR | Depends | Acceptance criteria |
|---|---|---|---|---|---|---|
| S18-01 | **U13 (i) — OE display guard.** `openevolve.py` `parse_population` (:1124-1129) + `read_checkpoint_best_score` (:1196-1201): prefer numeric `combined_score`; define the no-`combined_score` fallback (population ranking needs a number — sum is acceptable *here* since it precedes the coverage-key commit). Update `tests/test_run_population.py` (:202 `1.75` et al.; :217/:245/:258 bare `score` fixtures). | infra | 367 | PR-1 | — | `run population` / live `run status` display and the #306 fallback rank by `combined_score` when present; the `1.75`-sum test is revised; no crash on a metrics dict lacking `combined_score` |
| S18-02 | **U13 (ii) — coverage keys + timeout side-channel in BOTH wrapper templates.** OE `_WRAPPER_TEMPLATE` + Shinka `_WRAPPER_TEMPLATE`: add `instances_valid`/`instances_total` to the result dict, a timeout side-channel row, **add the distinct `TimeoutError` branch to the Shinka template** (fact 6), and **exclude `instances_*` from the mean loops** (OE :1428-1435, Shinka :394-403). Preserve `{{`/`}}` escaping. Reserve the `instances_` prefix. | infra | 367 | PR-1 | S18-01 | Generated wrappers emit coverage keys that are **not** summed into the displayed score (guarded by S18-01); a timed-out instance is recorded on the side-channel in both templates; no `instances_*` key contaminates the metric mean |
| S18-03 | **U13 (iii) — `evaluation.on_timeout`/`timeout_score` + default flip.** Parse at `core/run.py:869-873` (shared launch point); add `on_timeout`/`timeout_score` to `BackendRunSpec` (base.py); thread into both `generate_wrapper` timeout branches (penalize → write `timeout_score`; drop → survivor-mean as today); **net-new value validation** (`penalize\|drop`, finite score) at the parse point; update both config templates (OE :1600, Shinka :283); **default = `penalize`**. Resume inherits the baked policy (:1497-1502). | infra/domain | 367 | PR-1 | S18-02 | Default run **penalizes** timed-out instances with `timeout_score` (0.0); `--config-override evaluation.on_timeout=drop` restores survivor-mean (0.17 behavior); `on_timeout=bogus` or a non-finite `timeout_score` is **rejected at run/dry-run**; for runs with **zero timeouts**, `penalize` and `drop` produce **identical scores** (the policy is a no-op) — metrics differ from the 0.17 output only by the reserved `instances_*` coverage keys that S18-02 adds to every wrapper (so this is *not* a byte-identical-to-0.17 claim) |
| S18-04 | **PR-1 tests (L1/L2).** Display prefers `combined_score`; coverage keys never inflate the score; penalize-vs-drop fitness; validation rejects bad `evaluation.*`; Shinka `TimeoutError` branch fires. | test | 367 | PR-1 | S18-01..03 | New IDs below pass; full suite green (no-shinka env); Shinka L2 green (shinka env) |
| S18-05 | **U11 (A) — swap `_run_post_eval` → `evaluate_solution`.** Delete `core/run.py:1242-1306`; rewire `launch_run` (:1083-1100) + `resume_run` (~:1775) to `core.eval.evaluate_solution`; thread `config.dataset_name`; `force=True`/has-existing-eval check; keep warn-only; DB-contention guard (commit `proj_conn` / WAL / busy_timeout before the call). | domain | 368 | PR-2 | S18-04 (PR-1 merged) | Post-run eval writes `eval_metadata`/`eval_instances` (no longer stderr-only); no DB-contention error when `launch_run` still holds `proj_conn`; a missing/failed post-eval still only warns; the hardcoded `timeout_s=300` is gone (uses the eval path's timeout) |
| S18-06 | **U11 (B) — honest display pass.** `get_run_info`/`RunInfo` show engine best (labeled **"engine, single eval"**) next to the post-eval **mean + U13 coverage**; `cli/run.py:721-722` labels; the #306 display fallback (:2267-2277) labeled "engine, single eval". | domain/cli | 368 | PR-2 | S18-05 | `run info` renders both numbers with distinct labels; the bare inflated engine number never appears without its "single eval" label; JSON output carries both fields |
| S18-07 | **PR-2 tests (L2).** Post-eval mean stored + displayed; labels distinct; #306 fallback labeled; single-LLM default path unaffected. | test | 368 | PR-2 | S18-05..06 | New IDs below pass; zero regression on existing `run info` tests |

### Wave B — Version-backend + OE run-launch robustness

| # | Task | Layer | Backlog | PR | Depends | Acceptance criteria |
|---|---|---|---|---|---|---|
| S18-08 | **U4 — migration v14 (`problem_versions.backend`).** Two DDL edits only (recon): fresh `_PROJECT_SCHEMA_SQL` (db.py:42-47) + new `if current < 14:` ALTER (after :479), guard+bump on the global DB; `CURRENT_SCHEMA_VERSION = 14`. Add `backend: str = "openevolve"` to `ProblemVersion` + 4 CRUD copies (insert/get/get_by_hash/list). | infra | 369 | PR-3 | — (db.py v14 isolated; **PR-3 merges after PR-2** per the core/run.py serialization + merge order) | Fresh project DB has the column; a v13 DB upgrades cleanly; global DB no-ops-and-bumps; existing version rows default `'openevolve'`; `mypy` clean |
| S18-09 | **U4 — persist + resolve backend on version.** Persist `--backend` at version-create (core/problem.py:165 — discarded today). Resolution `explicit --backend > version backend > default`: change CLI `--backend` default + `RunConfig.backend` to a **`None` sentinel** (fact 5); reorder `launch_run` to load the version row before `get_backend` (:718 before :707); warn (not error) on mismatch (mirror :747-751). Dry-run inherits via the same `launch_run`. Resume unaffected (no `--backend` flag). | domain/cli | 369 | PR-3 | S18-08; **PR-2 merged** (the core/run.py resolution edit follows Wave A — matches the Stream B "after PR-2" gate + the PR-1→PR-2→PR-3→PR-4 merge order) | `version create v2 --backend shinka` persists `shinka`; `run v2` (no `--backend`) resolves Shinka from the version; `run v2 --backend openevolve` runs OE **with a mismatch warning**; a version with no stored backend still defaults `openevolve` |
| S18-10 | **PR-3 tests (L2).** Migration v14 fresh+upgrade+global-no-op; backend persisted at create; 3-way resolution order; mismatch warn. | test | 369 | PR-3 | S18-08..09 | `test_db_migration_v14_problem_versions_backend` + resolution/mismatch scenarios pass |
| S18-11 | **U8 — `validate_seed_metrics()` hook.** New protocol method (base.py:287-492). OE impl: `feature_dimensions` (from `resolved_config` :1701) must be present + numeric in the seed pre-flight `InstanceTestResult.metrics`; **allowlist builtins** `complexity`/`diversity`/`combined_score` (introduce fresh). Shinka: no-op. | infra | 370 | PR-4 | S18-04 (PR-1 merged, openevolve.py); **PR-2 merged** (PR-4 follows Wave A on core/run.py — matches the Stream B "after PR-2" gate + merge order) | Seed missing a declared non-builtin dim → clear pre-flight error naming the dim + available metrics; a declared builtin dim never errors; Shinka run unaffected |
| S18-12 | **U8 — wire the hook after the existing pre-flight.** Call `validate_seed_metrics` right after the pre-flight in **both** copies (`launch_run` :962-1006, `resume_run` :1650-1692) — or extract the shared block. Skipped when the dataset dir is empty (as pre-flight already is). | domain | 370 | PR-4 | S18-11; **PR-2 + PR-3 merged** (the core/run.py pre-flight-hook edit at :962/:1650 rebases on PR-2's post-eval deletions and PR-3's resolution reorder) | The hook fires on both launch and resume; an empty-dataset run still skips pre-flight (and thus the hook); the error aborts **before** iteration 0 |
| S18-13 | **U6 phase 2 — default checkpoint cadence.** `build_config` insert after openevolve.py:811, gated on `"checkpoint_interval" not in config`: `max(1, min(100, iterations//10))`; explicit values (config.yaml / `--config-override`) **never touched**. | infra | 364 | PR-4 | S18-04 (PR-1 merged, openevolve.py); **PR-2 merged** (PR-4 follows Wave A on core/run.py — matches the Stream B "after PR-2" gate + merge order) | A default ≤100-iter run gets a mid-run checkpoint (`interval < iterations`); an explicit `checkpoint_interval` is preserved verbatim; the S17a-12 phase-1 warn (5c) fires only on explicit equality; 5b clamp no longer trips on default-100-vs-small-iters |
| S18-14 | **PR-4 tests (L2).** Seed missing metric fails fast; builtins allowed; Shinka no-op; cadence default-when-unset vs untouched-when-explicit. | test | 370/364 | PR-4 | S18-11..13 | New IDs below pass |

### Wave C — Flagship + hardening + spike + docs (parallel)

| # | Task | Layer | Backlog | PR | Depends | Acceptance criteria |
|---|---|---|---|---|---|---|
| S18-15 | **Top-N — CLI gate + rank revival.** `solution extract`: revive `--rank N` (+ optional `--program-id` for Shinka); resolve `run.backend` → `capabilities().top_n_extraction`; clear "not supported on `<backend>`" error when False. `core.extract_solution` already accepts arbitrary rank — pure CLI/plumbing. | cli/domain | 299 | PR-5 | — (clean files) | `solution extract --run <id> --rank 2` reaches the backend on a top-N-capable run; the same on an OE run exits non-zero with a clear message; `--rank 1` behaves exactly as today |
| S18-16 | **Top-N — Shinka on-demand path.** New `ShinkaBackend.extract_ranked_program(run_dir, rank\|program_id)` reading `programs.sqlite` (the :2012 query without `LIMIT 1`); materialize to `programs/rank-<N>.py` via the `extract_solution` recovery flow (core/solution.py:447-452). Retroactive on old runs; no run-dir layout change. | infra | 299 | PR-5 | S18-15; **PR-1 merged** (shinka.py `_WRAPPER_TEMPLATE` rewrite — same file, hard) + **PR-4 merged** (Shinka no-op `validate_seed_metrics` — same `ShinkaBackend` class; avoids a same-file/same-class rebase) | `--rank 2` on a Shinka run materializes and promotes the 2nd-best program (distinct `combined_score`); `--program-id <id>` promotes an arbitrary population program; UNIQUE(run_id, rank) respected |
| S18-17 | **Top-N — tests + DES/ADR narrative reconcile.** L2: rank-2 Shinka extract, OE clear-unsupported, program-id path. Reconcile the stale abandoned top-N narrative (sprint-014 §Review :309; DES-005 §~966/§1246) + document OE checkpoint-granularity deferral (`top_n_extraction=False` stays). | test/doc | 299 | PR-5 | S18-16 | Test IDs pass; DES-005/ADR-007 top-N section reflects Shinka-native + OE-deferred, no stale "promote via extract" contradiction |
| S18-18 | **base.py reap hardening.** Recursive-descendant enumeration + `killpg` in `ChildProcessReaperMixin` (base.py:35-105), reusing the S17a `evaluator_runner.py` pgid helpers (`_own_pgid`/`_signal_child`/`_reap_process_group`); PID-reuse guard; per-survivor `os.getpgid` + group sweep covers grandchildren. | infra | 359 (carry) | PR-6 | **PR-1 merged** (`BackendRunSpec` fields) + **PR-4 merged** (`validate_seed_metrics` protocol method) — hard, same base.py file/classes. #320 (S18-20) verdict **informs scope/tests but does NOT gate shipping** — reap hardening ships **regardless** (committed carry-over pool; supersedes the sprint-017a.md:60 "only if evidence" gate) | A mocked run leaking a **grandchild** is reaped (not just direct children); `killpg` used with single-PID fallback; the Shinka single-PID wrapper-kill grandchildren caveat is closed at the backstop; existing shutdown tests pass |
| S18-19 | **PR-6 tests.** Grandchild reap; killpg path; single-PID fallback; no regression on the 017a backstop. | test | 359 | PR-6 | S18-18 | New IDs pass; `test_openevolve_shutdown.py`/`test_shinka_shutdown.py` unaffected |
| S18-20 | **#320 spike — qwen15 mid-run deadlock.** Timeboxed: stall hypothesis first (no-LLM-timeout via stalling fake endpoint, model-independent), then patch-apply loop, then scheduler. Deliver findings + a fix (e.g. a Shinka LLM-request timeout lever) **or** a filed upstream issue; supply the reap-hardening evidence gate. | investigation | 320 | PR-7 | — | A documented repro (or a documented failure-to-repro with the reason) + a concrete recommendation; if a fix is scoped, it is a separate small PR; backlog #320 updated with the verdict |
| S18-21 | **#354 — doc command-lint.** CI test parsing fenced-block `revolver` invocations, asserting each subcommand/flag resolves in the Typer tree; shared CLI-tree walker (`revolver.cli.app` `.commands` walk, vendored-click aware, group-callback params, deprecated-flag denylist for `--tag`). **Line grammar: match only _line-initial_ invocations inside a fence (`revolver …`, `$ revolver …`, `> revolver …`); inline-prose backtick mentions (e.g. spec-run.md:217's `` `revolver solution extract … --rank <N>` `` sentence) are OUT of scope** — this keeps the lint off the stale `--rank` prose that PR-5 (S18-17) reconciles, so PR-8 stays lint-only and does not collide with PR-5's DES-005/conops/spec-run edits. | test/infra | 354 | PR-8 | — (prefer merge **after PR-5** so the revived-`--rank` corpus is consistent — soft, since the line-initial grammar already skips the prose mentions) | The lint catches a renamed/removed flag on the PR that renames it; it does **not** false-positive on `problem version create --tag`; it does **not** fire on inline-prose backtick mentions (line-initial fenced invocations only); runs in CI (`unit` marker); parses untagged fences too |
| S18-22 | **#354 — invert doc-reviewer trigger.** Fire the doc-reviewer also when `src/revolver/cli/*.py` changes (prose in `.claude/agents/doc-reviewer/agent.md` frontmatter + the CLAUDE.md agents table; optionally a new hook). | doc/config | 354 | PR-8 | — | The doc-reviewer trigger description names CLI-source changes; no existing hook is broken |
| S18-23 | **#355 — freshness stamps.** `verified-against: vX.Y.Z` front-matter on the 3 guide/tutorial files (`docs/guides/initial-program-structure.md`, `docs/guides/tuning-oe-config.md`, **`docs/specs/user-story-e2e.md`** — the 3rd is under `docs/specs/`, NOT `docs/guides/`) + a release-checklist / CI version-lag check (**scans `docs/guides/` plus `docs/specs/user-story-e2e.md`, not `docs/guides/*` alone**). | doc | 355 | PR-8 | S18-25 (order after #356 restructure on the tuning guide) | Each guide carries a stamp; the check flags a doc >N versions behind; stamp added to the **restructured** tuning guide (not the pre-restructure one) |
| S18-24 | **PR-8 tests + doc-reviewer pass.** Lint test cases (resolving vs renamed vs deprecated-`--tag`); trigger/stamp docs reviewed. | test/doc | 354/355 | PR-8 | S18-21..23 | Lint test IDs pass; doc-reviewer 0 FAIL on touched sections |
| S18-25 | **#356 — Shinka tuning guide restructure.** `tuning-oe-config.md` → backend-neutral concept guide + per-backend knob reference (OE / Shinka); relocate the cross-engine ensemble section (line 863). | doc | 356 | PR-9 | — | The guide is backend-neutral in name+structure; OE and Shinka knob references are separated; the ensemble section is a top-level cross-engine section, not wedged under OE; doc-reviewer 0 FAIL |

---

## Doc-edit cascade — run spec-before-code (before implementation PRs)

Per the project's spec-before-code pattern (sprint-017 session 055) and Release Checklist step 0, run the spec/DES/validation cascade **before** the Wave A/B implementation PRs so they land on a reviewed baseline. Edit surface (from triage §3 + recon):

- **ADD FRs** (next free numbers, confirm at write time): U13 timeout semantics (`evaluation.on_timeout`/`timeout_score`, default-penalize), U11 honest best-score display, U4 backend-on-version + resolution order, U8 seed-metric validation, top-N `solution extract --rank`. A normative note that `evaluation.*` is now a **validated** Revolver-owned section.
- **AMEND** (route each edit to the section that actually owns the code — the pre-v0.17.0 cascade produced **9 validation FAILs** from exactly this U11/U13 misroute lag class):
  - **DES-005 §3.2** (the OE `_WRAPPER_TEMPLATE` mean loop — DES-006:52 explicitly delegates this to DES-005 §3.2): `instances_*` coverage keys + mean-exclusion + the penalize/drop timeout contract + the Shinka `TimeoutError` branch (U13).
  - **DES-005 §4.4** (teardown, ~:604): recursive-descendant + killpg reap hardening — **this is where reap lives, NOT §7**.
  - **DES-005 §4/§5** (run-launch): pre-flight `validate_seed_metrics` hook (U8) + `RunConfig.backend` None-sentinel resolution order (U4); capabilities top-N consumer.
  - **DES-005 §7 — Post-Run Training Evaluation (FR-RUN-019/020, :789)** — **U11** (was missing from the earlier list): `_run_post_eval` → `core.eval.evaluate_solution` (persists eval_metadata/eval_instances), dual-score `RunInfo` display. §7 is precisely the section U11 rewrites.
  - **DES-005 §2.5/§8**: the new dual-score `RunInfo` fields.
  - **DES-006**: penalize/drop + coverage-key semantics only where DES-006 owns aggregation (the read/eval path); the wrapper-template coverage keys themselves are a **DES-005 §3.2** amendment per DES-006:52, not solely DES-006.
  - **DES-003**: `problem version` backend persistence.
  - **DES-001**: schema v14.
  - **DES-007/ADR-007**: top-N Shinka-native / OE-deferred; reconcile the sprint-014 stale narrative.
- **Validation**: traceability rows for each new FR; `val-integration-tests.md` adds the L2 IDs below; `val-e2e-tests.md` optionally adds a penalize-vs-drop scenario against the fake server.
- Reviewers: **spec-reviewer** + **validation-reviewer** before code; **doc-reviewer** post-release (checks README/guide version numbers — note #355 stamps + #356 restructure land in this sprint).

---

## Integration Tests (L2)

New IDs (added to `val-integration-tests.md`) that must pass at sprint end. Baseline: **1471 passing** (post-017a).

| Area | Scenario | Test ID | Status |
|---|---|---|---|
| U13 display | `parse_population`/`run status` rank by `combined_score`, not sum-of-metrics | `test_oe_display_prefers_combined_score` | Planned |
| U13 coverage | Wrapper `instances_valid`/`instances_total` emitted, **not** summed into the score | `test_wrapper_coverage_keys_not_in_score` | Planned |
| U13 timeout | Shinka wrapper's distinct `TimeoutError` branch records the timeout on the side-channel | `test_shinka_wrapper_timeout_branch` | Planned |
| U13 penalize | Default run penalizes a timed-out instance with `timeout_score`; `on_timeout=drop` restores survivor-mean | `test_on_timeout_penalize_vs_drop` | Planned |
| U13 validation | `evaluation.on_timeout=bogus` / non-finite `timeout_score` rejected at run/dry-run | `test_evaluation_on_timeout_validation` | Planned |
| U11 post-eval | Post-run eval writes `eval_metadata`/`eval_instances` (no longer stderr-only); no DB-contention error | `test_post_run_eval_persists_via_evaluate_solution` | Planned |
| U11 display | `run info` shows engine best ("single eval") + post-eval mean (coverage-labeled); #306 fallback labeled | `test_run_info_honest_score_labels` | Planned |
| U4 migration | Fresh + v13-upgrade project DB gets `problem_versions.backend`; global DB no-ops; rows default `openevolve` | `test_db_migration_v14_problem_versions_backend` | Planned |
| U4 resolution | `version create --backend shinka` persists; `run` resolves it; explicit `--backend` mismatch warns | `test_run_backend_resolution_order_and_mismatch_warn` | Planned |
| U8 seed | Seed missing a declared non-builtin `feature_dimensions` metric fails at pre-flight (launch + resume) | `test_validate_seed_metrics_missing_dim_fails` | Planned |
| U8 builtins | Declared builtin dim (`complexity`/`diversity`/`combined_score`) never errors; Shinka no-op | `test_validate_seed_metrics_builtins_and_shinka_noop` | Planned |
| U6 phase 2 | Default ≤100-iter run gets a mid-run checkpoint; explicit `checkpoint_interval` untouched | `test_checkpoint_cadence_default_when_unset` | Planned |
| Top-N | `solution extract --rank 2` promotes the 2nd-best Shinka program; `--program-id` path | `test_solution_extract_rank_n_shinka` | Planned |
| Top-N gate | `--rank 2` on an OE run → clear "not supported" error | `test_solution_extract_rank_unsupported_oe` | Planned |
| Reap hardening | A leaked **grandchild** is reaped via recursive-descendant + `killpg`; single-PID fallback | `test_reaper_grandchild_killpg` | Planned |
| Doc lint | Lint catches a renamed flag; passes on deprecated `--tag`; parses untagged fences | `test_doc_command_lint_resolves_cli_tree` | Planned |
| Non-regression | Full suite (1471+ baseline) green (no-shinka env); Shinka L2 green (shinka env) | full-suite regression | Planned |

**Test count planned**: **16 new automated L2 test IDs** + 1 spike deliverable (#320) + full-suite regression. Expected suite ~1487+.

---

## PR Grouping

| PR | Backlog | Tasks | Files (primary) | Wave |
|---|---|---|---|---|
| **PR-1** | 367 | S18-01..04 | `openevolve.py`, `shinka.py` (wrapper templates), `core/run.py` (:869 parse), `base.py` (BackendRunSpec), `tests/test_run_population.py` | A |
| **PR-2** | 368 | S18-05..07 | `core/run.py` (post-eval swap + display), `core/eval.py`, `cli/run.py` (labels), `models/run.py` (`RunInfo` dual-score fields — S18-06 "JSON output carries both fields") | A (after PR-1) |
| **PR-3** | 369 | S18-08..10 | `db.py` (v14 — isolated), `models/problem.py`, `models/run.py`, `cli/problem.py`, `core/problem.py`, `cli/run.py`, `core/run.py` (backend resolution) | B |
| **PR-4** | 370, 364 | S18-11..14 | `base.py` (protocol), `openevolve.py` (seed-validate + cadence), `shinka.py` (no-op), `core/run.py` (pre-flight hook) | B |
| **PR-5** | 299 | S18-15..17 | `cli/solution.py`, `core/solution.py`, `shinka.py` (extract_ranked_program), DES-005/ADR-007 | C |
| **PR-6** | 359 | S18-18..19 | `base.py` (`ChildProcessReaperMixin`) | C |
| **PR-7** | 320 | S18-20 | investigation (spike); fix PR TBD | C |
| **PR-8** | 354, 355 | S18-21..24 | `tests/`, `.claude/agents/doc-reviewer/agent.md`, `CLAUDE.md`, `docs/guides/{initial-program-structure,tuning-oe-config}.md` + **`docs/specs/user-story-e2e.md`** front-matter (the 3rd stamp file is NOT under `docs/guides/`), `.github/workflows/ci.yml` | C |
| **PR-9** | 356 | S18-25 | `docs/guides/tuning-oe-config.md` | C |

---

## Parallelization

### Dependency graph

```
v0.17.1 (develop) + spec-before-code cascade
        │
   ┌────┴──────────────────────── WAVE A (critical path — semantic slice) ─────────────────┐
   │   PR-1 (#367 U13)  S18-01 → S18-02 → S18-03 → S18-04   (strict internal order)         │
   │        │  files: openevolve.py, shinka.py, core/run.py, base.py                        │
   │        └──> PR-2 (#368 U11)  S18-05 → S18-06 → S18-07   ← HARD dep on PR-1 merged       │
   │                 files: core/run.py, core/eval.py, cli/run.py                            │
   └────────────────────────────────────────────────────────────────────────────────────────┘
        │
   ┌────┴──────────────────────── WAVE B (after Wave A on shared files) ───────────────────┐
   │   PR-3 (#369 U4)   S18-08 → S18-09 → S18-10   ← core/run.py resolution (after Wave A)   │
   │        (db.py v14 is ISOLATED — could start earlier, but the resolution edit collides)  │
   │   PR-4 (#370+#364) S18-11 → S18-12 → S18-13 → S18-14   ← openevolve.py + core/run.py     │
   │        (PR-3 ∥ PR-4 possible — different core/run.py regions — but coordinate that file) │
   └────────────────────────────────────────────────────────────────────────────────────────┘
        │
   ┌────┴──────────────────────── WAVE C (parallel from sprint start where files are clean) ┐
   │   PR-5 (#299 top-N)  S18-15 → S18-16 → S18-17                                            │
   │        cli/solution.py + core/solution.py CLEAN → S18-15 starts immediately;            │
   │        S18-16 shinka.py sequences after PR-1 AND PR-4 (same file/class)                 │
   │   PR-6 (reap)        S18-18 → S18-19   ← base.py; after PR-1(BackendRunSpec)+PR-4(hook); │
   │        #320 evidence informs tests only (does NOT gate shipping)                         │
   │   PR-7 (#320 spike)  S18-20   ← investigation; STARTS IMMEDIATELY (read-only mostly)     │
   │   PR-8 (#354/#355)   S18-21..24   ← tests/.claude/CLAUDE.md/CI; STARTS IMMEDIATELY;      │
   │        S18-23 stamp sequences AFTER PR-9 (#356) restructures the tuning guide           │
   │   PR-9 (#356 guide)  S18-25   ← docs only; STARTS IMMEDIATELY                            │
   └────────────────────────────────────────────────────────────────────────────────────────┘
```

### Critical path

```
S18-01 → S18-02 → S18-03 → S18-04  (PR-1 #367 merge)
   → S18-05 → S18-06 → S18-07  (PR-2 #368 merge)
   → S18-11 → S18-12 → S18-13 → S18-14  (PR-4 merge)
   → full regression + release
```

The eval-honesty chain (#367 → #368) is the deepest and strictly serial (hard dependency + heavy `core/run.py`+`openevolve.py` overlap). Wave B follows it on those shared files. Everything in Wave C parallelizes off the critical path from sprint start (top-N CLI gate, both doc PRs, and the #320 spike all touch files the critical path never opens).

### Parallel work streams

| Stream | Tasks | Can start after | Agent |
|---|---|---|---|
| A — Eval honesty (PR-1 → PR-2) | S18-01..07 | cascade merged | Agent 1 (owns the semantic core; sequential) |
| B — Version-backend + OE robustness (PR-3, PR-4) | S18-08..14 | PR-2 merged (core/run.py) | Agent 1 or 2 (coordinate `core/run.py`) |
| C — Top-N flagship (PR-5) | S18-15..17 | S18-15 immediately; S18-16 after PR-1 | Agent 2 |
| D — Reap hardening (PR-6) | S18-18..19 | PR-1 + PR-4 merged (#320 verdict informs scope/tests, does **not** gate shipping) | Agent 3 |
| E — #320 spike (PR-7) | S18-20 | sprint start | Agent 3 |
| F — Docs #354/#355 (PR-8) | S18-21..24 | sprint start (S18-23 after PR-9) | Agent 4 |
| G — Docs #356 (PR-9) | S18-25 | sprint start | Agent 4 or new |

Peak parallelism: **4 agents** — Stream A (semantic core) + Stream C (top-N CLI gate, clean files) + Stream E (#320 spike, read-only) + Stream F/G (docs) all run concurrently from sprint start. Streams D and B open once their shared-file prerequisites merge.

### Conflict risks

- **`core/run.py`** — the highest-conflict file this sprint: PR-1 (:869 `evaluation.*` parse), PR-2 (delete `_run_post_eval` :1242-1306, display :2267-2277, call sites :1083/:1775), PR-3 (backend resolution :707-720), PR-4 (pre-flight hook :962/:1650). **Serialize the whole chain** (PR-1 → PR-2 → PR-3/PR-4), or route all `core/run.py` edits through one agent. Different regions, but high churn.
- **`openevolve.py`** — PR-1 (display :1124-1129 + wrapper + `generate_wrapper` timeout args), PR-4 (`validate_seed_metrics` :1701 + cadence :811). Different regions; sequence PR-4 after PR-1.
- **`shinka.py`** — PR-1 (wrapper template :296-470 + `TimeoutError` branch), PR-4 (no-op `validate_seed_metrics` on `ShinkaBackend`), PR-5 (`extract_ranked_program` ~:1978, **same `ShinkaBackend` class** as PR-4). Three disjoint regions, but PR-4 and PR-5 both add methods to `ShinkaBackend`; **sequence PR-5's shinka.py commit after PR-1 _and_ PR-4** to avoid a same-file/same-class rebase.
- **`base.py`** — PR-1 (`BackendRunSpec` fields :243-area), PR-4 (`validate_seed_metrics` protocol :331-area), PR-6 (`ChildProcessReaperMixin` :35-105). Three different classes; sequence PR-6 last.
- **`db.py`** — PR-3 only (v14). **Isolated** — no other PR touches it. Low risk.
- **`cli/run.py`** — PR-2 (dual-score `(from run)` labels :715-725), PR-3 (`--backend` default :44-50). Different regions; **PR-2 then PR-3, sequential** (the merge order already serializes them). Absent from the earlier inventory — logged here so any future re-parallelization sees the full map.
- **`models/run.py`** — PR-2 (`RunInfo` dual-score fields for the honest-display JSON, :313 area), PR-3 (`RunConfig.backend` None-sentinel :85). Different classes/regions; **PR-2 then PR-3, sequential**.
- **`docs/guides/tuning-oe-config.md`** — PR-9 (#356 restructure) **and** PR-8 (#355 freshness stamp, S18-23). **Sequence PR-9 first**, then stamp the restructured file (flagged in the graph).
- **`cli/solution.py` / `core/solution.py`** — PR-5 only. **Clean** — S18-15 can start immediately.
- **`tests/`, `.claude/`, `CLAUDE.md`, `.github/`** (doc-lint + trigger) **and the freshness-stamp front-matter of `docs/guides/{initial-program-structure,tuning-oe-config}.md` + `docs/specs/user-story-e2e.md`** (S18-23) — PR-8. Clean **provided PR-8 stays lint-only** (no doc-rot sweep): the stale `solution extract --rank` invocations in the corpus (spec-run.md:217, conops.md:227, DES-005:856/1314/1333 — all **inline-prose backtick** mentions) are reconciled by **PR-5** (S18-17) when `--rank` is revived, and S18-21's **line-initial** lint grammar does **not** fire on prose, so PR-8 never needs to edit those PR-5-owned files. Still, prefer **PR-5 before PR-8** so the revived-`--rank` corpus is consistent before the lint runs (belt-and-suspenders). (The tuning-guide stamp is separately sequenced after PR-9 — see the tuning-guide bullet.)

**Recommended merge order**: cascade → **PR-1 → PR-2** (Wave A serial) → **PR-3 → PR-4** (Wave B; PR-4 rebases on PR-3's `core/run.py`) → **PR-5, PR-6, PR-9, PR-8** (Wave C, rebased; hard edges: **PR-9 before PR-8's tuning-guide stamp**, and **PR-5 before PR-8** so the revived-`--rank` corpus is consistent before the doc-lint) → **PR-7** spike verdict folded in. PR-6 (reap) rebases last on `base.py` after PR-1+PR-4.

---

## Exit Criteria

The sprint is complete when ALL of the following hold:

1. **U13 honest fitness (PR-1)** — default runs **penalize** timed-out instances (`timeout_score`, default 0.0); `evaluation.on_timeout=drop` restores 0.17 survivor-mean; `evaluation.*` values are validated (bad values rejected at run/dry-run); wrapper coverage keys (`instances_valid`/`instances_total`) are emitted but never summed into the displayed score; the Shinka wrapper has a distinct `TimeoutError` branch. **The default flip is release-noted** — landed in the README v0.18.0 behavior-changes subsection + the `v0.18.0` tag annotation (see the Release note section for the landing artifacts; there is no `CHANGELOG.md` in this repo).
2. **U11 honest score (PR-2)** — post-run eval persists via `core.eval.evaluate_solution` (no longer stderr-only, no DB-contention); `run info` shows the engine best labeled "engine, single eval" next to the coverage-labeled post-eval mean; the #306 fallback never renders the inflated number bare.
3. **U4 backend-on-version (PR-3)** — migration v14 applies cleanly (fresh + v13-upgrade; global DB no-ops); `--backend` persists at version-create; resolution order `explicit > version > default` works via the `None` sentinel; an explicit mismatch **warns** (not errors).
4. **U8 seed validation (PR-4)** — a seed missing a declared non-builtin `feature_dimensions` metric fails at **pre-flight** (launch + resume) with a clear message; builtins allowed; Shinka no-op.
5. **U6 phase 2 (PR-4)** — a default ≤100-iteration run has a mid-run checkpoint; explicit `checkpoint_interval` is never overridden; the S17a-12 phase-1 warn still fires only on explicit equality.
6. **Top-N flagship (PR-5)** — `solution extract --rank 2` promotes the 2nd-best program on a Shinka run (retroactively); OE gives a clear "not supported" message; DES-005/ADR-007 top-N narrative reconciled (Shinka-native / OE-deferred).
7. **Reap hardening (PR-6)** — a leaked grandchild is reaped via recursive-descendant + `killpg` (single-PID fallback), informed by the #320 spike verdict.
8. **#320 spike (PR-7)** — a documented repro (or documented non-repro + reason) + a concrete recommendation; backlog #320 updated.
9. **Doc anti-rot (PR-8, PR-9)** — the command-lint CI test catches a renamed flag and passes on deprecated `--tag`; the doc-reviewer trigger fires on CLI-source changes; the 3 guides carry freshness stamps; the tuning guide is backend-neutral (OE/Shinka knob split, ensemble relocated).
10. **Zero regression** — full suite (1471+ baseline) green on the no-shinka env; Shinka L2 green on the shinka env; `ruff`/`mypy` clean; CI green. **No _unintended_ behavior change on the OE single-LLM default path.** This sprint makes **six deliberate, in-scope default-path changes** (each release-noted or spec-captured) that are **not** regressions: (1) the `on_timeout=penalize` fitness-landscape flip (U13, PR-1); (2) default checkpoint cadence `max(1, min(100, iterations//10))` when `checkpoint_interval` is unset (U6 phase 2, PR-4 — changes checkpoint dirs / resume points / disk-IO profile); (3) post-run eval now persists `eval_metadata`/`eval_instances` and uses the eval path's timeout instead of the hardcoded `timeout_s=300` (U11 commit A, PR-2); (4) a new pre-flight fail-fast when a seed lacks a declared non-builtin `feature_dimensions` metric (U8, PR-4 — runs that previously launched now abort before iteration 0); (5) `run info` dual-score display + labels (U11 commit B, PR-2); (6) generated wrappers emit the reserved `instances_valid`/`instances_total` keys (U13 commit ii, PR-1). The "no behavior change" clause scopes to **everything outside this enumerated list**; of the six, only (1) changes the fitness landscape a run explores.
11. **Doc cascade** — spec-before-code (FRs for U13/U11/U4/U8/top-N, DES-005/006/003/001, ADR-007/DES-007 top-N, traceability + val-integration) with spec-reviewer + validation-reviewer passed; doc-reviewer post-release 0 FAIL.

---

## Release note (v0.18.0) — REQUIRED

**Behavior change — timeout handling now penalizes by default.** As of v0.18.0, an instance that **times out** during evolution contributes a **penalty score** (`evaluation.timeout_score`, default `0.0`) to the program's fitness instead of being silently dropped from the mean. This is a **fitness-landscape change**: runs may explore differently than on 0.17, and best-scores are lower-but-honest. To restore the previous survivorship-mean behavior, set `evaluation.on_timeout: drop` (config.yaml) or `--config-override evaluation.on_timeout=drop`. Paired with honest best-score reporting: `run info` now shows the engine best (single-eval) next to a coverage-labeled post-eval mean. Document the negative-is-good caveat where `timeout_score` is used as a floor.

**Behavior change — default checkpoint cadence (U6 phase 2).** When `checkpoint_interval` is left unset, an OE run now checkpoints every `max(1, min(100, iterations//10))` iterations (previously a flat `100`), so a killed short run has a mid-run checkpoint to resume from. Explicit `checkpoint_interval` values (config.yaml or `--config-override`) are never overridden. A user diffing run directories across 0.17→0.18 will see more frequent checkpoint dirs on default short runs.

**Landing artifacts (the note must ship somewhere concrete — this repo has no `CHANGELOG.md` and no prior release-note vehicle, so an unanchored requirement would silently drop).** Per CLAUDE.md Release Checklist step 1b (README refresh for user-facing behavior changes), this note lands as: (a) a **README** v0.18.0 release/sprint-table row **plus a "Behavior changes (v0.18)" subsection** capturing both the `on_timeout=penalize` flip and the checkpoint-cadence default, refreshed on `develop` **before** the `develop`→`main` merge; and (b) the **annotated `v0.18.0` tag message** on `main`. The post-release doc-reviewer validates the README subsection (which must not be the first time the README sees these changes). Referenced by Exit Criterion 1.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **`core/run.py` is the highest-conflict file** (PR-1/2/3/4 all touch it, different regions). | High | Serialize the semantic chain (PR-1 → PR-2 → PR-3/4); route `core/run.py` edits through one agent; each PR rebases on the prior. |
| **U13 default flip changes the fitness landscape** — silent for a user re-running an old config. | High | Mandatory release note + `evaluation.on_timeout=drop` escape hatch; spec-before-code FR captures the normative change; a joint validation re-run (engine-penalized vs post-eval mean) recommended before tag. |
| **367→368 strict order** — 368's display consumes 367's coverage keys; landing 368 first would render undefined keys. | Medium | Hard PR dependency (PR-2 blocked until PR-1 merges); the internal 3-commit order of 367 (display guard **before** coverage keys) is enforced so the sum-path never inflates the score mid-migration. |
| **U4 `None`-sentinel refactor** touches the CLI default + `RunConfig.backend` + resolution reorder — a regression here mis-resolves the backend on every run. | Medium | Recon-confirmed contradiction (fact 5) captured in S18-09; resume path (already `None`-modelled) is the reference; dedicated 3-way resolution + mismatch-warn tests (S18-10). |
| **Migration v14 mis-sequenced or missing the global-DB no-op** corrupts the upgrade path. | Low | One-column discipline; guard on `problem_versions` table presence (v10/v12/v13 pattern); dedicated `test_db_migration_v14_*` mirroring v13. |
| **#320 not reproducible** (qwen15 possibly deleted, per the gemma4:8b precedent). | Medium | Model-independent stall-repro vector (no-LLM-timeout via stalling fake endpoint); timebox; a documented non-repro + the reap-hardening defensive fix is an acceptable outcome. |
| **Top-N OE temptation** — shipping OE top-N now would bake the sum-of-metrics ordering #367 is changing. | Low | Explicitly OUT (top_n_extraction=False on OE); documented deferral; ship Shinka-only + the CLI gate. |
| **#355/#356 collide on the tuning guide.** | Low | Sequence PR-9 (restructure) before PR-8's stamp (S18-23); flagged in the graph. |

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / Y integration tests passing (baseline 1471; ~1487+ expected)

### Demo-able features
- [ ] U13 — timed-out instances penalized by default; `on_timeout=drop` restores 0.17
- [ ] U11 — `run info` shows engine best (single-eval) next to honest coverage-labeled post-eval mean
- [ ] U4 — `version create --backend shinka` then `run` (no `--backend`) resolves Shinka from the version; mismatch warns
- [ ] U8 — seed missing a declared feature metric fails at pre-flight, not mid-run
- [ ] U6 phase 2 — default ≤100-iter run has a mid-run checkpoint to resume from
- [ ] Top-N — `solution extract --rank 2` promotes the 2nd-best Shinka program; OE clear "not supported"
- [ ] Reap hardening — grandchild reap via recursive/killpg
- [ ] Doc anti-rot — command-lint CI test + freshness stamps + backend-neutral tuning guide

### #320 spike verdict
- Repro outcome / root cause / recommendation:

### Carry-over
- OE top-N (post-#367) → S19
- #357 executable e2e + generated CLI reference → S19 (reuses the #354 CLI-tree walker)
- U9 per-arm bandit prior (#371) → upstream, demand-gated
- Any tasks not completed within this sprint's waves
