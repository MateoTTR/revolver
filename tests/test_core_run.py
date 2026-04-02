"""L1 unit tests for revolver.core.run — domain orchestration functions.

All OpenEvolve calls are mocked. Tests cover:
- launch_run() happy path, validation, dry-run, token proxy, lock files
- _post_run_evaluation() instance evaluation
- resume_run() creates new run from parent
- list_runs() with filters
- get_run_info() returns complete data
- get_run_status() with and without active locks
- generate_run_id() / generate_solution_id() format
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from revolver.core.exceptions import ExternalError, IntegrityError, RevolverError
from revolver.core.run import (
    MIN_VALID_ITERATION_RATIO,
    _collect_programs,
    _determine_run_status,
    _handle_post_run_failure,
    _is_pid_alive,
    _post_run_evaluation,
    generate_run_id,
    generate_solution_id,
    get_run_info,
    get_run_status,
    launch_run,
    list_runs,
    resume_run,
)
from revolver.infra.db import (
    get_project_db,
    get_run,
    insert_run,
    insert_solution,
)
from revolver.infra.openevolve import RunOutput
from revolver.infra.store import (
    REVOLVER_DIR,
    create_run_dir,
    init_project_store,
    write_run_lock,
    write_run_manifest,
)
from revolver.infra.token_proxy import TokenUsage as ProxyTokenUsage
from revolver.models.run import RunConfig

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with initialized .revolver/ store and DB."""
    init_project_store(tmp_path)
    # Initialize the project DB
    db_path = tmp_path / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    conn.close()
    return tmp_path


@pytest.fixture()
def project_with_prereqs(tmp_project: Path) -> dict:
    """Set up a project with problem version, LLM, and dataset for run tests.

    Returns a dict with project_root and connection details.
    """
    root = tmp_project
    db_path = root / REVOLVER_DIR / "revolver.db"

    # Create problem version snapshot directory with required files
    snapshot_dir = root / REVOLVER_DIR / "problem" / "v1.0"
    snapshot_dir.mkdir(parents=True)
    evaluator_code = (
        "def evaluate_instance(program_path, instance_path):\n    return {'combined_score': 1.0}\n"
    )
    (snapshot_dir / "evaluator.py").write_text(evaluator_code)
    (snapshot_dir / "initial_program.py").write_text("# initial program\n")
    (snapshot_dir / "config.yaml").write_text("iterations: 5\n")

    # Insert problem version in DB
    proj_conn = get_project_db(db_path)
    try:
        proj_conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
            ("v1.0", "hash-v1", "test version", datetime.now(UTC).isoformat()),
        )
        proj_conn.commit()

        # Insert dataset in DB
        dataset_dir = root / "datasets" / "train-small"
        dataset_dir.mkdir(parents=True)
        (dataset_dir / "instance1.txt").write_text("instance 1 data")
        (dataset_dir / "instance2.txt").write_text("instance 2 data")

        proj_conn.execute(
            "INSERT INTO datasets (name, path, split, storage, description, "
            "global_hash, instance_count, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "train-small",
                str(dataset_dir),
                "train",
                "reference",
                "test dataset",
                "dataset-hash-1",
                2,
                datetime.now(UTC).isoformat(),
            ),
        )
        proj_conn.commit()

        # Insert dataset instances
        proj_conn.executemany(
            "INSERT INTO dataset_instances (dataset_name, instance_id, hash) VALUES (?, ?, ?)",
            [
                ("train-small", "instance1.txt", "inst-hash-1"),
                ("train-small", "instance2.txt", "inst-hash-2"),
            ],
        )
        proj_conn.commit()

        # Insert dataset compat
        proj_conn.execute(
            "INSERT INTO dataset_compat (dataset_name, problem_version) VALUES (?, ?)",
            ("train-small", "v1.0"),
        )
        proj_conn.commit()
    finally:
        proj_conn.close()

    # Insert LLM in global DB (use custom path for test isolation)
    from revolver.infra.db import get_global_db_at

    global_db_path = root / "global.db"
    global_conn = get_global_db_at(global_db_path)
    try:
        global_conn.execute(
            "INSERT INTO llms (name, provider, model, source, base_url, "
            "api_key_env, input_cost_per_mtok, output_cost_per_mtok, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "test-llm",
                "openai",
                "gpt-4",
                "remote",
                "http://localhost:11434/v1",
                None,
                3.0,
                15.0,
                datetime.now(UTC).isoformat(),
            ),
        )
        global_conn.commit()

        # Also insert a local LLM for concurrency tests
        global_conn.execute(
            "INSERT INTO llms (name, provider, model, source, base_url, "
            "api_key_env, input_cost_per_mtok, output_cost_per_mtok, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "local-llm",
                "ollama",
                "codestral:22b",
                "local",
                "http://localhost:11434/v1",
                None,
                None,
                None,
                datetime.now(UTC).isoformat(),
            ),
        )
        global_conn.commit()
    finally:
        global_conn.close()

    return {
        "root": root,
        "db_path": db_path,
        "global_db_path": global_db_path,
        "dataset_dir": dataset_dir,
        "snapshot_dir": snapshot_dir,
    }


# ── ID generation tests ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_generate_run_id_format() -> None:
    """generate_run_id must return run-YYYYMMDD-HHMMSS format."""
    run_id = generate_run_id()
    assert run_id.startswith("run-")
    parts = run_id.split("-")
    assert len(parts) == 3
    assert len(parts[1]) == 8  # YYYYMMDD
    assert len(parts[2]) == 6  # HHMMSS


@pytest.mark.unit
def test_generate_solution_id_format() -> None:
    """generate_solution_id must return sol-YYYYMMDD-HHMMSS format."""
    sol_id = generate_solution_id()
    assert sol_id.startswith("sol-")
    parts = sol_id.split("-")
    assert len(parts) == 3
    assert len(parts[1]) == 8  # YYYYMMDD
    assert len(parts[2]) == 6  # HHMMSS


