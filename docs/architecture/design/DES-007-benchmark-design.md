# DES-007 — `revolver benchmark` — Benchmark Design

**Version**: 0.1
**Date**: 2026-03-12
**Status**: Accepted
**Traceable to**: [spec-benchmark.md](../../specs/spec-benchmark.md), [Architecture](../architecture.md) §4/§6.3, [DES-001 Data Model](DES-001-sqlite-data-model.md) §3.9–3.10 (benchmarks, benchmark_solutions), [DES-006 Eval Loop](DES-006-eval-loop.md) §4/§6 (compute_aggregates, Pydantic models), [ConOps](../../conops/conops.md) §4.7/§5.7/§8 (export formats)

---

## 1. Overview

This document details the design of the `revolver benchmark` commands: `benchmark` (run a comparative benchmark), `results` (display stored benchmark results), `export` (export to CSV/JSON), and `list` (list past benchmarks). A benchmark evaluates multiple solutions against a single evaluation dataset and produces a comparative table with aggregate statistics.

### 1.1 Key Responsibilities

| Responsibility | Description |
|---|---|
| **Input validation** | All solutions exist, dataset exists, warn on `train` split |
| **Eval reuse** | Skip evaluation for solutions that already have results on the dataset |
| **Eval trigger** | Run evaluation for solutions missing results (delegates to `core.eval`) |
| **Aggregate computation** | Compute per-solution aggregates from raw per-instance data (reuses `compute_aggregates()` from DES-006) |
| **Comparison** | Build comparative table across solutions for each metric |
| **Per-instance comparison** | Side-by-side per-instance view with best-per-instance identification |
| **Lineage enrichment** | Include run lineage (problem version, LLM, training dataset, generation time) |
| **Storage** | Store benchmark metadata and solution membership in SQLite |
| **Export** | CSV and JSON export matching ConOps §8.1/§8.2 schemas |

### 1.2 Relationship with `revolver eval`

Benchmark is a **consumer** of evaluation results. It never computes per-instance metrics directly — it either reuses existing eval results or triggers `core.eval.evaluate_solution()` for solutions that lack results. The `compute_aggregates()` function from DES-006 is the single source of truth for aggregate computation.

```
revolver benchmark
  │
  ├── For each solution:
  │   ├── Has eval results? → reuse (query eval_instances)
  │   └── No eval results?  → call core.eval.evaluate_solution()
  │
  ├── compute_aggregates() per solution  (DES-006 §4.3)
  ├── Build comparative table
  └── Store benchmark metadata in SQLite
```

---

## 2. Command → Layer Flow

### 2.1 `revolver benchmark`

Run a comparative benchmark of multiple solutions.

```
CLI (cli/benchmark.py)
  │ Parse: --solutions, --dataset, --timeout, --alias
  ▼
Core (core/benchmark.py) → run_benchmark()
  │ 1. Resolve project root                        ──► Infra: store.find_project_root()
  │    If not found → ProjectNotFoundError (exit 1)
  │ 2. Validate all solutions exist                 ──► Infra: db.get_solution(id_or_alias)
  │                                                     for each solution
  │ 3. Load dataset registration                    ──► Infra: db.get_dataset(name)
  │    Quick integrity check                        ──► Core: dataset.verify_dataset_integrity()
  │    Warn if split != 'eval'                     (FR-BEN-001)
  │ 4. For each solution:
  │    a. Check for existing eval results           ──► Infra: db.get_eval_metadata()
  │    b. If exists → reuse (skip evaluation)       (FR-BEN-002)
  │    c. If not → run evaluation                   ──► Core: eval.evaluate_solution()
  │       with force=True (no confirmation needed)  (FR-BEN-003)
  │    d. On eval failure → mark as failed,         (spec §4)
  │       continue with remaining solutions
  │ 5. Load raw per-instance data for all           ──► Infra: db.get_eval_instances()
  │    successfully evaluated solutions
  │ 6. Compute aggregates per solution              ──► Core: eval.compute_aggregates()
  │ 7. Enrich with lineage from parent run          ──► Infra: db.get_run(solution.run_id)
  │ 8. Generate benchmark ID                        ──► generate_benchmark_id()
  │ 9. Store benchmark metadata + solution refs     ──► Infra: db.insert_benchmark()
  │                                                     Infra: db.insert_benchmark_solutions()
  │ 10. Return BenchmarkResult
  ▼
Infra
  ├── store: project root resolution
  ├── db: read solutions/runs/eval data, write benchmark rows
  └── hashing: dataset integrity verification (via eval)
```

