"""Evaluator fixture with both evaluate() and evaluate_instance().

When both are present, evaluate() takes priority (legacy mode).
"""

from __future__ import annotations


def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    """Per-instance evaluation."""
    with open(program_path) as f:
        source = f.read()
    return {"combined_score": len(source) / 100.0}


def evaluate(program_path: str) -> dict[str, float]:
    """Global evaluate — legacy pattern takes priority."""
    with open(program_path) as f:
        source = f.read()
    return {"combined_score": len(source) / 100.0, "legacy": 1.0}