# ── launch_run tests ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_launch_run_unknown_llm(project_with_prereqs: dict) -> None:
    """launch_run must raise RevolverError for unknown LLM name."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="nonexistent-llm",
        dataset_name="train-small",
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch(
            "revolver.core.run.resolve_llm_or_ensemble",
            side_effect=RevolverError("LLM or ensemble 'nonexistent-llm' not found."),
        ),
    ):
        mock_global_db.return_value = MagicMock()
        with pytest.raises(RevolverError, match=r"LLM.*not found"):
            launch_run(config, project_root=root)


@pytest.mark.unit
def test_launch_run_unknown_version(project_with_prereqs: dict) -> None:
    """launch_run must raise RevolverError for unknown problem version."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v99.0",
        llm_name="test-llm",
        dataset_name="train-small",
    )

    with patch("revolver.core.run.get_global_db") as mock_global_db:
        mock_global_db.return_value = MagicMock()
        with pytest.raises(RevolverError, match=r"Problem version.*not found"):
            launch_run(config, project_root=root)


@pytest.mark.unit
def test_launch_run_unknown_dataset(project_with_prereqs: dict) -> None:
    """launch_run must raise RevolverError for unknown dataset."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="nonexistent-dataset",
    )

    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
    ):
        mock_global_db.return_value = MagicMock()
        with pytest.raises(RevolverError, match=r"Dataset.*not found"):
            launch_run(config, project_root=root)


@pytest.mark.unit
def test_launch_run_integrity_failure(project_with_prereqs: dict) -> None:
    """launch_run must raise IntegrityError on dataset integrity failure."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
    )

    from revolver.models.dataset import IntegrityMismatch, IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    bad_integrity = IntegrityReport(
        is_valid=False,
        checked_at=datetime.now(UTC),
        mismatches=[
            IntegrityMismatch(
                filename="instance1.txt",
                expected_hash="abc",
                actual_hash="xyz",
            )
        ],
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=bad_integrity,
        ),
    ):
        mock_global_db.return_value = MagicMock()
        with pytest.raises(IntegrityError, match="integrity check failed"):
            launch_run(config, project_root=root)


@pytest.mark.unit
def test_launch_run_dry_run(project_with_prereqs: dict) -> None:
    """launch_run with dry_run=True must return config without side effects."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        dry_run=True,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(
        is_valid=True,
        checked_at=datetime.now(UTC),
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
    ):
        mock_global_db.return_value = MagicMock()
        result = launch_run(config, project_root=root)

    assert result.run_id == "dry-run"
    assert result.programs_stored == 0
    assert result.generation_time_s == 0.0

    # No run directory should be created
    runs_dir = root / REVOLVER_DIR / "runs"
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir() and d.name != "locks"]
    assert len(run_dirs) == 0


@pytest.mark.unit
def test_launch_run_warns_non_train_split(
    project_with_prereqs: dict, capsys: pytest.CaptureFixture
) -> None:
    """launch_run must warn on stderr if dataset split != train."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    # Update dataset split to 'eval'
    conn = get_project_db(db_path)
    try:
        conn.execute("UPDATE datasets SET split = 'eval' WHERE name = 'train-small'")
        conn.commit()
    finally:
        conn.close()

    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        dry_run=True,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(
        is_valid=True,
        checked_at=datetime.now(UTC),
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
    ):
        mock_global_db.return_value = MagicMock()
        launch_run(config, project_root=root)

    captured = capsys.readouterr()
    assert "split='eval'" in captured.err


