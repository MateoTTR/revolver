"""Evaluator fixture with evaluate_instance() only.

Used to test wrapper generation in instance mode.
"""

from __future__ import annotations


def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    """Evaluate one program against one instance."""
    with open(program_path) as f:
        source = f.read()
    return {"combined_score": len(source) / 100.0, "instance": 1.0}
