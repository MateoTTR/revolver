"""L1 unit tests for revolver.models.benchmark — Benchmark Pydantic models (S6-01)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from revolver.models.benchmark import (
    BenchmarkDetailResult,
    BenchmarkEntry,
    BenchmarkResult,
    BenchmarkSummary,
    EvalStatus,
    InstanceComparison,
    InstanceSolutionResult,
    SolutionLineage,
)
from revolver.models.eval import MetricAggregate

# ── Helpers ──────────────────────────────────────────────────────────────────

_TS = datetime(2026, 3, 10, 17, 0, 0, tzinfo=UTC)


def _make_lineage(**kwargs: object) -> SolutionLineage:
    defaults: dict[str, object] = {
        "problem_version": "v1.1",
        "llm": "claude-opus",
        "llm_model": "claude-opus-4-6",
        "train_dataset": "train-small",
        "iterations": 200,
    }
    defaults.update(kwargs)
    return SolutionLineage(**defaults)  # type: ignore[arg-type]


def _make_aggregate(**kwargs: object) -> MetricAggregate:
    defaults: dict[str, object] = {
        "mean": 0.87,
        "min": 0.62,
        "max": 0.95,
        "p10": 0.71,
        "p50": 0.88,
        "p90": 0.93,
        "std": 0.08,
        "count": 100,
    }
    defaults.update(kwargs)
    return MetricAggregate(**defaults)  # type: ignore[arg-type]


def _make_entry(**kwargs: object) -> BenchmarkEntry:
    defaults: dict[str, object] = {
        "solution_id": "sol-20260310-143000",
        "run_id": "run-20260310-143000",
        "lineage": _make_lineage(),
        "metrics": {"combined_score": _make_aggregate()},
        "instances_count": 100,
        "instances_solved": 100,
    }
    defaults.update(kwargs)
    return BenchmarkEntry(**defaults)  # type: ignore[arg-type]


# ── SolutionLineage ──────────────────────────────────────────────────────────


class TestSolutionLineage:
    """Tests for SolutionLineage model."""

    @pytest.mark.unit
    def test_creation_full(self) -> None:
        """SolutionLineage can be created with all fields."""
        lineage = SolutionLineage(
            problem_version="v1.1",
            llm="claude-opus",
            llm_model="claude-opus-4-6",
            train_dataset="train-small",
            iterations=200,
            generation_time_s=8100.0,
        )
        assert lineage.problem_version == "v1.1"
        assert lineage.llm == "claude-opus"
        assert lineage.llm_model == "claude-opus-4-6"
        assert lineage.train_dataset == "train-small"
        assert lineage.iterations == 200
        assert lineage.generation_time_s == 8100.0

    @pytest.mark.unit
    def test_generation_time_nullable(self) -> None:
        """SolutionLineage accepts None generation_time_s."""
        lineage = _make_lineage()
        assert lineage.generation_time_s is None

    @pytest.mark.unit
    def test_frozen(self) -> None:
        """SolutionLineage is frozen (immutable)."""
        lineage = _make_lineage()
        with pytest.raises(ValidationError):
            lineage.problem_version = "v2.0"  # type: ignore[misc]

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """SolutionLineage raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            SolutionLineage(problem_version="v1.0")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """SolutionLineage serializes to dict and back."""
        lineage = _make_lineage(generation_time_s=8100.0)
        data = lineage.model_dump()
        restored = SolutionLineage.model_validate(data)
        assert restored == lineage

    @pytest.mark.unit
    def test_no_path_fields(self) -> None:
        """SolutionLineage contains no file system path fields (FR-BEN-013)."""
        field_names = set(SolutionLineage.model_fields.keys())
        path_candidates = {f for f in field_names if "path" in f.lower()}
        assert path_candidates == set()


# ── BenchmarkEntry ───────────────────────────────────────────────────────────


