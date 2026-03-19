"""L2 integration tests for ``revolver eval`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner with a real
SQLite database and real filesystem (in ``tmp_path``). The evaluator_runner
is mocked at the infra boundary to avoid spawning real subprocesses.

Traceable to: val-integration-tests.md section 2.6 (10 scenarios).
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
import revolver.core.eval as core_eval_module
from revolver.core.project import init_project
from revolver.infra.db import (
    get_project_db,
    insert_dataset,
    insert_dataset_compat,
    insert_dataset_instances,
    insert_problem_version,
    insert_run,
    insert_solution,
)
from revolver.infra.store import PROBLEM_DIR, REVOLVER_DIR, RUNS_DIR
from revolver.models.dataset import DatasetInstance, DatasetRegistration
from revolver.models.problem import InstanceTestResult, ProblemVersion

pytestmark = pytest.mark.integration

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


def _parse_json_output(result: object) -> object:
    """Extract and parse the first JSON object/array from CLI output."""
    output = getattr(result, "output", "") or ""
    stdout = getattr(result, "stdout", "") or ""
    text = stdout or output
    for i, ch in enumerate(text):
        if ch in ("{", "["):
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(text, i)
            return obj
    msg = f"No JSON found in output: {text[:200]}"
    raise ValueError(msg)


def _invoke_with_cwd(args: list[str], cwd: Path) -> object:
    """Invoke the CLI with a patched working directory."""
    with patch("pathlib.Path.cwd", return_value=cwd):
        return runner.invoke(app, args, catch_exceptions=False)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def eval_project(tmp_path: Path) -> dict[str, object]:
    """Create a complete project with problem version, dataset, run, and solution.

    Returns a dict with all the IDs and paths needed for eval tests.
    """
    # Initialize project
    init_project(tmp_path, "test-eval-project")
    db_path = tmp_path / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)

    # Create problem version
    now = datetime.now(UTC)
    pv = ProblemVersion(
        tag="v1.0",
        hash="sha256:abc123",
        message="Test version",
        created_at=now,
    )
    insert_problem_version(conn, pv)

    # Create evaluator in problem version snapshot
    snapshot_dir = tmp_path / REVOLVER_DIR / PROBLEM_DIR / "v1.0"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    evaluator_content = '''"""Test evaluator."""
import os

def evaluate(program_path):
    """Legacy evaluator that checks for REVOLVER_INSTANCE_PATH."""
    instance_path = os.environ.get("REVOLVER_INSTANCE_PATH", "")
    dataset_dir = os.environ.get("REVOLVER_DATASET_DIR", "")
    with open(program_path) as f:
        source = f.read()
    if instance_path:
        return {"combined_score": len(source) / 100.0}
    elif dataset_dir:
        return {"combined_score": 0.85, "weighted_avg": 0.90}
    return {"combined_score": len(source) / 100.0}
'''
    (snapshot_dir / "evaluator.py").write_text(evaluator_content)

    # Create dataset directory with 3 instances
    data_dir = tmp_path / "data" / "instances"
    data_dir.mkdir(parents=True)
    for i in range(1, 4):
        (data_dir / f"instance_{i:03d}.json").write_text(json.dumps({"id": i, "value": i * 10}))

    # Register dataset
    ds_instances = [
        DatasetInstance(
            filename=f"instance_{i:03d}.json",
            relative_path=f"instance_{i:03d}.json",
            hash=f"sha256:inst{i}",
            size_bytes=50,
        )
        for i in range(1, 4)
    ]
    ds = DatasetRegistration(
        name="eval-bench",
        path=str(data_dir),
        split="eval",
        storage="reference",
        instance_count=3,
        global_hash="sha256:dataset_hash",
        created_at=now,
    )
    insert_dataset(conn, ds)
    insert_dataset_instances(conn, "eval-bench", ds_instances)
    insert_dataset_compat(conn, "eval-bench", "v1.0")

    # Create run
    run_id = "run-20260317-100000"
    insert_run(
        conn,
        run_id=run_id,
        problem_version="v1.0",
        llm="test-llm",
        dataset="eval-bench",
        iterations=10,
        problem_hash="sha256:abc123",
        dataset_hash="sha256:dataset_hash",
        llm_model="test-model",
        created_at=now,
        status="completed",
    )

    # Create solution
    solution_id = "sol-20260317-100000"
    insert_solution(
        conn,
        solution_id=solution_id,
        run_id=run_id,
        rank=1,
        best_score=0.95,
        alias="my-solution",
    )

    # Create program file
    programs_dir = tmp_path / REVOLVER_DIR / RUNS_DIR / run_id / "programs"
    programs_dir.mkdir(parents=True)
    (programs_dir / "rank-1.py").write_text("# Test program\nprint('hello')\n")

    conn.close()

    return {
        "root": tmp_path,
        "db_path": db_path,
        "solution_id": solution_id,
        "run_id": run_id,
        "dataset_name": "eval-bench",
        "data_dir": data_dir,
        "snapshot_dir": snapshot_dir,
        "program_path": programs_dir / "rank-1.py",
    }


def _make_mock_run_instance(
    metrics: dict[str, float] | None = None,
    fail_instance: str | None = None,
) -> object:
    """Create a mock for evaluator_runner.run_instance.

    Args:
        metrics: Default metrics to return for passing instances.
        fail_instance: Instance ID that should fail.

    Returns:
        A mock function that returns InstanceTestResult.
    """
    if metrics is None:
        metrics = {"combined_score": 1.0}

    def mock_run_instance(
        evaluator_path: Path,
        program_path: Path,
        instance_path: Path,
        timeout_s: float = 300.0,
    ) -> InstanceTestResult:
        instance_id = instance_path.name
        if fail_instance and instance_id == fail_instance:
            return InstanceTestResult(
                instance_id=instance_id,
                status="fail",
                time_s=0.1,
                error="Evaluation failed: test error",
            )
        return InstanceTestResult(
            instance_id=instance_id,
            status="pass",
            metrics=dict(metrics),
            time_s=0.05,
        )

    return mock_run_instance


# ── Test 1: test_stores_per_instance_results ────────────────────────────────


def test_stores_per_instance_results(eval_project: dict[str, object]) -> None:
    """Valid solution + 3 instances -> per-instance results in DB, aggregates displayed."""
    root = eval_project["root"]
    assert isinstance(root, Path)

    mock_fn = _make_mock_run_instance({"combined_score": 1.0})
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result = _invoke_with_cwd(
            ["eval", "--solution", "my-solution", "--dataset", "eval-bench"],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "solved" in output.lower() or "3/3" in output

    # Verify DB has per-instance results
    db_path = eval_project["db_path"]
    assert isinstance(db_path, Path)
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM eval_instances")
        count = cursor.fetchone()[0]
        assert count >= 3, f"Expected at least 3 eval_instance rows, got {count}"

        cursor = conn.execute("SELECT COUNT(*) FROM eval_metadata")
        meta_count = cursor.fetchone()[0]
        assert meta_count == 1
    finally:
        conn.close()


# ── Test 2: test_handles_instance_failure ───────────────────────────────────


def test_handles_instance_failure(eval_project: dict[str, object]) -> None:
    """One instance fails -> recorded as unsolved, eval continues."""
    root = eval_project["root"]
    assert isinstance(root, Path)

    mock_fn = _make_mock_run_instance(
        metrics={"combined_score": 1.0},
        fail_instance="instance_002.json",
    )
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result = _invoke_with_cwd(
            ["eval", "--solution", "my-solution", "--dataset", "eval-bench"],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "2/3" in output  # 2 solved out of 3

    # Verify the failed instance is recorded
    db_path = eval_project["db_path"]
    assert isinstance(db_path, Path)
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT status FROM eval_instances WHERE instance_id = 'instance_002.json'"
        )
        rows = cursor.fetchall()
        assert len(rows) >= 1
        assert rows[0][0] == "failed"
    finally:
        conn.close()


# ── Test 3: test_nonexistent_solution ───────────────────────────────────────


def test_nonexistent_solution(eval_project: dict[str, object]) -> None:
    """Non-existent solution -> exit code 1."""
    root = eval_project["root"]
    assert isinstance(root, Path)

    result = _invoke_with_cwd(
        ["eval", "--solution", "nonexistent-sol", "--dataset", "eval-bench"],
        root,
    )

    assert result.exit_code == 1
    output = _get_all_output(result)
    assert "not found" in output.lower()


# ── Test 4: test_integrity_warning ──────────────────────────────────────────


def test_integrity_warning(eval_project: dict[str, object]) -> None:
    """Dataset hash mismatch -> warning on stderr, eval proceeds."""
    root = eval_project["root"]
    assert isinstance(root, Path)
    data_dir = eval_project["data_dir"]
    assert isinstance(data_dir, Path)

    # Modify an instance to cause integrity mismatch
    (data_dir / "instance_001.json").write_text(json.dumps({"id": 1, "value": 999}))

    mock_fn = _make_mock_run_instance({"combined_score": 1.0})
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result = _invoke_with_cwd(
            ["eval", "--solution", "my-solution", "--dataset", "eval-bench"],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "warning" in output.lower() or "integrity" in output.lower()


# ── Test 5: test_warns_incompatible_version ─────────────────────────────────


def test_warns_incompatible_version(eval_project: dict[str, object]) -> None:
    """Dataset not compatible with problem version -> warning on stderr."""
    root = eval_project["root"]
    assert isinstance(root, Path)

    # Insert a different problem version, then replace compat entries
    db_path = eval_project["db_path"]
    assert isinstance(db_path, Path)
    conn = get_project_db(db_path)
    try:
        # First insert the problem version (FK parent)
        insert_sql = (
            "INSERT OR IGNORE INTO problem_versions "
            "(tag, hash, message, created_at) VALUES (?, ?, ?, ?)"
        )
        conn.execute(
            insert_sql,
            ("v2.0-other", "sha256:diff", "", datetime.now(UTC).isoformat()),
        )
        # Remove old compat entry
        conn.execute("DELETE FROM dataset_compat WHERE dataset_name = 'eval-bench'")
        # Insert compat with a DIFFERENT version
        conn.execute(
            "INSERT INTO dataset_compat (dataset_name, problem_version) VALUES (?, ?)",
            ("eval-bench", "v2.0-other"),
        )
        conn.commit()
    finally:
        conn.close()

    mock_fn = _make_mock_run_instance({"combined_score": 1.0})
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result = _invoke_with_cwd(
            ["eval", "--solution", "my-solution", "--dataset", "eval-bench"],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "not marked compatible" in output.lower() or "warning" in output.lower()


# ── Test 6: test_warns_non_eval_split ───────────────────────────────────────


def test_warns_non_eval_split(tmp_path: Path) -> None:
    """Dataset split=train -> warning on stderr."""
    # Create a project with a train-split dataset
    init_project(tmp_path, "test-train-split")
    db_path = tmp_path / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    now = datetime.now(UTC)

    # Problem version
    pv = ProblemVersion(tag="v1.0", hash="sha256:abc", message="", created_at=now)
    insert_problem_version(conn, pv)

    # Evaluator snapshot
    snapshot_dir = tmp_path / REVOLVER_DIR / PROBLEM_DIR / "v1.0"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "evaluator.py").write_text(
        "def evaluate(p):\n    return {'combined_score': 1.0}\n"
    )

    # Dataset with split=train
    data_dir = tmp_path / "train_data"
    data_dir.mkdir()
    (data_dir / "inst1.json").write_text('{"v": 1}')
    ds = DatasetRegistration(
        name="train-ds",
        path=str(data_dir),
        split="train",
        storage="reference",
        instance_count=1,
        global_hash="sha256:train_hash",
        created_at=now,
    )
    insert_dataset(conn, ds)
    insert_dataset_instances(
        conn,
        "train-ds",
        [
            DatasetInstance(
                filename="inst1.json", relative_path="inst1.json", hash="sha256:i1", size_bytes=10
            )
        ],
    )

    # Run + solution
    run_id = "run-20260317-110000"
    insert_run(
        conn,
        run_id=run_id,
        problem_version="v1.0",
        llm="test-llm",
        dataset="train-ds",
        iterations=5,
        problem_hash="sha256:abc",
        dataset_hash="sha256:train_hash",
        llm_model="test-model",
        created_at=now,
        status="completed",
    )
    insert_solution(conn, solution_id="sol-train", run_id=run_id, rank=1, best_score=0.8)
    programs_dir = tmp_path / REVOLVER_DIR / RUNS_DIR / run_id / "programs"
    programs_dir.mkdir(parents=True)
    (programs_dir / "rank-1.py").write_text("# program\n")
    conn.close()

    mock_fn = _make_mock_run_instance({"combined_score": 1.0})
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result = _invoke_with_cwd(
            ["eval", "--solution", "sol-train", "--dataset", "train-ds"],
            tmp_path,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "train" in output.lower()


# ── Test 7: test_re_eval_requires_confirmation ──────────────────────────────


def test_re_eval_requires_confirmation(eval_project: dict[str, object]) -> None:
    """Results already exist -> confirmation required; --force skips."""
    root = eval_project["root"]
    assert isinstance(root, Path)

    # First eval
    mock_fn = _make_mock_run_instance({"combined_score": 1.0})
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result1 = _invoke_with_cwd(
            ["eval", "--solution", "my-solution", "--dataset", "eval-bench"],
            root,
        )
    assert result1.exit_code == 0

    # Second eval in JSON mode without --force should fail
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result2 = _invoke_with_cwd(
            ["--json", "eval", "--solution", "my-solution", "--dataset", "eval-bench"],
            root,
        )
    assert result2.exit_code == 1
    output2 = _get_all_output(result2)
    assert "already exists" in output2.lower() or "force" in output2.lower()

    # Third eval with --force should succeed
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result3 = _invoke_with_cwd(
            [
                "--json",
                "eval",
                "--solution",
                "my-solution",
                "--dataset",
                "eval-bench",
                "--force",
            ],
            root,
        )
    assert result3.exit_code == 0


# ── Test 8: test_results_command ────────────────────────────────────────────


def test_results_command(eval_project: dict[str, object]) -> None:
    """After eval, 'eval results' displays aggregates."""
    root = eval_project["root"]
    assert isinstance(root, Path)

    # First run an eval
    mock_fn = _make_mock_run_instance({"combined_score": 1.0, "accuracy": 0.95})
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result1 = _invoke_with_cwd(
            ["eval", "--solution", "my-solution", "--dataset", "eval-bench"],
            root,
        )
    assert result1.exit_code == 0

    # Now query results
    result2 = _invoke_with_cwd(
        ["eval", "results", "--solution", "my-solution", "--dataset", "eval-bench"],
        root,
    )

    output = _get_all_output(result2)
    assert result2.exit_code == 0, f"Exit code {result2.exit_code}: {output}"
    # Should show aggregates (metric names may be truncated by rich table)
    assert "1.0000" in output or "0.9500" in output or "mean" in output.lower()


# ── Test 9: test_results_per_instance ───────────────────────────────────────


def test_results_per_instance(eval_project: dict[str, object]) -> None:
    """--per-instance shows per-instance breakdown."""
    root = eval_project["root"]
    assert isinstance(root, Path)

    # First run an eval
    mock_fn = _make_mock_run_instance({"combined_score": 0.9})
    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(core_eval_module, "_run_legacy_global_aggregation", return_value=None),
    ):
        result1 = _invoke_with_cwd(
            ["eval", "--solution", "my-solution", "--dataset", "eval-bench"],
            root,
        )
    assert result1.exit_code == 0

    # Query per-instance results
    result2 = _invoke_with_cwd(
        [
            "eval",
            "results",
            "--solution",
            "my-solution",
            "--dataset",
            "eval-bench",
            "--per-instance",
        ],
        root,
    )

    output = _get_all_output(result2)
    assert result2.exit_code == 0, f"Exit code {result2.exit_code}: {output}"
    # Should show individual instance IDs
    assert "instance_001" in output or "instance_002" in output or "instance_003" in output


# ── Test 10: test_results_shows_user_aggregates ─────────────────────────────


def test_results_shows_user_aggregates(eval_project: dict[str, object]) -> None:
    """Legacy evaluator -> global aggregation, user_aggregates stored and displayed."""
    root = eval_project["root"]
    assert isinstance(root, Path)

    mock_fn = _make_mock_run_instance({"combined_score": 1.0})
    user_agg = {"combined_score": 0.85, "weighted_avg": 0.90}

    with (
        patch.object(core_eval_module, "run_instance", side_effect=mock_fn),
        patch.object(
            core_eval_module,
            "_run_legacy_global_aggregation",
            return_value=user_agg,
        ),
    ):
        result1 = _invoke_with_cwd(
            ["eval", "--solution", "my-solution", "--dataset", "eval-bench"],
            root,
        )
    assert result1.exit_code == 0

    # Query results - should show user aggregates
    result2 = _invoke_with_cwd(
        ["eval", "results", "--solution", "my-solution", "--dataset", "eval-bench"],
        root,
    )

    output = _get_all_output(result2)
    assert result2.exit_code == 0, f"Exit code {result2.exit_code}: {output}"
    # Should display user aggregates section
    assert "user aggregates" in output.lower() or "weighted_avg" in output.lower()
