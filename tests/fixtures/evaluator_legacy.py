"""Legacy evaluator fixture for testing.

Uses the global evaluate() pattern without per-instance support.
"""

from __future__ import annotations


def evaluate(program_path: str) -> dict[str, float]:
    """Global evaluate — legacy pattern."""
    with open(program_path) as f:
        source = f.read()
    return {"combined_score": len(source) / 100.0, "line_count": float(source.count("\n"))}
