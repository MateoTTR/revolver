# Triage — revolver-demos feedback v0.17 (U1–U14)

> **Source**: demo feedback report v0.17 (private demo repository; execution complete 2026-07-03:
> 2 smoke + 4×100-gen + 1 champion @150, zero run crashes, zero bridge wedges).
> **Method** (session 057, 2026-07-04): per-item code verification against the released v0.17.0
> (editable checkout, `develop`) and the `shinka`/`openevolve` packages in the `revolver-demos`
> conda env — one verification agent + one independent adversarial counter-review per item, plus
> an architecture pass on the interacting U11–U14 eval cluster. All 14 counter-reviews concur
> with the verification verdicts. Raw structured results archived in the session scratchpad.
>
> **Verdict vocabulary**: FIX / FIX+DOCUMENT / DOCUMENT / WONTFIX / UPSTREAM · effort S/M/L ·
> regression risk low/medium/high · train `0.17.1` (defensive patch) / `v0.18` (semantic) / `S18+`.
>
> **Do-not-regress list** (verified working in 0.17, no patch below touches these): M1 Shinka
> ensemble→bandit, M3 `--llm-weight`, M4 `cost_aware_coef=0` auto-injection, B6 `REVOLVER_HOME`,
> PID-aware self-healing run lock, Shinka placeholder key for key-less local endpoints.

---

## 0. Triage table

