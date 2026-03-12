# DES-005 — `revolver run` — OpenEvolve Orchestration

**Version**: 0.2 — Run/Solution refactor
**Date**: 2026-03-12
**Status**: Draft
**Traceable to**: [spec-run.md](../../specs/spec-run.md), [Architecture](../architecture.md) §4/§6.1, [ADR-006](../adr/ADR-006-openevolve-instance-injection.md), [DES-001 Data Model](DES-001-sqlite-data-model.md) §3.5–3.6 (runs, solutions), [POC #12](../../pocs/poc-openevolve-integration.md)

---

## 1. Overview

This document details the design of the `revolver run` commands: `run` (launch an evolution run), `status`, `resume`, `list`, and `info`. The **run** is the first-class physical entity that owns all artifacts (checkpoint, config, wrapper evaluator, programs). Solutions are lightweight DB references pointing to (run_id, rank). These commands orchestrate OpenEvolve to generate solutions from a problem version + LLM + dataset combination.

### 1.1 Key Responsibilities

| Responsibility | Description |
|---|---|
| **Input validation** | Problem version, LLM, dataset exist and are usable |
| **Wrapper evaluator generation** | Transform user's `evaluate_instance()` into OpenEvolve-compatible `evaluate()` |
| **Environment setup** | Set `REVOLVER_*` env vars per ADR-006 |
| **OpenEvolve configuration** | Programmatically configure LLM endpoint, iterations, output dir |
| **Execution** | Launch OpenEvolve via controller class (not `run_evolution()`) |
| **Progress monitoring** | Display iteration count, best score, elapsed time |
| **Result collection** | Extract top-N programs, store in run directory + create solution references in DB |
| **Post-run evaluation** | Evaluate all top-N programs on training instances (FR-RUN-019) |
| **Concurrency control** | Per-run lock files in `.revolver/runs/locks/` |

---

## 2. Command → Layer Flow

### 2.1 `revolver run`

Launch an OpenEvolve evolution run.

```
CLI (cli/run.py)
  │ Parse: --version, --llm, --dataset, --iterations, --alias, --top-n,
  │        --config-override, --dry-run
  │ Validate: all required options provided
  ▼
Core (core/run.py) → start_run()
  │ 1. Resolve project root                        ──► Infra: store.find_project_root()
  │ 2. Load problem version                        ──► Infra: db.get_problem_version(tag)
  │    Verify snapshot integrity                    ──► Infra: hashing.verify_snapshot()
  │ 3. Resolve LLM                                 ──► Infra: db.get_llm(name) [global DB]
  │    If local: check loaded                       ──► Infra: ollama.is_loaded(model)
  │    If remote: check API key env var is set
  │ 4. Load dataset registration                   ──► Infra: db.get_dataset(name)
  │    Quick integrity check                        ──► Core: dataset.verify_dataset_integrity()
  │    Warn if split != 'train'                    (FR-RUN-002)
  │    Warn if not compatible with version          (FR-RUN-003)
  │ 5. Check concurrency constraints                ──► Infra: store.get_active_runs()
  │    Scan .revolver/runs/locks/ for active locks
  │    If local LLM and another local run active → error (FR-RUN-014)
  │ 6. If --dry-run: display resolved config and exit (DD-08)
  │ 7. Generate run ID                              ──► generate_run_id()
  │ 8. Create run directory                         ──► Infra: store.create_run_dir(id)
  │    .revolver/runs/<id>/
  │    .revolver/runs/<id>/programs/
  │ 9. Generate wrapper evaluator (into run dir)    ──► Core: run.generate_wrapper()
  │ 10. Prepare environment variables               (ADR-006)
  │     REVOLVER_DATASET_DIR, REVOLVER_INSTANCE_LOG, REVOLVER_EVAL_LOG
  │     (paths point to .revolver/runs/<id>/)
  │ 11. Configure OpenEvolve programmatically       ──► Infra: openevolve.build_config()
  │ 12. Write run lock file                         ──► Infra: store.write_run_lock(id)
  │     .revolver/runs/locks/<id>.lock
  │ 13. Launch OpenEvolve                           ──► Infra: openevolve.run()
  │ 14. Monitor progress                            ──► callback to CLI for display
  │ 15. On completion:
  │     a. Collect top-N programs                   ──► Infra: openevolve.collect_results()
  │        Save as rank-1.py, rank-2.py, ...
  │        in .revolver/runs/<id>/programs/
  │     b. Copy checkpoint, config, evaluator       ──► Infra: store
  │        into run directory
  │     c. For each of the N programs (rank 1..N):
  │        i.   Generate solution ID                ──► generate_solution_id()
  │        ii.  Insert solution row (run_id, rank)  ──► Infra: db.insert_solution()
  │        iii. Set alias on rank-1 only (if provided)
  │     d. Post-run training evaluation             ──► Core: eval.evaluate_solution()
  │        on EACH top-N solution (FR-RUN-019)
  │     e. Update run status to 'completed'         ──► Infra: db.update_run_status()
  │     f. Write run manifest                       ──► Infra: store.write_run_manifest()
  │     g. Remove run lock                          ──► Infra: store.remove_run_lock(id)
  │ 16. Return RunResult (containing N SolutionResults)
  ▼
Infra
  ├── store: run dirs, manifests, lock files
  ├── db: read problem/LLM/dataset, insert run + solutions, update run status
  ├── hashing: snapshot integrity verification
  ├── ollama: check model loaded (local LLMs)
  ├── openevolve: configure, launch, monitor, collect results
  └── dataset (core): integrity verification
```

### 2.2 `revolver run status`

Show the status of current active runs or the most recent run.

```
CLI (cli/run.py)
  │ Parse: (no options)
  ▼
Core (core/run.py) → get_run_status()
  │ 1. Scan .revolver/runs/locks/ for active locks  ──► Infra: store.get_active_runs()
  │ 2. For each lock file: validate PID still alive
  │    Remove stale locks (PID dead)
  │ 3. If active runs found: read progress from each lock file
  │ 4. If no active: query most recent run           ──► Infra: db.get_latest_run()
  │ 5. Return RunStatus (with list of active run_ids)
  ▼
Infra
  ├── store: scan locks/ directory, read lock files
  └── db: query latest run
```

### 2.3 `revolver run resume`

Resume a run from its checkpoint. Creates a **new run** with `resumed_from` pointing to the parent run. The parent run and its solutions/eval results remain immutable.

```
CLI (cli/run.py)
  │ Parse: --run <run_id>
  ▼
Core (core/run.py) → resume_run()
  │ 1. Resolve run                                  ──► Infra: db.get_run(run_id)
  │ 2. Load run metadata                            (problem_version, llm, dataset, config)
  │ 3. Locate checkpoint dir                        ──► store: .revolver/runs/<run_id>/oe-checkpoint/
  │ 4. Validate checkpoint exists and is non-empty
  │ 5. Validate run status is 'completed' or 'interrupted'
  │    (cannot resume a 'running' run)
  │ 6. Load original problem version                ──► Infra: db.get_problem_version(tag)
  │ 7. Load original LLM config                     ──► Infra: db.get_llm(name)
  │ 8. Load original dataset                        ──► Infra: db.get_dataset(name)
  │ 9. Create NEW run with resumed_from: <run_id>   ──► generate_run_id()
  │ 10. Create new run directory                    ──► Infra: store.create_run_dir(new_id)
  │ 11. Copy wrapper from parent run (DD-09)        ──► Infra: store
  │     (wrapper reused, not regenerated)
  │ 12. Copy parent checkpoint into new run dir     ──► Infra: store
  │ 13. Reconstruct environment and OpenEvolve config
  │     (same as original run, from parent metadata)
  │ 14. Write run lock file                         ──► Infra: store.write_run_lock(new_id)
  │ 15. Launch OpenEvolve with checkpoint           ──► Infra: openevolve.run(checkpoint=...)
  │ 16. Monitor progress                            ──► callback to CLI for display
  │ 17. On completion (same as fresh run):
  │     a. Collect top-N programs → save as rank-1.py, rank-2.py, ...
  │        in .revolver/runs/<new_id>/programs/
  │     b. Copy checkpoint, config into new run directory
  │     c. For each of the N programs:
  │        i.   Generate solution ID
  │        ii.  Insert solution row (run_id, rank) in DB
  │     d. Post-run training evaluation on EACH top-N solution
  │     e. Update run status to 'completed'
  │     f. Write run manifest
  │     g. Remove run lock
  │ 18. Return RunResult
  ▼
Infra
  ├── db: read run metadata, insert new run + solutions, update run status
  ├── openevolve: launch with checkpoint
  └── store: read parent checkpoint/wrapper, create new run dir, write manifest
```

### 2.4 `revolver run list`

List runs with optional filters.

```
CLI (cli/run.py)
  │ Parse: --version, --llm, --status, --sort
  ▼
Core (core/run.py) → list_runs()
  │ 1. Query runs with optional filters             ──► Infra: db.list_runs()
  │ 2. Return list of RunSummary
  ▼
Infra
  └── db: query runs table with filters
```

### 2.5 `revolver run info`

Show detailed information about a specific run, including its solutions and resume chain.

```
CLI (cli/run.py)
  │ Parse: <run_id>
  ▼
Core (core/run.py) → get_run_info()
  │ 1. Query run metadata                           ──► Infra: db.get_run(run_id)
  │ 2. Query associated solutions                   ──► Infra: db.get_solutions_for_run(run_id)
  │ 3. Query resume chain (CTE recursive)           ──► Infra: db.get_resume_chain(run_id)
  │ 4. Return RunInfo
  ▼
Infra
  └── db: query runs + solutions tables
```

---

## 3. Wrapper Evaluator Generation

A central mechanism of `revolver run` is generating a wrapper evaluator that bridges the user's `evaluate_instance()` function with OpenEvolve's `evaluate(program_path)` interface (ADR-006).

### 3.1 User-Provided Code

The user writes **only** the single-instance evaluation logic in `evaluator.py`:

```python
def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    """Evaluate one program against one instance. Return metrics dict."""
    # User's domain logic here
    ...
    return {"combined_score": 0.85, "makespan": 142.5}
```

### 3.2 Generated Wrapper

Revolver generates a `_revolver_evaluator.py` file in the run's directory that wraps the user's function:

```python
"""Auto-generated by Revolver. Do not edit."""
import os
import sys
import json
import sqlite3
import statistics
from pathlib import Path

# Import user's evaluator from the problem version snapshot
sys.path.insert(0, "{snapshot_dir}")
from evaluator import evaluate_instance


def evaluate(program_path: str) -> dict[str, float]:
    instance_path = os.environ.get("REVOLVER_INSTANCE_PATH")

    if instance_path:
        # Single-instance mode (revolver eval / revolver benchmark)
        return evaluate_instance(program_path, instance_path)

    # Aggregated mode (OpenEvolve training)
    dataset_dir = os.environ["REVOLVER_DATASET_DIR"]
    instances = sorted(
        p for p in Path(dataset_dir).iterdir()
        if not p.name.startswith(".")
    )

    all_metrics = []
    for inst in instances:
        try:
            metrics = evaluate_instance(program_path, str(inst))
            all_metrics.append(metrics)
            _log_instance(inst.name, metrics)
        except Exception:
            pass  # Skip failed instances during training

    if not all_metrics:
        return {"combined_score": 0.0}

    combined = statistics.mean(m["combined_score"] for m in all_metrics)
    result = {"combined_score": combined}

    # Include other metrics as aggregated means
    all_keys = set()
    for m in all_metrics:
        all_keys.update(m.keys())
    for key in sorted(all_keys):
        if key != "combined_score":
            vals = [m[key] for m in all_metrics if key in m]
            if vals:
                result[key] = statistics.mean(vals)

    return result


def _log_instance(instance_id: str, metrics: dict[str, float]) -> None:
    """Optional: log per-instance results to SQLite side-channel."""
    log_path = os.environ.get("REVOLVER_INSTANCE_LOG")
    if not log_path:
        return
    try:
        conn = sqlite3.connect(log_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS instance_log "
            "(instance_id TEXT, metric TEXT, value REAL, pid INTEGER)"
        )
        for metric, value in metrics.items():
            conn.execute(
                "INSERT INTO instance_log VALUES (?, ?, ?, ?)",
                (instance_id, metric, value, os.getpid()),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Side-channel is best-effort
```

### 3.3 Generation Logic

```python
def generate_wrapper(
    snapshot_dir: Path,
    output_dir: Path,
) -> Path:
    """
    Generate the wrapper evaluator file.

    Args:
        snapshot_dir: Path to .revolver/problem/<tag>/ (immutable snapshot)
        output_dir: Path to run directory (.revolver/runs/<id>/)

    Returns:
        Path to the generated _revolver_evaluator.py

    Detection order (D-005-a):
        1. If evaluate() exists → use as-is (priority, legacy mode)
        2. Else if evaluate_instance() exists → generate wrapper
        3. Else → raise EvaluatorError
    """
```

### 3.4 Legacy Mode

If the user's evaluator already defines `evaluate(program_path)`, Revolver uses it directly without generating a wrapper. This supports advanced users who want full control over the aggregation strategy and maintains backward compatibility with standard OpenEvolve evaluators. The user may also define both `evaluate()` and `evaluate_instance()` in the same file; Revolver only checks for `evaluate()` first.

Detection order (D-005-a):
1. `evaluate(program_path)` → use as-is (legacy mode, priority)
2. `evaluate_instance(program_path, instance_path)` → generate wrapper
3. Neither → error

**Trade-offs of legacy mode**:

| Capability | `evaluate_instance()` (wrapper) | `evaluate()` (legacy) |
|---|---|---|
| User writes | Single-instance logic only | Full dual-mode evaluator (both aggregated and single-instance) |
| Aggregation strategy | Fixed: `mean(combined_score)` | User-controlled (min, max, weighted, etc.) |
| Training per-instance side-channel | Supported (wrapper logs each instance) | Not available (evaluator is a black box to Revolver) |
| Post-run eval (FR-RUN-019) | Full per-instance results | Full per-instance results (same as wrapper) |
| `revolver eval` / `benchmark` | Full per-instance results | Full per-instance results (same as wrapper) |
| Final traceability | Complete | Complete |

The key insight: **legacy mode does not affect final traceability**. The post-run eval (§7) always evaluates the best program per-instance regardless of the evaluator mode. The only difference is per-instance visibility *during* the evolution run (side-channel), which is an observability convenience (FR-RUN-005b, SHOULD), not a traceability requirement.

The recommended approach is `evaluate_instance()` for simplicity. Legacy mode is for users who need custom aggregation (e.g., worst-case optimization using `min` instead of `mean`).

### 3.5 Scope of the Generated Wrapper

The generated `_revolver_evaluator.py` is stored in the run directory (`.revolver/runs/<id>/`) and is used **exclusively by OpenEvolve** during the evolution run (aggregated mode). It is **not** used by `revolver eval` or `revolver benchmark`.

When `revolver eval` evaluates a solution ([DES-006](DES-006-eval-loop.md) §3.3), it loads the evaluator directly from the problem version snapshot and calls either `evaluate_instance()` (preferred) or `evaluate()` with `REVOLVER_INSTANCE_PATH` set. The wrapper is not involved because `revolver eval` always operates in single-instance mode.

```
OpenEvolve training:  _revolver_evaluator.py → evaluate() (aggregated mode)
                      └── calls evaluate_instance() per instance
                      └── returns mean(combined_score)

revolver eval:        .revolver/problem/<tag>/evaluator.py → evaluate_instance() (direct)
                      └── returns per-instance metrics
```

---

## 4. OpenEvolve Integration

### 4.1 Controller Class Usage

Per ADR-006 and POC #12 S7, Revolver uses the `OpenEvolve` controller class directly for resume support:

```python
# In revolver/infra/openevolve.py
import asyncio
from openevolve.controller import OpenEvolve as OEController

class OpenEvolveRunner:
    """Wrapper around OpenEvolve controller for Revolver integration."""

    def __init__(
        self,
        initial_program: Path,
        evaluator: Path,
        config: dict,
        output_dir: Path,
    ):
        self._controller = OEController(
            str(initial_program),
            str(evaluator),
            config,
            str(output_dir),
        )

    def run(
        self,
        iterations: int,
        checkpoint: Path | None = None,
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> RunOutput:
        """
        Launch OpenEvolve evolution loop.

        Args:
            iterations: Number of evolution iterations
            checkpoint: Path to checkpoint directory for resume (optional)
            on_progress: Callback invoked after each iteration

        Returns:
            RunOutput with best programs and metrics
        """
        best = asyncio.run(
            self._controller.run(
                iterations=iterations,
                checkpoint_path=str(checkpoint) if checkpoint else None,
            )
        )
        return self._collect_output(best)
```

### 4.2 OpenEvolve Configuration

OpenEvolve is configured programmatically by merging the problem version's `config.yaml` with Revolver's overrides:

```python
def build_config(
    problem_config: Path,
    llm: LLMEntry,
    iterations: int | None,
    config_overrides: list[str] | None,
    output_dir: Path,
) -> dict:
    """
    Build the OpenEvolve config dict.

    Merge order (last wins):
        1. Problem version's config.yaml (base)
        2. LLM endpoint configuration (base_url, model, api_key)
        3. --iterations override
        4. --config-override key=value pairs
        5. Output directory (always Revolver-controlled)
    """
```

### 4.3 LLM Endpoint Injection

OpenEvolve expects LLM configuration in its config. Revolver injects it based on the registered LLM:

| LLM field | OpenEvolve config key | Source |
|---|---|---|
| `base_url` | `llm.base_url` | LLM registry (`llms.base_url`) |
| `model` | `llm.model` | LLM registry (`llms.model`) |
| `api_key` | `llm.api_key` | Read from env var named in `llms.api_key_env` |

For local LLMs (Ollama), `base_url` is typically `http://localhost:11434/v1` and no API key is needed.

---

## 5. Environment Variables

Set before launching OpenEvolve, per ADR-006:

| Variable | Value | Required |
|---|---|---|
| `REVOLVER_DATASET_DIR` | `resolve_dataset_path(dataset_name)` | Yes (FR-RUN-005) |
| `REVOLVER_INSTANCE_LOG` | `.revolver/runs/<id>/instance_log.db` | Optional (FR-RUN-005b) |
| `REVOLVER_EVAL_LOG` | `.revolver/runs/<id>/eval.log` | Optional (FR-RUN-005c) |

These are set in the current process environment before calling `openevolve.run()`. OpenEvolve's worker processes inherit them via standard `os.environ` propagation (validated in POC #12 S2).

**Note (D-005-d)**: `REVOLVER_INSTANCE_LOG` and `REVOLVER_EVAL_LOG` are used only by the generated wrapper evaluator. Legacy evaluators (`evaluate()` mode) do not benefit from these unless the user implements them manually.

**Cleanup**: After the run completes (success or failure), the env vars are unset to avoid polluting subsequent operations in the same process.

```python
@contextmanager
def revolver_env(env_vars: dict[str, str]):
    """Context manager to set and clean up REVOLVER_* env vars."""
    old = {}
    for key, value in env_vars.items():
        old[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key in env_vars:
            if old[key] is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old[key]
```

---

## 6. Concurrency Control

### 6.1 Per-Run Lock Files (FR-RUN-014)

Each active run has its own lock file in `.revolver/runs/locks/`. This replaces the single `.revolver/run.lock` file (DD-11).

**Mechanism**: A lock file `.revolver/runs/locks/<run_id>.lock` is created when a run starts:

```yaml
# .revolver/runs/locks/run-20260310-143000.lock
run_id: "run-20260310-143000"
llm: "codestral-local"
llm_source: "local"
started_at: "2026-03-10T14:30:00Z"
pid: 12345
```

Before starting a local-LLM run, Revolver checks:
1. Scan `.revolver/runs/locks/` for `*.lock` files
2. For each lock file: is the PID still alive? (`os.kill(pid, 0)`)
3. If PID dead → stale lock, remove it
4. If any live lock has `llm_source == "local"` → error: "A local LLM run is already in progress"
5. If no conflict → proceed

### 6.2 Remote LLM — Parallel Execution (FR-RUN-015)

Remote LLM runs have no local resource conflict. A lock file is still created (for status tracking via `run status`) but does not block other runs. The concurrency check only blocks when `llm_source == "local"` and another local-LLM lock is alive.

### 6.3 Lock File Lifecycle

```
start_run()  → write .revolver/runs/locks/<run_id>.lock
              → launch OpenEvolve
              → on completion/failure: remove .revolver/runs/locks/<run_id>.lock
              → on crash: stale lock detected by PID check on next run/status
```

---

## 7. Post-Run Training Evaluation (FR-RUN-019/020)

After OpenEvolve completes, Revolver evaluates **all top-N programs** on all training instances to produce per-instance results accessible via `revolver eval results` (DD-12).

```python
def _post_run_evaluation(
    run_id: str,
    problem_version: str,
    dataset_name: str,
) -> None:
    """
    Evaluate all top-N programs on training instances.
    For each solution created by the run, calls core.eval.evaluate_solution().
    The program path for each solution is resolved via (run_id, rank).
    Results are stored in eval_metadata/eval_instances with the training
    dataset, making them accessible via:
      revolver eval results --solution <id> --dataset <train-dataset>
    """
```

This step is **synchronous** — it runs after OpenEvolve completes but before the run is marked as finished. Each of the N solutions is evaluated sequentially. If evaluation fails for a specific solution, a warning is emitted but evaluation continues for remaining solutions. The run is still considered successful regardless of post-run evaluation failures (the run and solutions are already stored).

---

## 8. Pydantic Data Models

```python
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from pathlib import Path

class RunConfig(BaseModel):
    """Configuration for an OpenEvolve run."""
    problem_version: str
    llm_name: str
    dataset_name: str
    iterations: int | None = None
    alias: str | None = None
    top_n: int = 1
    config_overrides: list[str] = []
    dry_run: bool = False

class RunManifest(BaseModel):
    """Manifest stored in .revolver/runs/<id>/manifest.yaml."""
    model_config = ConfigDict(frozen=True)

    run_id: str
    created_at: datetime
    generation_time_s: float | None = None
    iterations: int
    top_n: int = 1
    status: str = "running"  # running | completed | interrupted

    # Lineage
    problem_version: str
    problem_hash: str
    dataset: str
    dataset_hash: str
    llm: str
    llm_model: str
    resumed_from: str | None = None

    # Files
    programs: list[str] = []  # ["rank-1.py", "rank-2.py", ...]
    checkpoint: str = "oe-checkpoint/"
    config_snapshot: str = "config.yaml"

class RunResult(BaseModel):
    """Returned to CLI after a run completes."""
    run_id: str                        # This run's own ID
    solutions: list["SolutionResult"]  # One per top-N program (rank 1 first)
    problem_version: str
    llm: str
    dataset: str
    iterations: int
    generation_time_s: float
    resumed_from: str | None = None

class SolutionResult(BaseModel):
    """One solution from a top-N run."""
    solution_id: str
    run_id: str                        # Run that produced this solution
    alias: str | None = None
    rank: int                          # 1 = best
    best_score: float | None = None

class RunStatus(BaseModel):
    """Status of active runs or the most recent run."""
    active: bool
    run_ids: list[str] = []            # Active run IDs (may be multiple)
    run_id: str | None = None          # Most recent run (if no active)
    problem_version: str | None = None
    llm: str | None = None
    dataset: str | None = None
    iterations_completed: int | None = None
    iterations_total: int | None = None
    best_score: float | None = None
    started_at: datetime | None = None
    elapsed_s: float | None = None

class RunSummary(BaseModel):
    """Summary for run list output."""
    run_id: str
    problem_version: str
    llm: str
    dataset: str
    top_n: int
    iterations: int
    generation_time_s: float | None = None
    status: str
    resumed_from: str | None = None
    created_at: datetime
    best_score: float | None = None

class RunInfo(BaseModel):
    """Detailed run information for run info output."""
    run_id: str
    problem_version: str
    problem_hash: str
    llm: str
    llm_model: str
    dataset: str
    dataset_hash: str
    top_n: int
    iterations: int
    generation_time_s: float | None = None
    status: str
    resumed_from: str | None = None
    created_at: datetime
    solutions: list["SolutionResult"] = []
    resume_chain: list[str] = []       # Ordered list of ancestor run IDs

class ProgressInfo(BaseModel):
    """Progress callback data from OpenEvolve."""
    iteration: int
    total_iterations: int
    best_score: float
    elapsed_s: float
```

---

## 9. Storage Layout

Each run has its own directory under `.revolver/runs/`. Solutions do not have their own directories — they are DB references to programs stored in the run directory.

```
.revolver/
├── runs/
│   ├── run-20260310-143000/
│   │   ├── manifest.yaml              # Run metadata + lineage
│   │   ├── config.yaml                # Verbatim OpenEvolve config used (FR-RUN-017)
│   │   ├── _revolver_evaluator.py     # Generated wrapper (or copied evaluator)
│   │   ├── oe-checkpoint/             # OpenEvolve checkpoint for resume
│   │   │   └── ...                    # OpenEvolve internal files
│   │   ├── instance_log.db            # SQLite side-channel (optional, FR-RUN-005b)
│   │   ├── eval.log                   # Evaluator log (optional, FR-RUN-005c)
│   │   └── programs/
│   │       ├── rank-1.py
│   │       ├── rank-2.py
│   │       └── rank-3.py
│   ├── run-20260310-160000/
│   │   └── ...
│   └── locks/
│       └── run-20260310-143000.lock
├── problem/
├── datasets/
└── revolver.db
```

### 9.1 SQLite

Uses tables from [DES-001](DES-001-sqlite-data-model.md):
- `runs` (§3.5): run metadata, lineage, resume chain
- `solutions` (§3.6): lightweight references (run_id, rank, alias, best_score)
- `eval_metadata` + `eval_instances` (§3.7–3.8): post-run training evaluation

---

## 10. Core Layer: Function Signatures

```python
# --- Run ---
def start_run(config: RunConfig) -> RunResult:
    """
    Launch an OpenEvolve evolution run.
    Validates inputs, generates wrapper, launches OE, stores results.
    Creates a run directory, then N solution rows in DB (one per top-N program).
    Post-run evaluation runs on all top-N solutions.
    If config.dry_run is True, validates everything and returns without launching.
    """

def resume_run(run_id: str) -> RunResult:
    """
    Resume a run from its checkpoint.
    Creates a NEW run with resumed_from pointing to the parent run.
    Copies wrapper and checkpoint from parent, launches OE with checkpoint.
    On completion: creates new solutions, runs post-run eval.
    """

def get_run_status() -> RunStatus:
    """
    Get status of active runs or the most recent run.
    Scans .revolver/runs/locks/ for active locks, falls back to latest run in DB.
    """

def list_runs(
    version: str | None = None,
    llm: str | None = None,
    status: str | None = None,
    sort: str = "created_at",
) -> list[RunSummary]:
    """List runs with optional filters."""

def get_run_info(run_id: str) -> RunInfo:
    """
    Get detailed info for a run, including its solutions and resume chain.
    Uses a recursive CTE to resolve the full resume ancestry.
    """

# --- Internal ---
def generate_wrapper(
    snapshot_dir: Path,
    output_dir: Path,
) -> Path:
    """Generate wrapper evaluator or copy legacy evaluator."""

def _post_run_evaluation(
    run_id: str,
    problem_version: str,
    dataset_name: str,
) -> None:
    """Evaluate all top-N programs on training instances after run. Iterates over solutions for the run."""

def generate_run_id() -> str:
    """Generate run-YYYYMMDD-HHMMSS with counter for collisions."""

def generate_solution_id() -> str:
    """Generate sol-YYYYMMDD-HHMMSS with counter for collisions."""
```

---

## 11. CLI Layer: Typer Commands

```python
import typer

app = typer.Typer(name="run", help="Generate solutions via OpenEvolve")

@app.callback(invoke_without_command=True)
def run_default(
    ctx: typer.Context,
    version: str = typer.Option(..., "--version", help="Problem version tag"),
    llm: str = typer.Option(..., "--llm", help="Registered LLM name"),
    dataset: str = typer.Option(..., "--dataset", help="Training dataset name"),
    iterations: int | None = typer.Option(None, "--iterations", help="Override iteration count"),
    alias: str | None = typer.Option(None, "--alias", help="Solution alias (rank-1 only)"),
    top_n: int = typer.Option(1, "--top-n", help="Number of top solutions to keep"),
    config_override: list[str] | None = typer.Option(None, "--config-override", help="key=value overrides"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate inputs and show config without launching"),
): ...

@app.command()
def status(): ...

@app.command()
def resume(
    run: str = typer.Option(..., "--run", help="Run ID to resume from"),
): ...

@app.command()
def list(
    version: str | None = typer.Option(None, "--version", help="Filter by problem version"),
    llm: str | None = typer.Option(None, "--llm", help="Filter by LLM name"),
    status: str | None = typer.Option(None, "--status", help="Filter by status (running, completed, interrupted)"),
    sort: str = typer.Option("created_at", "--sort", help="Sort by field (created_at, score, iterations)"),
): ...

@app.command()
def info(
    run_id: str = typer.Argument(..., help="Run ID to inspect"),
): ...
```

---

## 12. Sequence Diagrams

### 12.1 `revolver run --version v1.1 --llm claude --dataset train-small`

```
User      CLI         Core            OpenEvolve    Store    DB       Hashing
 │         │           │                │            │        │         │
 │─ run ──►│           │                │            │        │         │
 │         │─ start() ►│                │            │        │         │
 │         │           │── get version ────────────────────►│         │
 │         │           │── verify snapshot ────────────────────────────►│
 │         │           │── get LLM ────────────────────────►│         │
 │         │           │── get dataset ────────────────────►│         │
 │         │           │── check integrity ──────────────────────────►│
 │         │           │── scan locks/ ─────►│            │        │
 │         │           │                     │            │        │
 │         │           │── gen run ID         │            │        │
 │         │           │── insert run ───────────────────►│         │
 │         │           │── create run dir ───►│            │        │
 │         │           │── generate wrapper   │            │        │
 │         │           │── set env vars       │            │        │
 │         │           │── build OE config    │            │        │
 │         │           │── write run lock ───►│            │        │
 │         │           │                     │            │        │
 │         │           │── run() ────────────►│            │        │
 │         │           │                     │ (evolution) │        │
 │◄progress│◄─progress─│◄── on_progress ────│            │        │
 │         │           │                     │            │        │
 │         │           │◄── results ─────────│            │        │
 │         │           │── save programs ────►│ (rank-N.py)│        │
 │         │           │── copy checkpoint ──►│            │        │
 │         │           │── for each top-N:    │            │        │
 │         │           │   ── gen solution ID  │            │        │
 │         │           │   ── insert solution ───────────►│         │
 │         │           │── post-run eval (all) │            │        │
 │         │           │── update run status ─────────────►│         │
 │         │           │── write manifest ───►│            │        │
 │         │           │── remove run lock ──►│            │        │
 │◄─result─│◄─RunResult│                     │            │        │
```

### 12.2 `revolver run resume --run run-20260310-143000`

```
User      CLI         Core            OpenEvolve    Store    DB
 │         │           │                │            │        │
 │─resume─►│           │                │            │        │
 │         │─resume() ►│                │            │        │
 │         │           │── get run ──────────────────────────►│
 │         │           │── locate checkpoint ►│            │
 │         │           │── validate checkpoint│            │
 │         │           │── validate status    │            │
 │         │           │── get version ──────────────────────►│
 │         │           │── get LLM ──────────────────────────►│
 │         │           │── get dataset ──────────────────────►│
 │         │           │── gen NEW run ID      │            │
 │         │           │── insert run (resumed)──────────────►│
 │         │           │── create new run dir ►│            │
 │         │           │── copy wrapper ──────►│ (from parent)
 │         │           │── copy checkpoint ───►│ (from parent)
 │         │           │── reconstruct config  │            │
 │         │           │── write run lock ────►│            │
 │         │           │                      │            │
 │         │           │── run(checkpoint) ───►│            │
 │         │           │                      │ (resume)   │
 │◄progress│◄─progress─│◄── on_progress ─────│            │
 │         │           │◄── results ──────────│            │
 │         │           │── save programs ─────►│ (rank-N.py)│
 │         │           │── for each top-N:     │            │
 │         │           │   ── insert solution ────────────►│
 │         │           │── post-run eval (all)  │            │
 │         │           │── update run status ──────────────►│
 │         │           │── write manifest ────►│            │
 │         │           │── remove run lock ───►│            │
 │◄─result─│◄─RunResult│                      │            │
```

---

## 13. Design Decisions

### DD-01: Wrapper evaluator generation vs requiring dual-mode code

Revolver generates the wrapper evaluator rather than requiring the user to write dual-mode code. This:
- **Reduces boilerplate**: the user writes only `evaluate_instance()`, the simplest possible interface
- **Eliminates mistakes**: the dual-mode pattern, env var reading, side-channel logging are all handled correctly by the generated code
- **Supports legacy mode**: users who already have an `evaluate()` function can use it directly

Trade-off: code generation adds complexity to `revolver run`. Mitigated by the fact that the generated code is deterministic and stored alongside the solution for inspection.

### DD-02: Lock file with PID check for concurrency control

A lock file with PID is simpler than alternatives (SQLite advisory lock, OS-level flock):
- **Self-healing**: stale locks are detected via PID check, no manual cleanup needed
- **Portable**: works on Linux, macOS, WSL2
- **Inspectable**: the lock file is human-readable YAML, easy to debug

Trade-off: PID reuse could theoretically cause a false positive (a different process reuses the PID). In practice, PIDs are not reused quickly enough for this to matter with runs that take minutes to hours.

### DD-03: Post-run evaluation uses the same eval machinery

FR-RUN-019 requires evaluating the best program on all training instances after the run. Rather than implementing a separate evaluation loop, this reuses `core.eval.evaluate_solution()` with the training dataset. This ensures:
- **Consistency**: training and evaluation results use the same format and storage
- **Queryability**: results are accessible via `revolver eval results --solution <id> --dataset <train>`
- **No code duplication**: the evaluation loop is implemented once

### DD-04: OpenEvolve controller class, not `run_evolution()`

Per POC #12 S7, the high-level `run_evolution()` function does not support checkpoint resume. The `OpenEvolve` controller class provides:
- `run(iterations, checkpoint_path)` for resume
- Direct access to results without parsing stdout
- Programmatic configuration (no need to write a temporary YAML file)

Trade-off: tighter coupling to OpenEvolve internals. Mitigated by isolating all OpenEvolve interaction in `infra/openevolve.py`.

### DD-05: Generated wrapper stored in run directory

The `_revolver_evaluator.py` is stored in the run directory (not a temporary file) because:
- **Traceability**: the exact evaluator code used for the run is preserved
- **Debugging**: the user can inspect the generated wrapper if results are unexpected
- **Resume**: the wrapper is copied to the new run directory on resume (DD-09)
- The `_` prefix signals it's an internal file, not user-authored

### DD-06: Environment variable cleanup via context manager

Env vars are set before the run and cleaned up after. The context manager pattern ensures cleanup even on exceptions, preventing env var pollution between sequential operations in the same process (e.g., running `revolver run` followed by `revolver eval` in a script).

### DD-07: Top-N creates N solutions pointing to the same run

When `--top-n > 1`, the run produces N ranked programs stored as `rank-1.py`, `rank-2.py`, ..., `rank-N.py` in the run's `programs/` directory. For each program, a solution row is inserted in the DB referencing `(run_id, rank)`. Solutions have no directory of their own — they are lightweight DB references.

**Key properties**:
- All N solutions share the same `run_id`
- Each solution has a distinct `solution_id` and `rank`
- The program path is resolved as `.revolver/runs/<run_id>/programs/rank-<N>.py`
- Checkpoint, config, wrapper, and logs belong to the **run**, not to individual solutions

**Alternatives considered**:

| Approach | Pros | Cons |
|---|---|---|
| **A: N files in one solution** | Simple storage, one ID | Only one program usable by eval; others are dead artifacts |
| **B: N separate solution directories** | Each independently evaluable | N directories with duplicated lineage; complex resume |
| **C: N solution rows, one run directory** (chosen) | Clean separation: run owns files, solutions are references | Requires join to resolve program path |

**Why option C**: the run is the physical entity (checkpoint, config, wrapper), and solutions are the logical entity (evaluable, aliasable, benchmarkable). This avoids directory proliferation while keeping each solution as a first-class entity in the DB.

**Managing proliferation**: The user manages many solutions via:
- `revolver solution list --rank 1` — show only the best from each run
- `revolver solution list --version v1.1 --llm claude` — filter by lineage (via run join)
- `revolver solution list --sort score` — sort by score to find the best
- `revolver solution alias <id> "my-champion"` — name what matters (FR-SOL-006)

**Post-run behavior with top-N**:
- Post-run training evaluation (FR-RUN-019) runs on **all top-N solutions** (DD-12).
- `revolver run resume` operates on the **run** (which contains the full checkpoint with the entire population). It does not resume a specific solution.
- The `--alias` option (if provided) is set only on the rank-1 solution. Rank > 1 solutions have no alias by default.

### DD-08: `--dry-run` validates without launching (D-005-g)

`revolver run --dry-run` performs all validation steps (problem version, LLM availability, dataset integrity, concurrency check) and displays the resolved OpenEvolve configuration, then exits without creating a run directory or launching the evolution. This helps catch configuration errors before committing to a potentially long run.

The `--dry-run` flag is checked after step 5 (concurrency check) and before step 7 (run ID generation) in the §2.1 flow. No run ID is generated, no directory is created, no lock file is written.

### DD-09: Wrapper reused on resume (D-005-h)

When resuming a run, the generated wrapper evaluator from the parent run is **copied** into the new run directory rather than being regenerated. This ensures:
- **Determinism**: the exact same evaluator code is used across the resume chain
- **Safety**: the problem version snapshot is immutable, so regenerating the wrapper would produce the same result — but copying avoids any risk of subtle changes in the generation logic between Revolver versions
- **Simplicity**: no need to re-detect evaluate() vs evaluate_instance() on resume

### DD-10: Evaluator detection priority: evaluate() > evaluate_instance() (D-005-a)

When both `evaluate()` and `evaluate_instance()` are defined in the user's evaluator, Revolver uses `evaluate()` (legacy mode). The rationale:
- `evaluate()` is the OpenEvolve-native interface — if the user wrote it, they want full control
- The user may call `evaluate_instance()` internally from their `evaluate()`, using a custom aggregation strategy
- This avoids silently ignoring the user's carefully crafted `evaluate()` in favor of a generated wrapper

Detection order:
1. `evaluate(program_path)` found → use as-is (legacy mode)
2. `evaluate_instance(program_path, instance_path)` found → generate wrapper
3. Neither → raise `EvaluatorError`

### DD-11: Per-run lock files instead of single lock (D-005-b)

Each active run has its own lock file in `.revolver/runs/locks/<run_id>.lock`, replacing the previous single `.revolver/run.lock`. This supports:
- **Multiple concurrent remote-LLM runs**: each tracked by its own lock file
- **Accurate status reporting**: `run status` can list all active runs
- **Clean lifecycle**: lock files are scoped to their run, reducing stale-lock confusion

The concurrency constraint (only one local-LLM run at a time, FR-RUN-014) is enforced by scanning all lock files and checking `llm_source` — not by the existence of a single lock.

### DD-12: Post-run eval on all top-N solutions (D-005-e)

Post-run training evaluation (FR-RUN-019) runs on **all top-N solutions**, not just rank-1. The cost is N sequential evaluations, which is acceptable because:
- The user typically sets N to a small value (1–5)
- Evaluation per solution is fast compared to the evolution run itself
- Having per-instance results for all solutions enables immediate comparison without manual `revolver eval` calls
- This aligns with the principle that every solution is a first-class entity (DD-07)

---

## 14. Architecture Impact

### New modules

| Module | Layer | Purpose |
|---|---|---|
| `infra/openevolve.py` | Infrastructure | OpenEvolve controller wrapper (launch, monitor, collect results) |

### Existing modules impacted

| Module | Change |
|---|---|
| `core/run.py` | Implement `start_run()`, `resume_run()`, `get_run_status()`, `list_runs()`, `get_run_info()`, `generate_wrapper()` |
| `cli/run.py` | Implement 5 Typer commands (`run`, `status`, `resume`, `list`, `info`) |
| `models/run.py` | Define `RunConfig`, `RunManifest`, `RunResult`, `SolutionResult`, `RunStatus`, `RunSummary`, `RunInfo`, `ProgressInfo` (new file) |
| `infra/store.py` | Add `create_run_dir()`, `write_run_manifest()`, per-run lock management (`write_run_lock()`, `remove_run_lock()`, `get_active_runs()`) |
| `infra/db.py` | Add `insert_run()`, `insert_solution()` (simplified: run_id + rank), `get_run()`, `list_runs()`, `get_solutions_for_run()`, `get_resume_chain()`, `get_latest_run()`, `update_run_status()` |
| `core/eval.py` | Called by `_post_run_evaluation()` — must be implemented before or alongside DES-005 |

### Cross-DES dependencies

| Dependency | Direction | Details |
|---|---|---|
| DES-001 | DES-005 → DES-001 | Uses `runs` (§3.5) and `solutions` (§3.6) tables |
| DES-003 | DES-005 → DES-003 | Loads problem version snapshot, verifies integrity |
| DES-004 | DES-005 → DES-004 | Loads dataset, verifies integrity, resolves path |
| DES-006 | DES-005 → DES-006 | Post-run evaluation reuses `core.eval.evaluate_solution()` |

---

## 15. Open Questions

- ~~**RQ-01**: Should `revolver run` support `--dry-run`?~~ **Resolved** (D-005-g): `--dry-run` accepted. Validates all inputs and displays the resolved OpenEvolve config without launching. See DD-08.
- ~~**RQ-02**: Should the generated wrapper be regenerated on `resume`?~~ **Resolved** (D-005-h): Wrapper reused on resume (copied from parent run). See DD-09.
- **RQ-03**: How should OpenEvolve's progress be monitored? Options: (a) parse stdout, (b) poll checkpoint directory, (c) callback from controller. This depends on the controller class API, which needs further investigation.
