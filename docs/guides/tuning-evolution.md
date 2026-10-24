---
verified-against: v0.19.0
---

# Tuning Evolution Runs

Practical guide for tuning evolution runs through the Revolver CLI, on both
supported backends: **OpenEvolve** (default) and **ShinkaEvolve**
(`--backend shinka`, opt-in via `pip install 'revolver[shinka]'`).

## Overview

Both engines expose dozens of configuration knobs. Most have sensible
defaults, but a few have significant impact on optimization quality and cost.
This guide separates what is *shared* from what is *engine-specific*:

| Section | Scope |
|---|---|
| [Tuning concepts](#tuning-concepts) | Backend-neutral: what the levers mean, and how each backend maps them |
| [Ensemble strategies](#ensemble-strategies-cross-engine) | Cross-engine: multi-model ensembles, selection strategies, verified asymmetries |
| [Operational levers](#operational-levers-revolver-side) | Revolver-side: thread caps, token accounting, serialized local endpoints |
| [OpenEvolve knob reference](#openevolve-knob-reference) | MAP-Elites grid, islands, parallelism, profiles, multi-objective |
| [ShinkaEvolve knob reference](#shinkaevolve-knob-reference) | Islands + archive, bandit selection, patch attempts, LLM sampling pool, novelty |
| [Known issues](#known-issues) | Cross-engine caveats to keep in mind when reading results |

**Key principle**: both engines are *evolutionary* systems. They need enough
iterations to explore, diversify, and converge. Tuning the parameters below
determines the balance between exploration breadth, exploitation depth, and
wall-clock cost.

**Workflow tip**: `revolver run --dry-run` prints the fully resolved
configuration (including backend-specific extras) without launching anything.
Use it to verify every tuning decision in this guide before spending compute.

---

## Tuning concepts

Concepts in this section apply to both backends. Revolver owns a set of
**neutral levers** — first-class CLI flags mapped per backend — so the same
command shape works on either engine:

| Neutral lever | Flag | OpenEvolve mapping | ShinkaEvolve mapping |
|---|---|---|---|
| Backend | `--backend {openevolve,shinka}` | default | opt-in extra |
| Iterations | `--iterations N` | `max_iterations` | `evo_config.num_generations` |
| Temperature | `--temperature F` (or LLM registry) | `llm.temperature` | `llm_kwargs.temperatures: [F]` |
| Parallel evaluations | `--parallel N` | `evaluator.parallel_evaluations` | **no effect** (warns) — engine-managed |
| Full-rewrite mode | `--rewrite-mode` | `diff_based_evolution=false` + `max_code_length=50000` | `patch_types=["full"]` + `patch_type_probs=[1.0]` |
| Selection strategy | `--selection {fixed,ucb,ucb1,thompson}` | `fixed` only (rejected otherwise) | all four |
| Ensemble member weights | registry weights / `--llm-weight model=w` | honored | honored under `fixed` only |
| Reasoning effort | `llm add/update --reasoning-effort` (registry) | honored **per member** | single **global** pool |
| Everything else | `--config-override key=value` | OE schema keys | `evo_config.` / `db_config.` / `job_config.` keys |

### Exploration vs exploitation

Every knob in this guide ultimately shifts the same balance:

- **Exploration** — how broadly the population samples new algorithmic ideas:
  more islands, higher temperature, full-rewrite mode, adaptive model
  selection, quality-diversity mechanisms.
- **Exploitation** — how hard the engine refines what already works: fewer
  islands, lower temperature, diff-based edits, fixed selection weighted
  toward the strongest model.

Short runs cannot afford much exploration (there is no time to converge back);
long runs stagnate without it. The per-backend profiles and rules of thumb
below are all instances of this trade-off.

### Iteration budget

`--iterations` is the primary cost lever: each iteration is at least one LLM
call plus one evaluation. It maps to OpenEvolve `max_iterations` and
ShinkaEvolve `evo_config.num_generations`. Freshly scaffolded projects
(`revolver project init`) default to 10 iterations on both backends — a smoke
value, not a tuning recommendation.

| Budget | What to expect |
|---|---|
| ~50 | Setup validation only. Closer to random search than evolution. |
| ~500 | Diversity mechanisms start paying off; measurable improvement. |
| 2000+ | Full-scale search; complex algorithmic discoveries become likely. |

### Islands and migration

Both engines split the population into independent **islands** that evolve
separately and exchange their best programs periodically (**migration**).
Each island explores a different region of the solution space; migration
injects fresh genetic material and prevents premature convergence.

The knobs live under different namespaces and have different defaults:
OpenEvolve `database.num_islands` (default 5) /
`database.migration_interval` (default 50) — see the
[OpenEvolve knob reference](#islands); ShinkaEvolve `db_config.num_islands`
(scaffold default 2) / `db_config.migration_interval` (default 10) — see the
[ShinkaEvolve knob reference](#islands-and-the-elite-archive).

### Quality-diversity: grid vs archive

The two engines keep their populations diverse through **different
mechanisms** — this is the single largest conceptual difference between them:

- **OpenEvolve** maintains an explicit **MAP-Elites grid**: programs are
  binned by configurable *feature dimensions* (code complexity, diversity,
  any evaluator metric), and the best program per cell is kept. You tune the
  grid directly (`database.feature_dimensions`, `database.feature_bins`).
- **ShinkaEvolve** has **no MAP-Elites grid**. Diversity comes from islands,
  a bounded **elite archive** (`db_config.archive_size`), weighted parent
  sampling, and an optional embedding-based **novelty rejection** loop that
  resamples candidates too similar to existing programs.

Consequence: MAP-Elites tuning advice (feature dimensions, multi-objective
grids) applies to OpenEvolve only; on ShinkaEvolve the equivalent levers are
the archive size and novelty rejection.

### Temperature

Temperature controls the randomness of the LLM's output. Lower values produce
more deterministic, conservative code changes. Higher values produce more
diverse, creative (but potentially invalid) changes.

There are two ways to set temperature, with different scopes:

**1. Per-LLM default** (stored in the LLM registry):

```bash
# Set temperature when registering an LLM
revolver llm add my-llm --source local --model codestral:22b \
  --temperature 0.7

# Update temperature on an existing LLM
revolver llm update my-llm --temperature 1.0
```

This temperature is injected into every run that uses this LLM, unless
overridden by the CLI flag.

**2. Per-run override** (highest priority):

```bash
# Override temperature for a single run
revolver run --llm my-llm --temperature 0.5
```

Temperature is resolved with last-wins semantics on both backends:

1. Problem `config.yaml` (base) — lowest priority
2. LLM registry `temperature` field — overrides config.yaml
3. `--temperature` CLI flag — overrides everything

Per-backend mapping: OpenEvolve receives a single global `llm.temperature`;
ShinkaEvolve receives a single-valued sampling pool
(`llm_kwargs.temperatures: [F]`). When no temperature is set anywhere on the
ShinkaEvolve path, the engine samples each query's temperature from its own
default pool `[0.0, 0.5, 1.0]`.

Effect on evolution:

| Temperature | Behavior | When to use |
|-------------|----------|-------------|
| 0.0 - 0.3 | Very conservative. Minimal code changes, mostly syntactic. High valid-diff rate but low diversity. | Fine-tuning a near-optimal solution |
| 0.4 - 0.7 | Balanced. Moderate changes, good mix of valid and creative diffs. | General-purpose optimization (recommended starting point) |
| 0.8 - 1.2 | Creative. Larger structural changes, algorithmic rewrites. Lower valid-diff rate. | Early exploration, complex problems |
| 1.3 - 2.0 | Highly random. Many invalid diffs, but occasionally breakthrough ideas. | Brainstorming phase with large iteration budget |

**Practical advice**: start at 0.7 for API models and 0.5 for smaller local
models. Local models (7B-22B parameters) produce more formatting errors at
high temperatures, so keeping temperature moderate helps maintain a usable
valid-diff rate.

### Parallelism

`--parallel` controls how many candidate programs are evaluated concurrently
— but it is honored **on the OpenEvolve backend only**
(`evaluator.parallel_evaluations`; details and per-LLM recommendations in the
[OpenEvolve knob reference](#parallel-evaluations)).

On the **ShinkaEvolve backend `--parallel` has no effect** and Revolver warns
instead of silently ignoring it: the engine manages its own evaluation job
pool. The Shinka-side concurrency lever is `job_config.max_proposal_jobs`
(how many LLM proposal jobs run concurrently) — see
[Proposal concurrency](#proposal-concurrency-max_proposal_jobs).

On both backends, Revolver pins LLM-facing concurrency to 1 for `--source
local` endpoints unless you opt out — see
[Subscription-backed and single-GPU local endpoints](#subscription-backed-and-single-gpu-local-endpoints).

### Full-rewrite mode

By default, both engines evolve programs through **diff-based** edits: the
LLM reads the current program and produces a targeted patch that modifies a
small section. This works well for incremental optimization — parameter
tuning, local search improvements, and minor algorithmic tweaks.

**Full-rewrite mode** asks the LLM for the **entire program** each iteration.
Instead of patching the existing code, the LLM generates a complete
replacement. This enables fundamentally different algorithmic approaches that
diff-based mode cannot reach.

The neutral `--rewrite-mode` flag (on `run` and `run resume`) enables it on
either backend:

```bash
revolver run --rewrite-mode
# OpenEvolve equivalent:
#   --config-override diff_based_evolution=false --config-override max_code_length=50000
# ShinkaEvolve equivalent: patch_types=["full"], patch_type_probs=[1.0]
```

Per-backend nuances:

- **OpenEvolve** is *either/or*: `diff_based_evolution: false` switches every
  iteration to full generation, and `max_code_length: 50000` raises the
  generated-program size limit (default 10000 characters, too small for full
  programs). Config overrides always take precedence over the
  `--rewrite-mode` defaults — e.g. `revolver run --rewrite-mode
  --config-override max_code_length=30000` uses rewrite mode with a smaller
  limit.
- **ShinkaEvolve** natively *mixes* patch modes per iteration: the Revolver
  default is `patch_types: ["diff", "full"]` with sampling probabilities
  `[0.6, 0.4]`, so ~40% of generations are already full rewrites without any
  flag. `--rewrite-mode` forces 100% full rewrites; a custom mix is a
  config.yaml / `--config-override` matter (see the
  [ShinkaEvolve knob reference](#patch-generation-patch_types-max_patch_attempts)).

#### When to use full-rewrite mode

Full-rewrite mode is useful when:

- **The initial program is a placeholder or naive baseline.** You want the
  LLM to explore entirely new solution structures, not tweak an existing one.
- **You want to explore fundamentally different algorithmic approaches.** For
  example, switching from a hand-rolled gradient descent to a `scipy.optimize`
  solver, or from a greedy heuristic to a mathematical programming formulation.
- **Diff-based mode is producing only minor parameter tweaks.** If evolution
  has stagnated and all diffs are small constant adjustments, switching to
  full-rewrite can break out of the local optimum.

Stick with diff-based mode (the default) when:

- The initial program already uses the right algorithmic approach and just
  needs tuning.
- You are using a small local model (7B–22B parameters) that struggles with
  generating long, syntactically correct programs.
- Token cost is a primary concern — full-rewrite generates far more tokens
  per iteration.

#### Model compatibility (thinking models)

Not all models work well in full-rewrite mode. Gemini "thinking" models
(those that use chain-of-thought reasoning internally) can silently consume
their output token budget on thinking tokens, leaving too few tokens for the
actual program. This results in truncated output and 0% valid programs.

| Model | Rewrite mode | Notes |
|---|---|---|
| Gemini Flash-Lite | OK | Fast and cheap, good for exploration |
| Gemini Flash (thinking) | NOT recommended | Thinking tokens consume `max_tokens` silently, causing truncated output |
| Gemini Pro (`reasoning_effort=low`) | OK | Good quality, reasonable cost |
| Gemini Pro (default reasoning) | OK | Best quality but expensive |

> **Tip**: if you must use a thinking model, lower its reasoning budget with
> the first-class flag — `revolver llm update <name> --reasoning-effort low`
> (persisted in the registry, applied to every run) — rather than
> `--config-override`. A one-off `--config-override llm.reasoning_effort=low`
> remains available as an escape hatch for a single non-ensemble OpenEvolve
> run.

#### Trade-offs

| Aspect | Diff-based (default) | Full-rewrite |
|---|---|---|
| Creativity | Incremental — small changes to existing code | High — can discover fundamentally different approaches |
| Token cost | Low — only the diff is generated | High — entire program generated each iteration |
| OE `max_code_length` needed | Default is sufficient | At least 50000 (the `--rewrite-mode` default) |
| Iteration speed | Fast — small payloads | Slower — more tokens per iteration |
| Best for | Tuning, parameter optimization, local search | Paradigm exploration, algorithm discovery |

#### Recommended workflow

For complex problems where you are unsure which algorithmic approach is best:

1. **Start in full-rewrite mode** with a minimal initial program and an
   enriched `problem.md` (see the
   [initial program guide](initial-program-structure.md#problemmd-as-key-lever)):

   ```bash
   revolver run --llm gemini-pro --rewrite-mode --iterations 50
   ```

2. **Identify the best approach** from the evolved programs using
   `revolver solution show`.

3. **Switch to diff-based mode** for fine-tuning. Use the best evolved
   program as the new initial program and run diff-based evolution to
   optimize parameters and details:

   ```bash
   revolver run --llm gemini-flash-lite --iterations 500
   ```

This two-phase workflow combines the creative exploration of full-rewrite
with the efficiency of diff-based tuning.

### Neutral flags first, `--config-override` as escape hatch

`--config-override key=value` (repeatable, dotted keys reach nested sections)
is the **reserved escape hatch for backend-exclusive structural keys** —
OpenEvolve `database.feature_dimensions`, ShinkaEvolve
`db_config.archive_size`, and the like. It is **not** the path for the common
levers in the table above: those have first-class flags precisely so the same
command works on both backends.

Two guard rails:

- A `--config-override` whose key matches no field in the resolved backend's
  config schema is a no-op and is **warned** rather than silently accepted
  (spec §4.5).
- `--config-override` cannot address *array members* — per-member ensemble
  weight or reasoning effort is reachable only through `--llm-weight` and the
  `llm ensemble add` flags.

---

## Ensemble strategies (cross-engine)

Both backends run multi-model ensembles from the same registry entities.
Instead of using a single LLM for all code generation requests, an ensemble
distributes requests across multiple models. Revolver manages ensembles as
named entities in the LLM registry, making them reusable and traceable —
OpenEvolve consumes them as a static weighted sampler (`llm.models`),
ShinkaEvolve through its bandit model-selection layer.

### The AlphaEvolve pattern: Flash 80% + Pro 20%

The AlphaEvolve paper demonstrated that mixing a fast, cheap model with
a slower, more capable model produces better results than either model
alone. The cheap model handles the majority of iterations (broad
exploration), while the expensive model contributes occasional
high-quality breakthroughs (targeted exploitation).

A typical Revolver setup mirrors this pattern:

```bash
# Register the individual LLMs
revolver llm add flash-lite --provider google \
  --model gemini-2.5-flash-lite \
  --api-key-env GEMINI_API_KEY

revolver llm add pro --provider google \
  --model gemini-2.5-pro \
  --api-key-env GEMINI_API_KEY

# Create the ensemble
revolver llm ensemble create alphevo
revolver llm ensemble add alphevo --llm flash-lite --weight 0.8
revolver llm ensemble add alphevo --llm pro --weight 0.2 --temperature 0.5

# Launch a run with the ensemble (either backend)
revolver run --llm alphevo --iterations 100
```

### Weight recommendations

Weights control how often each model is sampled. Weights are
auto-normalized, so `0.8 + 0.2` and `4 + 1` are equivalent. Revolver warns
(but does not error) if weights do not sum to 1.0.

| Strategy | Cheap model weight | Expensive model weight | When to use |
|----------|-------------------|----------------------|-------------|
| Exploration-heavy | 0.8-0.9 | 0.1-0.2 | Most scenarios; maximize iterations per dollar |
| Balanced | 0.5-0.6 | 0.4-0.5 | When the cheap model produces too many invalid diffs |
| Quality-focused | 0.2-0.3 | 0.7-0.8 | Short runs where every iteration counts |

**Start with 80/20** and adjust based on the valid-diff rate. If the
cheap model's diffs are mostly invalid (e.g., < 30% valid), shift weight
toward the expensive model.

> Weights are honored on **OpenEvolve** and on **ShinkaEvolve under
> `--selection fixed`** only — under the Shinka adaptive bandit modes they
> are deliberately ignored with a warning. See the
> [three-strategy walkthrough](#cross-engine-ensemble-the-same-ensemble-on-three-selection-strategies)
> below.

### Per-model configuration

Each ensemble member can have its own `temperature` and `max_tokens`
overrides. These override the LLM registry defaults for that model
within the ensemble context only.

```bash
# Pro model with low reasoning_effort-friendly temperature
revolver llm ensemble add alphevo --llm pro --weight 0.2 \
  --temperature 0.5 --max-tokens 16384
```

Common per-model settings:

| Model type | Temperature | Max tokens | Notes |
|-----------|-------------|-----------|-------|
| Flash-Lite (cheap) | 0.7-1.0 | Default | Higher temperature for diversity |
| Pro (expensive) | 0.3-0.5 | 16384 | Lower temperature for reliable output |
| Thinking models | 0.5 | 32768 | Needs high `max_tokens` for reasoning budget |

> **Gemini Pro tip**: When using Gemini Pro in an ensemble, set its reasoning
> budget per member with the first-class flag —
> `revolver llm ensemble add <ensemble> --llm pro --weight 0.2 --reasoning-effort low` —
> so the expensive member thinks less without touching the cheap member. This
> is the canonical path; `--config-override llm.reasoning_effort=` is a
> non-ensemble escape hatch only. (Per-member effort is honored on OpenEvolve
> only — see the [asymmetries](#two-asymmetries-to-keep-in-mind) below.)

### Cost implications

Ensemble runs can dramatically reduce cost by routing most iterations
through cheap models. Approximate Gemini pricing as of early 2026 (provider
list prices — for your own budgeting):

| Model | Input cost (per 1M tokens) | Output cost (per 1M tokens) | Relative cost |
|-------|---------------------------|----------------------------|---------------|
| Flash-Lite | $0.075 | $0.30 | 1x (baseline) |
| Flash | $0.15 | $0.60 | 2x |
| Pro | $1.25 | $10.00 | ~36x |

With an 80/20 Flash-Lite/Pro ensemble over 500 iterations:
- ~400 iterations at Flash-Lite cost + ~100 at Pro cost
- Estimated 5-7x cheaper than running all 500 on Pro alone
- Quality benefit: Pro's occasional contributions lift the population

> **Revolver does not report cost (#300).** Cost estimation was removed:
> Revolver reports **tokens only** (`run info` shows the prompt/completion
> token breakdown, not a USD figure), because neither engine persists
> per-attempt or reasoning/thinking tokens, so no realistic cost is reachable.
> Use the per-model token counts above plus your provider console to reason
> about spend.

### Ensemble vs sequential resume

There are two ways to combine cheap and expensive models:

**Ensemble** (concurrent within a single run):
- Both models contribute to the same population simultaneously
- Pro injects high-quality solutions while Flash explores broadly
- Best for: single-phase optimization where you want continuous
  cross-pollination between model capabilities

```bash
revolver run --llm alphevo --iterations 500
```

**Sequential resume** (phased, separate runs):
- Phase 1: cheap model explores broadly, diversifying the population
- Phase 2: expensive model refines the best solutions found in Phase 1
- Best for: budget-constrained optimization where you want to maximize
  cheap exploration before spending on expensive refinement

```bash
# Phase 1: broad exploration with cheap model
revolver run --llm flash-lite --iterations 500

# Phase 2: refine with expensive model, resuming from Phase 1
revolver run resume <run-id> --llm pro --iterations 100
```

| Aspect | Ensemble | Sequential resume |
|--------|----------|-------------------|
| Model interaction | Concurrent, same population | Sequential, inherited population |
| Cost control | Controlled by weights | Controlled by iteration count per phase |
| Exploration/exploitation | Balanced throughout | Exploration-first, exploitation-second |
| Complexity | One run, one command | Two runs, manual phase transition |
| Traceability | Single run record with ensemble snapshot | Two run records with resume chain |

**Recommendation**: start with ensemble (simpler) unless you need
fine-grained budget control per phase. Sequential resume is particularly
useful when you want to explore with full-rewrite mode first, then
switch to diff-based mode for refinement.

### Cross-engine ensemble: the same ensemble on three selection strategies

The **same** registered ensemble runs on both backends, but *how* the
member weights and per-member reasoning effort are honored differs by
engine and selection strategy. This section walks through one concrete
ensemble across the three combinations. All commands below are
`--dry-run`-verified (they resolve and exit 0 without launching a run).

Setup — a two-member weighted ensemble with a per-member reasoning
effort on the expensive model:

```bash
# Register two Gemini models (both read GEMINI_API_KEY)
revolver llm add flash-lite --provider google \
  --model gemini-2.5-flash-lite --api-key-env GEMINI_API_KEY
revolver llm add pro --provider google \
  --model gemini-2.5-pro --api-key-env GEMINI_API_KEY

# Weighted ensemble: 80% cheap, 20% expensive; pro also thinks less
revolver llm ensemble create alphevo
revolver llm ensemble add alphevo --llm flash-lite --weight 0.8
revolver llm ensemble add alphevo --llm pro --weight 0.2 \
  --temperature 0.5 --reasoning-effort low
```

Three-way comparison (add `--dry-run` to inspect the resolved config
without launching):

```bash
# 1. OpenEvolve — static weighted sampler (the only OE ensemble mode)
revolver run --version v1.0 --llm alphevo --dataset train-small \
  --backend openevolve --selection fixed --iterations 100
#   → llm_models: gemini-2.5-flash-lite×0.8, gemini-2.5-pro×0.2
#     (weights become llm.models[].weight; per-member reasoning_effort honored)

# 2. ShinkaEvolve fixed — same weights, via FixedSampler.prior_probs
revolver run --version v1.0 --llm alphevo --dataset train-small \
  --backend shinka --selection fixed --iterations 100
#   → llm_dynamic_selection: fixed
#     llm_dynamic_selection_kwargs.prior_probs: [0.8, 0.2]  (weights honored)
#     llm_kwargs.reasoning_efforts: [low]  (see the asymmetry below)

# 3. ShinkaEvolve ucb — adaptive bandit; the SAME weights are ignored
revolver run --version v1.0 --llm alphevo --dataset train-small \
  --backend shinka --selection ucb --iterations 100
#   → llm_dynamic_selection: ucb  (learns arm weights from a uniform start)
#     Warning: ensemble weights (registry weights / --llm-weight) are ignored
#              under '--selection ucb' on the shinka backend …
```

`--selection` is capability-checked per backend (ADR-007 A2/A4):
OpenEvolve accepts `fixed` only (any adaptive value is rejected before the
run); ShinkaEvolve accepts `fixed | ucb | ucb1 | thompson`. Omitting
`--selection` defaults to `fixed` on both engines.

#### Two asymmetries to keep in mind

1. **Member weights are honored only under OE-weighted and Shinka-fixed.**
   Under any Shinka adaptive mode (`ucb`/`ucb1`/`thompson`), the bandit
   starts uniform and learns arm weights from observed rewards, so your
   configured weights (registry weights **or** `--llm-weight` overrides)
   are deliberately **ignored with a warning** — they are not silently
   applied. The shinka samplers expose **no per-arm prior**, so the bandit
   cannot be warm-started from your weights either. This matters most on
   **short runs (tens of generations)**: the bandit has too few
   observations to converge away from uniform, so prefer
   `--selection fixed` there — it is the only mode that actually applies
   your weights. Reserve the adaptive modes for longer runs, and use
   `fixed` whenever you want to pin the sampling mixture.

2. **Per-member `reasoning_effort` is OpenEvolve-only.** On OpenEvolve
   each `llm.models[]` entry carries its own `reasoning_effort`, so a
   Flash member and a Pro member can think at different levels.
   ShinkaEvolve exposes a **single global** `llm_kwargs.reasoning_efforts`
   pool with no per-member setting (ADR-007 A3.2), so Revolver collapses
   the members' efforts into one value: identical efforts merge silently;
   *disagreeing* efforts pick the **highest** level (never under-think)
   **with a warning**. On local/bridge members the setting is inert and is
   flagged as such. If per-member effort matters to your run, use the
   OpenEvolve backend.

> `--config-override` is the reserved escape hatch for backend-exclusive
> *structural* keys (OE `feature_dimensions`, Shinka `archive_size`, …); it
> is **not** the path for these common levers, and it cannot address array
> members such as per-member weight or reasoning effort — those are
> reachable only through `--llm-weight` / the ensemble member flags. A
> `--config-override key=value` whose key matches no field in the resolved
> backend's config schema is a no-op and is **warned** rather than silently
> accepted (spec §4.5).

---

## Operational levers (Revolver-side)

The levers in this section belong to Revolver itself, not to either engine —
they behave identically regardless of `--backend`.

### Timed-out instance policy (`evaluation.on_timeout`, `evaluation.timeout_score`)

Since v0.18, an instance that hits `evaluation.timeout_per_instance` during
evolution is **penalized by default**: it contributes
`evaluation.timeout_score` (default `0.0`, must be finite) to the program's
fitness mean instead of silently vanishing from it. This is a deliberate
fitness-landscape change — best-scores are lower but honest, and a program
that times out on hard instances now feels selection pressure. Both wrapper
templates implement the same policy, and both emit the reserved
`instances_valid`/`instances_total` coverage keys (never averaged into the
score) so `run info` can label its coverage.

- Restore the pre-0.18 survivor-mean: `evaluation.on_timeout: drop` in
  config.yaml, or `--config-override evaluation.on_timeout=drop`.
- Lower-is-better metrics: the default `0.0` assumes a higher-is-better
  score around positive values — where `timeout_score` acts as a floor and
  *negative is good*, pick a value genuinely worse than any real instance
  score.
- Values are validated at run **and** dry-run (`penalize|drop`, finite
  score): a typo fails fast instead of being silently ignored.
- The policy is baked into the generated wrapper at launch; **resume
  inherits the parent run's policy** without re-supplying the overrides.
- A run with zero timeouts scores identically under both policies.

### Evaluation thread caps (`REVOLVER_EVAL_NUM_THREADS`)

Revolver's own evaluation paths — post-run training eval, `revolver eval`,
`benchmark`, `problem test`, and the run pre-flight — each run the evaluator
in an isolated subprocess. Since v0.17.1 that subprocess is **killed at the
per-instance timeout** (SIGTERM to its process group, then SIGKILL after a
3 s grace — no leaked workers), and receives a **numeric thread cap** so a
single evaluation cannot oversubscribe every core with BLAS/OpenMP threads
(the classic symptom: a program evolved under ShinkaEvolve's capped
evolution-phase evals then *times out* in the uncapped post-run eval).

The cap injects the standard variable family (`OMP_NUM_THREADS`,
`OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`,
`VECLIB_MAXIMUM_THREADS`, `BLIS_NUM_THREADS`, `GOTO_NUM_THREADS`, …) plus
`OMP_DYNAMIC=FALSE`, `MKL_DYNAMIC=FALSE`, `OMP_WAIT_POLICY=PASSIVE`.

Resolution order:

1. **User env wins**: if *any* cap variable is already set in your
   environment (e.g. `OMP_NUM_THREADS=2`), Revolver injects **nothing**.
2. **`REVOLVER_EVAL_NUM_THREADS=N`** caps each eval subprocess at `N`
   threads; **`0` disables the cap** (escape hatch for a legitimate single
   big-BLAS evaluation on a dedicated machine).
3. **Default**: `max(1, cpu_count // 2)`.

One stderr line announces the applied cap per process:
`[revolver] numeric thread cap per eval process: N (REVOLVER_EVAL_NUM_THREADS=0 to disable)`.

```bash
# Cap each eval subprocess at 4 threads
REVOLVER_EVAL_NUM_THREADS=4 revolver eval --solution my-sol --dataset eval-set

# Uncapped (dedicated machine, one heavy numeric eval at a time)
REVOLVER_EVAL_NUM_THREADS=0 revolver eval --solution my-sol --dataset eval-set
```

> Note: this cap applies to **Revolver's eval subprocesses**. During the
> evolution phase, each backend manages its own evaluation workers
> (ShinkaEvolve's scheduler injects an equivalent cap family itself).

### Token accounting (and why there is no cost figure)

`run info` reports a prompt / completion / total **token** breakdown, but
**no cost** (#300). The breakdown counts the LLM responses recorded for
stored programs only:

- **Retry and failed-attempt tokens are not counted.** Both engines keep
  only the last response per program; intermediate retries are not summed.
- **Reasoning / thinking tokens are not counted.** Thinking-capable models
  (e.g. Gemini, Claude) bill large hidden reasoning-token totals that the
  engines never persist to disk — so they are unrecoverable for reporting.

Cost was removed because no realistic figure is reachable from the persisted
data and API pricing drifts. For thinking-model spend, **watch the provider
console** rather than relying on Revolver's token counts.

### Subscription-backed and single-GPU local endpoints

A `--source local` endpoint is often a **serialized** backend: a single GPU
serving one request at a time, or a subscription-backed local
OpenAI-compatible shim that processes one call at a time. Fanning out parallel generation requests
to such an endpoint
queues them rather than running them concurrently — and can trip rate limits.
Pin concurrency to 1:

- **OpenEvolve path** — Revolver **auto-pins** `evaluator.parallel_evaluations`
  to `1` whenever the run's LLM has `--source local` and you did not pass
  `--parallel` explicitly, so the engine issues one evaluation (and therefore
  one LLM call) at a time. If you set `--parallel >1` on a local endpoint
  Revolver honours it but emits a warning; a `--config-override
  evaluator.parallel_evaluations=N` always wins over the auto-pin:

  ```bash
  # LLM registered with --source local → auto-pinned to 1 (no --parallel needed):
  revolver run --llm codestral-local

  # Force concurrency on a local endpoint that can take it (warns, honoured):
  revolver run --llm codestral-local --parallel 3
  ```

  A `--dry-run` shows the resolved `parallel_evaluations` value. See also
  [Slow local endpoints & request timeout](#slow-local-endpoints--request-timeout)
  — Revolver already raises the per-call timeout to 600 s for
  `--source local` LLMs on the OpenEvolve path.

- **ShinkaEvolve path** — Revolver **auto-pins** `job_config.max_proposal_jobs`
  to `1` whenever the run's LLM has `--source local`, so Shinka does not launch
  several proposal jobs against a serialized endpoint. You can override the
  auto-pin explicitly:

  ```bash
  # Allow 3 concurrent proposal jobs against a local endpoint that can take it:
  revolver run --backend shinka --llm codestral-local \
    --config-override job_config.max_proposal_jobs=3
  ```

  A `--dry-run` shows the resolved `max_proposal_jobs` value under the Shinka
  backend extras.

> **Subscription spend is not tracked by Revolver.** When you drive a provider
> subscription through a local OpenAI-compatible shim, the spend is recorded
> on the **provider console**, not by Revolver. Revolver does not capture a
> non-standard `total_cost_usd` field returned by such a shim — watch the
> provider console for subscription usage.

> **Token totals under-count on subscription-backed local endpoints.** Beyond
> cost, the prompt/completion **token** counts that `run info` reports are also
> understated for `--source local` shim endpoints. Such a shim returns an
> OpenAI `usage` block that omits the hidden context its upstream client
> injects per call and the model's thinking tokens, so a call billed as
> hundreds of real tokens may report only a handful. This is the same family of
> gap as the reasoning/thinking caveat in
> [Token accounting](#token-accounting-and-why-there-is-no-cost-figure) above.
> `run info` prints an explicit caveat for `--source local` runs — track real
> consumption on the **provider console**, not Revolver's token totals.

---

## OpenEvolve knob reference

OpenEvolve organizes its configuration in a flat YAML schema with nested
sections: top-level keys (`max_iterations`, `diff_based_evolution`,
`max_code_length`, `checkpoint_interval`), `llm:`, `database:` (the
MAP-Elites archive), and `evaluator:`. The `evaluation:` section in a
scaffolded `config.yaml` is Revolver-specific (per-instance eval timeout) and
is not passed to the engine.

### MAP-Elites feature dimensions

MAP-Elites is the quality-diversity algorithm at the heart of OpenEvolve.
Instead of keeping only the single best program, it maintains a *map* of
programs indexed by *feature dimensions* — behavioral characteristics that
distinguish programs from each other.

#### What are feature dimensions?

A feature dimension is a numeric metric that partitions the solution space.
For example:

- **Code length** (number of lines) — short vs. long solutions
- **Execution time** — fast vs. slow solutions
- **Memory usage** — lightweight vs. memory-intensive solutions

Each unique combination of discretized feature values defines a *cell* in the
map. MAP-Elites keeps the best program in each cell, preserving diversity
across the feature space.

#### Default behavior

By default, OpenEvolve builds a 2D MAP-Elites grid on its two built-in
feature dimensions, `complexity` and `diversity` — the default
`feature_dimensions: ["complexity", "diversity"]`. `complexity` tracks
program length and `diversity` tracks how different a program is from the
rest of the population; neither requires anything from your evaluator.

#### Configuring feature dimensions

`feature_dimensions` is a **list of metric names** (strings) — not integer
indices. Each name selects a MAP-Elites grid axis. Valid names are the
OpenEvolve built-ins `complexity`, `diversity`, `score`, plus **any metric
name your evaluator's `evaluate()` returns**. Use `--config-override` to
choose them:

```bash
# Use two feature dimensions by name: the built-in score + a custom metric
revolver run --llm my-llm \
  --config-override 'database.feature_dimensions=["score","execution_time"]'
```

> **Note**: OpenEvolve organizes these parameters under the `database` namespace
> in its configuration. Always use `database:` in YAML or `database.` prefix
> with `--config-override`. If you place them at the top level, Revolver will
> warn you at `problem version` time.

If your evaluator returns:

```python
return {
    "score": combined_score,         # OpenEvolve built-in name
    "execution_time": elapsed,       # custom metric
    "memory_usage": peak_memory_mb,  # custom metric
}
```

Then `database.feature_dimensions=["score","execution_time"]` creates a 2D map
with `score` on one axis and `execution_time` on the other. This encourages
OpenEvolve to find diverse programs: some that are fast, some that score high,
and some that balance both.

`feature_bins` (int, or a `{dimension: bins}` dict; default `10`) sets how
many buckets each axis is divided into.

#### When to add feature dimensions

| Scenario | Recommendation |
|----------|----------------|
| Single-objective optimization (maximize score) | The default `["complexity","diversity"]` is fine — it preserves behavioral diversity while the score improves |
| You care about multiple trade-offs (speed vs. quality) | Swap in your own metric names, e.g. `["score","execution_time"]` |
| Evaluator returns many metrics | Pick the 2-3 most meaningful metric names as dimensions |
| Very few iterations (< 100) | Stick with a single dimension, e.g. `["score"]` — not enough iterations to fill a 2D map |

> **Note**: More dimensions means a larger map with more cells to fill. With
> too many dimensions and too few iterations, most cells stay empty and
> MAP-Elites degrades to near-random search.

### Islands

#### Default settings

| Parameter | Default | Config key |
|-----------|---------|------------|
| Number of islands | 5 | `database.num_islands` |
| Migration interval | 50 iterations | `database.migration_interval` |
| Topology | Ring | (hardcoded in OpenEvolve) |

In ring topology, island 0 migrates to island 1, island 1 to island 2, and
so on, with the last island migrating back to island 0. Each island maintains
its own MAP-Elites map and explores different regions of the solution space
(see [Islands and migration](#islands-and-migration) for the concept).

#### Tuning islands

```bash
# Reduce to 2 islands for short runs
revolver run --llm my-llm --iterations 50 \
  --config-override database.num_islands=2

# Increase to 8 islands for long runs with diverse exploration
revolver run --llm my-llm --iterations 2000 \
  --config-override database.num_islands=8

# Adjust migration frequency
revolver run --llm my-llm \
  --config-override database.migration_interval=100
```

| Scenario | Islands | Migration interval | Rationale |
|----------|---------|-------------------|-----------|
| Quick sanity check (50 iters) | 2 | 25 | Few iterations; more islands = wasted diversity |
| Moderate run (500 iters) | 5 (default) | 50 (default) | Enough iterations for ~10 migrations per island |
| Long exploration (2000+ iters) | 5-8 | 50-100 | More islands = broader search; migrations every 50-100 iters |
| Single-strategy focus | 1 | N/A | No islands, no migration — pure single-population MAP-Elites |

**Rule of thumb**: each island should see at least 5-10 migrations during
the run. If `iterations / migration_interval < 5`, reduce the number of
islands or lower the migration interval.

### Parallel evaluations

The `evaluator.parallel_evaluations` parameter controls how many candidate
programs are evaluated concurrently. This is a key performance lever, but its
effectiveness depends on your LLM backend.

#### Setting via CLI

```bash
# Run with 4 parallel evaluations
revolver run --llm my-llm --parallel 4

# Or via config override
revolver run --llm my-llm \
  --config-override evaluator.parallel_evaluations=4
```

#### When parallel evaluations help

| LLM backend | Recommended `--parallel` | Why |
|-------------|-------------------------|-----|
| Remote API (Anthropic, OpenAI, Google) | 4-8 | API calls are network-bound; parallelism overlaps latency |
| Local Ollama (single GPU) | 1-2 | GPU serializes inference; more parallelism = more memory, not more throughput |
| Local Ollama (multi-GPU) | Match GPU count | Each request can go to a different GPU |
| vLLM or TGI (batching server) | 4-8 | Batching server handles concurrency internally |

**Cost warning**: with remote APIs, higher parallelism increases throughput
but does not reduce token cost. You pay for the same total tokens regardless
of parallelism. It only reduces wall-clock time.

```bash
# Fast API run: 8 parallel evals, 500 iterations
revolver run --llm claude-sonnet --iterations 500 --parallel 8

# Local Ollama: keep parallelism low
revolver run --llm codestral-local --iterations 50 --parallel 1
```

### Slow local endpoints & request timeout

On the **OpenEvolve** backend, every LLM call is routed through Revolver's
HTTP `TokenCountingProxy` (token accounting). OpenEvolve's own OpenAI client
defaults to a **60-second** request timeout. A slow local endpoint — for
example a subscription-backed local OpenAI-compatible shim, where a
single call can take 50–530 s — therefore aborts at 60 s, triggers a retry
storm, and ultimately fails with a proxy `BrokenPipeError` (the late upstream
response is written into an already-closed connection).

**Default behavior (#307)**: when an OpenEvolve run uses an LLM registered
with `--source local` and **no explicit `--timeout`**, Revolver raises the
injected `llm.timeout` to **600 s** so slow local endpoints survive. Remote
API models keep OpenEvolve's 60-s default (they are fast and a long hang is
better surfaced as an error).

Precedence (last wins): OpenEvolve default → Revolver's 600 s local default →
the LLM entry's `--timeout` → `--config-override llm.timeout=…`.

```bash
# Override the per-call timeout on a slow local endpoint explicitly:
revolver llm update my-bridge --timeout 600

# Or for a single run, via config override:
revolver run --version v1.0 --llm my-bridge --dataset train \
  --config-override llm.timeout=900
```

> Note: this applies to the OpenEvolve path only. The **ShinkaEvolve**
> backend does not use the HTTP proxy (it reads `programs.sqlite`), so the
> 60-s trap does not apply there — shinka's own client default is **1200 s**,
> and the same registry `--timeout` maps onto it: see
> [LLM request timeout](#llm-request-timeout-llm_timeout) in the Shinka knob
> reference (#320).

### Multi-objective setup

OpenEvolve supports multi-objective optimization through MAP-Elites feature
dimensions combined with custom evaluator metrics. Instead of optimizing a
single score, you can explore trade-offs between competing objectives.

#### Defining custom metrics in your evaluator

Your evaluator must return a dictionary with named metrics. You reference
those metric names directly in `feature_dimensions`:

```python
import time

def evaluate(program_output, dataset_path):
    start = time.time()
    # ... run and validate the program output ...
    elapsed = time.time() - start

    return {
        "score": quality_score,        # primary objective
        "execution_time": elapsed,     # secondary objective
    }
```

#### Configuring multi-objective search

Use `feature_dimensions` to tell MAP-Elites which metric names define the map:

```bash
# Optimize score while exploring execution_time trade-offs
revolver run --llm my-llm --iterations 500 \
  --config-override 'database.feature_dimensions=["score","execution_time"]'
```

This creates a 2D map where:
- One axis is the `score` metric
- The other axis is `execution_time`

MAP-Elites will keep the best program in each (score, execution_time) cell,
giving you a *Pareto front* of solutions: some fast but lower-quality, some
high-quality but slower, and some balanced.

#### Example: TSP with execution time

For a TSP problem where the evaluator returns both solution quality and
computation time:

```bash
# Register the LLM
revolver llm add claude-sonnet --provider anthropic \
  --model claude-sonnet-4-20250514 \
  --api-key-env ANTHROPIC_API_KEY \
  --temperature 0.7

# Run with multi-objective configuration
revolver run --llm claude-sonnet --iterations 500 \
  --config-override 'database.feature_dimensions=["score","execution_time"]' \
  --config-override database.num_islands=5 \
  --parallel 4
```

After the run, extract and compare solutions:

```bash
# Extract the best overall solution
revolver solution extract --run <run-id> --alias best-overall

# Inspect the solution code
revolver solution show best-overall
```

#### Guidelines for multi-objective setup

- Keep the number of objectives small (2-3). More objectives need
  exponentially more iterations to fill the map.
- Feature dimensions shape the MAP-Elites grid, not the ranking. OpenEvolve
  ranks programs by its `combined_score`, so pick dimension names that
  capture the trade-offs you care about (e.g. `score` vs `execution_time`).
- Use `--iterations 500+` for 2D maps, `--iterations 2000+` for 3D maps.
- The evaluator must return consistent metric names across all evaluations.

### Recommended profiles

These profiles combine the parameters above into ready-to-use OpenEvolve
configurations for common scenarios. Adapt them to your problem and LLM.

#### Quick sanity check — 50 iterations

Minimal exploration. Useful to verify that your evaluator works, the LLM
produces valid diffs, and the scoring function is reasonable. Do not expect
significant optimization at this scale.

```bash
revolver run --llm my-llm --iterations 50 \
  --config-override database.num_islands=2 \
  --config-override database.migration_interval=25 \
  --temperature 0.5 \
  --parallel 1
```

**What to expect**: 2 islands, 2 migrations total. MAP-Elites barely starts
filling cells. Closer to random search than true evolution. Good for catching
setup errors early.

#### Moderate evolution — 500 iterations

MAP-Elites starts being useful. The population diversifies, and migration
spreads good ideas across islands. A solid choice for initial experimentation
with a new problem.

```bash
revolver run --llm my-llm --iterations 500 \
  --config-override database.num_islands=5 \
  --config-override database.migration_interval=50 \
  --temperature 0.7 \
  --parallel 4
```

**What to expect**: 5 islands, ~10 migrations each. The map fills with
diverse solutions. You should see measurable improvement over the initial
program. With API models at `--parallel 4`, expect 10-30 minutes wall-clock
depending on the evaluator.

#### Full evolution — 2000+ iterations

Full-scale evolutionary search. Multiple migration waves refine and diversify
the population. Best for complex problems where the solution space is large.

```bash
revolver run --llm my-llm --iterations 2000 \
  --config-override database.num_islands=8 \
  --config-override database.migration_interval=100 \
  --config-override 'database.feature_dimensions=["score","execution_time"]' \
  --temperature 0.8 \
  --parallel 8
```

**What to expect**: 8 islands, ~20 migrations each, 2D MAP-Elites map.
Extensive exploration of the solution space. The LLM has enough iterations
to discover and refine complex algorithmic improvements (e.g., 2-opt, or-opt,
simulated annealing for TSP). With API models at `--parallel 8`, expect
1-4 hours wall-clock.

#### Profile comparison

| Parameter | 50 iters | 500 iters | 2000+ iters |
|-----------|----------|-----------|-------------|
| `database.num_islands` | 2 | 5 | 5-8 |
| `database.migration_interval` | 25 | 50 | 50-100 |
| `database.feature_dimensions` | `["complexity","diversity"]` | `["complexity","diversity"]` | `["score","execution_time"]` |
| `temperature` | 0.5 | 0.7 | 0.8 |
| `parallel` | 1 | 4 | 4-8 |
| Expected improvement | Negligible | Moderate | Significant |
| Use case | Setup validation | Initial experiments | Production optimization |

### OpenEvolve quick reference

All parameters can be set via `--config-override key=value` on `revolver run`.
Dotted keys reach nested config sections (e.g., `evaluator.parallel_evaluations`).

| Parameter | Config key | CLI shorthand | Default |
|-----------|-----------|---------------|---------|
| Islands | `database.num_islands` | `--config-override database.num_islands=N` | 5 |
| Migration interval | `database.migration_interval` | `--config-override database.migration_interval=N` | 50 |
| Feature dimensions | `database.feature_dimensions` | `--config-override 'database.feature_dimensions=["score","execution_time"]'` | `["complexity","diversity"]` |
| Population size | `database.population_size` | `--config-override database.population_size=N` | 1000 |
| Parallel evaluations | `evaluator.parallel_evaluations` | `--parallel N` | 1 |
| Temperature | `llm.temperature` | `--temperature F` | Model default |
| Iterations | `max_iterations` | `--iterations N` | From config.yaml |
| Checkpoint interval | `checkpoint_interval` | `--config-override checkpoint_interval=N` | `max(1, min(100, iterations//10))` when unset (v0.18) |
| Cascade evaluation | `evaluator.cascade_evaluation` | `--config-override evaluator.cascade_evaluation=true` | `false` (Revolver default) |
| Diff-based evolution | `diff_based_evolution` | `--rewrite-mode` (sets to `false`) | `true` |
| Max code length | `max_code_length` | `--rewrite-mode` (sets to `50000`) | 10000 |
| Per-call LLM timeout | `llm.timeout` | `revolver llm add/update <name> --timeout N` (registry) | 60 s (auto-raised to 600 s for `--source local`) |
| Ensemble models | `llm.models` | `--llm <ensemble-name>` | N/A (auto-generated) |
| Reasoning effort | `llm.reasoning_effort` | `revolver llm add/update <name> --reasoning-effort low` (registry) or `llm ensemble add --reasoning-effort low` (per member) | Model default |
| Eval timeout (Revolver) | `evaluation.timeout_per_instance` | (config.yaml, Revolver-specific) | 30 s |
| Timeout policy (Revolver) | `evaluation.on_timeout` / `evaluation.timeout_score` | (config.yaml or `--config-override`, Revolver-specific) | `penalize` / `0.0` since v0.18 (`drop` restores pre-0.18) |

---

## ShinkaEvolve knob reference

ShinkaEvolve configuration is organized in three sections that map 1:1 to the
engine's dataclasses, plus a Revolver-specific `evaluation` section:

```yaml
evo_config:    # shinka.core.EvolutionConfig — generations, patch modes, LLM sampling
  num_generations: 10
  patch_types: [diff, full]
  patch_type_probs: [0.6, 0.4]
  max_patch_attempts: 10
  llm_kwargs:
    max_tokens: 16384

db_config:     # shinka.database.DatabaseConfig — islands, archive, migration
  num_islands: 2
  archive_size: 40
  migration_interval: 10

job_config:    # shinka.launch.LocalJobConfig — local evaluation job settings
  conda_env: null

evaluation:    # Revolver-specific (not passed to ShinkaEvolve)
  timeout_per_instance: 30  # seconds
```

`--config-override` uses the same dotted paths (e.g.
`--config-override db_config.num_islands=4`). Shinka-only structural keys are
exactly what the escape hatch is for.

### Islands and the elite archive

ShinkaEvolve has **no MAP-Elites grid** (see
[Quality-diversity: grid vs archive](#quality-diversity-grid-vs-archive)).
Diversity comes from islands plus a bounded **elite archive** of the best
programs, from which parents are sampled (weighted parent selection —
`db_config.parent_selection_strategy`, engine default `weighted`).

| Parameter | Scaffold default | Config key |
|-----------|-----------------|------------|
| Number of islands | 2 | `db_config.num_islands` |
| Elite archive size | 40 | `db_config.archive_size` |
| Migration interval | 10 generations | `db_config.migration_interval` |

```bash
# Broader search on a longer run: more islands, larger archive
revolver run --backend shinka --llm my-llm --iterations 200 \
  --config-override db_config.num_islands=4 \
  --config-override db_config.archive_size=60
```

The same rule of thumb as OpenEvolve applies: each island should see several
migrations during the run — with the default `migration_interval=10`, even a
50-generation run migrates 5 times.

### Bandit selection (`--selection`, `--selection-kwarg`)

ShinkaEvolve picks which ensemble member serves each generation through a
selection strategy — this is where the engine goes beyond OpenEvolve's static
weighted sampling:

| `--selection` | Sampler | Weights honored? | When to use |
|---|---|---|---|
| `fixed` (default) | `FixedSampler` with `prior_probs` from your weights | **Yes** | Short runs; pinning the mixture; apples-to-apples vs OE |
| `ucb` | `AsymmetricUCB` bandit | No (uniform start, warned) | Longer runs; let observed rewards drive model choice |
| `ucb1` | Alias of `ucb` (same `AsymmetricUCB` class) | No | Same as `ucb` |
| `thompson` | `ThompsonSampler` bandit | No | Longer runs; Bayesian alternative to UCB |

`--selection-kwarg key=value` (repeatable) tunes the **selected** sampler.
Shinka spreads these kwargs verbatim into the sampler's constructor, so
Revolver validates them per strategy — a kwarg the selected sampler does not
accept is dropped with a warning instead of crashing the engine
(`--dry-run` surfaces the resolved kwargs, so check there first):

| Strategy | Accepted `--selection-kwarg` keys |
|---|---|
| `fixed` | *(none — weights come from the registry / `--llm-weight`)* |
| `ucb` / `ucb1` | `exploration_coef`, `epsilon`, `auto_decay`, `shift_by_baseline`, `shift_by_parent`, `adaptive_scale`, `asymmetric_scaling`, `exponential_base`, `cost_aware_coef`, `cost_exploration_coef`, `cost_power`, `cost_ref_percentile` |
| `thompson` | `epsilon`, `prior_alpha`, `prior_beta`, `auto_decay`, `shift_by_baseline`, `shift_by_parent`, `adaptive_scale`, `asymmetric_scaling`, `exponential_base` |

```bash
# Adaptive selection with a higher exploration coefficient
revolver run --backend shinka --llm alphevo --iterations 300 \
  --selection ucb --selection-kwarg exploration_coef=2.0
```

> **`cost_aware_coef` defaults to 0 in Revolver** (ShinkaEvolve's own default
> is 0.5): with a flat-rate subscription or a local bridge, per-model cost is
> undifferentiated and cost-aware arm scoring would be noise. Set
> `--selection-kwarg cost_aware_coef=0.5` explicitly to restore the engine's
> cost-aware behavior on metered API fleets.

See the
[three-strategy walkthrough](#cross-engine-ensemble-the-same-ensemble-on-three-selection-strategies)
for how weights and reasoning effort behave under each strategy.

### Patch generation (`patch_types`, `max_patch_attempts`)

Each generation, ShinkaEvolve samples a patch mode from
`evo_config.patch_types` with probabilities `patch_type_probs`. The Revolver
default is `["diff", "full"]` with `[0.6, 0.4]` — a built-in mix of
incremental edits and full rewrites. `--rewrite-mode` forces
`["full"]`/`[1.0]`; a custom mix goes through the config:

```bash
# Mostly diffs, occasional full rewrite
revolver run --backend shinka --llm my-llm \
  --config-override 'evo_config.patch_types=["diff","full"]' \
  --config-override 'evo_config.patch_type_probs=[0.8,0.2]'
```

`evo_config.max_patch_attempts` caps how many times the engine re-asks the
LLM when a patch is malformed before giving up on the generation.
ShinkaEvolve's own default is **1** — a single malformed patch loses the
whole generation, which is the dominant failure mode with cheap models —
so **Revolver defaults it to 10** (matching ShinkaEvolve's example configs).
An explicit config.yaml value or `--config-override` still wins.

### LLM sampling pool (`llm_kwargs`)

`evo_config.llm_kwargs` holds **global sampling pools** shared by all
ensemble members — this is the deep difference from OpenEvolve's per-member
`llm.models[]` entries:

- **`max_tokens`** — output token budget per query. Revolver defaults to
  **16384**: a smaller budget starves thinking-capable models, which spend it
  on reasoning and return empty content. Raising it further increases
  thinking-token spend.
- **`temperatures`** — a pool sampled per query. Revolver writes a
  single-valued pool `[F]` from `--temperature`/the registry; when nothing is
  set, the engine samples from its own default pool `[0.0, 0.5, 1.0]`.
- **`reasoning_efforts`** — a **single global pool** with no per-member
  setting (ADR-007 A3.2). Set it through the registry
  (`revolver llm add/update --reasoning-effort`, `llm ensemble add
  --reasoning-effort`); Revolver projects the members' efforts into one
  global value — identical efforts merge silently, disagreeing efforts pick
  the **highest** level with a warning. Do not set `reasoning_efforts`
  directly in config.yaml: the registry projection owns the key, and Revolver
  warns when a config-path value ends up inert. Also note the setting is a
  **no-op for local/bridge models**, which Shinka classes as non-reasoning.

### Proposal concurrency (`max_proposal_jobs`)

`job_config.max_proposal_jobs` bounds how many LLM proposal jobs run
concurrently (engine default: 6). This is the ShinkaEvolve concurrency lever
— `--parallel` has **no effect** on this backend (Revolver warns; evaluation
jobs are engine-managed).

Revolver auto-pins it to **1** for `--source local` LLMs (serialized
endpoints); override explicitly when your endpoint can take more:

```bash
revolver run --backend shinka --llm codestral-local \
  --config-override job_config.max_proposal_jobs=3
```

### LLM request timeout (`llm_timeout`)

ShinkaEvolve hard-codes its per-request LLM client timeout to **1200 s**
(20 min) with no config or env override, and wraps every call in a
multi-layer retry stack — a stalled endpoint can therefore wedge a run for
hours while the log freezes at `==> QUERYING` (#320). Revolver maps the
registry's neutral per-call timeout onto this backend: when the run's LLM
(or any ensemble member) is registered with `--timeout N`, Revolver sets
shinka's client timeout to that value for the duration of the run and
restores it afterwards. For ensembles the **maximum** over the members' set
timeouts wins (conservative — the slowest member is never truncated). When
no member sets `--timeout`, the engine default (1200 s) is left untouched.

```bash
# Fail fast on a wedge-prone local endpoint: cap each LLM request at 5 min
revolver llm update qwen-local --timeout 300
revolver run --backend shinka --llm qwen-local --iterations 100
```

A `--dry-run` shows the resolved value as `llm_timeout` under the Shinka
backend extras; `--config-override llm_timeout=N` overrides it for a single
run.

> **Honest limits.** This lever caps the **per-attempt** stall — a dead
> endpoint now surfaces as retry errors within roughly the configured
> timeout instead of 20-minute cliffs — but shinka 0.0.7 bakes its retry
> backoff budget (`max_time=6000` s) at import time, so the **total** worst
> case across the full retry stack stays hours-long until upstream exposes
> the request timeout and retry budget as configuration (the stall spike, backlog row 320; filed
> upstream as [SakanaAI/ShinkaEvolve#143](https://github.com/SakanaAI/ShinkaEvolve/issues/143)).

### Novelty rejection

ShinkaEvolve's signature diversity mechanism: candidate programs are
embedded, compared to existing programs, and candidates that are too similar
(`evo_config.code_embed_sim_threshold`, engine default 0.99) are rejected and
resampled, up to `evo_config.max_novelty_attempts` (engine default 3) times.

**Revolver disables it by default** (`evo_config.embedding_model: null`) so
local-only runs never require an OpenAI embedding key. To enable it on an
API-keyed setup:

```bash
revolver run --backend shinka --llm my-llm \
  --config-override evo_config.embedding_model=text-embedding-3-small
# Requires OPENAI_API_KEY for the embedding calls.
```

### ShinkaEvolve quick reference

| Parameter | Config key / flag | Default (Revolver) | Notes |
|-----------|------------------|--------------------|-------|
| Generations | `--iterations N` → `evo_config.num_generations` | 10 (scaffold) | Engine default is 50 |
| Islands | `db_config.num_islands` | 2 | |
| Elite archive | `db_config.archive_size` | 40 | No MAP-Elites grid |
| Migration interval | `db_config.migration_interval` | 10 | |
| Selection strategy | `--selection {fixed,ucb,ucb1,thompson}` | `fixed` | Weights honored under `fixed` only |
| Sampler kwargs | `--selection-kwarg k=v` | `cost_aware_coef=0` on ucb/ucb1 | Validated per strategy; `--dry-run` surfaces them |
| Member weights | registry weights / `--llm-weight model=w` | — | Ignored + warned under adaptive modes |
| Patch modes | `evo_config.patch_types` / `patch_type_probs` | `["diff","full"]` / `[0.6,0.4]` | `--rewrite-mode` → `["full"]` |
| Patch attempts | `evo_config.max_patch_attempts` | 10 | Engine default is 1 |
| Max tokens | `evo_config.llm_kwargs.max_tokens` | 16384 | Thinking models need the headroom |
| Temperature | `--temperature F` → `llm_kwargs.temperatures=[F]` | Engine pool `[0.0,0.5,1.0]` when unset | |
| Reasoning effort | registry `--reasoning-effort` → `llm_kwargs.reasoning_efforts` | Model default | Global pool; highest wins on disagreement; inert for local/bridge |
| Proposal jobs | `job_config.max_proposal_jobs` | Engine default 6; auto-pinned to 1 for `--source local` | `--parallel` is a no-op here |
| Per-call LLM timeout | registry `--timeout` → `llm_timeout` | Engine default 1200 s | Ensemble: max over set member timeouts; caps the per-attempt stall only (#320) |
| Timeout policy (Revolver) | `evaluation.on_timeout` / `evaluation.timeout_score` | `penalize` / `0.0` since v0.18 | `drop` restores pre-0.18 survivor-mean; backend-neutral (see Operational levers) |
| Novelty rejection | `evo_config.embedding_model` | `null` (disabled) | Enable with an OpenAI embedding model + key |
| Spend cap | `evo_config.max_api_costs` | `null` (no cap) | Hard USD cap enforced by the engine |
| Eval timeout (Revolver) | `evaluation.timeout_per_instance` | 30 s | Revolver-specific section |

---

## Known issues

### Engine `best_score` is a single, possibly optimistic evaluation

The `best_score` reported by the evolution engines (and displayed by
`revolver run info`) is the maximum over *single* engine-side evaluations
of each candidate program. Two effects can inflate it:

- **Evaluation noise** — `max()` over noisy single evaluations picks the
  lucky ones.
- **Timeout survivorship** (only with `evaluation.on_timeout: drop`) — in
  drop mode the engine-side evaluation averages over the dataset instances
  that *completed* within the per-instance timeout, so a program that only
  finishes its easy instances can score higher than one evaluated on all of
  them. As of v0.18 the default is penalize: a timed-out instance
  contributes `evaluation.timeout_score` (default `0.0`) to the mean.

The noise effect remains: treat the engine `best_score` as an
evolution-pressure signal, not a reportable result. `run info` now labels
it "(engine, single eval)" next to a coverage-labeled post-eval mean —
report that mean, or **re-score the saved best solution with `revolver
eval` (which runs every instance) and report that number.**

### Bandit selection cannot be warm-started (shinka)

The shinka samplers (`ucb`/`ucb1`/`thompson`) expose no per-arm prior, so
ensemble weights cannot seed the bandit — it always starts uniform (see
the [ensemble asymmetries](#two-asymmetries-to-keep-in-mind) above). Follow
the in-run warning: for short runs, prefer `--selection fixed` to apply
weights.

---

## Checklist

Before launching a tuned run:

- [ ] `--dry-run` inspected: resolved config matches your intent on the selected backend
- [ ] Temperature is appropriate for the LLM size (lower for small models)
- [ ] Iteration count gives each island several migrations
- [ ] A quick sanity run (~50 iterations) passed without errors
- [ ] Ensemble weights sum to ~1.0 (`revolver llm ensemble info` to verify)
- [ ] Each ensemble member LLM is registered and has valid API key env var
- [ ] **OpenEvolve**: evaluator returns all metrics needed for `feature_dimensions`
- [ ] **OpenEvolve**: `--parallel` matches the LLM backend (high for API, low for local)
- [ ] **OpenEvolve**: `feature_dimensions` count is appropriate for the iteration budget
- [ ] **ShinkaEvolve**: `--selection fixed` if you want the ensemble weights actually applied (short runs especially)
- [ ] **ShinkaEvolve**: `max_proposal_jobs` matches your endpoint's real concurrency
- [ ] **ShinkaEvolve**: registry `--timeout` set on wedge-prone (slow local) LLMs — caps the per-attempt stall (#320)
