# Spec: revolver solution

**Traceable to**: ConOps §4.6 (Solution), DES-001 v0.2 (solutions table)
**Status**: Draft

---

## 1. Scope

This spec covers solution browsing and metadata management. Solutions are lightweight DB references to (`run_id`, `rank`) — they do NOT own filesystem directories. The program file for a solution is located at `.revolver/runs/<run_id>/programs/rank-<N>.py`. Solutions are created by `revolver run` ([spec-run.md](spec-run.md)) — this spec only covers read and update operations on existing solutions.

---

## 2. Commands

### 2.1 `revolver solution list`

List all solutions in the current project.

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--version <tag>` | string | — | Filter by problem version |
| `--llm <name>` | string | — | Filter by LLM used |
| `--rank <n>` | int | — | Filter by rank (1 = best from run). Useful to hide secondary solutions from top-N runs |
| `--sort <field>` | string | `created_at` | Sort by: `created_at`, `score`, `alias` |

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
  Rank: #1 of 3

Run: run-20260310-143000
  Problem version: v1.1 (sha256:e5f6g7h8...)
  Training dataset: train-small (sha256:f1e2d3c4...)
  LLM: claude-opus (claude-opus-4-6)
  Iterations: 200
  Generation time: 3h45m

Program: .revolver/runs/run-20260310-143000/programs/rank-1.py

Sibling solutions (same run):
  sol-20260310-143001  #2  score=0.85  (no alias)
  sol-20260310-143002  #3  score=0.79  (no alias)

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
| FR-SOL-009 | SHOULD | `info` shows sibling solutions from the same run (when top-N > 1) | §4.6 |
| FR-SOL-010 | MUST | Solutions reference their parent run via `run_id`. All lineage data is accessed through the run. | §4.6 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Solution ID or alias not found | Error: "Solution '<id>' not found" | 1 |
| Alias already in use by another solution | Error: "Alias '<alias>' already in use by solution '<other-id>'" | 1 |
| Empty alias string | Error: "Alias cannot be empty" | 1 |
| `--rank` value <= 0 | Error: "Rank must be a positive integer" | 1 |
| Not in a Revolver project | Error: "Not a Revolver project" | 1 |

---

## 5. Dependencies

- Solutions are created by `revolver run` ([spec-run.md](spec-run.md))
- Evaluation results referenced in `info` come from `revolver eval` ([spec-eval.md](spec-eval.md))
- Solution schema defined in DES-001 (solutions table)