@pytest.mark.unit
def test_launch_run_warns_incompatible_dataset(
    project_with_prereqs: dict, capsys: pytest.CaptureFixture
) -> None:
    """launch_run must warn if dataset is not compatible with problem version."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    # Remove compat entry
    conn = get_project_db(db_path)
    try:
        conn.execute("DELETE FROM dataset_compat WHERE dataset_name = 'train-small'")
        # Add compat for a different version
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
            ("v2.0", "hash-v2", "another version", datetime.now(UTC).isoformat()),
        )
        conn.execute(
            "INSERT INTO dataset_compat (dataset_name, problem_version) VALUES (?, ?)",
            ("train-small", "v2.0"),
        )
        conn.commit()
    finally:
        conn.close()

    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        dry_run=True,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(
        is_valid=True,
        checked_at=datetime.now(UTC),
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
    ):
        mock_global_db.return_value = MagicMock()
        launch_run(config, project_root=root)

    captured = capsys.readouterr()
    assert "not marked as compatible" in captured.err


@pytest.mark.unit
def test_launch_run_happy_path(project_with_prereqs: dict) -> None:
    """launch_run must orchestrate a full run with mocked OpenEvolve."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
        alias="my-solution",
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    # Mock OpenEvolve runner
    mock_run_output = RunOutput(
        best_score=0.95,
        best_program="some_program",
        output_dir=None,
    )

    mock_proxy_usage = ProxyTokenUsage(prompt_tokens=1000, completion_tokens=500)

    from revolver.models.problem import InstanceTestResult

    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_ok,
        ),
        patch("revolver.core.run.count_valid_programs", return_value=5),
    ):
        mock_global_db.return_value = MagicMock()

        # Configure mock proxy
        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = mock_proxy_usage
        mock_proxy_cls.return_value = mock_proxy

        # Configure mock OpenEvolve runner
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        result = launch_run(config, project_root=root)

    assert result.run_id.startswith("run-")
    assert result.problem_version == "v1.0"
    assert result.llm == "test-llm"
    assert result.dataset == "train-small"
    assert result.iterations == 5
    assert result.generation_time_s > 0
    assert result.solution.rank == 1
    assert result.solution.best_score == 0.95
    assert result.solution.alias == "my-solution"
    assert result.token_usage is not None
    assert result.token_usage.prompt_tokens == 1000
    assert result.token_usage.completion_tokens == 500

    # Verify run dir was created
    run_dir = root / REVOLVER_DIR / "runs" / result.run_id
    assert run_dir.is_dir()
    assert (run_dir / "programs").is_dir()

    # Verify lock was removed
    lock_file = root / REVOLVER_DIR / "runs" / "locks" / f"{result.run_id}.lock"
    assert not lock_file.exists()

    # Verify manifest was written
    manifest_path = run_dir / "manifest.yaml"
    assert manifest_path.exists()

    # Verify DB records
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT status, generation_time_s FROM runs WHERE id = ?",
            (result.run_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "completed"
        assert row[1] > 0

        cursor = conn.execute(
            "SELECT id, rank, alias, best_score FROM solutions WHERE run_id = ?",
            (result.run_id,),
        )
        sol_row = cursor.fetchone()
        assert sol_row is not None
        assert sol_row[1] == 1
        assert sol_row[2] == "my-solution"
        assert sol_row[3] == 0.95
    finally:
        conn.close()


@pytest.mark.unit
def test_launch_run_local_llm_sequential(project_with_prereqs: dict) -> None:
    """launch_run must raise RevolverError if another local LLM run is active."""
    root = project_with_prereqs["root"]

    config = RunConfig(
        problem_version="v1.0",
        llm_name="local-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="local-llm",
        model="codestral:22b",
        source="local",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    # Write a lock file with current PID (simulating active run)
    write_run_lock(
        root,
        "run-existing",
        {
            "run_id": "run-existing",
            "pid": os.getpid(),  # Current PID is alive
            "llm_source": "local",
        },
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
    ):
        mock_global_db.return_value = MagicMock()

        with pytest.raises(RevolverError, match="local LLM run is already active"):
            launch_run(config, project_root=root)


@pytest.mark.unit
def test_launch_run_openevolve_failure(project_with_prereqs: dict) -> None:
    """launch_run must set status to failed on OpenEvolve failure."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    from revolver.models.problem import InstanceTestResult

    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_ok,
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = ProxyTokenUsage()
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.side_effect = ExternalError("OpenEvolve crashed")
        mock_oe_cls.return_value = mock_runner

        with pytest.raises(ExternalError):
            launch_run(config, project_root=root)

    # Verify run was set to failed (not interrupted — OE crash)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT status FROM runs")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "failed"
    finally:
        conn.close()


# ── _post_run_evaluation tests ────────────────────────────────────────────────


@pytest.mark.unit
def test_post_run_evaluation_evaluates_instances(
    project_with_prereqs: dict, capsys: pytest.CaptureFixture
) -> None:
    """_post_run_evaluation must evaluate all training instances."""
    root = project_with_prereqs["root"]
    snapshot_dir = project_with_prereqs["snapshot_dir"]
    dataset_dir = project_with_prereqs["dataset_dir"]

    # Create a program file
    program_path = root / "test_program.py"
    program_path.write_text("# test program\n")

    from revolver.models.problem import InstanceTestResult

    mock_result = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 1.0},
        time_s=0.1,
    )

    with patch("revolver.core.run.eval_run_instance", return_value=mock_result):
        _post_run_evaluation(
            proj_conn=MagicMock(),
            run_id="run-test",
            solution_id="sol-test",
            snapshot_dir=snapshot_dir,
            dataset_path=dataset_dir,
            program_path=program_path,
        )

    captured = capsys.readouterr()
    assert "Post-run evaluation" in captured.err
    assert "2/2 passed" in captured.err


@pytest.mark.unit
def test_post_run_evaluation_warns_on_missing_evaluator(
    project_with_prereqs: dict, capsys: pytest.CaptureFixture
) -> None:
    """_post_run_evaluation must warn if evaluator not found."""
    empty_dir = project_with_prereqs["root"] / "empty_snapshot"
    empty_dir.mkdir()

    _post_run_evaluation(
        proj_conn=MagicMock(),
        run_id="run-test",
        solution_id="sol-test",
        snapshot_dir=empty_dir,
        dataset_path=project_with_prereqs["dataset_dir"],
        program_path=Path("/nonexistent/program.py"),
    )

    captured = capsys.readouterr()
    assert "evaluator not found" in captured.err


@pytest.mark.unit
def test_post_run_evaluation_warns_on_missing_program(
    project_with_prereqs: dict, capsys: pytest.CaptureFixture
) -> None:
    """_post_run_evaluation must warn if program file not found."""
    snapshot_dir = project_with_prereqs["snapshot_dir"]

    _post_run_evaluation(
        proj_conn=MagicMock(),
        run_id="run-test",
        solution_id="sol-test",
        snapshot_dir=snapshot_dir,
        dataset_path=project_with_prereqs["dataset_dir"],
        program_path=Path("/nonexistent/program.py"),
    )

    captured = capsys.readouterr()
    assert "program not found" in captured.err


# ── pre-flight check tests ────────────────────────────────────────────────────


@pytest.mark.unit
def test_preflight_check_pass(project_with_prereqs: dict, capsys: pytest.CaptureFixture) -> None:
    """Pre-flight check with passing evaluator must log success and proceed."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    mock_run_output = RunOutput(best_score=0.95, output_dir=None)
    mock_proxy_usage = ProxyTokenUsage(prompt_tokens=100, completion_tokens=50)

    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.75},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_ok,
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = mock_proxy_usage
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        result = launch_run(config, project_root=root)

    assert result.run_id.startswith("run-")
    captured = capsys.readouterr()
    assert "Pre-flight check passed" in captured.err
    assert "score=0.7500" in captured.err


@pytest.mark.unit
def test_preflight_check_evaluator_crash(project_with_prereqs: dict) -> None:
    """Pre-flight check must abort with RevolverError when evaluator crashes."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    preflight_fail = InstanceTestResult(
        instance_id="instance1.txt",
        status="fail",
        time_s=0.1,
        error="ValueError: intentional failure",
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_fail,
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy_cls.return_value = mock_proxy

        with pytest.raises(RevolverError, match="Pre-flight check failed"):
            launch_run(config, project_root=root)

    # Verify run was set to failed (not interrupted — pre-flight failure)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT status FROM runs")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "failed"
    finally:
        conn.close()


@pytest.mark.unit
def test_preflight_check_timeout(project_with_prereqs: dict) -> None:
    """Pre-flight check must abort with RevolverError on timeout."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    preflight_timeout = InstanceTestResult(
        instance_id="instance1.txt",
        status="timeout",
        time_s=60.0,
        error="Evaluation timed out after 60.0s",
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_timeout,
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy_cls.return_value = mock_proxy

        with pytest.raises(RevolverError, match=r"Pre-flight check failed.*timeout"):
            launch_run(config, project_root=root)

    # Verify run was set to failed (not interrupted — pre-flight timeout)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT status FROM runs")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "failed"
    finally:
        conn.close()


@pytest.mark.unit
def test_preflight_check_score_zero(
    project_with_prereqs: dict, capsys: pytest.CaptureFixture
) -> None:
    """Pre-flight check with score=0 must warn but not abort."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    mock_run_output = RunOutput(best_score=0.0, output_dir=None)
    mock_proxy_usage = ProxyTokenUsage(prompt_tokens=100, completion_tokens=50)

    preflight_zero = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.0},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_zero,
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = mock_proxy_usage
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        result = launch_run(config, project_root=root)

    # Run should proceed (not abort)
    assert result.run_id.startswith("run-")
    captured = capsys.readouterr()
    assert "score=0.0000" in captured.err
    assert "Evolution may not produce improvements" in captured.err
    assert "Pre-flight check passed" in captured.err


@pytest.mark.unit
def test_dry_run_skips_preflight(project_with_prereqs: dict) -> None:
    """launch_run with dry_run=True must not run pre-flight check."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        dry_run=True,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(
        is_valid=True,
        checked_at=datetime.now(UTC),
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.eval_run_instance",
        ) as mock_run_instance,
    ):
        mock_global_db.return_value = MagicMock()
        result = launch_run(config, project_root=root)

    assert result.run_id == "dry-run"
    mock_run_instance.assert_not_called()


