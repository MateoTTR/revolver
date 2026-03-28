# Tuning OpenEvolve Configuration

Practical guide for tuning OpenEvolve parameters via the Revolver CLI.
Covers MAP-Elites feature dimensions, islands, parallelism, temperature,
and recommended profiles for different iteration budgets.

## Overview

OpenEvolve exposes dozens of configuration knobs. Most have sensible defaults,
but a few have significant impact on optimization quality and cost. This guide
focuses on the parameters you are most likely to tune through `revolver run`
flags and `--config-override`.

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

By default, OpenEvolve uses a single feature dimension (index `0`), which
typically corresponds to the primary score returned by the evaluator. This
means the map is essentially one-dimensional.

### Configuring feature dimensions

Use `--config-override` to set which evaluator metrics serve as feature
dimensions:

```bash
# Use two feature dimensions (e.g., score and execution_time)
revolver run --llm my-llm \
  --config-override database.feature_dimensions=[0,1]
```

> **Note**: OpenEvolve organizes these parameters under the `database` namespace
> in its configuration. Always use `database:` in YAML or `database.` prefix
> with `--config-override`. If you place them at the top level, Revolver will
> warn you at `problem version` time.

The integers refer to the *index* of metrics returned by your evaluator's
`evaluate()` function. If your evaluator returns:

```python
return {
    "score": combined_score,         # index 0
    "execution_time": elapsed,       # index 1
    "memory_usage": peak_memory_mb,  # index 2
}
```

Then `database.feature_dimensions=[0,1]` creates a 2D map indexed by `score` and
`execution_time`. This encourages OpenEvolve to find diverse programs: some
that are fast, some that score high, and some that balance both.

### When to add feature dimensions

| Scenario | Recommendation |
|----------|----------------|
| Single-objective optimization (maximize score) | Default `[0]` is fine |
| You care about multiple trade-offs (speed vs. quality) | Add a second dimension: `[0,1]` |
| Evaluator returns many metrics | Pick the 2-3 most meaningful as dimensions |
| Very few iterations (< 100) | Stick with 1 dimension — not enough iterations to fill a 2D map |

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
  --config-override database.feature_dimensions=[0,1] \
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
| `database.feature_dimensions` | `[0]` | `[0]` | `[0,1]` |
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

Your evaluator must return a dictionary with named metrics. The order of
keys determines the index used in `feature_dimensions`:

```python
import time

def evaluate(program_output, dataset_path):
    start = time.time()
    # ... run and validate the program output ...
    elapsed = time.time() - start

    return {
        "score": quality_score,        # index 0: primary objective
        "execution_time": elapsed,     # index 1: secondary objective
    }
```

### Configuring multi-objective search

Use `feature_dimensions` to tell MAP-Elites which metrics define the map:

```bash
# Optimize score while exploring execution_time trade-offs
revolver run --llm my-llm --iterations 500 \
  --config-override database.feature_dimensions=[0,1]
```

This creates a 2D map where:
- One axis is the `score` metric (index 0)
- The other axis is `execution_time` (index 1)

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
  --config-override database.feature_dimensions=[0,1] \
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
- Put the primary objective at index 0. OpenEvolve's `combined_score`
  (used for ranking) is typically based on the first metric.
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
| Feature dimensions | `database.feature_dimensions` | `--config-override database.feature_dimensions=[0,1]` | `[0]` |
| Population size | `database.population_size` | `--config-override database.population_size=N` | 20 |
| Parallel evaluations | `evaluator.parallel_evaluations` | `--parallel N` | 1 |
| Temperature | `llm.temperature` | `--temperature F` | Model default |
| Iterations | `max_iterations` | `--iterations N` | From config.yaml |
| Checkpoint interval | `checkpoint_interval` | `--config-override checkpoint_interval=N` | 100 |
| Cascade evaluation | `evaluator.cascade_evaluation` | `--config-override evaluator.cascade_evaluation=true` | `false` (Revolver default) |
| Diff-based evolution | `diff_based_evolution` | `--rewrite-mode` (sets to `false`) | `true` |
| Max code length | `max_code_length` | `--rewrite-mode` (sets to `50000`) | 10000 |
| Ensemble models | `llm.models` | `--llm <ensemble-name>` | N/A (auto-generated) |
| Reasoning effort | `llm.reasoning_effort` | `--config-override llm.reasoning_effort=low` | Model default |

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

The `--rewrite-mode` flag on `run start` and `run resume` sets both keys
at once:

```bash
revolver run start --rewrite-mode
# Equivalent to:
revolver run start --config-override diff_based_evolution=false \
                   --config-override max_code_length=50000
```

Config overrides always take precedence over `--rewrite-mode` defaults.
For example, to use rewrite mode with a smaller code length limit:

```bash
revolver run start --rewrite-mode --config-override max_code_length=30000
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

> **Tip**: if you must use a thinking model, set `reasoning_effort=low` via
> `--config-override llm.reasoning_effort=low` to minimize the token budget
> consumed by internal reasoning.

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
   revolver run start --llm gemini-pro --rewrite-mode --iterations 50
   ```

2. **Identify the best approach** from the evolved programs using
   `revolver solution show`.

3. **Switch to diff-based mode** for fine-tuning. Use the best evolved
   program as the new initial program and run diff-based evolution to
   optimize parameters and details:

   ```bash
   revolver run start --llm gemini-flash-lite --iterations 500
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
revolver run start --llm alphevo --iterations 100
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

> **Gemini Pro tip**: When using Gemini Pro in an ensemble, set
> `reasoning_effort=low` via `--config-override llm.reasoning_effort=low`
> to prevent the model from consuming its token budget on internal
> reasoning instead of generating code.

### Cost implications

Ensemble runs can dramatically reduce cost by routing most iterations
through cheap models. Approximate Gemini pricing as of early 2026:

| Model | Input cost (per 1M tokens) | Output cost (per 1M tokens) | Relative cost |
|-------|---------------------------|----------------------------|---------------|
| Flash-Lite | $0.075 | $0.30 | 1x (baseline) |
| Flash | $0.15 | $0.60 | 2x |
| Pro | $1.25 | $10.00 | ~36x |

With an 80/20 Flash-Lite/Pro ensemble over 500 iterations:
- ~400 iterations at Flash-Lite cost + ~100 at Pro cost
- Estimated 5-7x cheaper than running all 500 on Pro alone
- Quality benefit: Pro's occasional contributions lift the population

Use `revolver llm update <name> --input-cost <X> --output-cost <Y>` to
register per-model costs, then `revolver run info` will report estimated
run cost.

### Ensemble vs sequential resume

There are two ways to combine cheap and expensive models:

**Ensemble** (concurrent within a single run):
- Both models contribute to the same population simultaneously
- Pro injects high-quality solutions while Flash explores broadly
- Best for: single-phase optimization where you want continuous
  cross-pollination between model capabilities

```bash
revolver run start --llm alphevo --iterations 500
```

**Sequential resume** (phased, separate runs):
- Phase 1: cheap model explores broadly, filling the MAP-Elites map
- Phase 2: expensive model refines the best solutions found in Phase 1
- Best for: budget-constrained optimization where you want to maximize
  cheap exploration before spending on expensive refinement

```bash
# Phase 1: broad exploration with cheap model
revolver run start --llm flash-lite --iterations 500

# Phase 2: refine with expensive model, resuming from Phase 1
revolver run resume --run <run-id> --llm pro --iterations 100
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
