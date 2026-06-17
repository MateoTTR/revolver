# Sprint 015 — Thinking-Model Usability + Token Honesty + Bridge Robustness (ADR-007 P3, resserré)

**Status**: Planning (re-scoped 2026-06-17, session 051)
**Goal**: Make thinking-capable LLMs actually usable on the Shinka backend, make Revolver's token reporting honest (and drop the unachievable cost figure), and fix the slow-local-endpoint timeout that breaks the `claude-ollama-bridge` direction now in active use. Pay down the cheapest, lowest-risk S14 carry-over debt (shim removal, env restore) along the way.
**Demo**: a Gemini thinking-model Shinka run completes instead of returning empty content (`max_tokens=16384` + `max_patch_attempts=10` defaults); `run info` shows a prompt/completion/total token breakdown with an honest caveat and **no cost line**; a run where every proposal fails reports `status: completed_with_errors` with a visible warning; an OpenEvolve run against a slow local endpoint (bridge, 50–530 s/call) no longer aborts at 60 s; the `infra/openevolve.py` re-export shim is gone.
**Source**: backlog #300 (re-framed by the session-051 spike), #301, #302, #307; the S14 carry-over cheap items; ADR-007 (P3 phase).
**Predecessor**: Sprint 014 (v0.14.0) — ShinkaEvolve MVP, real engine E2E.

> **Re-scope note (session 051)**: this sprint was originally planned with 9 scopes (A–I, 33 tasks). After the user's steer (*cost is not a need; token counting matters more; if a mechanism requires fragile digging into engine internals, drop it*) and the **token-accounting spike** ([spike-300-token-accounting.md](../analysis/spike-300-token-accounting.md)), the sprint is **resserré to 6 scopes**. The deferred scopes (top-N #299, resume clone parity, config-override/ensemble→bandit/multi-language, full CLI/UX polish, DES-005 full rewrite) move to **Sprint 016** — see *Deferred to S16* below. This document is the S15 plan of record and supersedes the prior 9-scope version and the `sprint-014.md` carry-over list.

---

## The spike that re-shaped Scope A

The 🔴 #300 "cost/token under-report 20×" finding was investigated against the **real on-disk artifacts** of the demo runs (session 051, full note: [spike-300-token-accounting.md](../analysis/spike-300-token-accounting.md)). Decisive results:

- `gen_*/attempts/**/metadata.json` and `gen_*/failure.json` carry **only a derived cost** (`llm_cost`/`api_costs`) — **zero token fields** (`grep -i token` empty across all 4 runs).
- `llm_result.thinking_tokens` exists but is **0 on every real run** (Gemini-3-flash, Gemini-2.5-pro, Claude-bridge). The ~492 K billed thinking tokens are **on no readable file**.
- For a productive run, stored `api_costs` already ≈ Σ attempt `llm_cost` ($0.1146 == $0.1146); the 20× gap is **entirely** the invisible thinking tokens.

**Therefore**: there is **no simple+robust** way to count attempt/failure or thinking tokens — the data is never persisted; recovering it needs fragile monkeypatching of Shinka internals → dropped per the robustness rule. Token counting stays limited to stored `programs.sqlite` rows (already implemented, robust). Cost is removed from output (no realistic figure is reachable; not a user need).

---

## Scope

### In scope (6 scopes)

| Scope | Backlog ref | Content |
|---|---|---|
| **A — Token honesty + cost removal** | #300 (re-framed) | Remove `estimated_cost_usd` from reported output; surface stored prompt/completion/total token breakdown in `run info`; add a caveat that retry/failed-attempt and thinking tokens are not counted. No attempt/failure sweep. |
| **B — Shinka LLM-setting surface** | #301 (🟠), extends #120 | `ShinkaBackend.build_config()`: default `max_patch_attempts=10`, default `max_tokens=16384` (vs Shinka's 4096) + propagate `LLMEntry.max_tokens`, expose `reasoning_efforts`. The correctness-vs-cost lever for thinking models. **Highest value.** |
| **C — Unproductive-run status** | #302 (🟠) | Detect "0 successful child programs" on Shinka post-run → `completed_with_errors` + visible warning. |
| **#307 — Slow-local-endpoint timeout (OE)** | #307 (🟠) | Raise the default LLM timeout (or warn at `run`/dry-run) for `--source local` entries on the OE path; document the proxy/60-s-trap interaction. |
| **F — Shim removal + env cleanup** | S14 carry-over (cheap) | Delete `infra/openevolve.py` re-export shim + update imports; restore `PYTHONUNBUFFERED` after `launch()` in both backends; remove the dead defensive `iterations` fallback. |
| **Doc — minimal release pass** | — | Reflect cost removal (NFR-024, conops token/cost wording), the new caveat, `run info` token breakdown, and the #307 timeout guidance; update val-e2e Scenario 3 status. **Not** the full DES-005 rewrite (→ S16). |