### 2.2 `revolver benchmark results`

Display results of a previous benchmark.

```
CLI (cli/benchmark.py)
  │ Parse: --latest, --id, --metric, --per-instance, --sort-by
  ▼
Core (core/benchmark.py) → get_benchmark_results()
  │ 1. Resolve benchmark                            ──► Infra: db.get_benchmark()
  │    (by --id or --latest)
  │ 2. Load benchmark solutions                     ──► Infra: db.get_benchmark_solutions()
  │ 3. If --per-instance:
  │    a. Load raw per-instance data for all         ──► Infra: db.get_eval_instances()
  │       solutions in the benchmark
  │    b. Build per-instance comparison matrix
  │    c. Identify best solution per instance        (FR-BEN-015)
  │    d. Return BenchmarkDetailResult
  │ 4. Else (aggregates):
  │    a. Load raw per-instance data per solution    ──► Infra: db.get_eval_instances()
  │    b. Compute aggregates per solution            ──► Core: eval.compute_aggregates()
  │    c. Enrich with lineage                        ──► Infra: db.get_run()
  │    d. Return BenchmarkResult
  ▼
Infra
  └── db: query benchmarks, benchmark_solutions, eval_metadata, eval_instances, runs
```

### 2.3 `revolver benchmark export`

Export benchmark results to a file.

```
CLI (cli/benchmark.py)
  │ Parse: --latest, --id, --format, --output, --per-instance
  ▼
Core (core/benchmark.py) → export_benchmark()
  │ 1. Resolve benchmark (same as §2.2)
  │ 2. Load all data (same as §2.2, aggregates or per-instance)
  │ 3. Format according to --format:
  │    a. csv → build CSV rows matching ConOps §8.1  (FR-BEN-007)
  │    b. json → build JSON matching ConOps §8.2     (FR-BEN-008)
  │ 4. Write to --output path
  │ 5. Strip secrets/file paths from export          (FR-BEN-013)
  ▼
Infra
  └── db: same as §2.2
```

### 2.4 `revolver benchmark list`

List all benchmarks.

```
CLI (cli/benchmark.py)
  │ Parse: (no required options)
  ▼
Core (core/benchmark.py) → list_benchmarks()
  │ 1. Query all benchmarks with solution count      ──► Infra: db.list_benchmarks()
  │ 2. Return list[BenchmarkSummary]
  ▼
Infra
  └── db: query benchmarks + COUNT(benchmark_solutions)
```

---

## 3. Eval Reuse Logic

The benchmark's core optimization is avoiding redundant evaluation (FR-BEN-002). The logic is:

```python
def _ensure_evaluated(
    solution_id: str,
    dataset_name: str,
    timeout_s: int,
) -> EvalStatus:
    """
    Ensure a solution has been evaluated on the dataset.
    Returns the eval status (reused, evaluated, or failed).
    """
    existing = db.get_eval_metadata(solution_id, dataset_name)
    if existing:
        return EvalStatus(status="reused", eval_id=existing.eval_id)

    try:
        result = eval.evaluate_solution(
            solution_id_or_alias=solution_id,
            dataset_name=dataset_name,
            timeout_s=timeout_s,
            force=True,  # No confirmation — benchmark context
        )
        return EvalStatus(status="evaluated", eval_id=result.metadata.eval_id)
    except EvalError as e:
        return EvalStatus(status="failed", error=str(e))
```

**Key behaviors**:

| Scenario | Action |
|---|---|
| Eval results exist for (solution, dataset) | Reuse — no re-evaluation |
| No eval results | Trigger `evaluate_solution()` with `force=True` |
| Evaluation fails for one solution | Mark failed, continue with others |
| All evaluations fail | Error: "Evaluation failed for all solutions" (exit code 4) |

**Why `force=True`**: Benchmark triggers evaluation as a side effect. There is no pre-existing result to protect, so no confirmation is needed. The `force=True` flag bypasses the re-evaluation confirmation from DES-006 §5 (D-006-a) without prompting the user.

---

## 4. Aggregate Computation

### 4.1 Reuse of DES-006 `compute_aggregates()`

Benchmark reuses the `compute_aggregates()` function from DES-006 §4.3 to compute per-solution statistics. This function takes a list of `InstanceResult` objects and returns `dict[str, MetricAggregate]` with mean, min, max, p10, p50, p90, std, count per metric.

