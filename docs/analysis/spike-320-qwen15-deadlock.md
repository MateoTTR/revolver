# Spike #320 — ShinkaEvolve mid-run "deadlock" with qwen15: repro + diagnosis

**Sprint 018 PR-7 (S18-20), timeboxed spike — 2026-07-05.**
Investigates the hang observed **during** a Shinka run with the `qwen15`
model (A2 eval on `revolver-demos`, 2026-06-23). Distinct from the A2/#314
post-run teardown hang; not covered by PR #224.

**Verdict: REPRODUCED, model-independently.** The "deadlock" is an
**unbounded LLM-call stall wrapped in a four-layer multiplicative retry
stack**, invisible to ShinkaEvolve's own stuck-system watchdog. It is not a
lock-ordering deadlock and not the patch-apply loop per se (that loop is one
of the multipliers). `qwen15` was the *trigger* (a slow local model whose
generation latency crosses shinka's hard-coded 20-minute request timeout),
not the cause. A separate Revolver bug was found on the way: the
`max_proposal_jobs=1` local-endpoint pin never reaches the engine.

Repro script: [`spike-320-repro.py`](spike-320-repro.py) (same directory).

---

## 1. Hypotheses (issue #247 order) — outcomes

| # | Hypothesis | Outcome |
|---|---|---|
| 1 | **LLM-call stall** (no effective request timeout) | **CONFIRMED — root cause.** Nuance vs. the issue text: shinka 0.0.7 *does* set a client timeout (hard-coded 1200 s), but the retry stack around it multiplies a single stalled endpoint into a ~60 h wedge per proposal (worst case), and a trickling endpoint into an *infinite* one. No lever exists to change it. |
| 2 | Patch-apply retry loop (`max_patch_attempts`) | **Contributing multiplier, not the root.** The loop re-queries the LLM on every `None` response (×10 with Revolver's default), multiplying the layer-1..3 stall. It never spins without an LLM call in between. |
| 3 | Scheduler deadlock | **RULED OUT.** The asyncio event loop stays healthy during the wedge (it services signals and writes logs); the proposal coordinator is idle-waiting for the one occupied proposal slot. No lock cycle. |

## 2. Empirical repro (2026-07-05, `revolver-demos` env, shinka 0.0.7)

Technique: a fake OpenAI-compatible endpoint that accepts the TCP connection
and the `POST /v1/chat/completions` request, then **never sends a single
response byte** (the L3-fake-server technique). A 2-generation
`ShinkaEvolveRunner` run is pointed at it, constructed exactly the way
`ShinkaBackend._run_engine` does. The driver observes, dumps the child's
thread stacks via `SIGUSR1`/faulthandler, then kills the process group.

### Run 1 — `stall` mode (real constants, 150 s observation)

```
source ~/miniforge3/etc/profile.d/conda.sh && conda activate revolver-demos
python docs/analysis/spike-320-repro.py --mode stall --watch-seconds 150
```

| Evidence | Value | Meaning |
|---|---|---|
| Gen-0 (initial program) evaluated | yes (score 0.5) | evaluation path is healthy — the wedge is **not** the evaluator |
| Stalled connections | **1**, held open the whole window | the gen-1 proposal's one LLM request |
| Last engine log line | `==> QUERYING: ['local/stalled-qwen15@...']` | frozen at the query, forever |
| `STUCK SYSTEM DETECTED` lines | **0** in 150 s | watchdog threshold is 60 s — it is **blind** to the wedge (§3.3) |
| Child alive at kill time | yes | wedged, not crashed |
| Stack dump | main thread parked in the asyncio selector | the wedge is a parked coroutine awaiting an HTTP response **in-process** — no child process is involved in the stall itself |

Nothing would have changed for another 20 minutes: the first
`APITimeoutError` fires at t+1200 s, and then the retry stack begins (§3.2).

### Run 2 — `fast` mode (same code path, L1 timeout shrunk to 8 s, 240 s observation)

`shinka/llm/client.py` reads the module-global `TIMEOUT` **at call time**
(clients are constructed per query), so patching `shinka.llm.client.TIMEOUT = 8`
before the run fast-forwards layer 1 without touching any other layer —
letting the full cascade play out in minutes instead of days:

| Evidence | Value | Meaning |
|---|---|---|
| Stalled connections | **23 in ~4 min** | for **ONE** logical `llm.query` call — retry amplification is real |
| openai SDK internal retries | 16 `Retrying request to /chat/completions` lines | layer-1b: 2 silent retries per attempt (SDK default) |
| `backoff` retries | 7 `Local OpenAI - Retry N due to error: Request timed out` lines | layer 2 live, waits 7–20 s (expo, `max_value=20`) |
| `STUCK SYSTEM DETECTED` lines | **0** | watchdog still blind |
| Generation progress | none | zero forward progress throughout |

Every retry opens a **new** request while (in real life) Ollama is still
grinding on the previous ones — each retry makes a struggling endpoint
strictly worse.

## 3. Root-cause analysis — the code paths

### 3.1 The stall point

One proposal = one `await self.llm.query(...)` with **no `asyncio.wait_for`
wrapper** at any call site:

- `shinka/core/async_runner.py:3606` (in `_run_patch_async`, :3549 — the main proposal path)
- `shinka/core/async_runner.py:3382` (in `_run_fix_patch_async`, :3335)
- `shinka/core/async_runner.py:1817` (in `_generate_initial_program`, :1801 — skipped by Revolver, which always passes `init_program_str`)

The only bound on the await is the HTTP client's own timeout.

### 3.2 The four-layer retry stack (local/Ollama path)

| Layer | Where | Bound | Worst case vs. a fully stalled endpoint |
|---|---|---|---|
| **L1** — httpx/openai client timeout | `shinka/llm/client.py:182` (`openai.AsyncOpenAI(..., timeout=TIMEOUT)`), `shinka/llm/constants.py:1` (`TIMEOUT = 1200`, **hard-coded**, no env/config override — only the *headless* provider has `SHINKA_HEADLESS_TIMEOUT`) | 1200 s per HTTP attempt | — |
| **L1b** — openai SDK internal retries | openai 2.43.0 default `max_retries=2` (shinka never overrides) | 3 HTTP attempts per `create()` | ≈ 60 min per `create()` |
| **L2** — `backoff` decorator | `shinka/llm/providers/local_openai.py:105-117` — retries `APITimeoutError` (among others), `max_tries=20`, `max_value=20`, `max_time=6000` (`constants.py:2-5`) | gives up when elapsed ≥ 6000 s | ≈ 2 h per `query_local_openai_async` call, then raises |
| **L3** — `AsyncLLMClient.query` loop | `shinka/llm/llm.py:602-621`, `MAX_RETRIES = 3` (`llm.py:14`) | 3 tries, 1 s apart | ≈ 6 h, then returns `None` |
| **L4** — patch-attempt loop | `shinka/core/async_runner.py:3604` — `for patch_attempt in range(max_patch_attempts)`; a `None` response continues the loop with "The previous attempt failed. Try again." | Revolver defaults `max_patch_attempts` to **10** (`src/revolver/infra/backends/shinka.py:115,954`) | **≈ 60 h per proposal** |

After a proposal finally fails, the next generation's proposal starts the
same cycle: the run *never* terminates usefully. And the **trickle variant**
is strictly infinite: httpx's read timeout is per-received-chunk, so an
endpoint that dribbles bytes (an overloaded Ollama streaming a token every
few minutes never happens on the non-streaming path, but a half-broken proxy
or NIC-level trickle does) resets L1 forever and no layer above it ever runs.

### 3.3 The blind watchdog

ShinkaEvolve has a stuck-system watchdog — and it can never see this wedge:

- `shinka/core/async_runner.py:561` — `stuck_detection_timeout = 60.0`
- `shinka/core/async_runner.py:5225` (`_is_system_stuck`) — `is_stuck` requires
  `running_eval_jobs == 0` **and** `running_proposal_jobs == 0` (:5254-5257)
- the wedged proposal keeps `len(self.active_proposal_tasks) >= 1` for its
  whole (multi-hour) lifetime, so `_handle_stuck_system` (:5263) never runs.

Verified empirically in both runs: 0 watchdog lines despite 60 s threshold.

### 3.4 Why qwen15, and why mid-run

The mechanism is model-independent (proved with the fake endpoint). The
*trigger* is model-dependent: any condition making a request take ≥ 1200 s
enters the cascade —

1. a slow local model with Revolver's `max_tokens=16384` default
   (`shinka.py:114` — the #301 thinking-model fix) can exceed 20 min of
   generation on modest hardware; Ollama buffers the non-streaming response
   until done, so the client sees zero bytes and L1 fires while Ollama keeps
   working; the retry lands **behind** the still-running generation;
2. an Ollama-side wedge (model load stall, GPU thrash) reproduces the fake
   endpoint exactly.

Either way: each retry stacks a fresh doomed request onto a serialized
endpoint, throughput collapses to zero, log output freezes at `==> QUERYING`
(or cycles retry warnings), and the run looks deadlocked mid-run —
matching the #320 observation. Gen-0 evaluation succeeds first (as in the
repro), so the hang appears *after* visible progress. `qwen15` no longer
being pullable does not matter; the repro needs no model at all.

## 4. Secondary finding — Revolver's `max_proposal_jobs=1` pin is a no-op

`build_config` pins proposal concurrency to 1 for local-source LLMs
(UX-5/S16-21) so a serialized endpoint is not fanned out against — but the
pin never reaches the engine:

- `src/revolver/infra/backends/shinka.py:986-987` — writes
  `job["max_proposal_jobs"] = 1` into the `job_config` section;
- `src/revolver/infra/backends/shinka.py:1310` — `resolved_config` proudly
  displays it in `--dry-run`;
- **but** `LocalJobConfig` (`shinka/launch/scheduler.py:47-57`) has no such
  field, so `_dataclass_kwargs` (`shinka.py:1802-1821`) drops it at run time
  with `Warning: ignoring unknown job_config key(s) ... max_proposal_jobs`;
- `max_proposal_jobs` is actually a **`ShinkaEvolveRunner` constructor**
  kwarg (`shinka/core/async_runner.py:222-234`, default 6, CPU/memory-scaled
  in `_validate_concurrency_settings` :657) — and `_run_engine`
  (`shinka.py:1905-1920`) never passes it.

Consequence: real local runs use up to `min(6, cpu//2, …)` concurrent
proposal streams against the single-GPU endpoint, multiplying per-request
latency — pushing requests toward the 1200 s cliff of §3.2 and aggravating
the retry pile-up. The dry-run display is dishonest about it. (The tiny
repro run does not exhibit >1 concurrent proposals because the adaptive
pipeline target starts at 1; the finding is established from the code path
and the run-time warning.)

## 5. Recommendations

| # | What | Where | Effort |
|---|---|---|---|
| **R1** (separate small PR, this sprint) | **Wire the pin**: in `_run_engine`, pop `max_proposal_jobs` out of the job section and pass it to the `ShinkaEvolveRunner` constructor. Kills the misleading per-run warning, makes `--dry-run` honest, and removes the latency multiplier that pushes local endpoints over the timeout cliff. | `src/revolver/infra/backends/shinka.py` (`_run_engine`) + tests | **S** (≤ 0.5 day) |
| **R2** (small PR, this sprint or S19) | **LLM-request timeout lever**: a neutral first-class knob (config-override-is-the-exception rule; OE already has the analogous `llm --timeout` story). Shinka mapping: set/restore `shinka.llm.client.TIMEOUT` around the engine run — the module global is read at call time (empirically verified by the `fast`-mode repro, which uses exactly this seam). Honest limits to document: it caps the per-attempt stall and makes failures visible in minutes, but backoff's `max_time=6000` is baked at import, so the *total* worst case stays hours-long until upstream moves (R3). | `shinka.py` `_run_engine` + run-config plumbing + tests | **M** (1–2 days) |
| **R3** (file upstream, attach the repro) | ShinkaEvolve issue: (a) expose request timeout + retry budget as config; (b) wrap `self.llm.query` call sites in `asyncio.wait_for` with a per-proposal budget, or teach `_is_system_stuck` to consider the **age** of in-flight proposals instead of requiring `running_proposal_jobs == 0`; (c) `launch/local.py:176` `process.kill()` on job timeout kills only the direct child (grandchild leak on their side too). | github.com/SakanaAI/ShinkaEvolve | **S** (0.5 day to write) |

Non-recommendation: capping `max_patch_attempts` back down is *not* a fix —
it would resurrect the #301 malformed-patch generation loss and only divides
the wedge by a constant.

## 6. Evidence for PR-6 (reap hardening, #359) test scope

The wedge itself is **in-process** (a parked coroutine — stack dump in §2),
so the operator's escape is killing the Revolver process mid-wedge. What the
reap must then handle, per the observed process tree:

- eval jobs are plain `subprocess.Popen([...python, evaluate.py, ...])`
  direct children (`shinka/launch/local.py:105`) — **their** wrapper spawns a
  `multiprocessing.Process` per dataset instance (the Revolver wrapper's
  per-instance timeout guard, `shinka.py:327-353` template) → a **grandchild**
  exists whenever the kill lands mid-instance-eval. Per-PID SIGTERM of the
  direct child orphans it: PR-6's recursive descendant enumeration + `killpg`
  is exactly what closes this.
- the wedge duration is unbounded (hours-to-days), so the gap between the
  pre-run child-PID snapshot (`shinka.py:1903`) and the eventual reap is
  unbounded too — the **PID-reuse guard** case is not theoretical here.
- a useful PR-6 test shape: fake a wedged run (stalling endpoint, as in the
  repro) with an eval job in flight, kill mid-eval, assert the
  multiprocessing grandchild is reaped, not just the Popen child.

## 7. Repro instructions (summary)

```bash
source ~/miniforge3/etc/profile.d/conda.sh && conda activate revolver-demos  # any env with shinka 0.0.7
python docs/analysis/spike-320-repro.py                    # stall mode, ~3 min, exit 0 = wedge reproduced
python docs/analysis/spike-320-repro.py --mode fast        # retry-cascade mode, ~4 min
```

The driver prints an evidence JSON (also written to `<workdir>/evidence.json`)
and always kills the child process group at the end of the window.
