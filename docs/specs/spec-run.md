# Spec: revolver run

**Traceable to**: ConOps §4.6 (Solution), §5.5 (Workflow: Generate a Solution), §3.3 (Concurrency Model), §4.4 (Instance Injection), DES-005 v0.3
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
| `--config-override <key=value>` | string[] | No | Override specific OpenEvolve config values |
| `--dry-run` | flag | No | Validate all inputs and display resolved OpenEvolve config without launching the run |

**Behavior**:
1. **Validate inputs**:
   - Problem version exists
   - LLM is registered and reachable (loaded for local, API key set for remote)
   - Dataset is registered and compatible with the problem version (warn if not)
   - If dataset split is not `train`, display a warning (do not block)
2. **Verify dataset integrity**: recompute hashes, warn on mismatch
3. **Prepare environment**:
   - Set `REVOLVER_DATASET_DIR` to the dataset path
   - Set `REVOLVER_INSTANCE_LOG` to the side-channel SQLite DB path (optional, for per-instance visibility — ADR-006)
   - Set `REVOLVER_EVAL_LOG` to the evaluator log file path (optional — ADR-006)
   - Set OpenEvolve config to use the LLM's base URL
4. **Launch OpenEvolve** with the problem version's files (initial_program, evaluator, config)
5. **Monitor progress**: display iteration count, best score, elapsed time
6. **On completion**:
   - Store all top-ranked programs as `rank-1.py`, `rank-2.py`, etc. in `.revolver/runs/<run-id>/programs/` (OpenEvolve internal output, preserved for later extraction)
   - Create **one** solution DB row for the best program (rank-1) with `(run_id, rank=1)`
   - Record full lineage in `RunManifest` stored in the run directory
   - Store metrics in SQLite
   - Store the OpenEvolve checkpoint in the run directory for potential resume

**Output** (human, during run):
```
Run started: v1.1 + claude-opus + train-small
  Iteration 42/200 | Best score: 0.87 | Elapsed: 1h15m | ETA: 2h05m
```

**Output** (human, on completion):
```
Run completed: run-20260310-143000
  200 iterations in 3h45m
  Solution: sol-20260310-143000 (rank #1, alias: claude-small-v1.1)
  Best combined_score: 0.91
  Programs stored: 5 (use `run info` to inspect, `solution extract` to promote)
  Stored in: .revolver/runs/run-20260310-143000/
```

**Output** (JSON, on completion):
```json
{
  "run_id": "run-20260310-143000",
  "status": "completed",
  "problem_version": "v1.1",
  "llm": "claude-opus",
  "dataset": "train-small",
  "iterations": 200,
  "generation_time_s": 13500,
  "solution": {
    "solution_id": "sol-20260310-143000",
    "alias": "claude-small-v1.1",
    "rank": 1,
    "best_score": 0.91
  },
  "programs_stored": 5
}
```

**Exit codes**: 0 success, 1 invalid inputs, 2 dataset integrity failure, 3 LLM unavailable, 4 OpenEvolve failure

### 2.2 `revolver run status`

Show the status of active or most recent runs. Scans `.revolver/runs/locks/` for active runs and can show multiple concurrent runs.

**Output** (human):
```
Run in progress: run-20260310-143000
  Problem: v1.1 | LLM: claude-opus | Dataset: train-small
  Iteration: 42/200 | Best score: 0.87
  Started: 2026-03-10 14:30 | Elapsed: 1h15m
```

**Exit codes**: 0 always

### 2.3 `revolver run resume`

Resume an interrupted run from its checkpoint. Creates a NEW run from the parent run's checkpoint.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--run <run-id>` | string | Yes | Run whose checkpoint to resume from |

**Behavior**:
1. Locate the OpenEvolve checkpoint in the parent run's directory
2. Verify the checkpoint is valid and resumable
3. Create a new run (`resumed_from: <parent-run-id>`). The parent run's checkpoint is READ but not modified
4. Copy the wrapper evaluator from the parent run (no regeneration)
5. Re-launch OpenEvolve from the checkpoint with the same configuration
6. On completion: the new run gets its own ID, directory, programs, and a single solution DB row (rank-1)

**Exit codes**: 0 success, 1 if run or checkpoint not found, 4 if OpenEvolve fails

### 2.4 `revolver run list`

List all runs in the current project.

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--version <tag>` | string | — | Filter by problem version |
| `--llm <name>` | string | — | Filter by LLM used |
| `--status <status>` | string | — | Filter by status: `running`, `completed`, `interrupted` |
| `--sort <field>` | string | `created_at` | Sort by: `created_at`, `score`, `iterations` |

**Output** (human):
```
ID                    Version  LLM              Dataset      Iter  Score   Status      Date
run-20260310-143000   v1.0     codestral-local  train-small  100   0.74    completed   2026-03-10
run-20260310-173000   v1.0     claude-opus      train-small  100   0.82    completed   2026-03-10
```

**Exit codes**: 0 always

### 2.5 `revolver run info <run-id>`

Show detailed information about a run.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `run-id` | Yes | Run ID |

**Output** (human):
```
Run: run-20260310-143000
  Status: completed
  Problem version: v1.1 (sha256:e5f6g7h8...)
  LLM: claude-opus (claude-opus-4-6)
  Dataset: train-small (sha256:f1e2d3c4...)
  Iterations: 200
  Generation time: 3h45m
  Resumed from: —
  Directory: .revolver/runs/run-20260310-143000/

Solution (auto-created):
  sol-20260310-143000  rank=#1  score=0.91  claude-small-v1.1