```python
# In core/benchmark.py
from revolver.core.eval import compute_aggregates

def _compute_solution_aggregates(
    solution_id: str,
    dataset_name: str,
) -> dict[str, MetricAggregate]:
    """Load raw per-instance data and compute aggregates for a solution."""
    eval_meta = db.get_eval_metadata(solution_id, dataset_name)
    raw_instances = db.get_eval_instances(eval_meta.eval_id)
    return compute_aggregates(raw_instances)
```

### 4.2 User Aggregates in Benchmark

When a solution was evaluated with a legacy `evaluate()` evaluator (D-006-g), `eval_metadata.user_aggregates` contains the user's custom aggregation. Benchmark includes these in the results alongside Revolver-computed aggregates (DD-06).

The display logic:
- **Revolver aggregates**: always shown (computed from per-instance raw data)
- **User aggregates**: shown when present, with a `[user]` prefix to distinguish them

---

## 5. Per-Instance Comparison

### 5.1 Comparison Matrix

`benchmark results --per-instance` builds a matrix: rows = instances, columns = solutions.

```python
def _build_comparison_matrix(
    benchmark_id: str,
    dataset_name: str,
    metric_filter: str | None,
) -> list[InstanceComparison]:
    """
    Build per-instance comparison across all benchmark solutions.

    For each instance, collects the metric values from each solution's
    eval results. Identifies the best solution per instance (FR-BEN-015).
    """
```

### 5.2 Best-Per-Instance Identification (FR-BEN-015)

For each instance, the solution with the highest value for the sort metric (default: `combined_score`) is identified as the "best". The summary line counts wins per solution:

```
Summary: claude-large wins on 62/100, claude-small on 25/100, gemma-small on 13/100
```

**Tie-breaking**: when two solutions have the same metric value, both are counted as winners. The summary may sum to more than 100% in this case.

### 5.3 Missing Instance Handling

If a solution has status `"failed"` or `"timeout"` for an instance, it is displayed as `FAILED` or `TIMEOUT` in the comparison table and excluded from best-per-instance counting.

---

## 6. Export Formats

### 6.1 CSV Export (FR-BEN-007, ConOps §8.1)

One row per (solution, metric). Columns match ConOps §8.1:

```csv
benchmark_id,solution_id,solution_alias,run_id,problem,problem_version,llm,llm_model,train_dataset,eval_dataset,metric_name,mean,min,max,p10,p50,p90,std,gen_time_s,eval_time_s,instances_count,instances_solved
bench-20260310-170000,sol-20260310-143000,claude-small-v1.1,run-20260310-143000,scheduling-optimizer,v1.1,claude-opus,claude-opus-4-6,train-small,eval-benchmark,combined_score,0.87,0.62,0.95,0.71,0.88,0.93,0.08,8100,60,100,100
```

**Per-instance CSV** (`--per-instance`): one row per (solution, instance, metric).

```csv
benchmark_id,solution_id,solution_alias,instance_id,metric_name,value,status,compute_time_s
bench-20260310-170000,sol-20260310-143000,claude-small-v1.1,instance_001.json,combined_score,0.91,solved,1.2
```

### 6.2 JSON Export (FR-BEN-008, ConOps §8.2)

Aggregate JSON structure:

```json
{
  "benchmark_id": "bench-20260310-170000",
  "alias": "baseline-comparison",
  "eval_dataset": "eval-benchmark",
  "instance_count": 100,
  "created_at": "2026-03-10T17:00:00Z",
  "results": [
    {
      "solution_id": "sol-20260310-143000",
      "alias": "claude-small-v1.1",
      "run_id": "run-20260310-143000",
      "lineage": {
        "problem_version": "v1.1",
        "llm": "claude-opus",
        "llm_model": "claude-opus-4-6",
        "train_dataset": "train-small",
        "iterations": 200,
        "generation_time_s": 8100
      },
      "metrics": {
        "combined_score": {
          "mean": 0.87, "min": 0.62, "max": 0.95,
          "p10": 0.71, "p50": 0.88, "p90": 0.93,
          "std": 0.08, "count": 100
        }
      },
      "user_aggregates": null,
      "eval_time_s": 60,
      "instances_count": 100,
      "instances_solved": 100
    }
  ]
}
```

**Per-instance JSON** (`--per-instance`): same structure as spec-benchmark §2.2 JSON output.

### 6.3 Secret Stripping (FR-BEN-013)

Exported data must not contain:
- File system paths (dataset paths, program paths, snapshot paths)
- API keys or env var names
- PID or lock information

