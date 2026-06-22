# Sprint 016a — Corrective: v0.16.0 Demo Feedback (TSP + Beamforming)

**Status**: Planning
**Target release**: **v0.16.1** (corrective / patch)
**Goal**: Triage and fix the anomalies surfaced while validating Revolver **0.16.0** through the `revolver-demos` TSP + beamforming demos (gemma4 on a network Ollama via `sirius`/Tailscale, and Claude Opus/Sonnet via the `claude-ollama-bridge`). Priority on the genuine 🟠 blockers — a successful Shinka run that *looks* failed (A2) and `--parallel >1` on Claude Max turning into a multi-hour hang (A3). The network-Ollama issue (A1) was reframed by the demos update of 2026-06-22 down to a one-line probe fix (storage is already correct).
**Demo**: a single `revolver llm add --source local --base-url http://sirius:11434/v1` registers a network Ollama usable by **both** OE and Shinka; a `revolver run --backend shinka` returns to the prompt cleanly after `Done: … completed`; a `--source local` OE run on the bridge auto-limits to `parallel_evaluations=1` and no longer cascades into a retry storm.
**Source**: `revolver-demos/feedback/feedback-v0.16.md` (consolidated demo-validation report, branch `chore/restructure-v0.16`). That report is owned by the demos project; this sprint doc is the Revolver-side response and is **not** written from the demos session.
**Predecessor**: Sprint 016 (v0.16.0 — technical-debt paydown + CLI/UX polish).

