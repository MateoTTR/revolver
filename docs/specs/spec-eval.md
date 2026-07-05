# Spec: revolver eval

**Traceable to**: ConOps §5.6 (Workflow: Evaluate a Single Solution), §4.4 (Instance Injection), §4.5 (Metrics), DES-006 v0.2
**Status**: Draft

---

## 1. Scope

This spec covers single-solution evaluation against an evaluation dataset. The evaluation loop iterates over each instance, runs the evaluator in single-instance mode, collects metrics, and computes aggregate statistics.

---

## 2. Commands

### 2.1 `revolver eval`

Evaluate a solution against an evaluation dataset.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--solution <id-or-alias>` | string | Yes | Solution to evaluate |
| `--dataset <name>` | string | Yes | Registered evaluation dataset |
| `--timeout <seconds>` | int | No | Per-instance timeout. Default: 300s |
| `--parallelism <n>` | int | No | Number of instances to evaluate concurrently. Default: 1 |
| `--force` | flag | No | Skip confirmation and re-evaluate even if results already exist |
| `--per-instance` | flag | No | Show per-instance results on completion instead of aggregates only |

**Behavior**:
1. **Validate inputs**: solution exists, dataset exists (warn if split is not `eval`)
2. **Check for existing results**: check for existing evaluation results for this (solution, dataset) pair. If results exist: in interactive mode, prompt for confirmation ("Evaluation already exists for solution X on dataset Y. Re-evaluate? [y/N]"); in `--json` mode, return error (use `--force` to override). If `--force` is set, skip confirmation and delete existing results before proceeding.
3. **Verify dataset integrity**: recompute hashes, warn on mismatch
4. **Check compatibility**: warn if dataset not declared compatible with the solution's problem version
5. **Evaluation loop**: for each instance in the dataset:
   - Set `REVOLVER_INSTANCE_PATH` → path to the instance
   - Set `REVOLVER_INSTANCE_ID` → instance identifier (filename or dirname)
   - Call `evaluate(solution_best_program_path)`
   - Collect returned `dict[str, float]` and wall-clock time
6. **Legacy global aggregation** (D-006-g): if the evaluator uses `evaluate()` (legacy mode), make one additional call to `evaluate()` with `REVOLVER_DATASET_DIR` set (and `REVOLVER_INSTANCE_PATH` unset) to collect user-defined aggregates. Store the result in `user_aggregates` JSON column of `eval_metadata`.
7. **Store raw results** in SQLite: full `dict[str, float]` per instance (all metrics, not just aggregates)
8. **Compute and display aggregates** at read time from stored raw data

**Output** (human):
```
Evaluating "claude-small-v1.1" on "eval-benchmark" (100 instances)
  [████████████████████████████████] 100/100

Results:
  Metric          mean    min     max     p10     p50     p90     std
  combined_score  0.87    0.62    0.95    0.71    0.88    0.93    0.08
  makespan        142.5   98.0    210.0   105.0   140.0   185.0   28.3

  Instances: 100/100 solved
  Compute time: mean=1.2s, max=4.5s, total=120s

  User aggregates (legacy evaluator):
    combined_score: 0.84
    makespan: 148.2
```

**Output** (JSON, default — aggregates):
```json
{
  "eval_id": "eval-20260310-160000",
  "solution": "claude-small-v1.1",
  "dataset": "eval-benchmark",
  "instance_count": 100,
  "instances_solved": 100,
  "aggregates": {
    "combined_score": {"mean": 0.87, "min": 0.62, "max": 0.95, "p10": 0.71, "p50": 0.88, "p90": 0.93, "std": 0.08},
    "makespan": {"mean": 142.5, "min": 98.0, "max": 210.0, "p10": 105.0, "p50": 140.0, "p90": 185.0, "std": 28.3}
  },
  "compute_time": {"mean_s": 1.2, "max_s": 4.5, "total_s": 120.0},
  "user_aggregates": {"combined_score": 0.84, "makespan": 148.2},
  "evaluated_at": "2026-03-10T16:00:00Z"
}
```

**Output** (JSON, `--per-instance`):
```json
{
  "eval_id": "eval-20260310-160000",
  "solution": "claude-small-v1.1",
  "dataset": "eval-benchmark",
  "instances": [
    {"instance_id": "instance_001.json", "status": "solved", "metrics": {"combined_score": 0.91, "makespan": 105.0}, "time_s": 0.8},
    {"instance_id": "instance_002.json", "status": "solved", "metrics": {"combined_score": 0.85, "makespan": 142.0}, "time_s": 1.1},
    {"instance_id": "instance_003.json", "status": "failed", "error": "Timeout after 300s", "metrics": null, "time_s": null}
  ]
}
```

**Exit codes**: 0 success, 1 invalid inputs (including existing results in `--json` mode without `--force`), 2 dataset integrity failure, 4 if evaluator fails on all instances

### 2.2 `revolver eval results`

Display results of a previous evaluation.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--solution <id-or-alias>` | string | Yes | Solution whose results to show |
| `--dataset <name>` | string | No | Filter by dataset. Defaults to most recent evaluation. |
| `--per-instance` | flag | No | Show per-instance results instead of aggregates |

