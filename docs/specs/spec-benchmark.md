# Spec: revolver benchmark

**Traceable to**: ConOps §4.7 (Benchmark), §5.7 (Workflow: Benchmark Multiple Solutions), §8 (Export Format)
**Status**: Draft

---

## 1. Scope

This spec covers multi-solution benchmarking and result export. A benchmark evaluates multiple solutions against a single evaluation dataset and produces a comparative table. It builds on the evaluation mechanism from [spec-eval.md](spec-eval.md).

---

## 2. Commands

### 2.1 `revolver benchmark`

Run a comparative benchmark of multiple solutions.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--solutions <id-or-alias>...` | string[] | Yes | Solutions to compare (space-separated) |
| `--dataset <name>` | string | Yes | Registered evaluation dataset |
| `--timeout <seconds>` | int | No | Per-instance timeout. Default: 300s |
| `--alias <name>` | string | No | User-friendly name for this benchmark |

**Behavior**:
1. Validate all solutions exist and dataset exists with split `eval`
2. For each solution that does not already have evaluation results on this dataset: run the evaluation (same as `revolver eval`)
3. For each solution that already has results: reuse stored results (skip re-evaluation)
4. Aggregate results into a comparative table
5. Store benchmark metadata and results in SQLite

**Output** (human):
```
Benchmark: 3 solutions on "eval-benchmark" (100 instances)

combined_score:
  Solution              mean    min     max     p90     std     gen_time  eval_time
  claude-small-v1.1     0.87    0.62    0.95    0.93    0.08    2h15m     60s
  gemma-small-v1.1      0.82    0.55    0.91    0.89    0.11    1h30m     55s
  claude-large-v1.1     0.91    0.70    0.97    0.95    0.06    3h45m     62s
```

**Output** (JSON):
```json
{
  "benchmark_id": "bench-20260310-170000",
  "dataset": "eval-benchmark",
  "instance_count": 100,
  "results": [
    {
      "solution_id": "sol-20260310-143000",
      "alias": "claude-small-v1.1",
      "lineage": {
        "problem_version": "v1.1",
        "llm": "claude-opus",
        "train_dataset": "train-small",
        "iterations": 200,
        "generation_time_s": 8100
      },
      "metrics": {
        "combined_score": {"mean": 0.87, "min": 0.62, "max": 0.95, "p10": 0.71, "p50": 0.88, "p90": 0.93, "std": 0.08}
      },
      "eval_time_s": 60,
      "instances_solved": 100
    }
  ],
  "created_at": "2026-03-10T17:00:00Z"
}
```

**Exit codes**: 0 success, 1 invalid inputs, 4 if evaluation fails for all solutions

### 2.2 `revolver benchmark results`

Display results of a previous benchmark.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--latest` | flag | No | Show the most recent benchmark |
| `--id <bench-id>` | string | No | Show a specific benchmark by ID |
| `--metric <name>` | string | No | Filter to a single metric. Default: show all |

**Exit codes**: 0 success, 1 if no results found

### 2.3 `revolver benchmark export`

Export benchmark results to a file.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--latest` | flag | No | Export the most recent benchmark |
| `--id <bench-id>` | string | No | Export a specific benchmark by ID |
| `--format <fmt>` | string | Yes | `csv` or `json` |
| `--output <path>` | string | Yes | Output file path |

**CSV format** (see ConOps §8.1):
```
benchmark_id,solution_id,solution_alias,problem,problem_version,llm,train_dataset,eval_dataset,objective,mean,min,max,p10,p50,p90,std,gen_time_s,eval_time_s,instances_count,instances_solved
```

**JSON format**: same structure as ConOps §8.2.

**Exit codes**: 0 success, 1 if no results or invalid format

### 2.4 `revolver benchmark list`

List all benchmarks.

**Output** (human):
```
ID                      Date                 Dataset          Solutions  Alias
bench-20260310-170000   2026-03-10 17:00     eval-benchmark   3          baseline-comparison
bench-20260312-090000   2026-03-12 09:00     eval-benchmark   5          —
```

**Exit codes**: 0 always

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-BEN-001 | MUST | Accept multiple solutions and a single evaluation dataset | §5.7 |
| FR-BEN-002 | MUST | Reuse existing evaluation results when available (avoid redundant computation) | — |
| FR-BEN-003 | MUST | Run evaluation for solutions without existing results on the dataset | §5.7 |
| FR-BEN-004 | MUST | Produce a comparative table with per-metric aggregate statistics | §4.7 |
| FR-BEN-005 | MUST | Include lineage information (problem version, LLM, training dataset, generation time) | §4.7 |
| FR-BEN-006 | MUST | Store benchmark metadata and results in SQLite | NFR-013 |
| FR-BEN-007 | MUST | Export results in CSV format matching ConOps §8.1 schema | §8.1 |
| FR-BEN-008 | MUST | Export results in JSON format matching ConOps §8.2 schema | §8.2 |
| FR-BEN-009 | MUST | Include eval_time_s and instances_solved in results | §4.7 |
| FR-BEN-010 | SHOULD | Sort the comparative table by a configurable metric (default: `combined_score` mean) | — |
| FR-BEN-011 | SHOULD | Include generation_time_s from solution lineage for cost/quality comparison | §4.7 |
| FR-BEN-012 | MUST | `list` shows all past benchmarks with date, dataset, solution count | — |
| FR-BEN-013 | MUST | No secrets (API keys, file paths) in exported data | NFR-052 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Fewer than 1 solution provided | Error: "Provide at least one solution" | 1 |
| Solution not found | Error: "Solution '<id>' not found" | 1 |
| Dataset not found | Error: "Dataset '<name>' not found" | 1 |
| Dataset split is `train` | Error: "Use an evaluation dataset (split: eval)" | 1 |
| Evaluation fails for one solution | Mark as failed, continue with remaining solutions | — |
| Evaluation fails for all solutions | Error: "Evaluation failed for all solutions" | 4 |
| `--format` not `csv` or `json` | Error: "Unsupported format. Use 'csv' or 'json'" | 1 |
| Output path not writable | Error: "Cannot write to <path>" | 1 |
| No benchmark results found (for `results`/`export`) | Error: "No benchmark found" | 1 |
| Not in a Revolver project | Error: "Not a Revolver project" | 1 |

---

## 5. Dependencies

- Requires solutions from `revolver run` ([spec-run.md](spec-run.md))
- Uses the evaluation mechanism from `revolver eval` ([spec-eval.md](spec-eval.md))
- Requires a registered dataset with split `eval` ([spec-dataset.md](spec-dataset.md))
- Export formats defined in ConOps §8
