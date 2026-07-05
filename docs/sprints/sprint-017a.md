# Sprint 017a — Corrective: v0.17 Demo Feedback (eval teardown + papercuts)

**Status**: Planning
**Target release**: **v0.17.1** (defensive hotfix — Hotfix Process per CLAUDE.md; branch `hotfix/v0.17.1` off `develop`)
**Goal**: Ship the *defensive* slice of the `revolver-demos` v0.17.0 feedback triage (U1–U14). The load-bearing fix is the `infra/evaluator_runner.py` rewrite that closes U12 (post-run-eval `ProcessPoolExecutor` workers abandoned on timeout — one leaked grinder per timed-out instance) **together with** U14 (no BLAS thread-cap → oversubscription → the false 300 s timeouts that feed the leak). Both halves ship in one pass because each is unsafe alone. Around that load-bearing PR, a papercuts PR clears seven low-risk 🟠/🟡 items (U1, U2, U3, U5, U6-warn, U7-residual, U10) plus the U9 doc guidance. **Zero semantic change to scores, fitness, or display.**
**Demo**: the reporter's gen142 champion program, re-scored via `revolver eval`, completes **~10/10 instances in 7–116 s each** (was 0/10, 23–68 min survivor grinders); a real `--backend shinka` smoke run confirms **M1 ensemble→bandit / M3 `--llm-weight` / M4 `cost_aware_coef=0` / PID-aware lock** all still work; `revolver run … --dry-run` surfaces resolved `prior_probs`/`cost_aware_coef`; a `--selection-kwarg adaptive_scale=false` is now coerced to `False` (was silently `True`) and a garbage kwarg fails at `--dry-run` instead of at launch.
**Source**: [triage-feedback-v017.md](../analysis/triage-feedback-v017.md) — §1 (corrected eval-cluster causal graph), §2 (the 0.17.1 defensive slice + per-task patch sketches), the do-not-regress list. Upstream feedback: `revolver-demos/feedback/feedback-v0.17.md` (U1–U14). Scope split arbitrated by Mathieu (session 057).
**Predecessor**: Sprint 017 (v0.17.0 — multi-LLM ensemble validated end-to-end). This is a corrective patch on top of the *validated* release.

> **Do-not-regress list** (verified working in 0.17.0 — no task below touches these): **M1** Shinka
> ensemble→bandit, **M3** `--llm-weight`, **M4** `cost_aware_coef=0` auto-injection, **B6**
> `REVOLVER_HOME`, PID-aware self-healing run lock, Shinka placeholder key for key-less local
> endpoints. The `InstanceTestResult` contract (statuses, timeout message, error strings) must stay
> **byte-identical**. **No wrapper-template edits** this sprint — U13 rewrites those same lines in
> v0.18.

---

## Severity triage (defensive slice only)

Severity: 🔴 blocking · 🟠 important · 🟡 minor · ⚪ cosmetic/docs. Full triage (all 14 U-items, corrected root causes, adversarial counter-review) lives in [triage-feedback-v017.md](../analysis/triage-feedback-v017.md).

