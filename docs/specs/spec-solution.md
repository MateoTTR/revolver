# Spec: revolver solution

**Traceable to**: ConOps §4.6 (Solution), DES-001 v0.2 (solutions table)
**Status**: Draft

---

## 1. Scope

This spec covers solution browsing, metadata management, on-demand extraction, source inspection, file export, comparison, and deletion. Solutions are lightweight DB references to (`run_id`, `rank`) — they do NOT own filesystem directories. The program file for a solution is located at `.revolver/runs/<run_id>/programs/rank-<N>.py`. The rank-1 solution is auto-created by `revolver run` ([spec-run.md](spec-run.md)). Additional solutions can be extracted from a run's stored programs via `solution extract`. Source code can be viewed (`show`), exported (`export`), or compared (`diff`).

---

## 2. Commands

### 2.1 `revolver solution list`

List all solutions in the current project.

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--version <tag>` | string | — | Filter by problem version |
| `--llm <name>` | string | — | Filter by LLM used |
| `--rank <n>` | int | — | Filter by rank (1 = best from run). Useful to show only auto-created or only extracted solutions |

**Output** (human):
```
ID                      Alias               Version  LLM          Score   Rank  Run                   Date
sol-20260310-143000     claude-small-v1.1   v1.1     claude-opus  0.91    #1    run-20260310-143000   2026-03-10
sol-20260310-143001     —                   v1.1     claude-opus  0.85    #2    run-20260310-143000   2026-03-10
sol-20260310-160000     gemma-small-v1.1    v1.1     gemma-local  0.82    #1    run-20260310-160000   2026-03-10
sol-20260311-090000     —                   v1.0     claude-opus  0.78    #1    run-20260311-090000   2026-03-11
```

**Output** (JSON):
```json
{
  "solutions": [
    {
      "id": "sol-20260310-143000",
      "alias": "claude-small-v1.1",
      "problem_version": "v1.1",
      "llm": "claude-opus",
      "best_score": 0.91,
      "rank": 1,
      "run_id": "run-20260310-143000",
      "created_at": "2026-03-10T14:30:00Z"
    }
  ]
}
```

**Exit codes**: 0 always

### 2.2 `revolver solution info <id-or-alias>`

Show detailed information about a solution.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `id-or-alias` | Yes | Solution ID or alias |

**Output** (human):
```
Solution: sol-20260310-143000
  Alias: claude-small-v1.1
  Best combined_score: 0.91
  Rank: #1
  Source: auto (created by run)

Run: run-20260310-143000
  Problem version: v1.1 (sha256:e5f6g7h8...)
  Training dataset: train-small (sha256:f1e2d3c4...)
  LLM: claude-opus (claude-opus-4-6)
  Iterations: 200
  Generation time: 3h45m

Program: .revolver/runs/run-20260310-143000/programs/rank-1.py

Other solutions from same run:
  sol-20260311-091500  #2  score=0.85  (extracted)

Evaluations:
  eval-benchmark: mean=0.87, p90=0.93 (2026-03-10)
```

**Exit codes**: 0 success, 1 if not found

### 2.3 `revolver solution alias <id> <alias>`

Set or update a solution's alias.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `id` | Yes | Solution ID |
| `alias` | Yes | New alias (must be unique within the project) |

**Output** (human):
```
Solution "sol-20260310-143000" aliased as "claude-small-v1.1"
```

**Exit codes**: 0 success, 1 if ID not found or alias already in use

### 2.4 `revolver solution extract`

Promote a program from a run into a first-class solution — the **rank-1** program by default, or an arbitrary-ranked/identified population program via `--rank`/`--program-id` on top-N-capable backends (FR-SOL-021). This enables on-demand inspection: the user runs `revolver run info` to see all stored programs with scores, then extracts the one to promote for evaluation.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--run <run-id>` | string | Yes | Run containing the program to extract |
| `--rank <N>` | int | No | Rank of the population program to promote (default: 1). Ranks > 1 are gated on the run backend's `capabilities().top_n_extraction` (FR-SOL-021) |
| `--program-id <id>` | string | No | Promote a specific population program by its backend program ID (ShinkaEvolve `programs.sqlite`). Mutually exclusive with `--rank`; gated on `capabilities().top_n_extraction` (FR-SOL-021) |
| `--alias <name>` | string | No | User-friendly name for the new solution |
| `--force` / `-f` | flag | No | Replace an existing extraction for the same `(run_id, rank)` instead of erroring |

**Behavior**:
1. Verify the run exists and has status `completed`
2. Resolve the target program (default: rank 1). For `--rank <N>` with N > 1 or `--program-id`, resolve the run's backend and check `capabilities().top_n_extraction`: a non-capable backend (OpenEvolve) exits 1 with a clear "not supported on '<backend>'" error (FR-SOL-021)
3. Verify a program file `rank-<N>.py` exists in the run's `programs/` directory; on a top-N-capable backend (ShinkaEvolve) a missing `rank-<N>.py` is materialized on demand from the backend store (`programs.sqlite`) — retroactively on old runs, with no run-dir layout change
4. If `--force` is not set: verify no solution already exists for `(run_id, rank)` — prevent duplicates
5. If `--force` is set and a solution already exists for `(run_id, rank)`: delete the existing solution and its evaluation data before proceeding
6. Generate a new solution ID (`sol-YYYYMMDD-HHMMSS`)
7. Insert a solution DB row referencing `(run_id, rank)`
8. Evaluate the program on the training dataset (same as post-run eval for rank-1) and store results
9. Set alias if provided

