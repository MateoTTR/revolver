---
verified-against: v0.18.0
---

# Initial Program Structure Guide

Best practices for structuring initial programs that OpenEvolve can optimize
effectively.

## Why structure matters

OpenEvolve asks an LLM to generate **SEARCH/REPLACE diffs** against your code.
The LLM must read the current program, find a specific section, write a
replacement, and produce output that matches the diff format exactly.

A well-structured program gives the LLM clear, small targets to modify.
A monolithic program forces the LLM to reason about hundreds of lines at once
and produce large, fragile diffs — especially problematic for smaller models
(7B–22B parameters).

**Measured result**: on the TSP demo with codestral:22b (a 22B local model),
a monolithic program produced **0% valid diffs** across all iterations. After
restructuring into small functions, the same model achieved **100% valid diffs**
and actual optimization improvements.

## Function decomposition

Break your program into small, focused functions. Each function should do one
thing. This gives the LLM atomic units to modify independently.

### Bad: monolithic function

```python
def solve(data):
    # 100+ lines mixing I/O, data prep, algorithm, and output formatting
    n = len(data)
    visited = [False] * n
    result = [0]
    visited[0] = True
    for _ in range(n - 1):
        current = result[-1]
        best = float("inf")
        best_idx = -1
        for j in range(n):
            if not visited[j]:
                d = distance(data[current], data[j])
                if d < best:
                    best = d
                    best_idx = j
        result.append(best_idx)
        visited[best_idx] = True
    # ... more logic mixed in ...
    return result
```

The LLM must match and replace large sections of this monolithic block. Small
models frequently produce diffs that don't match the original code exactly,
causing 0% valid diffs.

### Good: decomposed functions

```python
def solve(data):
    n = len(data)
    if n <= 1:
        return list(range(n))
    distances = precompute_distances(data)
    tour = build_tour(data, distances)
    tour = improve_tour(data, distances, tour)
    return tour

def precompute_distances(data):
    """Compute pairwise distance matrix."""
    # 10 lines — one clear purpose
    ...

def build_tour(data, distances):
    """Construct an initial tour using nearest-neighbor heuristic."""
    # 15 lines — one clear purpose
    ...

def improve_tour(data, distances, tour):
    """Improve the tour using local search."""
    # 15 lines — one clear purpose
    ...
```

Each function is a small, self-contained unit that the LLM can modify
independently. A diff that replaces `improve_tour` doesn't need to touch
`build_tour` at all.

## EVOLVE-BLOCK placement

OpenEvolve uses `# EVOLVE-BLOCK-START` and `# EVOLVE-BLOCK-END` markers
to identify which parts of the code the LLM should modify. Only code inside
these markers is shown as modifiable to the LLM. The full marker is
`# --- EVOLVE-BLOCK-START ---` (the dashes are part of the marker comment
itself, not a separate construct).

### Syntax

```python
# --- EVOLVE-BLOCK-START ---
# Code the LLM can modify
# --- EVOLVE-BLOCK-END ---
```

### Placement rules

1. **Wrap the algorithmic core, not I/O.** The LLM should optimize your
   algorithm, not rewrite how you read files or print results.

2. **Each block should be self-contained.** The code inside a block should
   be understandable without reading the rest of the program.

3. **Keep blocks focused.** A single block with 100 lines defeats the
   purpose. If your block is large, decompose into functions first.

4. **One block is usually enough.** Place it around the section that contains
   all the functions you want the LLM to evolve.

### Example: good block placement

```python
def solve(cities):
    n = len(cities)
    if n <= 1:
        return list(range(n))

    # --- EVOLVE-BLOCK-START ---

    def _dist(i, j):
        """Euclidean distance between city i and city j."""
        dx = cities[i][0] - cities[j][0]
        dy = cities[i][1] - cities[j][1]
        return math.sqrt(dx * dx + dy * dy)

    def _build_tour():
        """Construct initial tour using nearest-neighbor."""
        visited = [False] * n
        tour = [0]
        visited[0] = True
        for _ in range(n - 1):
            cur = tour[-1]
            best_d = float("inf")
            best_j = -1
            for j in range(n):
                if not visited[j]:
                    d = _dist(cur, j)
                    if d < best_d:
                        best_d = d
                        best_j = j
            tour.append(best_j)
            visited[best_j] = True
        return tour

    def _improve_tour(tour):
        """Improve the tour using local search."""
        return tour  # stub — LLM will implement

    tour = _build_tour()
    tour = _improve_tour(tour)

    # --- EVOLVE-BLOCK-END ---

    return tour
```

