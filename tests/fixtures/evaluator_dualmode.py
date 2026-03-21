"""Dual-mode evaluator fixture for testing.

Supports both per-instance and aggregated evaluation modes.
"""

from __future__ import annotations


def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    """Per-instance evaluation — preferred mode."""
    with open(program_path) as f:
        source = f.read()
    return {"combined_score": len(source) / 100.0}


def evaluate(program_path: str) -> dict[str, float]:
    """Aggregated evaluation — legacy mode."""
    with open(program_path) as f:
        source = f.read()
    return {"combined_score": len(source) / 100.0}