The export functions operate on Pydantic models that contain only the safe fields. File paths never enter the export data models — lineage uses symbolic names (dataset name, LLM name, problem version tag) rather than paths.

---

## 7. Pydantic Data Models

```python
from pydantic import BaseModel, ConfigDict
from datetime import datetime

# --- Reused from DES-006 ---
# InstanceResult, MetricAggregate (imported from models/eval.py)

class SolutionLineage(BaseModel):
    """Lineage information from the solution's parent run."""
    model_config = ConfigDict(frozen=True)

    problem_version: str
    llm: str
    llm_model: str
    train_dataset: str                      # maps to runs.dataset column
    iterations: int
    generation_time_s: float | None = None

class BenchmarkEntry(BaseModel):
    """One solution's results within a benchmark."""
    model_config = ConfigDict(frozen=True)

    solution_id: str
    alias: str | None = None
    run_id: str
    lineage: SolutionLineage
    metrics: dict[str, "MetricAggregate"]       # metric_name → aggregates
    user_aggregates: dict[str, float] | None = None  # From legacy evaluate() (D-006-g)
    eval_time_s: float | None = None
    instances_count: int
    instances_solved: int

class BenchmarkResult(BaseModel):
    """Full benchmark result returned to CLI."""
    benchmark_id: str
    alias: str | None = None
    dataset_name: str
    instance_count: int
    entries: list[BenchmarkEntry]
    failed_solutions: list[str] = []            # Solutions that failed evaluation
    created_at: datetime

class BenchmarkSummary(BaseModel):
    """Summary for benchmark list output."""
    model_config = ConfigDict(frozen=True)

    benchmark_id: str
    alias: str | None = None
    dataset_name: str
    solution_count: int
    created_at: datetime

class InstanceComparison(BaseModel):
    """Per-instance comparison across solutions."""
    instance_id: str
    solutions: dict[str, "InstanceSolutionResult"]  # alias_or_id → result

class InstanceSolutionResult(BaseModel):
    """One solution's result for a single instance."""
    model_config = ConfigDict(frozen=True)

    status: str                                 # "solved" | "failed" | "timeout"
    metrics: dict[str, float] = {}              # metric_name → value
    compute_time_s: float | None = None

class BenchmarkDetailResult(BaseModel):
    """Per-instance benchmark comparison result."""
    benchmark_id: str
    alias: str | None = None
    dataset_name: str
    instance_count: int
    solution_ids: list[str]                     # Ordered list of solution aliases/IDs
    instances: list[InstanceComparison]
    wins: dict[str, int] = {}                   # alias_or_id → win count (FR-BEN-015)
    metric: str | None = None                   # Metric used for win counting

class EvalStatus(BaseModel):
    """Status of eval reuse check for a solution."""
    status: str                                 # "reused" | "evaluated" | "failed"
    eval_id: str | None = None
    error: str | None = None
```

---

## 8. Storage

### 8.1 SQLite Only

Like `revolver eval`, benchmarks are stored **only in SQLite**. There are no manifest files or filesystem artifacts for benchmarks.

Tables used:
- `benchmarks` (DES-001 §3.9): one row per benchmark
- `benchmark_solutions` (DES-001 §3.10): one row per (benchmark, solution) — N rows per benchmark
- `eval_metadata` + `eval_instances` (DES-001 §3.7–3.8): read-only access to evaluation data

### 8.2 Schema Reference

The definitive schema is in DES-001 §3.9–3.10. For reference:

```sql
CREATE TABLE benchmarks (
    id              TEXT PRIMARY KEY,       -- "bench-YYYYMMDD-HHMMSS"
    alias           TEXT,
    dataset_name    TEXT NOT NULL REFERENCES datasets(name),
    created_at      TEXT NOT NULL           -- ISO 8601
);

CREATE INDEX idx_benchmarks_created ON benchmarks(created_at DESC);

CREATE TABLE benchmark_solutions (
    benchmark_id    TEXT NOT NULL REFERENCES benchmarks(id),
    solution_id     TEXT NOT NULL REFERENCES solutions(id),
    PRIMARY KEY (benchmark_id, solution_id)
);
```

### 8.3 What is NOT Stored

- **Aggregates**: computed at read time from raw `eval_instances` data (DD-01)
- **Per-instance data**: lives in `eval_instances` — benchmark only stores references (DD-02)
- **Lineage**: lives in `runs` — benchmark enriches at display/export time
- **Export files**: written to user-specified path, not managed by Revolver

---

## 9. Key Queries

### 9.1 Get benchmark by ID or latest

