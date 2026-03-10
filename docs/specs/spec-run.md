# Spec: revolver run

**Traceable to**: ConOps §4.6 (Solution), §5.5 (Workflow: Generate a Solution), §3.3 (Concurrency Model), §4.4 (Instance Injection)
**Status**: Draft

---

## 1. Scope

This spec covers solution generation via OpenEvolve orchestration. `revolver run` is the core command that ties together a problem version, a dataset, and an LLM to produce evolved solutions.

---

## 2. Commands

### 2.1 `revolver run`

Launch an OpenEvolve evolution run.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--version <tag>` | string | Yes | Problem version to use |
| `--llm <name>` | string | Yes | Registered LLM to use |
| `--dataset <name>` | string | Yes | Registered training dataset |
| `--iterations <n>` | int | No | Number of evolution iterations. Overrides config.yaml value. |
| `--alias <name>` | string | No | User-friendly name for the generated solution |
| `--top-n <n>` | int | No | Number of top solutions to keep. Default: 1 |
| `--config-override <key=value>` | string[] | No | Override specific OpenEvolve config values |

**Behavior**:
1. **Validate inputs**:
   - Problem version exists
   - LLM is registered and reachable (loaded for local, API key set for remote)
   - Dataset is registered and compatible with the problem version (warn if not)
   - If dataset split is not `train`, display a warning (do not block)
2. **Verify dataset integrity**: recompute hashes, warn on mismatch
3. **Prepare environment**:
   - Set `REVOLVER_DATASET_DIR` to the dataset path
   - Set OpenEvolve config to use the LLM's base URL
4. **Launch OpenEvolve** with the problem version's files (initial_program, evaluator, config)
5. **Monitor progress**: display iteration count, best score, elapsed time
6. **On completion**:
   - Store the top-N solutions in `.revolver/solutions/<auto-id>/`
   - Record full lineage in `manifest.yaml`
   - Store metrics in SQLite
   - Copy the OpenEvolve checkpoint for potential resume

**Output** (human, during run):
```
Run started: v1.1 + claude-opus + train-small
  Iteration 42/200 | Best score: 0.87 | Elapsed: 1h15m | ETA: 2h05m
```

**Output** (human, on completion):
```
Run completed: 200 iterations in 3h45m
  Solution: sol-20260310-143000
  Alias: claude-small-v1.1
  Best combined_score: 0.91
  Stored in: .revolver/solutions/sol-20260310-143000/
```

**Output** (JSON, on completion):
```json
{
  "solution_id": "sol-20260310-143000",
  "alias": "claude-small-v1.1",
  "problem_version": "v1.1",
  "llm": "claude-opus",
  "dataset": "train-small",
  "iterations": 200,
  "best_score": 0.91,
  "generation_time_s": 13500,
  "path": ".revolver/solutions/sol-20260310-143000/"
}
```

**Exit codes**: 0 success, 1 invalid inputs, 2 dataset integrity failure, 3 LLM unavailable, 4 OpenEvolve failure

### 2.2 `revolver run status`

Show the status of the current or most recent run.

**Output** (human):
```
Run in progress: sol-20260310-143000
  Problem: v1.1 | LLM: claude-opus | Dataset: train-small
  Iteration: 42/200 | Best score: 0.87
  Started: 2026-03-10 14:30 | Elapsed: 1h15m
```

**Exit codes**: 0 always

### 2.3 `revolver run resume`

Resume an interrupted run from its checkpoint.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--solution <id-or-alias>` | string | Yes | Solution whose checkpoint to resume from |

**Behavior**:
1. Locate the OpenEvolve checkpoint in the solution's directory
2. Verify the checkpoint is valid and resumable
3. Re-launch OpenEvolve from the checkpoint with the same configuration
4. On completion: update the existing solution (same ID, updated metrics)

