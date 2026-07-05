"""Core solution logic: listing, detail, alias, extract, show, diff.

Implements the domain layer for ``revolver solution`` commands:
- ``list_solutions()`` — list with filters (FR-SOL-001, FR-SOL-002)
- ``get_solution_info()`` — full lineage JOIN + siblings (FR-SOL-003..005, FR-SOL-009)
- ``get_solution_program_path()`` — resolve solution to validated program path
- ``show_solution()`` — read program source code (FR-SOL-003, FR-SOL-004)
- ``diff_solutions()`` — unified diff between two solutions
- ``set_alias()`` — unique alias (FR-SOL-006, FR-SOL-007)
- ``extract_solution()`` — promote program to solution (FR-SOL-011..013,
  FR-SOL-021)

Traceable to: DES-005 §7, DES-006, FR-SOL-001..013, FR-SOL-021.
"""

from __future__ import annotations

from datetime import UTC, datetime
import difflib
from pathlib import Path
import sqlite3
import sys
from typing import TYPE_CHECKING

from revolver.core.exceptions import DuplicateNameError, RevolverError, ValidationError

if TYPE_CHECKING:
    from revolver.infra.backends.base import RecoveredProgram
from revolver.infra.db import (
    delete_solution as db_delete_solution,
    get_project_db,
    get_resume_chain,
    get_run,
    get_solution,
    get_solution_by_alias,
    get_solution_detail,
    get_solutions_for_run,
    list_solutions as db_list_solutions,
    update_solution_alias,
)
from revolver.infra.store import REVOLVER_DIR, RUNS_DIR, find_project_root
from revolver.models.solution import Solution


def list_solutions(
    *,
    version: str | None = None,
    llm: str | None = None,
    rank: int | None = None,
    project_root: Path | None = None,
) -> list[dict[str, object]]:
    """List solutions with optional filters.

    Returns dicts from ``db.list_solutions`` JOIN (solution + run columns).

    Args:
        version: Filter by problem version tag.
        llm: Filter by LLM registry name.
        rank: Filter by solution rank.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A list of dicts with solution and run columns.
    """
    root = project_root or find_project_root(Path.cwd())
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        return db_list_solutions(conn, version=version, llm=llm, rank=rank)
    finally:
        conn.close()


