"""Simple evaluator fixture for testing.

Returns a score based on the length of the program source code.
"""

from __future__ import annotations


def evaluate(program_path: str) -> dict[str, float]:
    """Evaluate a program by measuring source code length."""
    with open(program_path) as f:
        source = f.read()
    return {"combined_score": len(source) / 100.0}