The input validation (`n <= 1`) and the return statement are outside the block.
The LLM focuses only on the algorithm.

## Hint comments

Inside EVOLVE-BLOCKs, add `HINT` comments to guide the LLM toward specific
improvements. The LLM reads these as natural-language suggestions.

```python
def _build_tour():
    """Construct initial tour using nearest-neighbor from city 0.

    HINT: Try starting from multiple cities and keep the shortest.
    HINT: Or use greedy edge insertion instead.
    """
    ...

def _improve_tour(tour):
    """Improve the tour using local search.

    HINT: Implement 2-opt — for each pair of edges (i, i+1) and
    (j, j+1), check if reversing the segment tour[i+1:j+1]
    reduces the total tour distance.
    HINT: Or try or-opt — move a single city to a better position.
    """
    return tour  # stub
```

Hints are particularly effective for smaller models that benefit from explicit
direction. They also help steer larger models toward the improvements you
care about most.

## Stub patterns

Your initial program must **run correctly and produce a valid output with a
score greater than zero**. OpenEvolve needs a working baseline to improve upon.

### Why stubs matter

- If your program crashes, the evaluator returns score = 0. OpenEvolve cannot
  improve on a program that doesn't run.
- If your program returns invalid output (wrong format, missing fields), the
  evaluator may reject it entirely.
- A naive-but-correct implementation gives the LLM something concrete to
  improve. It can see the structure and make targeted changes.

### Stub strategy

1. **Start with the simplest correct algorithm.** For TSP, use
   nearest-neighbor. For sorting, use insertion sort. For optimization, use
   a greedy approach.

2. **Leave room for improvement.** The stub should be obviously suboptimal
   so the LLM has clear directions to explore.

3. **Use function stubs with docstrings.** If you want the LLM to implement
   a function from scratch, provide the signature, a docstring explaining
   what it should do, and a trivial body:

```python
def _improve_tour(tour):
    """Improve the tour using local search.

    HINT: Implement 2-opt — reverse segments to uncross edges.
    """
    return tour  # no-op stub — LLM will replace this
```

4. **Don't start empty.** A program with `pass` or `return []` everywhere
   will score 0. The LLM needs a working foundation.

## Real example: TSP v1 vs v2

The Revolver TSP demo illustrates the impact of program structure on
optimization success.

### v1 — Monolithic (0% valid diffs with codestral:22b)

```python
def solve(cities):
    n = len(cities)
    if n <= 1:
        return list(range(n))

    # --- EVOLVE-BLOCK-START ---
    visited = [False] * n
    tour = [0]
    visited[0] = True
    for _ in range(n - 1):
        current = tour[-1]
        best_dist = float("inf")
        best_city = -1
        for j in range(n):
            if not visited[j]:
                dx = cities[current][0] - cities[j][0]
                dy = cities[current][1] - cities[j][1]
                d = math.sqrt(dx * dx + dy * dy)
                if d < best_dist:
                    best_dist = d
                    best_city = j
        tour.append(best_city)
        visited[best_city] = True
    # --- EVOLVE-BLOCK-END ---

    return tour
```

One big block, one big function. The LLM must produce a SEARCH/REPLACE diff
that exactly matches a large chunk of this code. codestral:22b failed on every
attempt — the diffs never matched.

### v2 — Decomposed (100% valid diffs with codestral:22b)

```python
def solve(cities):
    n = len(cities)
    if n <= 1:
        return list(range(n))

    # --- EVOLVE-BLOCK-START ---

    def _dist(i, j):
        """Euclidean distance between city i and city j."""
        dx = cities[i][0] - cities[j][0]
        dy = cities[i][1] - cities[j][1]
        return math.sqrt(dx * dx + dy * dy)

    def _build_tour():
        """Construct initial tour using nearest-neighbor from city 0.

        HINT: Try starting from multiple cities and keep the shortest.
        HINT: Or use greedy edge insertion instead.
        """
        visited = [False] * n
        tour = [0]
        visited[0] = True
        for _ in range(n - 1):
            cur = tour[-1]
            best_d = float("inf")
            best_j = -1
            for j in range(n):
                if not visited[j]:
                    d = _dist(cur, j)
                    if d < best_d:
                        best_d = d
                        best_j = j
            tour.append(best_j)
            visited[best_j] = True
        return tour

    def _improve_tour(tour):
        """Improve the tour using local search.

        HINT: Implement 2-opt — for each pair of edges (i, i+1) and
        (j, j+1), check if reversing the segment tour[i+1:j+1]
        reduces the total tour distance.
        HINT: Or try or-opt — move a single city to a better position.
        """
        return tour  # stub — LLM will implement

    tour = _build_tour()
    tour = _improve_tour(tour)

    # --- EVOLVE-BLOCK-END ---

    return tour
```