class TestBenchmarkEntry:
    """Tests for BenchmarkEntry model."""

    @pytest.mark.unit
    def test_creation_full(self) -> None:
        """BenchmarkEntry can be created with all fields."""
        entry = BenchmarkEntry(
            solution_id="sol-20260310-143000",
            alias="claude-small-v1.1",
            run_id="run-20260310-143000",
            lineage=_make_lineage(generation_time_s=8100.0),
            metrics={"combined_score": _make_aggregate()},
            user_aggregates={"weighted_score": 0.90},
            eval_time_s=60.0,
            instances_count=100,
            instances_solved=100,
        )
        assert entry.solution_id == "sol-20260310-143000"
        assert entry.alias == "claude-small-v1.1"
        assert entry.run_id == "run-20260310-143000"
        assert entry.eval_time_s == 60.0
        assert entry.instances_count == 100
        assert entry.instances_solved == 100
        assert entry.user_aggregates == {"weighted_score": 0.90}

    @pytest.mark.unit
    def test_alias_nullable(self) -> None:
        """BenchmarkEntry accepts None alias."""
        entry = _make_entry()
        assert entry.alias is None

    @pytest.mark.unit
    def test_user_aggregates_nullable(self) -> None:
        """BenchmarkEntry accepts None user_aggregates (evaluate_instance mode)."""
        entry = _make_entry()
        assert entry.user_aggregates is None

    @pytest.mark.unit
    def test_eval_time_nullable(self) -> None:
        """BenchmarkEntry accepts None eval_time_s."""
        entry = _make_entry()
        assert entry.eval_time_s is None

    @pytest.mark.unit
    def test_frozen(self) -> None:
        """BenchmarkEntry is frozen (immutable)."""
        entry = _make_entry()
        with pytest.raises(ValidationError):
            entry.solution_id = "sol-other"  # type: ignore[misc]

    @pytest.mark.unit
    def test_metrics_contains_metric_aggregate(self) -> None:
        """BenchmarkEntry.metrics stores MetricAggregate values."""
        agg = _make_aggregate()
        entry = _make_entry(metrics={"combined_score": agg})
        assert entry.metrics["combined_score"] == agg

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """BenchmarkEntry raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            BenchmarkEntry(solution_id="sol-1")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """BenchmarkEntry serializes to dict and back."""
        entry = _make_entry(
            alias="my-solution",
            eval_time_s=30.0,
            user_aggregates={"score": 0.8},
        )
        data = entry.model_dump()
        restored = BenchmarkEntry.model_validate(data)
        assert restored == entry

    @pytest.mark.unit
    def test_no_path_fields(self) -> None:
        """BenchmarkEntry contains no file system path fields (FR-BEN-013)."""
        field_names = set(BenchmarkEntry.model_fields.keys())
        path_candidates = {f for f in field_names if "path" in f.lower()}
        assert path_candidates == set()


# ── BenchmarkResult ──────────────────────────────────────────────────────────


class TestBenchmarkResult:
    """Tests for BenchmarkResult model."""

    @pytest.mark.unit
    def test_creation_full(self) -> None:
        """BenchmarkResult can be created with all fields."""
        entry = _make_entry()
        result = BenchmarkResult(
            benchmark_id="bench-20260310-170000",
            alias="baseline-comparison",
            dataset_name="eval-benchmark",
            instance_count=100,
            entries=[entry],
            failed_solutions=["sol-bad"],
            created_at=_TS,
        )
        assert result.benchmark_id == "bench-20260310-170000"
        assert result.alias == "baseline-comparison"
        assert result.dataset_name == "eval-benchmark"
        assert result.instance_count == 100
        assert len(result.entries) == 1
        assert result.failed_solutions == ["sol-bad"]
        assert result.created_at == _TS

    @pytest.mark.unit
    def test_alias_nullable(self) -> None:
        """BenchmarkResult accepts None alias."""
        result = BenchmarkResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=10,
            entries=[],
            created_at=_TS,
        )
        assert result.alias is None

    @pytest.mark.unit
    def test_failed_solutions_default_empty(self) -> None:
        """BenchmarkResult defaults failed_solutions to empty list."""
        result = BenchmarkResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=10,
            entries=[],
            created_at=_TS,
        )
        assert result.failed_solutions == []

    @pytest.mark.unit
    def test_mutable(self) -> None:
        """BenchmarkResult is not frozen (allows mutation)."""
        result = BenchmarkResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=10,
            entries=[],
            created_at=_TS,
        )
        result.alias = "updated-alias"
        assert result.alias == "updated-alias"

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """BenchmarkResult raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            BenchmarkResult(benchmark_id="bench-1")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """BenchmarkResult serializes to dict and back."""
        entry = _make_entry()
        result = BenchmarkResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=5,
            entries=[entry],
            created_at=_TS,
        )
        data = result.model_dump()
        restored = BenchmarkResult.model_validate(data)
        assert restored == result

    @pytest.mark.unit
    def test_no_path_fields(self) -> None:
        """BenchmarkResult contains no file system path fields (FR-BEN-013)."""
        field_names = set(BenchmarkResult.model_fields.keys())
        path_candidates = {f for f in field_names if "path" in f.lower()}
        assert path_candidates == set()


