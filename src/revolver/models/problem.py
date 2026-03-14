"""Pydantic models for problem versioning and test results.

All models are frozen (immutable) to support content-addressable
snapshots and reproducible traceability.

Traceable to: DES-003 (Problem Versioning), FR-PBM-001..004.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileSnapshot(BaseModel):
    """A single file within a problem version snapshot.

    Attributes:
        name: Filename relative to the problem directory (e.g. ``"evaluator.py"``).
        hash: Content hash with algorithm prefix (e.g. ``"sha256:a1b2c3d4..."``).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    hash: str


class ProblemVersion(BaseModel):
    """Immutable problem version metadata.

    Attributes:
        tag: Human-readable version tag (e.g. ``"v1.0"``).
        hash: Snapshot hash computed from all constituent file hashes.
        message: Optional commit-style message describing the version.
        created_at: Timestamp of version creation.
        files: List of file snapshots included in this version.
    """

    model_config = ConfigDict(frozen=True)

    tag: str
    hash: str
    message: str = ""
    created_at: datetime
    files: list[FileSnapshot] = []


class InstanceTestResult(BaseModel):
    """Result of evaluating a single instance.

    Attributes:
        instance_id: Identifier of the evaluated instance.
        status: Outcome — ``"pass"``, ``"fail"``, or ``"timeout"``.
        metrics: Metric name/value pairs returned by the evaluator.
        time_s: Wall-clock time in seconds.
        error: Error message if the evaluation failed.
        traceback: Full traceback string if available.
    """

    instance_id: str
    status: str
    metrics: dict[str, float] | None = None
    time_s: float
    error: str | None = None
    traceback: str | None = None


class TestResult(BaseModel):
    """Aggregate result of a problem test run.

    Attributes:
        mode: ``"single"`` for one-instance test, ``"dataset"`` for full dataset.
        results: Per-instance results.
        total: Total number of instances evaluated.
        passed: Number of instances that passed.
        failed: Number of instances that failed or timed out.
        mean_time_s: Mean wall-clock time across instances.
        max_time_s: Maximum wall-clock time across instances.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    mode: str
    results: list[InstanceTestResult]
    total: int
    passed: int
    failed: int
    mean_time_s: float
    max_time_s: float