**Output** (human, `--per-instance`):
```
Instance              combined_score  makespan  time_s
instance_001.json     0.91            105.0     0.8
instance_002.json     0.85            142.0     1.1
instance_003.json     FAILED          —         —
...
```

**Exit codes**: 0 success, 1 if no results found

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-EVL-001 | MUST | Iterate over all instances in the evaluation dataset | §5.6 |
| FR-EVL-002 | MUST | Set `REVOLVER_INSTANCE_PATH` and `REVOLVER_INSTANCE_ID` per instance | §4.4 |
| FR-EVL-003 | MUST | Call the evaluator from the solution's problem version (not the mutable working copy) | §7.1 |
| FR-EVL-004 | MUST | Collect the full `dict[str, float]` return value and wall-clock time per instance | §4.5 |
| FR-EVL-005 | MUST | Store raw per-instance results in SQLite: instance ID, full metrics dict, wall-clock time, status (solved/failed/timeout), error message if any | NFR-013 |
| FR-EVL-006 | MUST | Compute aggregate statistics (mean, min, max, p10, p50, p90, std) at read time from stored raw data — aggregates are not stored separately | NFR-013 |
| FR-EVL-007 | MUST | Verify dataset integrity before evaluation | §7.2 |
| FR-EVL-008 | MUST | Warn if dataset is not compatible with the solution's problem version | §7.4 |
| FR-EVL-009 | MUST | Warn (do not block) if dataset split is not `eval`. The post-run training evaluation (FR-RUN-019/020) suppresses this warning (`warn_split=False`): evaluating the training split there is by design. | §4.3 |
| FR-EVL-010 | MUST | Handle evaluator exceptions per instance without aborting the full evaluation | — |
| FR-EVL-011 | MUST | Record instances where evaluation failed (count as "unsolved") | §5.6 |
| FR-EVL-012 | SHOULD | Display a progress bar during evaluation | — |
| FR-EVL-013 | SHOULD | Enforce a per-instance timeout | — |
| FR-EVL-014 | MAY | Support `--parallelism` for concurrent instance evaluation | — |
| FR-EVL-015 | MUST | `results` command retrieves stored evaluation results from SQLite | — |
| FR-EVL-016 | MUST | `results --per-instance` shows per-instance breakdown with full metrics dict | — |
| FR-EVL-017 | MUST | `results --per-instance --json` exports all raw per-instance data for external post-processing (histograms, plots, custom analysis) | — |
| FR-EVL-018 | MUST | If evaluation results already exist for a (solution, dataset) pair, require confirmation before re-evaluating. `--force` skips confirmation. In `--json` mode, return error without `--force`. | — |
| FR-EVL-019 | MUST | For legacy evaluators (`evaluate()`), perform a global aggregation call after per-instance evaluation: call `evaluate()` with `REVOLVER_DATASET_DIR` set and `REVOLVER_INSTANCE_PATH` unset. Store result in `user_aggregates`. | DES-006 v0.2 |
| FR-EVL-020 | MUST | Display both Revolver-computed aggregates and user aggregates (if available) in results output. | DES-006 v0.2 |
| FR-EVL-021 | MUST | Metric aggregation (both the training/run aggregation loop and eval aggregation) MUST guard against non-numeric metric fields: only values that are `int` or `float` (excluding `bool`) are aggregated; non-numeric fields (e.g. an `error` string returned on some instances) are skipped, not coerced to 0.0 or allowed to crash the aggregation. A candidate returning a non-numeric field on some instances is scored on its numeric metrics only (B1). The reserved **`instances_*` coverage keys** (`instances_valid`/`instances_total` — FR-RUN-053) are likewise **excluded from aggregation everywhere** (the training/run loop and read-time `compute_aggregates` alike): coverage is metadata, never averaged into a score (U13/#367). | DES-006 §4.3 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Solution not found | Error: "Solution '<id>' not found" | 1 |
| Dataset not found | Error: "Dataset '<name>' not found" | 1 |
| Dataset split is `train` | Warning: "Dataset '<name>' has split 'train'. Results may reflect training performance." | 0 (continue) |
| Dataset hash mismatch | Warning: "Dataset modified since registration" | 0 (continue) |
| Evaluator fails on a single instance | Mark as failed, continue to next instance | — |
| Evaluator fails on all instances | Error: "Evaluation failed on all instances" | 4 |
| Evaluation results already exist (without `--force`) | Error (JSON mode): "Evaluation already exists for solution X on dataset Y. Use --force to re-evaluate." / Warning + prompt (interactive mode) | 1 (JSON) / 0 (interactive, user confirms) |
| No previous results found (for `results`) | Error: "No evaluation found for solution '<id>' on dataset '<name>'. Run `revolver eval --solution <id> --dataset <name>` first." | 1 |
| Not in a Revolver project | Error: "Not a Revolver project" | 1 |

---

## 5. Dependencies

- Requires solutions produced by `revolver run` ([spec-run.md](spec-run.md))
- Requires a registered dataset ([spec-dataset.md](spec-dataset.md))
- Uses the same evaluator and instance injection mechanism as `revolver problem test` ([spec-problem.md](spec-problem.md))
- Results are consumed by `revolver benchmark` ([spec-benchmark.md](spec-benchmark.md))
