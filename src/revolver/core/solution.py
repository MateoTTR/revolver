"""Core solution logic: listing, detail, alias, extract.

Implements the domain layer for ``revolver solution`` commands:
- ``list_solutions()`` — list with filters (FR-SOL-001, FR-SOL-002)
- ``get_solution_info()`` — full lineage JOIN + siblings (FR-SOL-003..005, FR-SOL-009)
- ``set_alias()`` — unique alias (FR-SOL-006, FR-SOL-007)
- ``extract_solution()`` — promote program to solution (FR-SOL-011..013)

Traceable to: DES-005 §7, DES-006, FR-SOL-001..013.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from revolver.core.exceptions import DuplicateNameError, RevolverError, ValidationError
from revolver.infra.db import (
    delete_solution as db_delete_solution,
)
from revolver.infra.db import (
    get_project_db,
    get_run,
    get_solution,
    get_solution_by_alias,
    get_solution_detail,
    get_solutions_for_run,
    insert_solution,
    update_solution_alias,
)
from revolver.infra.db import (
    list_solutions as db_list_solutions,
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
    project_root: Path | None = None,
) -> Solution:
    """Promote a stored program to a new solution DB entry.

    1. Verify run exists
    2. Verify program file exists at ``.revolver/runs/<run_id>/programs/rank-<rank>.py``
    3. Generate unique ID: ``sol-YYYYMMDD-HHMMSS`` (with counter for collisions)
    4. Read best_score from the program's OE output if available
    5. Insert via ``db.insert_solution()``
    6. Return the new :class:`Solution`

    Args:
        run_id: ID of the run that produced the program.
        rank: Program rank within the run.
        alias: Optional alias for the new solution.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The newly created :class:`Solution`.

    Raises:
        RevolverError: If the run is not found or the program file does not exist.
        DuplicateNameError: If (run_id, rank) already extracted or alias is duplicate.
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
        if run.get("status") != "completed":
            raise ValidationError(
                f"Run '{run_id}' is not completed (status: '{run.get('status')}')"
            )

        # 2. Verify program file exists
        program_path = root / REVOLVER_DIR / RUNS_DIR / run_id / "programs" / f"rank-{rank}.py"
        if not program_path.exists():
            raise ValidationError(f"Program file not found: {program_path}")

        # 3. Generate unique ID
        solution_id = _generate_solution_id(conn)

        # 4. best_score: not available from file, set None
        best_score: float | None = None

        # 5. Pre-insert validation: check duplicates before INSERT
        existing = get_solutions_for_run(conn, run_id)
        for s in existing:
            if s.rank == rank:
                raise DuplicateNameError(f"Solution already exists for run={run_id}, rank={rank}")
        if alias:
            existing_alias = get_solution_by_alias(conn, alias)
            if existing_alias is not None:
                raise DuplicateNameError(f"Alias '{alias}' is already in use")

        # 6. Insert via db.insert_solution()
        insert_solution(
            conn,
            solution_id=solution_id,
            run_id=run_id,
            rank=rank,
            best_score=best_score,
            alias=alias,
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
    force: bool = False,
    is_json_mode: bool = False,
    project_root: Path | None = None,
) -> str:
    """Delete a solution and its associated eval data.

    Args:
        solution_id_or_alias: Solution ID or alias to delete.
        force: If True, skip confirmation prompt.
        is_json_mode: If True and not force, raise error (no interactive prompt).
        project_root: Project root directory (auto-detected if None).

    Returns:
        The solution ID that was deleted.

    Raises:
        RevolverError: If solution not found.
        ValidationError: If JSON mode without --force.
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
        display_name = sol.alias or sol.id

        # JSON mode without --force → error (no interactive prompt available)
        if is_json_mode and not force:
            raise ValidationError("Use --force to delete in JSON mode (no interactive prompt)")

        # Interactive confirmation unless --force
        if not force:
            import sys

            sys.stderr.write(f"Delete solution '{display_name}'? [y/N] ")
            sys.stderr.flush()
            answer = input().strip().lower()
            if answer not in ("y", "yes"):
                raise RevolverError("Aborted.")

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
