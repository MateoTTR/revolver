"""L1 unit tests for revolver.infra.hashing — SHA-256 hashing utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from revolver.infra.hashing import (
    compute_snapshot_hash,
    file_hash,
    global_hash,
    tree_hash,
)


@pytest.mark.unit
def test_sha256_used(tmp_path: Path) -> None:
    """file_hash must return a sha256-prefixed hex digest."""
    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    result = file_hash(f)
    assert result.startswith("sha256:"), f"Expected sha256: prefix, got {result}"
    # sha256 hex digest is 64 characters
    hex_part = result[len("sha256:") :]
    assert len(hex_part) == 64, f"Expected 64 hex chars, got {len(hex_part)}"


@pytest.mark.unit
def test_per_instance_hashes(tmp_path: Path) -> None:
    """file_hash must produce distinct hashes for distinct content."""
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("content A")
    f2.write_text("content B")
    h1 = file_hash(f1)
    h2 = file_hash(f2)
    assert h1 != h2, "Different content should produce different hashes"

    # Same content → same hash (deterministic)
    f3 = tmp_path / "c.txt"
    f3.write_text("content A")
    h3 = file_hash(f3)
    assert h1 == h3, "Same content should produce same hash"


@pytest.mark.unit
def test_subdirectory_tree_hash(tmp_path: Path) -> None:
    """tree_hash must hash directory contents recursively and deterministically."""
    # Create a directory with two files
    sub = tmp_path / "mydir"
    sub.mkdir()
    (sub / "file_a.txt").write_text("alpha")
    (sub / "file_b.txt").write_text("beta")

    h1 = tree_hash(sub)
    assert h1.startswith("sha256:")

    # Same content in different tmp dir → same hash
    sub2 = tmp_path / "mydir2"
    sub2.mkdir()
    (sub2 / "file_a.txt").write_text("alpha")
    (sub2 / "file_b.txt").write_text("beta")

    h2 = tree_hash(sub2)
    assert h1 == h2, "Same directory content should produce same tree hash"

    # Different content → different hash
    (sub2 / "file_b.txt").write_text("gamma")
    h3 = tree_hash(sub2)
    assert h1 != h3, "Different content should produce different tree hash"


@pytest.mark.unit
def test_snapshot_hash_sha256(tmp_path: Path) -> None:
    """compute_snapshot_hash must produce deterministic sha256 from sorted file list."""
    files = [
        ("evaluator.py", "sha256:aaa"),
        ("config.yaml", "sha256:bbb"),
        ("initial_program.py", "sha256:ccc"),
    ]
    h1 = compute_snapshot_hash(files)
    assert h1.startswith("sha256:")

    # Reorder input → same hash (sorted internally)
    files_reordered = [
        ("initial_program.py", "sha256:ccc"),
        ("config.yaml", "sha256:bbb"),
        ("evaluator.py", "sha256:aaa"),
    ]
    h2 = compute_snapshot_hash(files_reordered)
    assert h1 == h2, "Snapshot hash must be order-independent"


@pytest.mark.unit
def test_dataset_hash_computation(tmp_path: Path) -> None:
    """global_hash must produce deterministic sha256 from sorted instance hashes."""
    instances = [
        ("instance_003.json", "sha256:ccc"),
        ("instance_001.json", "sha256:aaa"),
        ("instance_002.json", "sha256:bbb"),
    ]
    h1 = global_hash(instances)
    assert h1.startswith("sha256:")

    # Reorder → same hash
    instances_reordered = [
        ("instance_001.json", "sha256:aaa"),
        ("instance_002.json", "sha256:bbb"),
        ("instance_003.json", "sha256:ccc"),
    ]
    h2 = global_hash(instances_reordered)
    assert h1 == h2, "Global hash must be order-independent"

    # Different data → different hash
    instances_different = [
        ("instance_001.json", "sha256:xxx"),
        ("instance_002.json", "sha256:bbb"),
        ("instance_003.json", "sha256:ccc"),
    ]
    h3 = global_hash(instances_different)
    assert h1 != h3, "Different instance hashes should produce different global hash"