# ── resume_run tests ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_resume_run_creates_new_run(project_with_prereqs: dict) -> None:
    """resume_run must create a new run with resumed_from pointing to parent."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    # Create a parent run
    parent_id = "run-20260310-143000"
    parent_run_dir = create_run_dir(root, parent_id)
    (parent_run_dir / "_revolver_evaluator.py").write_text("# wrapper\n")

    # Create the expected checkpoint directory structure
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True)

    # Insert parent run in DB
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=parent_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
        )
    finally:
        conn.close()

    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    mock_run_output = RunOutput(best_score=0.98, output_dir=None)
    mock_proxy_usage = ProxyTokenUsage(prompt_tokens=500, completion_tokens=200)

    from revolver.models.problem import InstanceTestResult

    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_ok,
        ),
        patch("revolver.core.run.count_valid_programs", return_value=5),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = mock_proxy_usage
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        result = resume_run(parent_id, project_root=root)

    assert result.run_id != parent_id
    assert result.run_id.startswith("run-")
    assert result.resumed_from == parent_id
    assert result.problem_version == "v1.0"
    assert result.llm == "test-llm"
    assert result.solution.best_score == 0.98

    # Verify new run dir has wrapper copied
    new_run_dir = root / REVOLVER_DIR / "runs" / result.run_id
    assert (new_run_dir / "_revolver_evaluator.py").exists()

    # Verify checkpoint was copied
    assert (new_run_dir / "oe-checkpoint").is_dir()

    # Verify DB record
    conn = get_project_db(db_path)
    try:
        from revolver.infra.db import get_run as db_get_run

        new_run = db_get_run(conn, result.run_id)
        assert new_run is not None
        assert new_run["resumed_from"] == parent_id
        assert new_run["status"] == "completed"
    finally:
        conn.close()


@pytest.mark.unit
def test_resume_run_preflight_crash(project_with_prereqs: dict) -> None:
    """resume_run must abort with RevolverError when pre-flight check fails."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    # Create a parent run
    parent_id = "run-20260310-143000"
    parent_run_dir = create_run_dir(root, parent_id)
    (parent_run_dir / "_revolver_evaluator.py").write_text("# wrapper\n")

    # Create the expected checkpoint directory structure
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True)

    # Insert parent run in DB
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=parent_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
        )
    finally:
        conn.close()

    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    preflight_fail = InstanceTestResult(
        instance_id="instance1.txt",
        status="fail",
        time_s=0.1,
        error="ValueError: evaluator crashed",
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_fail,
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy_cls.return_value = mock_proxy

        with pytest.raises(RevolverError, match="Pre-flight check failed"):
            resume_run(parent_id, project_root=root)

    # Verify the new run was set to failed in DB (not interrupted — pre-flight failure)
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT status FROM runs WHERE id != ?", (parent_id,))
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "failed"
    finally:
        conn.close()


@pytest.mark.unit
def test_resume_run_invalid_status(project_with_prereqs: dict) -> None:
    """resume_run must raise RevolverError if parent status is 'running'."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    parent_id = "run-20260310-143000"
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=parent_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="running",
        )
    finally:
        conn.close()

    with patch("revolver.core.run.get_global_db") as mock_global_db:
        mock_global_db.return_value = MagicMock()
        with pytest.raises(RevolverError, match="Cannot resume"):
            resume_run(parent_id, project_root=root)


@pytest.mark.unit
def test_resume_run_not_found(project_with_prereqs: dict) -> None:
    """resume_run must raise RevolverError if parent run not found."""
    root = project_with_prereqs["root"]

    with patch("revolver.core.run.get_global_db") as mock_global_db:
        mock_global_db.return_value = MagicMock()
        with pytest.raises(RevolverError, match="not found"):
            resume_run("nonexistent-run", project_root=root)


@pytest.mark.unit
def test_resume_llm_override(project_with_prereqs: dict) -> None:
    """resume_run with llm_name must use the override LLM, not the parent's."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    # Create a parent run using test-llm
    parent_id = "run-20260310-160000"
    parent_run_dir = create_run_dir(root, parent_id)
    (parent_run_dir / "_revolver_evaluator.py").write_text("# wrapper\n")
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True)

    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=parent_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
        )
    finally:
        conn.close()

    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    # The override LLM entry
    override_llm = LLMEntry(
        name="pro-llm",
        model="gemini-pro",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=5.0,
        output_cost_per_mtok=25.0,
        registered_at=datetime.now(UTC),
    )

    mock_run_output = RunOutput(best_score=0.95, output_dir=None)
    mock_proxy_usage = ProxyTokenUsage(prompt_tokens=300, completion_tokens=100)
    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=override_llm),
        patch("revolver.core.run.get_llm", return_value=override_llm),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.eval_run_instance", return_value=preflight_ok),
    ):
        mock_global_db.return_value = MagicMock()
        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = mock_proxy_usage
        mock_proxy_cls.return_value = mock_proxy
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        result = resume_run(parent_id, llm_name="pro-llm", project_root=root)

    # Result must reflect the override LLM
    assert result.llm == "pro-llm"

    # DB record must also store the override LLM
    conn = get_project_db(db_path)
    try:
        from revolver.infra.db import get_run as db_get_run

        new_run = db_get_run(conn, result.run_id)
        assert new_run is not None
        assert new_run["llm"] == "pro-llm"
    finally:
        conn.close()