```sql
-- By ID
SELECT * FROM benchmarks WHERE id = :bench_id;

-- Latest
SELECT * FROM benchmarks ORDER BY created_at DESC LIMIT 1;
```

### 9.2 Get benchmark solutions with eval metadata

```sql
SELECT bs.solution_id, s.alias, s.run_id, s.rank, s.best_score,
       em.eval_id, em.instance_count, em.instances_solved,
       em.eval_time_s, em.user_aggregates
FROM benchmark_solutions bs
JOIN solutions s ON bs.solution_id = s.id
JOIN eval_metadata em ON s.id = em.solution_id AND em.dataset_name = :dataset
WHERE bs.benchmark_id = :bench_id
ORDER BY s.alias, s.id;
```

### 9.3 Get lineage for enrichment

```sql
SELECT r.id AS run_id, r.problem_version, r.llm, r.llm_model,
       r.dataset AS train_dataset, r.iterations, r.generation_time_s
FROM solutions s
JOIN runs r ON s.run_id = r.id
WHERE s.id = :solution_id;
```

### 9.4 Raw per-instance data for benchmark (aggregate computation)

```sql
SELECT ei.instance_id, ei.metric_name, ei.value, ei.status,
       ei.error_message, ei.compute_time_s
FROM eval_instances ei
JOIN eval_metadata em ON ei.eval_id = em.eval_id
WHERE em.solution_id = :solution_id AND em.dataset_name = :dataset_name
ORDER BY ei.instance_id, ei.metric_name;
```

### 9.5 Per-instance comparison (all solutions in benchmark)

Same as DES-001 §6.6 (DES-001 §6.7 is a simplified variant without `generation_time_s` and metric filter — this query subsumes both cases):

```sql
SELECT ei.instance_id, s.id AS solution_id, s.alias,
       ei.metric_name, ei.value, ei.status, ei.compute_time_s,
       r.generation_time_s
FROM benchmark_solutions bs
JOIN solutions s ON bs.solution_id = s.id
JOIN runs r ON s.run_id = r.id
JOIN eval_metadata em ON s.id = em.solution_id AND em.dataset_name = :dataset
JOIN eval_instances ei ON em.eval_id = ei.eval_id
WHERE bs.benchmark_id = :bench_id
  AND (:metric IS NULL OR ei.metric_name = :metric)
ORDER BY ei.instance_id, ei.metric_name, s.id;
```

### 9.6 List benchmarks with solution count

```sql
SELECT b.id, b.alias, b.dataset_name, b.created_at,
       COUNT(bs.solution_id) AS solution_count
FROM benchmarks b
LEFT JOIN benchmark_solutions bs ON b.id = bs.benchmark_id
GROUP BY b.id
ORDER BY b.created_at DESC;
```

### 9.7 Check if eval exists (for reuse logic)

```sql
SELECT eval_id FROM eval_metadata
WHERE solution_id = :solution_id AND dataset_name = :dataset_name
LIMIT 1;
```

---

## 10. Core Layer: Function Signatures

