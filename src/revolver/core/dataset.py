"""Domain logic for dataset registration and integrity verification.

Implements ``revolver dataset`` commands: register, update, remove, list,
info, verify, and resolve_path.

Traceable to: DES-004 section 7, FR-DAT-001..016.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re

from revolver.core.exceptions import (
    DuplicateNameError,
    ProjectNotFoundError,
    RevolverError,
    ValidationError,
)
from revolver.infra.db import (
    delete_dataset,
    delete_dataset_compat,
    delete_dataset_compat_all,
    delete_dataset_instances,
    get_dataset,
    get_dataset_compat,
    get_dataset_instances,
    get_problem_version,
    get_project_db,
    get_solutions_by_dataset,
    insert_dataset,
    insert_dataset_compat,
    insert_dataset_instances,
    list_datasets as db_list_datasets,
    update_dataset_description,
)
from revolver.infra.hashing import file_hash, global_hash, tree_hash
from revolver.infra.store import (
    REVOLVER_DIR,
    ProjectNotFoundError as StoreProjectNotFoundError,
    create_dataset_snapshot,
    delete_dataset_store,
    find_project_root,
    get_snapshot_path,
    write_dataset_manifest,
)
from revolver.models.dataset import (
    DatasetInfo,
    DatasetInstance,
    DatasetRegistration,
    DatasetSummary,
    IntegrityMismatch,
    IntegrityReport,
)

# Regex for safe dataset names: alphanumeric start, then alphanum/dot/hyphen/underscore.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _validate_dataset_name(name: str) -> None:
    """Validate that a dataset name is safe for use as a path segment.

    Args:
        name: The dataset name to validate.

    Raises:
        ValidationError: If the name contains invalid characters.
    """
    if not _SAFE_NAME_RE.match(name):
        raise ValidationError(
            f"Invalid dataset name '{name}': "
            "must start with a letter or digit and contain only "
            "letters, digits, dots, hyphens, and underscores."
        )


def _resolve_project_root(project_root: Path | None) -> Path:
    """Resolve and return the project root directory.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The resolved project root path.

    Raises:
        ProjectNotFoundError: If no ``.revolver/`` directory is found
            in the hierarchy (caught by ``cli_error_boundary`` to show
            a user-friendly workspace message).
    """
    try:
        return find_project_root(project_root or Path.cwd())
    except StoreProjectNotFoundError as exc:
        raise ProjectNotFoundError(str(exc)) from exc


def _get_dir_size(path: Path) -> int:
    """Compute total size of all files in a directory recursively."""
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total


# ── register_dataset ─────────────────────────────────────────────────────────


def register_dataset(
    project_root: Path | None,
    name: str,
    path: Path,
    *,
    split: str | None = None,
    snapshot: bool = False,
    compatible_with: list[str] | None = None,
    description: str | None = None,
) -> DatasetRegistration:
    """Register a new dataset by computing instance hashes and storing metadata.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.
        name: Unique user-chosen identifier for the dataset.
        path: Path to the dataset directory.
        split: ``"train"`` or ``"eval"``, or ``None`` if unspecified.
        snapshot: If ``True``, copy files into ``.revolver/datasets/<name>/snapshot/``.
        compatible_with: List of problem version tags this dataset is compatible with.
        description: Optional short description.

    Returns:
        The created :class:`DatasetRegistration`.

    Raises:
        ValidationError: If the path does not exist or is not a directory.
        DuplicateNameError: If a dataset with *name* already exists.
        RevolverError: If a referenced problem version does not exist.
    """
    _validate_dataset_name(name)

    root = _resolve_project_root(project_root)
    resolved_path = path.resolve()

    # Validate path exists and is a directory
    if not resolved_path.exists():
        raise ValidationError(f"Dataset path does not exist: {resolved_path}")
    if not resolved_path.is_dir():
        raise ValidationError(f"Dataset path is not a directory: {resolved_path}")

    # Validate split value if provided
    if split is not None and split not in ("train", "eval"):
        raise ValidationError(f"Invalid split '{split}'. Must be 'train' or 'eval'.")

    # Open project DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # Check name uniqueness
        existing = get_dataset(conn, name)
        if existing is not None:
            raise DuplicateNameError(f"A dataset named '{name}' already exists")

        # Validate problem versions exist
        if compatible_with:
            for tag in compatible_with:
                pv = get_problem_version(conn, tag)
                if pv is None:
                    raise RevolverError(f"Problem version '{tag}' not found")

        # Enumerate instances: non-hidden top-level entries
        entries = sorted(p for p in resolved_path.iterdir() if not p.name.startswith("."))
        if not entries:
            raise ValidationError(f"No instances found in {resolved_path} (hidden files excluded)")

        # Compute per-instance hashes
        instances: list[DatasetInstance] = []
        hash_pairs: list[tuple[str, str]] = []
        for entry in entries:
            if entry.is_dir():
                h = tree_hash(entry)
                size = _get_dir_size(entry)
            else:
                h = file_hash(entry)
                size = entry.stat().st_size
            inst = DatasetInstance(
                filename=entry.name,
                relative_path=entry.name,
                hash=h,
                size_bytes=size,
            )
            instances.append(inst)
            hash_pairs.append((entry.name, h))

        # Compute global hash
        g_hash = global_hash(hash_pairs)

        # Determine storage mode
        storage: str = "reference"
        stored_path = str(resolved_path)
        if snapshot:
            create_dataset_snapshot(root, name, resolved_path)
            storage = "snapshot"

        now = datetime.now(UTC)

        # Build registration
        registration = DatasetRegistration(
            name=name,
            path=stored_path,
            storage=storage,  # type: ignore[arg-type]
            split=split,  # type: ignore[arg-type]
            instance_count=len(instances),
            global_hash=g_hash,
            created_at=now,
            description=description,
        )

        # Insert into DB atomically — defer commits to avoid partial state
        try:
            insert_dataset(conn, registration, commit=False)
            insert_dataset_instances(conn, name, instances, commit=False)
            if compatible_with:
                for tag in compatible_with:
                    insert_dataset_compat(conn, name, tag, commit=False)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        # Write manifest
        compat_list = compatible_with or []
        manifest_data = {
            "name": name,
            "path": stored_path,
            "storage": storage,
            "split": split,
            "instance_count": len(instances),
            "global_hash": g_hash,
            "registered_at": now.isoformat(),
            "description": description or "",
            "compatible_with": compat_list,
            "instances": [{"filename": inst.filename, "hash": inst.hash} for inst in instances],
        }
        write_dataset_manifest(root, name, manifest_data)

        return registration
    finally:
        conn.close()


# ── update_dataset ───────────────────────────────────────────────────────────


def update_dataset(
    project_root: Path | None,
    name: str,
    *,
    add_compat: list[str] | None = None,
    remove_compat: list[str] | None = None,
    description: str | None = None,
) -> DatasetRegistration:
    """Update mutable dataset metadata (compatibility list, description).

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.
        name: Dataset name.
        add_compat: Problem version tags to add to compatibility list.
        remove_compat: Problem version tags to remove from compatibility list.
        description: New description (replaces existing).

    Returns:
        The updated :class:`DatasetRegistration`.

    Raises:
        RevolverError: If the dataset or a referenced problem version is not found.
    """
    _validate_dataset_name(name)

    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        existing = get_dataset(conn, name)
        if existing is None:
            raise RevolverError(f"Dataset '{name}' not found")

        # Validate all problem versions exist before starting writes
        if add_compat:
            for tag in add_compat:
                pv = get_problem_version(conn, tag)
                if pv is None:
                    raise RevolverError(f"Problem version '{tag}' not found")

        # Apply all DB mutations atomically
        try:
            if add_compat:
                for tag in add_compat:
                    insert_dataset_compat(conn, name, tag, commit=False)

            if remove_compat:
                for tag in remove_compat:
                    delete_dataset_compat(conn, name, tag, commit=False)

            if description is not None:
                update_dataset_description(conn, name, description, commit=False)

            conn.commit()
        except Exception:
            conn.rollback()
            raise

        # Re-fetch updated registration
        updated = get_dataset(conn, name)
        if updated is None:
            raise RevolverError(f"Dataset '{name}' not found after update")

        # Update manifest
        compat_versions = get_dataset_compat(conn, name)
        instances_db = get_dataset_instances(conn, name)
        manifest_data = {
            "name": updated.name,
            "path": updated.path,
            "storage": updated.storage,
            "split": updated.split,
            "instance_count": updated.instance_count,
            "global_hash": updated.global_hash,
            "registered_at": updated.created_at.isoformat(),
            "description": updated.description or "",
            "compatible_with": compat_versions,
            "instances": [{"filename": inst.filename, "hash": inst.hash} for inst in instances_db],
        }
        write_dataset_manifest(root, name, manifest_data)

        return updated
    finally:
        conn.close()


# ── remove_dataset ───────────────────────────────────────────────────────────


def remove_dataset(
    project_root: Path | None,
    name: str,
    *,
    force: bool = False,
) -> None:
    """Unregister a dataset. Deletes DB entries, manifest, and snapshot files.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.
        name: Dataset name.
        force: If ``True``, remove even if solutions reference this dataset.

    Raises:
        RevolverError: If the dataset is not found or is referenced by solutions.
    """
    _validate_dataset_name(name)

    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        existing = get_dataset(conn, name)
        if existing is None:
            raise RevolverError(f"Dataset '{name}' not found")

        # Check for solution references
        solution_ids = get_solutions_by_dataset(conn, name)
        if solution_ids and not force:
            raise RevolverError(
                f"Dataset '{name}' is referenced by {len(solution_ids)} solutions: "
                f"{', '.join(solution_ids[:5])}. Use --force to remove anyway."
            )

        # Delete from DB (order matters for foreign key constraints)
        # When force-removing a dataset referenced by runs, we must
        # temporarily disable FK checks (DES-004: dangling references
        # in runs are acceptable — lineage hash preserves traceability).
        delete_dataset_compat_all(conn, name)
        delete_dataset_instances(conn, name)
        if force and solution_ids:
            conn.execute("PRAGMA foreign_keys=OFF")
            try:
                delete_dataset(conn, name)
            finally:
                conn.execute("PRAGMA foreign_keys=ON")
        else:
            delete_dataset(conn, name)

        # Delete store (manifest + snapshot directory)
        delete_dataset_store(root, name)
    finally:
        conn.close()


# ── list_datasets ────────────────────────────────────────────────────────────


def list_datasets(project_root: Path | None = None) -> list[DatasetSummary]:
    """List all registered datasets.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A list of :class:`DatasetSummary` instances sorted by name.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        return db_list_datasets(conn)
    finally:
        conn.close()