@pytest.mark.unit
def test_resume_llm_not_found(project_with_prereqs: dict) -> None:
    """resume_run with llm_name pointing to nonexistent LLM must raise RevolverError."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    parent_id = "run-20260310-161000"
    parent_run_dir = create_run_dir(root, parent_id)
    (parent_run_dir / "_revolver_evaluator.py").write_text("# wrapper\n")
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True)

    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=parent_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
        )
    finally:
        conn.close()

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch(
            "revolver.core.run.resolve_llm_or_ensemble",
            side_effect=RevolverError("LLM or ensemble 'nonexistent' not found."),
        ),
        patch("revolver.core.run.get_llm", return_value=None),
    ):
        mock_global_db.return_value = MagicMock()
        with pytest.raises(RevolverError, match="'nonexistent' not found"):
            resume_run(parent_id, llm_name="nonexistent", project_root=root)


@pytest.mark.unit
def test_resume_config_override_single(project_with_prereqs: dict) -> None:
    """resume_run with config_overrides must pass them to build_config."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    parent_id = "run-20260310-162000"
    parent_run_dir = create_run_dir(root, parent_id)
    (parent_run_dir / "_revolver_evaluator.py").write_text("# wrapper\n")
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True)

    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=parent_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
        )
    finally:
        conn.close()

    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    mock_run_output = RunOutput(best_score=0.90, output_dir=None)
    mock_proxy_usage = ProxyTokenUsage(prompt_tokens=400, completion_tokens=150)
    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.build_config", return_value={}) as mock_build_config,
        patch("revolver.core.run.resolve_api_keys", return_value={}),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.eval_run_instance", return_value=preflight_ok),
    ):
        mock_global_db.return_value = MagicMock()
        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = mock_proxy_usage
        mock_proxy_cls.return_value = mock_proxy
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        resume_run(
            parent_id,
            config_overrides=["reasoning_effort=low"],
            project_root=root,
        )

    # Verify build_config was called with config_overrides
    mock_build_config.assert_called_once()
    call_kwargs = mock_build_config.call_args
    assert call_kwargs.kwargs["config_overrides"] == ["reasoning_effort=low"]


@pytest.mark.unit
def test_resume_config_override_multiple(project_with_prereqs: dict) -> None:
    """resume_run with multiple config_overrides must pass all to build_config."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    parent_id = "run-20260310-163000"
    parent_run_dir = create_run_dir(root, parent_id)
    (parent_run_dir / "_revolver_evaluator.py").write_text("# wrapper\n")
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True)

    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=parent_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
        )
    finally:
        conn.close()

    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    mock_run_output = RunOutput(best_score=0.85, output_dir=None)
    mock_proxy_usage = ProxyTokenUsage(prompt_tokens=350, completion_tokens=120)
    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.build_config", return_value={}) as mock_build_config,
        patch("revolver.core.run.resolve_api_keys", return_value={}),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.eval_run_instance", return_value=preflight_ok),
    ):
        mock_global_db.return_value = MagicMock()
        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = mock_proxy_usage
        mock_proxy_cls.return_value = mock_proxy
        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        overrides = ["reasoning_effort=low", "num_islands=3"]
        resume_run(
            parent_id,
            config_overrides=overrides,
            project_root=root,
        )

    # Verify build_config was called with both overrides
    mock_build_config.assert_called_once()
    call_kwargs = mock_build_config.call_args
    assert call_kwargs.kwargs["config_overrides"] == overrides


# ── list_runs tests ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_runs_empty(tmp_project: Path) -> None:
    """list_runs must return empty list when no runs exist."""
    result = list_runs(project_root=tmp_project)
    assert result == []


@pytest.mark.unit
def test_list_runs_with_filters(project_with_prereqs: dict) -> None:
    """list_runs must filter by version, llm, and status."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    conn = get_project_db(db_path)
    try:
        now = datetime.now(UTC)
        insert_run(
            conn,
            run_id="run-001",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=now,
            status="completed",
        )
        insert_run(
            conn,
            run_id="run-002",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=now,
            status="interrupted",
        )
    finally:
        conn.close()

    # List all
    all_runs = list_runs(project_root=root)
    assert len(all_runs) == 2

    # Filter by status
    completed = list_runs(project_root=root, status="completed")
    assert len(completed) == 1
    assert completed[0].run_id == "run-001"

    interrupted = list_runs(project_root=root, status="interrupted")
    assert len(interrupted) == 1
    assert interrupted[0].run_id == "run-002"

    # Filter by version
    v1_runs = list_runs(project_root=root, version="v1.0")
    assert len(v1_runs) == 2

    v99_runs = list_runs(project_root=root, version="v99.0")
    assert len(v99_runs) == 0

    # Filter by llm
    llm_runs = list_runs(project_root=root, llm="test-llm")
    assert len(llm_runs) == 2


