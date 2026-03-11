# DES-006 — `revolver eval` — Evaluation Loop

**Version**: 0.1 — Initial draft
**Date**: 2026-03-11
**Status**: Draft
**Traceable to**: [spec-eval.md](../../specs/spec-eval.md), [Architecture](../architecture.md) §4/§6.2, [ADR-006](../adr/ADR-006-openevolve-instance-injection.md), [DES-001 Data Model](DES-001-sqlite-data-model.md) §3.7–3.8, [DES-003](DES-003-problem-versioning.md) §2.1.1, [DES-005](DES-005-run-orchestration.md) §7

---

## 1. Overview

This document details the design of the `revolver eval` commands: the default command (evaluate a solution against a dataset) and `results` (display stored evaluation results). The evaluation loop iterates over dataset instances in single-instance mode (ADR-006), calls the evaluator from the immutable problem version snapshot, and stores raw per-instance results in SQLite.

### 1.1 Key Responsibilities

| Responsibility | Description |
|---|---|
| **Input validation** | Solution exists, dataset exists, compatibility check |
| **Integrity verification** | Dataset hash check before evaluation |
| **Instance iteration** | Enumerate instances, set env vars per instance |
| **Evaluator invocation** | Call evaluator from problem version snapshot in subprocess |
| **Error isolation** | Per-instance failure does not abort the full evaluation |
| **Timeout enforcement** | Per-instance timeout via subprocess |
| **Result storage** | Raw per-instance results in SQLite (single source of truth) |
| **Aggregate computation** | Compute aggregates at display time from raw data |
| **Progress reporting** | Progress bar during evaluation |

### 1.2 Relationship with `revolver run`

The evaluation loop is also used by `revolver run` for post-run training evaluation (FR-RUN-019, [DES-005](DES-005-run-orchestration.md) §7). The core function `evaluate_solution()` is designed to be called from both `revolver eval` (CLI entry point) and `core.run._post_run_evaluation()` (internal).

---

## 2. Command → Layer Flow

### 2.1 `revolver eval`

Evaluate a solution against an evaluation dataset.

```
CLI (cli/eval.py)
  │ Parse: --solution, --dataset, --timeout, --parallelism
  ▼
Core (core/eval.py) → evaluate_solution()
  │ 1. Resolve project root                        ──► Infra: store.find_project_root()
  │ 2. Load solution metadata                       ──► Infra: db.get_solution(id_or_alias)
  │ 3. Load solution lineage                        ──► Infra: db.get_lineage(solution_id)
  │ 4. Load dataset registration                    ──► Infra: db.get_dataset(name)
  │    Quick integrity check                        ──► Core: dataset.verify_dataset_integrity()
  │    Warn if split != 'eval'                     (FR-EVL-009)
  │    Warn if not compatible with version          (FR-EVL-008)
  │ 5. Resolve evaluator path:
  │    .revolver/problem/<version>/evaluator.py     (FR-EVL-003)
  │ 6. Load evaluator module                        ──► Infra: evaluator_loader.load(path)
  │ 7. Resolve dataset path                         ──► Core: dataset.resolve_dataset_path()
  │ 8. Enumerate instances:
  │    sorted(p for p in dataset_path.iterdir() if not p.name.startswith('.'))
  │ 9. Generate eval ID                             ──► generate_eval_id()
  │ 10. Evaluation loop: for each instance:
  │     a. Set REVOLVER_INSTANCE_PATH               (FR-EVL-002)
  │     b. Set REVOLVER_INSTANCE_ID
  │     c. Call evaluator in subprocess with timeout (§3)
  │     d. Collect metrics dict + wall-clock time
  │     e. Store raw result in SQLite immediately    ──► Infra: db.insert_eval_instance()
  │     f. Report progress                           ──► callback to CLI
  │ 11. Store eval metadata in SQLite               ──► Infra: db.insert_eval_metadata()
  │ 12. Return EvalResult
  ▼
Infra
  ├── store: project root, evaluator path resolution
  ├── db: read solution/dataset, write eval results
  ├── evaluator_loader: dynamic module loading
  └── hashing: dataset integrity verification
```

### 2.2 `revolver eval results`

Display results of a previous evaluation.