**Output** (human):
```
Solution extracted: sol-20260311-091500
  Run: run-20260310-143000
  Rank: #1
  Score: 0.91
  Alias: claude-v1.1-best
  Training eval: 50 instances, mean combined_score=0.89
```

**Output** (JSON):
```json
{
  "solution_id": "sol-20260311-091500",
  "run_id": "run-20260310-143000",
  "rank": 1,
  "best_score": 0.91,
  "alias": "claude-v1.1-best",
  "training_eval": {
    "instance_count": 50,
    "mean_combined_score": 0.89
  }
}
```

**Exit codes**: 0 success, 1 if run not found, 1 if the requested program not found (or not materializable), 1 if solution already exists for this `(run, rank)` and `--force` not set, 1 if `--rank` > 1 or `--program-id` on a backend without `top_n_extraction`

### 2.5 `revolver solution delete <id-or-alias>`

Delete a solution and its associated evaluation data.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `id-or-alias` | Yes | Solution ID or alias to delete |

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--force` / `-f` | flag | false | Skip interactive confirmation prompt |

**Behavior**:
1. Resolve the solution by ID or alias
2. If `--json` is active and `--force` is not set, return an error (no interactive prompt possible in JSON mode)
3. If `--force` is not set, display solution details and ask for confirmation
4. Delete associated evaluation data (`eval_instances` then `eval_metadata`) within a transaction
5. Delete the solution row from the `solutions` table
6. The run and its program files are NOT deleted — only the DB reference and eval data are removed

**Output** (human):
```
Deleted solution "sol-20260310-143000" (alias: claude-small-v1.1)
  Cascade-deleted 1 evaluation(s)
```

**Output** (JSON):
```json
{
  "deleted": true,
  "solution_id": "sol-20260310-143000",
  "alias": "claude-small-v1.1"
}
```

**Exit codes**: 0 success, 1 if not found or confirmation declined

### 2.6 `revolver solution show <id-or-alias>`

Print the source code of a solution's program to stdout.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `id-or-alias` | Yes | Solution ID or alias |

**Output** (human):
```
# rank-1.py from run-20260310-143000
def solve(instance):
    ...