# ── get_run_info tests ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_run_info_returns_complete_data(project_with_prereqs: dict) -> None:
    """get_run_info must return full details with solutions and programs."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    run_id = "run-20260310-143000"
    create_run_dir(root, run_id)

    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
            generation_time_s=42.5,
            prompt_tokens=1000,
            completion_tokens=500,
        )
        insert_solution(
            conn,
            solution_id="sol-001",
            run_id=run_id,
            rank=1,
            best_score=0.95,
            alias="best-solution",
        )
    finally:
        conn.close()

    # Write manifest with programs
    manifest_data = {
        "run_id": run_id,
        "programs": [
            {"rank": 1, "score": 0.95, "file": "programs/rank-1.py"},
            {"rank": 2, "score": 0.90, "file": "programs/rank-2.py"},
        ],
    }
    write_run_manifest(root, run_id, manifest_data)

    info = get_run_info(run_id, project_root=root)

    assert info.run_id == run_id
    assert info.problem_version == "v1.0"
    assert info.problem_hash == "hash-v1"
    assert info.llm == "test-llm"
    assert info.llm_model == "gpt-4"
    assert info.dataset == "train-small"
    assert info.dataset_hash == "dataset-hash-1"
    assert info.iterations == 5
    assert info.generation_time_s == 42.5
    assert info.status == "completed"
    assert info.token_usage is not None
    assert info.token_usage.prompt_tokens == 1000
    assert info.token_usage.completion_tokens == 500
    assert info.token_usage.total_tokens == 1500

    # Solutions
    assert len(info.solutions) == 1
    assert info.solutions[0].solution_id == "sol-001"
    assert info.solutions[0].rank == 1
    assert info.solutions[0].alias == "best-solution"

    # Programs
    assert len(info.programs) == 2
    assert info.programs[0].rank == 1
    assert info.programs[1].rank == 2

    # Resume chain
    assert run_id in info.resume_chain


@pytest.mark.unit
def test_get_run_info_not_found(tmp_project: Path) -> None:
    """get_run_info must raise RevolverError if run not found."""
    with pytest.raises(RevolverError, match="not found"):
        get_run_info("nonexistent-run", project_root=tmp_project)


# ── get_run_status tests ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_run_status_no_runs(tmp_project: Path) -> None:
    """get_run_status must return inactive status when no runs exist."""
    status = get_run_status(project_root=tmp_project)

    assert status.active is False
    assert status.run_id is None


@pytest.mark.unit
def test_get_run_status_with_latest_run(project_with_prereqs: dict) -> None:
    """get_run_status must return latest run info when no active locks."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id="run-latest",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
        )
    finally:
        conn.close()

    status = get_run_status(project_root=root)

    assert status.active is False
    assert status.run_id == "run-latest"
    assert status.problem_version == "v1.0"
    assert status.llm == "test-llm"


@pytest.mark.unit
def test_get_run_status_with_active_lock(project_with_prereqs: dict) -> None:
    """get_run_status must detect active runs via lock files."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    run_id = "run-active"
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="running",
        )
    finally:
        conn.close()

    # Write lock with current PID (alive)
    write_run_lock(
        root,
        run_id,
        {"run_id": run_id, "pid": os.getpid(), "llm_source": "remote"},
    )

    status = get_run_status(project_root=root)

    assert status.active is True
    assert run_id in status.run_ids


@pytest.mark.unit
def test_get_run_status_removes_stale_lock(project_with_prereqs: dict) -> None:
    """get_run_status must remove stale locks (dead PIDs)."""
    root = project_with_prereqs["root"]

    # Write lock with a definitely dead PID
    write_run_lock(
        root,
        "run-stale",
        {"run_id": "run-stale", "pid": 999999999, "llm_source": "remote"},
    )

    status = get_run_status(project_root=root)

    assert status.active is False
    # Lock file should have been removed
    lock_file = root / REVOLVER_DIR / "runs" / "locks" / "run-stale.lock"
    assert not lock_file.exists()


@pytest.mark.unit
def test_get_run_status_active_with_checkpoint_progress(project_with_prereqs: dict) -> None:
    """get_run_status must populate iterations_completed and best_score from checkpoint."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    run_id = "run-progress"
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=50,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="running",
        )
    finally:
        conn.close()

    # Write lock with current PID (alive)
    write_run_lock(
        root,
        run_id,
        {"run_id": run_id, "pid": os.getpid(), "llm_source": "remote"},
    )

    # Create checkpoint directory with programs and metadata
    run_dir = root / REVOLVER_DIR / "runs" / run_id
    checkpoint_dir = run_dir / "oe-output" / "checkpoints" / "checkpoint_10"
    programs_dir = checkpoint_dir / "programs"
    programs_dir.mkdir(parents=True)

    # Write metadata pointing to best program
    metadata = {"best_program_id": "prog-001"}
    (checkpoint_dir / "metadata.json").write_text(json.dumps(metadata))

    # Write best program with metrics
    prog_data = {
        "id": "prog-001",
        "metrics": {"combined_score": 42.5, "accuracy": 0.95},
        "generation": 3,
    }
    (programs_dir / "prog-001.json").write_text(json.dumps(prog_data))

    # Write database.json with program entries
    db_entries = [{"id": f"prog-{i:03d}"} for i in range(12)]
    (checkpoint_dir / "database.json").write_text(json.dumps(db_entries))

    status = get_run_status(project_root=root)

    assert status.active is True
    assert status.iterations_completed == 12
    assert status.iterations_total == 50
    assert status.best_score == 42.5


@pytest.mark.unit
def test_get_run_status_active_no_checkpoint(project_with_prereqs: dict) -> None:
    """get_run_status must gracefully handle missing checkpoint (early in run)."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    run_id = "run-no-ckpt"
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=50,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="running",
        )
    finally:
        conn.close()

    # Write lock with current PID (alive), but NO checkpoint directory
    write_run_lock(
        root,
        run_id,
        {"run_id": run_id, "pid": os.getpid(), "llm_source": "remote"},
    )

    status = get_run_status(project_root=root)

    assert status.active is True
    assert status.iterations_completed is None
    assert status.best_score is None
    assert status.iterations_total == 50


@pytest.mark.unit
def test_get_run_status_idle_with_valid_iterations(project_with_prereqs: dict) -> None:
    """get_run_status must show valid_iterations for completed runs in idle status."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id="run-done",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=50,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
        )
        # Set valid_iterations in DB
        conn.execute(
            "UPDATE runs SET valid_iterations = ? WHERE id = ?",
            (35, "run-done"),
        )
        conn.commit()
    finally:
        conn.close()

    status = get_run_status(project_root=root)

    assert status.active is False
    assert status.run_id == "run-done"
    assert status.iterations_completed == 35
    assert status.iterations_total == 50