Same algorithm, same EVOLVE-BLOCK boundaries, but decomposed into three
functions with hint comments. The LLM can now:

- Replace just `_improve_tour` with a 2-opt implementation (small, precise diff)
- Modify `_build_tour` to try multiple starting cities (targeted change)
- Leave `_dist` alone if it doesn't need changing

**Results with codestral:22b**: 100% valid diffs (15/15 iterations), best score
improved from 1.0 (baseline) to 1.037 (3.7% better than nearest-neighbor).

## Problem.md as key lever

### What is problem.md?

`problem.md` is a markdown file in your problem directory that describes the
optimization problem to the LLM. When you run `revolver run`, Revolver
injects the contents of `problem.md` into the system prompt sent to
OpenEvolve. The LLM reads this description to understand *what* to optimize
and *how* to approach it.

A minimal `problem.md` might just state the objective:

```markdown
# Traveling Salesman Problem
Find the shortest tour visiting all cities exactly once and returning to the start.
```

But for complex problems, the richness of `problem.md` directly determines
the quality of the LLM's output.

### Why it matters

The LLM uses `problem.md` as its primary source of domain knowledge. Without
domain context, even a powerful model will default to generic approaches —
gradient descent with hand-rolled loops, simple greedy heuristics, or
parameter tweaking of the existing code.