```python
# --- Benchmark ---
def run_benchmark(
    solution_ids_or_aliases: list[str],
    dataset_name: str,
    timeout_s: int = 300,
    alias: str | None = None,
    on_progress: Callable[[str, str], None] | None = None,
) -> BenchmarkResult:
    """
    Run a comparative benchmark of multiple solutions.

    For each solution:
        1. Check for existing eval results (reuse if available)
        2. If missing, trigger evaluation (FR-BEN-002/003)
        3. On eval failure, mark as failed and continue

    Computes aggregates per solution from raw per-instance data.
    Stores benchmark metadata and solution references in SQLite.

    Args:
        solution_ids_or_aliases: Solutions to compare (at least 1)
        dataset_name: Registered evaluation dataset
        timeout_s: Per-instance timeout for triggered evaluations
        alias: Optional benchmark alias
        on_progress: Callback(solution_id, status) for CLI progress

    Raises:
        BenchmarkError: if no solutions or dataset not found
        BenchmarkError: if evaluation fails for ALL solutions (exit code 4)
    """

def get_benchmark_results(
    benchmark_id: str | None = None,
    latest: bool = False,
    per_instance: bool = False,
    metric: str | None = None,
    sort_by: str | None = None,
) -> BenchmarkResult | BenchmarkDetailResult:
    """
    Retrieve stored benchmark results.

    If per_instance=True, returns per-instance comparison matrix
    with best-per-instance identification (FR-BEN-014/015).
    Otherwise, computes aggregates from raw data.

    Raises:
        BenchmarkNotFoundError: if no benchmark matches criteria
    """

def export_benchmark(
    benchmark_id: str | None = None,
    latest: bool = False,
    format: str = "csv",
    output_path: Path = ...,
    per_instance: bool = False,
) -> Path:
    """
    Export benchmark results to CSV or JSON.

    Aggregate export: one row/entry per (solution, metric).
    Per-instance export: one row/entry per (solution, instance, metric).

    Args:
        format: "csv" or "json"
        output_path: Destination file path
        per_instance: If True, export raw per-instance data (FR-BEN-016)

    Returns:
        Path to the written file.

    Raises:
        BenchmarkNotFoundError: if no benchmark matches
        ExportError: if output path not writable or invalid format
    """

def list_benchmarks() -> list[BenchmarkSummary]:
    """List all benchmarks with date, dataset, and solution count."""

# --- Internal ---
def _ensure_evaluated(
    solution_id: str,
    dataset_name: str,
    timeout_s: int,
) -> EvalStatus:
    """Check for existing eval results, trigger evaluation if missing."""

def _compute_solution_aggregates(
    solution_id: str,
    dataset_name: str,
) -> dict[str, MetricAggregate]:
    """Load raw per-instance data and compute aggregates for a solution."""

def _build_comparison_matrix(
    benchmark_id: str,
    dataset_name: str,
    metric_filter: str | None,
    sort_by: str | None,
) -> tuple[list[InstanceComparison], dict[str, int]]:
    """Build per-instance comparison matrix and win counts."""

def _build_lineage(solution_id: str) -> SolutionLineage:
    """Load lineage from solution's parent run."""

def generate_benchmark_id() -> str:
    """Generate bench-YYYYMMDD-HHMMSS with counter for collisions."""
```

---

## 11. CLI Layer: Typer Commands

Global options `--json`, `--verbose`, `--quiet` are defined in the root Typer app callback (`cli/__init__.py`, see [architecture.md §4.1](../architecture.md)) and inherited by all commands. They are not repeated here.

```python
import typer
from pathlib import Path

app = typer.Typer(name="benchmark", help="Compare solutions with benchmarks")

@app.callback(invoke_without_command=True)
def benchmark_default(
    ctx: typer.Context,
    solutions: list[str] = typer.Option(..., "--solutions", help="Solution IDs or aliases"),
    dataset: str = typer.Option(..., "--dataset", help="Evaluation dataset name"),
    timeout: int = typer.Option(300, "--timeout", help="Per-instance timeout (seconds)"),
    alias: str | None = typer.Option(None, "--alias", help="Benchmark alias"),
):
    """Run a comparative benchmark of multiple solutions."""
    ...

@app.command()
def results(
    benchmark_id: str | None = typer.Option(None, "--id", help="Benchmark ID"),
    latest: bool = typer.Option(False, "--latest", help="Show most recent benchmark"),
    metric: str | None = typer.Option(None, "--metric", help="Filter to single metric"),
    per_instance: bool = typer.Option(False, "--per-instance", help="Per-instance comparison"),
    sort_by: str | None = typer.Option(None, "--sort-by", help="Sort instances by solution metric"),
):
    """Display results of a previous benchmark."""
    ...
# Note: exits with code 1 if no benchmark found.
# Either --id or --latest must be provided.

@app.command()
def export(
    benchmark_id: str | None = typer.Option(None, "--id", help="Benchmark ID"),
    latest: bool = typer.Option(False, "--latest", help="Export most recent benchmark"),
    format: str = typer.Option(..., "--format", help="Export format: csv or json"),
    output: Path = typer.Option(..., "--output", help="Output file path"),
    per_instance: bool = typer.Option(False, "--per-instance", help="Export per-instance data"),
):
    """Export benchmark results to a file."""
    ...

@app.command(name="list")
def list_cmd():
    """List all benchmarks."""
    ...
```

---

## 12. Sequence Diagrams

### 12.1 `revolver benchmark --solutions A B C --dataset eval-bench`