```

**Output** (JSON):
```json
{
  "alias": "claude-small-v1.1",
  "code": "def solve(instance):\n    ..."
}
```

**Exit codes**: 0 success, 1 if solution not found or program file missing

### 2.7 `revolver solution export <id-or-alias>`

Copy a solution's program file to a specified path.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `id-or-alias` | Yes | Solution ID or alias |

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `-o` / `--output <path>` | string | `<alias>.py` (or `<id>.py` if no alias) | Destination file path |

**Behavior**:
1. Resolve the solution by ID or alias
2. Locate the program file at `.revolver/runs/<run_id>/programs/rank-<N>.py`
3. Copy the file to the output path
4. If the output file already exists, overwrite it

**Output** (human):
```
Exported "claude-small-v1.1" → claude-small-v1.1.py
```

**Output** (JSON):
```json
{
  "solution_id": "sol-20260310-143000",
  "alias": "claude-small-v1.1",
  "output_path": "claude-small-v1.1.py"
}
```

**Exit codes**: 0 success, 1 if solution not found or program file missing

### 2.8 `revolver solution diff <a> <b>`

Show a unified diff between two solutions' program files.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `a` | Yes | First solution (ID or alias) |
| `b` | Yes | Second solution (ID or alias) |

**Output** (human):
```
--- claude-small-v1.1 (sol-20260310-143000, rank #1)
+++ gemma-small-v1.1 (sol-20260310-160000, rank #1)
@@ -1,5 +1,5 @@
 def solve(instance):
-    return greedy(instance)
+    return beam_search(instance)
```

**Output** (JSON):
```json
{
  "diff": "--- claude-small-v1.1 ...\n+++ gemma-small-v1.1 ...\n@@ ...",
  "identical": false
}
```

**Exit codes**: 0 success (including when files are identical), 1 if either solution not found or program file missing

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-SOL-001 | MUST | `list` shows all solutions with ID, alias, problem version, LLM, best score, rank, date | §4.6 |
| FR-SOL-002 | MUST | `list` supports filtering by problem version, LLM, and rank | — |
| FR-SOL-003 | MUST | `info` displays full lineage (problem version, dataset, LLM, config, generation time, iterations, rank, run_id) — lineage comes from the run (via JOIN), not from the solution itself | §4.6 |
| FR-SOL-004 | MUST | `info` shows program file path (derived from run directory and rank) | §4.6 |
| FR-SOL-005 | MUST | `info` shows evaluation results if available | — |
| FR-SOL-006 | MUST | `alias` sets a unique user-friendly name for a solution | §4.6 |
| FR-SOL-007 | MUST | Aliases are unique within a project | §4.6 |
| FR-SOL-008 | MUST | Solutions can be referenced by either ID or alias in all commands | — |
| FR-SOL-009 | SHOULD | `info` shows other solutions from the same run (if any were extracted) | §4.6 |
| FR-SOL-010 | MUST | Solutions reference their parent run via `run_id`. All lineage data is accessed through the run. | §4.6 |
| FR-SOL-011 | MUST | `extract` promotes the rank-1 program from a completed run into a solution with post-extraction training eval **by default**; an arbitrary rank or population program ID is reachable via FR-SOL-021 | — |
| FR-SOL-012 | MUST | `extract` prevents duplicate solutions for the same `(run_id, rank)` unless `--force` is set (`--force` semantics apply per rank) | — |
| FR-SOL-013 | MUST | `extract` generates a unique solution ID and inserts a solution DB row | — |
| FR-SOL-014 | MUST | `delete` removes a solution by ID or alias with interactive confirmation prompt | §4.6 |
| FR-SOL-015 | MUST | `delete --force` bypasses the interactive confirmation prompt | — |
| FR-SOL-016 | MUST | Deleting a solution cascade-deletes associated evaluation data (`eval_metadata` + `eval_instances`) | — |
| FR-SOL-017 | MUST | `delete` in JSON mode (`--json`) without `--force` returns an error (no interactive prompt possible) | NFR-003 |
| FR-SOL-018 | MUST | `show` displays the source code of a solution's program to stdout; `--json` outputs `{"alias":..., "code":...}` | §4.6 |
| FR-SOL-019 | MUST | `export` copies a solution's program file to a local path (default `<alias>.py`) | §4.6 |
| FR-SOL-020 | MUST | `diff` shows a unified diff between two solutions' programs; `--json` returns `{"diff":..., "identical": bool}` | §4.6 |
| FR-SOL-021 | MUST | `extract --rank <N>` (and `--program-id <id>` where supported) promotes an arbitrary-ranked/identified population program, **gated on the run backend's `capabilities().top_n_extraction`** (the capability exists since ADR-007 — this adds its consumer): ShinkaEvolve reads `programs.sqlite` retroactively (no run-dir layout change) and materializes `programs/rank-<N>.py`; a non-capable backend (OpenEvolve — consciously deferred: checkpoint-granularity limit, and OE ranking must first ride on `combined_score` per FR-RUN-052) exits 1 with a clear "not supported on '<backend>'" error; `(run_id, rank)` uniqueness is enforced; `--rank 1` behaves exactly as today (#299) | — |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Solution ID or alias not found | Error: "Solution '<id>' not found" | 1 |
| Alias already in use by another solution | Error: "Alias '<alias>' already in use by solution '<other-id>'" | 1 |
| Empty alias string | Error: "Alias cannot be empty" | 1 |
| `extract` with non-existent run | Error: "Run '<run-id>' not found" | 1 |
| `extract` with run not completed | Error: "Run '<run-id>' is not completed (status: '<status>')" | 1 |
| `extract` with missing program at the requested rank (absent file and not materializable from the backend store) | Error: "No program found at rank <N> for run '<run-id>'" | 1 |
| `extract` with already extracted rank (no `--force`) | Error: "Solution already exists for run '<run-id>' rank <N>: '<sol-id>'. Use --force to replace." | 1 |
| `extract --rank <N>` (N > 1) or `--program-id` on a backend without `top_n_extraction` (OpenEvolve) | Error: "Top-N extraction is not supported on backend '<backend>'." (FR-SOL-021) | 1 |
| `show` with missing program file | Error: "Program file not found for solution '<id>'" | 1 |
| `export` with missing program file | Error: "Program file not found for solution '<id>'" | 1 |
| `diff` with either solution not found | Error: "Solution '<id>' not found" | 1 |
| `diff` with missing program file | Error: "Program file not found for solution '<id>'" | 1 |
| `delete` with non-existent solution | Error: "Solution '<id>' not found" | 1 |
| `delete` in JSON mode without `--force` | Error: "Use --force to delete in JSON mode (no interactive prompt)" | 1 |
| `delete` confirmation declined by user | No deletion, exit silently | 1 |
| Not in a Revolver project | Error: "Not a Revolver project" | 1 |

---

## 5. Dependencies

- Rank-1 solutions are auto-created by `revolver run` ([spec-run.md](spec-run.md))
- Additional solutions are created by `solution extract` (this spec)
- `extract` reuses `core.eval.evaluate_solution()` for post-extraction training eval ([spec-eval.md](spec-eval.md))
- Evaluation results referenced in `info` come from `revolver eval` ([spec-eval.md](spec-eval.md))
- Solution schema defined in DES-001 (solutions table)
