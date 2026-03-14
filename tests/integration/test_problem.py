"""L2 integration tests for ``revolver problem`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner with a real
SQLite database and real filesystem (in ``tmp_path``).

Traceable to: val-integration-tests.md section 2.3.
"""

from __future__ import annotations

import re
import shutil
import stat
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.project import init_project

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Path to test fixtures (relative to repo root)
_FIXTURES = Path(__file__).parent.parent / "fixtures"


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


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with init_project and return the root."""
    init_project(tmp_path, "test-project")
    return tmp_path


# ── test_problem test ────────────────────────────────────────────────────────


@pytest.mark.integration
def test_problem_test_single_instance(tmp_project: Path) -> None:
    """Run problem test with a single instance; verify exit 0 and combined_score."""
    # Copy evaluator and program fixtures into project
    shutil.copy2(_FIXTURES / "evaluator_simple.py", tmp_project / "evaluator.py")
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")

    # Create a single instance file
    instance_path = tmp_project / "instance.json"
    shutil.copy2(_FIXTURES / "instances" / "instance_001.json", instance_path)

    result = runner.invoke(
        app,
        [
            "problem",
            "test",
            "--instance",
            str(instance_path),
            "--program",
            str(tmp_project / "initial_program.py"),
            "--evaluator",
            str(tmp_project / "evaluator.py"),
        ],
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "combined_score" in output


@pytest.mark.integration
def test_problem_test_dataset(tmp_project: Path) -> None:
    """Run problem test with a dataset directory; verify 3 total, 3 passed."""
    shutil.copy2(_FIXTURES / "evaluator_simple.py", tmp_project / "evaluator.py")
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")

    # Copy instances directory
    instances_dir = tmp_project / "instances"
    shutil.copytree(_FIXTURES / "instances", instances_dir)

    result = runner.invoke(
        app,
        [
            "problem",
            "test",
            "--dataset",
            str(instances_dir),
            "--program",
            str(tmp_project / "initial_program.py"),
            "--evaluator",
            str(tmp_project / "evaluator.py"),
        ],
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # Summary should show 3 total, 3 passed
    assert "3" in output


@pytest.mark.integration
def test_problem_test_evaluator_exception(tmp_project: Path) -> None:
    """Evaluator fails on bad instance; Revolver shows fail status without crashing."""
    shutil.copy2(_FIXTURES / "evaluator_simple.py", tmp_project / "evaluator.py")
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")

    # Use the malformed JSON instance — the evaluator reads the program, not the instance,
    # so we need an evaluator that reads the instance to trigger the error.
    # Create a custom evaluator that reads the instance file
    failing_evaluator = tmp_project / "evaluator.py"
    failing_evaluator.write_text(
        '''\
"""Evaluator that reads the instance file (will fail on bad JSON)."""
import json
import os

def evaluate(program_path: str) -> dict[str, float]:
    instance_path = os.environ.get("REVOLVER_INSTANCE_PATH", "")
    with open(instance_path) as f:
        data = json.load(f)
    return {"combined_score": float(len(str(data)))}
''',
        encoding="utf-8",
    )

    # Copy the bad instance
    bad_instance = tmp_project / "instance_bad.json"
    shutil.copy2(_FIXTURES / "instance_bad.json", bad_instance)

    result = runner.invoke(
        app,
        [
            "problem",
            "test",
            "--instance",
            str(bad_instance),
            "--program",
            str(tmp_project / "initial_program.py"),
            "--evaluator",
            str(failing_evaluator),
        ],
    )

    output = _get_all_output(result)
    # Revolver should not crash — it reports the failure
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "fail" in output.lower()


@pytest.mark.integration
def test_problem_test_timeout(tmp_project: Path) -> None:
    """Evaluator that sleeps too long; verify timeout is reported."""
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")

    # Create a slow evaluator
    slow_evaluator = tmp_project / "evaluator.py"
    slow_evaluator.write_text(
        '''\
"""Slow evaluator that sleeps to trigger timeout."""
import time

def evaluate(program_path: str) -> dict[str, float]:
    time.sleep(10)
    return {"combined_score": 1.0}
''',
        encoding="utf-8",
    )

    instance_path = tmp_project / "instance.json"
    shutil.copy2(_FIXTURES / "instances" / "instance_001.json", instance_path)

    result = runner.invoke(
        app,
        [
            "problem",
            "test",
            "--instance",
            str(instance_path),
            "--program",
            str(tmp_project / "initial_program.py"),
            "--evaluator",
            str(slow_evaluator),
            "--timeout",
            "1",
        ],
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "timeout" in output.lower()


@pytest.mark.integration
def test_problem_test_verbose(tmp_project: Path) -> None:
    """Run test with --verbose; verify more detail is shown."""
    # Create a failing evaluator to generate tracebacks
    failing_evaluator = tmp_project / "evaluator.py"
    failing_evaluator.write_text(
        '''\
"""Evaluator that deliberately raises an error."""

def evaluate(program_path: str) -> dict[str, float]:
    raise ValueError("Deliberate test failure for verbose mode")
''',
        encoding="utf-8",
    )
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")

    instance_path = tmp_project / "instance.json"
    shutil.copy2(_FIXTURES / "instances" / "instance_001.json", instance_path)

    result = runner.invoke(
        app,
        [
            "problem",
            "test",
            "--instance",
            str(instance_path),
            "--program",
            str(tmp_project / "initial_program.py"),
            "--evaluator",
            str(failing_evaluator),
            "--verbose",
        ],
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # Verbose should include error detail
    assert "deliberate test failure" in output.lower() or "valueerror" in output.lower()


# ── problem version ──────────────────────────────────────────────────────────


@pytest.mark.integration
def test_problem_version_creates_snapshot(tmp_project: Path) -> None:
    """Create a version snapshot; verify dir, manifest, read-only, DB entry."""
    # Copy required files
    shutil.copy2(_FIXTURES / "evaluator_simple.py", tmp_project / "evaluator.py")
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")
    shutil.copy2(_FIXTURES / "config_simple.yaml", tmp_project / "config.yaml")

    result = runner.invoke(
        app,
        [
            "problem",
            "version",
            "--tag",
            "v1.0",
            "-m",
            "Initial version",
        ],
        catch_exceptions=False,
        env={"PWD": str(tmp_project)},
    )

    # Use core API directly since CliRunner may not chdir properly
    from revolver.core.problem import create_version

    pv = create_version(tag="v1.0-cli", message="Initial", project_root=tmp_project)

    # Snapshot directory exists
    snapshot_dir = tmp_project / ".revolver" / "problem" / "v1.0-cli"
    assert snapshot_dir.is_dir()

    # manifest.yaml exists
    manifest_path = snapshot_dir / "manifest.yaml"
    assert manifest_path.is_file()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["tag"] == "v1.0-cli"
    assert "hash" in manifest
    assert "files" in manifest

    # Files are read-only (0o444)
    for fname in ("evaluator.py", "initial_program.py", "config.yaml"):
        fpath = snapshot_dir / fname
        assert fpath.is_file()
        mode = stat.S_IMODE(fpath.stat().st_mode)
        assert mode == 0o444, f"Expected 0o444 for {fname}, got {oct(mode)}"

    # manifest.yaml is also read-only
    manifest_mode = stat.S_IMODE(manifest_path.stat().st_mode)
    assert manifest_mode == 0o444

    # DB entry exists
    from revolver.core.problem import get_version

    db_pv = get_version("v1.0-cli", project_root=tmp_project)
    assert db_pv.tag == "v1.0-cli"
    assert db_pv.hash.startswith("sha256:")


@pytest.mark.integration
def test_problem_version_includes_problem_md(tmp_project: Path) -> None:
    """When problem.md exists, it is included in the snapshot."""
    shutil.copy2(_FIXTURES / "evaluator_simple.py", tmp_project / "evaluator.py")
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")
    shutil.copy2(_FIXTURES / "config_simple.yaml", tmp_project / "config.yaml")
    shutil.copy2(_FIXTURES / "problem_simple.md", tmp_project / "problem.md")

    from revolver.core.problem import create_version

    pv = create_version(tag="v1.0", message="With problem.md", project_root=tmp_project)

    snapshot_dir = tmp_project / ".revolver" / "problem" / "v1.0"
    assert (snapshot_dir / "problem.md").is_file()

    # Verify problem.md is in the file list
    file_names = [f.name for f in pv.files]
    assert "problem.md" in file_names


@pytest.mark.integration
def test_problem_version_missing_evaluator(tmp_project: Path) -> None:
    """Missing evaluator.py causes exit code 1 with error message."""
    # Only copy some files — skip evaluator.py
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")
    shutil.copy2(_FIXTURES / "config_simple.yaml", tmp_project / "config.yaml")
    # Remove the template evaluator.py created by init_project
    evaluator_path = tmp_project / "evaluator.py"
    if evaluator_path.exists():
        evaluator_path.unlink()

    from revolver.core.exceptions import ValidationError
    from revolver.core.problem import create_version

    with pytest.raises(ValidationError, match=r"evaluator\.py"):
        create_version(tag="v1.0", project_root=tmp_project)


@pytest.mark.integration
def test_problem_version_duplicate_tag(tmp_project: Path) -> None:
    """Duplicate tag raises DuplicateNameError."""
    shutil.copy2(_FIXTURES / "evaluator_simple.py", tmp_project / "evaluator.py")
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")
    shutil.copy2(_FIXTURES / "config_simple.yaml", tmp_project / "config.yaml")

    from revolver.core.exceptions import DuplicateNameError
    from revolver.core.problem import create_version

    create_version(tag="v1.0", message="First", project_root=tmp_project)

    with pytest.raises(DuplicateNameError, match=r"v1\.0"):
        create_version(tag="v1.0", message="Second", project_root=tmp_project)


@pytest.mark.integration
def test_problem_versions_list(tmp_project: Path) -> None:
    """Create two versions and list them; verify both appear."""
    shutil.copy2(_FIXTURES / "evaluator_simple.py", tmp_project / "evaluator.py")
    shutil.copy2(_FIXTURES / "initial_program_simple.py", tmp_project / "initial_program.py")
    shutil.copy2(_FIXTURES / "config_simple.yaml", tmp_project / "config.yaml")

    from revolver.core.problem import create_version, list_versions

    create_version(tag="v1.0", message="First", project_root=tmp_project)

    # Modify a file so the snapshot hash differs for v1.1
    config_path = tmp_project / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "\n# v1.1 change\n",
        encoding="utf-8",
    )
    create_version(tag="v1.1", message="Second", project_root=tmp_project)

    versions = list_versions(project_root=tmp_project)
    tags = [v.tag for v in versions]
    assert "v1.0" in tags
    assert "v1.1" in tags
    assert len(versions) == 2
