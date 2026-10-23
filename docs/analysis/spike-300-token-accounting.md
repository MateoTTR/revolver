# Spike — Token/Cost Accounting Completeness (backlog #300)

**Date**: 2026-06-17 (session 051)
**Question**: Can Revolver count the tokens spent on *failed proposals* and *retry attempts* of a Shinka run (not just the kept programs) — with a **simple and robust** mechanism that will not break when ShinkaEvolve is updated? If only a fragile internal-poking mechanism is possible, drop it.
**Verdict**: **No.** The per-attempt/failure token counts are **not persisted anywhere on disk** by ShinkaEvolve — only a derived cost is. Token counting is therefore limited to the stored `programs.sqlite` rows (already implemented). Drop the attempt/failure sweep; add an honesty caveat instead.

---

## Method

Inspected the real on-disk artifacts of the 4 Shinka runs produced during the 2026-06-13 TSP smoke test and the 2026-06-15 shim validation (the TSP problem's `.revolver/runs/` directory in the private demo repository), i.e. the exact files a `collect_token_usage()` sweep would have to read:

- `gen_*/attempts/**/metadata.json` (per-patch-attempt records)
- `gen_*/failure.json` (failed-proposal records)
- `programs.sqlite` `programs.metadata` (stored/kept programs)

Cross-checked against ShinkaEvolve 0.0.7 installed in the demo conda env.

## Findings

### 1. Attempt/failure files contain cost only — zero token fields

| File | Keys present | Token fields |
|---|---|---|
| `gen_*/attempts/**/metadata.json` | `generation`, `novelty_attempt`, `resample_attempt`, `patch_attempt`, `success`, `num_applied`, `patch_name`, `patch_description`, `error_msg`, `timestamp`, **`llm_cost`**, `llm_model` | **none** |
| `gen_*/failure.json` | `api_costs`, `novelty_cost`, `embed_cost`, `failure_class`, `failure_reason`, `failure_stage`, `attempts`, `parent_id`, `generation`, … | **none** |

`grep -i token` across **all** attempt/failure JSON files of all 4 runs → **empty**. Shinka writes only a derived `llm_cost`/`api_costs` (computed by litellm from its pricing tables), never the underlying token counts.

### 2. `thinking_tokens` exists as a field but is always 0

`programs.sqlite` `llm_result` carries a `thinking_tokens` key, but it is **0 across every real run** and every provider:

| Run dir | Model | stored in / out / **thinking** | provider-billed output |
|---|---|---|---|
| `run-20260613-140245` (productive, 9 children) | gemini-3-flash-preview | 31 617 / 8 416 / **0** | ~500 K (Google console) |
| `run-20260613-134326` (unproductive, 0 children) | gemini-2.5-pro | 0 / 0 / **0** | billed anyway |
| `run-20260615-201901` (shim) | Claude via a local OpenAI-compatible shim | 12 / 45 819 / **0** | n/a (subscription-backed) |

The ~492 K thinking tokens billed by Google on the productive run are in **no file Revolver can read**. Shinka/litellm never populate `thinking_tokens` for these providers.

### 3. Even for cost, the attempt sweep adds ~nothing on a productive run

`run-20260613-140245`: sum of `llm_cost` over the 32 attempt files = **$0.1146**, exactly equal to the sum of `api_costs` over the 9 stored `programs` rows. The stored `api_costs` already aggregates the generation's attempt cost. The ~20× provider-bill gap reported in session 050 is therefore **entirely the invisible thinking tokens**, which litellm's cost computation also omits — not missing attempts.

## Consequences

1. **No simple+robust attempt/failure token sweep exists** — the data is not hidden, it is *never written*. Recovering it would require monkeypatching Shinka's internal LLM-call layer to intercept the raw API `usage` → fragile, breaks on Shinka upgrade → **out of scope by the user's robustness rule**.
2. **Thinking-token capture is impossible** on the current Shinka path; report input/output as stored and add a caveat.
3. **What is already robust, keep**: stored-program token read (`collect_token_usage()`), and the OE path's HTTP `TokenCountingProxy` (intercepts all calls incl. retries; reads the standard OpenAI `usage`).
4. **Cost is dropped from output** (user decision, session 051) — vindicated empirically: no realistic cost figure is reachable from disk.
5. **Future robust option (not S15)**: complete token accounting on Shinka is only reachable at the **wire/proxy level** (as the OE path and the local OpenAI-compatible shim already do), independent of what the engine persists — still capped by what the provider returns in `usage` (Gemini omits thinking tokens even there).

## Outcome → Sprint 015 Scope A

- Remove `estimated_cost_usd` from reported output (model field + 2 OE call-sites + `run info`/`--json`).
- Surface the stored token breakdown (prompt / completion / total) in `run info`.
- Add caveat: "retry/failed-attempt tokens and reasoning/thinking tokens are not counted; watch the provider console for thinking-model spend."
- **No attempt/failure sweep.**
