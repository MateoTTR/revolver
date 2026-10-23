# ADR-007 — Pluggable Evolution Backend (OpenEvolve default, ShinkaEvolve optional)

**Date**: 2026-06-11
**Status**: Accepted (amended 2026-07-01, 2026-07-05)
**Deciders**: Mathieu (domain expert), Claude (architecture assistant)
**Amended**: 2026-07-01 — v0.17 multi-LLM ensemble selection (see the *Amendment* section below; supersedes parts of D4/D5, the "lossy" consequence, and the S15 roadmap line).
**Amended**: 2026-07-05 — v0.18 top-N extraction: `top_n_extraction` gains its first consumer (see the *Amendment — v0.18* section below; no capability-matrix change).

---

## Context

Revolver orchestrates a single evolution engine, OpenEvolve, and the coupling is explicit in the
key constraints ("OpenEvolve-based") and hardcoded in `infra/openevolve.py` + `core/run.py`.
ShinkaEvolve (SakanaAI, Apache-2.0) is a credible alternative engine sharing AlphaEvolve DNA with
OpenEvolve (identical `EVOLVE-BLOCK` markers, `combined_score` convention) but differing in
evaluator contract (subprocess CLI + `metrics.json` vs in-process dict), LLM access (native
per-provider SDKs vs OpenAI-compatible HTTP), persistence (single `programs.sqlite` vs
`checkpoint_N/` dirs + MAP-Elites cells), and token/cost tracking (Shinka has native USD accounting
via a bundled `pricing.csv`; OpenEvolve relies on Revolver's HTTP token-counting proxy). Revolver
itself reports **tokens only** and surfaces no USD figure (cost removed — #300; see D2).

Three preparatory studies ground this decision. Their working notes are kept outside the
repository; every finding this record relies on is stated here:

- **Engine comparison and bottom-up impact study** — the concept mapping between the two engines
  (identical `EVOLVE-BLOCK` markers and `combined_score` convention; divergent evaluator contract,
  LLM access, persistence and token accounting, as summarized above), a draft `EvolutionBackend`
  interface, and the integration risks (the evaluator-wrapper contract ranked first as the
  silent-bug source — see Risks).
- **Co-install spike** (backlog row 266) — co-installation of `shinka-evolve 0.0.7` alongside Revolver is **viable**
  (`pip check` clean; `httpx`/`rich` downgrades stay within Revolver's bounds; +75 transitive
  deps).
- **Top-down analysis** (backlog row 267) — only **4 commands are engine-coupled** (`run` launch, `run resume`,
  `run status` active-path, `run population`) plus 4 single-call shims (`doctor`, `setup`,
  `project init`, `problem version create`); **~82% of the CLI is engine-neutral** (~36
  engine-neutral commands). The post-engine boundary is `launch_run` writing Revolver-owned
  artifacts (`programs/rank-N.py` + manifest); everything downstream is engine-agnostic by
  construction. The same analysis fixed the backend interface and the three-sprint roadmap below.

Three open questions from the top-down analysis were arbitrated by the maintainer on 2026-06-11: reproducibility
scoping, token/cost semantics, and `backend_extras` typing — resolved below.

## Decision

Introduce a **pluggable evolution backend abstraction**. OpenEvolve remains the default backend
with **zero behavior change**; ShinkaEvolve becomes an optional, opt-in second backend.

### D1 — Backend abstraction (`infra/backends/`)

A `EvolutionBackend` protocol in `infra/backends/base.py`, a `get_backend(name)` factory, and two
implementations: `OpenEvolveBackend` (wraps the existing `infra/openevolve.py` ~1:1 — move, don't
rewrite) and `ShinkaBackend` (new). `core/run.py` routes launch / resume / live-progress /
population / token collection through `backend.*`.

Key interface points (the full protocol is `EvolutionBackend` in `src/revolver/infra/backends/base.py`):

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

`TokenUsage` stays **token-primary everywhere** (this supersedes the USD-primary recommendation of
the top-down analysis, after code verification of `shinka-evolve 0.0.7`):

- **OpenEvolve**: tokens measured by the HTTP `TokenCountingProxy` (unchanged). (No USD is reported —
  the Revolver-side estimate was removed in #300.)
- **ShinkaEvolve**: tokens read from `programs.sqlite` — Shinka persists `input_tokens`,
  `output_tokens`, `thinking_tokens` *and* USD costs per program in its metadata
  (`shinka/core/prompt_evolver.py::_extract_llm_metadata`); no proxy
  (`wants_http_proxy() = False`).
- **Cost removed in S15 (#300, removal completed in S16 — supersedes the `cost_usd` field below).**
  Revolver no longer reports any USD figure: the token-accounting spike (backlog row 300) showed that neither
  engine persists per-attempt or reasoning/thinking tokens, so no realistic cost is reachable.
  Token counts cover stored programs only; the `estimate_cost()` helper and the LLM
  `--input-cost`/`--output-cost` pricing flags/columns have been **removed** (schema migration v10
  drops the `llms` pricing columns). The struck-through paragraphs below describe the original
  design and are kept for history.
- ~~A supplementary **`cost_usd`** field carries native USD on Shinka (computed from its bundled
  `shinka/llm/providers/pricing.csv`, prices per 1M tokens, accessible via
  `pricing.calculate_cost()`) and the Revolver estimate on OE.~~
- ~~**Known asymmetry (accepted)**: Shinka's auxiliary LLM spend (embeddings/novelty, meta-LLM,
  summarizer) is tracked in USD only (`embed_cost`, `novelty_cost`, `meta_cost`); token totals on
  Shinka cover the evolution queries, the USD total covers everything.~~

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
- ~~Weighted ensemble → bandit selection (`ucb`) is **lossy** (weights and per-member overrides
  dropped) → adapter warns.~~ **Superseded by the v0.17 Amendment (A2/A3).** The mapping is now
  first-class: `--selection` chooses `fixed`/`ucb`/`ucb1`/`thompson`; under `fixed`, member weights are
  honored (→ `FixedSampler.prior_probs`). Weight-seeding and per-member `reasoning_effort` remain
  unavailable under the *adaptive* bandit modes — a verified ShinkaEvolve 0.0.7 limitation now surfaced
  honestly via `capabilities()`, not a silent drop.

### D6 — Dependency strategy: opt-in extra, in-process launch

ShinkaEvolve ships as an **opt-in extra** (`pip install revolver[shinka]`,
`shinka = ["shinka-evolve>=0.0.7"]`); no subprocess/venv isolation (co-install spike, backlog row 266: co-install is
clean). The backend launches Shinka **programmatically in-process** (not via its Hydra CLI),
mirroring how `OpenEvolveRunner` drives the OE controller. `doctor`/`setup` gain a per-backend
availability check / install entry.

### Implementation roadmap

Three sprints, each independently shippable (detailed in the top-down analysis): **S13** — abstraction refactor,
OE-only, exit criterion *zero behavior change* (existing L2/L3 suites stay green); **S14** — Shinka
MVP (single-LLM, fixed selection, contract tests on the `evaluate.py` wrapper front-loaded);
**S15** — parity (ensemble→bandit, top-N extraction capability, cost/token columns in `benchmark`,
backend surfaced everywhere).

> **Roadmap correction (v0.17 Amendment, 2026-07-01)**: S15 was re-scoped to token-honesty (#300) and
> S16/S16a to tech-debt + corrective work. The **ensemble→bandit** mapping and **top-N extraction** did
> not ship in S15 — they move to **S17/v0.17** (ensemble→bandit, this amendment) and **S18** (top-N #299).

## Amendment — v0.17 Multi-LLM Ensemble Selection (2026-07-01)

The S14 MVP shipped single-LLM **fixed** selection; the weighted→bandit ensemble mapping was deferred
(D5 anticipated it as "lossy", the roadmap placed it in S15). v0.17 **delivers** the multi-LLM ensemble as
a first-class, honestly-gated feature. This amendment refines D4/D5 and supersedes their "lossy/dropped"
framing. It is grounded in a source-verified, adversarially-checked study of ShinkaEvolve 0.0.7 and
OpenEvolve (working notes kept outside the repository; the verified facts are stated in A2–A5 below).

### A1 — Ensemble selection is a first-class **neutral run lever**, not `--config-override`

New neutral flags on `revolver run` / `run resume`, each mapped per backend (never exposed only through the
escape hatch): `--selection {fixed,ucb,ucb1,thompson}`, `--selection-kwarg k=v` (repeatable),
`--llm-weight model=w` (repeatable). Per-LLM `reasoning_effort` becomes a **registry field**
(`llm add` / `llm update` / `ensemble add --reasoning-effort`). This generalizes D4's neutral-lever
principle into a normative rule: **`--config-override` is the reserved escape hatch for backend-exclusive
structural keys; common levers get neutral names mapped per backend.** (Also forced by mechanism:
`_set_nested` cannot address list members — per-member weight/effort is *only* reachable via dedicated
flags, not `--config-override llm.models[i]...`.)

### A2 — Weighted→bandit is **first-class, gated by `capabilities()`** (supersedes the D5 bullet + the "Negative: lossy" consequence)

- **OpenEvolve** (`ensemble_model="weighted"`): static weighted-random sampler. `--selection` non-`fixed`
  → **rejected** with a clear error (`fixed` is the only accepted value; `selection_strategies=("fixed",)`).
  `--llm-weight` honored (patches per-member `weight`). Per-member `reasoning_effort` honored
  (`LLMModelConfig.reasoning_effort`).
- **ShinkaEvolve** (`ensemble_model="bandit"`): `--selection` → `evo_config.llm_dynamic_selection`
  (`fixed`/`ucb`/`ucb1` [alias of AsymmetricUCB]/`thompson`). Under `fixed`, member weights → the
  `FixedSampler.prior_probs` positional vector (**apples-to-apples with the OE weighted ensemble**). Under
  `ucb`/`thompson`, the arms are learned adaptively.

The headline cross-engine comparison is thus **OE-weighted** vs **Shinka-fixed** (same weights) vs
**Shinka-ucb** (adaptive) — the direct answer to the long-standing `multimodel-not-validated` gap.

### A3 — Two **verified capability asymmetries** (surfaced, map-with-warn — not hidden)

These are real ShinkaEvolve 0.0.7 constraints (source-verified; the adversarial verifiers returned
**REFUTED** on per-member effort and **PLAUSIBLE** with a documented gap on weight-seeding):

1. **Member weights seed the bandit only under `fixed`.** `prior_probs` exists only on `FixedSampler`;
   `AsymmetricUCB`/`ThompsonSampler` accept no `prior_probs` (and no `**kwargs`) → the bandit modes start
   **uniform** and **ignore** registry/`--llm-weight` weights. Revolver **warns** when weights are supplied
   under an adaptive mode. Weights therefore carry across **OE-weighted** and **Shinka-fixed** only.
2. **Per-member `reasoning_effort` is OpenEvolve-only.** Shinka's `reasoning_efforts` (like `temperatures`,
   `max_tokens`) is a **single global pool** sampled independently of the chosen model. Revolver maps
   `--reasoning-effort` **per member on OE**, and to a **single global value on Shinka** — when members
   disagree, Revolver aligns on the **highest** effort (total order `min < low < medium < high < max`, a
   conservative default that never under-thinks) and **warns** that per-member effort is not honored.
   Additionally inert for local/bridge models, which Shinka classes as non-reasoning.

### A4 — `capabilities()` widens to carry the selection surface honestly

Add two axes so validation is capability-driven, not hard-coded:
`selection_strategies: tuple[str, ...]` — the accepted `--selection` values (OE → `("fixed",)`, the
neutral vocabulary for its static weighted sampler; Shinka → `("fixed","ucb","ucb1","thompson")`) — and
`per_member_reasoning_effort: bool` (OE `True`, Shinka `False`). The `ensemble_model` axis
(`"weighted"`/`"bandit"`) describes the *sampler semantics* and is distinct from this selection vocabulary.
The CLI rejects an unsupported `--selection` and warns on a capability-limited lever, instead of diverging
silently.

### A5 — Sampler-kwarg projection is **per-strategy**

Shinka spreads `llm_dynamic_selection_kwargs` verbatim into the selected sampler's constructor, so a wrong
key raises `TypeError`. Revolver validates/routes `--selection-kwarg` against the **selected** sampler's
accepted kwargs and never passes a union. `cost_aware_coef` applies only to `ucb`/`ucb1` (**default 0** for
the flat-rate/bridge case — M4; note it is inert anyway when per-model cost is undifferentiated). This
composes with the "warn on a no-op override key" rule (backlog B9).

### Scope note

v0.17 also folds in a front-of-sprint correctness slice (B1 aggregation guard, B2 OE post-run teardown,
B7 OE best-of-interrupt recovery) — orthogonal to this ensemble amendment but shipped in the same release.
The separate **judge ensemble** (`evaluator_models` / `use_llm_feedback`) is a known unexposed gap, **not**
in v0.17 scope.

## Amendment — v0.18 Top-N Extraction Consumer (2026-07-05)

`capabilities().top_n_extraction` (D1) has carried correct per-backend values since S13 (Shinka
`True`, OE `False`) but had **zero consumers**. v0.18 adds the consumer (#299, FR-SOL-021):
`solution extract --rank N` (plus `--program-id <id>` where supported) promotes an
arbitrary-ranked population program, **gated on the run backend's `top_n_extraction`**; a
non-capable backend exits 1 with a clear "not supported on `<backend>`" error.

- **ShinkaEvolve — native.** The full population, source code included, lives in
  `programs.sqlite`; the backend reads it **retroactively** (the existing rank-1 query ordered by
  `combined_score`, without `LIMIT 1`) and materializes `programs/rank-<N>.py` — no run-dir layout
  change, works on pre-v0.18 runs.
- **OpenEvolve — deliberately stays `top_n_extraction=False` in v0.18.** Two reasons:
  (1) **checkpoint-granularity limit** — only checkpointed populations are recoverable, so OE top-N
  availability would depend on `checkpoint_interval` alignment (#364); (2) shipping it now would
  bake the pre-U13 **sum-of-metrics ordering** that #367 replaces with `combined_score`-first
  ranking (FR-RUN-052) in this same release. **Revisit post-#367** (candidate S19).

This is a consumer addition, not a capability change: D1, the capabilities matrix, and the
"Top-N extraction returns" consequence stand as written.

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| **Subprocess/CLI isolation of Shinka** (Hydra CLI, separate venv) | No dependency interaction at all | The co-install spike (backlog row 266) proved it unnecessary; loses in-process progress callbacks and typed errors; more moving parts (env management, IPC) |
| **No abstraction** — `if backend == "shinka"` branches in `core/run.py` | No refactor sprint | Unmaintainable; spreads engine knowledge through orchestration; blocks a third backend; untestable per-backend contracts |
| **Separate tool / fork** (`revolver-shinka`) | Zero risk to the OE path | Fragments the UX, duplicates 82%-neutral CLI, kills cross-engine benchmarking — the main payoff |
| **USD-primary `TokenUsage` on Shinka** (top-down analysis recommendation) | Matches Shinka's native accounting | Refuted by code inspection: Shinka persists per-program token counts; token-primary keeps one comparable unit across backends. (USD reporting was later removed entirely — #300.) |
| **Typed `OEExtras`/`ShinkaExtras` now** | Early validation of extras | Churn before the second backend exists; dict matches existing `config_overrides` precedent; promote later |
| **Make Shinka a hard dependency** | Simpler install matrix | +75 transitive deps (hydra, pandas, torch-adjacent stack) imposed on every user for an optional feature |

## Consequences

### Positive

- **Blast radius is contained and proven**: `core/run.py` + `infra/openevolve.py` + 4 small shims;
  the ~36 engine-neutral commands are untouched (the top-down CLI partition).
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
- ~~**Weighted→bandit ensemble mapping is lossy** on Shinka (weights, per-member overrides) — warned,
  not preventable.~~ **Superseded by the v0.17 Amendment (A2/A3).** The mapping is first-class; the
  residual limits (weights honored only under `fixed`; global-only `reasoning_effort` on Shinka) are
  verified engine constraints surfaced via `capabilities()`, not a Revolver-side loss.
- **Remote model-id constraint** on Shinka (`pricing.csv` recognition) is a real user-facing
  limitation to document.
- Token totals on Shinka exclude auxiliary LLM spend (embeddings/novelty, meta-LLM, summarizer) —
  minor reporting asymmetry. (Revolver reports tokens only and no USD total — #300.)
- One more abstraction layer to maintain; `infra/openevolve.py` moves (churn in imports, history).

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Shinka `evaluate.py` wrapper contract bugs (silent mis-scoring) | High | Front-load contract tests in S14 (fixture `programs.sqlite`, mock runner); the eval contract is the top silent-bug source identified by the impact study |
| `shinka-evolve` 0.0.x API instability | Medium | Pin `>=0.0.7,<0.1` in the extra; backend isolates the integration point |
| ~~Cost comparability drift (Shinka `pricing.csv` vs Revolver pricing)~~ | ~~Medium~~ | **No longer applicable** — cost reporting was removed (#300); comparison is token-primary only (D2), so there are no USD figures to drift |
| OE checkpoint-format changes breaking `OpenEvolveBackend` | Low | Unchanged from today; the backend wrapper isolates it |
| Per-backend test matrix growth (L2-OE + L2-Shinka) | Medium | Only the 4 coupled commands duplicate; neutral tests run once (top-down analysis) |

## References

- Preparatory studies — the engine comparison and bottom-up impact study (concept mapping, draft interface, risks), the dependency co-install spike (backlog row 266) and the top-down analysis (backlog row 267: CLI partition, finalized interface, engineering impact, sprint plan) — working notes kept outside the repository; their findings are stated in the Context section, and the finalized interface is `src/revolver/infra/backends/base.py`
- [ADR-006](ADR-006-openevolve-instance-injection.md) — instance injection (still valid for OE; Shinka reuses the same env-var inputs with a file-based wrapper output)
- [Specifications](../../specs/specifications.md) — FR-RUN-023/024/028-030, NFR-023, NFR §3.3 (revised per this ADR: NFR-024)
- [DES-005](../design/DES-005-run-orchestration.md), [DES-006](../design/DES-006-eval-loop.md) — revised per this ADR (backend-mediated orchestration, per-backend evaluator contract)
- ShinkaEvolve: https://github.com/SakanaAI/ShinkaEvolve (Apache-2.0)
