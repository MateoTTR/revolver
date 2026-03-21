"""Dynamic module loader for evaluator Python files.

Loads an evaluator file as a Python module and validates that it
exposes at least one of the following callable entry points:

- ``evaluate(program_path)`` — legacy/aggregated evaluation
- ``evaluate_instance(program_path, instance_path)`` — per-instance evaluation

Traceable to: DES-006 (Evaluation Loop), FR-EVL-001.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from revolver.core.exceptions import EvaluatorLoadError


def load_evaluator(path: Path) -> ModuleType:
    """Dynamically import a Python file as an evaluator module.

    The module must define at least one of:

    - ``evaluate(program_path)`` — legacy/aggregated evaluation
    - ``evaluate_instance(program_path, instance_path)`` — per-instance evaluation

    Args:
        path: Path to the evaluator ``.py`` file.

    Returns:
        The imported module.

    Raises:
        FileNotFoundError: If *path* does not exist.
        EvaluatorLoadError: If the module fails to import or lacks
            both ``evaluate`` and ``evaluate_instance`` callables.
    """
    if not path.exists():
        raise FileNotFoundError(f"Evaluator file not found: {path}")

    spec = importlib.util.spec_from_file_location("evaluator", path)
    if spec is None or spec.loader is None:
        raise EvaluatorLoadError(f"Cannot load evaluator from {path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise EvaluatorLoadError(f"Failed to import evaluator: {exc}") from exc

    has_evaluate = hasattr(module, "evaluate") and callable(module.evaluate)
    has_evaluate_instance = hasattr(module, "evaluate_instance") and callable(
        module.evaluate_instance
    )
    if not has_evaluate and not has_evaluate_instance:
        raise EvaluatorLoadError(
            "Evaluator must define 'evaluate(program_path)' "
            "and/or 'evaluate_instance(program_path, instance_path)'"
        )

    return module