```
CLI (cli/eval.py)
  │ Parse: --solution, --dataset, --per-instance, --json
  ▼
Core (core/eval.py) → get_eval_results()
  │ 1. Resolve solution                             ──► Infra: db.get_solution(id_or_alias)
  │ 2. Query eval metadata                          ──► Infra: db.get_eval_metadata()
  │ 3. If --per-instance:
  │    a. Query all raw instance results            ──► Infra: db.get_eval_instances()
  │    b. Return EvalDetailResult
  │ 4. Else (aggregates):
  │    a. Query raw instance results                ──► Infra: db.get_eval_instances()
  │    b. Compute aggregates in Python              (§4)
  │    c. Return EvalSummaryResult
  ▼
Infra
  └── db: query eval_metadata, eval_instances
```

---

## 3. Instance Evaluation Subprocess

Each instance is evaluated in an isolated subprocess, reusing the pattern from [DES-003 §2.1.1](DES-003-problem-versioning.md).

### 3.1 Why Subprocess?

Same rationale as DES-003 DD-01:
- **Hard timeout**: `future.result(timeout=N)` followed by process termination
- **Crash isolation**: evaluator segfaults don't affect the main Revolver process
- **Clean environment**: env vars set in child don't pollute parent

### 3.2 Subprocess Execution

```python
from concurrent.futures import ProcessPoolExecutor, TimeoutError

def _evaluate_instance(
    evaluator_path: Path,
    program_path: Path,
    instance_path: Path,
    instance_id: str,
    timeout_s: int = 300,
) -> InstanceResult:
    """
    Evaluate a single instance in a subprocess.

    1. Spawn subprocess via ProcessPoolExecutor(max_workers=1)
    2. In child process:
       a. Set REVOLVER_INSTANCE_PATH = str(instance_path)
       b. Set REVOLVER_INSTANCE_ID = instance_id
       c. Import evaluator module
       d. Call evaluate(program_path) or evaluate_instance(program_path, instance_path)
       e. Return metrics dict
    3. In parent: collect result with timeout
    4. On timeout: cancel future, return InstanceResult(status="timeout")
    5. On exception: return InstanceResult(status="failed", error=str(e))
    """
```

### 3.3 Evaluator Resolution

The evaluator is loaded from the **immutable problem version snapshot**, not the mutable working copy (FR-EVL-003):

```
.revolver/problem/<version>/evaluator.py
```

This ensures evaluation results are reproducible — the evaluator code cannot change between evaluations of the same problem version.

**Dual-mode detection**: The evaluator may define either:
1. `evaluate(program_path)` — standard OpenEvolve interface, used as-is
2. `evaluate_instance(program_path, instance_path)` — Revolver-style, called directly with instance path

Detection priority:
1. If `evaluate_instance` exists → call it with `(program_path, instance_path)`
2. Else if `evaluate` exists → set `REVOLVER_INSTANCE_PATH` env var, call `evaluate(program_path)`
3. Else → error

### 3.4 Parallelism (FR-EVL-014 — MAY)

Optional `--parallelism <n>` uses a `ProcessPoolExecutor` with `max_workers=n`:

```python
if parallelism > 1:
    with ProcessPoolExecutor(max_workers=parallelism) as pool:
        futures = {
            pool.submit(_eval_worker, evaluator_path, program_path, inst, timeout_s): inst
            for inst in instances
        }
        for future in as_completed(futures):
            instance = futures[future]
            result = future.result()  # InstanceResult
            ...
```