A richer `problem.md` gives the LLM the **vocabulary and concepts** it needs
to formulate sophisticated solutions. This is especially important in
[full-rewrite mode](tuning-evolution.md#full-rewrite-mode), where the LLM
generates the entire program from scratch and has maximum freedom to choose
its approach.

### What to include

Depending on your problem's complexity, consider adding:

- **Mathematical formulation of the objective function.** Explicit notation
  helps the LLM reason about the optimization landscape:

  ```markdown
  ## Objective
  Minimize the worst-case sidelobe level:
    min_w max_{θ ∈ sidelobe_region} |w^H a(θ)|²
  subject to w^H a(θ₀) = 1 (unit gain at look direction)
  ```

- **Known approaches from literature.** Name specific algorithms and
  techniques so the LLM can draw on its training knowledge:

  ```markdown
  ## Known approaches
  - Gradient descent with softmin relaxation of the max operator
  - Semidefinite programming (SDP) relaxation
  - Iterative worst-point boosting (Capon-style)
  - Continuation methods: start with smooth approximation, anneal toward hard max
  ```

- **Domain-specific hints.** Mention relevant libraries, useful techniques,
  and implementation patterns:

  ```markdown
  ## Implementation hints
  - Use `scipy.optimize.minimize` with L-BFGS-B for smooth objectives
  - Use `numpy.linalg` for array operations (steering vectors, covariance)
  - Softmin via log-sum-exp: `softmin(x, α) = -log(Σ exp(-α·xᵢ)) / α`
  - Multi-start: try several initial weight vectors to avoid local optima
  ```

- **Constraint descriptions.** Distinguish hard constraints (must satisfy)
  from soft constraints (penalized in the objective):

  ```markdown
  ## Constraints
  - Hard: unit gain at look direction (normalize weights after optimization)
  - Soft: mainlobe width (penalize if -3dB width exceeds 2× theoretical minimum)
  ```

- **Input/output format details.** Specify what the program receives and
  what it must return, including data types and shapes.

### When to enrich

Not every problem needs a detailed `problem.md`. Use this decision guide:

| Problem type | Enrichment level | What to add |
|---|---|---|
| Simple combinatorial (TSP, knapsack) | Minimal | Basic problem statement is sufficient |
| Continuous optimization | Medium | Mathematical formulation + solver hints |
| Domain-specific (signal processing, physics) | High | Domain vocabulary, known techniques, library suggestions |
| Research/novel problems | High | Literature references, known baselines, evaluation criteria |

### Evidence: beamforming POC (v0.9.0)

The impact of `problem.md` enrichment was demonstrated concretely in the
beamforming POC. Two configurations were compared:

- **Basic problem.md + diff mode** (Flash Lite, 300 iterations): the LLM
  produced only parameter tweaks to the existing worst-point boosting
  algorithm. Result: +0.030 dB improvement — equivalent to simply increasing
  the number of internal iterations in the baseline.

- **Enriched problem.md + full-rewrite mode** (Gemini Pro, 5 iterations):
  the LLM discovered `scipy.optimize.minimize` with L-BFGS-B, softmin
  log-sum-exp relaxation, and alpha continuation — a fundamentally different
  and more powerful approach. In just 5 iterations, it independently arrived
  at the same algorithmic strategy as a manually-written expert solver.

The enriched `problem.md` included the mathematical formulation (steering
vectors, softmin aggregation), known approaches (SDP, continuation methods),
and explicit library hints (`scipy.optimize`). This gave the LLM the
conceptual framework to propose a solution that diff-based mode with a basic
problem description could never reach.

**Three factors** were necessary simultaneously for this qualitative jump:

1. **Full-rewrite mode** — freed the LLM from incremental SEARCH/REPLACE diffs
2. **Enriched problem.md** — gave the LLM domain vocabulary and solver hints
3. **Powerful model** (Gemini Pro) — had the reasoning capacity to formulate
   the mathematical optimization correctly

### Don't over-specify

Provide context and vocabulary, not a step-by-step algorithm. The goal is to
expand the LLM's solution space, not to dictate the implementation.

**Good** — gives direction without prescribing implementation:

```markdown
## Hints
- Consider using scipy.optimize.minimize with L-BFGS-B for smooth objectives
- Softmin is a differentiable approximation of the max operator
- Multi-start with different initial vectors helps avoid local optima
```

**Too specific** — leaves no room for the LLM to explore:

```markdown
## Algorithm
1. Initialize w = a(θ₀) / ||a(θ₀)||²
2. For α in [5, 50, 500]:
   a. Define f(w) = -softmin(-|w^H a(θ)|², α) for θ in sidelobe grid
   b. Call scipy.optimize.minimize(f, w, method='L-BFGS-B', maxiter=2000)
   c. Normalize: w = w / (w^H a(θ₀))
3. Return w
```

The first version lets the LLM discover the right alpha schedule, iteration
count, and initialization strategy on its own. The second version turns
OpenEvolve into a copy-paste tool — if you already know the exact algorithm,
you don't need evolutionary optimization.

---

## Checklist

Before running OpenEvolve on your program:

- [ ] Program runs successfully and produces valid output
- [ ] Evaluator returns a score > 0 for the initial program
- [ ] Functions are small and focused (under ~30 lines each)
- [ ] EVOLVE-BLOCK markers surround the algorithmic core
- [ ] I/O and validation logic is outside the EVOLVE-BLOCK
- [ ] Stub functions have docstrings explaining what they should do
- [ ] HINT comments guide the LLM toward specific improvements
- [ ] No implicit dependencies between functions inside the block
- [ ] Initial program scores in the 0.3–0.7 range (not too easy, not too hard)
- [ ] Allowed libraries are documented in `problem.md` and available to the evaluator

## Common pitfalls

| Pitfall | Consequence | Fix |
|---------|-------------|-----|
| One large function in the EVOLVE-BLOCK | LLM produces diffs that don't match — 0% valid diffs | Decompose into small functions |
| No EVOLVE-BLOCK markers | OpenEvolve wraps the entire file — diffs are even larger | Add explicit markers around the algorithm |
| Program doesn't run initially | Score = 0, nothing to improve | Start with a naive-but-correct implementation |
| Empty stubs (`return None`) | Invalid output, score = 0 | Return a valid (even if suboptimal) result |
| Functions depend on shared mutable state | LLM changes one function, breaks another | Pass data explicitly via arguments and return values |
| Hints are too vague ("make it better") | LLM doesn't know what to try | Be specific: name algorithms, describe the optimization |
| EVOLVE-BLOCK around I/O code | LLM rewrites file reading, not the algorithm | Move I/O outside the block |
| Baseline already near-optimal | LLM has no room to improve — evolution adds nothing | Start with a simpler baseline (see below) |
| Restricting scientific libraries | LLM can't use proven solvers for complex math problems | Allow scipy/numpy and document it in `problem.md` |

## Lessons from the demo problems

The guidance above comes from the TSP demo, where a combinatorial problem maps
naturally to small Python functions. The beamforming demo (v0.8.1) introduced a
harder optimization problem — phased-array antenna beamforming — and surfaced
three additional lessons about how the initial program's strength and the
evaluator's constraints shape evolution outcomes.

### Stronger baseline = less improvement margin

If your initial program already uses a sophisticated algorithm, the LLM has
very little room to improve it. Evolution works best when the gap between the
baseline and the theoretical optimum is wide.

**Demo example**: the beamforming initial program used a worst-point
boosting algorithm that was already near-optimal. Across 5 models (3 local,
2 remote), the best improvement was only +0.044 dB — the LLM could tweak
parameters and add minor refinements (multi-init, soft-min weighting, projected
gradient), but it could not fundamentally change the algorithmic approach.

By contrast, the TSP initial program used a simple nearest-neighbor heuristic,
leaving plenty of room for the LLM to discover 2-opt, or-opt, and other
local search strategies.

**Guideline**: start with the simplest correct algorithm, not the best one you
know. If you already know the optimal approach, OpenEvolve is not the right
tool. OpenEvolve excels at exploring the space between "naive" and "expert."

| Baseline strength | Typical initial score | Evolution outcome |
|---|---|---|
| Trivial (random) | 0.0–0.1 | LLM may struggle to bootstrap — too far from a valid solution |
| Naive-but-correct | 0.3–0.7 | **Sweet spot** — plenty of room, LLM can discover real improvements |
| Near-optimal | 0.9+ | Marginal gains at best — LLM has nowhere meaningful to go |

### Allow scientific libraries for complex problems

For problems involving signal processing, linear algebra, convex optimization,
or other domains with mature libraries, restricting the LLM to pure Python
cripples its ability to find good solutions. An LLM that can use `scipy.optimize`
or `numpy.linalg` can leverage decades of optimized implementations rather than
reimplementing them from scratch.

**Demo example**: in the beamforming demo, the LLM could potentially have
used SDP solvers (`scipy.optimize`, `cvxpy`) or convex formulations to find
better beamforming weights. But the evaluator environment did not make these
available, so the LLM was limited to hand-rolled gradient-style tweaks.

**Guideline**: document allowed libraries explicitly in your `problem.md`.
Ensure they are installed in the evaluator environment. The evaluator wrapper
should not restrict imports unless you have a specific reason (e.g., measuring
pure algorithmic skill without library help).

```markdown
# problem.md (example)

## Allowed libraries
- numpy (array operations, linear algebra)
- scipy (optimization, signal processing)
- Do NOT use: cvxpy (too slow for per-instance evaluation)
```

If you want to measure whether the LLM can improve on a pure-Python solution,
make that an explicit constraint. Otherwise, let it use the tools that a human
expert would reach for.

### Problem difficulty calibration

The initial program's score on your training dataset is a strong predictor of
whether evolution will succeed. Calibrate difficulty before launching a long run.

**Too easy** (initial score > 0.9):

The baseline already solves the problem well. The LLM can only find marginal
improvements, and even those may not generalize to held-out data. This was the
situation in the beamforming demo — worst-point boosting already scored 0.100
on a scale where gains are measured in hundredths of dB.

Signs: best evolved program is barely better than baseline; most iterations
produce no improvement; LLM diffs are cosmetic (variable renames, minor
constant tweaks).

**Too hard** (initial score < 0.1):

The baseline is so far from a valid solution that the LLM cannot bootstrap.
Every modification it tries still scores zero, so evolution has no gradient
to follow.

Signs: every iteration scores 0.0; no programs survive selection; LLM diffs
are increasingly random as it has no positive signal to learn from.

**Sweet spot** (initial score 0.3–0.7):

The baseline is correct but clearly suboptimal. The LLM can see what works,
identify bottlenecks, and make targeted improvements that produce measurable
score gains.

Signs: first few iterations already produce improvements; score curve rises
steadily; LLM diffs are substantive (new algorithms, better data structures,
parameter tuning).

**How to calibrate**:

1. Run `revolver problem test` to get the baseline score.
2. If the score is above 0.9, simplify the initial program (remove
   optimizations, use a more naive algorithm).
3. If the score is below 0.1, add a better starting heuristic or reduce
   problem difficulty (fewer constraints, smaller instances).
4. Aim for a baseline that a human expert could improve by 2–5x — that
   gives the LLM realistic targets.
