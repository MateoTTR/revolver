# [FILED 2026-07-05] Upstream issue — github.com/SakanaAI/ShinkaEvolve/issues/143

**Title**: Unbounded LLM-call stall wedges a run for hours-to-days; stuck-system watchdog cannot see it (repro attached)

---

## Summary

A single stalled (or very slow) OpenAI-compatible endpoint wedges an entire evolution run mid-generation, with zero forward progress, for a worst case of **~60 hours per proposal** — and the built-in stuck-system watchdog structurally cannot detect it. Reproduced model-independently on shinka 0.0.7 with a fake endpoint that accepts the HTTP request and never sends a response byte.

## Root cause — a four-layer multiplicative retry stack with no external bound

One proposal is one `await self.llm.query(...)` with no `asyncio.wait_for` at any call site (`shinka/core/async_runner.py:3606` in `_run_patch_async`; `:3382` in `_run_fix_patch_async`; `:1817` in `_generate_initial_program`). The only bound on the await is the HTTP client's own timeout — and the layers around it multiply:

| Layer | Where | Bound | Worst case vs. a fully stalled endpoint |
|---|---|---|---|
| L1 — client timeout | `shinka/llm/client.py:182`, `shinka/llm/constants.py:1` (`TIMEOUT = 1200`, hard-coded, no config/env override) | 1200 s per HTTP attempt | — |
| L1b — openai SDK internal retries | SDK default `max_retries=2`, never overridden | 3 attempts per `create()` | ≈ 60 min per `create()` |
| L2 — `backoff` decorator | `shinka/llm/providers/local_openai.py:105-117` (`max_tries=20`, `max_time=6000`) | elapsed ≥ 6000 s | ≈ 2 h per query call |
| L3 — `AsyncLLMClient.query` retry loop | `shinka/llm/llm.py:602-621` (`MAX_RETRIES = 3`) | 3 tries | ≈ 6 h, then returns `None` |
| L4 — patch-attempt loop | `shinka/core/async_runner.py:3604` (`max_patch_attempts`, commonly raised to ~10 for weaker models) | per config | **≈ 60 h per proposal** |

Two aggravations:

- **The trickle variant is infinite**: httpx's read timeout is per-received-chunk, so an endpoint that dribbles bytes resets L1 forever and no outer layer ever fires.
- **Each retry makes a struggling endpoint strictly worse**: a slow local model (e.g. Ollama grinding on a large `max_tokens` completion) is still working on the previous request when the retry opens a fresh one behind it — observed 23 concurrent stalled connections for ONE logical query in the accelerated repro.

## The watchdog is structurally blind to this

`_is_system_stuck` (`shinka/core/async_runner.py:5225`) requires `running_eval_jobs == 0` **and** `running_proposal_jobs == 0` (`:5254-5257`). The wedged proposal keeps `len(self.active_proposal_tasks) >= 1` for its whole multi-hour lifetime, so `_handle_stuck_system` never runs. Verified empirically: 0 `STUCK SYSTEM DETECTED` lines across both repro runs despite the 60 s threshold.

## Reproduction

Fake OpenAI-compatible endpoint accepting `POST /v1/chat/completions` and never responding; 2-generation `ShinkaEvolveRunner` run pointed at it.

- **stall mode** (real constants, 150 s observation): gen-0 evaluates fine (the evaluator is healthy), then the run freezes at `==> QUERYING: [...]` with 1 connection held open; the first `APITimeoutError` would fire at t+1200 s.
- **fast mode** (same code path; `shinka.llm.client.TIMEOUT` module-global patched to 8 s at run time — it is read at call time — to fast-forward L1 only): 23 stalled connections in ~4 min for one logical query; 16 SDK-internal retry lines; 7 `backoff` retry lines; 0 watchdog lines; zero generation progress.

Standalone repro script attached (self-contained, needs only shinka 0.0.7 + an empty results dir; always cleans up its process group).

## Suggested fixes (any subset helps)

1. **Expose the request timeout and retry budget as configuration** — `TIMEOUT` (`constants.py:1`) and the `backoff` budgets (`constants.py:2-5`) are hard-coded today; only the headless provider has an env override (`SHINKA_HEADLESS_TIMEOUT`).
2. **Bound the proposal, not just the HTTP attempt**: wrap the `self.llm.query` call sites in `asyncio.wait_for` with a per-proposal budget — or teach `_is_system_stuck` to consider the **age** of in-flight proposal tasks instead of requiring `running_proposal_jobs == 0`.
3. **Grandchild leak on job kill**: `shinka/launch/local.py:177` `process.kill()` on job timeout kills only the direct child; an evaluator that spawns its own subprocesses (e.g. `multiprocessing`-based per-instance guards) leaks grandchildren. `os.killpg` on the job's process group would close it.

## Environment

shinka 0.0.7, Python 3.12, openai SDK 2.43.0, Linux. Observed originally with a slow local Ollama model (generation latency > 20 min at high `max_tokens` crosses the L1 cliff — the retry then lands behind the still-running generation); reproduced without any model via the fake endpoint.

---

*Status: FILED as https://github.com/SakanaAI/ShinkaEvolve/issues/143 (2026-07-05, after Mathieu's validation). The repro script was minimized to a Revolver-independent `shinka_stall_repro.py` (embedded in the issue), re-verified against real shinka 0.0.7 before filing (stall mode: WEDGED, exit 0).*
