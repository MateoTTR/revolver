# Spec: revolver solution

**Traceable to**: ConOps §4.6 (Solution), DES-001 v0.2 (solutions table)
**Status**: Draft

---

## 1. Scope

This spec covers solution browsing, metadata management, on-demand extraction, and deletion. Solutions are lightweight DB references to (`run_id`, `rank`) — they do NOT own filesystem directories. The program file for a solution is located at `.revolver/runs/<run_id>/programs/rank-<N>.py`. The rank-1 solution is auto-created by `revolver run` ([spec-run.md](spec-run.md)). Additional solutions can be extracted from a run's stored programs via `solution extract`.

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

Promote a lower-ranked program from a run into a first-class solution. This enables on-demand inspection: the user runs `revolver run info` to see all stored programs with scores, then extracts the ones worth evaluating.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--run <run-id>` | string | Yes | Run containing the program to extract |
| `--rank <n>` | int | Yes | Rank of the program to promote (e.g., 2, 3) |
| `--alias <name>` | string | No | User-friendly name for the new solution |

**Behavior**:
1. Verify the run exists and has status `completed`
2. Verify a program file `rank-<N>.py` exists in the run's `programs/` directory
3. Verify no solution already exists for `(run_id, rank)` — prevent duplicates
4. Generate a new solution ID (`sol-YYYYMMDD-HHMMSS`)
5. Insert a solution DB row referencing `(run_id, rank)`
6. Evaluate the program on the training dataset (same as post-run eval for rank-1) and store results
7. Set alias if provided

**Output** (human):
```
Solution extracted: sol-20260311-091500
  Run: run-20260310-143000
  Rank: #2
  Score: 0.85
  Alias: claude-v1.1-rank2
  Training eval: 50 instances, mean combined_score=0.83
```

**Output** (JSON):
```json
{
  "solution_id": "sol-20260311-091500",
  "run_id": "run-20260310-143000",
  "rank": 2,
  "best_score": 0.85,
  "alias": "claude-v1.1-rank2",
  "training_eval": {
    "instance_count": 50,
    "mean_combined_score": 0.83
  }
}
```

**Exit codes**: 0 success, 1 if run not found, 1 if rank not found, 1 if solution already exists for this (run, rank)

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
| FR-SOL-011 | MUST | `extract` promotes a stored program from a completed run into a solution with post-extraction training eval | — |
| FR-SOL-012 | MUST | `extract` prevents duplicate solutions for the same `(run_id, rank)` | — |
| FR-SOL-013 | MUST | `extract` generates a unique solution ID and inserts a solution DB row | — |
| FR-SOL-014 | MUST | `delete` removes a solution by ID or alias with interactive confirmation prompt | §4.6 |
| FR-SOL-015 | MUST | `delete --force` bypasses the interactive confirmation prompt | — |
| FR-SOL-016 | MUST | Deleting a solution cascade-deletes associated evaluation data (`eval_metadata` + `eval_instances`) | — |
| FR-SOL-017 | MUST | `delete` in JSON mode (`--json`) without `--force` returns an error (no interactive prompt possible) | NFR-003 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Solution ID or alias not found | Error: "Solution '<id>' not found" | 1 |
| Alias already in use by another solution | Error: "Alias '<alias>' already in use by solution '<other-id>'" | 1 |
| Empty alias string | Error: "Alias cannot be empty" | 1 |
| `--rank` value <= 0 | Error: "Rank must be a positive integer" | 1 |
| `extract` with non-existent run | Error: "Run '<run-id>' not found" | 1 |
| `extract` with run not completed | Error: "Run '<run-id>' is not completed (status: '<status>')" | 1 |
| `extract` with non-existent rank file | Error: "No program found at rank <N> for run '<run-id>'" | 1 |
| `extract` with already extracted rank | Error: "Solution already exists for run '<run-id>' rank <N>: '<sol-id>'" | 1 |
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
