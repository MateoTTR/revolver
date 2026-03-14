"""Tests for dataset store operations (S3-03)."""

from __future__ import annotations

from pathlib import Path

import pytest

from revolver.infra.store import (
    create_dataset_snapshot,
    delete_dataset_store,
    get_snapshot_path,
    init_project_store,
    read_dataset_manifest,
    update_dataset_manifest,
    write_dataset_manifest,
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """Create a temporary project with initialized .revolver/ store."""
    init_project_store(tmp_path)
    return tmp_path


class TestWriteDatasetManifest:
    """Tests for write_dataset_manifest."""

    def test_write_creates_manifest(self, project: Path) -> None:
        """write_dataset_manifest creates the manifest YAML file."""
        data = {"name": "train-small", "global_hash": "sha256:abc"}
        write_dataset_manifest(project, "train-small", data)

        manifest_path = project / ".revolver" / "datasets" / "train-small" / "manifest.yaml"
        assert manifest_path.exists()

    def test_write_creates_dataset_directory(self, project: Path) -> None:
        """write_dataset_manifest creates the dataset subdirectory."""
        data = {"name": "test"}
        write_dataset_manifest(project, "my-dataset", data)

        dataset_dir = project / ".revolver" / "datasets" / "my-dataset"
        assert dataset_dir.is_dir()


class TestReadDatasetManifest:
    """Tests for read_dataset_manifest."""

    def test_read_round_trip(self, project: Path) -> None:
        """Write then read manifest produces identical data."""
        data = {
            "name": "train",
            "path": "/data/train",
            "global_hash": "sha256:aabbccdd",
            "instances": [
                {"filename": "a.json", "hash": "sha256:aaa"},
                {"filename": "b.json", "hash": "sha256:bbb"},
            ],
        }
        write_dataset_manifest(project, "train", data)
        loaded = read_dataset_manifest(project, "train")
        assert loaded == data

    def test_read_nonexistent_raises(self, project: Path) -> None:
        """Reading a non-existent manifest raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            read_dataset_manifest(project, "nonexistent")


class TestUpdateDatasetManifest:
    """Tests for update_dataset_manifest."""

    def test_update_overwrites(self, project: Path) -> None:
        """update_dataset_manifest replaces existing manifest content."""
        data_v1 = {"name": "test", "version": 1}
        data_v2 = {"name": "test", "version": 2, "extra": "field"}
        write_dataset_manifest(project, "test", data_v1)
        update_dataset_manifest(project, "test", data_v2)
        loaded = read_dataset_manifest(project, "test")
        assert loaded == data_v2
        assert loaded["version"] == 2
        assert loaded["extra"] == "field"


class TestDeleteDatasetStore:
    """Tests for delete_dataset_store."""

    def test_delete_removes_directory(self, project: Path) -> None:
        """delete_dataset_store removes the dataset directory tree."""
        data = {"name": "to-delete"}
        write_dataset_manifest(project, "to-delete", data)
        dataset_dir = project / ".revolver" / "datasets" / "to-delete"
        assert dataset_dir.exists()

        delete_dataset_store(project, "to-delete")
        assert not dataset_dir.exists()

    def test_delete_removes_snapshot_files(self, project: Path) -> None:
        """delete_dataset_store removes snapshot files too."""
        # Create manifest and snapshot
        data = {"name": "snap"}
        write_dataset_manifest(project, "snap", data)
        snapshot_dir = get_snapshot_path(project, "snap")
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / "file.json").write_text('{"key": "value"}')

        delete_dataset_store(project, "snap")
        assert not (project / ".revolver" / "datasets" / "snap").exists()

    def test_delete_nonexistent_no_error(self, project: Path) -> None:
        """Deleting a non-existent dataset store does not raise."""
        delete_dataset_store(project, "nonexistent")  # Should not raise


class TestCreateDatasetSnapshot:
    """Tests for create_dataset_snapshot."""

    def test_snapshot_copies_files(self, project: Path, tmp_path: Path) -> None:
        """create_dataset_snapshot copies files from source to snapshot dir."""
        # Create source directory with files
        source = tmp_path / "source_data"
        source.mkdir()
        (source / "a.json").write_text('{"id": 1}')
        (source / "b.json").write_text('{"id": 2}')
        (source / "c.json").write_text('{"id": 3}')

        snapshot_path = create_dataset_snapshot(project, "snap-ds", source)

        assert snapshot_path.is_dir()
        assert (snapshot_path / "a.json").exists()
        assert (snapshot_path / "b.json").exists()
        assert (snapshot_path / "c.json").exists()
        assert (snapshot_path / "a.json").read_text() == '{"id": 1}'

    def test_snapshot_copies_subdirectories(self, project: Path, tmp_path: Path) -> None:
        """create_dataset_snapshot copies subdirectories recursively."""
        source = tmp_path / "source_data"
        source.mkdir()
        sub = source / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested content")
        (source / "top.txt").write_text("top content")

        snapshot_path = create_dataset_snapshot(project, "nested-ds", source)

        assert (snapshot_path / "top.txt").exists()
        assert (snapshot_path / "subdir" / "nested.txt").exists()
        assert (snapshot_path / "subdir" / "nested.txt").read_text() == "nested content"

    def test_snapshot_excludes_hidden_files(self, project: Path, tmp_path: Path) -> None:
        """create_dataset_snapshot excludes files starting with dot."""
        source = tmp_path / "source_data"
        source.mkdir()
        (source / "visible.json").write_text("{}")
        (source / ".hidden").write_text("hidden")
        (source / ".DS_Store").write_text("store")

        snapshot_path = create_dataset_snapshot(project, "no-hidden", source)

        assert (snapshot_path / "visible.json").exists()
        assert not (snapshot_path / ".hidden").exists()
        assert not (snapshot_path / ".DS_Store").exists()

    def test_snapshot_returns_correct_path(self, project: Path, tmp_path: Path) -> None:
        """create_dataset_snapshot returns the snapshot directory path."""
        source = tmp_path / "source_data"
        source.mkdir()
        (source / "file.txt").write_text("content")

        result = create_dataset_snapshot(project, "path-check", source)
        expected = project / ".revolver" / "datasets" / "path-check" / "snapshot"
        assert result == expected


class TestGetSnapshotPath:
    """Tests for get_snapshot_path."""

    def test_returns_correct_path(self, project: Path) -> None:
        """get_snapshot_path returns the expected path."""
        result = get_snapshot_path(project, "my-dataset")
        expected = project / ".revolver" / "datasets" / "my-dataset" / "snapshot"
        assert result == expected

    def test_path_does_not_need_to_exist(self, project: Path) -> None:
        """get_snapshot_path returns a path even if it does not exist yet."""
        result = get_snapshot_path(project, "future-dataset")
        assert isinstance(result, Path)
        # Path should not exist yet
        assert not result.exists()