| # | Sev | Feedback claim | Verified | Verdict | Effort | Risk | Train |
|---|---|---|---|---|---|---|---|
| U12 | 🔴 | "completed" run leaks eval workers | **Corrected** — leak real, but the grinders are Revolver's own post-run-eval `ProcessPoolExecutor` workers abandoned on timeout, NOT Shinka evolution workers | FIX | M | medium | **0.17.1** |
| U14 | 🟠 | post-run eval doesn't cap BLAS threads | Confirmed — zero thread-cap handling anywhere in Revolver's eval paths | FIX+DOC | S | low | **0.17.1** |
| U1 | 🟠 | `--selection-kwarg` strings → launch `TypeError` | Confirmed — plus an unreported silent `bool()` inversion (`adaptive_scale=false` → `True`) | FIX | S | low | **0.17.1** |
| U2 | 🟠 | OE key-less ensemble members crash at init | Confirmed — intra-OE parity bug vs single-LLM path (#115); bonus: `api_key=None` makes the SDK silently send ambient `OPENAI_API_KEY` to the local bridge | FIX | S | low | **0.17.1** |
| U3 | 🟡 | `--config-override` grouping → misleading error | Confirmed — generic to every repeatable `key=value` option on every group | FIX | S | low | **0.17.1** |
| U5 | 🟡 | OE root-level dead keys silently ignored | **Corrected** — `problem version create` HAS warned since S9a; the gap is no re-validation at run/dry-run/resume | FIX | S | low | **0.17.1** |
| U6 | 🟡 | `checkpoint_interval` ≥ iterations unrecoverable | **Corrected** — completion checkpoint IS written at equality; real gap is zero *mid-run* checkpoints for the whole ≤100-iteration default regime | FIX+DOC | S | low | **0.17.1** warn / v0.18 default |
| U7 | 🟡 | per-member `reasoning_effort` inert on Shinka | **Corrected** — warnings + docs already shipped in 0.17 (member path); residual hole: config.yaml/`--config-override` path warns nothing | FIX+DOC | S | low | **0.17.1** |
| U10 | 🟡 | dry-run hides `prior_probs`/bandit kwargs | **Corrected** — values ARE built in `build_config` (dry-run-reachable); `resolved_config()` just never extracts them | FIX | S | low | **0.17.1** |
| U13 | 🟠 | per-instance timeout drops instances → inflated fitness | Confirmed — survivorship-biased mean in BOTH wrapper templates; even the "safe subset" needs the sum→combined_score display guard first, so nothing fits 0.17.1 | FIX | M | medium | **v0.18** |
| U11 | 🟡 | engine `best_score` not reproducible | Confirmed — engine max(combined_score) is single-eval + U13-inflated; post-run eval exists but its honest number is never displayed next to it | FIX+DOC | M | medium | **v0.18** (after U13) |
| U4 | 🟡 | `--backend` default ignores version intent | Confirmed — backend used at version-create for validation then discarded (not persisted anywhere) | FIX | M | low | **v0.18** (migration v14) |
| U8 | 🟡 | `feature_dimensions` crash if seed lacks metric | **Corrected** — crash is at `controller.run()` seed-add (not `__init__`), message actually names the key; real friction is lateness; only sound validation point is the existing pre-flight | FIX+DOC | S | low | **v0.18** |
| U9 | ⚪ | bandit ignores ensemble weights (warm-start ask) | Confirmed — genuine **upstream** gap: shinka 0.0.7 has no per-arm prior (UCB none at all; Thompson scalars broadcast uniformly) | UPSTREAM | S doc | low | 0.17.1 doc / S18+ feature |

**Feedback quality**: 8/14 confirmed as reported, 6/14 corrected on the mechanism (U5, U6, U7, U8, U10, U12) —
in every corrected case the *friction* is real but the proposed fix location changes. The U12 correction is
the load-bearing one.

---

## 1. The eval cluster (U11–U14) — corrected causal graph

- **U12 root cause (corrected)**: `infra/evaluator_runner.py:run_instance` enforces the per-instance
  timeout with `future.result(timeout)` and on timeout **abandons** the pool worker — `future.cancel()`
  is a no-op on a running future and `ProcessPoolExecutor.shutdown(wait=False, cancel_futures=True)`
  never signals worker processes. One live worker leaks per timed-out instance, still executing
  `evaluate_instance` unbounded. The champion's post-run eval ran 10 sequential instances at 300 s
  (`core/run.py:1191-1196`), all timing out (because of U14) → workers abandoned 300 s apart → the
  observed 23–68 min survivor age spread (≈45 min). Affects **post-run eval, `revolver eval`,
  `benchmark`, `problem test`, and run preflight** — all funnel through `run_instance`.
- **The reporter's root cause (a) is refuted for this incident**: the Shinka evolution-phase wrapper
  DOES hard-kill on per-instance timeout (`shinka.py:338-346`, `mp.Process` + `join(timeout)` +
  `proc.kill()`) — U13's own evidence (hard instances dropped at 60 s all night) proves it fired.
  Caveat: that kill is single-PID, so evaluators spawning their own subprocesses could still orphan
  grandchildren (v0.18 hardening).
- **Why B2/PR #224 missed it**: the only reap (`ChildProcessReaperMixin`, `shinka.py:1782/1816`)
  runs inside the backend's `launch()` `finally` — i.e. **before** `_post_run_evaluation` — and
  enumerates direct children only. Ordering, not a broken reap. `status='completed'` is written to
  the DB (`core/run.py:990`) *before* post-run eval; the lock is removed at `:1042`; the CLI prints
  "Run completed" with zero synchronization against abandoned workers.
- **U14**: Shinka's scheduler injects a full numeric-thread-cap env family into evolution-phase eval
  subprocesses (`shinka/launch/scheduler.py:178-202`); Revolver's `run_instance` sets none — children
  inherit uncapped BLAS on all cores. A program evolved/selected under a 4-thread cap is then scored
  uncapped → oversubscription → false 300 s timeouts (the 0/10) → each false timeout feeds a U12 leak
  (positive feedback loop: leaked grinders slow the next sequential instance).
- **U13 → U11**: both wrapper templates mean over surviving instances only (timeout AND failure
  dropped; OE `_log_instance` fires on success only; Shinka marks partial runs "correct") → engine
  `combined_score` is survivorship-biased → `best_score` = max over noisy single evals of biased
  means. #306's fallback (solution score ← run `best_score`) propagates the inflated number.
- **Coupling rule**: U12+U14 live in the same ~40 lines of `run_instance` → **one rewrite, one PR**
  (caps without kill still leaks on genuinely slow evals; kill without caps still falsely times out
  the champion program). U13 must precede U11 in v0.18 (display consumes U13's coverage keys).
  No wrapper-template edits in 0.17.1 (U13 rewrites those same lines in v0.18).

## 2. 0.17.1 — defensive slice (proposed; hotfix process per CLAUDE.md)

Zero semantic change to scores, fitness, or display. Three PRs:

**PR-A — `evaluator_runner.py` rewrite (U12 kill + U14 caps, one pass)** `[task 358]`
- Replace the per-instance `ProcessPoolExecutor` with a spawn-context `mp.Process`: child calls
  `os.setsid()` first, then applies env overrides **before** importing the evaluator; parent polls a
  result queue against a deadline (no join-first); on deadline `killpg(SIGTERM)` → 3 s grace →
  `SIGKILL` (single-PID fallback if `getpgid` fails). `InstanceTestResult` contract byte-identical.
  Spawn (not fork) is load-bearing: the run parent imports `shinka.database` → numpy → fork children
  inherit pre-initialized uncapped OpenBLAS.
- Thread caps: 9-var family mirroring shinka's scheduler + `OMP_DYNAMIC/MKL_DYNAMIC=FALSE`,
  `OMP_WAIT_POLICY=PASSIVE`. Priority: explicit arg > `REVOLVER_EVAL_NUM_THREADS` (0 = uncapped) >
  default `max(1, cpu//2)`. If ANY cap var is already in the user env → inject nothing (preserves
  the reporter's `OMP_NUM_THREADS=2` workaround). One stderr line announcing the cap.
- Hoist `core/eval.py:_global_eval_worker` (nested → module level; unpicklable under spawn) and route
  the legacy global aggregation through the same killable primitive.
- Acceptance: re-run the reporter's gen142 program via `revolver eval` → expect ~10/10 in 7–116 s
  (their capped result, held-out +0.971); one real Shinka smoke run for M1/M3/M4/lock non-regression.
- Known cost: spawn adds ~0.5 s/child startup (test-suite slowdown ~30–90 s); caps can slow a
  legitimate single big-BLAS eval (escape hatch documented).

**PR-B — finalize backstop (U12 residual)** `[task 359]`
- Never-raising direct-children reap in `launch_run` between the `_post_run_evaluation` try/except
  and `remove_run_lock` (position matters: U11 deletes the post-eval loop internals in v0.18);
  "completed" messaging only after teardown. Keep the hotfix minimal per counter-review: the
  recursive-descendants + killpg reap hardening in `base.py` moves to v0.18 (PID-reuse races).

**PR-C — papercuts** `[tasks 360–366]`
- **U1**: `parsed[key] = _parse_value(value.strip())` in `_parse_selection_kwargs` (covers run+resume;
  fixes the docstring lie and the silent bool inversion) + fail-fast residual strings in
  `_route_selection_kwargs` → garbage now fails at `--dry-run`. Update the 2 unit assertions that
  codified the bug (`test_core_run.py:3213-3214`). Defer the `_parse_value` promotion to a shared
  module to v0.18.
- **U2**: `elif member_llm.source == "local": entry["api_key"] = "ollama"` in
  `_build_ensemble_llm_config` (mirror `openevolve.py:675-678`). Also closes the ambient
  `OPENAI_API_KEY`-to-bridge leak.
- **U3**: `GlobalOptionGroup.resolve_command` override — targeted hint when an unknown "subcommand"
  token contains `=` (compose with `super()` to keep typer's did-you-mean). Covers all groups/options.
- **U5**: re-validate the snapshot `config.yaml` at run/dry-run/resume entry via
  `backend.validate_config()` (config-file analogue of B9), warn-only.
- **U6 phase 1**: warn when the *final* interval ≥ effective iterations ("no mid-run checkpoint will
  exist; a killed run cannot be resumed") — keep the S9a `>` guard verbatim.
- **U7 residual**: fire the local-inert warning also when `reasoning_efforts` arrives via
  config.yaml/`--config-override` on a local/bridge fleet (post-override check in `build_config`).
- **U10**: add `llm_dynamic_selection_kwargs` to `resolved_config()` backend_extras (surfaces
  `prior_probs`, the M4-injected `cost_aware_coef`, and merged overrides in one line) + zip
  `prior_probs` into `llm_models` entries as weights for the existing dry-run renderer.
- **U9 doc part**: extend the FACT-B warning with guidance ("short runs → `--selection fixed` to
  apply weights; shinka samplers expose no per-arm prior") + tuning-guide note.
- Docs: `REVOLVER_EVAL_NUM_THREADS`, known-issues paragraph on engine-score semantics (interim
  U11/U13 mitigation: "re-score the saved best for reporting").

## 3. v0.18 — semantic slice (proposed)

Strict order inside the release:

1. **U13 (fitness honesty)** `[task 367]` — 3 commits: (i) display guard: `parse_population` /
   `read_checkpoint_best_score` prefer numeric `combined_score` over sum-of-metrics (user-visible
   display change; updates asserted tests); (ii) coverage keys `instances_valid`/`instances_total` +
   timeout side-channel logging in BOTH wrapper templates (+ distinct TimeoutError branch in the
   Shinka template; reserve the `instances_` metric prefix); (iii) `evaluation.on_timeout:
   penalize|drop` + `timeout_score` (default 0.0, finite-validated) — **default flips to penalize**
   with release note; `drop` restores 0.17 behavior; negative-is-good caveat documented.
2. **U11 (score honesty)** `[task 368]` — finish task 86 (`_run_post_eval` → `core.eval.
   evaluate_solution`, dataset threaded, warn-only preserved, DB-contention guard: commit
   `proj_conn` before the call / WAL / busy_timeout) then one display pass: `run info` shows engine
   best (labeled "engine, single eval") next to post-eval mean (labeled, with coverage from U13).
3. **U4** `[task 369]` — migration v14: `problem_versions.backend`; resolution order explicit
   `--backend` > version backend > default, warn on mismatch (warn, not error).
4. **U8** `[task 370]` — `validate_seed_metrics()` backend hook called right after the existing
   pre-flight: fail fast when `database.feature_dimensions` names a metric absent (or non-numeric)
   in the seed's pre-flight output; builtins `complexity`/`diversity`/`combined_score` allowed.
5. **U6 phase 2** `[task 364]` — smarter default cadence when interval unset (e.g.
   `max(1, min(100, iterations // 10))`), never overriding an explicit value.
6. **U12 hardening residue** — recursive-descendant reap + killpg in `base.py`; single-PID-kill
   caveat of the Shinka wrapper (grandchildren) if evidence of need.
7. Joint validation: overnight-style demo re-run comparing engine best_score (now penalized) vs
   post-eval mean; doc-narrative audit (drift-vigilance).

Deliberate residual (documented, not resolved): after v0.18 there are **two timeout semantics by
design** — engine fitness penalizes timeouts (evolution pressure), post-eval reports honest
coverage-labeled means (reporting). Labels carry the burden.

## 4. S18+ / upstream

- **U9 feature**: per-arm bandit priors need upstream shinka changes (AsymmetricUCB has no prior
  kwarg; `ThompsonSampler` coerces scalar priors via `float()` — arrays `TypeError` today). File
  upstream only if demand persists after the 0.17.1 doc guidance.
- **U12 upstream note**: shinka `launch/local.py` job-level timeout kill is also single-PID
  (secondary orphaning path, only active when `job_config.time` is set) — candidate upstream issue.

## 5. Corrections to send back to revolver-demos

So the demos side can fix their runbook/feedback provenance:

1. **U12**: the leaked grinders were Revolver post-run-eval workers (one per timed-out instance,
   300 s apart), not Shinka evolution workers — the Shinka wrapper's per-instance kill works.
   Their "evolution-phase eval workers not bounded" claim is refuted; causes (b)/(c) confirmed.
2. **U5**: `problem version create` did warn about the dead keys (their own fixed config admits it);
   the real gap is run-time re-validation — their runbook should treat create-time warnings as fatal.
3. **U6**: at `interval == iterations` a completion checkpoint IS written; the real exposure is
   mid-run (any ≤100-iteration run has zero mid-run checkpoints by default).
4. **U7**: warnings + doc for the inert per-member effort shipped in 0.17 on the member path — if
   they saw silence, they set efforts via config/override (the actual hole) or not at all.
5. **U8**: the OE error names the missing dim and lists available metrics — friction is lateness,
   not opacity; validation will hook the pre-flight (run-time), not config resolution (impossible).
6. **U10**: dry-run *infrastructure* already has the values (built in `build_config`); the gap was
   extraction/display only — expect this to be cheap to fix, no launch needed to validate kwargs
   once shipped.
