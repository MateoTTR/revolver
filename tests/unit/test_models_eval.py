"""L1 unit tests for revolver.models.eval — Eval Pydantic models (S5-01)."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from revolver.models.eval import (
    ComputeTimeSummary,
    EvalDetailResult,
    EvalMetadata,
    EvalResult,
    InstanceResult,
    MetricAggregate,
)

# ── InstanceResult ──────────────────────────────────────────────────────────


class TestInstanceResult:
    """Tests for InstanceResult model."""

    @pytest.mark.unit
    def test_creation_solved(self) -> None:
        """InstanceResult can be created with solved status and metrics."""
        result = InstanceResult(
            instance_id="instance_001.txt",
            status="solved",
            metrics={"score": 0.95, "time": 1.5},
            compute_time_s=2.3,
        )
        assert result.instance_id == "instance_001.txt"
        assert result.status == "solved"
        assert result.metrics == {"score": 0.95, "time": 1.5}
        assert result.error is None
        assert result.compute_time_s == 2.3

    @pytest.mark.unit
    def test_creation_failed(self) -> None:
        """InstanceResult can be created with failed status and error."""
        result = InstanceResult(
            instance_id="bad_instance.txt",
            status="failed",
            error="ZeroDivisionError: division by zero",
            compute_time_s=0.1,
        )
        assert result.status == "failed"
        assert result.metrics == {}
        assert result.error == "ZeroDivisionError: division by zero"

    @pytest.mark.unit
    def test_creation_timeout(self) -> None:
        """InstanceResult can be created with timeout status."""
        result = InstanceResult(
            instance_id="slow.txt",
            status="timeout",
        )
        assert result.status == "timeout"
        assert result.metrics == {}
        assert result.error is None
        assert result.compute_time_s is None

    @pytest.mark.unit
    def test_defaults(self) -> None:
        """InstanceResult applies defaults for optional fields."""
        result = InstanceResult(
            instance_id="inst",
            status="solved",
        )
        assert result.metrics == {}
        assert result.error is None
        assert result.compute_time_s is None

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """InstanceResult raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            InstanceResult(instance_id="inst")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_mutable(self) -> None:
        """InstanceResult is not frozen (allows mutation)."""
        result = InstanceResult(
            instance_id="inst",
            status="solved",
        )
        result.status = "failed"
        assert result.status == "failed"

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """InstanceResult serializes to dict and back."""
        result = InstanceResult(
            instance_id="inst",
            status="solved",
            metrics={"score": 0.8},
            compute_time_s=1.0,
        )
        data = result.model_dump()
        restored = InstanceResult.model_validate(data)
        assert restored == result


# ── MetricAggregate ─────────────────────────────────────────────────────────


class TestMetricAggregate:
    """Tests for MetricAggregate model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """MetricAggregate can be created with all fields."""
        agg = MetricAggregate(
            mean=0.85,
            min=0.60,
            max=0.99,
            p10=0.65,
            p50=0.85,
            p90=0.95,
            std=0.12,
            count=50,
        )
        assert agg.mean == 0.85
        assert agg.min == 0.60
        assert agg.max == 0.99
        assert agg.p10 == 0.65
        assert agg.p50 == 0.85
        assert agg.p90 == 0.95
        assert agg.std == 0.12
        assert agg.count == 50

    @pytest.mark.unit
    def test_frozen(self) -> None:
        """MetricAggregate is frozen (immutable)."""
        agg = MetricAggregate(
            mean=0.85,
            min=0.60,
            max=0.99,
            p10=0.65,
            p50=0.85,
            p90=0.95,
            std=0.12,
            count=50,
        )
        with pytest.raises(ValidationError):
            agg.mean = 0.90  # type: ignore[misc]

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """MetricAggregate raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            MetricAggregate(mean=0.85)  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """MetricAggregate serializes to dict and back."""
        agg = MetricAggregate(
            mean=0.85,
            min=0.60,
            max=0.99,
            p10=0.65,
            p50=0.85,
            p90=0.95,
            std=0.12,
            count=50,
        )
        data = agg.model_dump()
        restored = MetricAggregate.model_validate(data)
        assert restored == agg


# ── EvalMetadata ────────────────────────────────────────────────────────────