def get_solution_info(
    id_or_alias: str,
    *,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Get full solution detail (lineage, eval, siblings).

    Uses ``db.get_solution_detail()`` for the main JOIN.
    Also calls ``db.get_solutions_for_run()`` for siblings (FR-SOL-009).
    Includes ``program_path`` derivation (FR-SOL-004).

    Args:
        id_or_alias: Solution ID or alias to look up.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A dict with full solution detail including lineage, program path,
        and sibling solutions.

    Raises:
        RevolverError: If the solution is not found.
    """
    root = project_root or find_project_root(Path.cwd())
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        detail = get_solution_detail(conn, id_or_alias)
        if detail is None:
            raise RevolverError(f"Solution not found: {id_or_alias}")

        run_id = str(detail["run_id"])
        rank_raw = detail["rank"]
        rank = int(str(rank_raw)) if rank_raw is not None else 1

        # Derive program path (FR-SOL-004)
        program_path = root / REVOLVER_DIR / RUNS_DIR / run_id / "programs" / f"rank-{rank}.py"
        detail["program_path"] = str(program_path)

        # Get sibling solutions (FR-SOL-009)
        siblings = get_solutions_for_run(conn, run_id)
        detail["siblings"] = [
            {
                "id": s.id,
                "rank": s.rank,
                "best_score": s.best_score,
                "alias": s.alias,
            }
            for s in siblings
            if s.id != str(detail["id"])
        ]

        # Build resume chain if the run was resumed (F6)
        run_record = get_run(conn, run_id)
        if run_record is not None:
            resumed_from = run_record.get("resumed_from")
            if resumed_from is not None:
                detail["resumed_from"] = str(resumed_from)
                chain = get_resume_chain(conn, run_id)
                detail["resume_chain"] = chain

        return detail
    finally:
        conn.close()


def get_solution_program_path(
    id_or_alias: str,
    *,
    project_root: Path | None = None,
) -> tuple[Solution, Path]:
    """Resolve a solution and return its validated program file path.

    Looks up the solution by ID or alias, derives the program path from
    the run directory structure, and validates that the file exists on disk.

    Args:
        id_or_alias: Solution ID or alias to look up.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A tuple of (Solution, Path) where Path is the validated program file path.

    Raises:
        RevolverError: If the solution is not found or the program file
            does not exist on disk.
    """
    root = project_root or find_project_root(Path.cwd())
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        sol = get_solution(conn, id_or_alias)
        if sol is None:
            raise RevolverError(f"Solution not found: {id_or_alias}")

        rank = sol.rank if sol.rank is not None else 1
        program_path = root / REVOLVER_DIR / RUNS_DIR / sol.run_id / "programs" / f"rank-{rank}.py"
        if not program_path.exists():
            raise RevolverError(f"Program file not found: {program_path}")

        return sol, program_path
    finally:
        conn.close()


def show_solution(
    id_or_alias: str,
    *,
    project_root: Path | None = None,
) -> tuple[str, Solution]:
    """Read the program source code for a solution.

    Resolves the solution by ID or alias, locates the program file
    via ``program_path``, and returns its contents as a string along
    with the resolved Solution object.

    Args:
        id_or_alias: Solution ID or alias to look up.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A tuple of (source_code, Solution).

    Raises:
        RevolverError: If the solution is not found or the program file
            does not exist on disk.
    """
    sol, program_path = get_solution_program_path(id_or_alias, project_root=project_root)
    return program_path.read_text(encoding="utf-8"), sol


def diff_solutions(
    a: str,
    b: str,
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Compute a unified diff between two solution programs.

    Resolves both solutions by ID or alias, reads their program files,
    and returns the output of :func:`difflib.unified_diff`.

    Args:
        a: First solution ID or alias.
        b: Second solution ID or alias.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A list of diff lines (may be empty if programs are identical).

    Raises:
        RevolverError: If either solution is not found or its program file
            does not exist on disk.
    """
    root = project_root or find_project_root(Path.cwd())
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        sol_a = get_solution(conn, a)
        if sol_a is None:
            raise RevolverError(f"Solution not found: {a}")

        sol_b = get_solution(conn, b)
        if sol_b is None:
            raise RevolverError(f"Solution not found: {b}")

        rank_a = sol_a.rank if sol_a.rank is not None else 1
        rank_b = sol_b.rank if sol_b.rank is not None else 1

        path_a = root / REVOLVER_DIR / RUNS_DIR / sol_a.run_id / "programs" / f"rank-{rank_a}.py"
        path_b = root / REVOLVER_DIR / RUNS_DIR / sol_b.run_id / "programs" / f"rank-{rank_b}.py"

        if not path_a.exists():
            raise RevolverError(f"Program file not found: {path_a}")
        if not path_b.exists():
            raise RevolverError(f"Program file not found: {path_b}")

        lines_a = path_a.read_text(encoding="utf-8").splitlines(keepends=True)
        lines_b = path_b.read_text(encoding="utf-8").splitlines(keepends=True)

        label_a = sol_a.alias or sol_a.id
        label_b = sol_b.alias or sol_b.id

        return list(
            difflib.unified_diff(
                lines_a,
                lines_b,
                fromfile=label_a,
                tofile=label_b,
            )
        )
    finally:
        conn.close()


def set_alias(
    id_or_alias: str,
    alias: str,
    *,
    project_root: Path | None = None,
) -> None:
    """Set alias on a solution. Resolve by ID or alias first, then update.

    Args:
        id_or_alias: Solution ID or alias to resolve.
        alias: The new alias to set (must be unique).
        project_root: Explicit project root, or ``None`` to auto-detect.

    Raises:
        RevolverError: If the solution is not found.
        DuplicateNameError: If the alias is already in use.
    """
    if not alias or not alias.strip():
        raise ValidationError("Alias must not be empty")

    root = project_root or find_project_root(Path.cwd())
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        sol = get_solution(conn, id_or_alias)
        if sol is None:
            raise RevolverError(f"Solution not found: {id_or_alias}")
        update_solution_alias(conn, sol.id, alias)
    finally:
        conn.close()


def _recover_checkpoint_program(
    run: dict[str, object],
    run_dir: Path,
) -> RecoveredProgram:
    """Recover the best program of an interrupted/failed run from its checkpoint.

    Resolves the run's backend and asks it to recover its best program from the
    latest checkpoint (B7 / FR-RUN-051). This is a **read-only** step: it does
    not write to disk, so it is safe to call before the alias/duplicate/force
    validation (the recovered code is materialized only once validation passes,
    to avoid leaving a stray ``rank-1.py`` behind on an aborted command).

    Returns:
        The recovered :class:`RecoveredProgram` (code + score).

    Raises:
        CheckpointRecoveryError: No usable checkpoint exists yet.
        RecoveryNotSupportedError: The backend has no checkpoint recovery.
    """
    from revolver.infra.backends.base import get_backend

    backend_name = str(run.get("backend") or "openevolve")
    backend = get_backend(backend_name)
    return backend.recover_best_from_checkpoint(run_dir)


def extract_solution(
    run_id: str,
    rank: int,
    *,
    alias: str | None = None,
    force: bool = False,
    from_checkpoint: bool = False,
    program_id: str | None = None,
    project_root: Path | None = None,
) -> Solution:
    """Promote a stored program to a new solution DB entry.

    1. Verify run exists and is completed
    2. Verify program file exists at ``.revolver/runs/<run_id>/programs/rank-<rank>.py``
    3. Validate: check alias uniqueness and duplicate ``(run_id, rank)``
    4. Generate unique ID: ``sol-YYYYMMDD-HHMMSS`` (with counter for collisions)
    5. Atomically delete old solution (if ``force=True``) and insert new one
    6. Return the new :class:`Solution`

    When ``force=True`` and a solution already exists for the same
    ``(run_id, rank)`` pair, the old solution is replaced atomically:
    the delete and insert happen within a single SQLite transaction so
    that a crash or insert failure cannot leave the database without a
    solution for that ``(run_id, rank)`` slot.

    When ``from_checkpoint=True`` **and** the run is ``interrupted``/``failed``,
    the best program is recovered from the backend's latest checkpoint (B7 /
    FR-RUN-051) instead of read from ``programs/rank-<rank>.py``: the recovered
    code is materialized to that path and its score is stored as
    ``best_score``. The default (``from_checkpoint=False``) is unchanged —
    interrupted/failed runs are still rejected.

    Ranks > 1 and ``program_id`` are gated on the run backend's
    ``capabilities().top_n_extraction`` (FR-SOL-021, ADR-007): a non-capable
    backend (OpenEvolve — consciously deferred, #299) is rejected with a
    clear "not supported" error before any other validation.

    Args:
        run_id: ID of the run that produced the program.
        rank: Program rank within the run (1 = best). Ranks > 1 require a
            backend with ``top_n_extraction`` support (FR-SOL-021).
        alias: Optional alias for the new solution.
        force: If ``True``, replace an existing solution for the same
            ``(run_id, rank)`` pair instead of raising an error.
        from_checkpoint: If ``True``, recover the best program from the
            backend's latest checkpoint when the run is interrupted/failed.
            Recovery is rank-1 only: incompatible with ``rank > 1`` and
            ``program_id``.
        program_id: Backend program ID of the population program to promote
            (FR-SOL-021, top-N-capable backends only). Mutually exclusive
            with ranks > 1.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The newly created :class:`Solution`.

    Raises:
        RevolverError: If the run is not found or the program file does not
            exist, or ``program_id`` extraction is requested (the on-demand
            backend path lands with S18-16).
        ValidationError: If rank is <= 0, ``program_id`` is combined with a
            rank > 1 or ``from_checkpoint``, the requested rank/program_id is
            not supported on the run's backend (FR-SOL-021), the run is not
            completed, or the program file does not exist.
        CheckpointRecoveryError: ``from_checkpoint`` requested but no usable
            checkpoint exists yet.
        RecoveryNotSupportedError: ``from_checkpoint`` requested on a backend
            without checkpoint recovery (e.g. ShinkaEvolve).
        DuplicateNameError: If ``force=False`` and ``(run_id, rank)`` already
            extracted, or if the alias is already in use.
    """
    if rank <= 0:
        raise ValidationError(f"Rank must be > 0, got {rank}")
    if program_id is not None and rank != 1:
        raise ValidationError("rank and program_id are mutually exclusive")
    if from_checkpoint and (rank != 1 or program_id is not None):
        raise ValidationError(
            "--from-checkpoint only recovers the best (rank-1) program; "
            "it cannot be combined with --rank > 1 or --program-id."
        )

    root = project_root or find_project_root(Path.cwd())
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # 1. Verify run exists and is completed
        run = get_run(conn, run_id)
        if run is None:
            raise RevolverError(f"Run not found: {run_id}")

        # 1b. FR-SOL-021 top-N gate: promoting a rank > 1 or an arbitrary
        # program id requires a backend that advertises reliable top-N
        # extraction (capabilities().top_n_extraction — ADR-007 v0.18
        # amendment). OpenEvolve consciously stays non-capable in v0.18
        # (checkpoint-granularity limit + pre-U13 ordering, #299).
        if rank > 1 or program_id is not None:
            from revolver.infra.backends.base import get_backend

            backend_name = str(run.get("backend") or "openevolve")
            if not get_backend(backend_name).capabilities().top_n_extraction:
                raise ValidationError(
                    f"Top-N extraction is not supported on backend '{backend_name}'."
                )
            if program_id is not None:
                # Stage 1 (S18-15) ships the CLI surface and the capability
                # gate; the on-demand backend extraction path
                # (ShinkaBackend.extract_ranked_program) lands with S18-16.
                raise RevolverError(
                    "Extraction by program id is not implemented yet for "
                    f"backend '{backend_name}'."
                )

        run_dir = root / REVOLVER_DIR / RUNS_DIR / run_id
        program_path = run_dir / "programs" / f"rank-{rank}.py"

        status = run.get("status")
        # B7 / FR-RUN-051: --from-checkpoint recovers the best program of an
        # interrupted/failed run. The default path is unchanged: only completed
        # (or completed_with_errors) runs are extractable.
        use_checkpoint = from_checkpoint and status in ("interrupted", "failed")
        if from_checkpoint and status in ("completed", "completed_with_errors"):
            # The flag is a no-op on a run that already has extractable
            # programs — say so rather than silently ignoring it.
            sys.stderr.write(
                f"Note: run '{run_id}' is {status}; --from-checkpoint ignored, "
                "using the normal rank-1 program.\n"
            )

        recovered: RecoveredProgram | None = None
        if not use_checkpoint:
            if status not in ("completed", "completed_with_errors"):
                if from_checkpoint:
                    raise ValidationError(
                        f"Run '{run_id}' has status '{status}'. --from-checkpoint "
                        "only applies to 'interrupted' or 'failed' runs."
                    )
                raise ValidationError(f"Run '{run_id}' is not completed (status: '{status}')")

            # 2. Verify program file exists
            if not program_path.exists():
                raise ValidationError(f"Program file not found: {program_path}")
        else:
            # Read-only recovery (fails fast on an unrecoverable run). The
            # recovered code is materialized to disk only *after* the
            # alias/duplicate/force validation below, so an aborted command
            # never leaves a stray rank-1.py behind.
            recovered = _recover_checkpoint_program(run, run_dir)

        # 3. Pre-mutation validation: check alias uniqueness and duplicates
        # Alias check MUST happen before any delete to avoid data loss on
        # alias collision when force=True.
        if alias:
            existing_alias = get_solution_by_alias(conn, alias)
            if existing_alias is not None:
                raise DuplicateNameError(f"Alias '{alias}' is already in use")

        existing = get_solutions_for_run(conn, run_id)
        old_solution_id: str | None = None
        for s in existing:
            if s.rank == rank:
                if force:
                    old_solution_id = s.id
                else:
                    raise DuplicateNameError(
                        f"Solution already exists for run={run_id}, rank={rank}"
                    )

        # 3b. Materialize the recovered checkpoint program now that all
        # validation has passed — never before (finding #2: no stray file on
        # an aborted command).
        recovered_score: float | None = None
        if recovered is not None:
            program_path.parent.mkdir(parents=True, exist_ok=True)
            program_path.write_text(recovered.code, encoding="utf-8")
            recovered_score = recovered.score

        # 4. Generate unique ID
        solution_id = _generate_solution_id(conn)

        # 5. best_score: unavailable from a program file, but recovered from
        # the checkpoint metadata when --from-checkpoint was used (B7).
        best_score: float | None = recovered_score

        # 6. Atomic delete + insert within a single transaction.
        # We use raw SQL instead of the helper functions to avoid
        # separate commits (db_delete_solution and insert_solution each
        # commit independently).
        with conn:
            if old_solution_id is not None:
                # Cascade-delete eval data for the old solution
                conn.execute(
                    "DELETE FROM eval_instances WHERE eval_id IN "
                    "(SELECT eval_id FROM eval_metadata WHERE solution_id = ?)",
                    (old_solution_id,),
                )
                conn.execute(
                    "DELETE FROM eval_metadata WHERE solution_id = ?",
                    (old_solution_id,),
                )
                cursor = conn.execute(
                    "DELETE FROM solutions WHERE id = ?",
                    (old_solution_id,),
                )
                if cursor.rowcount == 0:
                    raise RevolverError(f"Failed to delete existing solution: {old_solution_id}")

            conn.execute(
                "INSERT INTO solutions (id, run_id, rank, best_score, alias) "
                "VALUES (?, ?, ?, ?, ?)",
                (solution_id, run_id, rank, best_score, alias),
            )

        # 7. Return the new Solution
        return Solution(
            id=solution_id,
            run_id=run_id,
            rank=rank,
            best_score=best_score,
            alias=alias,
        )
    finally:
        conn.close()


def delete_solution(
    solution_id_or_alias: str,
    *,
    project_root: Path | None = None,
) -> str:
    """Delete a solution and its associated eval data.

    This is a pure domain function — confirmation prompts belong in the CLI
    layer.  It resolves alias → ID, deletes the solution, and returns the
    deleted ID.

    Args:
        solution_id_or_alias: Solution ID or alias to delete.
        project_root: Project root directory (auto-detected if None).

    Returns:
        The solution ID that was deleted.

    Raises:
        RevolverError: If solution not found.
    """
    root = project_root or find_project_root(Path.cwd())
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # Resolve alias-or-id using the same pattern as set_alias / get_solution_info
        sol = get_solution(conn, solution_id_or_alias)
        if sol is None:
            raise RevolverError(f"Solution not found: {solution_id_or_alias}")

        solution_id = sol.id

        deleted = db_delete_solution(conn, solution_id)
        if not deleted:
            raise RevolverError(f"Solution not found: {solution_id}")  # pragma: no cover

        return solution_id
    finally:
        conn.close()


def _generate_solution_id(conn: sqlite3.Connection) -> str:
    """Generate a unique solution ID: ``sol-YYYYMMDD-HHMMSS``.

    Appends a counter suffix (``-2``, ``-3``, ...) if a collision is found.

    Args:
        conn: An open project database connection.

    Returns:
        A unique solution ID string.
    """
    now = datetime.now(UTC)
    base = f"sol-{now.strftime('%Y%m%d-%H%M%S')}"

    # Check for collision
    cursor = conn.execute("SELECT id FROM solutions WHERE id = ?", (base,))
    if cursor.fetchone() is None:
        return base

    # Add counter suffix
    counter = 2
    while True:
        candidate = f"{base}-{counter}"
        cursor = conn.execute("SELECT id FROM solutions WHERE id = ?", (candidate,))
        if cursor.fetchone() is None:
            return candidate
        counter += 1
