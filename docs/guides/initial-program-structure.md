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

**Real-world result**: on the TSP demo with codestral:22b (a 22B local model),
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
    tour = build_tour(data)
    tour = improve_tour(data, tour)
    return tour

def build_tour(data):
    """Construct an initial tour using nearest-neighbor heuristic."""
    # 15 lines — one clear purpose
    ...

def improve_tour(data, tour):
    """Improve the tour using local search."""
    # 15 lines — one clear purpose
    ...
```

Each function is a small, self-contained unit that the LLM can modify
independently. A diff that replaces `improve_tour` doesn't need to touch
`build_tour` at all.

## EVOLVE-BLOCK placement

OpenEvolve uses `# EVOLVE-BLOCK-START` and `# EVOLVE-BLOCK-END` markers
(with `---` delimiters) to identify which parts of the code the LLM should
modify. Only code inside these markers is shown as modifiable to the LLM.

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