# ── BenchmarkSummary ─────────────────────────────────────────────────────────


class TestBenchmarkSummary:
    """Tests for BenchmarkSummary model."""

    @pytest.mark.unit
    def test_creation_full(self) -> None:
        """BenchmarkSummary can be created with all fields."""
        summary = BenchmarkSummary(
            benchmark_id="bench-20260310-170000",
            alias="baseline",
            dataset_name="eval-benchmark",
            solution_count=3,
            created_at=_TS,
        )
        assert summary.benchmark_id == "bench-20260310-170000"
        assert summary.alias == "baseline"
        assert summary.dataset_name == "eval-benchmark"
        assert summary.solution_count == 3
        assert summary.created_at == _TS

    @pytest.mark.unit
    def test_alias_nullable(self) -> None:
        """BenchmarkSummary accepts None alias."""
        summary = BenchmarkSummary(
            benchmark_id="bench-1",
            dataset_name="ds",
            solution_count=2,
            created_at=_TS,
        )
        assert summary.alias is None

    @pytest.mark.unit
    def test_frozen(self) -> None:
        """BenchmarkSummary is frozen (immutable)."""
        summary = BenchmarkSummary(
            benchmark_id="bench-1",
            dataset_name="ds",
            solution_count=2,
            created_at=_TS,
        )
        with pytest.raises(ValidationError):
            summary.solution_count = 5  # type: ignore[misc]

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """BenchmarkSummary raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            BenchmarkSummary(benchmark_id="bench-1")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """BenchmarkSummary serializes to dict and back."""
        summary = BenchmarkSummary(
            benchmark_id="bench-1",
            alias="my-bench",
            dataset_name="ds",
            solution_count=2,
            created_at=_TS,
        )
        data = summary.model_dump()
        restored = BenchmarkSummary.model_validate(data)
        assert restored == summary


# ── InstanceSolutionResult ───────────────────────────────────────────────────


class TestInstanceSolutionResult:
    """Tests for InstanceSolutionResult model."""

    @pytest.mark.unit
    def test_creation_solved(self) -> None:
        """InstanceSolutionResult can be created with solved status and metrics."""
        result = InstanceSolutionResult(
            status="solved",
            metrics={"combined_score": 0.91, "time": 1.2},
            compute_time_s=1.2,
        )
        assert result.status == "solved"
        assert result.metrics == {"combined_score": 0.91, "time": 1.2}
        assert result.compute_time_s == 1.2

    @pytest.mark.unit
    def test_creation_failed(self) -> None:
        """InstanceSolutionResult can be created with failed status."""
        result = InstanceSolutionResult(status="failed")
        assert result.status == "failed"
        assert result.metrics == {}
        assert result.compute_time_s is None

    @pytest.mark.unit
    def test_creation_timeout(self) -> None:
        """InstanceSolutionResult can be created with timeout status."""
        result = InstanceSolutionResult(status="timeout", compute_time_s=300.0)
        assert result.status == "timeout"
        assert result.metrics == {}
        assert result.compute_time_s == 300.0

    @pytest.mark.unit
    def test_metrics_default_empty(self) -> None:
        """InstanceSolutionResult defaults metrics to empty dict."""
        result = InstanceSolutionResult(status="solved")
        assert result.metrics == {}

    @pytest.mark.unit
    def test_compute_time_nullable(self) -> None:
        """InstanceSolutionResult accepts None compute_time_s."""
        result = InstanceSolutionResult(status="solved")
        assert result.compute_time_s is None

    @pytest.mark.unit
    def test_frozen(self) -> None:
        """InstanceSolutionResult is frozen (immutable)."""
        result = InstanceSolutionResult(status="solved")
        with pytest.raises(ValidationError):
            result.status = "failed"  # type: ignore[misc]

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """InstanceSolutionResult raises ValidationError when status missing."""
        with pytest.raises(ValidationError):
            InstanceSolutionResult()  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """InstanceSolutionResult serializes to dict and back."""
        result = InstanceSolutionResult(
            status="solved",
            metrics={"score": 0.9},
            compute_time_s=1.5,
        )
        data = result.model_dump()
        restored = InstanceSolutionResult.model_validate(data)
        assert restored == result

    @pytest.mark.unit
    def test_invalid_status_raises(self) -> None:
        """InstanceSolutionResult raises ValidationError for invalid status."""
        with pytest.raises(ValidationError):
            InstanceSolutionResult(status="unknown")  # type: ignore[arg-type]

    @pytest.mark.unit
    def test_no_path_fields(self) -> None:
        """InstanceSolutionResult contains no file system path fields (FR-BEN-013)."""
        field_names = set(InstanceSolutionResult.model_fields.keys())
        path_candidates = {f for f in field_names if "path" in f.lower()}
        assert path_candidates == set()


# ── InstanceComparison ───────────────────────────────────────────────────────


class TestInstanceComparison:
    """Tests for InstanceComparison model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """InstanceComparison can be created with instance_id and solutions."""
        sol_a = InstanceSolutionResult(status="solved", metrics={"combined_score": 0.9})
        sol_b = InstanceSolutionResult(status="solved", metrics={"combined_score": 0.7})
        comparison = InstanceComparison(
            instance_id="instance_001.json",
            solutions={"sol-a": sol_a, "sol-b": sol_b},
        )
        assert comparison.instance_id == "instance_001.json"
        assert len(comparison.solutions) == 2
        assert comparison.solutions["sol-a"].metrics["combined_score"] == 0.9
        assert comparison.solutions["sol-b"].metrics["combined_score"] == 0.7

    @pytest.mark.unit
    def test_empty_solutions(self) -> None:
        """InstanceComparison accepts empty solutions dict."""
        comparison = InstanceComparison(
            instance_id="instance_001.json",
            solutions={},
        )
        assert comparison.solutions == {}

    @pytest.mark.unit
    def test_mutable(self) -> None:
        """InstanceComparison is not frozen (allows mutation)."""
        comparison = InstanceComparison(
            instance_id="inst-1",
            solutions={},
        )
        comparison.instance_id = "inst-2"
        assert comparison.instance_id == "inst-2"

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """InstanceComparison raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            InstanceComparison(instance_id="inst-1")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """InstanceComparison serializes to dict and back."""
        comparison = InstanceComparison(
            instance_id="inst-1",
            solutions={"sol-a": InstanceSolutionResult(status="solved", metrics={"score": 0.9})},
        )
        data = comparison.model_dump()
        restored = InstanceComparison.model_validate(data)
        assert restored == comparison

    @pytest.mark.unit
    def test_no_path_fields(self) -> None:
        """InstanceComparison contains no file system path fields (FR-BEN-013)."""
        field_names = set(InstanceComparison.model_fields.keys())
        path_candidates = {f for f in field_names if "path" in f.lower()}
        assert path_candidates == set()


# ── BenchmarkDetailResult ────────────────────────────────────────────────────


class TestBenchmarkDetailResult:
    """Tests for BenchmarkDetailResult model."""

    @pytest.mark.unit
    def test_creation_full(self) -> None:
        """BenchmarkDetailResult can be created with all fields."""
        comparison = InstanceComparison(
            instance_id="inst-1",
            solutions={
                "sol-a": InstanceSolutionResult(status="solved", metrics={"combined_score": 0.9})
            },
        )
        detail = BenchmarkDetailResult(
            benchmark_id="bench-20260310-170000",
            alias="baseline",
            dataset_name="eval-benchmark",
            instance_count=100,
            solution_ids=["sol-a", "sol-b"],
            instances=[comparison],
            wins={"sol-a": 62, "sol-b": 38},
            metric="combined_score",
        )
        assert detail.benchmark_id == "bench-20260310-170000"
        assert detail.alias == "baseline"
        assert detail.dataset_name == "eval-benchmark"
        assert detail.instance_count == 100
        assert detail.solution_ids == ["sol-a", "sol-b"]
        assert len(detail.instances) == 1
        assert detail.wins == {"sol-a": 62, "sol-b": 38}
        assert detail.metric == "combined_score"

    @pytest.mark.unit
    def test_alias_nullable(self) -> None:
        """BenchmarkDetailResult accepts None alias."""
        detail = BenchmarkDetailResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=10,
            solution_ids=[],
            instances=[],
        )
        assert detail.alias is None

    @pytest.mark.unit
    def test_wins_default_empty(self) -> None:
        """BenchmarkDetailResult defaults wins to empty dict."""
        detail = BenchmarkDetailResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=10,
            solution_ids=[],
            instances=[],
        )
        assert detail.wins == {}

    @pytest.mark.unit
    def test_metric_nullable(self) -> None:
        """BenchmarkDetailResult accepts None metric."""
        detail = BenchmarkDetailResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=10,
            solution_ids=[],
            instances=[],
        )
        assert detail.metric is None

    @pytest.mark.unit
    def test_mutable(self) -> None:
        """BenchmarkDetailResult is not frozen (allows mutation)."""
        detail = BenchmarkDetailResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=10,
            solution_ids=[],
            instances=[],
        )
        detail.metric = "combined_score"
        assert detail.metric == "combined_score"

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """BenchmarkDetailResult raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            BenchmarkDetailResult(benchmark_id="bench-1")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """BenchmarkDetailResult serializes to dict and back."""
        detail = BenchmarkDetailResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=2,
            solution_ids=["sol-a"],
            instances=[
                InstanceComparison(
                    instance_id="inst-1",
                    solutions={
                        "sol-a": InstanceSolutionResult(status="solved", metrics={"score": 0.85})
                    },
                )
            ],
            wins={"sol-a": 1},
            metric="score",
        )
        data = detail.model_dump()
        restored = BenchmarkDetailResult.model_validate(data)
        assert restored == detail

    @pytest.mark.unit
    def test_no_path_fields(self) -> None:
        """BenchmarkDetailResult contains no file system path fields (FR-BEN-013)."""
        field_names = set(BenchmarkDetailResult.model_fields.keys())
        path_candidates = {f for f in field_names if "path" in f.lower()}
        assert path_candidates == set()

    @pytest.mark.unit
    def test_nested_empty_solutions_round_trip(self) -> None:
        """BenchmarkDetailResult with empty InstanceComparison.solutions serializes correctly."""
        detail = BenchmarkDetailResult(
            benchmark_id="bench-1",
            dataset_name="ds",
            instance_count=1,
            solution_ids=[],
            instances=[
                InstanceComparison(
                    instance_id="inst-empty",
                    solutions={},
                )
            ],
        )
        data = detail.model_dump()
        restored = BenchmarkDetailResult.model_validate(data)
        assert restored == detail
        assert restored.instances[0].solutions == {}


