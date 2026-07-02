# Tuning OpenEvolve Configuration

Practical guide for tuning OpenEvolve parameters via the Revolver CLI.
Covers MAP-Elites feature dimensions, islands, parallelism, temperature,
and recommended profiles for different iteration budgets.

## Overview

OpenEvolve exposes dozens of configuration knobs. Most have sensible defaults,
but a few have significant impact on optimization quality and cost. This guide
focuses on the parameters you are most likely to tune through `revolver run`
flags and `--config-override`.

> **Backend scope**: this guide applies to the default **OpenEvolve** backend. The ShinkaEvolve backend (`--backend shinka`) uses a different `config.yaml` shape (`evo_config`/`db_config`/`job_config`) — these keys and overrides do not apply there; a dedicated Shinka tuning guide is planned (S15).

**Key principle**: OpenEvolve is an *evolutionary* system. It needs enough
iterations to explore, diversify, and converge. Tuning the parameters below
determines the balance between exploration breadth, exploitation depth, and
wall-clock cost.

---

## MAP-Elites feature dimensions

MAP-Elites is the quality-diversity algorithm at the heart of OpenEvolve.
Instead of keeping only the single best program, it maintains a *map* of
programs indexed by *feature dimensions* — behavioral characteristics that
distinguish programs from each other.

### What are feature dimensions?

A feature dimension is a numeric metric that partitions the solution space.
For example:

- **Code length** (number of lines) — short vs. long solutions
- **Execution time** — fast vs. slow solutions
- **Memory usage** — lightweight vs. memory-intensive solutions

Each unique combination of discretized feature values defines a *cell* in the
map. MAP-Elites keeps the best program in each cell, preserving diversity
across the feature space.

### Default behavior

By default, OpenEvolve builds a 2D MAP-Elites grid on its two built-in
feature dimensions, `complexity` and `diversity` — the default
`feature_dimensions: ["complexity", "diversity"]`. `complexity` tracks
program length and `diversity` tracks how different a program is from the
rest of the population; neither requires anything from your evaluator.

### Configuring feature dimensions

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

### When to add feature dimensions

| Scenario | Recommendation |
|----------|----------------|
| Single-objective optimization (maximize score) | The default `["complexity","diversity"]` is fine — it preserves behavioral diversity while the score improves |
| You care about multiple trade-offs (speed vs. quality) | Swap in your own metric names, e.g. `["score","execution_time"]` |
| Evaluator returns many metrics | Pick the 2-3 most meaningful metric names as dimensions |
| Very few iterations (< 100) | Stick with a single dimension, e.g. `["score"]` — not enough iterations to fill a 2D map |

> **Note**: More dimensions means a larger map with more cells to fill. With
> too many dimensions and too few iterations, most cells stay empty and
> MAP-Elites degrades to near-random search.

---

## Islands

OpenEvolve uses an *island model* for parallel evolution. The population is
split into independent islands that evolve separately, exchanging their best
solutions periodically via *migration*.

### Default settings

| Parameter | Default | Config key |
|-----------|---------|------------|
| Number of islands | 5 | `database.num_islands` |
| Migration interval | 50 iterations | `database.migration_interval` |
| Topology | Ring | (hardcoded in OpenEvolve) |

In ring topology, island 0 migrates to island 1, island 1 to island 2, and
so on, with the last island migrating back to island 0.

### How islands help

Each island maintains its own MAP-Elites map and explores different regions
of the solution space. Migration injects high-quality programs from
neighboring islands, introducing fresh genetic material that prevents
premature convergence.

### Tuning islands

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

---

## Parallel evaluations

The `parallel_evaluations` parameter controls how many candidate programs are
evaluated concurrently. This is a key performance lever, but its effectiveness
depends on your LLM backend.

### Setting via CLI

```bash
# Run with 4 parallel evaluations
revolver run --llm my-llm --parallel 4

# Or via config override
revolver run --llm my-llm \
  --config-override evaluator.parallel_evaluations=4
```

### When parallel evaluations help

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

---

## Temperature tuning

Temperature controls the randomness of the LLM's output. Lower values produce
more deterministic, conservative code changes. Higher values produce more
diverse, creative (but potentially invalid) changes.

### Setting temperature

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

The CLI `--temperature` flag always wins over the LLM registry value.

### Precedence order

Temperature is resolved with last-wins semantics:

1. Problem `config.yaml` (base) — lowest priority
2. LLM registry `temperature` field — overrides config.yaml
3. `--temperature` CLI flag — overrides everything

### Effect on evolution

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

---

## Slow local endpoints & request timeout

On the **OpenEvolve** backend, every LLM call is routed through Revolver's
HTTP `TokenCountingProxy` (token accounting). OpenEvolve's own OpenAI client
defaults to a **60-second** request timeout. A slow local endpoint — for
example the `claude-ollama-bridge` exposing a Claude subscription, where a
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
> 60-s trap does not apply there.

---

## Token accounting (and why there is no cost figure)

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

