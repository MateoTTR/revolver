"""Dual-mode evaluator fixture for testing.

Supports both per-instance and aggregated evaluation modes.
"""

from __future__ import annotations

import os


def evaluate_instance(program_path: str) -> dict[str, float]:
    """Per-instance evaluation — preferred mode."""
    _instance_path = os.environ.get("REVOLVER_INSTANCE_PATH", "")
    with open(program_path) as f:
        source = f.read()
    return {"combined_score": len(source) / 100.0}


def evaluate(program_path: str) -> dict[str, float]:
    """Aggregated evaluation — legacy mode."""
    with open(program_path) as f:
        source = f.read()
    return {"combined_score": len(source) / 100.0}
