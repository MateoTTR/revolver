"""L2 integration tests for ``revolver dataset`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner with a real
SQLite database and real filesystem (in ``tmp_path``).

Traceable to: val-integration-tests.md section 2.4.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.project import init_project
from revolver.infra.db import get_project_db
from revolver.infra.store import REVOLVER_DIR

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _get_all_output(result: object) -> str:
    """Combine stdout and stderr from a CliRunner result."""
    parts: list[str] = []
    for attr in ("stdout", "stderr", "output"):
        val = getattr(result, attr, None)
        if val:
            parts.append(val)
    return _strip_ansi("".join(parts))


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with init_project and return the root."""
    init_project(tmp_path, "test-project")
    return tmp_path


@pytest.fixture()
def dataset_dir(tmp_path: Path) -> Path:
    """Create a directory with 3 JSON instance files for dataset tests."""
    data_dir = tmp_path / "data" / "instances"
    data_dir.mkdir(parents=True)
    for i in range(1, 4):
        (data_dir / f"instance_{i:03d}.json").write_text(
            json.dumps({"id": i, "value": i * 10}),
            encoding="utf-8",
        )
    return data_dir


def _invoke_with_cwd(args: list[str], cwd: Path) -> object:
    """Invoke the CLI with a patched working directory.

    Patches Path.cwd() so that find_project_root auto-detects the project
    in the given directory.
    """
    with patch("pathlib.Path.cwd", return_value=cwd):
        return runner.invoke(app, args, catch_exceptions=False)