---

## Subscription-backed and single-GPU local endpoints

A `--source local` endpoint is often a **serialized** backend: a single GPU
serving one request at a time, or a subscription bridge (e.g. the
`claude-ollama-bridge` exposing a Claude Max subscription) that processes one
call at a time. Fanning out parallel generation requests to such an endpoint
queues them rather than running them concurrently — and can trip rate limits.
Pin concurrency to 1:

- **OpenEvolve path** — Revolver **auto-pins** `evaluator.parallel_evaluations`
  to `1` whenever the run's LLM has `--source local` and you did not pass
  `--parallel` explicitly, so the engine issues one evaluation (and therefore
  one LLM call) at a time. If you set `--parallel >1` on a local endpoint
  Revolver honours it but emits a warning; a `--config-override
  evaluator.parallel_evaluations=N` always wins over the auto-pin:

  ```bash
  # Auto-pinned to 1 (no --parallel needed):
  revolver run --llm codestral-local --source local

  # Force concurrency on a local endpoint that can take it (warns, honoured):
  revolver run --llm codestral-local --source local --parallel 3
  ```

  A `--dry-run` shows the resolved `parallel_evaluations` value. See also
  *Slow local endpoints & request timeout* above — Revolver already raises the
  per-call timeout to 600 s for `--source local` LLMs.

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

> **Subscription spend is not tracked by Revolver.** When you drive a Claude
> Max (or similar) subscription through a local bridge, the spend is recorded
> on the **Anthropic console**, not by Revolver. Revolver does not capture the
> `total_cost_usd` field returned by the bridge — watch the provider console
> for subscription usage.

> **Token totals under-count on bridge/Agent-SDK endpoints.** Beyond cost, the
> prompt/completion **token** counts that `run info` reports are also
> understated for `--source local` bridge endpoints. The bridge returns an
> OpenAI `usage` block that omits the hidden Claude-Code context the Agent SDK
> injects per call and the model's thinking tokens, so a call billed as
> hundreds of real tokens may report only a handful. This is the same family of
> gap as the reasoning/thinking caveat in *Token accounting* above. `run info`
> prints an explicit caveat for `--source local` runs — track real consumption
> on the **Anthropic console**, not Revolver's token totals.

---

## Recommended profiles

These profiles combine the parameters above into ready-to-use configurations
for common scenarios. Adapt them to your problem and LLM.

### Quick sanity check — 50 iterations

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

### Moderate evolution — 500 iterations

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

### Full evolution — 2000+ iterations

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

### Profile comparison

| Parameter | 50 iters | 500 iters | 2000+ iters |
|-----------|----------|-----------|-------------|
| `database.num_islands` | 2 | 5 | 5-8 |
| `database.migration_interval` | 25 | 50 | 50-100 |
| `database.feature_dimensions` | `["complexity","diversity"]` | `["complexity","diversity"]` | `["score","execution_time"]` |
| `temperature` | 0.5 | 0.7 | 0.8 |
| `parallel` | 1 | 4 | 4-8 |
| Expected improvement | Negligible | Moderate | Significant |
| Use case | Setup validation | Initial experiments | Production optimization |

---

## Multi-objective setup

OpenEvolve supports multi-objective optimization through MAP-Elites feature
dimensions combined with custom evaluator metrics. Instead of optimizing a
single score, you can explore trade-offs between competing objectives.

### Defining custom metrics in your evaluator

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

### Configuring multi-objective search

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

### Example: TSP with execution time

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

### Guidelines for multi-objective setup

- Keep the number of objectives small (2-3). More objectives need
  exponentially more iterations to fill the map.
- Feature dimensions shape the MAP-Elites grid, not the ranking. OpenEvolve
  ranks programs by its `combined_score`, so pick dimension names that
  capture the trade-offs you care about (e.g. `score` vs `execution_time`).
- Use `--iterations 500+` for 2D maps, `--iterations 2000+` for 3D maps.
- The evaluator must return consistent metric names across all evaluations.

---

## Quick reference

All parameters can be set via `--config-override key=value` on `revolver run`.
Dotted keys reach nested config sections (e.g., `evaluator.parallel_evaluations`).

| Parameter | Config key | CLI shorthand | Default |
|-----------|-----------|---------------|---------|
| Islands | `database.num_islands` | `--config-override database.num_islands=N` | 5 |
| Migration interval | `database.migration_interval` | `--config-override database.migration_interval=N` | 50 |
| Feature dimensions | `database.feature_dimensions` | `--config-override 'database.feature_dimensions=["score","execution_time"]'` | `["complexity","diversity"]` |
| Population size | `database.population_size` | `--config-override database.population_size=N` | 20 |
| Parallel evaluations | `evaluator.parallel_evaluations` | `--parallel N` | 1 |
| Temperature | `llm.temperature` | `--temperature F` | Model default |
| Iterations | `max_iterations` | `--iterations N` | From config.yaml |
| Checkpoint interval | `checkpoint_interval` | `--config-override checkpoint_interval=N` | 100 |
| Cascade evaluation | `evaluator.cascade_evaluation` | `--config-override evaluator.cascade_evaluation=true` | `false` (Revolver default) |
| Diff-based evolution | `diff_based_evolution` | `--rewrite-mode` (sets to `false`) | `true` |
| Max code length | `max_code_length` | `--rewrite-mode` (sets to `50000`) | 10000 |
| Ensemble models | `llm.models` | `--llm <ensemble-name>` | N/A (auto-generated) |
| Reasoning effort | `llm.reasoning_effort` | `revolver llm add/update <name> --reasoning-effort low` (registry) or `llm ensemble add --reasoning-effort low` (per member) | Model default |

