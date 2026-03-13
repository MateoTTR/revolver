"""SHA-256 hashing utilities for files, directories, and snapshots.

All hashes are returned with a ``sha256:`` prefix (NFR-014).

Traceable to: DES-003 section 2.2.1, DES-004 section 3.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 8192


def file_hash(path: Path) -> str:
    """Compute SHA-256 of a file's contents.

    Args:
        path: Path to the file to hash.

    Returns:
        Hash string with ``sha256:`` prefix, e.g. ``sha256:a1b2c3...``.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def tree_hash(path: Path) -> str:
    """Compute SHA-256 of a directory tree.

    Algorithm:
        1. Recursively list all files (sorted by relative path).
        2. For each file, compute ``file_hash``.
        3. Concatenate ``"relative/path:hash\\n"`` (sorted).
        4. SHA-256 of the concatenation (UTF-8).

    Args:
        path: Path to the directory.

    Returns:
        Hash string with ``sha256:`` prefix.
    """
    entries: list[tuple[str, str]] = []
    for file_path in sorted(path.rglob("*")):
        if file_path.is_file():
            rel = str(file_path.relative_to(path))
            fh = file_hash(file_path)
            entries.append((rel, fh))

    content = "".join(f"{name}:{fhash}\n" for name, fhash in entries)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def global_hash(instance_hashes: list[tuple[str, str]]) -> str:
    """Compute SHA-256 of sorted instance hashes (dataset-level hash).

    Args:
        instance_hashes: List of ``(instance_id, hash)`` tuples.

    Returns:
        Hash string with ``sha256:`` prefix.
    """
    sorted_hashes = sorted(instance_hashes, key=lambda x: x[0])
    content = "".join(f"{iid}:{ihash}\n" for iid, ihash in sorted_hashes)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compute_snapshot_hash(files: list[tuple[str, str]]) -> str:
    """Compute SHA-256 of sorted file hashes (problem snapshot hash).

    This is used by ``revolver problem version`` to create a
    content-addressable identifier for a problem snapshot.

    Args:
        files: List of ``(filename, file_hash)`` tuples.

    Returns:
        Hash string with ``sha256:`` prefix.
    """
    sorted_files = sorted(files, key=lambda x: x[0])
    content = "".join(f"{name}:{fhash}\n" for name, fhash in sorted_files)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
