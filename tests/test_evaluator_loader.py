"""Tests for the evaluator loader (S2-07)."""

from __future__ import annotations

from pathlib import Path

import pytest

from revolver.core.exceptions import EvaluatorLoadError
from revolver.infra.evaluator_loader import load_evaluator

FIXTURES = Path(__file__).parent / "fixtures"


class TestLoadEvaluator:
    """Tests for load_evaluator()."""

    def test_load_valid_evaluator(self) -> None:
        """Loading evaluator_simple.py succeeds and has evaluate()."""
        module = load_evaluator(FIXTURES / "evaluator_simple.py")
        assert hasattr(module, "evaluate")
        assert callable(module.evaluate)

    def test_load_evaluate_instance_only(self) -> None:
        """Loading evaluator_instance.py succeeds with only evaluate_instance()."""
        module = load_evaluator(FIXTURES / "evaluator_instance.py")
        assert not hasattr(module, "evaluate")
        assert hasattr(module, "evaluate_instance")
        assert callable(module.evaluate_instance)

    def test_load_dualmode_evaluator(self) -> None:
        """Loading evaluator_dualmode.py exposes both evaluate and evaluate_instance."""
        module = load_evaluator(FIXTURES / "evaluator_dualmode.py")
        assert callable(module.evaluate)
        assert callable(module.evaluate_instance)

    def test_load_both_evaluator(self) -> None:
        """Loading evaluator_both.py succeeds with both functions."""
        module = load_evaluator(FIXTURES / "evaluator_both.py")
        assert callable(module.evaluate)
        assert callable(module.evaluate_instance)

    def test_load_neither_evaluator(self) -> None:
        """Loading evaluator_neither.py raises EvaluatorLoadError."""
        with pytest.raises(EvaluatorLoadError, match="evaluate"):
            load_evaluator(FIXTURES / "evaluator_neither.py")

    def test_load_missing_evaluate_function(self, tmp_path: Path) -> None:
        """A module without evaluate() or evaluate_instance() raises EvaluatorLoadError."""
        bad = tmp_path / "no_evaluate.py"
        bad.write_text("def hello(): pass\n")
        with pytest.raises(EvaluatorLoadError, match="evaluate"):
            load_evaluator(bad)

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        """A non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_evaluator(tmp_path / "missing.py")

    def test_load_syntax_error(self, tmp_path: Path) -> None:
        """A file with a syntax error raises EvaluatorLoadError."""
        bad = tmp_path / "bad_syntax.py"
        bad.write_text("def broken(\n")
        with pytest.raises(EvaluatorLoadError, match="Failed to import"):
            load_evaluator(bad)
