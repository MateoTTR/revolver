"""Domain logic for problem testing and versioning.

Implements ``revolver problem test``, ``version``, ``versions``, and
``get_version`` — four domain functions per DES-003 section 5.

Traceable to: DES-003, FR-PRB-006..013.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shutil
import sys

from revolver.core.exceptions import (
    DuplicateNameError,
    RevolverError,
    ValidationError,
)
from revolver.infra.db import (
    get_problem_version,
    get_problem_version_by_hash,
    get_project_db,
    insert_problem_version,
    list_problem_versions as db_list_problem_versions,
)
from revolver.infra.evaluator_loader import load_evaluator
from revolver.infra.evaluator_runner import run_instance
from revolver.infra.hashing import compute_snapshot_hash, file_hash
from revolver.infra.store import (
    PROBLEM_DIR,
    REVOLVER_DIR,
    ProjectNotFoundError as StoreProjectNotFoundError,
    find_project_root,
    write_manifest,
)
from revolver.models.problem import (
    FileSnapshot,
    InstanceTestResult,
    ProblemVersion,
    TestResult,
)

# ── Required and optional problem files ──────────────────────────────────────

_REQUIRED_FILES = ("evaluator.py", "initial_program.py", "config.yaml")
_OPTIONAL_FILES = ("problem.md",)


def _resolve_project_root(project_root: Path | None) -> Path:
    """Resolve and return the project root directory.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The resolved project root path.

    Raises:
        RevolverError: If no project is found.
    """
    try:
        return find_project_root(project_root or Path.cwd())
    except StoreProjectNotFoundError as exc:
        raise RevolverError(str(exc)) from exc


def test_problem(
    instance: Path | None = None,
    dataset: Path | None = None,
    program: Path | None = None,
    evaluator: Path | None = None,
    timeout: int = 300,
) -> TestResult:
    """Test a problem evaluator against one instance or a dataset.

    Args:
        instance: Path to a single instance file (mutually exclusive with *dataset*).
        dataset: Path to a directory of instance files (mutually exclusive with *instance*).
        program: Path to the program to evaluate. Defaults to ``./initial_program.py``.
        evaluator: Path to the evaluator file. Defaults to ``./evaluator.py``.
        timeout: Maximum wall-clock seconds per instance evaluation.

    Returns:
        A :class:`TestResult` with per-instance results and summary statistics.

    Raises:
        ValidationError: If required files are missing or arguments are invalid.
    """
    # Resolve program path
    program_path = program if program is not None else Path("initial_program.py")
    if not program_path.is_file():
        raise ValidationError(f"Program file not found: {program_path}")

    # Resolve evaluator path
    evaluator_path = evaluator if evaluator is not None else Path("evaluator.py")
    if not evaluator_path.is_file():
        raise ValidationError(f"Evaluator file not found: {evaluator_path}")

    # Validate the evaluator module can be loaded
    load_evaluator(evaluator_path)

    # Build instance list
    instance_paths: list[Path] = []
    if instance is not None:
        if not instance.is_file():
            raise ValidationError(f"Instance file not found: {instance}")
        instance_paths = [instance]
        mode: str = "single"
    elif dataset is not None:
        if not dataset.is_dir():
            raise ValidationError(f"Dataset directory not found: {dataset}")
        instance_paths = sorted(p for p in dataset.iterdir() if p.is_file())
        if not instance_paths:
            raise ValidationError(f"No instance files found in {dataset}")
        mode = "dataset"
    else:
        raise ValidationError("Either --instance or --dataset must be provided")

    # Run each instance
    results: list[InstanceTestResult] = []
    for inst_path in instance_paths:
        result = run_instance(
            evaluator_path=evaluator_path,
            program_path=program_path,
            instance_path=inst_path,
            timeout_s=float(timeout),
        )
        results.append(result)

        # FR-PRB-013: warn if metrics present but no combined_score
        if result.metrics and "combined_score" not in result.metrics:
            sys.stderr.write(
                f"Warning: instance {result.instance_id} has metrics but no 'combined_score' key\n"
            )

    # Compute summary
    passed = sum(1 for r in results if r.status == "pass")
    failed = len(results) - passed
    times = [r.time_s for r in results]
    mean_time = sum(times) / len(times) if times else 0.0
    max_time = max(times) if times else 0.0

    return TestResult(
        mode=mode,  # type: ignore[arg-type]
        results=results,
        total=len(results),
        passed=passed,
        failed=failed,
        mean_time_s=mean_time,
        max_time_s=max_time,
    )


def create_version(
    tag: str,
    message: str = "",
    project_root: Path | None = None,
) -> ProblemVersion:
    """Create a new problem version snapshot.

    Copies required files into ``.revolver/problem/<tag>/``, computes
    content hashes, writes a manifest, and inserts a DB record.

    Args:
        tag: Human-readable version tag (e.g. ``"v1.0"``).
        message: Optional descriptive message for the version.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The created :class:`ProblemVersion` with file list.

    Raises:
        ValidationError: If required files are missing (FR-PRB-010).
        DuplicateNameError: If *tag* already exists (FR-PRB-008).
        DuplicateNameError: If content is identical to an existing version.
    """
    root = _resolve_project_root(project_root)

    # FR-PRB-010: check required files
    for fname in _REQUIRED_FILES:
        if not (root / fname).is_file():
            raise ValidationError(f"Required file missing: {fname}. Expected at {root / fname}")

    # Collect files to snapshot (required + optional if present)
    files_to_copy: list[str] = list(_REQUIRED_FILES)
    for fname in _OPTIONAL_FILES:
        if (root / fname).is_file():
            files_to_copy.append(fname)

    # Open project DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # FR-PRB-008: check tag uniqueness
        existing = get_problem_version(conn, tag)
        if existing is not None:
            raise DuplicateNameError(
                f"Problem version '{tag}' already exists. Choose a different tag."
            )

        # Create snapshot directory: .revolver/problem/<tag>/
        snapshot_dir = root / REVOLVER_DIR / PROBLEM_DIR / tag
        snapshot_dir.mkdir(parents=True, exist_ok=False)

        # FR-PRB-006: copy files to snapshot
        for fname in files_to_copy:
            shutil.copy2(root / fname, snapshot_dir / fname)

        # DES-003 DD-04: set snapshot files read-only
        for fname in files_to_copy:
            (snapshot_dir / fname).chmod(0o444)

        # Compute per-file SHA-256 on the SNAPSHOT copies
        file_snapshots: list[FileSnapshot] = []
        file_hash_pairs: list[tuple[str, str]] = []
        for fname in sorted(files_to_copy):
            fh = file_hash(snapshot_dir / fname)
            file_snapshots.append(FileSnapshot(name=fname, hash=fh))
            file_hash_pairs.append((fname, fh))

        # Compute snapshot hash
        snap_hash = compute_snapshot_hash(file_hash_pairs)

        # FR-PRB-008: check hash uniqueness (duplicate content detection)
        existing_by_hash = get_problem_version_by_hash(conn, snap_hash)
        if existing_by_hash is not None:
            # Clean up the snapshot directory we already created
            shutil.rmtree(snapshot_dir)
            raise DuplicateNameError(
                f"Content unchanged since version '{existing_by_hash.tag}'. "
                f"No new version created — problem files are identical."
            )

        # Write manifest.yaml
        now = datetime.now(UTC)
        manifest_data = {
            "tag": tag,
            "hash": snap_hash,
            "message": message,
            "created_at": now.isoformat(),
            "files": [{"name": fs.name, "hash": fs.hash} for fs in file_snapshots],
        }
        manifest_path = snapshot_dir / "manifest.yaml"
        write_manifest(manifest_path, manifest_data)
        manifest_path.chmod(0o444)

        # Build ProblemVersion
        pv = ProblemVersion(
            tag=tag,
            hash=snap_hash,
            message=message,
            created_at=now,
            files=file_snapshots,
        )

        # Insert into DB
        insert_problem_version(conn, pv)

        return pv
    finally:
        conn.close()


def list_versions(project_root: Path | None = None) -> list[ProblemVersion]:
    """List all problem versions in chronological order.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A list of :class:`ProblemVersion` instances, oldest first.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        return db_list_problem_versions(conn)
    finally:
        conn.close()


def get_version(tag: str, project_root: Path | None = None) -> ProblemVersion:
    """Retrieve a problem version by tag.

    Args:
        tag: The version tag to look up.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The :class:`ProblemVersion` for the given tag.

    Raises:
        RevolverError: If the tag does not exist.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        pv = get_problem_version(conn, tag)
        if pv is None:
            raise RevolverError(f"Problem version '{tag}' not found.")
        return pv
    finally:
        conn.close()