**Exit codes**: 0 success, 1 if solution or checkpoint not found, 4 if OpenEvolve fails

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-RUN-001 | MUST | Validate that problem version, LLM, and dataset exist before starting | — |
| FR-RUN-002 | MUST | Warn (do not block) if the dataset's split is not `train` | §4.3 |
| FR-RUN-003 | MUST | Warn (do not block) if the dataset is not declared compatible with the problem version | §7.4 |
| FR-RUN-004 | MUST | Verify dataset integrity (hash check) before starting; warn on mismatch | §7.2 |
| FR-RUN-005 | MUST | Set `REVOLVER_DATASET_DIR` environment variable for the evaluator | §4.4 |
| FR-RUN-006 | MUST | Configure OpenEvolve to use the LLM's base URL and model ID | §3.2 |
| FR-RUN-007 | MUST | Generate a unique solution ID: `sol-{YYYYMMDD}-{HHMMSS}` | §4.6 |
| FR-RUN-008 | MUST | Store the top-N best programs in `.revolver/solutions/<id>/` | §4.6 |
| FR-RUN-009 | MUST | Record full lineage in `manifest.yaml`: problem version, dataset, LLM, config, timestamp, iterations, generation time | §4.6 |
| FR-RUN-010 | MUST | Store metrics (best scores per iteration) in SQLite | §4.6 |
| FR-RUN-019 | MUST | On completion, evaluate the best program on all training instances and store raw per-instance results in SQLite (same format as `revolver eval`) | §4.6 |
| FR-RUN-020 | MUST | Training results are accessible via `revolver eval results --solution <id> --dataset <train-dataset>` | — |
| FR-RUN-011 | MUST | Store the OpenEvolve checkpoint for resume capability | §4.6, §5.5 |
| FR-RUN-012 | MUST | Support `--alias` for user-friendly solution naming | §4.6 |
| FR-RUN-013 | MUST | `resume` restores an interrupted run from checkpoint | §5.5 |
| FR-RUN-014 | MUST | Local LLM runs execute sequentially (one at a time) | §3.3 |
| FR-RUN-015 | MUST | Remote LLM runs can execute in parallel | §3.3 |
| FR-RUN-016 | SHOULD | Display progress during the run (iteration count, best score, elapsed time) | — |
| FR-RUN-017 | SHOULD | Store the OpenEvolve config used (verbatim copy) in the solution directory | NFR-023 |
| FR-RUN-018 | SHOULD | Record generation wall-clock time in solution lineage | §4.6 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Problem version not found | Error: "Problem version '<tag>' not found" | 1 |
| LLM not registered | Error: "LLM '<name>' not found" | 1 |
| Local LLM not loaded | Error: "LLM '<name>' is not loaded. Run `revolver llm start <name>` first." | 3 |
| Remote LLM API key not set | Error: "API key not configured. Set <ENV_VAR> environment variable." | 3 |
| Dataset not found | Error: "Dataset '<name>' not found" | 1 |
| Dataset split is not `train` | Warning: "Dataset '<name>' has split 'eval'. Consider using a training dataset." | 0 (continue) |
| Dataset hash mismatch | Warning: "Dataset '<name>' has been modified since registration. Results may not be reproducible." | 0 (continue) |
| Dataset incompatible with problem version | Warning: "Dataset '<name>' is not declared compatible with version '<tag>'." | 0 (continue) |
| OpenEvolve crashes during run | Error: "OpenEvolve failed: <error>". Preserve partial results if any. | 4 |
| Resume with no checkpoint | Error: "No checkpoint found for solution '<id>'" | 1 |
| Another local run already in progress | Error: "A local LLM run is already in progress. Wait for it to complete or cancel it." | 3 |
| Not in a Revolver project | Error: "Not a Revolver project" | 1 |

---

## 5. Solution Manifest Format

`.revolver/solutions/<id>/manifest.yaml`:

```yaml
solution_id: "sol-20260310-143000"
alias: "claude-small-v1.1"
created_at: "2026-03-10T14:30:00Z"
generation_time_s: 13500
iterations: 200

lineage:
  problem_version: "v1.1"
  problem_hash: "sha256:e5f6g7h8..."
  dataset: "train-small"
  dataset_hash: "sha256:f1e2d3c4..."
  llm: "claude-opus"
  llm_model: "claude-opus-4-6"

best_score: 0.91
top_n: 1
files:
  - "best.py"

checkpoint: "oe-checkpoint/"
config_snapshot: "config.yaml"
```

---

## 6. Dependencies

- Requires an initialized project ([spec-project.md](spec-project.md))
- Requires a problem version ([spec-problem.md](spec-problem.md))
- Requires a registered LLM ([spec-llm.md](spec-llm.md))
- Requires a registered dataset ([spec-dataset.md](spec-dataset.md))
- Solutions produced here are consumed by `revolver eval` ([spec-eval.md](spec-eval.md)) and `revolver benchmark` ([spec-benchmark.md](spec-benchmark.md))
