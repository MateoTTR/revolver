"""Pydantic models for dataset registration and integrity verification.

Frozen (immutable) models for dataset registration metadata and instance
hashing. Mutable models for summary views and integrity reports.

Traceable to: DES-004 (Dataset Registration), FR-DAT-001..016.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DatasetInstance(BaseModel):
    """Hash record for a single instance (file or subdirectory) in a dataset.

    Attributes:
        filename: Filename or directory name (top-level entry).
        relative_path: Relative path within the dataset directory.
        hash: Content hash with algorithm prefix (e.g. ``"sha256:a1b2..."``).
        size_bytes: Size in bytes (file size or total directory size).
    """

    model_config = ConfigDict(frozen=True)

    filename: str
    relative_path: str
    hash: str
    size_bytes: int


class DatasetRegistration(BaseModel):
    """Full dataset registration record (immutable core metadata).

    Attributes:
        name: Unique user-chosen identifier (e.g. ``"train-small"``).
        path: Absolute path to the dataset directory.
        storage: ``"reference"`` (default) or ``"snapshot"``.
        split: ``"train"``, ``"eval"``, ``"both"`` (usable for training and
            evaluation), or ``None`` if unspecified.
        instance_count: Number of top-level entries in the dataset directory.
        global_hash: SHA-256 of sorted instance hashes (dataset-level hash).
        created_at: Timestamp of registration.
        description: Optional short description.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    storage: Literal["reference", "snapshot"]
    split: Literal["train", "eval", "both"] | None
    instance_count: int
    global_hash: str
    created_at: datetime
    description: str | None = None


class DatasetSummary(BaseModel):
    """Brief dataset info for list views.

    Attributes:
        name: Dataset identifier.
        split: ``"train"``, ``"eval"``, ``"both"``, or ``None``.
        instance_count: Number of instances.
        storage: ``"reference"`` or ``"snapshot"``.
        created_at: Timestamp of registration.
    """

    name: str
    split: Literal["train", "eval", "both"] | None
    instance_count: int
    storage: Literal["reference", "snapshot"]
    created_at: datetime


class IntegrityMismatch(BaseModel):
    """A single instance whose hash does not match the stored value.

    Attributes:
        filename: Instance filename or directory name.
        expected_hash: Hash stored at registration time.
        actual_hash: Hash recomputed from current file contents.
    """

    filename: str
    expected_hash: str
    actual_hash: str


class IntegrityReport(BaseModel):
    """Result of dataset integrity verification.

    Attributes:
        is_valid: ``True`` if all instances match and none are missing/extra.
        checked_at: Timestamp of the verification.
        mismatches: Instances whose content has changed.
        missing: Instance filenames that are no longer on disk.
        extra: New filenames found on disk that were not in the registration.
    """

    is_valid: bool
    checked_at: datetime
    mismatches: list[IntegrityMismatch] = []
    missing: list[str] = []
    extra: list[str] = []


class DatasetInfo(BaseModel):
    """Detailed dataset info with optional integrity report.

    Attributes:
        registration: Full registration metadata.
        instances: List of per-instance hash records.
        compat_versions: Problem version tags this dataset is compatible with.
        integrity: Integrity report, populated only when ``--verify`` is used.
    """

    registration: DatasetRegistration
    instances: list[DatasetInstance] = []
    compat_versions: list[str] = []
    integrity: IntegrityReport | None = None
