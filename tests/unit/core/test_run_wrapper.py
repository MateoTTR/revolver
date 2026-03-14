"""Tests for generate_wrapper() (S4-03).

Verifies wrapper evaluator generation for instance mode, legacy mode,
and error cases.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from revolver.core.exceptions import EvaluatorLoadError
from revolver.core.run import WRAPPER_FILENAME, generate_wrapper

pytestmark = [pytest.mark.unit]

FIXTURES = Path(__file__).parents[2] / "fixtures"


class TestGenerateWrapperInstanceMode:
    """Tests for generate_wrapper() with evaluate_instance() evaluators."""

    def test_generates_wrapper(self, tmp_path: Path) -> None:
        """Evaluator with evaluate_instance() triggers wrapper generation."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)

        assert result.exists()
        assert result.name == WRAPPER_FILENAME
        assert result.parent == output_dir

    def test_wrapper_contains_evaluate_function(self, tmp_path: Path) -> None:
        """Generated wrapper defines an evaluate() function."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)
        code = result.read_text()

        assert "def evaluate(program_path" in code
        assert "def _log_instance(" in code

    def test_wrapper_imports_from_snapshot(self, tmp_path: Path) -> None:
        """Generated wrapper imports evaluate_instance from the snapshot dir."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)
        code = result.read_text()

        assert str(snapshot_dir) in code
        assert "from evaluator import evaluate_instance" in code

    def test_wrapper_is_valid_python(self, tmp_path: Path) -> None:
        """Generated wrapper compiles without syntax errors."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)
        code = result.read_text()

        # compile() raises SyntaxError if the code is invalid
        compile(code, str(result), "exec")

    def test_wrapper_uses_statistics_mean(self, tmp_path: Path) -> None:
        """Generated wrapper uses statistics.mean for aggregation."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)
        code = result.read_text()

        assert "statistics.mean" in code

    def test_wrapper_has_sqlite_side_channel(self, tmp_path: Path) -> None:
        """Generated wrapper includes SQLite side-channel logging."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)
        code = result.read_text()

        assert "REVOLVER_INSTANCE_LOG" in code
        assert "sqlite3" in code
        assert "instance_log" in code


class TestGenerateWrapperLegacyMode:
    """Tests for generate_wrapper() with evaluate() evaluators (legacy mode)."""

    def test_copies_legacy_evaluator(self, tmp_path: Path) -> None:
        """Evaluator with evaluate() is copied as-is (legacy mode)."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_legacy.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)

        assert result.exists()
        assert result.name == WRAPPER_FILENAME
        # Content should match the original evaluator
        original = (snapshot_dir / "evaluator.py").read_text()
        copied = result.read_text()
        assert copied == original

    def test_both_functions_uses_legacy(self, tmp_path: Path) -> None:
        """Evaluator with both evaluate() and evaluate_instance() uses legacy."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_both.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)

        # Should be a copy, not a generated wrapper
        original = (snapshot_dir / "evaluator.py").read_text()
        copied = result.read_text()
        assert copied == original


class TestGenerateWrapperErrors:
    """Tests for generate_wrapper() error cases."""

    def test_no_evaluator_function(self, tmp_path: Path) -> None:
        """Evaluator with neither function raises EvaluatorLoadError."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_neither.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        with pytest.raises(EvaluatorLoadError, match="evaluate"):
            generate_wrapper(snapshot_dir, output_dir)

    def test_missing_evaluator_file(self, tmp_path: Path) -> None:
        """Missing evaluator file raises FileNotFoundError."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        # No evaluator.py in snapshot_dir

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="evaluator"):
            generate_wrapper(snapshot_dir, output_dir)

    def test_syntax_error_in_evaluator(self, tmp_path: Path) -> None:
        """Evaluator with syntax error raises EvaluatorLoadError."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        (snapshot_dir / "evaluator.py").write_text("def broken(\n")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        with pytest.raises(EvaluatorLoadError, match="Failed to import"):
            generate_wrapper(snapshot_dir, output_dir)
