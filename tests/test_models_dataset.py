"""Tests for dataset Pydantic models (S3-01)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from revolver.models.dataset import (
    DatasetInfo,
    DatasetInstance,
    DatasetRegistration,
    DatasetSummary,
    IntegrityMismatch,
    IntegrityReport,
)


class TestDatasetInstance:
    """Tests for DatasetInstance model."""

    def test_creation(self) -> None:
        """DatasetInstance can be created with valid data."""
        inst = DatasetInstance(
            filename="instance_001.json",
            relative_path="instance_001.json",
            hash="sha256:abc123",
            size_bytes=1024,
        )
        assert inst.filename == "instance_001.json"
        assert inst.relative_path == "instance_001.json"
        assert inst.hash == "sha256:abc123"
        assert inst.size_bytes == 1024

    def test_frozen_rejects_mutation(self) -> None:
        """DatasetInstance is frozen and rejects attribute assignment."""
        inst = DatasetInstance(
            filename="a.json",
            relative_path="a.json",
            hash="sha256:abc",
            size_bytes=100,
        )
        with pytest.raises(ValidationError):
            inst.filename = "b.json"  # type: ignore[misc]

    def test_serialization_round_trip(self) -> None:
        """DatasetInstance serializes to JSON and back."""
        inst = DatasetInstance(
            filename="data.csv",
            relative_path="data.csv",
            hash="sha256:deadbeef",
            size_bytes=2048,
        )
        data = inst.model_dump()
        restored = DatasetInstance.model_validate(data)
        assert restored == inst


class TestDatasetRegistration:
    """Tests for DatasetRegistration model."""

    def test_valid_data(self) -> None:
        """DatasetRegistration validates with valid input."""
        now = datetime.now(UTC)
        reg = DatasetRegistration(
            name="train-small",
            path="/data/instances",
            storage="reference",
            split="train",
            instance_count=100,
            global_hash="sha256:aabbccdd",
            created_at=now,
            description="Small training set",
        )
        assert reg.name == "train-small"
        assert reg.storage == "reference"
        assert reg.split == "train"
        assert reg.instance_count == 100
        assert reg.description == "Small training set"

    def test_frozen_rejects_mutation(self) -> None:
        """DatasetRegistration is frozen and rejects attribute assignment."""
        now = datetime.now(UTC)
        reg = DatasetRegistration(
            name="test",
            path="/data",
            storage="reference",
            split="eval",
            instance_count=1,
            global_hash="sha256:abc",
            created_at=now,
        )
        with pytest.raises(ValidationError):
            reg.name = "other"  # type: ignore[misc]

    def test_defaults(self) -> None:
        """DatasetRegistration applies defaults for optional fields."""
        now = datetime.now(UTC)
        reg = DatasetRegistration(
            name="test",
            path="/data",
            storage="snapshot",
            split=None,
            instance_count=5,
            global_hash="sha256:abc",
            created_at=now,
        )
        assert reg.description is None
        assert reg.split is None

    def test_storage_literal_validation(self) -> None:
        """DatasetRegistration rejects invalid storage values."""
        now = datetime.now(UTC)
        with pytest.raises(ValidationError):
            DatasetRegistration(
                name="test",
                path="/data",
                storage="invalid",  # type: ignore[arg-type]
                split="train",
                instance_count=1,
                global_hash="sha256:abc",
                created_at=now,
            )

    def test_split_literal_validation(self) -> None:
        """DatasetRegistration rejects invalid split values."""
        now = datetime.now(UTC)
        with pytest.raises(ValidationError):
            DatasetRegistration(
                name="test",
                path="/data",
                storage="reference",
                split="test",  # type: ignore[arg-type]
                instance_count=1,
                global_hash="sha256:abc",
                created_at=now,
            )

    def test_split_none_is_valid(self) -> None:
        """DatasetRegistration accepts None split."""
        now = datetime.now(UTC)
        reg = DatasetRegistration(
            name="test",
            path="/data",
            storage="reference",
            split=None,
            instance_count=1,
            global_hash="sha256:abc",
            created_at=now,
        )
        assert reg.split is None

    def test_datetime_round_trip(self) -> None:
        """DatasetRegistration datetime serialises and deserialises correctly."""
        now = datetime.now(UTC)
        reg = DatasetRegistration(
            name="test",
            path="/data",
            storage="reference",
            split="train",
            instance_count=1,
            global_hash="sha256:abc",
            created_at=now,
        )
        data = reg.model_dump()
        restored = DatasetRegistration.model_validate(data)
        assert restored.created_at == now


class TestDatasetSummary:
    """Tests for DatasetSummary model."""

    def test_creation(self) -> None:
        """DatasetSummary can be created with valid data."""
        now = datetime.now(UTC)
        summary = DatasetSummary(
            name="eval-set",
            split="eval",
            instance_count=50,
            storage="snapshot",
            created_at=now,
        )
        assert summary.name == "eval-set"
        assert summary.split == "eval"
        assert summary.instance_count == 50
        assert summary.storage == "snapshot"

    def test_mutable(self) -> None:
        """DatasetSummary is not frozen (no ConfigDict frozen=True)."""
        now = datetime.now(UTC)
        summary = DatasetSummary(
            name="test",
            split="train",
            instance_count=10,
            storage="reference",
            created_at=now,
        )
        # Should not raise — DatasetSummary is mutable
        summary.name = "updated"
        assert summary.name == "updated"


class TestIntegrityMismatch:
    """Tests for IntegrityMismatch model."""

    def test_creation(self) -> None:
        """IntegrityMismatch can be created with valid data."""
        mm = IntegrityMismatch(
            filename="instance_003.json",
            expected_hash="sha256:aaa",
            actual_hash="sha256:bbb",
        )
        assert mm.filename == "instance_003.json"
        assert mm.expected_hash == "sha256:aaa"
        assert mm.actual_hash == "sha256:bbb"


class TestIntegrityReport:
    """Tests for IntegrityReport model."""

    def test_valid_report(self) -> None:
        """IntegrityReport validates with valid input."""
        now = datetime.now(UTC)
        report = IntegrityReport(
            is_valid=False,
            checked_at=now,
            mismatches=[
                IntegrityMismatch(
                    filename="a.json",
                    expected_hash="sha256:aaa",
                    actual_hash="sha256:bbb",
                ),
            ],
            missing=["b.json"],
            extra=["c.json"],
        )
        assert not report.is_valid
        assert len(report.mismatches) == 1
        assert report.missing == ["b.json"]
        assert report.extra == ["c.json"]

    def test_defaults(self) -> None:
        """IntegrityReport applies empty list defaults."""
        now = datetime.now(UTC)
        report = IntegrityReport(is_valid=True, checked_at=now)
        assert report.mismatches == []
        assert report.missing == []
        assert report.extra == []

    def test_is_valid_reflects_state(self) -> None:
        """IntegrityReport.is_valid accurately reflects mismatch state."""
        now = datetime.now(UTC)
        valid = IntegrityReport(is_valid=True, checked_at=now)
        assert valid.is_valid

        invalid = IntegrityReport(
            is_valid=False,
            checked_at=now,
            mismatches=[
                IntegrityMismatch(
                    filename="x.json",
                    expected_hash="sha256:old",
                    actual_hash="sha256:new",
                ),
            ],
        )
        assert not invalid.is_valid


class TestDatasetInfo:
    """Tests for DatasetInfo model."""

    def test_full_info(self) -> None:
        """DatasetInfo can hold full registration, instances, compat, and integrity."""
        now = datetime.now(UTC)
        reg = DatasetRegistration(
            name="train",
            path="/data/train",
            storage="reference",
            split="train",
            instance_count=2,
            global_hash="sha256:abc",
            created_at=now,
        )
        instances = [
            DatasetInstance(
                filename="a.json",
                relative_path="a.json",
                hash="sha256:aaa",
                size_bytes=100,
            ),
            DatasetInstance(
                filename="b.json",
                relative_path="b.json",
                hash="sha256:bbb",
                size_bytes=200,
            ),
        ]
        report = IntegrityReport(is_valid=True, checked_at=now)
        info = DatasetInfo(
            registration=reg,
            instances=instances,
            compat_versions=["v1.0", "v1.1"],
            integrity=report,
        )
        assert info.registration.name == "train"
        assert len(info.instances) == 2
        assert info.compat_versions == ["v1.0", "v1.1"]
        assert info.integrity is not None
        assert info.integrity.is_valid

    def test_defaults(self) -> None:
        """DatasetInfo applies defaults for optional fields."""
        now = datetime.now(UTC)
        reg = DatasetRegistration(
            name="test",
            path="/data",
            storage="reference",
            split="eval",
            instance_count=0,
            global_hash="sha256:abc",
            created_at=now,
        )
        info = DatasetInfo(registration=reg)
        assert info.instances == []
        assert info.compat_versions == []
        assert info.integrity is None

    def test_serializes_to_json(self) -> None:
        """DatasetInfo can be serialised to JSON and back."""
        now = datetime.now(UTC)
        reg = DatasetRegistration(
            name="test",
            path="/data",
            storage="snapshot",
            split="train",
            instance_count=1,
            global_hash="sha256:abc",
            created_at=now,
        )
        info = DatasetInfo(
            registration=reg,
            instances=[
                DatasetInstance(
                    filename="x.json",
                    relative_path="x.json",
                    hash="sha256:xyz",
                    size_bytes=512,
                ),
            ],
            compat_versions=["v1.0"],
        )
        json_str = info.model_dump_json()
        data = json.loads(json_str)
        assert data["registration"]["name"] == "test"
        assert len(data["instances"]) == 1

        restored = DatasetInfo.model_validate_json(json_str)
        assert restored.registration.name == "test"
        assert restored.compat_versions == ["v1.0"]
