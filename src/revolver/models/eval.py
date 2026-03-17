"""Pydantic models for evaluation entities.

Defines the data structures for per-instance results, metric aggregates,
evaluation metadata, and composite result types returned to the CLI layer.

Status literals use ``"solved"/"failed"/"timeout"`` (matching the SQLite
CHECK constraint and spec-eval output). This differs from DES-003
``InstanceTestResult`` which uses ``"pass"/"fail"/"timeout"`` for problem
testing — the distinction is intentional.

Traceable to: DES-006 (Evaluation Loop) section 6, DES-001 sections 3.7-3.8.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InstanceResult(BaseModel):
    """Result of evaluating a single instance.

    Attributes:
        instance_id: Identifier of the evaluated instance.
        status: Outcome — ``"solved"``, ``"failed"``, or ``"timeout"``.
        metrics: Metric name/value pairs (empty dict if failed/timeout).
        error: Error message if the evaluation failed.
        compute_time_s: Wall-clock time in seconds for this instance.
    """

    instance_id: str
    status: str  # "solved" | "failed" | "timeout"
    metrics: dict[str, float] = {}
    error: str | None = None
    compute_time_s: float | None = None


class MetricAggregate(BaseModel):
    """Aggregate statistics for a single metric across solved instances.

    Attributes:
        mean: Arithmetic mean.
        min: Minimum value.
        max: Maximum value.
        p10: 10th percentile (linear interpolation).
        p50: 50th percentile (median, linear interpolation).
        p90: 90th percentile (linear interpolation).
        std: Sample standard deviation (0.0 if n=1).
        count: Number of solved instances with this metric.
    """

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
    """Evaluation session metadata stored in ``eval_metadata`` table.

    Attributes:
        eval_id: Unique evaluation identifier (``"eval-YYYYMMDD-HHMMSS"``).
        solution_id: ID of the evaluated solution.
        dataset_name: Name of the evaluation dataset.
        instance_count: Total number of instances evaluated.
        instances_solved: Number of instances with ``status="solved"``.
        eval_time_s: Total wall-clock evaluation time in seconds.
        evaluated_at: Timestamp of evaluation completion.
        user_aggregates: Legacy ``evaluate()`` global aggregation result (D-006-g).
            ``None`` for ``evaluate_instance()`` mode.
    """

    model_config = ConfigDict(frozen=True)

    eval_id: str
    solution_id: str
    dataset_name: str
    instance_count: int
    instances_solved: int
    eval_time_s: float | None = None
    evaluated_at: datetime
    user_aggregates: dict[str, float] | None = None


class ComputeTimeSummary(BaseModel):
    """Compute time statistics across all instances.

    Attributes:
        mean_s: Mean wall-clock time per instance.
        max_s: Maximum wall-clock time across instances.
        total_s: Sum of all instance compute times.
    """

    model_config = ConfigDict(frozen=True)

    mean_s: float
    max_s: float
    total_s: float


class EvalResult(BaseModel):
    """Full evaluation result returned to CLI.

    JSON serialization produces nested ``compute_time`` matching spec-eval section 2.1.
    When ``user_aggregates`` is present (legacy ``evaluate()`` mode), the CLI displays
    both "Revolver aggregates" and "User aggregates" sections.

    Attributes:
        metadata: Evaluation session metadata.
        aggregates: Revolver-computed per-metric statistics from raw per-instance data.
        user_aggregates: Raw result from legacy ``evaluate()`` global call (D-006-g).
        compute_time: Summary of per-instance compute times.
    """

    metadata: EvalMetadata
    aggregates: dict[str, MetricAggregate]
    user_aggregates: dict[str, float] | None = None
    compute_time: ComputeTimeSummary | None = None


class EvalDetailResult(BaseModel):
    """Per-instance evaluation result for ``--per-instance`` output.

    Attributes:
        metadata: Evaluation session metadata.
        instances: All per-instance results.
    """

    metadata: EvalMetadata
    instances: list[InstanceResult]