### Explicitly deferred to Sprint 016

| Deferred item | Why deferred |
|---|---|
| Attempt/failure token sweep (#300 layer a) | **Dropped, not deferred** — spike proved the data does not exist on disk; user accepts losing it. |
| Resume clone parity + `resume_precheck` hook | Carries an unresolved engine-semantics question (does `ShinkaEvolveRunner` truly continue from a pre-populated `results_dir`?). Needs a moteur check before scoping. |
| Top-N extraction (#299) | High value but adds the largest task chain; OE side needs a `database.json` assessment. S16 candidate. |
| `--config-override` validation + ensemble→bandit + multi-language passthrough | Should-do completeness, not demo-blocking. |
| Full CLI/UX polish (#303–306) | Low risk, low value; bundle in S16. |
| DES-005 full rewrite + FR-RUN-036..039 / FR-RUN-042 doc debt | Large doc effort; the minimal release pass covers what S15 actually changes. |
| Removing the inert LLM pricing fields/flags (`--input-cost`/`--output-cost`, `input/output_cost_per_mtok` columns) | Needs a DB migration; left inert in S15, cleaned in S16. |

---

## Prioritization

| Priority | Scopes | Rationale |
|---|---|---|
| **Must-do (correctness / usability)** | B, C, #307 | Thinking models silently return empty content without B; 0-children runs are invisible failures without C; slow local endpoints abort at 60 s without #307. These block credible use today. |
| **Must-do (honesty)** | A | Reporting a 20×-wrong cost is worse than reporting none; the token number must be presented with its limits. |
| **Should-do (cheap debt)** | F | Mechanical, low-risk; shim removal is a maintenance gate for future Shinka work. |
| **Required for release** | Doc | The doc cascade must reflect what S15 changes before tagging v0.15.0. |

---

## Tasks

### Scope A — Token honesty + cost removal (#300)

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S15-01 | **Remove cost from reported output**: drop `estimated_cost_usd` from `models.run.TokenUsage`; remove the two `estimate_cost()` call-sites in `core/run.py` (launch ~L762, resume ~L1407); stop setting `estimated_cost_usd` in `ShinkaBackend.collect_token_usage()`. Leave `infra.token_proxy.estimate_cost()` and LLM pricing fields **inert** (deprecate in docstring; removal + DB migration → S16). | models/core/infra | PR-A | — | `TokenUsage` has no `estimated_cost_usd`; `run info --json` has no cost key; `ruff`/`mypy` clean; existing tests updated, none reference the removed field |
| S15-02 | **Token breakdown in `run info`**: display prompt / completion / total tokens from the collected `TokenUsage` for both backends (human + `--json`). | cli | PR-A | S15-01 | `run info` shows a token breakdown; `--json` carries `prompt_tokens`/`completion_tokens`/`total_tokens` |
| S15-03 | **Honesty caveat**: add a short note in `run info` (human output) and in the relevant guide: "Token counts cover stored programs only; retry/failed-attempt and reasoning/thinking tokens are not counted — watch the provider console for thinking-model spend." | cli/doc | PR-A | S15-02 | Caveat visible in `run info` (non-`--json`) when token data is present |
| S15-04 | **Tests**: token breakdown rendered; cost key absent from `--json`; caveat present; `collect_token_usage()` still returns correct prompt/completion from a fixture DB. | test | PR-A | S15-01..03 | New L2 scenarios pass on both backends; OE proxy token path regression green |

### Scope B — Shinka LLM-setting surface (#301, extends #120)

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S15-05 | **`max_patch_attempts` default 10**: inject into `ShinkaBackend.build_config()` unless overridden; document the single-attempt failure risk in the config template. | infra | PR-B | — | `build_config()` emits `max_patch_attempts=10` by default; `--config-override evo_config.max_patch_attempts=1` reduces it |
| S15-06 | **`max_tokens` escalation + propagation**: default the Shinka path to `16384` (not 4096) when `LLMEntry.max_tokens` is unset; propagate the registered value when present. Document the cost tension. | infra | PR-B | — | `build_config()` sets `max_tokens>=16384` by default; registered value wins when set |
| S15-07 | **`reasoning_efforts` exposure**: expose per-model `reasoning_efforts` in `build_config()` (Shinka per-provider naming); reachable via `--config-override`; document as the primary thinking-cost lever. | infra | PR-B | S15-05 | Dry-run shows `reasoning_efforts` in `backend_extras` when set; `launch()` passes it through |
| S15-08 | **Tests**: config-projection — default `max_patch_attempts=10`; `max_tokens` 4096→16384 escalation; `reasoning_efforts` present when override applied. | test | PR-B | S15-05..07 | 3 new config scenarios pass (auto-skip without shinka) |

### Scope C — Unproductive-run status (#302)

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S15-09 | **Detection**: in `core/run.py` Shinka post-run path, call `backend.count_valid(run_dir)`; if no successful child programs (only init rows) and ≥1 generation was attempted → status `completed_with_errors` + warning "Run completed but no successful child programs were generated". | domain | PR-C | — | `test_shinka_unproductive_run`: mocked runner, init-only fixture DB → `completed_with_errors`, warning logged |
| S15-10 | **`run info` display**: visible warning line when `status == completed_with_errors` and 0 successful children; distinct from the "some evaluations failed" path. | cli | PR-C | S15-09 | `run info` on an unproductive record shows the warning line |
| S15-11 | **Test**: L2 `test_run_shinka_unproductive` end-to-end (status + `run info` warning). | test | PR-C | S15-09, S15-10 | Passes with shinka; auto-skip without |

### Scope #307 — Slow-local-endpoint timeout (OE path)

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S15-12 | **Default timeout for `--source local` (OE)**: when an OE run uses a `--source local` LLM whose `LLMEntry.timeout` is unset, inject a higher default OE `config.llm.timeout` (e.g. 600 s) **or** warn at `run`/dry-run that the 60 s OpenAI-client default will abort slow endpoints. Document the `TokenCountingProxy`/60-s-trap interaction. | infra/domain | PR-307 | — | A `--source local` OE run no longer aborts at 60 s by default (or emits a clear dry-run/run warning); behavior documented |
| S15-13 | **Test + guide note**: L2 test that a `--source local` entry without explicit timeout yields the raised default (or the warning); add a "slow local endpoints / proxy timeout" note to `docs/guides/tuning-oe-config.md`. | test/doc | PR-307 | S15-12 | Test passes; guide note present |

### Scope F — Shim removal + env cleanup (S14 carry-over)

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S15-14 | **Delete `infra/openevolve.py` shim**: remove the file; repoint all internal imports + tests to `infra.backends.openevolve`; confirm no symbol was only available via the shim. | infra | PR-F | — | File gone; `ruff`/`mypy` clean; all OE tests pass without the shim |
| S15-15 | **`PYTHONUNBUFFERED` restore**: wrap the `os.environ["PYTHONUNBUFFERED"]="1"` mutation in both backends' `launch()` in a context manager / try-finally that restores the prior value (or deletes if absent). | infra | PR-F | — | After `launch()`, the env var is in its pre-call state; L1 test covers absent + prior-value cases |
| S15-16 | **Defensive `iterations` fallback removal**: remove the dead `cfg.get("max_iterations", 10)` fallback in `OpenEvolveBackend.launch()`/`resume()` (bound to `core.run.DEFAULT_ITERATIONS` since S14-05); add a comment pointing to the canonical resolution point. | infra | PR-F | — | Fallback gone; `grep -r "max_iterations.*10"` in `infra/` empty; OE tests pass |

### Scope Doc — minimal release pass

| # | Task | Layer | PR | Depends | Acceptance |
|---|---|---|---|---|---|
| S15-17 | **Doc reflect S15 changes**: update NFR-024 + conops token/cost wording for cost removal + the token caveat; note the `run info` token breakdown; add the #307 timeout guidance; update val-e2e Scenario 3 status to "Passing". **No** DES-005 full rewrite (→ S16). Run spec-reviewer + validation-reviewer after the doc PR. | doc | PR-Doc | A, #307 done | NFR-024/conops reflect "tokens only, no cost"; spec-reviewer 0 FAIL on touched docs |

---

## PR Breakdown and Waves

```
Wave 1 (parallel — manage shinka.py / core/run.py merge order):
    PR-F    Shim removal + env cleanup   — infra/backends/{oe,shinka}.py, delete infra/openevolve.py   (merge FIRST)
    PR-A    Token honesty + cost removal — models/run.py, core/run.py, infra/backends/shinka.py, cli
    PR-B    Shinka LLM settings          — infra/backends/shinka.py
    PR-C    Unproductive-run status      — core/run.py (post-run path), cli
    PR-307  Slow-endpoint timeout (OE)   — infra/backends/openevolve.py / core/run.py, guide

Wave 2 (after the code lands):
    PR-Doc  Minimal release doc pass     — docs only (spec-reviewer + validation-reviewer after)
```

**Conflict management**:
- `infra/backends/shinka.py`: PR-A, PR-B both touch it → merge in sequence (recommended PR-F → PR-A → PR-B), each rebased.
- `core/run.py`: PR-A (remove `estimate_cost` call-sites in the token-collection path) and PR-C (post-run status path) touch disjoint functions; PR-307 may touch the launch path — rebase before merge, no semantic conflict expected.
- `infra/openevolve.py`: PR-F deletes it; no other PR should import it.

**Recommended merge order**: PR-F → PR-A → PR-B → (PR-C, PR-307 any order) → PR-Doc.

---

## Integration Tests (L2)

| Area | Scenario | Test ID | Status |
|---|---|---|---|
| `run info` (cost removal) | No cost key in `--json`; token breakdown present | `test_run_info_no_cost_token_breakdown` | Planned |
| `run info` (caveat) | Honesty caveat line shown when tokens present | `test_run_info_token_caveat` | Planned |
| `run` (shinka, config) | `max_patch_attempts=10` by default | `test_shinka_max_patch_attempts_default` | Planned |
| `run` (shinka, config) | `max_tokens` ≥ 16384 when LLM entry unset | `test_shinka_max_tokens_escalation` | Planned |
| `run` (shinka, config) | `reasoning_efforts` present when override applied | `test_shinka_reasoning_efforts_override` | Planned |
| `run` (shinka, unproductive) | 0 successful children → `completed_with_errors` | `test_shinka_unproductive_run` | Planned |
| `run info` | Unproductive-run warning visible | `test_run_info_unproductive_warning` | Planned |
| `run` (OE, `--source local`) | No 60-s abort / clear warning for slow endpoint | `test_oe_local_timeout_default` | Planned |
| Shim removal | No import of `infra.openevolve`; suite green | regression | Planned |
| Env restore | `PYTHONUNBUFFERED` restored after `launch()` (both backends) | `test_pythonunbuffered_restore` | Planned |
| Full OE regression | Existing 1248+ tests pass on no-shinka env | regression | Planned |
| Full Shinka suite | S14 + new S15 Shinka L2 tests pass with shinka | shinka regression | Planned |

---

## Exit Criteria

The sprint is complete when ALL hold:

1. **Cost gone, tokens honest**: `run info` (human + `--json`) shows a prompt/completion/total token breakdown and **no cost figure**; the human output carries the "retry/thinking tokens not counted" caveat. L2 tests S15-04 pass.
2. **Thinking models complete**: `max_tokens=16384` and `max_patch_attempts=10` defaults prevent the empty-content failure; `reasoning_efforts` is configurable. L2 config tests S15-08 pass.
3. **Unproductive run detected**: a Shinka run with 0 successful children is recorded `completed_with_errors` with a visible `run info` warning. `test_shinka_unproductive_run` passes.
4. **Slow local endpoints survive**: a `--source local` OE run no longer aborts at the 60-s default (raised default or explicit warning); the proxy/timeout interaction is documented. S15-13 passes.
5. **Shim gone, env restored, fallback removed**: `infra/openevolve.py` does not exist; `PYTHONUNBUFFERED` is restored after `launch()`; the dead `iterations` fallback is removed. `ruff`/`mypy` clean.
6. **Full regression green**: existing 1248+ tests pass unmodified on a no-shinka env; all Shinka L2 tests pass on a shinka env; CI green.
7. **Doc cascade (minimal)**: NFR-024/conops reflect cost removal + token caveat; val-e2e Scenario 3 = Passing; spec-reviewer + validation-reviewer report 0 FAIL on touched docs. (DES-005 full rewrite explicitly deferred to S16.)

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / Y integration tests passing (target: 1248 + ~10 new S15 L2 scenarios on no-shinka env; all Shinka L2 tests on shinka env)

### Demo-able features
- [ ] `run info` shows tokens only (no cost) + honesty caveat
- [ ] Gemini thinking-model Shinka run completes (16384 / max_patch_attempts 10 defaults)
- [ ] `reasoning_efforts` configurable as a thinking-cost lever
- [ ] Unproductive run → `completed_with_errors` + visible warning
- [ ] Slow-local-endpoint OE run no longer aborts at 60 s
- [ ] `infra/openevolve.py` shim deleted; imports clean

### Carry-over
_To be filled at sprint end._
