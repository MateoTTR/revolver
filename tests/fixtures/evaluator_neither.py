"""Evaluator fixture with neither evaluate() nor evaluate_instance().

Used to test that generate_wrapper() raises EvaluatorError.
"""

from __future__ import annotations


def some_other_function(data: str) -> str:
    """A function that is not an evaluator entry point."""
    return data.upper()