def _create_problem_version(project_root: Path, tag: str) -> None:
    """Create a problem version in the project (needed for --compatible-with)."""
    # Copy required files for problem version
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    shutil.copy2(fixtures_dir / "evaluator_simple.py", project_root / "evaluator.py")
    shutil.copy2(
        fixtures_dir / "initial_program_simple.py",
        project_root / "initial_program.py",
    )
    shutil.copy2(fixtures_dir / "config_simple.yaml", project_root / "config.yaml")

    from revolver.core.problem import create_version

    create_version(tag=tag, message=f"Version {tag}", project_root=project_root)


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_add_basic(tmp_project: Path, dataset_dir: Path) -> None:
    """Valid directory with 3 JSON files: DB entry, per-instance hashes, global hash, count=3."""
    result = _invoke_with_cwd(
        ["dataset", "add", "train-small", "--path", str(dataset_dir)],
        tmp_project,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "registered" in output.lower() or "train-small" in output

    # Verify DB entry
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT * FROM datasets WHERE name = ?", ("train-small",))
        row = cursor.fetchone()
        assert row is not None, "Dataset not found in DB"

        # Check instance count (column index 6)
        assert row[6] == 3

        # Check global hash exists (column index 5)
        assert row[5].startswith("sha256:")

        # Check per-instance hashes
        cursor = conn.execute(
            "SELECT instance_id, hash FROM dataset_instances WHERE dataset_name = ?",
            ("train-small",),
        )
        instances = cursor.fetchall()
        assert len(instances) == 3
        for _, inst_hash in instances:
            assert inst_hash.startswith("sha256:")
    finally:
        conn.close()


@pytest.mark.integration
def test_add_with_snapshot(tmp_project: Path, dataset_dir: Path) -> None:
    """--snapshot copies files into .revolver/datasets/<name>/snapshot/."""
    result = _invoke_with_cwd(
        ["dataset", "add", "eval-bench", "--path", str(dataset_dir), "--snapshot"],
        tmp_project,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify snapshot directory exists with copies
    snapshot_dir = tmp_project / REVOLVER_DIR / "datasets" / "eval-bench" / "snapshot"
    assert snapshot_dir.is_dir()
    snapshot_files = sorted(f.name for f in snapshot_dir.iterdir())
    assert len(snapshot_files) == 3

    # Verify DB storage column is "snapshot"
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT storage FROM datasets WHERE name = ?", ("eval-bench",))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "snapshot"
    finally:
        conn.close()


@pytest.mark.integration
def test_add_with_split(tmp_project: Path, dataset_dir: Path) -> None:
    """--split train stored in DB."""
    result = _invoke_with_cwd(
        ["dataset", "add", "ds-train", "--path", str(dataset_dir), "--split", "train"],
        tmp_project,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify split stored in DB
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT split FROM datasets WHERE name = ?", ("ds-train",))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "train"
    finally:
        conn.close()


@pytest.mark.integration
def test_add_with_compatible_version(tmp_project: Path, dataset_dir: Path) -> None:
    """--compatible-with v1.0 creates compat entry (requires problem version v1.0)."""
    # Create problem version v1.0 first
    _create_problem_version(tmp_project, "v1.0")

    result = _invoke_with_cwd(
        [
            "dataset",
            "add",
            "ds-compat",
            "--path",
            str(dataset_dir),
            "--compatible-with",
            "v1.0",
        ],
        tmp_project,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify compat entry in DB
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT problem_version FROM dataset_compat WHERE dataset_name = ?",
            ("ds-compat",),
        )
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "v1.0"
    finally:
        conn.close()


@pytest.mark.integration
def test_add_nonexistent_path(tmp_project: Path) -> None:
    """Non-existent path results in exit code 1."""
    result = _invoke_with_cwd(
        ["dataset", "add", "bad-ds", "--path", "/nonexistent/path/data"],
        tmp_project,
    )

    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"


@pytest.mark.integration
def test_add_duplicate_name_fails(tmp_project: Path, dataset_dir: Path) -> None:
    """Duplicate name results in exit code 1."""
    # First add
    result1 = _invoke_with_cwd(
        ["dataset", "add", "dup-ds", "--path", str(dataset_dir)],
        tmp_project,
    )
    assert result1.exit_code == 0

    # Second add with same name
    result2 = _invoke_with_cwd(
        ["dataset", "add", "dup-ds", "--path", str(dataset_dir)],
        tmp_project,
    )
    assert result2.exit_code == 1, f"Expected exit 1, got {result2.exit_code}"


@pytest.mark.integration
def test_list_after_adds(tmp_project: Path, dataset_dir: Path) -> None:
    """After 2 adds, both listed."""
    _invoke_with_cwd(
        ["dataset", "add", "ds-alpha", "--path", str(dataset_dir)],
        tmp_project,
    )

    # Create a second dataset dir with different files
    data_dir2 = dataset_dir.parent / "instances2"
    data_dir2.mkdir(parents=True)
    for i in range(1, 3):
        (data_dir2 / f"item_{i}.json").write_text(
            json.dumps({"id": i}),
            encoding="utf-8",
        )

    _invoke_with_cwd(
        ["dataset", "add", "ds-beta", "--path", str(data_dir2)],
        tmp_project,
    )

    result = _invoke_with_cwd(["dataset", "list"], tmp_project)
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "ds-alpha" in output
    assert "ds-beta" in output


@pytest.mark.integration
def test_info_basic(tmp_project: Path, dataset_dir: Path) -> None:
    """Shows dataset details: name, hash, instances."""
    _invoke_with_cwd(
        ["dataset", "add", "ds-info", "--path", str(dataset_dir)],
        tmp_project,
    )

    result = _invoke_with_cwd(["dataset", "info", "ds-info"], tmp_project)
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "ds-info" in output
    assert "sha256:" in output


@pytest.mark.integration
def test_info_verify_recomputes_hash(tmp_project: Path, dataset_dir: Path) -> None:
    """Modify a file, --verify detects mismatch."""
    _invoke_with_cwd(
        ["dataset", "add", "ds-verify", "--path", str(dataset_dir)],
        tmp_project,
    )

    # Modify one of the instance files
    modified_file = dataset_dir / "instance_001.json"
    modified_file.write_text(
        json.dumps({"id": 1, "value": 999, "modified": True}),
        encoding="utf-8",
    )

    result = _invoke_with_cwd(
        ["--json", "dataset", "info", "ds-verify", "--verify"],
        tmp_project,
    )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Parse JSON output to check integrity report (use result.output to avoid duplication)
    data = json.loads(result.output)
    assert data["integrity"] is not None
    assert data["integrity"]["is_valid"] is False
    assert len(data["integrity"]["mismatches"]) >= 1


@pytest.mark.integration
def test_update_compat_versions(tmp_project: Path, dataset_dir: Path) -> None:
    """Add compat version via update command."""
    # Create problem version first
    _create_problem_version(tmp_project, "v2.0")

    # Register dataset without compat
    _invoke_with_cwd(
        ["dataset", "add", "ds-update", "--path", str(dataset_dir)],
        tmp_project,
    )

    # Update to add compat version
    result = _invoke_with_cwd(
        ["dataset", "update", "ds-update", "--add-compatible-with", "v2.0"],
        tmp_project,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify compat entry in DB
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT problem_version FROM dataset_compat WHERE dataset_name = ?",
            ("ds-update",),
        )
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "v2.0"
    finally:
        conn.close()


@pytest.mark.integration
def test_remove_deletes_metadata(tmp_project: Path, dataset_dir: Path) -> None:
    """DB + manifest removed on dataset remove."""
    _invoke_with_cwd(
        ["dataset", "add", "ds-remove", "--path", str(dataset_dir)],
        tmp_project,
    )

    # Verify manifest exists
    manifest_path = tmp_project / REVOLVER_DIR / "datasets" / "ds-remove" / "manifest.yaml"
    assert manifest_path.exists()

    # Remove
    result = _invoke_with_cwd(["dataset", "remove", "ds-remove"], tmp_project)
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify DB entry removed
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT * FROM datasets WHERE name = ?", ("ds-remove",))
        assert cursor.fetchone() is None

        cursor = conn.execute(
            "SELECT * FROM dataset_instances WHERE dataset_name = ?", ("ds-remove",)
        )
        assert cursor.fetchall() == []
    finally:
        conn.close()

    # Verify manifest/dir removed
    assert not manifest_path.exists()


@pytest.mark.integration
def test_remove_blocked_by_reference(tmp_project: Path, dataset_dir: Path) -> None:
    """Exit code 1 when referenced by solutions."""
    _create_problem_version(tmp_project, "v1.0")

    _invoke_with_cwd(
        ["dataset", "add", "ds-blocked", "--path", str(dataset_dir)],
        tmp_project,
    )

    # Insert a fake run + solution that references this dataset
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            """\
            INSERT INTO runs (id, problem_version, llm, dataset, iterations,
                              problem_hash, dataset_hash, llm_model, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run-001",
                "v1.0",
                "test-llm",
                "ds-blocked",
                10,
                "sha256:fake",
                "sha256:fake",
                "test-model",
                "completed",
                "2026-01-01T00:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO solutions (id, run_id, rank) VALUES (?, ?, ?)",
            ("sol-001", "run-001", 1),
        )
        conn.commit()
    finally:
        conn.close()

    # Attempt to remove (should be blocked)
    result = _invoke_with_cwd(["dataset", "remove", "ds-blocked"], tmp_project)
    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"
    output = _get_all_output(result)
    assert "referenced" in output.lower() or "solution" in output.lower()


@pytest.mark.integration
def test_remove_forced(tmp_project: Path, dataset_dir: Path) -> None:
    """--force removes despite references."""
    _create_problem_version(tmp_project, "v1.0")

    _invoke_with_cwd(
        ["dataset", "add", "ds-forced", "--path", str(dataset_dir)],
        tmp_project,
    )

    # Insert a fake run + solution that references this dataset
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            """\
            INSERT INTO runs (id, problem_version, llm, dataset, iterations,
                              problem_hash, dataset_hash, llm_model, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run-002",
                "v1.0",
                "test-llm",
                "ds-forced",
                10,
                "sha256:fake",
                "sha256:fake",
                "test-model",
                "completed",
                "2026-01-01T00:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO solutions (id, run_id, rank) VALUES (?, ?, ?)",
            ("sol-002", "run-002", 1),
        )
        conn.commit()
    finally:
        conn.close()

    # Force remove
    result = _invoke_with_cwd(
        ["dataset", "remove", "ds-forced", "--force"],
        tmp_project,
    )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify removed from DB
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT * FROM datasets WHERE name = ?", ("ds-forced",))
        assert cursor.fetchone() is None
    finally:
        conn.close()


@pytest.mark.integration
def test_remove_snapshot_deletes_files(tmp_project: Path, dataset_dir: Path) -> None:
    """Snapshot files deleted on remove."""
    _invoke_with_cwd(
        ["dataset", "add", "ds-snap-rm", "--path", str(dataset_dir), "--snapshot"],
        tmp_project,
    )

    snapshot_dir = tmp_project / REVOLVER_DIR / "datasets" / "ds-snap-rm" / "snapshot"
    assert snapshot_dir.is_dir()
    assert len(list(snapshot_dir.iterdir())) == 3

    # Remove
    result = _invoke_with_cwd(["dataset", "remove", "ds-snap-rm"], tmp_project)
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify snapshot directory deleted
    dataset_store_dir = tmp_project / REVOLVER_DIR / "datasets" / "ds-snap-rm"
    assert not dataset_store_dir.exists()