| Item | Sev | Corrected root cause (triage §1/§0) | Backlog | PR |
|---|---|---|---|---|
| **U12** | 🔴 | `run_instance` enforces the per-instance timeout with `future.result(timeout)` and **abandons** the pool worker (`future.cancel()` is a no-op on a running future). One live worker leaks per timed-out instance. Funnels through **post-run eval, `revolver eval`, `benchmark`, `problem test`, preflight**. `status='completed'`/lock-removal/"completed" print all happen **before** teardown syncs against the abandoned workers. | 358, 359 | PR-A, PR-B |
| **U14** | 🟠 | Zero thread-cap handling anywhere in Revolver's eval paths — children inherit uncapped BLAS on all cores → oversubscription → the false 300 s timeouts that each feed a U12 leak (positive feedback loop). | 358 | PR-A |
| **U1** | 🟠 | `--selection-kwarg` strings reach the sampler un-coerced → launch `TypeError`; plus a silent `bool()` inversion (`adaptive_scale=false` → `True`). | 360 | PR-C |
| **U2** | 🟠 | OE key-less local ensemble members crash at init (intra-OE parity gap vs the single-LLM path, #115); bonus: `api_key=None` makes the SDK silently send ambient `OPENAI_API_KEY` to the local bridge. | 361 | PR-C |
| **U3** | 🟡 | Repeatable `key=value` option token mistaken for a subcommand → misleading error. Generic to every group. | 362 | PR-C |
| **U5** | 🟡 | OE root-level dead keys: `problem version create` HAS warned since S9a, but there is no re-validation at run/dry-run/resume. | 363 | PR-C |
| **U6** | 🟡 | Completion checkpoint IS written at `interval == iterations`; real gap is zero *mid-run* checkpoints for the whole ≤100-iteration default regime → a killed run can't be resumed. **Phase 1 (warn) only** this sprint. | 364 | PR-C |
| **U7** | 🟡 | Member-path `reasoning_efforts` warnings shipped in 0.17 W2a; residual hole is the config.yaml/`--config-override` path (warns nothing) for local/bridge fleets. | 365 | PR-C |
| **U10** | 🟡 | `prior_probs`/bandit kwargs ARE built in `build_config` (dry-run-reachable); `resolved_config()` just never extracts them. | 366 | PR-C |
| **U9** | ⚪ | Genuine **upstream** gap (shinka 0.0.7 has no per-arm prior). **Doc part only** this sprint. | 371 | PR-C |

**Explicitly out of scope (deferred to v0.18 / S18+):** U13 (367, honest timeout semantics — rewrites the wrapper templates), U11 (368, honest best-score display — after U13), U4 (369, persist backend on problem version — migration v14), U8 (370, `validate_seed_metrics()`), U6 **phase-2** default cadence (part of 364, v0.18), and the **recursive-descendant + `killpg` reap hardening in `base.py`** (PID-reuse races — v0.18). See triage §3/§4.

---

## Scope

### In scope

| Scope | Item | Backlog | Content |
|---|---|---|---|
| **CORE-1 — eval teardown rewrite (load-bearing)** | U12 kill + U14 caps | 358 | Replace the per-instance `ProcessPoolExecutor` in `run_instance` (`infra/evaluator_runner.py:67-121`) with a **spawn-context** `mp.Process`: child `os.setsid()` first, applies the thread-cap env **before** importing the evaluator; parent polls a result queue against a deadline (no join-first); on deadline `killpg(SIGTERM)` → 3 s grace → `SIGKILL` (single-PID fallback if `getpgid` fails). Thread caps = 9-var family mirroring Shinka's scheduler + `OMP_DYNAMIC/MKL_DYNAMIC=FALSE`, `OMP_WAIT_POLICY=PASSIVE`; priority explicit-arg > `REVOLVER_EVAL_NUM_THREADS` (0 = uncapped) > default `max(1, cpu//2)`; inject nothing if the user already set any cap var. Hoist `core/eval.py:_global_eval_worker` (nested at `:215`) to module level (unpicklable under spawn) and route the legacy global aggregation through the same killable primitive. `InstanceTestResult` byte-identical. |
| **CORE-2 — finalize backstop** | U12 residual | 359 | Never-raising **direct-children** reap in `launch_run` between the `_post_run_evaluation` call (`core/run.py:996`) and `remove_run_lock` (`:1042`), mirrored in `resume_run` (`:1673`→`:1717`); "completed" messaging emitted **only after** teardown. Kept minimal (no `base.py` recursive/killpg hardening — v0.18). |
| **CORE-3 — papercuts** | U1, U2, U3, U5, U6-warn, U7-residual, U10 | 360–366 | Seven small, zero-semantic-change fixes (detail cards below). |
| **DOC — U9 guidance + eval-teardown docs** | U9 doc, REVOLVER_EVAL_NUM_THREADS, known-issues | 371 (+358/359 doc) | Extend the FACT-B warning + tuning-guide note ("short runs → `--selection fixed`"); document `REVOLVER_EVAL_NUM_THREADS`; a known-issues paragraph on engine-score semantics (interim U11/U13 mitigation: "re-score the saved best for reporting"); light DES-005 §7 teardown + FR-RUN-019 touchpoints. |

### Explicitly out of scope

| Deferred item | Backlog | Why deferred |
|---|---|---|
| U13 — honest timeout semantics (default flips to penalize) | 367 | Rewrites BOTH wrapper templates + fitness-landscape change → v0.18 semantic slice; needs the sum→`combined_score` display guard first. |
| U11 — honest best-score display | 368 | Consumes U13's coverage keys; strict order U13 → U11 → v0.18. |
| U4 — persist backend on problem version | 369 | Needs migration v14; v0.18. |
| U8 — `validate_seed_metrics()` backend hook | 370 | Pre-flight validation feature; v0.18. |
| U6 phase-2 smarter default cadence | 364 (part) | Fitness/cadence behavior change; v0.18. Only the phase-1 **warn** ships here. |
| Recursive-descendant + `killpg` reap hardening in `base.py` | — | PID-reuse races; the Shinka single-PID grandchildren caveat — v0.18 only if evidence of need. |

---

## Prioritization

| Priority | Scope | Rationale |
|---|---|---|
| **Must-do** | CORE-1 (U12+U14, 358) | The only 🔴 with a proven, reproducible incident (0/10 instances, 45-min grinder survivor spread). Kill-without-caps still falsely times out the champion; caps-without-kill still leaks on genuinely slow evals — **one rewrite, one PR**. Blast radius = all five eval paths. |
| **Must-do** | CORE-2 (U12, 359) | Belt to CORE-1's braces: catches any child that outlives per-instance kill and stops the "completed" print from racing abandoned workers. Correctly *sized* only once CORE-1's source-kill exists. |
| **Should-do** | CORE-3 U1 (360), U2 (361) | The two 🟠 papercuts: a launch-time `TypeError` + silent bool inversion, and a key-less-local ensemble crash + ambient-key leak. |
| **Should-do** | CORE-3 U3/U5/U6/U7/U10 (362–366) | 🟡 friction removers; each S-effort, low risk, zero semantic change. |
| **Nice-to-have** | DOC (U9, 371 + teardown docs) | Doc-only; the U9 upstream gap gets interim guidance, the new env var and engine-score caveat get documented. |

---

## Anomaly detail cards

### U12 🔴 — "completed" run leaks eval workers *(corrected: Revolver's own post-run-eval workers, not Shinka)*

- **Observed** (reporter): after a champion run printed "completed", `ps` showed 6 surviving eval-worker children (`STAT=Rl`, 237–454 % CPU each, load avg 124), ages spread 23–68 min — 10 workers abandoned in total (one per timed-out instance), 6 still alive at observation.
- **Corrected root cause** (triage §1): `infra/evaluator_runner.py:run_instance` enforces the per-instance timeout with `future.result(timeout)` and on timeout **abandons** the `ProcessPoolExecutor` worker — `future.cancel()` is a no-op on a running future and `shutdown(wait=False, cancel_futures=True)` never signals worker processes. The champion's post-run eval ran 10 sequential instances at 300 s (`core/run.py:1191-1196`), all timing out (U14) → workers abandoned 300 s apart → the observed spread. **The Shinka evolution-phase wrapper's per-instance kill works** (`shinka.py:338-346`); this is Revolver's own eval primitive. Affects **post-run eval, `revolver eval`, `benchmark`, `problem test`, run preflight** — all funnel through `run_instance`.
- **Why #224 missed it**: the only reap (`ChildProcessReaperMixin`) runs inside `launch()`'s `finally` — **before** `_post_run_evaluation` — and enumerates direct children only. Ordering, not a broken reap.
- **Fix**: PR-A (kill at source) + PR-B (finalize backstop). See CORE-1/CORE-2.
- **Backlog**: 358 (PR-A), 359 (PR-B).

### U14 🟠 — post-run eval doesn't cap BLAS threads

- **Confirmed**: Shinka's scheduler injects a full numeric-thread-cap env family into evolution-phase eval subprocesses (`shinka/launch/scheduler.py:178-202`); Revolver's `run_instance` sets none → children inherit uncapped BLAS on all cores. A program evolved/selected under a 4-thread cap, then scored uncapped → oversubscription → false 300 s timeouts → each feeds a U12 leak.
- **Fix**: shipped inside the same `run_instance` rewrite (PR-A). Priority: explicit arg > `REVOLVER_EVAL_NUM_THREADS` (0 = uncapped) > default `max(1, cpu//2)`; **inject nothing if the user already set any cap var** (preserves the reporter's `OMP_NUM_THREADS=2` workaround). One stderr line announcing the cap.
- **Backlog**: 358 (PR-A).

### U1 🟠 — `--selection-kwarg` values un-coerced (+ silent bool inversion)

- **Confirmed**: strings reach the sampler un-coerced → launch `TypeError`; plus an unreported `bool("false") == True` inversion (`adaptive_scale=false` → `True`).
- **Fix**: `parsed[key] = _parse_value(value.strip())` in `_parse_selection_kwargs` (`core/run.py:140`, covers both call sites `:716`/`:1461`) + fail-fast residual strings in `_route_selection_kwargs` → garbage now fails at `--dry-run`. Update the 2 unit assertions codifying the bug (`test_core_run.py:3213-3214`). (`_parse_value` promotion to a shared module → v0.18.)
- **Backlog**: 360 (PR-C).

### U2 🟠 — OE key-less local ensemble members crash at init

- **Confirmed**: intra-OE parity bug vs the single-LLM path (#115); `api_key=None` also makes the SDK silently send ambient `OPENAI_API_KEY` to the local bridge.
- **Fix**: `elif member_llm.source == "local": entry["api_key"] = "ollama"` in `_build_ensemble_llm_config` (mirror `openevolve.py:675-678`). Closes the ambient-key leak.
- **Backlog**: 361 (PR-C).

### U3 🟡 — repeatable `key=value` option mistaken for a subcommand

- **Confirmed**: generic to `--config-override`/`--selection-kwarg`/`--llm-weight` on every group.
- **Fix**: `GlobalOptionGroup.resolve_command` override — targeted hint when an unknown "subcommand" token contains `=`, composed with `super()` to keep typer's did-you-mean.
- **Backlog**: 362 (PR-C).

### U5 🟡 — OE root-level dead keys not re-validated at run

- **Corrected**: `problem version create` HAS warned since S9a (one-shot); the gap is no re-validation at run/dry-run/resume.
- **Fix**: re-validate the snapshot `config.yaml` at run/dry-run/resume entry via `backend.validate_config()` (config-file analogue of B9 #350), **warn-only**.
- **Backlog**: 363 (PR-C).

### U6 🟡 — `checkpoint_interval` ≥ iterations unrecoverable *(phase-1 warn only)*

- **Corrected**: a completion checkpoint IS written at `interval == iterations`; the real gap is zero *mid-run* checkpoints for the ≤100-iteration default regime.
- **Fix (phase 1)**: warn when the *final* interval ≥ effective iterations ("no mid-run checkpoint will exist; a killed run cannot be resumed"); keep the S9a `>` guard **verbatim**. Phase-2 smarter default cadence → v0.18.
- **Backlog**: 364 (PR-C; the `/ v0.18 default` part stays open).

### U7 🟡 — `reasoning_efforts` inert-warning hole on the config path

- **Corrected**: member-path warnings + docs already shipped in 0.17 W2a; residual hole is config.yaml/`--config-override`.
- **Fix**: fire the local-inert warning also when `reasoning_efforts` arrives via config.yaml/`--config-override` on a local/bridge fleet (post-override check in `build_config`, Shinka).
- **Backlog**: 365 (PR-C).

### U10 🟡 — dry-run hides `prior_probs`/bandit kwargs

- **Corrected**: values ARE built in `build_config` (dry-run-reachable); `resolved_config()` never extracts them.
- **Fix**: add `llm_dynamic_selection_kwargs` to `ShinkaBackend.resolved_config()` backend_extras (surfaces `prior_probs`, the M4-injected `cost_aware_coef`, merged overrides in one line) + zip `prior_probs` into `llm_models` entries as weights for the existing dry-run renderer.
- **Backlog**: 366 (PR-C).

### U9 ⚪ — bandit ignores ensemble weights *(doc part only)*

- **Confirmed upstream gap**: shinka 0.0.7 has no per-arm prior (UCB none; Thompson scalars broadcast uniformly). Upstream feature is demand-gated (S18+).
- **Fix (doc)**: extend the FACT-B warning with guidance ("short runs → `--selection fixed` to apply weights; shinka samplers expose no per-arm prior") + tuning-guide note.
- **Backlog**: 371 (PR-C; the `/ S18+ upstream` part stays open).

---

## Tasks

| # | Task | Layer | PR | Depends | Acceptance criteria |
|---|---|---|---|---|---|
| S17a-01 | **U12 kill** — rewrite `run_instance` (`infra/evaluator_runner.py:67-121`) onto a **spawn-context** `mp.Process`: child `os.setsid()` first; parent polls a result queue against a deadline (no join-first); on deadline `killpg(SIGTERM)` → 3 s grace → `SIGKILL`, single-PID fallback when `getpgid` raises. Keep `InstanceTestResult` construction byte-identical (statuses `pass`/`fail`/`timeout`, timeout message, error strings). | infra | PR-A | — | A deliberately-hung evaluator instance is killed at the deadline and **no child survives** the call (assert via PID/pgid probe); a passing instance returns the same `InstanceTestResult` as the pre-rewrite path; the timeout `InstanceTestResult` message string is unchanged. |
| S17a-02 | **U14 caps** — in the same rewrite, apply the 9-var BLAS thread-cap family + `OMP_DYNAMIC/MKL_DYNAMIC=FALSE` + `OMP_WAIT_POLICY=PASSIVE` in the child **before** importing the evaluator. Priority: explicit arg > `REVOLVER_EVAL_NUM_THREADS` (`0` = uncapped) > default `max(1, cpu//2)`. If **any** cap var already exists in the parent env → inject nothing. One stderr line announces the applied cap. | infra | PR-A | S17a-01 | Default injects `max(1, cpu//2)` and prints one cap line; `REVOLVER_EVAL_NUM_THREADS=3` → caps at 3; `REVOLVER_EVAL_NUM_THREADS=0` → uncapped; pre-set `OMP_NUM_THREADS=2` in the parent env → Revolver injects **nothing** (workaround preserved). |
| S17a-03 | **Hoist `_global_eval_worker`** — move `core/eval.py:_global_eval_worker` (nested at `:215`) to module level (unpicklable under spawn) and route the legacy global-aggregation path (`core/eval.py:234`) through the same killable spawn primitive as S17a-01. | infra | PR-A | S17a-01 | `_global_eval_worker` is importable at module level and picklable under `spawn`; the legacy `evaluate()` global-aggregation path (`FR-EVL-019/020`) still returns `user_aggregates` unchanged and is now kill-on-timeout. |
| S17a-04 | **PR-A tests (L1/L2)** — kill-on-timeout leaves no live child (killpg + single-PID fallback); cap-injection precedence (explicit/env/default/respect-user-env); contract byte-identical; legacy global-aggregation kill path. Accept the ~30–90 s suite slowdown (spawn ~0.5 s/child). | test | PR-A | S17a-01..03 | New tests in `tests/test_evaluator_runner.py` + `tests/integration/test_eval.py` cover all seven scenarios below; full suite green (no-shinka env). |
| S17a-05 | **PR-A docs** — document `REVOLVER_EVAL_NUM_THREADS` (README + `docs/guides/tuning-oe-config.md`); add the DES-005 §7 teardown note + FR-RUN-019 touchpoint (post-run eval now kills-on-timeout + thread-caps). | doc | PR-A | S17a-01..02 | README + tuning guide mention `REVOLVER_EVAL_NUM_THREADS` (0=uncapped, default `cpu//2`, respect-user-env); DES-005 §7 + FR-RUN-019 reference the killable eval primitive; doc-reviewer reports 0 FAIL on the touched sections. |
| S17a-06 | **U12 backstop** — never-raising direct-children reap in `launch_run` between `_post_run_evaluation` (`core/run.py:996`) and `remove_run_lock` (`:1042`), mirrored in `resume_run` (`:1673`→`:1717`); move the "completed" messaging to **after** teardown. Minimal — no `base.py` recursive/killpg hardening (v0.18). Must not disturb the PID-aware self-healing lock. | domain | PR-B | S17a-01 (semantics) | On a mocked run that leaks one direct child through post-run eval, the child is reaped before `remove_run_lock`; the reap never raises; "completed" is printed only after teardown; the run result in the DB is intact; PID-aware lock behavior unchanged. |
| S17a-07 | **PR-B test (L2)** — assert the backstop reaps a leaked direct child before lock removal and that "completed" is printed after teardown. | test | PR-B | S17a-06 | `test_launch_run_finalize_backstop_reaps_before_lock` + `test_launch_run_completed_message_after_teardown` pass; existing lock/resume tests unaffected. |
| S17a-08 | **U1 (360)** — `parsed[key] = _parse_value(value.strip())` in `_parse_selection_kwargs` (`core/run.py:140`, both call sites) + fail-fast residual strings in `_route_selection_kwargs`. Update the 2 assertions at `test_core_run.py:3213-3214` that codified the bug. | domain | PR-C | — | `--selection-kwarg cost_aware_coef=0.3` yields float `0.3`; `adaptive_scale=false` yields `False` (was `True`); a non-parseable residual string fails at `--dry-run` with a clear error; the 2 stale assertions are updated to the corrected behavior. |
| S17a-09 | **U2 (361)** — `elif member_llm.source == "local": entry["api_key"] = "ollama"` in `_build_ensemble_llm_config` (`openevolve.py`, mirror `:675-678`). | infra | PR-C | — | A key-less local ensemble member builds an OE config with `api_key="ollama"` (no init crash); no ambient `OPENAI_API_KEY` is forwarded to the local endpoint; remote members unaffected. |
| S17a-10 | **U3 (362)** — `GlobalOptionGroup.resolve_command` override emitting a targeted hint when an unknown "subcommand" token contains `=`; compose with `super()` to keep typer's did-you-mean. | cli | PR-C | — | `revolver run foo=bar` prints a hint naming the likely intended repeatable option; a genuine unknown subcommand still gets typer's did-you-mean; covers `run`/`llm`/other groups. |
| S17a-11 | **U5 (363)** — re-validate the snapshot `config.yaml` at run/dry-run/resume entry via `backend.validate_config()`, warn-only. | domain | PR-C | — | A snapshot config with a dead OE key warns on stderr at `run`, `--dry-run`, and `resume`; the run still proceeds (warn-only); a clean config warns nothing. |
| S17a-12 | **U6 phase-1 (364)** — warn when the *final* `checkpoint_interval` ≥ effective iterations ("no mid-run checkpoint; a killed run cannot be resumed"); keep the S9a `>` guard verbatim. | domain | PR-C | — | `--iterations 50` with an effective interval of 50 (or larger) warns; an interval of 10 does not; the existing S9a `>` guard/error path is unchanged. |
| S17a-13 | **U7 residual (365)** — fire the local-inert `reasoning_efforts` warning also when it arrives via config.yaml/`--config-override` on a local/bridge fleet (post-override check in `build_config`, Shinka). | infra | PR-C | — | A Shinka run on an all-local fleet with `reasoning_efforts` set via `--config-override` warns it is inert; the member-path warning (0.17 W2a) still fires; a reasoning-capable remote fleet warns nothing. |
| S17a-14 | **U10 (366)** — add `llm_dynamic_selection_kwargs` to `ShinkaBackend.resolved_config()` backend_extras + zip `prior_probs` into `llm_models` entries as weights for the dry-run renderer. | infra | PR-C | — | `run … --backend shinka --dry-run` surfaces `prior_probs`, the M4-injected `cost_aware_coef`, and merged overrides in `backend_extras`; per-member weights appear next to `llm_models`; single-LLM dry-run output unchanged. |
| S17a-15 | **PR-C tests (L2)** — one scenario per papercut (U1 coercion + fail-fast, U2 placeholder key, U3 hint, U5 re-validate warn, U6 interval warn, U7 config-path inert warn, U10 dry-run surfacing). | test | PR-C | S17a-08..14 | All eight papercut test IDs pass; no regression on existing run/dry-run/ensemble tests. |
| S17a-16 | **U9 doc (371) + known-issues** — extend the FACT-B warning + tuning-guide note ("short runs → `--selection fixed`; shinka samplers expose no per-arm prior"); add a known-issues paragraph on engine-score semantics (interim U11/U13 mitigation: "re-score the saved best for reporting"). | doc | PR-C | — | The FACT-B warning carries the short-run guidance; the tuning guide + a known-issues section document the per-arm-prior gap and the re-score-for-reporting workaround; doc-reviewer reports 0 FAIL on the touched sections. |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md` (§2.5 `run`, §2.6 `eval`, `problem test`) plus new IDs introduced here that must pass at sprint end.

| Area | Scenario | Test ID | Status |
|---|---|---|---|
| U12 kill | Hung instance killed at deadline; no child survives the call (killpg path) | `test_run_instance_kills_on_timeout` | Planned |
| U12 kill | `getpgid` failure → single-PID kill fallback still terminates the child | `test_run_instance_single_pid_fallback` | Planned |
| U14 caps | Default injects `max(1, cpu//2)` + one stderr cap line | `test_run_instance_thread_cap_default` | Planned |
| U14 caps | `REVOLVER_EVAL_NUM_THREADS` honored (incl. `0` = uncapped) | `test_run_instance_thread_cap_env_override` | Planned |
| U14 caps | Any pre-set cap var in parent env → Revolver injects nothing | `test_run_instance_thread_cap_respects_user_env` | Planned |
| U12/U14 contract | `InstanceTestResult` statuses / timeout message / error strings byte-identical | `test_run_instance_result_contract_byte_identical` | Planned |
| U12 legacy path | Legacy global `evaluate()` aggregation runs through the killable primitive; `user_aggregates` unchanged | `test_global_eval_worker_module_level_killable` | Planned |
| U12 acceptance (demo) | Reporter's gen142 program re-scored via `revolver eval` → ~10/10 in 7–116 s/instance | manual demo (revolver-demos env) | Planned |
| U12 backstop | Leaked direct child reaped between post-run eval and lock removal | `test_launch_run_finalize_backstop_reaps_before_lock` | Planned |
| U12 backstop | "completed" printed only after teardown | `test_launch_run_completed_message_after_teardown` | Planned |
| U1 | `--selection-kwarg` values coerced (`0.3`→float, `false`→`False`) | `test_selection_kwarg_value_coercion` | Planned |
| U1 | Non-parseable residual kwarg fails at `--dry-run` | `test_selection_kwarg_residual_string_fails_fast` | Planned |
| U2 | Key-less local OE ensemble member gets `api_key="ollama"`; no ambient key forwarded | `test_oe_ensemble_local_member_placeholder_key` | Planned |
| U3 | Unknown `foo=bar` token → targeted repeatable-option hint | `test_unknown_subcommand_equals_token_hint` | Planned |
| U5 | Snapshot config dead key warns at run/dry-run/resume (warn-only) | `test_run_revalidates_snapshot_config_warns` | Planned |
| U6 | Final `checkpoint_interval` ≥ iterations warns | `test_checkpoint_interval_ge_iterations_warns` | Planned |
| U7 | `reasoning_efforts` via config/override on a local fleet → inert warning | `test_shinka_reasoning_efforts_config_path_inert_warns` | Planned |
| U10 | `--dry-run` surfaces `prior_probs`/`cost_aware_coef` in backend_extras | `test_shinka_dry_run_surfaces_selection_kwargs` | Planned |
| Non-regression | Real `--backend shinka` smoke run: M1 ensemble→bandit / M3 `--llm-weight` / M4 `cost_aware_coef=0` / PID-aware lock all still work | manual smoke (shinka env) | Planned |
| Non-regression | Full existing suite (~1316+ baseline) passes on the no-shinka env | full suite regression | Planned |

**Test count planned**: **17 new automated L2 test IDs** (7 PR-A, 2 PR-B, 8 PR-C) + **1 demo acceptance** (gen142 re-score) + **1 Shinka smoke** (do-not-regress gate) + full-suite regression.

---

## Parallelization

### Dependency graph

```
hotfix/v0.17.1 branched from develop
        │
        ├──> PR-A (CORE-1: U12 kill + U14 caps)      ← load-bearing; files: evaluator_runner.py, core/eval.py
        │        S17a-01 (spawn mp.Process + killpg)
        │            └─> S17a-02 (thread-cap family)
        │            └─> S17a-03 (hoist _global_eval_worker)
        │                 └─> S17a-04 (PR-A tests)
        │                 └─> S17a-05 (PR-A docs: REVOLVER_EVAL_NUM_THREADS + DES-005/FR-RUN-019)
        │
        ├──> PR-C (CORE-3 papercuts + U9 doc)         ← PARALLEL with PR-A (disjoint code files)
        │        S17a-08 (U1)  ── core/run.py
        │        S17a-09 (U2)  ── openevolve.py        ┐
        │        S17a-10 (U3)  ── cli global options   │ mutually independent
        │        S17a-11 (U5)  ── core/run.py          │ (share core/run.py & shinka.py
        │        S17a-12 (U6)  ── core/run.py          │  within the SAME PR/agent)
        │        S17a-13 (U7)  ── shinka.py            │
        │        S17a-14 (U10) ── shinka.py            ┘
        │            └─> S17a-15 (PR-C tests)
        │            └─> S17a-16 (U9 doc + known-issues)
        │
        └──> PR-B (CORE-2: finalize backstop)          ← depends on PR-A SEMANTICS; files: core/run.py
                 S17a-06 (backstop reap + "completed" ordering)
                     └─> S17a-07 (PR-B test)
```

### Critical path

```
S17a-01 → S17a-02 → S17a-03 → S17a-04  (PR-A merge)  →  S17a-06 → S17a-07  (PR-B merge)  →  regression + release
```

PR-A is the deepest chain and the load-bearing rewrite; PR-B follows it because the backstop is only correctly *sized* once the source-kill lands (belt-to-braces). **PR-C runs fully in parallel with PR-A** and is off the critical path.

### PR structure — validated / amended

| PR | Backlog | Files (primary) | Independence |
|---|---|---|---|
| **PR-A** | 358 | `infra/evaluator_runner.py`, `core/eval.py`, `tests/test_evaluator_runner.py`, `tests/integration/test_eval.py`, README + tuning guide + DES-005 §7 / FR-RUN-019 | The load-bearing rewrite — U12 kill + U14 caps ship **together** (each half unsafe alone). **Kept free of `core/run.py`** so it parallelizes cleanly with PR-C. |
| **PR-B** | 359 | `core/run.py` (`launch_run` + `resume_run` teardown tail) | **Separate PR** (recommended below), sequenced **after** PR-A. |
| **PR-C** | 360–366, 371 | `core/run.py` (U1/U5/U6), `infra/backends/openevolve.py` (U2), `infra/backends/shinka.py` (U7/U10), CLI global options (U3), README/guide docs (U9 + known-issues) | Parallel with PR-A (disjoint code files). |

**PR-B decision — separate PR, not a second commit of PR-A (recommended):**
1. **Preserves the valuable parallelism.** Folding 359 into PR-A would pull `core/run.py` into the load-bearing rewrite, colliding with PR-C's `core/run.py` items (U1/U5/U6) and defeating the "PR-A ∥ PR-C by two worktree agents" plan. PR-A stays confined to `evaluator_runner.py`/`core/eval.py`.
2. **Correct sequencing is expressible.** PR-B depends on PR-A's *semantics* (source-kill must exist before the backstop is minimally sized) — a dependent PR captures that; a same-PR commit would also work but forces the file collision above.
3. **Isolates a delicate lifecycle reorder.** Moving "completed" messaging after teardown, between `_post_run_evaluation` and `remove_run_lock`, and not disturbing the PID-aware lock, is worth reviewing on its own small diff.
*Alternative considered (fold into PR-A as commit 2): rejected only because of the `core/run.py`↔PR-C collision; if the team prefers a single U12 PR, do it and route PR-C's `core/run.py` items through the same agent to serialize the edits.*

**PR-C decision — one papercuts PR (recommended), with a documented fallback split:**
- Seven S-effort items, all "zero semantic change", share the defensive-hotfix framing → one coherent review, mirrors S16a's bundled PR-DOC / PR-A6+A3 precedent.
- **Fallback split if the diff exceeds a review-comfortable size:** PR-C1 = run-path validation (S17a-08 U1, S17a-11 U5, S17a-12 U6 — all `core/run.py`); PR-C2 = backend/CLI/dry-run + docs (S17a-09 U2, S17a-10 U3, S17a-13 U7, S17a-14 U10, S17a-16 U9). This split is file-clean (`core/run.py` on one side, backends/CLI/docs on the other).

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — eval teardown rewrite (CORE-1) | S17a-01..05 | `hotfix/v0.17.1` HEAD | Agent 1 (owns the load-bearing rewrite) |
| C — papercuts + U9 doc (CORE-3) | S17a-08..16 | `hotfix/v0.17.1` HEAD | Agent 2 |
| B — finalize backstop (CORE-2) | S17a-06..07 | PR-A merged | Agent 1 (reuses eval-teardown context) |

Peak parallelism: **2 agents** (Streams A and C) from sprint start. Stream B follows PR-A. Stream C may internally use a second agent split by file (backends/CLI vs `core/run.py`) for a peak of 3 if desired, but the items are small enough for one.

### Merge order & conflict risks

**Recommended merge order:** PR-A → PR-C → PR-B (PR-B rebases last, on top of PR-C's `core/run.py` edits).

- **`core/run.py`** — touched by **PR-B** (`launch_run`/`resume_run` teardown tail, ~`:1042`/`:1717`) and **PR-C** (U1 `_parse_selection_kwargs` ~`:140`/`:716`/`:1461`, U5 run/dry-run/resume entry, U6 checkpoint-interval warn). **Different functions/regions → low-but-nonzero conflict.** Mitigation: land PR-C before PR-B; PR-B rebases on develop that already carries PR-C. If run concurrently, route PR-B and PR-C's `core/run.py` items through the **same agent** (S16a P9 pattern).
- **`docs/guides/tuning-oe-config.md`** + **README.md** — touched by **PR-A** (`REVOLVER_EVAL_NUM_THREADS`) and **PR-C** (U9 guidance + known-issues). **Moderate** — different sections; land PR-A's doc edits first or coordinate the guide section boundaries.
- **`infra/backends/shinka.py`** — PR-C only (U7 `build_config` + U10 `resolved_config`), same PR/agent → no cross-PR conflict.
- **`infra/backends/openevolve.py`** — PR-C only (U2). No conflict.
- **`infra/evaluator_runner.py` + `core/eval.py`** — PR-A only. No conflict.
- **No wrapper-template edits anywhere** — `openevolve.py`/`shinka.py` `_WRAPPER_TEMPLATE` aggregation lines are U13's (v0.18); PR-C's `openevolve.py`/`shinka.py` edits stay in `_build_ensemble_llm_config`/`build_config`/`resolved_config`, never the templates.

---

## Exit criteria

The sprint is complete when ALL of the following hold:

1. **U12+U14 (PR-A)** — `run_instance` kills the child (or its process group) at the per-instance deadline with **no surviving worker**, across all five eval paths (post-run eval, `revolver eval`, `benchmark`, `problem test`, preflight); thread caps apply with the documented precedence and respect a user-set cap var; `_global_eval_worker` is module-level and killable; `InstanceTestResult` is byte-identical.
2. **Demo acceptance** — the reporter's gen142 program re-scored via `revolver eval` completes **~10/10 instances in 7–116 s each** (was 0/10) on the `revolver-demos` env.
3. **U12 backstop (PR-B)** — a leaked direct child is reaped between post-run eval and `remove_run_lock`; the reap never raises; "completed" prints only after teardown; the run result and the PID-aware lock are intact.
4. **Papercuts (PR-C)** — U1 coerces + fails-fast (bool inversion gone); U2 places the local placeholder key (no ambient-key leak); U3 hints on `=` tokens; U5 re-validates snapshot config warn-only; U6 warns on the unrecoverable interval; U7 warns on the config-path inert `reasoning_efforts`; U10 surfaces the resolved selection kwargs in dry-run.
5. **Do-not-regress green** — a real `--backend shinka` smoke run confirms **M1 / M3 / M4 / B6 / PID-aware lock / placeholder key** all still work; the full existing suite (~1316+ baseline) passes on the no-shinka env; `ruff`/`mypy` clean; CI green.
6. **Zero semantic change** — no change to scores, fitness, or displayed values; **no wrapper-template edits**.
7. **Docs** — `REVOLVER_EVAL_NUM_THREADS` documented (README + tuning guide); DES-005 §7 teardown + FR-RUN-019 touchpoints updated; U9 short-run guidance + engine-score known-issues paragraph present; post-release doc-reviewer reports 0 FAIL.

---

## Release steps (Hotfix Process — CLAUDE.md)

This is a **hotfix**, not a normal sprint release. Follow the Hotfix Process:

1. **Branch** — `git checkout -b hotfix/v0.17.1 develop`.
2. **Fix + tests** — land PR-A, then PR-C, then PR-B (rebased) per the merge order; full suite + Shinka smoke green.
3. **Draft PRs** — from the **main/orchestrator session** (`gh pr create --draft --base develop`) so the code-review hook fires; run code-reviewer **foreground**; address findings; `gh pr ready`.
4. **Light doc cascade before tag** (hotfix version — the spec surface is small: DES-005 §7 + FR-RUN-019 + README/guide `REVOLVER_EVAL_NUM_THREADS`). spec-reviewer/validation-reviewer optional given the tiny spec delta; **doc-reviewer runs post-release** (checks version numbers in README/guide).
5. **Release Checklist** — version bump `0.17.1` in **both** `pyproject.toml` and `src/revolver/__init__.py`; merge `develop` → `main`; tag `v0.17.1` on `main`; verify install + `revolver --version`; run the post-release verification block.

---

## Sprint Review

_Session 057 (2026-07-04). All 3 PRs merged: #242 (PR-A), #243 (PR-C), #245 (PR-B) — merge order A → C → B as planned, PR-B rebased on post-C develop with zero conflicts._

### Tests passing
- **20 / 17 planned** new automated tests (L1+L2) merged and green (PR-A 8 + PR-B 3 + PR-C 9 — extra: invalid-env-value cap case, U7 combo warn-once, U1 JSON-array fail-fast); full suite **1471 passed, 4 skipped** on develop after the last merge; `ruff`/`mypy` clean; CI green on all 3 PRs (one CI-only failure caught and fixed en route: the U5 test initially depended on a real openevolve install, absent from the CI main job → mocked `is_available`/`validate_config` + an install-gated twin in `test_run_oe.py`).
- Code reviews: 0 CRITICAL across the three PRs (PR-A: 1 W + 3 S; PR-B: 0 W + 3 S; PR-C: 1 W + 3 S — all findings addressed and re-pushed before ready).
- **Demo acceptance (gen142 re-score) PASSED**: `revolver eval --solution beam3-champ-sonnetheavy --dataset beamforming-eval` → **10/10 solved in 810.5 s** (was 0/10 + manual `kill -9`), per-instance `time_s` 7.9–245 s (all < 300 s timeout), cap line `numeric thread cap per eval process: 8` printed, **zero surviving eval workers** after completion. `combined_score` mean **3.29** — reproduces the reporter's thread-capped held-out reference (3.2918, +0.971) without any manual env workaround.
- **Shinka smoke (do-not-regress gate)**: not run as a live run — the claude-ollama-bridge was down at release time. Compensating coverage: the 49 install-gated Shinka tests re-run against real shinka 0.0.7 (`shinka-spike` env) during PR-C, M1/M3/M4 projection + lock tests in the suite, and the U1/U3/U9/U10 dry-run validations below exercised the real Shinka `build_config` path end-to-end. Live non-regression deferred to the next revolver-demos run on 0.17.1.

### Demo-able features
- [x] gen142 champion re-scored via `revolver eval` → **10/10** in 7.9–245 s (was 0/10; no grinder survivors)
- [~] `--backend shinka` smoke run — deferred (bridge down); covered by real-shinka test suite + dry-run validation
- [x] `REVOLVER_EVAL_NUM_THREADS` caps eval BLAS threads (default `cpu//2`=8 announced on stderr); pre-set `OMP_NUM_THREADS` respected
- [x] `--selection-kwarg` coercion: `exploration_coef=0.7`/`auto_decay=0.98` → floats at dry-run; `auto_decay=banana` → clear `ValidationError` at `--dry-run`, exit 1
- [x] Key-less local OE ensemble member no longer crashes at init; no ambient key forwarded (L2-tested)
- [x] `run … --dry-run` surfaces `llm_dynamic_selection_kwargs` incl. the M4-injected `cost_aware_coef: 0.0`
- [x] `revolver run db_config.num_islands=4` → targeted hint naming the repeatable options (`--config-override`, `--selection-kwarg`, `--llm-weight`)
- [x] FACT-B warning now carries the U9 short-run guidance ("prefer `--selection fixed`; no per-arm prior")

### Carry-over
- v0.18 semantic slice: U13 (367), U11 (368), U4 (369), U8 (370), U6 phase-2 (364 part), `base.py` recursive/killpg reap hardening
- S18+ / upstream: U9 per-arm bandit prior (371 part)
- Live Shinka smoke on 0.17.1 → next revolver-demos session
