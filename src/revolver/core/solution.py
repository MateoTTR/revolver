"""Core solution logic: listing, detail, alias, extract, show, diff.

Implements the domain layer for ``revolver solution`` commands:
- ``list_solutions()`` — list with filters (FR-SOL-001, FR-SOL-002)
- ``get_solution_info()`` — full lineage JOIN + siblings (FR-SOL-003..005, FR-SOL-009)
- ``get_solution_program_path()`` — resolve solution to validated program path
- ``show_solution()`` — read program source code (FR-SOL-003, FR-SOL-004)
- ``diff_solutions()`` — unified diff between two solutions
- ``set_alias()`` — unique alias (FR-SOL-006, FR-SOL-007)
- ``extract_solution()`` — promote program to solution (FR-SOL-011..013)

Traceable to: DES-005 §7, DES-006, FR-SOL-001..013.
"""

from __future__ import annotations

from datetime import UTC, datetime
import difflib
from pathlib import Path
import sqlite3

from revolver.core.exceptions import DuplicateNameError, RevolverError, ValidationError
from revolver.infra.db import (
    delete_solution as db_delete_solution,
    get_project_db,
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


def extract_solution(
    run_id: str,
    rank: int,
    *,
    alias: str | None = None,
    force: bool = False,
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

    Args:
        run_id: ID of the run that produced the program.
        rank: Program rank within the run.
        alias: Optional alias for the new solution.
        force: If ``True``, replace an existing solution for the same
            ``(run_id, rank)`` pair instead of raising an error.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The newly created :class:`Solution`.

    Raises:
        RevolverError: If the run is not found or the program file does not exist.
        ValidationError: If rank is <= 0, the run is not completed, or the
            program file does not exist.
        DuplicateNameError: If ``force=False`` and ``(run_id, rank)`` already
            extracted, or if the alias is already in use.
    """
    if rank <= 0:
        raise ValidationError(f"Rank must be > 0, got {rank}")

    root = project_root or find_project_root(Path.cwd())
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # 1. Verify run exists and is completed
        run = get_run(conn, run_id)
        if run is None:
            raise RevolverError(f"Run not found: {run_id}")
        if run.get("status") not in ("completed", "completed_with_errors"):
            raise ValidationError(
                f"Run '{run_id}' is not completed (status: '{run.get('status')}')"
            )

        # 2. Verify program file exists
        program_path = root / REVOLVER_DIR / RUNS_DIR / run_id / "programs" / f"rank-{rank}.py"
        if not program_path.exists():
            raise ValidationError(f"Program file not found: {program_path}")

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

        # 4. Generate unique ID
        solution_id = _generate_solution_id(conn)

        # 5. best_score: not available from file, set None
        best_score: float | None = None

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
