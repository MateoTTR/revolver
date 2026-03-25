"""L1 unit tests for core solution logic (extract_solution).

Tests cover:
- extract_solution(rank=0): raises ValidationError (rank guard)
- extract_solution(force=True): atomic delete + insert
- extract_solution(force=True) with alias collision: alias check before delete

Traceable to: FR-SOL-011..013, DES-005 section 7, PR #122 review findings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.core.exceptions import DuplicateNameError, ValidationError
from revolver.core.project import init_project
from revolver.core.solution import extract_solution
from revolver.infra.db import (
    get_project_db,
    get_solution,
    insert_run,
    insert_solution,
)
from revolver.infra.store import REVOLVER_DIR, RUNS_DIR


def _setup_project_with_run(
    tmp_path: Path,
    *,
    run_id: str = "run-test-001",
    status: str = "completed",
    rank: int = 1,
) -> Path:
    """Initialize a project, create a completed run, and write a program file.

    Returns the project root path.
    """
    init_project(tmp_path, "test-project")
    db_path = tmp_path / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # Insert problem version and dataset required by FK constraints
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO problem_versions (tag, hash, message, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("v1.0", "hash-v1.0", "Version v1.0", now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO datasets "
            "(name, path, split, storage, description, "
            "global_hash, instance_count, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("train-small", "/data/train", "train", "reference", "", "hash-ds", 10, now),
        )
        conn.commit()

        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="hash-v1.0",
            dataset_hash="hash-ds",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status=status,
            generation_time_s=30.0,
        )
    finally:
        conn.close()

    # Create program file
    programs_dir = tmp_path / REVOLVER_DIR / RUNS_DIR / run_id / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    (programs_dir / f"rank-{rank}.py").write_text("def solve(): pass\n", encoding="utf-8")
    return tmp_path


class TestExtractSolutionRankValidation:
    """Tests for the rank validation guard in extract_solution."""

    @pytest.mark.unit
    def test_rank_zero_raises_validation_error(self, tmp_path: Path) -> None:
        """extract_solution(rank=0) raises ValidationError.

        Validates that the rank > 0 guard works at the domain layer,
        independent of CLI argument parsing.
        """
        root = _setup_project_with_run(tmp_path)
        with pytest.raises(ValidationError, match="Rank must be > 0"):
            extract_solution(
                "run-test-001",
                0,
                project_root=root,
            )

    @pytest.mark.unit
    def test_rank_negative_raises_validation_error(self, tmp_path: Path) -> None:
        """extract_solution(rank=-1) raises ValidationError."""
        root = _setup_project_with_run(tmp_path)
        with pytest.raises(ValidationError, match="Rank must be > 0"):
            extract_solution(
                "run-test-001",
                -1,
                project_root=root,
            )


class TestExtractSolutionForceAtomicity:
    """Tests for atomic delete+insert behavior when force=True."""

    @pytest.mark.unit
    def test_force_replaces_existing_solution(self, tmp_path: Path) -> None:
        """force=True deletes old solution and inserts new one atomically."""
        root = _setup_project_with_run(tmp_path)

        # First extract: create initial solution
        sol1 = extract_solution(
            "run-test-001",
            1,
            alias="first-extract",
            project_root=root,
        )
        assert sol1.alias == "first-extract"

        # Second extract with force: should replace
        sol2 = extract_solution(
            "run-test-001",
            1,
            alias="replaced",
            force=True,
            project_root=root,
        )
        assert sol2.alias == "replaced"
        assert sol2.id != sol1.id

        # Verify old solution is gone and new one exists
        db_path = root / REVOLVER_DIR / "revolver.db"
        conn = get_project_db(db_path)
        try:
            assert get_solution(conn, sol1.id) is None
            assert get_solution(conn, sol2.id) is not None
        finally:
            conn.close()

    @pytest.mark.unit
    def test_force_alias_collision_does_not_delete_existing(self, tmp_path: Path) -> None:
        """When force=True but alias is taken, the old solution is NOT deleted.

        The alias check happens before the delete, so a DuplicateNameError
        is raised without any mutation.
        """
        root = _setup_project_with_run(tmp_path, rank=1)

        # Create a second run to hold the alias-owning solution
        db_path = root / REVOLVER_DIR / "revolver.db"
        conn = get_project_db(db_path)
        try:
            insert_run(
                conn,
                run_id="run-other",
                problem_version="v1.0",
                llm="test-llm",
                dataset="train-small",
                iterations=10,
                problem_hash="hash-v1.0",
                dataset_hash="hash-ds",
                llm_model="gpt-4",
                created_at=datetime.now(UTC),
                status="completed",
                generation_time_s=10.0,
            )
            insert_solution(
                conn,
                solution_id="sol-other",
                run_id="run-other",
                rank=1,
                alias="taken-alias",
            )
        finally:
            conn.close()

        # First extract for run-test-001
        sol1 = extract_solution(
            "run-test-001",
            1,
            project_root=root,
        )

        # Try force extract with alias collision — should raise without deleting
        with pytest.raises(DuplicateNameError, match="already in use"):
            extract_solution(
                "run-test-001",
                1,
                alias="taken-alias",
                force=True,
                project_root=root,
            )

        # Original solution must still exist (no data loss)
        conn = get_project_db(db_path)
        try:
            assert get_solution(conn, sol1.id) is not None
        finally:
            conn.close()

    @pytest.mark.unit
    def test_force_without_existing_solution(self, tmp_path: Path) -> None:
        """force=True on a (run_id, rank) with no existing solution works fine."""
        root = _setup_project_with_run(tmp_path)

        sol = extract_solution(
            "run-test-001",
            1,
            alias="new-sol",
            force=True,
            project_root=root,
        )
        assert sol.alias == "new-sol"
        assert sol.run_id == "run-test-001"
        assert sol.rank == 1
