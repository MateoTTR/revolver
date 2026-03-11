# DES-005 — `revolver run` — OpenEvolve Orchestration

**Version**: 0.1 — Initial draft
**Date**: 2026-03-11
**Status**: Draft
**Traceable to**: [spec-run.md](../../specs/spec-run.md), [Architecture](../architecture.md) §4/§6.1, [ADR-006](../adr/ADR-006-openevolve-instance-injection.md), [DES-001 Data Model](DES-001-sqlite-data-model.md) §3.5–3.6, [POC #12](../../pocs/poc-openevolve-integration.md)

---

## 1. Overview

This document details the design of the `revolver run` commands: the default command (launch an evolution run), `status`, and `resume`. These commands orchestrate OpenEvolve to generate solutions from a problem version + LLM + dataset combination.

### 1.1 Key Responsibilities

| Responsibility | Description |
|---|---|
| **Input validation** | Problem version, LLM, dataset exist and are usable |
| **Wrapper evaluator generation** | Transform user's `evaluate_instance()` into OpenEvolve-compatible `evaluate()` |
| **Environment setup** | Set `REVOLVER_*` env vars per ADR-006 |
| **OpenEvolve configuration** | Programmatically configure LLM endpoint, iterations, output dir |
| **Execution** | Launch OpenEvolve via controller class (not `run_evolution()`) |
| **Progress monitoring** | Display iteration count, best score, elapsed time |
| **Result collection** | Extract top-N solutions, store files + lineage + metrics |
| **Post-run evaluation** | Evaluate best program on all training instances (FR-RUN-019) |
| **Concurrency control** | Sequential for local LLMs, parallel for remote (§3.3) |

---

## 2. Command → Layer Flow

### 2.1 `revolver run`

Launch an OpenEvolve evolution run.

```
CLI (cli/run.py)
  │ Parse: --version, --llm, --dataset, --iterations, --alias, --top-n, --config-override
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
  │ 5. Check concurrency constraints                ──► Infra: store.get_active_run()
  │    If local LLM and another local run active → error (FR-RUN-014)
  │ 6. Generate solution ID                         ──► generate_solution_id()
  │ 7. Create solution directory structure          ──► Infra: store.create_solution_dir(id)
  │ 8. Generate wrapper evaluator                   ──► Core: run.generate_wrapper()
  │ 9. Prepare environment variables                (ADR-006)
  │ 10. Configure OpenEvolve programmatically       ──► Infra: openevolve.build_config()
  │ 11. Write run lock file                         ──► Infra: store.write_run_lock()
  │ 12. Launch OpenEvolve                           ──► Infra: openevolve.run()
  │ 13. Monitor progress                            ──► callback to CLI for display
  │ 14. On completion:
  │     a. Collect top-N programs                   ──► Infra: openevolve.collect_results()
  │     b. Generate run_id (= rank-1 solution ID)
  │     c. For each of the N programs (rank 1..N):
  │        i.   Generate solution ID                ──► generate_solution_id()
  │        ii.  Create solution directory            ──► Infra: store.create_solution_dir(id)
  │        iii. Copy program file as best.py
  │        iv.  Write manifest.yaml                  ──► Infra: store.write_solution_manifest()
  │        v.   Insert solution + lineage (with run_id, rank) in SQLite
  │     d. For rank-1 only: copy checkpoint, config, evaluator, side-channel logs
  │     e. Post-run training evaluation (rank-1)    ──► Core: eval.evaluate_solution() (FR-RUN-019)
  │     f. Remove run lock                          ──► Infra: store.remove_run_lock()
  │ 15. Return RunResult (containing N SolutionResults)
  ▼
Infra
  ├── store: project root, solution dirs, manifests, lock files
  ├── db: read problem/LLM/dataset, write solution + lineage
  ├── hashing: snapshot integrity verification
  ├── ollama: check model loaded (local LLMs)
  ├── openevolve: configure, launch, monitor, collect results
  └── dataset (core): integrity verification
```

### 2.2 `revolver run status`

Show the status of the current or most recent run.

```
CLI (cli/run.py)
  │ Parse: (no options)
  ▼
Core (core/run.py) → get_run_status()
  │ 1. Check for active run lock                    ──► Infra: store.get_active_run()
  │ 2. If active: read progress from lock file
  │ 3. If no active: query most recent solution     ──► Infra: db.get_latest_solution()
  │ 4. Return RunStatus
  ▼
Infra
  ├── store: read run lock file
  └── db: query latest solution
```

### 2.3 `revolver run resume`

Resume an interrupted run from its checkpoint.

```
CLI (cli/run.py)
  │ Parse: --solution <id-or-alias>
  ▼
Core (core/run.py) → resume_run()
  │ 1. Resolve solution                             ──► Infra: db.get_solution(id_or_alias)
  │ 2. Load solution lineage                        ──► Infra: db.get_lineage(solution_id)
  │ 3. Locate checkpoint dir                        ──► store: .revolver/solutions/<id>/oe-checkpoint/
  │ 4. Validate checkpoint exists and is non-empty
  │ 5. Load original problem version                ──► Infra: db.get_problem_version(tag)
  │ 6. Load original LLM config                     ──► Infra: db.get_llm(name)
  │ 7. Load original dataset                        ──► Infra: db.get_dataset(name)
  │ 8. Reconstruct environment and OpenEvolve config
  │    (same as original run, from lineage)
  │ 9. Launch OpenEvolve with checkpoint_path       ──► Infra: openevolve.run(checkpoint=...)
  │ 10. On completion: update solution (same ID)
  │     a. Update best_score if improved
  │     b. Update lineage (iterations, gen_time)
  │     c. Overwrite checkpoint with latest
  │     d. Post-run training evaluation              ──► Core: eval.evaluate_solution()
  │ 11. Return RunResult
  ▼
Infra
  ├── db: read solution + lineage, update on completion
  ├── openevolve: launch with checkpoint
  └── store: read/write checkpoint, update manifest
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

Revolver generates a `_revolver_evaluator.py` file in the solution's working directory that wraps the user's function:

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
        output_dir: Path to solution working directory

    Returns:
        Path to the generated _revolver_evaluator.py

    Validation:
        1. Check that snapshot_dir/evaluator.py defines evaluate_instance()
        2. If not, check for evaluate() — legacy mode (user wrote full dual-mode)
        3. If evaluate_instance() found → generate wrapper
        4. If evaluate() found → copy as-is (no wrapper needed)
        5. If neither → raise EvaluatorError
    """
```

### 3.4 Legacy Mode

If the user's evaluator already defines `evaluate(program_path)` (not `evaluate_instance`), Revolver uses it directly without generating a wrapper. This supports advanced users who want full control over the aggregation strategy and maintains backward compatibility with standard OpenEvolve evaluators.

Detection order:
1. `evaluate_instance(program_path, instance_path)` → generate wrapper
2. `evaluate(program_path)` → use as-is (legacy mode)
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

The generated `_revolver_evaluator.py` is used **exclusively by OpenEvolve** during the evolution run (aggregated mode). It is **not** used by `revolver eval` or `revolver benchmark`.

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
| `REVOLVER_INSTANCE_LOG` | `.revolver/solutions/<id>/instance_log.db` | Optional (FR-RUN-005b) |
| `REVOLVER_EVAL_LOG` | `.revolver/solutions/<id>/eval.log` | Optional (FR-RUN-005c) |

These are set in the current process environment before calling `openevolve.run()`. OpenEvolve's worker processes inherit them via standard `os.environ` propagation (validated in POC #12 S2).

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

### 6.1 Local LLM — Sequential Execution (FR-RUN-014)

Local LLMs share a single GPU. Only one local LLM run can execute at a time.

**Mechanism**: A lock file `.revolver/run.lock` is created when a local-LLM run starts:

```yaml
# .revolver/run.lock
solution_id: "sol-20260310-143000"
llm: "codestral-local"
llm_source: "local"
started_at: "2026-03-10T14:30:00Z"
pid: 12345
```

Before starting a local run, Revolver checks:
1. Does `.revolver/run.lock` exist?
2. If yes: is the PID still alive? (`os.kill(pid, 0)`)
3. If PID alive → error: "A local LLM run is already in progress"
4. If PID dead → stale lock, remove it and proceed

### 6.2 Remote LLM — Parallel Execution (FR-RUN-015)

Remote LLM runs have no local resource conflict. The lock file is still created (for `run status`) but does not block other runs. The check only applies when `llm_source == "local"`.

### 6.3 Lock File Lifecycle

```
start_run()  → write run.lock
              → launch OpenEvolve
              → on completion/failure: remove run.lock
              → on crash: stale lock detected by PID check
```

---

## 7. Post-Run Training Evaluation (FR-RUN-019/020)

After OpenEvolve completes, Revolver evaluates the best program on all training instances to produce per-instance results accessible via `revolver eval results`.

```python
def _post_run_evaluation(
    solution_id: str,
    problem_version: str,
    dataset_name: str,
) -> None:
    """
    Evaluate best program on all training instances.
    Reuses core.eval.evaluate_solution() with the training dataset.
    The program path is resolved internally from the solution_id.
    Results are stored in eval_metadata/eval_instances with the training
    dataset, making them accessible via:
      revolver eval results --solution <id> --dataset <train-dataset>
    """
```

This step is **synchronous** — it runs after OpenEvolve completes but before the run is marked as finished. If it fails, a warning is emitted but the run is still considered successful (the solution and lineage are already stored).

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

class SolutionManifest(BaseModel):
    """Manifest stored in .revolver/solutions/<id>/manifest.yaml."""
    model_config = ConfigDict(frozen=True)

    solution_id: str
    alias: str | None = None
    created_at: datetime
    generation_time_s: float
    iterations: int
    best_score: float | None = None

    # Lineage
    problem_version: str
    problem_hash: str
    dataset: str
    dataset_hash: str
    llm: str
    llm_model: str

    top_n: int = 1
    run_id: str | None = None       # Shared across top-N solutions; None if top_n=1
    rank: int = 1                   # 1 = best
    files: list[str] = []           # ["best.py", ...]
    checkpoint: str = "oe-checkpoint/"
    config_snapshot: str = "config.yaml"

class RunResult(BaseModel):
    """Returned to CLI after a run completes."""
    solutions: list["SolutionResult"]  # One per top-N program (rank 1 first)
    run_id: str                        # Shared across all top-N solutions
    problem_version: str
    llm: str
    dataset: str
    iterations: int
    generation_time_s: float

class SolutionResult(BaseModel):
    """One solution from a top-N run."""
    solution_id: str
    alias: str | None = None
    rank: int                          # 1 = best
    best_score: float | None = None
    path: str                          # .revolver/solutions/<id>/

class RunStatus(BaseModel):
    """Status of the current or most recent run."""
    active: bool
    solution_id: str | None = None
    problem_version: str | None = None
    llm: str | None = None
    dataset: str | None = None
    iterations_completed: int | None = None
    iterations_total: int | None = None
    best_score: float | None = None
    started_at: datetime | None = None
    elapsed_s: float | None = None

class ProgressInfo(BaseModel):
    """Progress callback data from OpenEvolve."""
    iteration: int
    total_iterations: int
    best_score: float
    elapsed_s: float
```

---

## 9. Storage Layout

### 9.1 Solution Directories

When `--top-n 1` (default), a single solution directory is created:

```
.revolver/solutions/
└── sol-20260310-143000/
    ├── manifest.yaml              # Solution metadata + lineage (§5 of spec-run)
    ├── best.py                    # Best evolved program
    ├── config.yaml                # Verbatim OpenEvolve config used (FR-RUN-017)
    ├── _revolver_evaluator.py     # Generated wrapper (or copied evaluator)
    ├── oe-checkpoint/             # OpenEvolve checkpoint for resume
    │   └── ...                    # OpenEvolve internal files
    ├── instance_log.db            # SQLite side-channel (optional, FR-RUN-005b)
    └── eval.log                   # Evaluator log (optional, FR-RUN-005c)
```

When `--top-n 3`, three separate solution directories are created (see DD-07):

```
.revolver/solutions/
├── sol-20260310-143000/           # rank 1 (best) — run_id = sol-20260310-143000
│   ├── manifest.yaml
│   ├── best.py
│   ├── config.yaml
│   ├── _revolver_evaluator.py
│   └── oe-checkpoint/             # Checkpoint stored only in rank-1 solution
├── sol-20260310-143000-1/         # rank 2 — run_id = sol-20260310-143000
│   ├── manifest.yaml
│   └── best.py
└── sol-20260310-143000-2/         # rank 3 — run_id = sol-20260310-143000
    ├── manifest.yaml
    └── best.py
```

**Note**: The checkpoint, config, evaluator, and side-channel logs are stored only in the rank-1 solution directory. Rank > 1 solutions contain only the program file and manifest. Resume always operates on the rank-1 solution.

### 9.2 Run Lock

```
.revolver/run.lock                 # Active run marker (deleted on completion)
```

### 9.3 SQLite

Uses tables from [DES-001](DES-001-sqlite-data-model.md):
- `solutions` (§3.5): solution metadata
- `solution_lineage` (§3.6): full provenance
- `eval_metadata` + `eval_instances` (§3.7–3.8): post-run training evaluation

---

## 10. Core Layer: Function Signatures

```python
# --- Run ---
def start_run(config: RunConfig) -> RunResult:
    """
    Launch an OpenEvolve evolution run.
    Validates inputs, generates wrapper, launches OE, stores results.
    If top_n > 1, creates N separate solutions with shared run_id.
    Post-run evaluation runs on the rank-1 (best) solution only.
    """

def resume_run(solution_id_or_alias: str) -> RunResult:
    """
    Resume an interrupted run from its checkpoint.
    Reconstructs config from lineage, launches OE with checkpoint.
    """

def get_run_status() -> RunStatus:
    """
    Get status of current or most recent run.
    Checks run lock first, falls back to latest solution.
    """

# --- Internal ---
def generate_wrapper(
    snapshot_dir: Path,
    output_dir: Path,
) -> Path:
    """Generate wrapper evaluator or copy legacy evaluator."""

def _post_run_evaluation(
    solution_id: str,
    problem_version: str,
    dataset_name: str,
) -> None:
    """Evaluate best program on training instances after run. Program path resolved from solution_id."""

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
    alias: str | None = typer.Option(None, "--alias", help="Solution alias"),
    top_n: int = typer.Option(1, "--top-n", help="Number of top solutions to keep"),
    config_override: list[str] | None = typer.Option(None, "--config-override", help="key=value overrides"),
): ...

