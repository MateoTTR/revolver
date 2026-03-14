"""Pydantic model for solution entities.

A solution is a lightweight logical reference pointing to a specific
program within a run: ``(run_id, rank)``. It has no directory of its own;
the program file is resolved via ``.revolver/runs/<run_id>/programs/rank-<N>.py``.

The ``UNIQUE(run_id, rank)`` invariant is enforced at the database level
(see DES-001 §3.6) to guarantee that each rank appears at most once per run.
Alias uniqueness is also enforced at the database level (``alias TEXT UNIQUE``).

Traceable to: DES-001 §3.6 (solutions table), DES-005 §8.
"""

from __future__ import annotations

from pydantic import BaseModel


class Solution(BaseModel):
    """A solution reference stored in the project database.

    A solution is a pointer to a specific ranked program produced by an
    OpenEvolve run. The rank-1 solution is auto-created on run completion;
    additional solutions can be extracted on demand via
    ``revolver solution extract``.

    The ``UNIQUE(run_id, rank)`` constraint in the database ensures that
    each rank appears at most once per run.

    Attributes:
        id: Unique solution identifier (e.g. ``"sol-20260310-143000"``).
        run_id: ID of the run that produced this solution.
        rank: Program rank within the run (1 = best).
        best_score: Best score achieved by this program (``None`` if unavailable).
        alias: Optional user-given alias (unique across all solutions).
    """

    id: str
    run_id: str
    rank: int
    best_score: float | None = None
    alias: str | None = None