```
User      CLI         Core            Eval            DB
 │         │           │               │               │
 │─bench──►│           │               │               │
 │         │─run_bench()►│             │               │
 │         │           │── validate solutions ────────►│
 │         │           │── get dataset ───────────────►│
 │         │           │── verify integrity             │
 │         │           │                                │
 │         │           │── for solution A:               │
 │         │           │   check eval exists ──────────►│
 │         │           │   ◄── exists ────────────────│
 │◄progress│◄─A reused─│   (reuse)                      │
 │         │           │                                │
 │         │           │── for solution B:               │
 │         │           │   check eval exists ──────────►│
 │         │           │   ◄── not found ─────────────│
 │         │           │   evaluate_solution()─►│       │
 │         │           │                        │──eval─►│
 │         │           │                  ◄─────│       │
 │◄progress│◄B evaluated│                       │       │
 │         │           │                                │
 │         │           │── for solution C:               │
 │         │           │   (same as A or B)             │
 │         │           │                                │
 │         │           │── load raw instances per sol ──►│
 │         │           │── compute_aggregates() per sol  │
 │         │           │── build lineage per sol ───────►│
 │         │           │── generate benchmark ID         │
 │         │           │── store benchmark ─────────────►│
 │◄─result─│◄Benchmark─│                                │
```

### 12.2 `revolver benchmark results --latest --per-instance --metric combined_score`

```
User      CLI         Core            DB
 │         │           │               │
 │─results►│           │               │
 │         │─get_bench()►│             │
 │         │           │── get latest benchmark ──────►│
 │         │           │── get benchmark solutions ───►│
 │         │           │── load per-instance data ────►│
 │         │           │   (for all solutions)          │
 │         │           │── build comparison matrix      │
 │         │           │── count wins per solution      │
 │◄─table──│◄─Detail ──│                               │
```

### 12.3 `revolver benchmark export --latest --format csv --output results.csv`

```
User      CLI         Core            DB        FS
 │         │           │               │         │
 │─export─►│           │               │         │
 │         │─export()──►│              │         │
 │         │           │── resolve benchmark ───►│
 │         │           │── load aggregates ─────►│
 │         │           │── build CSV rows         │
 │         │           │── write file ───────────────►│
 │◄─done───│◄─path ────│                         │
```

---

## 13. Design Decisions

### DD-01: No stored aggregates — compute at read time (consistent with DES-006 DD-01)

Benchmark tables (`benchmarks`, `benchmark_solutions`) store only metadata and membership. All aggregate statistics are computed at read time from raw `eval_instances` data using `compute_aggregates()` from DES-006.

**Rationale**:
- **Consistency**: same principle as `revolver eval` — single source of truth is raw per-instance data
- **No duplication**: aggregates are never stale or out of sync
- **Flexibility**: aggregate formulas can change without migration
- **Performance**: benchmark typically covers 2–10 solutions × 100–10,000 instances; computing aggregates for 100,000 total rows takes <100ms in Python

**Alternative considered**: store pre-computed aggregates in a `benchmark_results` table. Rejected: duplicates data that already exists in `eval_instances`, risks staleness, adds schema complexity.

### DD-02: Benchmark stores references, not data (single source of truth)

`benchmark_solutions` only records which solutions participate in a benchmark. It does not store eval results, aggregates, or lineage. This data is read from `eval_metadata`, `eval_instances`, and `runs` at display/export time.

**Rationale**:
- **FR-BEN-006**: "per-instance data is read from eval results (single source of truth)"
- **No staleness**: if a solution is re-evaluated (with `--force`), the benchmark automatically reflects the new results
- **Minimal schema**: two simple tables are sufficient

**Trade-off**: a re-evaluation (`revolver eval --force`) changes what a past benchmark displays. This is acceptable because re-evaluation is a deliberate, confirmed action (DES-006 D-006-a), and the benchmark should always reflect the current state of evaluation data.

### DD-03: CSV + JSON only, no Parquet (resolves AQ-05)

Benchmark exports support CSV and JSON only. Parquet is not supported in v1.

**Rationale**:
- **CSV is universal**: importable by Excel, pandas, R, any data tool
- **JSON is structured**: machine-readable, preserves nesting (lineage, per-metric aggregates)
- **Parquet adds a dependency**: `pyarrow` (~150MB) or `polars` for a marginal benefit
- **Trivial conversion**: users who need Parquet can convert from CSV with one pandas line (`pd.read_csv(...).to_parquet(...)`)
- **`--per-instance` export** (FR-BEN-016) provides the raw data needed for custom analysis (histograms, scatter plots, statistical tests) without requiring Parquet

**Future**: Parquet support can be added as an optional dependency if user demand emerges. The `export_benchmark()` function's `format` parameter is extensible.

### DD-04: Benchmark triggers eval with `force=True` (no double confirmation)