class TestEvalMetadata:
    """Tests for EvalMetadata model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """EvalMetadata can be created with all fields."""
        ts = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
        meta = EvalMetadata(
            eval_id="eval-20260315-100000",
            solution_id="sol-20260314-120000",
            dataset_name="eval-benchmark",
            instance_count=100,
            instances_solved=95,
            eval_time_s=45.2,
            evaluated_at=ts,
            user_aggregates={"combined_score": 0.72},
        )
        assert meta.eval_id == "eval-20260315-100000"
        assert meta.solution_id == "sol-20260314-120000"
        assert meta.dataset_name == "eval-benchmark"
        assert meta.instance_count == 100
        assert meta.instances_solved == 95
        assert meta.eval_time_s == 45.2
        assert meta.evaluated_at == ts
        assert meta.user_aggregates == {"combined_score": 0.72}

    @pytest.mark.unit
    def test_frozen(self) -> None:
        """EvalMetadata is frozen (immutable)."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=10,
            instances_solved=8,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        with pytest.raises(ValidationError):
            meta.eval_id = "eval-2"  # type: ignore[misc]

    @pytest.mark.unit
    def test_nullable_eval_time(self) -> None:
        """EvalMetadata accepts None eval_time_s."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=10,
            instances_solved=8,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        assert meta.eval_time_s is None

    @pytest.mark.unit
    def test_nullable_user_aggregates(self) -> None:
        """EvalMetadata accepts None user_aggregates (evaluate_instance mode)."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=10,
            instances_solved=8,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        assert meta.user_aggregates is None

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """EvalMetadata raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            EvalMetadata(eval_id="eval-1")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """EvalMetadata serializes to dict and back."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=10,
            instances_solved=8,
            eval_time_s=5.0,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
            user_aggregates={"score": 0.9},
        )
        data = meta.model_dump()
        restored = EvalMetadata.model_validate(data)
        assert restored == meta


# ── ComputeTimeSummary ──────────────────────────────────────────────────────


class TestComputeTimeSummary:
    """Tests for ComputeTimeSummary model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """ComputeTimeSummary can be created with all fields."""
        cts = ComputeTimeSummary(mean_s=1.5, max_s=5.0, total_s=150.0)
        assert cts.mean_s == 1.5
        assert cts.max_s == 5.0
        assert cts.total_s == 150.0

    @pytest.mark.unit
    def test_frozen(self) -> None:
        """ComputeTimeSummary is frozen (immutable)."""
        cts = ComputeTimeSummary(mean_s=1.5, max_s=5.0, total_s=150.0)
        with pytest.raises(ValidationError):
            cts.mean_s = 2.0  # type: ignore[misc]

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """ComputeTimeSummary raises ValidationError when required fields missing."""
        with pytest.raises(ValidationError):
            ComputeTimeSummary(mean_s=1.5)  # type: ignore[call-arg]


# ── EvalResult ──────────────────────────────────────────────────────────────


class TestEvalResult:
    """Tests for EvalResult model."""

    @pytest.mark.unit
    def test_creation_full(self) -> None:
        """EvalResult can be created with all fields."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=10,
            instances_solved=9,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        agg = MetricAggregate(
            mean=0.85,
            min=0.60,
            max=0.99,
            p10=0.65,
            p50=0.85,
            p90=0.95,
            std=0.12,
            count=9,
        )
        cts = ComputeTimeSummary(mean_s=1.0, max_s=3.0, total_s=9.0)
        result = EvalResult(
            metadata=meta,
            aggregates={"score": agg},
            user_aggregates={"combined_score": 0.72},
            compute_time=cts,
        )
        assert result.metadata == meta
        assert "score" in result.aggregates
        assert result.user_aggregates == {"combined_score": 0.72}
        assert result.compute_time == cts

    @pytest.mark.unit
    def test_nullable_user_aggregates(self) -> None:
        """EvalResult accepts None user_aggregates."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=10,
            instances_solved=9,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        result = EvalResult(
            metadata=meta,
            aggregates={},
        )
        assert result.user_aggregates is None
        assert result.compute_time is None

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """EvalResult serializes to dict and back."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=5,
            instances_solved=5,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        agg = MetricAggregate(
            mean=0.85,
            min=0.60,
            max=0.99,
            p10=0.65,
            p50=0.85,
            p90=0.95,
            std=0.12,
            count=5,
        )
        result = EvalResult(
            metadata=meta,
            aggregates={"score": agg},
        )
        data = result.model_dump()
        restored = EvalResult.model_validate(data)
        assert restored == result


# ── EvalDetailResult ────────────────────────────────────────────────────────


class TestEvalDetailResult:
    """Tests for EvalDetailResult model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """EvalDetailResult can be created with metadata and instances."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=2,
            instances_solved=1,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        instances = [
            InstanceResult(
                instance_id="inst-1",
                status="solved",
                metrics={"score": 0.9},
                compute_time_s=1.0,
            ),
            InstanceResult(
                instance_id="inst-2",
                status="failed",
                error="RuntimeError",
                compute_time_s=0.5,
            ),
        ]
        detail = EvalDetailResult(metadata=meta, instances=instances)
        assert detail.metadata == meta
        assert len(detail.instances) == 2
        assert detail.instances[0].status == "solved"
        assert detail.instances[1].status == "failed"

    @pytest.mark.unit
    def test_empty_instances(self) -> None:
        """EvalDetailResult can have an empty instances list."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=0,
            instances_solved=0,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        detail = EvalDetailResult(metadata=meta, instances=[])
        assert detail.instances == []

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """EvalDetailResult serializes to dict and back."""
        meta = EvalMetadata(
            eval_id="eval-1",
            solution_id="sol-1",
            dataset_name="ds",
            instance_count=1,
            instances_solved=1,
            evaluated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        instances = [
            InstanceResult(
                instance_id="inst-1",
                status="solved",
                metrics={"score": 0.9},
            ),
        ]
        detail = EvalDetailResult(metadata=meta, instances=instances)
        data = detail.model_dump()
        restored = EvalDetailResult.model_validate(data)
        assert restored == detail
