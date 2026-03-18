"""Pydantic models for benchmark entities.

Covers the full benchmark lifecycle: solution lineage enrichment, per-solution
aggregate results, benchmark summary for list views, per-instance comparison
matrices, and eval reuse status.

Traceable to: DES-007 (Benchmark Design) §7, FR-BEN-001..016.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from revolver.models.eval import MetricAggregate


class SolutionLineage(BaseModel):
    """Lineage information from the solution's parent run.

    Frozen: lineage is immutable once enriched from the ``runs`` table.

    Attributes:
        problem_version: Problem version tag used in the generating run
            (e.g. ``"v1.1"``).
        llm: LLM registry name used (e.g. ``"claude-opus"``).
        llm_model: Full model identifier (e.g. ``"claude-opus-4-6"``).
        train_dataset: Dataset name used for training (maps to ``runs.dataset``
            column).
        iterations: Number of OpenEvolve iterations executed in the run.
        generation_time_s: Wall-clock generation time in seconds.
            ``None`` if timing is unavailable.
    """

    model_config = ConfigDict(frozen=True)

    problem_version: str
    llm: str
    llm_model: str
    train_dataset: str
    iterations: int
    generation_time_s: float | None = None


class BenchmarkEntry(BaseModel):
    """One solution's results within a benchmark.

    Frozen: entry values are immutable once computed from eval data.

    Attributes:
        solution_id: Unique solution identifier
            (e.g. ``"sol-20260310-143000"``).
        alias: Optional user-given alias for the solution.
        run_id: ID of the run that produced this solution.
        lineage: Lineage information from the solution's parent run.
        metrics: Per-metric aggregate statistics computed from raw
            per-instance data. Keys are metric names.
        user_aggregates: Custom aggregates from legacy ``evaluate()`` global
            call (DES-006 D-006-g). ``None`` when using ``evaluate_instance()``
            mode.
        eval_time_s: Total wall-clock time for the evaluation in seconds.
            ``None`` if timing is unavailable.
        instances_count: Total number of instances evaluated.
        instances_solved: Number of instances with ``status="solved"``.
    """

    model_config = ConfigDict(frozen=True)

    solution_id: str
    alias: str | None = None
    run_id: str
    lineage: SolutionLineage
    metrics: dict[str, MetricAggregate]
    user_aggregates: dict[str, float] | None = None
    eval_time_s: float | None = None
    instances_count: int
    instances_solved: int


class BenchmarkResult(BaseModel):
    """Full benchmark result returned to the CLI layer.

    Attributes:
        benchmark_id: Unique benchmark identifier
            (e.g. ``"bench-20260310-170000"``).
        alias: Optional user-given benchmark alias.
        dataset_name: Name of the evaluation dataset used.
        instance_count: Total number of instances in the dataset.
        entries: Per-solution results for all successfully evaluated solutions.
        failed_solutions: Solution IDs that failed evaluation and were excluded
            from the benchmark (DES-007 DD-07). Empty when all solutions
            evaluated successfully.
        created_at: Timestamp when the benchmark was created.
    """

    benchmark_id: str
    alias: str | None = None
    dataset_name: str
    instance_count: int
    entries: list[BenchmarkEntry]
    failed_solutions: list[str] = []
    created_at: datetime


class BenchmarkSummary(BaseModel):
    """Summary for benchmark list output.

    Frozen: summary values are immutable once read from the database.

    Attributes:
        benchmark_id: Unique benchmark identifier.
        alias: Optional user-given benchmark alias.
        dataset_name: Name of the evaluation dataset used.
        solution_count: Number of solutions included in the benchmark.
        created_at: Timestamp when the benchmark was created.
    """

    model_config = ConfigDict(frozen=True)

    benchmark_id: str
    alias: str | None = None
    dataset_name: str
    solution_count: int
    created_at: datetime


class InstanceSolutionResult(BaseModel):
    """One solution's result for a single instance.

    Frozen: per-instance result values are immutable once read from eval data.

    Attributes:
        status: Outcome of the evaluation for this instance. One of
            ``"solved"``, ``"failed"``, or ``"timeout"``.
        metrics: Metric values for this instance. Empty when status is not
            ``"solved"``.
        compute_time_s: Wall-clock time in seconds for this instance
            evaluation. ``None`` if timing is unavailable.
    """

    model_config = ConfigDict(frozen=True)

    status: str
    metrics: dict[str, float] = {}
    compute_time_s: float | None = None


class InstanceComparison(BaseModel):
    """Per-instance comparison across solutions.

    Attributes:
        instance_id: Identifier of the instance (filename or directory name).
        solutions: Mapping of solution alias or ID to its result for this
            instance.
    """

    instance_id: str
    solutions: dict[str, InstanceSolutionResult]


class BenchmarkDetailResult(BaseModel):
    """Per-instance benchmark comparison result.

    Returned by ``get_benchmark_results(per_instance=True)``. Contains the
    full comparison matrix for all instances and solutions, plus win counts
    for best-per-instance identification (FR-BEN-015).

    Attributes:
        benchmark_id: Unique benchmark identifier.
        alias: Optional user-given benchmark alias.
        dataset_name: Name of the evaluation dataset used.
        instance_count: Total number of instances in the dataset.
        solution_ids: Ordered list of solution aliases or IDs in the benchmark.
        instances: Per-instance comparison matrix. Each entry contains results
            from all solutions for that instance.
        wins: Win count per solution alias or ID (FR-BEN-015). A solution
            wins an instance when it achieves the best metric value. Ties
            are counted for all tied solutions.
        metric: Metric used for win counting. ``None`` defaults to
            ``"combined_score"``.
    """

    benchmark_id: str
    alias: str | None = None
    dataset_name: str
    instance_count: int
    solution_ids: list[str]
    instances: list[InstanceComparison]
    wins: dict[str, int] = {}
    metric: str | None = None


class EvalStatus(BaseModel):
    """Status of eval reuse check for a solution.

    Used internally by ``_ensure_evaluated()`` to report whether an existing
    eval was reused, a new evaluation was triggered, or the evaluation failed
    (DES-007 §3).

    Attributes:
        status: Outcome of the eval check. One of ``"reused"``,
            ``"evaluated"``, or ``"failed"``.
        eval_id: Evaluation ID (either reused or newly created).
            ``None`` when status is ``"failed"``.
        error: Error message when ``status == "failed"``. ``None`` otherwise.
    """

    status: str
    eval_id: str | None = None
    error: str | None = None