When benchmark needs to evaluate a solution (FR-BEN-003), it calls `evaluate_solution(force=True)`. This bypasses the re-evaluation confirmation (DES-006 D-006-a).

**Rationale**:
- Benchmark only triggers evaluation when **no results exist** (§3). `force=True` suppresses the interactive re-evaluation prompt (DES-006 D-006-a) — if a concurrent process deposited results between the existence check and this call, they will be silently replaced rather than triggering an interactive confirmation.
- The user already consented to evaluation by running `revolver benchmark`.
- Prompting for confirmation per solution would break the benchmark flow.

### DD-05: Sort by configurable metric, default `combined_score` mean (FR-BEN-010)

The comparative table is sorted by a configurable metric's mean value (descending). Default metric: `combined_score`.

**Rationale**:
- `combined_score` is the conventional metric name in OpenEvolve evaluators
- Sorting by mean provides a natural ranking
- `--metric` flag allows filtering to a single metric for focused comparison
- `--sort-by` on `results --per-instance` sorts instances by a specific solution's values for detailed analysis

### DD-06: User aggregates displayed alongside Revolver aggregates

When legacy evaluators (`evaluate()` mode) produce `user_aggregates`, benchmark displays them in a separate section, consistent with DES-006 DD-07.

**Display**:
- Main table: Revolver-computed aggregates (mean, min, max, p10, p50, p90, std)
- Secondary table: user aggregates when present, prefixed with `[user]`

**JSON export**: `user_aggregates` field is included per result entry (null when absent).

**Rationale**: user's custom aggregation (weighted average, min-based scoring) may differ from Revolver's standard statistics. Both perspectives are valuable for comparison.

### DD-07: Failed solutions included in benchmark metadata

When evaluation fails for one or more solutions, the benchmark is still created with the remaining solutions. Failed solution IDs are recorded in the `BenchmarkResult.failed_solutions` list and displayed as a warning.

**Rationale**:
- A partial benchmark is more useful than no benchmark
- The user can fix the failing solution and re-benchmark
- spec-benchmark §4: "Evaluation fails for one solution → mark as failed, continue"
- Only when **all** solutions fail does the benchmark abort (exit code 4)

**Note**: failed solutions are **not** inserted into `benchmark_solutions`. They are reported in the CLI output but not persisted in the DB.

---

## 14. Architecture Impact

### New modules

| Module | Layer | Purpose |
|---|---|---|
| `core/benchmark.py` | Domain | Benchmark orchestration, comparison, export |
| `cli/benchmark.py` | CLI | Typer commands for benchmark |
| `models/benchmark.py` | Models | `BenchmarkResult`, `BenchmarkEntry`, `BenchmarkSummary`, etc. |

### Existing modules impacted

| Module | Change |
|---|---|
| `infra/db.py` | Add `insert_benchmark()`, `insert_benchmark_solutions()`, `get_benchmark()`, `get_benchmark_solutions()`, `list_benchmarks()` |
| `core/eval.py` | No change — `evaluate_solution()` and `compute_aggregates()` already exist |
| `models/eval.py` | No change — `InstanceResult`, `MetricAggregate` already exist |

### DES-001 Schema — No Change Required

The `benchmarks` and `benchmark_solutions` tables (DES-001 §3.9–3.10) already contain all required fields. No schema modifications are needed.

### Cross-DES Dependencies

| Dependency | Direction | Details |
|---|---|---|
| DES-001 | DES-007 → DES-001 | Uses `benchmarks` + `benchmark_solutions` tables (DES-001 §3.9–3.10), reads `eval_metadata` + `eval_instances` (§3.7–3.8), reads `runs` (§3.5) + `solutions` (§3.6) |
| DES-006 | DES-007 → DES-006 | Calls `evaluate_solution()` for missing evals, imports `compute_aggregates()` for aggregate computation, reuses `InstanceResult` + `MetricAggregate` models |
| DES-005 | DES-007 → DES-005 | Reads run lineage (problem_version, llm, llm_model, dataset, iterations, generation_time_s) via `runs` table |
| DES-004 | DES-007 → DES-004 | Uses `verify_dataset_integrity()` |

---

## 15. Open Questions

- **BQ-01**: Should `benchmark results` support filtering by problem version or LLM? Currently, a benchmark is defined by its solution set — filtering within a benchmark would reduce the comparison. Could be useful for `benchmark list` filtering. Deferred to implementation.
- **BQ-02**: Should `benchmark export` support a `--metric` filter for CSV (export only one metric's aggregates)? Currently, all metrics are exported. Low-priority convenience feature.
