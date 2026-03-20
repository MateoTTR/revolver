"""L1 unit tests for iteration success rate tracking — Sprint 006c.

Covers:
- count_valid_programs() with a mock database.json file
- count_valid_programs() returns None for missing/corrupt file
- RunManifest/RunResult/RunSummary/RunInfo with valid_iterations
- DB round-trip for valid_iterations
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from revolver.infra.db import (
    get_project_db,
    get_run,
    insert_run,
    update_run_valid_iterations,
)
from revolver.infra.openevolve import count_valid_programs
from revolver.models.run import (
    RunInfo,
    RunManifest,
    RunResult,
    RunSummary,
    SolutionResult,
)

# ── count_valid_programs tests ───────────────────────────────────────────────


@pytest.mark.unit
def test_count_valid_programs_list(tmp_path: Path) -> None:
    """count_valid_programs counts entries in a JSON list."""
    db_file = tmp_path / "database.json"
    programs = [
        {"id": 1, "code": "x = 1", "score": 0.5},
        {"id": 2, "code": "x = 2", "score": 0.7},
        {"id": 3, "code": "x = 3", "score": 0.9},
    ]
    db_file.write_text(json.dumps(programs))

    result = count_valid_programs(tmp_path)
    assert result == 3


@pytest.mark.unit
def test_count_valid_programs_dict_with_programs_key(tmp_path: Path) -> None:
    """count_valid_programs counts entries under 'programs' key."""
    db_file = tmp_path / "database.json"
    data = {
        "programs": [
            {"id": 1, "score": 0.5},
            {"id": 2, "score": 0.8},
        ],
        "metadata": {"version": 1},
    }
    db_file.write_text(json.dumps(data))

    result = count_valid_programs(tmp_path)
    assert result == 2


@pytest.mark.unit
def test_count_valid_programs_in_subdirectory(tmp_path: Path) -> None:
    """count_valid_programs finds database.json in a subdirectory."""
    checkpoint_dir = tmp_path / "checkpoint_5"
    checkpoint_dir.mkdir()
    db_file = checkpoint_dir / "database.json"
    programs = [{"id": i} for i in range(10)]
    db_file.write_text(json.dumps(programs))

    result = count_valid_programs(tmp_path)
    assert result == 10


@pytest.mark.unit
def test_count_valid_programs_missing_file(tmp_path: Path) -> None:
    """count_valid_programs returns None when no database.json exists."""
    result = count_valid_programs(tmp_path)
    assert result is None


@pytest.mark.unit
def test_count_valid_programs_nonexistent_dir() -> None:
    """count_valid_programs returns None for nonexistent directory."""
    result = count_valid_programs(Path("/nonexistent/path"))
    assert result is None


@pytest.mark.unit
def test_count_valid_programs_corrupt_json(tmp_path: Path) -> None:
    """count_valid_programs returns None for corrupt JSON."""
    db_file = tmp_path / "database.json"
    db_file.write_text("{not valid json!!!}")

    result = count_valid_programs(tmp_path)
    assert result is None


@pytest.mark.unit
def test_count_valid_programs_empty_list(tmp_path: Path) -> None:
    """count_valid_programs returns 0 for empty list."""
    db_file = tmp_path / "database.json"
    db_file.write_text("[]")

    result = count_valid_programs(tmp_path)
    assert result == 0


# ── Model tests ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_run_manifest_valid_iterations() -> None:
    """RunManifest accepts valid_iterations field."""
    now = datetime(2026, 3, 20, 14, 0, 0, tzinfo=UTC)
    manifest = RunManifest(
        run_id="run-1",
        created_at=now,
        iterations=100,
        valid_iterations=85,
        problem_version="v1.0",
        problem_hash="sha256:abc",
        dataset="train",
        dataset_hash="sha256:def",
        llm="test-llm",
        llm_model="test-model",
    )
    assert manifest.valid_iterations == 85


@pytest.mark.unit
def test_run_manifest_valid_iterations_default_none() -> None:
    """RunManifest defaults valid_iterations to None."""
    now = datetime(2026, 3, 20, 14, 0, 0, tzinfo=UTC)
    manifest = RunManifest(
        run_id="run-1",
        created_at=now,
        iterations=100,
        problem_version="v1.0",
        problem_hash="sha256:abc",
        dataset="train",
        dataset_hash="sha256:def",
        llm="test-llm",
        llm_model="test-model",
    )
    assert manifest.valid_iterations is None


@pytest.mark.unit
def test_run_result_valid_iterations() -> None:
    """RunResult accepts valid_iterations field."""
    sol = SolutionResult(solution_id="sol-1", run_id="run-1", rank=1, best_score=0.9)
    result = RunResult(
        run_id="run-1",
        solution=sol,
        programs_stored=3,
        problem_version="v1.0",
        llm="test",
        dataset="train",
        iterations=50,
        valid_iterations=42,
        generation_time_s=60.0,
    )
    assert result.valid_iterations == 42


@pytest.mark.unit
def test_run_summary_valid_iterations() -> None:
    """RunSummary accepts valid_iterations field."""
    now = datetime(2026, 3, 20, 14, 0, 0, tzinfo=UTC)
    summary = RunSummary(
        run_id="run-1",
        problem_version="v1.0",
        llm="test",
        dataset="train",
        iterations=100,
        valid_iterations=80,
        status="completed",
        created_at=now,
    )
    assert summary.valid_iterations == 80


@pytest.mark.unit
def test_run_info_valid_iterations() -> None:
    """RunInfo accepts valid_iterations field."""
    now = datetime(2026, 3, 20, 14, 0, 0, tzinfo=UTC)
    info = RunInfo(
        run_id="run-1",
        problem_version="v1.0",
        problem_hash="sha256:abc",
        llm="test",
        llm_model="test-model",
        dataset="train",
        dataset_hash="sha256:def",
        iterations=100,
        valid_iterations=90,
        status="completed",
        created_at=now,
    )
    assert info.valid_iterations == 90


# ── DB round-trip tests ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_db_insert_run_with_valid_iterations(tmp_path: Path) -> None:
    """Run inserted with valid_iterations is retrieved correctly."""
    db_path = tmp_path / "project.db"
    conn = get_project_db(db_path)
    try:
        # Need a problem version and dataset first
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) "
            "VALUES ('v1.0', 'sha256:abc', '', '2026-03-20T00:00:00')"
        )
        conn.execute(
            "INSERT INTO datasets (name, path, split, storage, description, "
            "global_hash, instance_count, registered_at) "
            "VALUES ('train', '/data', 'train', 'reference', '', 'sha256:def', 10, "
            "'2026-03-20T00:00:00')"
        )
        conn.commit()

        now = datetime(2026, 3, 20, 14, 0, 0, tzinfo=UTC)
        insert_run(
            conn,
            run_id="run-test-001",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train",
            iterations=100,
            problem_hash="sha256:abc",
            dataset_hash="sha256:def",
            llm_model="test-model",
            created_at=now,
            valid_iterations=85,
        )

        row = get_run(conn, "run-test-001")
        assert row is not None
        assert row["valid_iterations"] == 85
    finally:
        conn.close()


@pytest.mark.unit
def test_db_update_run_valid_iterations(tmp_path: Path) -> None:
    """update_run_valid_iterations updates the column correctly."""
    db_path = tmp_path / "project.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) "
            "VALUES ('v1.0', 'sha256:abc', '', '2026-03-20T00:00:00')"
        )
        conn.execute(
            "INSERT INTO datasets (name, path, split, storage, description, "
            "global_hash, instance_count, registered_at) "
            "VALUES ('train', '/data', 'train', 'reference', '', 'sha256:def', 10, "
            "'2026-03-20T00:00:00')"
        )
        conn.commit()

        now = datetime(2026, 3, 20, 14, 0, 0, tzinfo=UTC)
        insert_run(
            conn,
            run_id="run-test-002",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train",
            iterations=50,
            problem_hash="sha256:abc",
            dataset_hash="sha256:def",
            llm_model="test-model",
            created_at=now,
        )

        # Initially None
        row = get_run(conn, "run-test-002")
        assert row is not None
        assert row["valid_iterations"] is None

        # Update
        update_run_valid_iterations(conn, "run-test-002", 42)

        row = get_run(conn, "run-test-002")
        assert row is not None
        assert row["valid_iterations"] == 42
    finally:
        conn.close()
