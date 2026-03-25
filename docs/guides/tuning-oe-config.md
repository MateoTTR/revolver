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
  --config-override feature_dimensions=[0,1]
```

The integers refer to the *index* of metrics returned by your evaluator's
`evaluate()` function. If your evaluator returns:

```python
return {
    "score": combined_score,         # index 0
    "execution_time": elapsed,       # index 1
    "memory_usage": peak_memory_mb,  # index 2
}
```

Then `feature_dimensions=[0,1]` creates a 2D map indexed by `score` and
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
| Number of islands | 5 | `num_islands` |
| Migration interval | 50 iterations | `migration_interval` |
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
  --config-override num_islands=2

# Increase to 8 islands for long runs with diverse exploration
revolver run --llm my-llm --iterations 2000 \
  --config-override num_islands=8

# Adjust migration frequency
revolver run --llm my-llm \
  --config-override migration_interval=100
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
revolver llm add my-llm --provider ollama --model codestral:22b \
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
  --config-override num_islands=2 \
  --config-override migration_interval=25 \
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
  --config-override num_islands=5 \
  --config-override migration_interval=50 \
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
  --config-override num_islands=8 \
  --config-override migration_interval=100 \
  --config-override feature_dimensions=[0,1] \
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
| `num_islands` | 2 | 5 | 5-8 |
| `migration_interval` | 25 | 50 | 50-100 |
| `feature_dimensions` | `[0]` | `[0]` | `[0,1]` |
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
  --config-override feature_dimensions=[0,1]
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
  --config-override feature_dimensions=[0,1] \
  --config-override num_islands=5 \
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
| Islands | `num_islands` | `--config-override num_islands=N` | 5 |
| Migration interval | `migration_interval` | `--config-override migration_interval=N` | 50 |
| Feature dimensions | `feature_dimensions` | `--config-override feature_dimensions=[0,1]` | `[0]` |
| Parallel evaluations | `evaluator.parallel_evaluations` | `--parallel N` | 1 |
| Temperature | `llm.temperature` | `--temperature F` | Model default |
| Iterations | `max_iterations` | `--iterations N` | From config.yaml |
| Population size | `population_size` | `--config-override population_size=N` | 20 |
| Cascade evaluation | `evaluator.cascade_evaluation` | `--config-override evaluator.cascade_evaluation=true` | `false` (Revolver default) |

---

## Checklist

Before launching a tuned run:

- [ ] Evaluator returns all metrics needed for `feature_dimensions`
- [ ] Temperature is appropriate for the LLM size (lower for small models)
- [ ] `--parallel` matches the LLM backend (high for API, low for local)
- [ ] Iteration count gives at least 5 migrations per island
- [ ] `feature_dimensions` count is appropriate for the iteration budget
- [ ] A quick sanity run (50 iters) passed without errors