@app.command()
def status(): ...

@app.command()
def resume(
    solution: str = typer.Option(..., "--solution", help="Solution ID or alias to resume"),
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
 │         │           │── check run lock ──►│            │        │
 │         │           │                     │            │        │
 │         │           │── gen solution ID    │            │        │
 │         │           │── create sol dir ───►│            │        │
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
 │         │           │── collect programs   │            │        │
 │         │           │── copy checkpoint ──►│            │        │
 │         │           │── write manifest ───►│            │        │
 │         │           │── insert solution ──────────────►│         │
 │         │           │── insert lineage ───────────────►│         │
 │         │           │── post-run eval      │            │        │
 │         │           │── remove run lock ──►│            │        │
 │◄─result─│◄─RunResult│                     │            │        │
```

### 12.2 `revolver run resume --solution claude-small-v1.1`

```
User      CLI         Core            OpenEvolve    Store    DB
 │         │           │                │            │        │
 │─resume─►│           │                │            │        │
 │         │─resume() ►│                │            │        │
 │         │           │── get solution ─────────────────────►│
 │         │           │── get lineage ──────────────────────►│
 │         │           │── locate checkpoint ►│            │
 │         │           │── validate checkpoint│            │
 │         │           │── get version ──────────────────────►│
 │         │           │── get LLM ──────────────────────────►│
 │         │           │── reconstruct config  │            │
 │         │           │── write run lock ────►│            │
 │         │           │                      │            │
 │         │           │── run(checkpoint) ───►│            │
 │         │           │                      │ (resume)   │
 │◄progress│◄─progress─│◄── on_progress ─────│            │
 │         │           │◄── results ──────────│            │
 │         │           │── update solution ──────────────►│
 │         │           │── update lineage ───────────────►│
 │         │           │── post-run eval       │            │
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

### DD-05: Generated wrapper stored in solution directory

The `_revolver_evaluator.py` is stored in the solution directory (not a temporary file) because:
- **Traceability**: the exact evaluator code used for the run is preserved
- **Debugging**: the user can inspect the generated wrapper if results are unexpected
- **Resume**: the wrapper is needed again if the run is resumed
- The `_` prefix signals it's an internal file, not user-authored

### DD-06: Environment variable cleanup via context manager

Env vars are set before the run and cleaned up after. The context manager pattern ensures cleanup even on exceptions, preventing env var pollution between sequential operations in the same process (e.g., running `revolver run` followed by `revolver eval` in a script).

### DD-07: Top-N creates N separate solutions (not N files in one)

When `--top-n > 1`, each of the N best programs becomes its own solution with a distinct solution ID, its own directory, and its own row in `solutions` + `solution_lineage`. All N solutions share a common `run_id` (equal to the rank-1 solution's ID) and are distinguished by `rank` (1 = best).

**Alternatives considered**:

| Approach | Pros | Cons |
|---|---|---|
| **A: N files in one solution** (`best.py`, `top-2.py`) | Simple storage, one ID | Only `best.py` usable by eval/benchmark; rank > 1 programs are dead artifacts |
| **B: N separate solutions** (chosen) | Each independently evaluable, benchmarkable, aliasable | More solutions in the listing; run_id/rank schema additions |

**Why option B**: the whole point of keeping N programs is to evaluate and compare them. With option A, `top-2.py` would require special-casing in `revolver eval` to specify which file to use — breaking the model where one solution = one program. Option B keeps the model clean: every solution is a first-class entity.

**Managing proliferation**: The user manages many solutions via:
- `revolver solution list --rank 1` — show only the best from each run (default for concise view)
- `revolver solution list --version v1.1 --llm claude` — filter by lineage
- `revolver solution list --sort score` — sort by score to find the best
- `revolver solution alias <id> "my-champion"` — name what matters (FR-SOL-006)
- The listing always shows lineage columns (version, LLM, dataset, rank) so each solution is identifiable at a glance

**Post-run behavior with top-N**:
- Post-run training evaluation (FR-RUN-019) runs on the **rank-1 solution only**. The user can evaluate rank > 1 solutions manually via `revolver eval`.
- Checkpoint and config are stored only in the rank-1 solution directory. `revolver run resume` always resumes the rank-1 solution.
- The `--alias` option (if provided) is set only on the rank-1 solution. Rank > 1 solutions have no alias by default.

---

## 14. Architecture Impact

### New modules

| Module | Layer | Purpose |
|---|---|---|
| `infra/openevolve.py` | Infrastructure | OpenEvolve controller wrapper (launch, monitor, collect results) |

### Existing modules impacted

| Module | Change |
|---|---|
| `core/run.py` | Implement `start_run()`, `resume_run()`, `get_run_status()`, `generate_wrapper()` |
| `cli/run.py` | Implement 3 Typer commands (`run`, `status`, `resume`) |
| `models/run.py` | Define `RunConfig`, `SolutionManifest`, `RunResult`, `RunStatus`, `ProgressInfo` (new file) |
| `infra/store.py` | Add `create_solution_dir()`, `write_solution_manifest()`, run lock management |
| `infra/db.py` | Add `insert_solution()`, `insert_lineage()`, `get_solution()`, `get_lineage()`, `get_latest_solution()` |
| `core/eval.py` | Called by `_post_run_evaluation()` — must be implemented before or alongside DES-005 |

### Cross-DES dependencies

| Dependency | Direction | Details |
|---|---|---|
| DES-001 | DES-005 → DES-001 | Uses `solutions` and `solution_lineage` tables |
| DES-003 | DES-005 → DES-003 | Loads problem version snapshot, verifies integrity |
| DES-004 | DES-005 → DES-004 | Loads dataset, verifies integrity, resolves path |
| DES-006 | DES-005 → DES-006 | Post-run evaluation reuses `core.eval.evaluate_solution()` |

---

## 15. Open Questions

- **RQ-01**: Should `revolver run` support `--dry-run` to validate all inputs and show the config without actually launching OpenEvolve? This would help catch configuration errors before committing to a potentially long run.
- **RQ-02**: Should the generated wrapper be regenerated on `resume`, or should the stored one be reused? Current design: reuse the stored one, since the problem version is immutable.
- **RQ-03**: How should OpenEvolve's progress be monitored? Options: (a) parse stdout, (b) poll checkpoint directory, (c) callback from controller. This depends on the controller class API, which needs further investigation.
- **RQ-04** (post-V1): Allow the user to choose top-N **after** a run completes, rather than at launch time. Currently `--top-n` must be set upfront. A post-run selection workflow (e.g., `revolver solution register --from-run <run-id> --rank 1..5`) would let the user inspect scores first and pick the programs to promote to solutions. This changes the ConOps significantly (candidate vs solution distinction, manual registration) and is deferred to a future version.
