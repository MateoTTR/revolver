# ADR-007 — Pluggable Evolution Backend (OpenEvolve default, ShinkaEvolve optional)

**Date**: 2026-06-11
**Status**: Accepted
**Deciders**: Mathieu (domain expert), Claude (architecture assistant)

---

## Context

Revolver orchestrates a single evolution engine, OpenEvolve, and the coupling is explicit in the
key constraints ("OpenEvolve-based") and hardcoded in `infra/openevolve.py` + `core/run.py`.
ShinkaEvolve (SakanaAI, Apache-2.0) is a credible alternative engine sharing AlphaEvolve DNA with
OpenEvolve (identical `EVOLVE-BLOCK` markers, `combined_score` convention) but differing in
evaluator contract (subprocess CLI + `metrics.json` vs in-process dict), LLM access (native
per-provider SDKs vs OpenAI-compatible HTTP), persistence (single `programs.sqlite` vs
`checkpoint_N/` dirs + MAP-Elites cells), and cost tracking (native USD via bundled `pricing.csv`
vs Revolver's HTTP token-counting proxy).

Three preparatory studies ground this decision:

- **Comparison + bottom-up impact** (session 046): [shinka-vs-openevolve.md](../../analysis/shinka-vs-openevolve.md),
  [shinka-backend-impact.md](../../analysis/shinka-backend-impact.md) — draft `EvolutionBackend`
  interface, concept mapping, risks.
- **Spike #266** (session 047): [shinka-spike-266.md](../../analysis/shinka-spike-266.md) —
  co-installation of `shinka-evolve 0.0.7` alongside Revolver is **viable** (`pip check` clean;
  `httpx`/`rich` downgrades stay within Revolver's bounds; +75 transitive deps).
- **Top-down analysis #267** (session 047): [shinka-topdown-267.md](../../analysis/shinka-topdown-267.md) —
  only **4 commands are engine-coupled** (`run` launch, `run resume`, `run status` active-path,
  `run population`) plus 4 single-call shims (`doctor`, `setup`, `project init`,
  `problem version create`); **~82% of the CLI is engine-neutral**. The post-engine boundary is
  `launch_run` writing Revolver-owned artifacts (`programs/rank-N.py` + manifest); everything
  downstream is engine-agnostic by construction.

Three open questions from #267 were arbitrated by the user (session 048, 2026-06-11):
reproducibility scoping, token/cost semantics, and `backend_extras` typing — resolved below.

## Decision

Introduce a **pluggable evolution backend abstraction**. OpenEvolve remains the default backend
with **zero behavior change**; ShinkaEvolve becomes an optional, opt-in second backend.

### D1 — Backend abstraction (`infra/backends/`)

A `EvolutionBackend` protocol in `infra/backends/base.py`, a `get_backend(name)` factory, and two
implementations: `OpenEvolveBackend` (wraps the existing `infra/openevolve.py` ~1:1 — move, don't
rewrite) and `ShinkaBackend` (new). `core/run.py` routes launch / resume / live-progress /
population / token collection through `backend.*`.

Key interface points (full signature in [shinka-topdown-267.md §2.2](../../analysis/shinka-topdown-267.md)):

- **`capabilities() -> BackendCapabilities`** — declares what the backend can honestly do:
  `global_seed`, `map_elites_cells`, `native_cost_tracking`, `multi_language`, `ensemble_model`
  (`"weighted"` | `"bandit"`), `top_n_extraction`. Drives warnings and docs instead of silent
  divergence.
- **`resume()` is a first-class method**, not a flag on `launch()`: OE resumes by copying a
  checkpoint dir + `checkpoint_path`; Shinka resumes by reusing the same `results_dir` (DB-driven).
- **`config_template()`** serves `project init` (per-backend `config.yaml` scaffold);
  **`validate_config()`** serves `problem version create`.
- **Token strategy is a backend decision**: `wants_http_proxy()` + `collect_token_usage(run_dir)`.

### D2 — Token/cost tracking: token-primary on both backends

`TokenUsage` stays **token-primary everywhere** (this supersedes the USD-primary recommendation in
#267 §5.1/Q2, after code verification of `shinka-evolve 0.0.7`):

- **OpenEvolve**: tokens measured by the HTTP `TokenCountingProxy` (unchanged); USD estimated from
  Revolver-side pricing.
- **ShinkaEvolve**: tokens read from `programs.sqlite` — Shinka persists `input_tokens`,
  `output_tokens`, `thinking_tokens` *and* USD costs per program in its metadata
  (`shinka/core/prompt_evolver.py::_extract_llm_metadata`); no proxy
  (`wants_http_proxy() = False`).
- A supplementary **`cost_usd`** field carries native USD on Shinka (computed from its bundled
  `shinka/llm/providers/pricing.csv`, prices per 1M tokens, accessible via
  `pricing.calculate_cost()`) and the Revolver estimate on OE.
- **Known asymmetry (accepted)**: Shinka's auxiliary LLM spend (embeddings/novelty, meta-LLM,
  summarizer) is tracked in USD only (`embed_cost`, `novelty_cost`, `meta_cost`); token totals on
  Shinka cover the evolution queries, the USD total covers everything.

### D3 — Reproducibility scoped per backend

The project-level guarantee "runs must be reproducible given the same config and seed" becomes a
**backend capability** (`capabilities().global_seed`): honored by OpenEvolve (`random_seed`),
**not guaranteed by ShinkaEvolve** (no global search seed). NFR §3.3 and the Key Constraints are
reworded accordingly; the CLI warns when a seed is requested on a backend that cannot honor it.
User arbitration: reproducibility is not a strong enough need to block the Shinka backend.

### D4 — Neutral config surface: `ResolvedConfig` + `backend_extras`

The OE-shaped `ResolvedOEConfig` is replaced by a neutral `ResolvedConfig`:

- **Unified neutral fields** for concepts that exist in both engines under different names —
  Revolver owns the neutral name, each backend maps it to its native one: iterations
  (`max_iterations` ↔ `num_generations`), num_islands, temperature (global ↔ per-model
  `llm_kwargs`), parallel (`parallel_evaluations` ↔ eval job pool), rewrite mode
  (`diff_based_evolution` ↔ `patch_types`), llm_models, config_overrides. Lossy or
  shape-divergent mappings warn (map-with-warn, never silently no-op).
- **`backend_extras: dict[str, Any]`** for backend-exclusive parameters (OE: `checkpoint_interval`,
  `feature_dimensions`, `max_code_length`, `cascade_evaluation`…; Shinka: `max_api_costs`,
  `archive_size`, novelty/embeddings, meta-LLM…). Shipped as an **untyped dict first**; promotion
  to typed `OEExtras`/`ShinkaExtras` is deferred until the second backend exists in code.

A new `--backend {openevolve,shinka}` CLI flag (default `openevolve`) selects the backend at
`revolver run`; the backend is stored on the run (DB migration: `runs.backend TEXT NOT NULL
DEFAULT 'openevolve'`) and surfaced in `run info`/`run list`/dry-run (solution/benchmark surfacing
follows in the parity phase).

### D5 — LLM registry: no schema change, per-backend projection

`LLMEntry`/`EnsembleEntry`/`EnsembleMember` already carry every datum Shinka needs. Each backend
projects the registry at build time:

- Local (Ollama) → `local/{model}@{base_url}?api_key_env=…` (adapter synthesizes a default env
  name when unset).
- Remote → the adapter exports the **provider-standard env var** (`ANTHROPIC_API_KEY`, …) from the
  key Revolver already resolves; Shinka ignores custom `api_key_env` names for remote.
- **Documented limitation**: remote model ids must be recognized by Shinka's `pricing.csv` (or use
  a `openrouter/`/`local/` prefix), else Shinka raises `ValueError`.
- Weighted ensemble → bandit selection (`ucb`) is **lossy** (weights and per-member overrides
  dropped) → adapter warns.

### D6 — Dependency strategy: opt-in extra, in-process launch

ShinkaEvolve ships as an **opt-in extra** (`pip install revolver[shinka]`,
`shinka = ["shinka-evolve>=0.0.7"]`); no subprocess/venv isolation (spike #266: co-install is
clean). The backend launches Shinka **programmatically in-process** (not via its Hydra CLI),
mirroring how `OpenEvolveRunner` drives the OE controller. `doctor`/`setup` gain a per-backend
availability check / install entry.

### Implementation roadmap

Three sprints, each independently shippable (detail in #267 §6): **S13** — abstraction refactor,
OE-only, exit criterion *zero behavior change* (existing L2/L3 suites stay green); **S14** — Shinka
MVP (single-LLM, fixed selection, contract tests on the `evaluate.py` wrapper front-loaded);
**S15** — parity (ensemble→bandit, top-N extraction capability, cost/token columns in `benchmark`,
backend surfaced everywhere).

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| **Subprocess/CLI isolation of Shinka** (Hydra CLI, separate venv) | No dependency interaction at all | Spike #266 proved it unnecessary; loses in-process progress callbacks and typed errors; more moving parts (env management, IPC) |
| **No abstraction** — `if backend == "shinka"` branches in `core/run.py` | No refactor sprint | Unmaintainable; spreads engine knowledge through orchestration; blocks a third backend; untestable per-backend contracts |
| **Separate tool / fork** (`revolver-shinka`) | Zero risk to the OE path | Fragments the UX, duplicates 82%-neutral CLI, kills cross-engine benchmarking — the main payoff |
| **USD-primary `TokenUsage` on Shinka** (#267 recommendation) | Matches Shinka's native accounting | Refuted by code inspection: Shinka persists per-program token counts; token-primary keeps one comparable unit across backends with USD as supplement |
| **Typed `OEExtras`/`ShinkaExtras` now** | Early validation of extras | Churn before the second backend exists; dict matches existing `config_overrides` precedent; promote later |
| **Make Shinka a hard dependency** | Simpler install matrix | +75 transitive deps (hydra, pandas, torch-adjacent stack) imposed on every user for an optional feature |

## Consequences

### Positive

- **Blast radius is contained and proven**: `core/run.py` + `infra/openevolve.py` + 4 small shims;
  the ~36 engine-neutral commands are untouched (#267 §1).
- **OE default unchanged** — S13 exits only when the full existing test suite passes unmodified.
- **Honest capability reporting** (`capabilities()`) instead of silent divergence: seed, MAP-Elites,
  top-N, ensemble semantics.
- **Cross-engine benchmarking unlocked** (same problem, same LLM, OE vs Shinka) with a comparable
  token-primary cost axis — where Shinka claims sample-efficiency gains.
- **Top-N extraction returns** as a backend capability (Shinka's SQLite `get_top_programs(k)` is
  reliable where OE's `top_programs/` was not — the original reason for the rank-1 simplification).
- A third backend has a defined integration surface.

### Negative

- `revolver[shinka]` pulls **+75 transitive dependencies** and downgrades `httpx`/`rich` within
  Revolver's accepted ranges.
- **Weighted→bandit ensemble mapping is lossy** on Shinka (weights, per-member overrides) — warned,
  not preventable.
- **Remote model-id constraint** on Shinka (`pricing.csv` recognition) is a real user-facing
  limitation to document.
- Token totals on Shinka exclude auxiliary LLM spend (USD total covers it) — minor reporting
  asymmetry.
- One more abstraction layer to maintain; `infra/openevolve.py` moves (churn in imports, history).

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Shinka `evaluate.py` wrapper contract bugs (silent mis-scoring) | High | Front-load contract tests in S14 (fixture `programs.sqlite`, mock runner); the eval contract is the top silent-bug source (impact R4) |
| `shinka-evolve` 0.0.x API instability | Medium | Pin `>=0.0.7,<0.1` in the extra; backend isolates the integration point |
| Cost comparability drift (Shinka `pricing.csv` vs Revolver pricing) | Medium | Token-primary comparison (D2); document that USD figures come from different tables |
| OE checkpoint-format changes breaking `OpenEvolveBackend` | Low | Unchanged from today; the backend wrapper isolates it |
| Per-backend test matrix growth (L2-OE + L2-Shinka) | Medium | Only the 4 coupled commands duplicate; neutral tests run once (#267 §5.3) |

## References

- [shinka-vs-openevolve.md](../../analysis/shinka-vs-openevolve.md) — engine comparison (session 046)
- [shinka-backend-impact.md](../../analysis/shinka-backend-impact.md) — bottom-up impact + draft interface
- [shinka-spike-266.md](../../analysis/shinka-spike-266.md) — dependency co-install spike (#266)
- [shinka-topdown-267.md](../../analysis/shinka-topdown-267.md) — CLI partition, finalized interface, engineering impact, sprint plan (#267)
- [ADR-006](ADR-006-openevolve-instance-injection.md) — instance injection (still valid for OE; Shinka reuses the same env-var inputs with a file-based wrapper output)
- [Specifications](../../specs/specifications.md) — FR-RUN-023/024/028-030, NFR-023, NFR §3.3 (to be revised per this ADR)
- [DES-005](../design/DES-005-run-orchestration.md), [DES-006](../design/DES-006-eval-loop.md) — to be revised (backend-mediated orchestration, per-backend evaluator contract)
- ShinkaEvolve: https://github.com/SakanaAI/ShinkaEvolve (Apache-2.0)