# ── EvalStatus ───────────────────────────────────────────────────────────────


class TestEvalStatus:
    """Tests for EvalStatus model."""

    @pytest.mark.unit
    def test_creation_reused(self) -> None:
        """EvalStatus can be created with reused status."""
        status = EvalStatus(status="reused", eval_id="eval-20260310-160000")
        assert status.status == "reused"
        assert status.eval_id == "eval-20260310-160000"
        assert status.error is None

    @pytest.mark.unit
    def test_creation_evaluated(self) -> None:
        """EvalStatus can be created with evaluated status."""
        status = EvalStatus(status="evaluated", eval_id="eval-20260310-170000")
        assert status.status == "evaluated"
        assert status.eval_id == "eval-20260310-170000"
        assert status.error is None

    @pytest.mark.unit
    def test_creation_failed(self) -> None:
        """EvalStatus can be created with failed status and error."""
        status = EvalStatus(status="failed", error="EvalError: evaluator crashed")
        assert status.status == "failed"
        assert status.eval_id is None
        assert status.error == "EvalError: evaluator crashed"

    @pytest.mark.unit
    def test_eval_id_nullable(self) -> None:
        """EvalStatus accepts None eval_id."""
        status = EvalStatus(status="failed", error="crash")
        assert status.eval_id is None

    @pytest.mark.unit
    def test_error_nullable(self) -> None:
        """EvalStatus accepts None error."""
        status = EvalStatus(status="reused", eval_id="eval-1")
        assert status.error is None

    @pytest.mark.unit
    def test_mutable(self) -> None:
        """EvalStatus is not frozen (allows mutation)."""
        status = EvalStatus(status="reused")
        status.eval_id = "eval-1"
        assert status.eval_id == "eval-1"

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """EvalStatus raises ValidationError when status is missing."""
        with pytest.raises(ValidationError):
            EvalStatus()  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """EvalStatus serializes to dict and back."""
        status = EvalStatus(
            status="evaluated",
            eval_id="eval-1",
        )
        data = status.model_dump()
        restored = EvalStatus.model_validate(data)
        assert restored == status

    @pytest.mark.unit
    def test_invalid_status_raises(self) -> None:
        """EvalStatus raises ValidationError for invalid status."""
        with pytest.raises(ValidationError):
            EvalStatus(status="pending")  # type: ignore[arg-type]

    @pytest.mark.unit
    def test_no_path_fields(self) -> None:
        """EvalStatus contains no file system path fields (FR-BEN-013)."""
        field_names = set(EvalStatus.model_fields.keys())
        path_candidates = {f for f in field_names if "path" in f.lower()}
        assert path_candidates == set()