> **PROVISIONAL SNAPSHOT.** The feedback report is still **OPEN**. The 3rd demo problem
> **frequency-planning** has **not yet** been run through Revolver (still at the "wire the
> project + run" stage); its run is expected to add items, after which the report will be
> extended *before v0.16 is frozen*. This sprint captures the **current** A1–A7 set only.
> Treat scope, task numbering, and the release cut as subject to a follow-up amendment
> (anticipate an `A8+` block and a possible second wave of tasks). Beamforming itself is
> **not yet validated end-to-end** — it is blocked by A2 (Shinka post-run hang) and A5
> (bridge 502s on Opus); A1/A2/A3 are prerequisites to closing that validation.

---

## Severity triage

Severity scale: 🔴 blocking · 🟠 important · 🟡 minor · ⚪ cosmetic/docs. The 🟠 items are the must-do core of this sprint.

| Item | Sev | Title | Attribution | Backlog ref | New task |
|---|---|---|---|---|---|
| **A1** | 🟠→🟡 | Network/local Ollama **probe** ignores `--base-url`/`OLLAMA_HOST` (storage already correct → cosmetic validation bug, per demos refinement 2026-06-22) | Revolver-core | new | #313 |
| **A2** | 🟠 | Shinka run busy-loops at ~100% CPU after `Done: … completed`, CLI never exits | Revolver-core | new | #314 |
| **A3** | 🟠 | `--parallel >1` on Claude Max / bridge causes a retry-storm hang on the OE path | Revolver-core | **extends #309** | #315 |
| **A4** | 🟡 | Bridge under-reports tokens (`usage` 2/4 vs real Agent-SDK spend) | bridge → Revolver impact | **composes #308** | #316 |
| **A5** | 🟡 | Bridge 502 under sustained load (transient) | bridge (external) | new (external) | #317 |
| **A6** | ⚪ | OE `config.yaml` scaffold triggers its own validator warnings | Revolver-core | new | #318 |
| **A7** | ⚪ | CLI/doc inconsistencies — `run resume --run` (option) vs sibling positionals; README `--tag` stale | Revolver-core | new | #319 |

**Backlog reuse, not duplication:**

- A3 *extends* #309 (which auto-pinned `max_proposal_jobs=1` for Shinka-local and added OE guidance as **doc-only** in S16-22); A3 turns that OE doc-only guidance into an **auto-pin + warn** in `build_config()`. #309 stays closed; #315 adds the OE code path.
- A4 *composes* #308 (the "Max-subscription spend is tracked on the Anthropic console" one-liner, shipped in S16-22/PR-UX); A4 reframes it from *cost* (already removed in #300) to *token under-count* on bridge/local endpoints. #308 stays closed; #316 extends its caveat to `run info` output and the tuning guide.

---

## Planning decisions (locked 2026-06-22)

Arbitrated with the user after the demos 2026-06-22 A1 refinement. These resolve the open design/scope/sequencing questions; the task cards and PR plan below reflect them.

| Ref | Question | Resolution |
|---|---|---|
| **P1** (A3) | Auto-pin policy for `--source local` | Auto-pin `parallel_evaluations=1` for **all** `--source local` endpoints (incl. genuine multi-GPU local — conservative default) with an easy override via `--parallel`/`--config-override`. Mirrors the Shinka-side pin already shipped in #309. |
| **P2** (A6) | OE template fix direction | **Rewrite `_CONFIG_TEMPLATE` to OE-schema-correct keys** (`max_iterations`; commented `database.population_size`). **Correction (2026-06-22):** OE's `EvaluatorConfig` field is `timeout`, **not** `timeout_per_instance` — so the wrapper timeout stays under a Revolver-owned `evaluation:` section stripped before strict validation (symmetric with Shinka's `_REVOLVER_SECTIONS`), **not** relocated under `evaluator:`. The validator stays strict for genuine OE keys. *(Implemented PR #222; deviation reviewed + signed off 2026-06-22.)* |
| **P3** | Sequencing / release | **Ship A1–A7 now as v0.16.1.** Frequency-planning (A8+) becomes a separate **`sprint-016b`** / v0.16.2 once the feedback report is extended — do **not** hold 16a. |
| **P4** (A1) | CLI surface + `OLLAMA_HOST` | **Reuse the existing `--base-url`** (no new `--host` flag); keep `OLLAMA_HOST` as an **optional convenience** default when `--base-url` is absent. |
| **P5** (A3) | Explicit `--parallel >1` on local | **Warn but honour** the user's value (map-with-warn). |
| **P6** (A7) | `run resume --run` | Add positional `RUN_ID`; **keep `--run` as a backward-compat alias** (mirror #304 `--tag`). |
| **P7** (A2) | Spike + fix shape | Spike on the **shinka env** (`revolver-demos`); if in-process teardown can't kill the busy-loop, fix via a **Revolver-owned subprocess that we reap** after the result is persisted; **file an upstream Shinka issue** (cf. #159 for OE). |
| **P8** | Backlog | Add rows **#313–#319** to `docs/tasks/backlog.md` now (16a scope is stable). |
| **P9** | PR-A3 / PR-A6 conflict | **Same agent** owns both PRs (shared file `openevolve.py`, different regions). |

---

## Scope

### In scope

| Scope | Item | Content |
|---|---|---|
| **CORE-1 — Network Ollama probe** | A1 (#313) | Derive probe root URL from `--base-url`/`OLLAMA_HOST`; pass to `OllamaClient`; normalize root vs `/v1` forms; ensure stored entry agrees with probe; both backends inherit the corrected URL. |
| **CORE-2 — Shinka post-run hang** | A2 (#314) | Spike-gated: identify the lingering process; implement orchestrator-owned teardown (explicit cleanup / subprocess-reap after result persisted). |
| **CORE-3 — OE local parallel auto-pin** | A3 (#315) | Auto-pin `parallel_evaluations=1` in `openevolve.build_config()` for `--source local` when `--parallel` unset and not in `--config-override`; warn if user sets `--parallel >1` on local; surface in dry-run. |
| **DOC-1 — Token under-count caveat** | A4 (#316) | Add caveat to `run info` (for `--source local` runs) and tuning guide — mirrors the #300 thinking-token caveat; no code change in the counting path. |
| **DOC-2 — Bridge 502 verify** | A5 (#317) | Verify Revolver proxy surfaces bridge 502 legibly (FB-01/#123 path); track external bridge-side follow-up; no Revolver code change expected. |
| **CORE-4 — OE scaffold warnings** | A6 (#318) | Rewrite `_CONFIG_TEMPLATE` to schema-correct keys; ensure a freshly-scaffolded project validates clean. |
| **UX-1 — CLI/doc consistency** | A7 (#319) | Positional `RUN_ID` on `run resume` (keep `--run` alias); README Quick Start update. |

### Explicitly out of scope

| Deferred item | Why deferred |
|---|---|
| Top-N extraction (#299) | Largest carry-over from S16; fits a dedicated sprint (S017). |
| Frequency-planning demo items | Report not yet extended; will be folded in as A8+ before v0.16 is frozen. |
| Bridge-side backoff / error mapping (A5 core fix) | External repo (`claude-ollama-bridge`) — not Revolver-core scope. |

---

## Prioritization

| Priority | Scope | Rationale |
|---|---|---|
| **Must-do** | CORE-2 (A2) | Shinka runs succeed but the terminal hangs indefinitely; users read it as a crash. Beamforming end-to-end validation is gated on this. |
| **Must-do** | CORE-3 (A3) | Silent multi-hour hang at default `--parallel` on any `--source local` endpoint; the OE path was left as doc-only guidance in #309 — that gap is now proven harmful. |
| **Should-do** | CORE-1 (A1) | Reframed by the demos 2026-06-22 update to a **cosmetic validation-probe bug** — storage is already correct and one `--source local --base-url <remote>` entry was verified to serve both backends once the probe passes. Cheap one-line fix (+ `/v1`↔root normalization + tests); kept to remove the `socat` workaround, but no longer a blocker. |
| **Should-do** | CORE-4 (A6) | The official scaffold warns about itself — low risk, high annoyance; the fix is localized to `_CONFIG_TEMPLATE`. |
| **Should-do** | UX-1 (A7) | Sibling-command shape inconsistency; README is stale after S16 positional-tag change. |
| **Nice-to-have** | DOC-1 (A4), DOC-2 (A5) | Doc-only; no user-visible correctness gap beyond the existing #300 caveat. |

---

## Anomaly detail cards

### A1 🟠→🟡 — Network/local Ollama probe ignores `--base-url`/`OLLAMA_HOST`

> **Reframed (demos feedback update 2026-06-22, found while wiring frequency-planning).** The
> root cause is **purely the validation probe**, not storage. The persisted entry is already
> correct, and a `--source local --base-url <remote>` registration was **verified to work for
> both OE and Shinka** once the probe passes (Shinka embed observed: `local/gemma4:latest@http://localhost:11435/v1`).
> A1 is therefore a **cosmetic validation bug**, not the architecture limitation first reported
> — severity **🟠 → 🟡**, and the fix shrinks to a one-line probe change (+ a `/v1`↔root
> normalization detail and tests). The original "no single registration works for both
> backends" claim is **disproven**.

- **Observed**: `revolver llm add --source local` always probes `http://localhost:11434` and ignores `--base-url`/`OLLAMA_HOST`. The pre-storage probe (`health_check`/`show_model`) fails for a network Ollama → registration aborts *before* the (correct) entry is persisted.
- **Expected**: the probe targets the `--base-url`/`OLLAMA_HOST` host; one `--source local --base-url <remote>` entry registers and resolves for both backends.
- **Repro**: register a remote gemma4 (`sirius`) for OE + Shinka in one `--source local` entry → probe hits `localhost:11434` (nothing listening) → fails. Lightest workaround: have *anything* answer on `localhost:11434` during `add` (the bridge's `/api/show` stub, or a `socat` mirror); the real `--base-url` is then stored fine.
- **Root cause** (file:line — confirmed by the demos refinement):
  - `cli/llm.py:106`: the probe is `OllamaClient()` with **no argument** → defaults to `http://localhost:11434` (`infra/ollama.py:76`). **Core fix is one line**: `OllamaClient(base_url=…)`.
  - `cli/llm.py:116`: the **stored** entry already passes `base_url=base_url` correctly → the persisted URL is fine; only the pre-storage probe is hardcoded (`core/llm.py:177-196` confirms `--base-url` is honoured for storage; `OLLAMA_HOST` is never read).
  - Downstream verified URL-aware: Shinka embeds `local/<model>@<base_url>?api_key_env=…` (`infra/backends/shinka.py:414-420`); OE maps `llm.base_url → config.llm.api_base` (`infra/backends/openevolve.py:492-493`). Fixing the probe is sufficient — one entry then serves both backends.
- **Proposed fix**:
  1. **Core (one line + normalization)**: in `cli/llm.py`, build the probe `OllamaClient` with the resolved **root** URL — derive from `--base-url`, stripping a trailing `/v1` since the native `/api/*` endpoints live at the root, not under `/v1` (this is the correctness detail the demos' raw `OllamaClient(base_url=base_url)` one-liner misses when the URL is `/v1`-suffixed). Default `http://localhost:11434`.
  2. **Optional convenience**: also read `OLLAMA_HOST` as the probe + stored default when `--base-url` is absent (the original feedback ask). Storage already works via `--base-url`, so this is a nicety, not the fix.
- **Backlog**: new — **#313** (severity 🟡; the demos refinement is the authoritative root cause).

### A2 🟠 — Shinka run busy-loops after completion, never exits

- **Observed**: after a Shinka run prints `Done: … completed` (result **stored correctly** in `programs.sqlite`), a child `revolver run` process busy-loops at ~100% CPU (State R, 1 thread, `wchan 0`) and never exits → the CLI never returns to the prompt; the terminal hangs. The OE path exits cleanly.
- **Expected**: the CLI returns to the prompt promptly after `Done: … completed`, exit code 0, no lingering process.
- **Repro**: `revolver run --backend shinka --llm <local> --iterations 5` on the TSP demo with gemma4. Contrast: `--backend openevolve` exits cleanly.
- **Root cause** (suspected; runtime — spike-gated):
  - `infra/backends/shinka.py:1377`: `_run_engine()` calls `runner.run()` **in-process** (`ShinkaEvolveRunner` → `asyncio.run()` + `JobScheduler` pool). The `Done` message is printed at `cli/run.py:248` and control returns through `core/run.py:804` (`backend.launch()`).
  - The symptom (single-thread `R`/`wchan 0` busy-loop *after* the result is persisted) points at a lingering child or pool worker that is **not joined/terminated** when `runner.run()` returns — the OE path has no equivalent of Shinka's `JobScheduler`.
  - **Precedent**: backlog #159 filed an upstream OpenEvolve `ProcessPoolExecutor.shutdown(wait=True)` hang. Shinka's scheduler is the analogous suspect; a fix may also be upstream-bound.
- **Proposed fix** (after the spike pins the exact process):
  - Preferred: wrap the Shinka engine launch so the orchestrator **owns** teardown — explicit `scheduler.shutdown()` / runner cleanup in a `finally`, then join/terminate any surviving child.
  - Backstop: run `runner.run()` in a Revolver-owned subprocess that is reaped (hard timeout) once the result is persisted to `programs.sqlite`.
  - If the busy-loop is upstream and unkillable cleanly, file an upstream issue (as #159) and document the subprocess-reap mitigation.
- **Backlog**: new — **#314**. **Spike-first** (see S16a-04).

### A3 🟠 — `--parallel >1` harmful on Claude Max (OE path)

- **Observed**: `--parallel 5` + `BRIDGE_CONCURRENCY=5` → 5 calls dispatched together complete staggered ~130s apart (150/269/396/533s), not simultaneously: Anthropic serializes requests per subscription → concurrency yields ~no wall-clock gain. Worse: queued calls exceed the 600s timeout → OE retry storm → `BrokenPipeError` (via `TokenCountingProxy`) → multi-hour hang (run stuck 13:42→15:39, 4/10 iterations before a manual kill). At `--parallel 1` the cascade disappears.
- **Expected**: a `--source local` (subscription-backed / single-GPU) endpoint defaults to serialized execution; concurrency is opt-in, not a foot-gun.
- **Repro**: `revolver run --backend openevolve --llm <bridge-local> --parallel 5` on the bridge → staggered calls, timeouts, hang. `--parallel 1` → clean.
- **Root cause** (file:line):
  - `infra/backends/openevolve.py:548-556`: `--parallel` maps straight to `config.evaluator.parallel_evaluations` with **no auto-pin** for local endpoints — fully user-controlled.
  - The Shinka side already auto-pins for local (`infra/backends/shinka.py:703-715`, #309/S16-21). The OE side was left as **doc-only** guidance in S16-22 — that is the gap.
  - "Bridge-like" is **not** a distinct category; it is `LLMEntry.source == "local"` (same signal used by the #307 600s-timeout auto-inject). No new enum needed.
- **Proposed fix** (extends #309 to the OE path):
  - In `openevolve.build_config()`, when `llm.source == "local"` and `--parallel` was **not** explicitly set and `evaluator.parallel_evaluations` is not in `--config-override`, inject `parallel_evaluations = 1`.
  - If the user explicitly passes `--parallel >1` on a `--source local` endpoint, **warn** (mirror the existing Shinka map-with-warn pattern) but honour their value.
  - Surface the pinned value in the dry-run output.
- **Backlog**: extends #309 — new task **#315**. #309 stays closed (Shinka pin + doc); #315 adds the OE auto-pin/warn.

### A4 🟡 — Bridge under-counts tokens *(bridge → Revolver impact)*

- **Observed**: a 6-token "pong" via the bridge bills ~$0.031 (the Agent SDK injects a large hidden Claude Code context per call); the bridge returns OpenAI `usage` prompt/completion = **2/4** → the token totals Revolver records **massively under-count** real consumption. Evolution calls cost $0.23–0.40.
- **Expected**: Revolver does not present an authoritative-looking token total that is silently wrong on bridge runs; the under-count is disclosed.
- **Repro**: any `--source local` bridge run → `run info` token totals reflect only the bridge-reported `usage`, not the hidden Agent-SDK context or thinking tokens.
- **Root cause / framing**: cost was already removed from output in #300 (no realistic cost is reachable). The residual is the **token under-count**, which is structurally the same family as the Shinka "thinking/retry tokens not counted" caveat from #300. Neither the OE token path nor `ShinkaBackend.collect_token_usage()` can recover the hidden context tokens without fragile bridge-internal coupling.
- **Proposed fix** (composes #308): add a **caveat** (mirroring the #300 thinking-token caveat) to `run info` and the tuning guide — *bridge / Agent-SDK endpoints under-report token usage; track real spend on the Anthropic console*. Do not present the under-counted total without that qualifier. No attempt to monkeypatch the bridge usage.
- **Backlog**: composes #308 — new task **#316**.

### A5 🟡 — Bridge 502 under sustained load (transient) *(external)*

- **Observed**: during the parallel-5 retry storm the bridge returned repeated `502 Bad Gateway` / `UpstreamError: SDK call failed: … success` on large evolution prompts; small pong calls recovered immediately afterward → transient rate-limiting (not a hard Max cap), surfaced as a confusing/contradictory error.
- **Attribution**: bridge-side (`claude-ollama-bridge` repo) — clearer error mapping + backoff belong there. **Out of Revolver-core scope.**
- **Revolver mitigation**: the trigger is the A3 retry storm; **A3 auto-pin avoids it**. Revolver's proxy already forwards the upstream status/body (FB-01/#123); verify that a bridge 502 surfaces legibly (not masked as a generic proxy error).
- **Proposed fix**: tracked, external — file/confirm on the bridge repo (backoff + error mapping). Revolver side: one-line verification that the proxy surfaces the 502 clearly; no code change expected.
- **Backlog**: new (external) — **#317**, marked *external / monitor*.

### A6 ⚪ — OE `config.yaml` scaffold triggers its own validator warnings

- **Observed**: the scaffolded `config.yaml` emits "Unknown OE config key" / "Did you mean 'database.population_size'" from `problem version create --backend openevolve` on an **untouched** project. The official template warns about itself.
- **Expected**: a freshly-scaffolded project validates clean (zero warnings).
- **Repro**: `revolver project init … --backend openevolve` → `revolver problem version create … --backend openevolve` on the untouched scaffold.
- **Root cause** (file:line) — template ↔ validator/OE-schema mismatch on three keys:
  - `infra/backends/openevolve.py:1229-1249` (`_CONFIG_TEMPLATE`) emits top-level `num_iterations`, top-level `population_size`, and an `evaluation:` section.
  - `validate_oe_config()` (`:125`): `population_size` ∈ `_DATABASE_KEYS` → "Did you mean 'database.population_size'"; `num_iterations` and `evaluation:` are neither in `REVOLVER_KEYS` (`initial_program`/`num_generations`/`timeout_per_instance`) nor in the OE schema (OE uses `max_iterations` and `evaluator:`) → "Unknown OE config key".
- **Proposed fix**: investigate which template keys `build_config()` actually consumes vs which are decorative; rewrite `_CONFIG_TEMPLATE` to schema-correct keys (`max_iterations`, commented `database: population_size`) without silently changing the effective iteration count / population. Note `EvaluatorConfig` has `timeout`, **not** `timeout_per_instance`, so keep the wrapper timeout under the Revolver-owned `evaluation:` section (stripped before the strict parse, symmetric with Shinka) rather than under `evaluator:`. Prefer correcting the template over widening the validator allowlist for genuine OE keys (which would hide real user mistakes).
- **Backlog**: new — **#318**.

### A7 ⚪ — CLI / doc inconsistencies

- **Observed**:
  1. `run info RUN_ID` (positional) vs `run resume --run ID` (option) — shape mismatch between sibling commands. `run delete` (`:635`) and `run population` (`:734`) are also positional, so `run resume` (`cli/run.py:323`) is the only outlier.
  2. README Quick Start uses `version create --tag v1.0` while `--help` shows the **positional** `TAG` (made positional in #304/S16) → README is stale.
- **Expected**: sibling commands share a shape; docs match `--help`.
- **Proposed fix**:
  1. Add a positional `RUN_ID` argument to `run resume`, keep `--run` as a backward-compat alias (positional wins; raise a clear error if neither is supplied) — mirror the #304 positional-tag pattern from S16-17.
  2. Update README Quick Start to `revolver problem version create v1.0`.
- **Backlog**: new — **#319**.

---

## Tasks

| # | Task | Layer | PR | Depends | Acceptance criteria |
|---|---|---|---|---|---|
| S16a-01 | Extract a `_normalize_ollama_url(url: str \| None) -> tuple[str, str]` helper in `infra/ollama.py` or `core/llm.py` that returns `(root_url, api_url)` — strips a trailing `/v1` for the root form, appends `/v1` for the API form. | infra | PR-A1 | — | Helper handles `http://host:11434`, `http://host:11434/v1`, and `None` (defaults to `http://localhost:11434`); unit tests cover all three input shapes. |
| S16a-02 | `cli/llm.py` — when building the probe `OllamaClient`, pass the resolved root URL from `--base-url` (strip `/v1`) or `OLLAMA_HOST` (strip `/v1` if present), defaulting to `http://localhost:11434`. Uses the S16a-01 helper. | cli | PR-A1 | S16a-01 | `llm add --source local --base-url http://sirius:11434/v1` probes `http://sirius:11434`, not `localhost`; `OLLAMA_HOST=http://sirius:11434 llm add --source local` probes `http://sirius:11434`. |
| S16a-03 | **(optional convenience — storage already honours `--base-url`)** `core/llm.py:add_llm()` — when `--base-url` is absent, default `resolved_base_url` from `OLLAMA_HOST` (append `/v1` if not present) before falling back to `http://localhost:11434/v1`. Uses the S16a-01 helper. Stored entry and probe then agree on the same host. | domain | PR-A1 | S16a-01 | `OLLAMA_HOST=http://sirius:11434 llm add --source local` stores `base_url=http://sirius:11434/v1`; `--base-url http://sirius:11434/v1` stores the same value; no `OLLAMA_HOST` → still stores `http://localhost:11434/v1`. |
| S16a-04 | **SPIKE**: reproduce the Shinka post-run busy-loop in the `revolver-demos` env; identify the exact lingering entity (asyncio event loop still running / `JobScheduler` pool worker not joined / forked evaluator child process). Record: (a) the exact process state when the loop persists, (b) whether the hang is in the `asyncio.run()` tear-down or in a pool thread, (c) whether it is in Revolver's `_run_engine` or in Shinka internals. Write a spike note in the §Spike Result section below. | investigation | — | — | Spike note written in §Spike Result; exact lingering entity named; fix shape decided (orchestrator teardown / subprocess-reap / upstream issue). |
| S16a-05 | Implement clean Shinka shutdown per spike findings: add explicit `try/finally` cleanup around `runner.run()` in `_run_engine()` — call the identified teardown method(s) (e.g., `scheduler.shutdown(wait=True, cancel_futures=True)`) before returning. As a backstop, if the cleanup raises or takes >N seconds, terminate the current process once the result has been persisted to `programs.sqlite`. | infra | PR-A2 | S16a-04 (GO) | `revolver run --backend shinka --iterations 5` (mocked or real) returns to the prompt with exit 0 within a bounded time after `Done: … completed`; no `~100% CPU` child survives; `programs.sqlite` result intact; L2 test passes. |
| S16a-06 | L2 test: Shinka run exits cleanly after completion. Mock the `ShinkaEvolveRunner` to verify that `_run_engine()` cleans up the scheduler/pool; assert exit without a lingering background thread. Auto-skip without `[shinka]` extra. | test | PR-A2 | S16a-05 | Test asserts that the background thread/pool is joined within the timeout; shinka-env regression stays green; no-shinka env auto-skips. |
| S16a-07 | `infra/backends/openevolve.py` — `build_config()`: when `spec.llm_entry.source == "local"` and `--parallel` was **not** explicitly supplied by the user and `evaluator.parallel_evaluations` is not present in `spec.config_overrides`, inject `parallel_evaluations = 1`. If the user explicitly sets `--parallel >1` on a `--source local` endpoint, emit a `[yellow]Warning[/yellow]` (mirror the Shinka warn-and-honour pattern from S16-21) but honour the value. Surface the injected `parallel_evaluations` value in the dry-run output alongside `build_config()` results. | infra | PR-A3 | — | OE dry-run with `--source local` LLM shows `parallel_evaluations: 1`; explicit `--parallel 3` on local emits a warning and sets `parallel_evaluations: 3`; `--source remote` LLM is unaffected; `--config-override evaluator.parallel_evaluations=2` overrides the auto-pin; L2 test covers all four paths. |
| S16a-08 | `run info` output: when the run's LLM `source == "local"`, append a caveat line after the token summary — "Note: bridge/Agent-SDK endpoints under-report token usage (hidden context and thinking tokens not counted); track real spend on the Anthropic console." Mirror the phrasing of the #300 thinking-token caveat already present. | cli | PR-DOC | — | `run info` on a `--source local` run shows the caveat line; `--source remote` run shows no caveat; no change to the stored `TokenUsage` fields. |
| S16a-09 | Tuning guide (`docs/guides/tuning-oe-config.md`): extend the "Subscription-backed and single-GPU local endpoints" section (added in S16-22) with (a) the OE auto-pin behaviour (new in S16a-07, mirrors the existing Shinka auto-pin paragraph) and (b) the token under-count caveat (composing #308 / extending S16-22's one-liner to the token dimension). | doc | PR-DOC | S16a-07, S16a-08 | Guide section describes both Shinka and OE auto-pin; token under-count caveat is present and accurate; doc-reviewer reports 0 FAIL on the touched section. |
| S16a-10 | Verify that Revolver's `TokenCountingProxy` (FB-01/#123 path) surfaces a bridge `502 Bad Gateway` response as a readable error (status code + body forwarded, not swallowed as a generic proxy error). No code change expected; if a masking bug is found, fix it. File/confirm bridge-side backoff + error mapping in the `claude-ollama-bridge` repo issue tracker. | infra (verify) + external | PR-DOC | — | Manual verification note in §Spike Result or PR description; if code change needed, acceptance test covers the 502 path; external follow-up linked. |
| S16a-11 | Investigate which keys in `_CONFIG_TEMPLATE` (`infra/backends/openevolve.py:1229-1249`) `build_config()` actually reads vs which are decorative comments for the user. Record findings, then rewrite the template to schema-correct keys: `max_iterations` (OE schema key, not `num_iterations`); commented `database: population_size` (not top-level `population_size`); keep the wrapper timeout under a Revolver-owned `evaluation:` section stripped before the strict parse — `EvaluatorConfig` has `timeout`, not `timeout_per_instance`, so it cannot live under `evaluator:`. Verify that the rewrite does not silently change the effective iteration count or population defaults. | infra | PR-A6 | — | `revolver problem version create --backend openevolve` on a freshly-scaffolded project emits **zero** validator warnings; the template's `max_iterations`/`population_size`/`timeout_per_instance` values are preserved or commented-out-safe; L2 test: fresh scaffold + `problem version create` → 0 warnings. |
| S16a-12 | `cli/run.py` — `run_resume`: add a positional `run_id: str | None = typer.Argument(None, help="Run ID to resume.")`, keep `--run` as a backward-compat option. Resolve: positional wins; raise a clear `ValidationError` if neither is supplied. Mirror the #304 positional-tag pattern from S16-17 (`problem_version_create`). | cli | PR-A7 | — | `revolver run resume <id>` works (positional); `revolver run resume --run <id>` still works (compat alias); `revolver run resume` with no ID prints a clear error and exits 1; `revolver run resume <id> --run <other-id>` uses the positional; L2 test covers all four paths. |
| S16a-13 | README Quick Start: update `revolver problem version create --tag v1.0` → `revolver problem version create v1.0` (positional, as per S16-17/#304). | doc | PR-DOC | — | README Quick Start matches `revolver problem version create --help`; doc-reviewer reports 0 FAIL. |
| S16a-14 | L2 integration tests for CORE-1 (A1): (a) `test_llm_add_local_base_url_probe` — probe targets the network host, not localhost; (b) `test_llm_add_local_ollama_host_env` — `OLLAMA_HOST` honoured as probe + stored default; (c) `test_llm_add_local_network_url_oe_api_base` — OE `build_config` `api_base` carries the network URL; (d) `test_llm_add_local_network_url_shinka_embed` — Shinka embed carries `local/<model>@<network-url>`. | test | PR-A1 | S16a-01..03 | All four test IDs pass; existing LLM registration tests unaffected. |
| S16a-15 | L2 integration tests for CORE-4 (A6): `test_oe_scaffold_zero_warnings` — fresh `project init` + `problem version create --backend openevolve` on the untouched scaffold emits zero validator warnings. | test | PR-A6 | S16a-11 | Test passes without `--source local` or shinka env; no regression on existing OE config validation tests. |
| S16a-16 | L2 integration tests for UX-1 (A7): (a) `test_run_resume_positional_run_id` — `run resume <id>` dispatches correctly; (b) `test_run_resume_option_compat` — `run resume --run <id>` still dispatches; (c) `test_run_resume_no_id_exits_1` — no-arg exits 1 with clear message. | test | PR-A7 | S16a-12 | All three test IDs pass; existing resume tests unaffected. |

---

## PR breakdown and waves

```
Wave 1 — independent, no shared-file conflicts across streams:
    PR-A1   A1 network/local Ollama        — infra/ollama.py (or core/llm.py helper),
                                              cli/llm.py, core/llm.py, tests/
    PR-A3   A3 OE parallel auto-pin/warn   — infra/backends/openevolve.py (build_config only),
                                              tests/
    PR-A6   A6 OE scaffold fix             — infra/backends/openevolve.py (_CONFIG_TEMPLATE only),
                                              tests/
    PR-A7   A7 run resume positional        — cli/run.py (run_resume only), tests/
    PR-DOC  A4 caveat (cli/run.py + guide) + A5 verify + A7 README
                                            — cli/run.py (run_info display), README.md,
                                              docs/guides/tuning-oe-config.md

Wave 1b — spike (no code; blocks PR-A2):
    SPIKE   S16a-04 Shinka busy-loop investigation

Wave 2 — after spike:
    PR-A2   A2 clean Shinka shutdown        — infra/backends/shinka.py (_run_engine),
                                              tests/integration/
```

**Conflict management:**

- `infra/backends/openevolve.py`: PR-A3 (modifies `build_config()` §local-pin, lines ~548-556) and PR-A6 (modifies `_CONFIG_TEMPLATE`, lines ~1229-1249) touch **different regions** of the same file. **Decision (P9): a single agent owns both PRs**, landing PR-A6 first (simpler, lower risk) then PR-A3 in sequence — no cross-branch rebase needed.
- `cli/run.py`: PR-A7 (modifies `run_resume`) and PR-DOC (modifies `run_info` display) touch **different commands** in the same file. Non-overlapping by function — no significant conflict risk; merge in any order.
- `infra/backends/shinka.py`: PR-A2 (`_run_engine` teardown) has no overlap with Wave 1 PRs. Proceed independently after the spike.

**Recommended merge order:** PR-A7 → PR-A6 → PR-A1 → PR-A3 → PR-DOC → PR-A2 (after spike GO).

---

## Spike Result

_To be filled during the sprint._

### A2 spike (S16a-04)

- **Status**: not yet executed.
- **Environment**: `revolver-demos` conda env (shinka 0.0.7 + Revolver develop).
- **Procedure**: run `revolver run --backend shinka --iterations 5` on a minimal demo; after `Done:` observe `ps aux` + `pstree` to identify the lingering process(es); attach `strace -p <pid>` or examine `/proc/<pid>/wchan`; confirm whether the hang is in `asyncio.run()` teardown, `JobScheduler` thread pool, or a forked evaluator child.
- **Expected output**: exact class/function name of the lingering entity; go/no-go decision for S16a-05 (orchestrator teardown vs subprocess-reap vs upstream issue).

---

## Integration tests (L2)

Tests from `val-integration-tests.md` (and new test IDs introduced in this sprint) that must pass at sprint end.

| Area | Scenario | Test ID | Status |
|---|---|---|---|
| A1 — network Ollama probe | `llm add --source local --base-url http://host:11434/v1` probes `host`, not `localhost` | `test_llm_add_local_base_url_probe` | Planned |
| A1 — OLLAMA_HOST | `OLLAMA_HOST=http://host:11434` honoured as probe + stored default when `--base-url` absent | `test_llm_add_local_ollama_host_env` | Planned |
| A1 — OE backend URL | network URL reaches OE `build_config` `api_base` | `test_llm_add_local_network_url_oe_api_base` | Planned |
| A1 — Shinka backend URL | network URL reaches Shinka `local/<model>@<url>` embed | `test_llm_add_local_network_url_shinka_embed` | Planned |
| A2 — Shinka clean exit | `run --backend shinka` (mocked) returns exit 0 within bound; scheduler/pool joined | `test_shinka_run_exits_cleanly` | Planned (shinka env) |
| A3 — OE local auto-pin | OE dry-run with `--source local` shows `parallel_evaluations: 1` | `test_oe_local_parallel_pin_dry_run` | Planned |
| A3 — OE explicit override | `--parallel 3` on `--source local` warns + sets `parallel_evaluations: 3` | `test_oe_local_parallel_explicit_warns` | Planned |
| A3 — OE config-override | `--config-override evaluator.parallel_evaluations=2` wins over auto-pin | `test_oe_local_parallel_config_override_wins` | Planned |
| A3 — OE remote unaffected | `--source remote` LLM: no auto-pin applied | `test_oe_remote_parallel_no_pin` | Planned |
| A4 — token caveat | `run info` on `--source local` run shows token under-count caveat | `test_run_info_local_token_caveat` | Planned |
| A4 — no caveat on remote | `run info` on `--source remote` run shows no caveat | `test_run_info_remote_no_token_caveat` | Planned |
| A6 — scaffold zero warnings | fresh scaffold → `problem version create --backend openevolve` → 0 warnings | `test_oe_scaffold_zero_warnings` | Planned |
| A7 — resume positional | `run resume <id>` dispatches correctly | `test_run_resume_positional_run_id` | Planned |
| A7 — resume option compat | `run resume --run <id>` still dispatches (backward compat) | `test_run_resume_option_compat` | Planned |
| A7 — resume no-id | `run resume` with no ID exits 1 with clear message | `test_run_resume_no_id_exits_1` | Planned |
| Regression (no-shinka env) | Existing 1289+ tests pass after all Wave 1 changes | full suite regression | Planned |
| Regression (shinka env) | Shinka L2 suite passes; `test_shinka_run_exits_cleanly` green | shinka regression | Planned |

---

## Exit criteria

The sprint is complete when ALL of the following hold:

1. **A1** — one `revolver llm add --source local --base-url http://host:11434/v1` (or `OLLAMA_HOST=http://host:11434`) registration probes the **network** host; stored `base_url` carries the network URL; both OE (`api_base`) and Shinka (`local/<model>@<url>`) inherit it. No `socat` mirror needed.
2. **A2** — `revolver run --backend shinka` returns to the prompt with exit 0 after `Done: … completed`; no `~100% CPU` lingering child; result intact in `programs.sqlite`. Spike result recorded in §Spike Result; upstream issue filed if the fix is upstream-bound.
3. **A3** — OE auto-pins `parallel_evaluations=1` for `--source local`; explicit `--parallel >1` warns and is honoured; `--config-override` wins over auto-pin; `--source remote` unaffected. The bridge retry-storm hang no longer reproduces at the default.
4. **A4** — `run info` on a `--source local` run shows the token under-count caveat; tuning guide updated.
5. **A5** — Revolver proxy verified to surface bridge 502 legibly; bridge-side follow-up tracked in the external repo.
6. **A6** — `revolver problem version create --backend openevolve` on a freshly-scaffolded project emits zero validator warnings.
7. **A7** — `run resume <id>` (positional) and `run resume --run <id>` (compat) both work; README Quick Start matches `--help`.
8. **Regression green** — existing 1289+ tests pass on the no-shinka env; Shinka L2 tests pass on the `revolver-demos` env; `ruff`/`mypy` clean; CI green.

---

## Parallelization

### Dependency graph

```
(Wave 1 — all branches independently forkable from develop)

S16a-01 (infra: normalize_ollama_url helper)
    ├──> S16a-02 (cli: probe URL from --base-url/OLLAMA_HOST)
    ├──> S16a-03 (domain: stored base_url from OLLAMA_HOST)
    └──> S16a-14 (test: A1 integration tests)
         [all three → PR-A1]

S16a-07 (infra: OE local parallel auto-pin/warn)
    └──> (test: covered by S16a-07 acceptance criteria, inline)
         [→ PR-A3]

S16a-11 (infra: OE scaffold template rewrite)
    └──> S16a-15 (test: scaffold zero warnings)
         [→ PR-A6]

S16a-12 (cli: run resume positional RUN_ID)
    └──> S16a-16 (test: A7 integration tests)
         [→ PR-A7]

S16a-08 (cli: run info local token caveat)
    ├──> S16a-09 (doc: tuning guide OE auto-pin + caveat)  ← also needs S16a-07 merged
    └──> S16a-10 (infra verify: proxy 502 + external)
    └──> S16a-13 (doc: README Quick Start)
         [all → PR-DOC]

(Wave 1b — spike, no code)
S16a-04 (spike: Shinka busy-loop investigation)
    └──> S16a-05 (infra: Shinka shutdown teardown)    [Wave 2]
         └──> S16a-06 (test: Shinka clean exit)       [Wave 2 → PR-A2]
```

### Critical path

Wave 1 (fully parallel) → PR-DOC merge → Wave 2 (after spike):

**S16a-04 (spike) → S16a-05 → S16a-06 → PR-A2 merge → regression + release**

The spike is on the critical path because PR-A2 cannot start until the exact lingering process is known. All other Wave 1 PRs run in parallel and are independent of the spike.

Estimated sequential depth:

- Wave 1 items: 2–3 tasks per stream (shallow chains), fully parallel across streams.
- Wave 2 (A2): 3 sequential tasks after the spike (spike → teardown impl → test).

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Network Ollama (CORE-1) | S16a-01, S16a-02, S16a-03, S16a-14 | develop HEAD | Agent 1 |
| B — OE parallel pin (CORE-3) | S16a-07 (+ inline L2) | develop HEAD | Agent 2 |
| C — OE scaffold fix (CORE-4) | S16a-11, S16a-15 | develop HEAD | Agent 3 |
| D — CLI consistency (UX-1) | S16a-12, S16a-16 | develop HEAD | Agent 2 or 3 |
| E — Doc + caveat | S16a-08, S16a-09, S16a-10, S16a-13 | PR-A3 merged (for guide accuracy) | Agent 1 or 2 |
| F — Shinka hang spike | S16a-04 | develop HEAD (needs shinka env) | Agent with shinka env access |
| G — Shinka teardown (CORE-2) | S16a-05, S16a-06 | Spike GO | Agent with shinka env access |

Peak parallelism: **4 agents** simultaneously at Wave 1 start (streams A, B, C, D). Collapses to 1–2 agents for Wave 2 after spike.

### Conflict risks

- `infra/backends/openevolve.py`: **moderate risk** — PR-A3 modifies `build_config()` (~lines 548-556) and PR-A6 modifies `_CONFIG_TEMPLATE` (~lines 1229-1249). Changes are in different function bodies; git will not conflict on adjacent regions, but a rebase is still recommended. **Mitigation**: land PR-A6 first (simpler), rebase PR-A3 branch on top before merging.
- `cli/run.py`: PR-A7 (`run_resume`, ~line 323) and PR-DOC (`run_info` display, ~line 508) touch different functions in the same file. **Low risk** — non-overlapping hunks; no coordination needed beyond merge order.
- `core/llm.py`: PR-A1 only. No other Wave 1 PR touches this file.
- `infra/backends/shinka.py`: PR-A2 only (`_run_engine`). No overlap with Wave 1 PRs.
- `docs/guides/tuning-oe-config.md`: PR-DOC extends the section added in S16-22. No other PR in this sprint touches the guide.

---

## Sprint Review

**Wave 1 complete — 6 of 7 items merged into `develop` (2026-06-22/23).** A2 (#224) remains a draft pending runtime confirmation on the demos env.

| PR | Items | Backlog | Status |
|---|---|---|---|
| #220 | A1 — network/local Ollama probe (+ scheme-less `OLLAMA_HOST` + `/v1` storage, folded in from review) | #313 | merged |
| #222 | A6 + A3 — warning-free OE scaffold + local parallel auto-pin | #318, #315 | merged |
| #219 | A7 — positional `RUN_ID` on `run resume` | #319a | merged |
| #221 | A4/A5/A7-doc — token under-count caveat, 502 verify, README positional tag | #316, #317, #319b | merged |
| #224 | A2 — orchestrator-owned Shinka shutdown | #314 | **draft** — demos runtime confirmation pending |

### Reviews
- Each merged PR got an independent adversarial review (workflow, 5 agents — all approved, no blockers) **and** a posted GitHub `code-reviewer` review. A1's two non-blocking findings (scheme-less `OLLAMA_HOST`, asymmetric `/v1` storage) were folded in before merge.
- Process fix adopted (**option A**, codified in `CLAUDE.md` PR workflow): the orchestrator/main session creates PRs so the `gh pr create` code-review hook fires — a PR created inside a background subagent ships unreviewed.

### Tests / CI
- Suite at **1316 passed / 4 skipped** (no-shinka env); ruff + mypy clean; CI green on all merged PRs.
- Infra: scaled the self-hosted runner pool to **3** (`x1c-mathieu`, `-2`, `-3`) to parallelize the lint + 3.12 + 3.14 matrix. Two transient CI hangs handled by re-trigger — one orphaned job from a runner restart, one intermittent `fork()`-in-multithreaded-process pytest deadlock (candidate hardening: `pytest-timeout` / `spawn` start method).

### A2 carry-over (gate to v0.16.1)
- Spike (upstream ShinkaEvolve v0.0.7): the post-run busy-loop is leaked per-call async LLM clients (`openai.AsyncOpenAI`/httpx never `aclose()`d) spinning during `asyncio.run()` teardown; the runner's own `_cleanup_async()` already joins the pools. Fix #224 = orchestrator-owned teardown (`_shutdown_runner` wait=False + `_reap_run_children` SIGTERM/SIGKILL), mocked-test green. **Runtime confirmation on the demos shinka env is the gate to merge #224 and cut v0.16.1.** Upstream issue warranted (cf. #159).

---

## Provisional / pending

- **Frequency-planning** has not yet run through Revolver. **Decision (P3): ship A1–A7 now as v0.16.1; do not wait.** When frequency-planning runs, the feedback report will be extended with an **A8+** block → triaged into a **separate `sprint-016b`** (v0.16.2), not appended here.
- **Beamforming end-to-end** validation is gated on A2 (Shinka hang) and A5 (bridge 502); close it once A2/A3 land and re-run via gemma4-on-`sirius`.
- **Backlog rows #313–#319** added to `docs/tasks/backlog.md` (§"Demo-surfaced — `revolver-demos` v0.16.0 validation") on 2026-06-22 (P8).

---

## Appendix — confirmed: `problem.md` is injected into the LLM prompt (both backends)

Asked alongside this sprint: *does Revolver inject the `problem.md` description into the prompt sent to the LLMs?* **Yes**, for both backends:

- Read from the version snapshot in `core/run.py:587-591` (`.revolver/problem/<tag>/problem.md`, optional, FR-PRB-015) and passed via `BackendRunSpec.problem_description`.
- **OpenEvolve**: injected into `config.prompt.system_message` via `SYSTEM_PROMPT_TEMPLATE` (`openevolve.py:558-563`).
- **Shinka**: injected into `evo_config.task_sys_msg` via the same template (`shinka.py:660-664`).
- It is a **system-prompt** injection, **not** embedded into `initial_program.py`. If `problem.md` is absent, the backend's default system prompt is used unchanged. Documented in DES-005 §4.4.

---

## Sprint Review

_To be filled at sprint end._

### Tests passing

- X / 16 new integration tests passing (L2)

### Demo-able features

- [ ] `revolver llm add --source local --base-url http://sirius:11434/v1` probes `sirius`, not `localhost`; no `socat` needed
- [ ] `revolver run --backend shinka --iterations 5` returns to the prompt after `Done: … completed` (exit 0, no hang)
- [ ] `revolver run --backend openevolve --llm <bridge-local>` dry-run shows `parallel_evaluations: 1`; `--parallel 3` warns
- [ ] `run info` on a bridge run shows the token under-count caveat
- [ ] Fresh `project init` + `problem version create --backend openevolve` → zero validator warnings
- [ ] `revolver run resume <run-id>` (positional) works; `--run <id>` still works
- [ ] README Quick Start shows `revolver problem version create v1.0` (no `--tag`)

### Spike result

- [ ] A2 spike result: lingering entity identified; fix shape decided (see §Spike Result above)

### Carry-over

_TBD at sprint end._