---

## Full-rewrite mode

By default, OpenEvolve operates in **diff-based** mode: the LLM reads the
current program and produces a SEARCH/REPLACE diff that modifies a small
section. This works well for incremental optimization — parameter tuning,
local search improvements, and minor algorithmic tweaks.

**Full-rewrite mode** (`diff_based_evolution: false`) tells OpenEvolve to
ask the LLM for the **entire program** each iteration. Instead of patching
the existing code, the LLM generates a complete replacement. This enables
fundamentally different algorithmic approaches that diff-based mode cannot
reach.

### When to use full-rewrite mode

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

### Configuration

Two OpenEvolve config keys control full-rewrite behavior:

```yaml
diff_based_evolution: false
max_code_length: 50000
```

- `diff_based_evolution: false` — switches from SEARCH/REPLACE diffs to full
  program generation.
- `max_code_length: 50000` — sets the maximum allowed length (in characters)
  of the generated program. In full-rewrite mode, the LLM produces the entire
  program, so this limit must be large enough to accommodate it.

### CLI shortcut

The `--rewrite-mode` flag on `run` and `run resume` sets both keys
at once:

```bash
revolver run --rewrite-mode
# Equivalent to:
revolver run --config-override diff_based_evolution=false \
                   --config-override max_code_length=50000
```

Config overrides always take precedence over `--rewrite-mode` defaults.
For example, to use rewrite mode with a smaller code length limit:

```bash
revolver run --rewrite-mode --config-override max_code_length=30000
# Uses diff_based_evolution=false and max_code_length=30000
```

### Gemini model compatibility

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
> remains available as an escape hatch for a single non-ensemble run.

### Trade-offs

| Aspect | Diff-based (default) | Full-rewrite |
|---|---|---|
| Creativity | Incremental — small changes to existing code | High — can discover fundamentally different approaches |
| Token cost | Low — only the diff is generated | High — entire program generated each iteration |
| `max_code_length` needed | Default is sufficient | At least 50000 (the `--rewrite-mode` default) |
| Iteration speed | Fast — small payloads | Slower — more tokens per iteration |
| Best for | Tuning, parameter optimization, local search | Paradigm exploration, algorithm discovery |

### Recommended workflow

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

---

## Ensemble strategies

OpenEvolve supports multi-model ensembles via its `llm.models` array.
Instead of using a single LLM for all code generation requests, an
ensemble distributes requests across multiple models weighted by sampling
probability. Revolver manages ensembles as named entities in the LLM
registry, making them reusable and traceable.

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

# Launch a run with the ensemble
revolver run --llm alphevo --iterations 100
```

### Weight recommendations

Weights control how often each model is sampled. OpenEvolve
auto-normalizes weights, so `0.8 + 0.2` and `4 + 1` are equivalent.
Revolver warns (but does not error) if weights do not sum to 1.0.

| Strategy | Cheap model weight | Expensive model weight | When to use |
|----------|-------------------|----------------------|-------------|
| Exploration-heavy | 0.8-0.9 | 0.1-0.2 | Most scenarios; maximize iterations per dollar |
| Balanced | 0.5-0.6 | 0.4-0.5 | When the cheap model produces too many invalid diffs |
| Quality-focused | 0.2-0.3 | 0.7-0.8 | Short runs where every iteration counts |

**Start with 80/20** and adjust based on the valid-diff rate. If the
cheap model's diffs are mostly invalid (e.g., < 30% valid), shift weight
toward the expensive model.

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
> non-ensemble escape hatch only.

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
- Phase 1: cheap model explores broadly, filling the MAP-Elites map
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
   applied. Use `fixed` when you want to pin the sampling mixture.

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

## Checklist

Before launching a tuned run:

- [ ] Evaluator returns all metrics needed for `feature_dimensions`
- [ ] Temperature is appropriate for the LLM size (lower for small models)
- [ ] `--parallel` matches the LLM backend (high for API, low for local)
- [ ] Iteration count gives at least 5 migrations per island
- [ ] `feature_dimensions` count is appropriate for the iteration budget
- [ ] A quick sanity run (50 iters) passed without errors
- [ ] Ensemble weights sum to ~1.0 (`revolver llm ensemble info` to verify)
- [ ] Each ensemble member LLM is registered and has valid API key env var
