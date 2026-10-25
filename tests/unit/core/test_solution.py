"""L1 unit tests for core solution logic (extract_solution).

Tests cover:
- extract_solution(rank=0): raises ValidationError (rank guard)
- extract_solution(force=True): atomic delete + insert
- extract_solution(force=True) with alias collision: alias check before delete
- the FR-SOL-021 top-N capability gate (rank > 1 / program_id resolve the
  run backend's ``capabilities().top_n_extraction`` — S18-15)

Traceable to: FR-SOL-011..013, FR-SOL-021, DES-005 section 7,
PR #122 review findings, sprint-018 S18-15/S18-16.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.core.exceptions import DuplicateNameError, ValidationError
from revolver.core.project import init_project
from revolver.core.solution import extract_solution, get_solution_info
from revolver.infra.db import (
    get_project_db,
    get_solution,
    insert_run,
    insert_solution,
)
from revolver.infra.store import REVOLVER_DIR, RUNS_DIR
from tests.fixtures.programs_sqlite import SHINKA_OUTPUT_SUBDIR, build_programs_db


def _setup_project_with_run(
    tmp_path: Path,
    *,
    run_id: str = "run-test-001",
    status: str = "completed",
    rank: int = 1,
    backend: str = "openevolve",
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
            backend=backend,
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


class TestExtractSolutionTopNGate:
    """Tests for the FR-SOL-021 top-N capability gate (S18-15).

    The gate resolves the run's backend and checks
    ``capabilities().top_n_extraction`` — a static per-backend matrix, so no
    engine package (and no ``is_available`` probe) is involved.
    """

    @pytest.mark.unit
    def test_rank_2_on_openevolve_raises(self, tmp_path: Path) -> None:
        """rank=2 on an OpenEvolve run raises the capability-gate error."""
        root = _setup_project_with_run(tmp_path, backend="openevolve")
        with pytest.raises(
            ValidationError,
            match="Top-N extraction is not supported on backend 'openevolve'",
        ):
            extract_solution(
                "run-test-001",
                2,
                project_root=root,
            )

    @pytest.mark.unit
    def test_program_id_on_openevolve_raises(self, tmp_path: Path) -> None:
        """program_id on an OpenEvolve run raises the capability-gate error."""
        root = _setup_project_with_run(tmp_path, backend="openevolve")
        with pytest.raises(
            ValidationError,
            match="Top-N extraction is not supported on backend 'openevolve'",
        ):
            extract_solution(
                "run-test-001",
                1,
                program_id="prog-42",
                project_root=root,
            )

    @pytest.mark.unit
    @pytest.mark.shinkaevolve
    def test_rank_2_on_shinka_passes_gate(self, tmp_path: Path) -> None:
        """rank=2 on a Shinka run passes the gate and promotes rank-2.

        Existing-file fast path: the rank-2 program file already exists on
        disk, so the backend store is never consulted (the on-demand
        ``programs.sqlite`` path is covered by the S18-16 tests).
        """
        root = _setup_project_with_run(tmp_path, backend="shinka", rank=2)
        sol = extract_solution(
            "run-test-001",
            2,
            alias="second-best",
            project_root=root,
        )
        assert sol.rank == 2
        assert sol.run_id == "run-test-001"

    @pytest.mark.unit
    @pytest.mark.shinkaevolve
    def test_program_id_on_shinka_missing_store_raises(self, tmp_path: Path) -> None:
        """program_id on a Shinka run without programs.sqlite errors clearly.

        The gate passes (``top_n_extraction=True``) but the run dir has no
        backend program store to resolve the id from (S18-16).
        """
        root = _setup_project_with_run(tmp_path, backend="shinka")
        with pytest.raises(ValidationError, match="No backend program store"):
            extract_solution(
                "run-test-001",
                1,
                program_id="prog-42",
                project_root=root,
            )

    @pytest.mark.unit
    @pytest.mark.shinkaevolve
    def test_program_id_on_shinka_resolves_rank_and_score(self, tmp_path: Path) -> None:
        """program_id resolves to its rank and records the store score (S18-16).

        ``prog-gen2-best`` is the best scored fixture program: the id
        resolves to rank 1, whose ``rank-1.py`` already exists on disk —
        the existing file is not rewritten (no clobber), but the store's
        ``combined_score`` (0.91) is still recorded as ``best_score``.
        """
        root = _setup_project_with_run(tmp_path, backend="shinka")
        run_dir = root / REVOLVER_DIR / RUNS_DIR / "run-test-001"
        build_programs_db(run_dir / SHINKA_OUTPUT_SUBDIR / "programs.sqlite")

        sol = extract_solution(
            "run-test-001",
            1,
            program_id="prog-gen2-best",
            project_root=root,
        )
        assert sol.rank == 1
        assert sol.best_score == pytest.approx(0.91)
        # The pre-existing rank-1.py was not rewritten.
        rank1 = run_dir / "programs" / "rank-1.py"
        assert rank1.read_text(encoding="utf-8") == "def solve(): pass\n"

    @pytest.mark.unit
    def test_program_id_with_rank_n_raises(self, tmp_path: Path) -> None:
        """program_id combined with rank != 1 is rejected (mutual exclusion)."""
        root = _setup_project_with_run(tmp_path)
        with pytest.raises(ValidationError, match="mutually exclusive"):
            extract_solution(
                "run-test-001",
                2,
                program_id="prog-42",
                project_root=root,
            )

    @pytest.mark.unit
    def test_from_checkpoint_with_rank_n_raises(self, tmp_path: Path) -> None:
        """from_checkpoint with rank > 1 is rejected (recovery is rank-1 only)."""
        root = _setup_project_with_run(tmp_path, status="interrupted")
        with pytest.raises(ValidationError, match="rank-1"):
            extract_solution(
                "run-test-001",
                2,
                from_checkpoint=True,
                project_root=root,
            )

    @pytest.mark.unit
    def test_from_checkpoint_with_program_id_raises(self, tmp_path: Path) -> None:
        """from_checkpoint with program_id is rejected (recovery is rank-1 only)."""
        root = _setup_project_with_run(tmp_path, status="interrupted")
        with pytest.raises(ValidationError, match="rank-1"):
            extract_solution(
                "run-test-001",
                1,
                from_checkpoint=True,
                program_id="prog-42",
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


class TestGetSolutionInfoProgramPath:
    """FR-SOL-004: ``program_path`` is derived from the run directory and the rank."""

    @pytest.mark.unit
    def test_program_path_derived_from_run_dir_and_rank(self, tmp_path: Path) -> None:
        """A rank-2 solution resolves to ``<run dir>/programs/rank-2.py``."""
        root = _setup_project_with_run(tmp_path, run_id="run-test-002", rank=2)
        conn = get_project_db(root / REVOLVER_DIR / "revolver.db")
        try:
            insert_solution(
                conn,
                solution_id="sol-rank-2",
                run_id="run-test-002",
                rank=2,
                best_score=0.5,
            )
        finally:
            conn.close()

        info = get_solution_info("sol-rank-2", project_root=root)

        expected = root / REVOLVER_DIR / RUNS_DIR / "run-test-002" / "programs" / "rank-2.py"
        assert info["program_path"] == str(expected)
        assert expected.is_file()