# ── _collect_programs tests ───────────────────────────────────────────────────


@pytest.mark.unit
def test_collect_programs_from_top_programs(tmp_path: Path) -> None:
    """_collect_programs must find programs in top_programs/ directory."""
    oe_dir = tmp_path / "oe-output"
    top_dir = oe_dir / "top_programs"
    top_dir.mkdir(parents=True)
    (top_dir / "program_0.py").write_text("# best\n")
    (top_dir / "program_1.py").write_text("# second\n")

    programs_dir = tmp_path / "programs"

    programs = _collect_programs(oe_dir, programs_dir)

    assert len(programs) == 2
    assert programs[0].rank == 1
    assert programs[0].file == "programs/rank-1.py"
    assert programs[1].rank == 2
    assert (programs_dir / "rank-1.py").exists()
    assert (programs_dir / "rank-2.py").exists()


@pytest.mark.unit
def test_collect_programs_empty_output(tmp_path: Path) -> None:
    """_collect_programs must return empty list if no programs found."""
    oe_dir = tmp_path / "oe-output"
    oe_dir.mkdir()
    programs_dir = tmp_path / "programs"

    programs = _collect_programs(oe_dir, programs_dir)
    assert programs == []


# ── _is_pid_alive tests ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_is_pid_alive_current_process() -> None:
    """_is_pid_alive must return True for the current process."""
    assert _is_pid_alive(os.getpid()) is True


@pytest.mark.unit
def test_is_pid_alive_dead_process() -> None:
    """_is_pid_alive must return False for a nonexistent PID."""
    assert _is_pid_alive(999999999) is False


# ── Post-run error handling tests (F3 fix) ───────────────────────────────────


@pytest.mark.unit
def test_handle_post_run_failure_sets_completed_with_errors(
    project_with_prereqs: dict,
) -> None:
    """_handle_post_run_failure must set status to completed_with_errors."""
    root = project_with_prereqs["root"]
    db_path = project_with_prereqs["db_path"]

    conn = get_project_db(db_path)
    try:
        run_id = "run-post-err"
        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="running",
        )

        # Create run dir
        run_dir = root / REVOLVER_DIR / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Call handler with an exception
        exc = RuntimeError("DB insert failed")
        _handle_post_run_failure(conn, root, run_id, run_dir, 42.5, exc)

        # Verify status is completed_with_errors
        row = get_run(conn, run_id)
        assert row is not None
        assert row["status"] == "completed_with_errors"
        assert row["generation_time_s"] == 42.5

        # Verify error log was written
        error_log = run_dir / "run-error.log"
        assert error_log.exists()
        content = error_log.read_text()
        assert "RuntimeError" in content
        assert "DB insert failed" in content
    finally:
        conn.close()


@pytest.mark.unit
def test_launch_run_post_processing_failure_sets_completed_with_errors(
    project_with_prereqs: dict,
) -> None:
    """launch_run must set status to completed_with_errors when post-processing fails."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    mock_run_output = RunOutput(
        best_score=0.95,
        best_program="some_program",
        output_dir=None,
    )

    mock_proxy_usage = ProxyTokenUsage(prompt_tokens=1000, completion_tokens=500)

    from revolver.models.problem import InstanceTestResult

    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_ok,
        ),
        patch(
            "revolver.core.run.insert_solution",
            side_effect=RuntimeError("DB constraint error"),
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = mock_proxy_usage
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        with pytest.raises(ExternalError, match="completed_with_errors"):
            launch_run(config, project_root=root)

    # Verify run was set to completed_with_errors (not interrupted)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT status, generation_time_s FROM runs")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "completed_with_errors"
        # generation_time_s should be set (OE completed)
        assert rows[0][1] is not None
        assert rows[0][1] > 0
    finally:
        conn.close()

    # Verify error log was written
    runs_dir = root / REVOLVER_DIR / "runs"
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("run-")]
    assert len(run_dirs) == 1
    error_log = run_dirs[0] / "run-error.log"
    assert error_log.exists()
    content = error_log.read_text()
    assert "RuntimeError" in content


@pytest.mark.unit
def test_launch_run_oe_failure_sets_failed(
    project_with_prereqs: dict,
) -> None:
    """launch_run must set status to failed when OE itself fails (S9-08)."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    from revolver.models.problem import InstanceTestResult

    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_ok,
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = ProxyTokenUsage()
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.side_effect = RuntimeError("OE crashed")
        mock_oe_cls.return_value = mock_runner

        with pytest.raises(ExternalError):
            launch_run(config, project_root=root)

    # Verify run was set to failed (OE didn't complete — S9-08)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT status FROM runs")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "failed"
    finally:
        conn.close()


# ── S8-11: Post-run evaluation message tests ─────────────────────────────────


@pytest.mark.unit
def test_launch_run_post_eval_message(
    project_with_prereqs: dict, capsys: pytest.CaptureFixture
) -> None:
    """launch_run emits 'Running post-run evaluation...' on stderr (S8-11)."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))
    mock_run_output = RunOutput(best_score=0.95, best_program="prog", output_dir=None)
    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.eval_run_instance", return_value=preflight_ok),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = ProxyTokenUsage(prompt_tokens=100, completion_tokens=50)
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        launch_run(config, project_root=root)

    captured = capsys.readouterr()
    assert "Running post-run evaluation..." in captured.err


@pytest.mark.unit
def test_launch_run_post_eval_message_suppressed_when_quiet(
    project_with_prereqs: dict, capsys: pytest.CaptureFixture
) -> None:
    """launch_run suppresses post-eval message when quiet=True (S8-11)."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))
    mock_run_output = RunOutput(best_score=0.95, best_program="prog", output_dir=None)
    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.eval_run_instance", return_value=preflight_ok),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = ProxyTokenUsage(prompt_tokens=100, completion_tokens=50)
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.return_value = mock_run_output
        mock_oe_cls.return_value = mock_runner

        launch_run(config, project_root=root, quiet=True)

    captured = capsys.readouterr()
    assert "Running post-run evaluation..." not in captured.err


