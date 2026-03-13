"""Simple initial program fixture for testing."""

from __future__ import annotations


def solve(data: list[int]) -> int:
    """Sum the input data.

    # --- EVOLVE-BLOCK-START ---
    This block will be evolved by OpenEvolve.
    """
    total = sum(data)
    # --- EVOLVE-BLOCK-END ---
    return total
