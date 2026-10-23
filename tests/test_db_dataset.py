"""Tests for dataset DB CRUD (S3-02)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.core.exceptions import DuplicateNameError
from revolver.infra.db import (
    delete_dataset,
    delete_dataset_compat_all,
    delete_dataset_instances,
    get_dataset,
    get_dataset_compat,
    get_dataset_instances,
    get_project_db,
    get_solutions_by_dataset,
    insert_dataset,
    insert_dataset_compat,
    insert_dataset_instances,
    insert_problem_version,
    list_datasets,
    update_dataset_description,
)
from revolver.models.dataset import DatasetInstance, DatasetRegistration
from revolver.models.problem import ProblemVersion

pytestmark = pytest.mark.unit


@pytest.fixture()
def db_conn(tmp_path: Path):
    """Create a project DB for testing."""
    conn = get_project_db(tmp_path / "revolver.db")
    yield conn
    conn.close()


def _make_registration(
    name: str = "train-small",
    path: str = "/data/train",
    storage: str = "reference",
    split: str = "train",
    instance_count: int = 3,
    global_hash: str = "sha256:aabbccdd",
    description: str | None = None,
    created_at: datetime | None = None,
) -> DatasetRegistration:
    """Helper to create a DatasetRegistration with defaults."""
    return DatasetRegistration(
        name=name,
        path=path,
        storage=storage,  # type: ignore[arg-type]
        split=split,  # type: ignore[arg-type]
        instance_count=instance_count,
        global_hash=global_hash,
        created_at=created_at or datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        description=description,
    )


def _make_instances(count: int = 3) -> list[DatasetInstance]:
    """Helper to create a list of DatasetInstance objects."""
    return [
        DatasetInstance(
            filename=f"instance_{i:03d}.json",
            relative_path=f"instance_{i:03d}.json",
            hash=f"sha256:hash{i:03d}",
            size_bytes=100 * (i + 1),
        )
        for i in range(count)
    ]


class TestInsertDataset:
    """Tests for insert_dataset."""

    def test_insert_and_get_round_trip(self, db_conn) -> None:
        """Insert a dataset, then retrieve it by name."""
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        result = get_dataset(db_conn, "train-small")
        assert result is not None
        assert result.name == "train-small"
        assert result.path == "/data/train"
        assert result.storage == "reference"
        assert result.split == "train"
        assert result.instance_count == 3
        assert result.global_hash == "sha256:aabbccdd"

    def test_duplicate_name_raises(self, db_conn) -> None:
        """Inserting a duplicate name raises DuplicateNameError."""
        reg1 = _make_registration(name="dup")
        reg2 = _make_registration(name="dup", global_hash="sha256:other")
        insert_dataset(db_conn, reg1)
        with pytest.raises(DuplicateNameError, match=r"already exists"):
            insert_dataset(db_conn, reg2)

    def test_snapshot_storage(self, db_conn) -> None:
        """Insert a snapshot-mode dataset."""
        reg = _make_registration(storage="snapshot")
        insert_dataset(db_conn, reg)
        result = get_dataset(db_conn, "train-small")
        assert result is not None
        assert result.storage == "snapshot"

    def test_description_stored(self, db_conn) -> None:
        """Description is stored and retrieved."""
        reg = _make_registration(description="Test description")
        insert_dataset(db_conn, reg)
        result = get_dataset(db_conn, "train-small")
        assert result is not None
        assert result.description == "Test description"

    def test_empty_description_returns_none(self, db_conn) -> None:
        """Empty description is stored as empty string and returned as None."""
        reg = _make_registration(description=None)
        insert_dataset(db_conn, reg)
        result = get_dataset(db_conn, "train-small")
        assert result is not None
        # Empty string in DB maps to None in model
        assert result.description is None


class TestGetDataset:
    """Tests for get_dataset."""

    def test_nonexistent_returns_none(self, db_conn) -> None:
        """Getting a non-existent dataset returns None."""
        result = get_dataset(db_conn, "nonexistent")
        assert result is None


class TestInsertDatasetInstances:
    """Tests for insert_dataset_instances."""

    def test_batch_insert_and_retrieve(self, db_conn) -> None:
        """Batch insert instances, then retrieve them."""
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        instances = _make_instances(3)
        insert_dataset_instances(db_conn, "train-small", instances)
        result = get_dataset_instances(db_conn, "train-small")
        assert len(result) == 3
        assert result[0].filename == "instance_000.json"
        assert result[0].hash == "sha256:hash000"

    def test_batch_insert_large(self, db_conn) -> None:
        """Batch insert handles 1000+ instances."""
        reg = _make_registration(instance_count=1500)
        insert_dataset(db_conn, reg)
        instances = _make_instances(1500)
        insert_dataset_instances(db_conn, "train-small", instances)
        result = get_dataset_instances(db_conn, "train-small")
        assert len(result) == 1500

    def test_empty_list(self, db_conn) -> None:
        """Inserting empty instance list does not fail."""
        reg = _make_registration(instance_count=0)
        insert_dataset(db_conn, reg)
        insert_dataset_instances(db_conn, "train-small", [])
        result = get_dataset_instances(db_conn, "train-small")
        assert result == []


class TestGetDatasetInstances:
    """Tests for get_dataset_instances."""

    def test_sorted_by_instance_id(self, db_conn) -> None:
        """Instances are returned sorted by instance_id."""
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        # Insert in reverse order
        instances = [
            DatasetInstance(
                filename="c.json",
                relative_path="c.json",
                hash="sha256:ccc",
                size_bytes=300,
            ),
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
        insert_dataset_instances(db_conn, "train-small", instances)
        result = get_dataset_instances(db_conn, "train-small")
        filenames = [r.filename for r in result]
        assert filenames == ["a.json", "b.json", "c.json"]

    def test_empty_for_nonexistent_dataset(self, db_conn) -> None:
        """No instances for a non-existent dataset returns empty list."""
        result = get_dataset_instances(db_conn, "nonexistent")
        assert result == []


class TestDatasetCompat:
    """Tests for insert_dataset_compat / get_dataset_compat."""

    def test_insert_and_get(self, db_conn) -> None:
        """Insert compat entry and retrieve it."""
        # Need a problem version first (FK constraint)
        pv = ProblemVersion(
            tag="v1.0",
            hash="sha256:pvhash",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
        )
        insert_problem_version(db_conn, pv)
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        insert_dataset_compat(db_conn, "train-small", "v1.0")
        result = get_dataset_compat(db_conn, "train-small")
        assert result == ["v1.0"]

    def test_multiple_compat_versions(self, db_conn) -> None:
        """Multiple compat versions are returned sorted."""
        pv1 = ProblemVersion(
            tag="v1.0",
            hash="sha256:pv1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        pv2 = ProblemVersion(
            tag="v2.0",
            hash="sha256:pv2",
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        insert_problem_version(db_conn, pv1)
        insert_problem_version(db_conn, pv2)
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        insert_dataset_compat(db_conn, "train-small", "v2.0")
        insert_dataset_compat(db_conn, "train-small", "v1.0")
        result = get_dataset_compat(db_conn, "train-small")
        assert result == ["v1.0", "v2.0"]

    def test_empty_compat(self, db_conn) -> None:
        """No compat entries returns empty list."""
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        result = get_dataset_compat(db_conn, "train-small")
        assert result == []


class TestListDatasets:
    """Tests for list_datasets."""

    def test_list_multiple(self, db_conn) -> None:
        """List returns all datasets sorted by name."""
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 2, 1, tzinfo=UTC)
        insert_dataset(
            db_conn,
            _make_registration(name="beta", created_at=t2),
        )
        insert_dataset(
            db_conn,
            _make_registration(name="alpha", global_hash="sha256:other", created_at=t1),
        )
        result = list_datasets(db_conn)
        assert len(result) == 2
        assert result[0].name == "alpha"
        assert result[1].name == "beta"

    def test_list_empty(self, db_conn) -> None:
        """List returns empty list when no datasets registered."""
        result = list_datasets(db_conn)
        assert result == []

    def test_list_returns_summaries(self, db_conn) -> None:
        """List returns DatasetSummary objects with correct fields."""
        reg = _make_registration(split="eval", storage="snapshot")
        insert_dataset(db_conn, reg)
        result = list_datasets(db_conn)
        assert len(result) == 1
        summary = result[0]
        assert summary.split == "eval"
        assert summary.storage == "snapshot"
        assert summary.instance_count == 3


class TestUpdateDatasetDescription:
    """Tests for update_dataset_description."""

    def test_update_description(self, db_conn) -> None:
        """Update description of an existing dataset."""
        reg = _make_registration(description="Old desc")
        insert_dataset(db_conn, reg)
        update_dataset_description(db_conn, "train-small", "New desc")
        result = get_dataset(db_conn, "train-small")
        assert result is not None
        assert result.description == "New desc"


class TestDeleteDataset:
    """Tests for delete_dataset."""

    def test_delete_existing(self, db_conn) -> None:
        """Delete an existing dataset."""
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        delete_dataset(db_conn, "train-small")
        result = get_dataset(db_conn, "train-small")
        assert result is None

    def test_delete_nonexistent_no_error(self, db_conn) -> None:
        """Deleting a nonexistent dataset does not raise."""
        delete_dataset(db_conn, "nonexistent")  # Should not raise


class TestDeleteDatasetInstances:
    """Tests for delete_dataset_instances."""

    def test_delete_instances(self, db_conn) -> None:
        """Delete all instances for a dataset."""
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        insert_dataset_instances(db_conn, "train-small", _make_instances(3))
        delete_dataset_instances(db_conn, "train-small")
        result = get_dataset_instances(db_conn, "train-small")
        assert result == []


class TestDeleteDatasetCompatAll:
    """Tests for delete_dataset_compat_all."""

    def test_delete_all_compat(self, db_conn) -> None:
        """Delete all compat entries for a dataset."""
        pv = ProblemVersion(
            tag="v1.0",
            hash="sha256:pv",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
        )
        insert_problem_version(db_conn, pv)
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        insert_dataset_compat(db_conn, "train-small", "v1.0")
        delete_dataset_compat_all(db_conn, "train-small")
        result = get_dataset_compat(db_conn, "train-small")
        assert result == []


class TestGetSolutionsByDataset:
    """Tests for get_solutions_by_dataset."""

    def test_empty_when_no_solutions(self, db_conn) -> None:
        """Returns empty list when no solutions reference the dataset."""
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        result = get_solutions_by_dataset(db_conn, "train-small")
        assert result == []

    def test_returns_solution_ids(self, db_conn) -> None:
        """Returns solution IDs when solutions reference the dataset via runs."""
        # Set up: problem version, dataset, run, solution
        pv = ProblemVersion(
            tag="v1.0",
            hash="sha256:pv",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
        )
        insert_problem_version(db_conn, pv)
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        # Insert a run referencing the dataset
        now = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC).isoformat()
        db_conn.execute(
            """\
            INSERT INTO runs (
                id, problem_version, llm, dataset, iterations,
                problem_hash, dataset_hash, llm_model, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run-20260314-120000",
                "v1.0",
                "test-llm",
                "train-small",
                100,
                "sha256:ph",
                "sha256:dh",
                "test-model",
                "completed",
                now,
            ),
        )
        # Insert a solution referencing the run
        db_conn.execute(
            "INSERT INTO solutions (id, run_id, rank, best_score) VALUES (?, ?, ?, ?)",
            ("sol-20260314-120000", "run-20260314-120000", 1, 0.95),
        )
        db_conn.commit()

        result = get_solutions_by_dataset(db_conn, "train-small")
        assert result == ["sol-20260314-120000"]


class TestCascadingDelete:
    """Tests for cascading delete workflow (instances + compat + dataset)."""

    def test_full_delete_cascade(self, db_conn) -> None:
        """Delete compat, instances, then dataset in correct order."""
        pv = ProblemVersion(
            tag="v1.0",
            hash="sha256:pv",
            created_at=datetime(2026, 3, 14, tzinfo=UTC),
        )
        insert_problem_version(db_conn, pv)
        reg = _make_registration()
        insert_dataset(db_conn, reg)
        insert_dataset_instances(db_conn, "train-small", _make_instances(3))
        insert_dataset_compat(db_conn, "train-small", "v1.0")

        # Delete in order: compat -> instances -> dataset
        delete_dataset_compat_all(db_conn, "train-small")
        delete_dataset_instances(db_conn, "train-small")
        delete_dataset(db_conn, "train-small")

        assert get_dataset(db_conn, "train-small") is None
        assert get_dataset_instances(db_conn, "train-small") == []
        assert get_dataset_compat(db_conn, "train-small") == []