# ── get_dataset_info ─────────────────────────────────────────────────────────


def get_dataset_info(
    project_root: Path | None,
    name: str,
    *,
    verify: bool = False,
) -> DatasetInfo:
    """Get detailed dataset info with optional integrity verification.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.
        name: Dataset name.
        verify: If ``True``, recompute hashes and compare.

    Returns:
        A :class:`DatasetInfo` with registration, instances, and optional integrity report.

    Raises:
        RevolverError: If the dataset is not found.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        registration = get_dataset(conn, name)
        if registration is None:
            raise RevolverError(f"Dataset '{name}' not found")

        instances = get_dataset_instances(conn, name)
        compat_versions = get_dataset_compat(conn, name)

        integrity: IntegrityReport | None = None
        if verify:
            integrity = verify_dataset_integrity(project_root, name)

        return DatasetInfo(
            registration=registration,
            instances=instances,
            compat_versions=compat_versions,
            integrity=integrity,
        )
    finally:
        conn.close()


# ── verify_dataset_integrity ────────────────────────────────────────────────


def verify_dataset_integrity(
    project_root: Path | None,
    name: str,
) -> IntegrityReport:
    """Perform full integrity verification on a dataset.

    Recomputes all instance hashes and compares to stored values.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.
        name: Dataset name.

    Returns:
        An :class:`IntegrityReport` with mismatch, missing, and extra details.

    Raises:
        RevolverError: If the dataset is not found.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        registration = get_dataset(conn, name)
        if registration is None:
            raise RevolverError(f"Dataset '{name}' not found")

        stored_instances = get_dataset_instances(conn, name)
        stored_hashes = {inst.filename: inst.hash for inst in stored_instances}

        # Resolve dataset path
        dataset_path = resolve_dataset_path(project_root, name)

        # Re-enumerate and re-hash current files
        current_entries = sorted(p for p in dataset_path.iterdir() if not p.name.startswith("."))
        current_hashes: dict[str, str] = {}
        for entry in current_entries:
            h = tree_hash(entry) if entry.is_dir() else file_hash(entry)
            current_hashes[entry.name] = h

        # Compare
        mismatches: list[IntegrityMismatch] = []
        missing: list[str] = []
        extra: list[str] = []

        for filename, expected_hash in stored_hashes.items():
            if filename not in current_hashes:
                missing.append(filename)
            elif current_hashes[filename] != expected_hash:
                mismatches.append(
                    IntegrityMismatch(
                        filename=filename,
                        expected_hash=expected_hash,
                        actual_hash=current_hashes[filename],
                    )
                )

        for filename in current_hashes:
            if filename not in stored_hashes:
                extra.append(filename)

        is_valid = not mismatches and not missing and not extra

        return IntegrityReport(
            is_valid=is_valid,
            checked_at=datetime.now(UTC),
            mismatches=mismatches,
            missing=missing,
            extra=extra,
        )
    finally:
        conn.close()


# ── resolve_dataset_path ────────────────────────────────────────────────────


def resolve_dataset_path(
    project_root: Path | None,
    name: str,
) -> Path:
    """Resolve the effective path (original or snapshot) for a dataset.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.
        name: Dataset name.

    Returns:
        Path to the dataset files (snapshot path if storage=snapshot,
        otherwise the stored original path).

    Raises:
        RevolverError: If the dataset is not found.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        registration = get_dataset(conn, name)
        if registration is None:
            raise RevolverError(f"Dataset '{name}' not found")

        if registration.storage == "snapshot":
            return get_snapshot_path(root, name)
        return Path(registration.path)
    finally:
        conn.close()