# ── S9-08: Run failure status tracking ───────────────────────────────────────


@pytest.mark.integration
def test_run_oe_failure_marks_failed(project_with_prereqs: dict) -> None:
    """OE exception during run must set status='failed', write run-error.log (S9-08)."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_ok,
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = ProxyTokenUsage()
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.side_effect = RuntimeError("OE crashed: missing API key")
        mock_oe_cls.return_value = mock_runner

        with pytest.raises(ExternalError):
            launch_run(config, project_root=root)

    # Verify status is 'failed' in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT status FROM runs")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "failed"
    finally:
        conn.close()

    # Verify run-error.log exists with traceback content
    runs_dir = root / REVOLVER_DIR / "runs"
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("run-")]
    assert len(run_dirs) == 1
    error_log = run_dirs[0] / "run-error.log"
    assert error_log.exists(), "run-error.log must be written on OE failure"
    content = error_log.read_text()
    assert "RuntimeError" in content
    assert "OE crashed: missing API key" in content

    # Verify lock file was removed
    lock_files = list((root / REVOLVER_DIR / "locks").glob("*.lock"))
    assert len(lock_files) == 0, "Lock file must be removed on failure"


@pytest.mark.integration
def test_run_keyboard_interrupt_marks_interrupted(project_with_prereqs: dict) -> None:
    """KeyboardInterrupt during OE must set status='interrupted', not 'failed' (S9-08)."""
    root = project_with_prereqs["root"]
    config = RunConfig(
        problem_version="v1.0",
        llm_name="test-llm",
        dataset_name="train-small",
        iterations=5,
    )

    from revolver.models.dataset import IntegrityReport
    from revolver.models.llm import LLMEntry
    from revolver.models.problem import InstanceTestResult

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=datetime.now(UTC),
    )

    good_integrity = IntegrityReport(is_valid=True, checked_at=datetime.now(UTC))

    preflight_ok = InstanceTestResult(
        instance_id="instance1.txt",
        status="pass",
        metrics={"combined_score": 0.5},
        time_s=0.1,
    )

    with (
        patch("revolver.core.run.get_global_db") as mock_global_db,
        patch("revolver.core.run.resolve_llm_or_ensemble", return_value=llm),
        patch("revolver.core.run.get_llm", return_value=llm),
        patch(
            "revolver.core.run.verify_dataset_integrity",
            return_value=good_integrity,
        ),
        patch(
            "revolver.core.run.resolve_dataset_path",
            return_value=project_with_prereqs["dataset_dir"],
        ),
        patch("revolver.core.run.OpenEvolveRunner") as mock_oe_cls,
        patch("revolver.core.run.TokenCountingProxy") as mock_proxy_cls,
        patch(
            "revolver.core.run.eval_run_instance",
            return_value=preflight_ok,
        ),
    ):
        mock_global_db.return_value = MagicMock()

        mock_proxy = MagicMock()
        mock_proxy.start.return_value = "http://127.0.0.1:9999"
        mock_proxy.stop.return_value = ProxyTokenUsage()
        mock_proxy_cls.return_value = mock_proxy

        mock_runner = MagicMock()
        mock_runner.run.side_effect = KeyboardInterrupt()
        mock_oe_cls.return_value = mock_runner

        with pytest.raises(KeyboardInterrupt):
            launch_run(config, project_root=root)

    # Verify status is 'interrupted' (not 'failed') in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT status FROM runs")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "interrupted"
    finally:
        conn.close()

    # Verify lock file was removed
    lock_files = list((root / REVOLVER_DIR / "locks").glob("*.lock"))
    assert len(lock_files) == 0, "Lock file must be removed on interrupt"


# ── _determine_run_status tests ──────────────────────────────────────────────


@pytest.mark.unit
class TestDetermineRunStatus:
    """L2 tests for _determine_run_status() helper."""

    def test_run_all_errors_status_failed_zero_valid(self) -> None:
        """A run with valid_iterations=0 should be 'failed'."""
        assert _determine_run_status(valid_iters=0, total_iters=3) == "failed"

    def test_run_all_errors_status_failed_none_valid(self) -> None:
        """A run with valid_iterations=None should be 'failed'."""
        assert _determine_run_status(valid_iters=None, total_iters=3) == "failed"

    def test_run_all_errors_status_failed_zero_total(self) -> None:
        """A run with valid_iterations=0 and total_iterations=0 should be 'failed'."""
        assert _determine_run_status(valid_iters=0, total_iters=0) == "failed"

    def test_run_low_valid_ratio_status_completed_with_errors(self) -> None:
        """A run with valid_iterations=1 out of 20 (5%) should be 'completed_with_errors'."""
        assert _determine_run_status(valid_iters=1, total_iters=20) == "completed_with_errors"

    def test_run_normal_valid_ratio_status_completed(self) -> None:
        """A run with valid_iterations=15 out of 20 (75%) should be 'completed'."""
        assert _determine_run_status(valid_iters=15, total_iters=20) == "completed"

    def test_run_exactly_at_threshold_status_completed(self) -> None:
        """A run at exactly MIN_VALID_ITERATION_RATIO should be 'completed'."""
        # 10% = exactly at threshold → completed (not strictly less)
        total = 100
        valid = int(total * MIN_VALID_ITERATION_RATIO)  # 10
        assert _determine_run_status(valid_iters=valid, total_iters=total) == "completed"

    def test_run_just_below_threshold_status_completed_with_errors(self) -> None:
        """A run just below MIN_VALID_ITERATION_RATIO should be 'completed_with_errors'."""
        # 9/100 = 9% < 10%
        assert _determine_run_status(valid_iters=9, total_iters=100) == "completed_with_errors"

    def test_run_all_valid_status_completed(self) -> None:
        """A run where all iterations are valid should be 'completed'."""
        assert _determine_run_status(valid_iters=20, total_iters=20) == "completed"
