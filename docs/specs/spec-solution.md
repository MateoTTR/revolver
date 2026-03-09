# Spec: revolver solution

**Traceable to**: ConOps §4.6 (Solution)
**Status**: Draft

---

## 1. Scope

This spec covers solution browsing and metadata management. Solutions are created by `revolver run` ([spec-run.md](spec-run.md)) — this spec only covers read and update operations on existing solutions.

---

## 2. Commands

### 2.1 `revolver solution list`

List all solutions in the current project.

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--version <tag>` | string | — | Filter by problem version |
| `--llm <name>` | string | — | Filter by LLM used |
| `--sort <field>` | string | `created_at` | Sort by: `created_at`, `score`, `alias` |

**Output** (human):
```
ID                      Alias               Version  LLM          Score   Date
sol-20260310-143000     claude-small-v1.1   v1.1     claude-opus  0.91    2026-03-10
sol-20260310-160000     gemma-small-v1.1    v1.1     gemma-local  0.82    2026-03-10
sol-20260311-090000     —                   v1.0     claude-opus  0.78    2026-03-11
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

Lineage:
  Problem version: v1.1 (sha256:e5f6g7h8...)
  Training dataset: train-small (sha256:f1e2d3c4...)
  LLM: claude-opus (claude-opus-4-6)
  Iterations: 200
  Generation time: 3h45m

Files:
  .revolver/solutions/sol-20260310-143000/
  ├── best.py
  ├── config.yaml
  ├── manifest.yaml
  └── oe-checkpoint/

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
| FR-SOL-001 | MUST | `list` shows all solutions with ID, alias, problem version, LLM, best score, date | §4.6 |
| FR-SOL-002 | MUST | `list` supports filtering by problem version and LLM | — |
| FR-SOL-003 | MUST | `info` displays full lineage (problem version, dataset, LLM, config, generation time, iterations) | §4.6 |
| FR-SOL-004 | MUST | `info` shows file paths to the stored solution programs | §4.6 |
| FR-SOL-005 | MUST | `info` shows evaluation results if available | — |
| FR-SOL-006 | MUST | `alias` sets a unique user-friendly name for a solution | §4.6 |
| FR-SOL-007 | MUST | Aliases are unique within a project | §4.6 |
| FR-SOL-008 | MUST | Solutions can be referenced by either ID or alias in all commands | — |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Solution ID or alias not found | Error: "Solution '<id>' not found" | 1 |
| Alias already in use by another solution | Error: "Alias '<alias>' already in use by solution '<other-id>'" | 1 |
| Empty alias string | Error: "Alias cannot be empty" | 1 |
| Not in a Revolver project | Error: "Not a Revolver project" | 1 |

---

## 5. Dependencies

- Solutions are created by `revolver run` ([spec-run.md](spec-run.md))
- Evaluation results referenced in `info` come from `revolver eval` ([spec-eval.md](spec-eval.md))