**Constraints**:
- Default parallelism is 1 (sequential)
- Parallelism is limited to the number of CPU cores
- Each subprocess gets its own environment (env vars are set per-worker)
- SQLite writes are safe with WAL mode (validated in POC #12 S4)

---

## 4. Aggregate Computation

### 4.1 Design Decision: Compute at Read Time (DD-01)

FR-EVL-006 specifies: "Compute aggregate statistics at read time from stored raw data — aggregates are not stored separately."

This contradicts DES-001 §3.7 which defines an `eval_results` table for stored aggregates, and DES-001 DM-01 which says aggregates are materialized.

**Resolution**: We follow the spec (FR-EVL-006). Aggregates are computed in Python from raw `eval_instances` data at display time. The `eval_results` table from DES-001 is **replaced** by a lighter `eval_metadata` table that stores only the evaluation session metadata (no per-metric aggregate rows).

**Rationale**:
- **Single source of truth**: raw per-instance data is the only stored data; aggregates are derived
- **Flexibility**: if aggregate formulas change (e.g., add p25/p75), no migration needed
- **Simplicity**: one table for raw data, one for metadata, instead of three (metadata + aggregates + instances)
- **Performance is acceptable**: computing aggregates from 10,000 instances in Python takes <10ms; even 100,000 instances complete in <100ms

### 4.2 Revised Schema

Replace `eval_results` (DES-001 §3.7) with:

```sql
CREATE TABLE eval_metadata (
    eval_id         TEXT PRIMARY KEY,       -- "eval-YYYYMMDD-HHMMSS"
    solution_id     TEXT NOT NULL REFERENCES solutions(id),
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    instance_count  INTEGER NOT NULL,
    instances_solved INTEGER NOT NULL,
    eval_time_s     REAL,                   -- total wall-clock time
    evaluated_at    TEXT NOT NULL            -- ISO 8601
);

CREATE UNIQUE INDEX idx_eval_unique ON eval_metadata(solution_id, dataset_name);
```

The `eval_instances` table (DES-001 §3.8) is **kept as-is** but with a simplified foreign key:

```sql
CREATE TABLE eval_instances (
    eval_id         TEXT NOT NULL REFERENCES eval_metadata(eval_id),
    instance_id     TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    value           REAL,                   -- NULL if failed/timeout
    status          TEXT NOT NULL CHECK (status IN ('solved', 'failed', 'timeout')),
    error_message   TEXT,                   -- if status != 'solved'
    compute_time_s  REAL,                   -- wall-clock time for this instance
    PRIMARY KEY (eval_id, instance_id, metric_name)
);

CREATE INDEX idx_eval_inst_eval ON eval_instances(eval_id);
```

**Note**: `idx_eval_unique` on `eval_metadata` ensures at most one evaluation per (solution, dataset). Re-evaluation replaces the previous result (DELETE old + INSERT new in a transaction).

### 4.3 Aggregate Computation Logic

```python
import statistics

def compute_aggregates(
    instances: list[InstanceResult],
) -> dict[str, MetricAggregate]:
    """
    Compute aggregate statistics from raw per-instance results.

    For each metric key found across solved instances:
        - mean, min, max
        - p10, p50 (median), p90
        - std (sample standard deviation; 0.0 if n=1)

    Returns dict mapping metric_name → MetricAggregate.
    """
    solved = [i for i in instances if i.status == "solved"]
    if not solved:
        return {}

    # Discover all metric keys
    all_keys: set[str] = set()
    for inst in solved:
        all_keys.update(inst.metrics.keys())

    aggregates = {}
    for key in sorted(all_keys):
        values = [inst.metrics[key] for inst in solved if key in inst.metrics]
        if not values:
            continue
        values_sorted = sorted(values)
        n = len(values_sorted)
        aggregates[key] = MetricAggregate(
            mean=statistics.mean(values),
            min=min(values),
            max=max(values),
            p10=_percentile(values_sorted, 0.10),
            p50=_percentile(values_sorted, 0.50),
            p90=_percentile(values_sorted, 0.90),
            std=statistics.stdev(values) if n > 1 else 0.0,
            count=n,
        )
    return aggregates


def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile using linear interpolation (same as numpy default)."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    k = (n - 1) * p
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_values[-1]
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])
```

---

## 5. Re-Evaluation Handling

When evaluating a solution that already has results on the same dataset:

```python
def evaluate_solution(...) -> EvalResult:
    # Check for existing results
    existing = db.get_eval_metadata(solution_id, dataset_name)
    if existing:
        # Delete old results and re-evaluate
        db.delete_eval(existing.eval_id)  # Cascades to eval_instances
    # Proceed with evaluation...
```

This is an **unconditional replace** — if the user runs `revolver eval` again on the same (solution, dataset), the previous results are deleted and replaced. Rationale:
- The evaluator code is immutable (from problem version snapshot), so results should be identical
- But the dataset may have changed (integrity check warns but doesn't block)
- Re-evaluation is an explicit user action, so replacing is expected behavior

---

## 6. Pydantic Data Models

```python
from pydantic import BaseModel, ConfigDict
from datetime import datetime

class InstanceResult(BaseModel):
    """Result of evaluating a single instance.
    Note: status uses "solved"/"failed"/"timeout" (matching SQLite CHECK constraint
    and spec-eval output). DES-003 InstanceTestResult uses "pass"/"fail"/"timeout"
    for problem testing. The difference is intentional: "solved/failed" reflects
    whether the evaluator produced a valid result, while "pass/fail" reflects
    whether the test assertion passed."""
    instance_id: str
    status: str                     # "solved" | "failed" | "timeout"
    metrics: dict[str, float] = {}  # Empty if failed/timeout
    error: str | None = None
    compute_time_s: float | None = None

class MetricAggregate(BaseModel):
    """Aggregate statistics for a single metric."""
    model_config = ConfigDict(frozen=True)

    mean: float
    min: float
    max: float
    p10: float
    p50: float
    p90: float
    std: float
    count: int

class EvalMetadata(BaseModel):
    """Evaluation session metadata."""
    model_config = ConfigDict(frozen=True)

    eval_id: str
    solution_id: str
    dataset_name: str
    instance_count: int
    instances_solved: int
    eval_time_s: float | None = None
    evaluated_at: datetime

class ComputeTimeSummary(BaseModel):
    """Compute time statistics across all instances."""
    model_config = ConfigDict(frozen=True)

    mean_s: float
    max_s: float
    total_s: float

class EvalResult(BaseModel):
    """Full evaluation result returned to CLI.
    JSON serialization produces nested 'compute_time' matching spec-eval §2.1."""
    metadata: EvalMetadata
    aggregates: dict[str, MetricAggregate]
    compute_time: ComputeTimeSummary | None = None

class EvalDetailResult(BaseModel):
    """Per-instance evaluation result for --per-instance output."""
    metadata: EvalMetadata
    instances: list[InstanceResult]
```

---

## 7. Storage

### 7.1 SQLite Only

Unlike `revolver run` which uses both files and SQLite, `revolver eval` stores results **only in SQLite**. There are no manifest files or filesystem artifacts for evaluations.

Tables used:
- `eval_metadata`: one row per evaluation session
- `eval_instances`: one row per (instance, metric) — N instances × M metrics rows per evaluation

### 7.2 Storage Example

For an evaluation with 100 instances and 2 metrics (`combined_score`, `makespan`):

```
eval_metadata: 1 row
eval_instances: 200 rows (100 instances × 2 metrics)
```

Query for aggregate display:
```sql
SELECT metric_name, value
FROM eval_instances
WHERE eval_id = :eval_id AND status = 'solved'
ORDER BY metric_name, instance_id;
```

Aggregates are then computed in Python from the result set.

### 7.3 Key Queries

#### Get evaluation for a (solution, dataset) pair
```sql
SELECT * FROM eval_metadata
WHERE solution_id = :solution_id
  AND (:dataset IS NULL OR dataset_name = :dataset)
ORDER BY evaluated_at DESC
LIMIT 1;
```

#### Get raw per-instance results
```sql
SELECT instance_id, metric_name, value, status, error_message, compute_time_s
FROM eval_instances
WHERE eval_id = :eval_id
ORDER BY instance_id, metric_name;
```

#### Check if evaluation exists (used by benchmark to skip re-eval)
```sql
SELECT eval_id FROM eval_metadata
WHERE solution_id = :solution_id AND dataset_name = :dataset_name
LIMIT 1;
```

---

## 8. Core Layer: Function Signatures

```python
# --- Evaluation ---
def evaluate_solution(
    solution_id_or_alias: str,
    dataset_name: str,
    timeout_s: int = 300,
    parallelism: int = 1,
    on_progress: Callable[[int, int], None] | None = None,
) -> EvalResult:
    """
    Evaluate a solution against a dataset.
    Iterates instances, stores raw results, computes aggregates.
    Called by both CLI (revolver eval) and core.run (post-run eval).
    """

def get_eval_results(
    solution_id_or_alias: str,
    dataset_name: str | None = None,
    per_instance: bool = False,
) -> EvalResult | EvalDetailResult:
    """
    Retrieve stored evaluation results.
    If per_instance=True, returns all raw instance data.
    Otherwise, computes aggregates from raw data.
    """

# --- Internal ---
def _evaluate_instance(
    evaluator_path: Path,
    program_path: Path,
    instance_path: Path,
    instance_id: str,
    timeout_s: int = 300,
) -> InstanceResult:
    """Evaluate a single instance in a subprocess."""

def generate_eval_id() -> str:
    """Generate eval-YYYYMMDD-HHMMSS with counter for collisions."""

def compute_aggregates(
    instances: list[InstanceResult],
) -> dict[str, MetricAggregate]:
    """Compute aggregate statistics from raw results."""
```

---

## 9. CLI Layer: Typer Commands

Global options `--json`, `--verbose`, `--quiet` are defined in the root Typer app callback (`cli/__init__.py`, see [architecture.md §4.1](../architecture.md)) and inherited by all commands. They are not repeated here.

```python
import typer

app = typer.Typer(name="eval", help="Evaluate solutions against datasets")

@app.callback(invoke_without_command=True)
def eval_default(
    ctx: typer.Context,
    solution: str = typer.Option(..., "--solution", help="Solution ID or alias"),
    dataset: str = typer.Option(..., "--dataset", help="Evaluation dataset name"),
    timeout: int = typer.Option(300, "--timeout", help="Per-instance timeout (seconds)"),
    parallelism: int = typer.Option(1, "--parallelism", help="Concurrent instances"),
    per_instance: bool = typer.Option(False, "--per-instance", help="Show per-instance results on completion"),
): ...

@app.command()
def results(
    solution: str = typer.Option(..., "--solution", help="Solution ID or alias"),
    dataset: str | None = typer.Option(None, "--dataset", help="Filter by dataset"),
    per_instance: bool = typer.Option(False, "--per-instance", help="Show per-instance results"),
): ...
```

---

## 10. Sequence Diagrams

### 10.1 `revolver eval --solution claude-small-v1.1 --dataset eval-benchmark`

```
User      CLI         Core            EvalLoader   Subprocess   DB       Hashing
 │         │           │                │            │           │         │
 │─ eval ─►│           │                │            │           │         │
 │         │─evaluate()►│               │            │           │         │
 │         │           │── get solution ──────────────────────►│         │
 │         │           │── get lineage ───────────────────────►│         │
 │         │           │── get dataset ───────────────────────►│         │
 │         │           │── check integrity ──────────────────────────────►│
 │         │           │── resolve evaluator path              │         │
 │         │           │── enumerate instances                 │         │
 │         │           │── generate eval ID                    │         │
 │         │           │                │            │           │         │
 │         │           │── for each instance:        │           │         │
 │         │           │   │ set env vars             │           │         │
 │         │           │   │ spawn ──────────────────►│           │         │
 │         │           │   │   import evaluator       │           │         │
 │         │           │   │   call evaluate()        │           │         │
 │         │           │   │◄── metrics ─────────────│           │         │
 │         │           │   │ store instance result ──────────►│         │
 │◄progress│◄─progress─│   │                          │           │         │
 │         │           │                              │           │         │
 │         │           │── store eval metadata ───────────────►│         │
 │         │           │── compute aggregates (Python)│           │         │
 │◄─result─│◄EvalResult│                              │           │         │
```

### 10.2 `revolver eval results --solution claude-small-v1.1 --per-instance`

```
User      CLI         Core            DB
 │         │           │               │
 │─results►│           │               │
 │         │─get_eval()►│              │
 │         │           │── get metadata ►│
 │         │           │◄── metadata ──│
 │         │           │── get instances►│
 │         │           │◄── raw data ──│
 │◄─table──│◄─Detail ──│              │
```

---

## 11. Design Decisions

### DD-01: Aggregates computed at read time, not stored

See §4.1 for full rationale. This resolves the tension between FR-EVL-006 (no stored aggregates) and DES-001 DM-01 (materialized aggregates). We follow the spec.

**DES-001 update required**: Replace `eval_results` table with `eval_metadata`. The `eval_instances` table is retained with a simplified FK. DES-001 §3.7 and DM-01 should be updated to reflect this decision.

### DD-02: Evaluator from problem version snapshot (FR-EVL-003)

The evaluator used for evaluation is always the one from the immutable problem version snapshot (`.revolver/problem/<version>/evaluator.py`), not the mutable working copy. This ensures:
- **Reproducibility**: same problem version → same evaluator → same results (given same data)
- **Isolation**: editing the working copy doesn't affect ongoing or future evaluations of existing versions

### DD-03: Immediate per-instance storage

Each instance result is stored in SQLite immediately after completion, not batched:
- **Resilience**: if the evaluation is interrupted, completed instances are preserved
- **Observability**: intermediate results can be queried during a long evaluation
- **Simplicity**: no in-memory accumulator to manage

Trade-off: more frequent SQLite writes. Mitigated by WAL mode and the fact that each write is a single INSERT (~0.1ms).

### DD-04: Re-evaluation replaces previous results

Running `revolver eval` on the same (solution, dataset) pair deletes and replaces previous results. Alternatives considered:
- **Keep history**: store multiple evaluations per (solution, dataset). Rejected: adds complexity (which eval to display by default?), and the evaluator is immutable so results should be identical.
- **Block re-evaluation**: error if results exist. Rejected: prevents legitimate use cases (dataset modified, evaluator bug fixed in new problem version).

### DD-05: Single `_evaluate_instance` implementation shared with DES-003

The subprocess-based instance evaluation logic is shared between `core.eval._evaluate_instance()` and `core.problem._test_instance()` (DES-003). Both:
- Run the evaluator in a subprocess with timeout
- Set `REVOLVER_INSTANCE_PATH` and `REVOLVER_INSTANCE_ID`
- Collect `dict[str, float]` result

The difference: `problem test` loads the mutable evaluator, while `eval` loads the snapshot evaluator. The subprocess wrapper is the same. This should be factored into a shared function in `core/_eval_common.py` or `infra/evaluator_runner.py`.

---

## 12. Architecture Impact

### New modules

| Module | Layer | Purpose |
|---|---|---|
| `infra/evaluator_runner.py` | Infrastructure | Shared subprocess-based evaluator execution (used by both `core/eval.py` and `core/problem.py`) |

### Existing modules impacted

| Module | Change |
|---|---|
| `core/eval.py` | Implement `evaluate_solution()`, `get_eval_results()`, `compute_aggregates()` |
| `cli/eval.py` | Implement 2 Typer commands (`eval`, `results`) |
| `models/eval.py` | Define `InstanceResult`, `MetricAggregate`, `EvalMetadata`, `EvalResult`, `EvalDetailResult` |
| `infra/db.py` | Add `insert_eval_metadata()`, `insert_eval_instance()`, `get_eval_metadata()`, `get_eval_instances()`, `delete_eval()` |
| `infra/evaluator_loader.py` | Already exists (DES-003) — no change |
| `core/problem.py` | Refactor `_test_instance()` to use shared `evaluator_runner` |

### DES-001 Schema Update (done)

The `eval_results` table (DES-001 §3.7) has been replaced by `eval_metadata`. Updated sections:
- [x] DES-001 §2 ER diagram → `eval_metadata` replaces `eval_results`
- [x] DES-001 §3.7 → `eval_metadata` table definition
- [x] DES-001 §3.8 → FK simplified to reference `eval_metadata(eval_id)`
- [x] DES-001 §6.3 → benchmark query loads raw data, aggregates computed in Python
- [x] DES-001 §6.5 → queries `eval_metadata`
- [x] DES-001 §9 → "Why raw data only" replaces "Why store aggregates AND raw data"
- [x] DES-001 DM-01 → updated to reflect read-time computation

### Impact on `core/benchmark.py`

With aggregates no longer stored in SQLite, `revolver benchmark` must compute aggregates in Python from raw `eval_instances` data. The `compute_aggregates()` function (§4.3) is reusable:
- `core/benchmark.py` loads raw per-instance data for each solution via `db.get_eval_instances()`
- Calls `compute_aggregates()` to produce per-solution, per-metric statistics
- Builds the comparative table from these aggregates

This is consistent with spec-benchmark FR-BEN-004 ("per-metric aggregate statistics computed from raw per-instance data") and FR-BEN-006 ("per-instance data is read from eval results, single source of truth").

### Cross-DES dependencies

| Dependency | Direction | Details |
|---|---|---|
| DES-001 | DES-006 → DES-001 | Uses `eval_metadata` + `eval_instances` tables (schema update required) |
| DES-003 | DES-006 ↔ DES-003 | Shares evaluator subprocess pattern; uses evaluator_loader |
| DES-004 | DES-006 → DES-004 | Uses `resolve_dataset_path()` and `verify_dataset_integrity()` |
| DES-005 | DES-005 → DES-006 | Post-run evaluation calls `evaluate_solution()` |

---

## 13. Open Questions

- **EQ-01**: Should re-evaluation ask for confirmation before deleting existing results? Current design: no, `revolver eval` is idempotent — running it again simply refreshes the results. If we add confirmation, it should probably be a `--force` flag.
- **EQ-02**: Should `eval results` support filtering by instance status (e.g., `--failed-only`)? Useful for debugging, but adds CLI complexity. Could be deferred to a later version.
- **EQ-03**: The shared evaluator subprocess logic (DD-05) could live in `infra/evaluator_runner.py` (new module) or `core/_eval_common.py` (private module in core). Which is the better location? Subprocess management is infrastructure-level, suggesting `infra/`.
