"""Dynamic module loader for evaluator Python files.

Loads an evaluator file as a Python module and validates that it
exposes a callable ``evaluate(program_path)`` function.

Traceable to: DES-006 (Evaluation Loop), FR-EVL-001.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from revolver.core.exceptions import EvaluatorLoadError


def load_evaluator(path: Path) -> ModuleType:
    """Dynamically import a Python file as an evaluator module.

    The module must define at least an ``evaluate(program_path)`` callable.

    Args:
        path: Path to the evaluator ``.py`` file.

    Returns:
        The imported module.

    Raises:
        FileNotFoundError: If *path* does not exist.
        EvaluatorLoadError: If the module fails to import or lacks
            a callable ``evaluate`` function.
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

    if not hasattr(module, "evaluate") or not callable(module.evaluate):
        raise EvaluatorLoadError("Evaluator must define an 'evaluate(program_path)' function")

    return module
