"""Tests for problem models (S2-09)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from revolver.models.problem import (
    FileSnapshot,
    InstanceTestResult,
    ProblemVersion,
    TestResult,
)


class TestFileSnapshot:
    """Tests for FileSnapshot model."""

    def test_creation(self) -> None:
        """FileSnapshot can be created with valid data."""
        snap = FileSnapshot(name="evaluator.py", hash="sha256:abc123")
        assert snap.name == "evaluator.py"
        assert snap.hash == "sha256:abc123"

    def test_frozen_rejects_mutation(self) -> None:
        """FileSnapshot is frozen and rejects attribute assignment."""
        snap = FileSnapshot(name="evaluator.py", hash="sha256:abc123")
        with pytest.raises(ValidationError):
            snap.name = "other.py"  # type: ignore[misc]


class TestProblemVersion:
    """Tests for ProblemVersion model."""

    def test_valid_data(self) -> None:
        """ProblemVersion validates with valid input."""
        now = datetime.now(UTC)
        pv = ProblemVersion(
            tag="v1.0",
            hash="sha256:deadbeef",
            message="Initial version",
            created_at=now,
            files=[FileSnapshot(name="eval.py", hash="sha256:abc")],
        )
        assert pv.tag == "v1.0"
        assert pv.message == "Initial version"
        assert len(pv.files) == 1

    def test_frozen_rejects_mutation(self) -> None:
        """ProblemVersion is frozen and rejects attribute assignment."""
        now = datetime.now(UTC)
        pv = ProblemVersion(tag="v1.0", hash="sha256:abc", created_at=now)
        with pytest.raises(ValidationError):
            pv.tag = "v2.0"  # type: ignore[misc]

    def test_datetime_round_trip(self) -> None:
        """ProblemVersion datetime serialises and deserialises correctly."""
        now = datetime.now(UTC)
        pv = ProblemVersion(tag="v1", hash="sha256:abc", created_at=now)
        data = pv.model_dump()
        restored = ProblemVersion.model_validate(data)
        assert restored.created_at == now

    def test_defaults(self) -> None:
        """ProblemVersion defaults are applied."""
        now = datetime.now(UTC)
        pv = ProblemVersion(tag="v1", hash="sha256:abc", created_at=now)
        assert pv.message == ""
        assert pv.files == []


class TestInstanceTestResult:
    """Tests for InstanceTestResult model."""

    def test_creation(self) -> None:
        """InstanceTestResult can be created with valid data."""
        result = InstanceTestResult(
            instance_id="inst-001",
            status="pass",
            metrics={"combined_score": 0.5},
            time_s=1.2,
        )
        assert result.status == "pass"
        assert result.metrics is not None
        assert result.metrics["combined_score"] == 0.5

    def test_instance_test_result_frozen(self) -> None:
        """InstanceTestResult is frozen and rejects attribute assignment."""
        result = InstanceTestResult(instance_id="x", status="pass", time_s=1.0)
        with pytest.raises(ValidationError):
            result.status = "fail"  # type: ignore[misc]


class TestTestResult:
    """Tests for TestResult model."""

    def test_valid_data(self) -> None:
        """TestResult validates with valid input."""
        r = TestResult(
            mode="single",
            results=[
                InstanceTestResult(instance_id="inst-001", status="pass", time_s=0.5),
            ],
            total=1,
            passed=1,
            failed=0,
            mean_time_s=0.5,
            max_time_s=0.5,
        )
        assert r.total == 1

    def test_test_result_frozen(self) -> None:
        """TestResult is frozen and rejects attribute assignment."""
        result = TestResult(
            mode="single",
            results=[],
            total=0,
            passed=0,
            failed=0,
            mean_time_s=0.0,
            max_time_s=0.0,
        )
        with pytest.raises(ValidationError):
            result.mode = "dataset"  # type: ignore[misc]

    def test_serializes_to_json(self) -> None:
        """TestResult can be serialised to JSON and back."""
        r = TestResult(
            mode="dataset",
            results=[
                InstanceTestResult(
                    instance_id="inst-001",
                    status="pass",
                    metrics={"score": 1.0},
                    time_s=0.3,
                ),
                InstanceTestResult(
                    instance_id="inst-002",
                    status="fail",
                    time_s=0.7,
                    error="bad output",
                ),
            ],
            total=2,
            passed=1,
            failed=1,
            mean_time_s=0.5,
            max_time_s=0.7,
        )
        json_str = r.model_dump_json()
        data = json.loads(json_str)
        assert data["mode"] == "dataset"
        assert len(data["results"]) == 2

        restored = TestResult.model_validate_json(json_str)
        assert restored.total == 2
        assert restored.results[1].error == "bad output"
