"""Pydantic models for evaluation entities.

Covers the full evaluation lifecycle: per-instance results, aggregate
statistics, evaluation metadata, and composite result types returned
to the CLI layer.

Status literals use ``"solved"/"failed"/"timeout"`` (matching the SQLite
CHECK constraint and spec-eval output). This is intentionally different
from DES-003 ``InstanceTestResult`` which uses ``"pass"/"fail"/"timeout"``
for problem testing: ``"solved/failed"`` reflects whether the evaluator
produced a valid result, while ``"pass/fail"`` reflects whether a test
assertion passed.

Traceable to: DES-006 (Eval Loop) section 6, DES-001 section 3.7-3.8.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InstanceResult(BaseModel):
    """Result of evaluating a single instance.

    Attributes:
        instance_id: Identifier of the evaluated instance (filename or dir name).
        status: Outcome of the evaluation. One of ``"solved"``, ``"failed"``,
            or ``"timeout"``.
        metrics: Mapping of metric names to float values. Empty when the
            instance is failed or timed out.
        error: Error message when ``status != "solved"``, ``None`` otherwise.
        compute_time_s: Wall-clock time in seconds for this instance evaluation.
            ``None`` if timing is unavailable.
    """

    instance_id: str
    status: str  # "solved" | "failed" | "timeout"
    metrics: dict[str, float] = {}
    error: str | None = None
    compute_time_s: float | None = None


class MetricAggregate(BaseModel):
    """Aggregate statistics for a single metric across solved instances.

    Frozen: aggregate values are immutable once computed.

    Attributes:
        mean: Arithmetic mean of the metric values.
        min: Minimum value.
        max: Maximum value.
        p10: 10th percentile.
        p50: 50th percentile (median).
        p90: 90th percentile.
        std: Sample standard deviation (0.0 when count is 1).
        count: Number of solved instances contributing to the aggregate.
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

    Frozen: metadata is immutable once an evaluation completes.

    Attributes:
        eval_id: Unique evaluation identifier (e.g. ``"eval-20260310-160000"``).
        solution_id: ID of the evaluated solution.
        dataset_name: Name of the evaluation dataset.
        instance_count: Total number of instances evaluated.
        instances_solved: Number of instances with ``status="solved"``.
        eval_time_s: Total wall-clock time for the evaluation in seconds.
            ``None`` if timing is unavailable.
        evaluated_at: Timestamp when the evaluation was performed (ISO 8601).
        user_aggregates: Custom aggregates from legacy ``evaluate()`` global call
            (DES-006 D-006-g). ``None`` when using ``evaluate_instance()`` mode.
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
    """Compute time statistics across all evaluated instances.

    Frozen: summary values are immutable once computed.

    Attributes:
        mean_s: Mean compute time in seconds.
        max_s: Maximum compute time in seconds.
        total_s: Total (sum) compute time in seconds.
    """

    model_config = ConfigDict(frozen=True)

    mean_s: float
    max_s: float
    total_s: float


class EvalResult(BaseModel):
    """Full evaluation result returned to the CLI layer.

    JSON serialization produces nested ``compute_time`` matching spec-eval
    section 2.1. When ``user_aggregates`` is present (legacy ``evaluate()`` mode),
    the CLI displays both "Revolver aggregates" and "User aggregates" sections.

    Attributes:
        metadata: Evaluation session metadata.
        aggregates: Revolver-computed per-metric aggregates from raw
            per-instance data. Keys are metric names.
        user_aggregates: Custom aggregates from legacy ``evaluate()`` global
            call (DES-006 D-006-g). ``None`` for ``evaluate_instance()`` mode.
        compute_time: Compute time summary across all instances.
            ``None`` if no timing data is available.
    """

    metadata: EvalMetadata
    aggregates: dict[str, MetricAggregate]
    user_aggregates: dict[str, float] | None = None
    compute_time: ComputeTimeSummary | None = None


class EvalDetailResult(BaseModel):
    """Per-instance evaluation result for ``--per-instance`` output.

    Attributes:
        metadata: Evaluation session metadata.
        instances: List of per-instance results.
    """

    metadata: EvalMetadata
    instances: list[InstanceResult]