Programs (from OpenEvolve output):
  #1  score=0.91  → sol-20260310-143000 (extracted)
  #2  score=0.85
  #3  score=0.79
  Use `revolver solution extract --run run-20260310-143000 --rank <N>` to promote.

Resume chain: (none)
```

**Exit codes**: 0 success, 1 if not found

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-RUN-001 | MUST | Validate that problem version, LLM, and dataset exist before starting | — |
| FR-RUN-002 | MUST | Warn (do not block) if the dataset's split is not `train` | §4.3 |
| FR-RUN-003 | MUST | Warn (do not block) if the dataset is not declared compatible with the problem version | §7.4 |
| FR-RUN-004 | MUST | Verify dataset integrity (hash check) before starting; warn on mismatch | §7.2 |
| FR-RUN-005 | MUST | Set `REVOLVER_DATASET_DIR` environment variable for the evaluator | §4.4 |
| FR-RUN-026 | SHOULD | Set `REVOLVER_INSTANCE_LOG` for optional per-instance SQLite side-channel logging | §4.4, ADR-006 |
| FR-RUN-027 | SHOULD | Set `REVOLVER_EVAL_LOG` for optional evaluator log file | §4.4, ADR-006 |
| FR-RUN-006 | MUST | Configure OpenEvolve to use the LLM's base URL and model ID | §3.2 |
| FR-RUN-007 | MUST | Generate a unique run ID: `run-{YYYYMMDD}-{HHMMSS}`. Generate solution IDs: `sol-{YYYYMMDD}-{HHMMSS}` | §4.6 |
| FR-RUN-008 | MUST | Store all top-ranked programs as `rank-N.py` files in the run directory (from OpenEvolve output). Create **one** solution DB row for the best program (rank-1), referencing (`run_id`, `rank=1`). Additional programs can be promoted to solutions via `revolver solution extract`. | §4.6 |
| FR-RUN-009 | MUST | Record full lineage in `RunManifest` in the run directory: problem version, dataset, LLM, config, timestamp, iterations, generation time | §4.6 |
| FR-RUN-010 | MUST | Store metrics (best scores per iteration) in SQLite | §4.6 |
| FR-RUN-019 | MUST | On completion, evaluate the rank-1 program on all training instances and store raw per-instance results in SQLite (same format as `revolver eval`) | §4.6 |
| FR-RUN-020 | MUST | Training results are accessible via `revolver eval results --solution <id> --dataset <train-dataset>` | — |
| FR-RUN-011 | MUST | Store the OpenEvolve checkpoint in the run directory for resume capability | §4.6, §5.5 |
| FR-RUN-012 | MUST | Support `--alias` for user-friendly solution naming | §4.6 |
| FR-RUN-013 | MUST | `resume` creates a new run from parent checkpoint. The parent run is immutable. | §5.5 |
| FR-RUN-014 | MUST | Local LLM runs execute sequentially (one at a time) | §3.3 |
| FR-RUN-015 | MUST | Remote LLM runs can execute in parallel | §3.3 |
| FR-RUN-016 | SHOULD | Display progress during the run (iteration count, best score, elapsed time) | — |
| FR-RUN-017 | SHOULD | Store the OpenEvolve config used (verbatim copy) in the run directory | NFR-023 |
| FR-RUN-018 | SHOULD | Record generation wall-clock time in solution lineage | §4.6 |
| FR-RUN-021 | MUST | `run list` shows all runs with filtering by version, LLM, status | — |
| FR-RUN-022 | MUST | `run info` displays full run details including the auto-created solution, all stored programs with scores, and resume chain | — |
| FR-RUN-023 | MUST | `--dry-run` validates all inputs and displays resolved config without launching | — |
| FR-RUN-024 | MUST | Resume copies the wrapper evaluator from the parent run (no regeneration) | — |
| FR-RUN-025 | SHOULD | Per-run lock files in `.revolver/runs/locks/` enable concurrent run tracking | §3.3 |

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
| Resume with no checkpoint | Error: "No checkpoint found for run '<run-id>'" | 1 |
| Another local run already in progress | Error: "A local LLM run is already in progress (see `.revolver/runs/locks/`). Wait for it to complete or cancel it." | 3 |
| `--dry-run` with missing or invalid inputs | Error reported as normal (exit 1), no run launched | 1 |
| Not in a Revolver project | Error: "Not a Revolver project" | 1 |

---

## 5. Run Manifest Format

`.revolver/runs/<id>/manifest.yaml`:

```yaml
run_id: "run-20260310-143000"
status: "completed"
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

resumed_from: null
config_file: "config.yaml"        # relative path to config in run dir (verbatim content stored in SQLite as config_snapshot)

solution:                          # auto-created rank-1 solution
  id: "sol-20260310-143000"
  rank: 1
  best_score: 0.91
  alias: "claude-small-v1.1"
  program: "programs/rank-1.py"

programs:                          # all programs stored from OpenEvolve output
  - rank: 1
    score: 0.91
    file: "programs/rank-1.py"
  - rank: 2
    score: 0.85
    file: "programs/rank-2.py"
  - rank: 3
    score: 0.79
    file: "programs/rank-3.py"
```

---

## 6. Dependencies

- Requires an initialized project ([spec-project.md](spec-project.md))
- Requires a problem version ([spec-problem.md](spec-problem.md))
- Requires a registered LLM ([spec-llm.md](spec-llm.md))
- Requires a registered dataset ([spec-dataset.md](spec-dataset.md))
- Solutions produced here are consumed by `revolver eval` ([spec-eval.md](spec-eval.md)) and `revolver benchmark` ([spec-benchmark.md](spec-benchmark.md))
