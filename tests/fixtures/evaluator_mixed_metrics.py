"""Evaluator fixture emitting a mix of numeric and non-numeric metrics.

Used to test that the OpenEvolve wrapper aggregation (B1 / FR-EVL-021)
tolerates non-numeric fields (e.g. a diagnostic ``error`` string, or a
``bool`` flag) rather than crashing ``statistics.mean`` on them.

The instance file's *name* selects the shape of the returned metrics so a
single fixture can exercise both the mixed-type and fully-numeric cases:

- an instance file named ``bad*`` returns a numeric ``combined_score``
  alongside a non-numeric ``error`` string and a ``bool`` ``passed`` flag;
- any other instance returns a fully numeric dict.
"""

from __future__ import annotations


def evaluate_instance(program_path: str, instance_path: str) -> dict:
    """Return metrics whose shape depends on the instance file name."""
    from pathlib import Path

    name = Path(instance_path).name
    if name.startswith("bad"):
        # Non-numeric fields mixed in with the numeric combined_score:
        # ``error`` is a str and ``passed`` is a bool (int subclass) — both
        # must be dropped from the aggregate, not crash it.
        return {"combined_score": 0.5, "error": "boom", "passed": True}
    return {"combined_score": 1.0, "accuracy": 0.8}
