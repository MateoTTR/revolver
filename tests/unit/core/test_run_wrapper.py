"""Tests for generate_wrapper() (S4-03).

Verifies wrapper evaluator generation for instance mode, legacy mode,
and error cases.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
from types import ModuleType

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


class TestGenerateWrapperTimeout:
    """Tests for per-instance timeout propagation into wrapper (S8-03)."""

    def test_wrapper_has_timeout(self, tmp_path: Path) -> None:
        """Wrapper generated with timeout_per_instance contains the timeout value."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir, timeout_per_instance=30)
        code = result.read_text()

        assert "_TIMEOUT_PER_INSTANCE = 30" in code
        assert "multiprocessing" in code
        assert "proc.kill()" in code
        assert "proc.join(" in code
        assert "TimeoutError" in code

    def test_wrapper_has_float_timeout(self, tmp_path: Path) -> None:
        """Wrapper generated with float timeout_per_instance renders correctly."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir, timeout_per_instance=45.5)
        code = result.read_text()

        assert "_TIMEOUT_PER_INSTANCE = 45.5" in code

    def test_wrapper_no_timeout(self, tmp_path: Path) -> None:
        """Wrapper generated without timeout has _TIMEOUT_PER_INSTANCE = None."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)
        code = result.read_text()

        assert "_TIMEOUT_PER_INSTANCE = None" in code

    def test_wrapper_no_timeout_is_valid_python(self, tmp_path: Path) -> None:
        """Wrapper without timeout compiles without syntax errors."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)
        code = result.read_text()
        compile(code, str(result), "exec")

    def test_wrapper_with_timeout_is_valid_python(self, tmp_path: Path) -> None:
        """Wrapper with timeout compiles without syntax errors."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir, timeout_per_instance=30)
        code = result.read_text()
        compile(code, str(result), "exec")

    def test_wrapper_no_timeout_calls_directly(self, tmp_path: Path) -> None:
        """When timeout is None, _call_evaluate_instance calls directly."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)
        code = result.read_text()

        # The function should exist and have the direct-call branch
        assert "def _call_evaluate_instance(" in code
        assert "return evaluate_instance(program_path, instance_path)" in code


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


def _load_generated_wrapper(wrapper_path: Path) -> ModuleType:
    """Import a generated wrapper file as a fresh module for exec-based tests."""
    spec = importlib.util.spec_from_file_location(
        f"_revolver_wrapper_under_test_{id(wrapper_path)}", wrapper_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGeneratedWrapperAggregation:
    """Exec the generated wrapper's aggregation loop (B1 / FR-EVL-021).

    No existing test previously exec'd the generated ``evaluate()`` in its
    aggregated (dataset) mode. These tests run it against a small on-disk
    dataset containing an instance whose ``evaluate_instance`` returns a mix
    of numeric and non-numeric metrics, asserting the numeric guard drops the
    non-numeric keys instead of crashing ``statistics.mean``.
    """

    def _build_wrapper(self, tmp_path: Path) -> ModuleType:
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_mixed_metrics.py", snapshot_dir / "evaluator.py")
        output_dir = tmp_path / "run"
        output_dir.mkdir()
        # timeout_per_instance=None -> _call_evaluate_instance calls directly
        # (no multiprocessing), so evaluate() runs in-process for the exec test.
        wrapper_path = generate_wrapper(snapshot_dir, output_dir)
        return _load_generated_wrapper(wrapper_path)

    def test_mixed_numeric_and_non_numeric_metrics_no_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-numeric metric field is dropped, not crashed on (B1)."""
        wrapper = self._build_wrapper(tmp_path)

        dataset_dir = tmp_path / "dataset"
        dataset_dir.mkdir()
        # "bad" instance -> {"combined_score": 0.5, "error": "boom", "passed": True}
        (dataset_dir / "bad-01.txt").write_text("x", encoding="utf-8")
        # numeric instance -> {"combined_score": 1.0, "accuracy": 0.8}
        (dataset_dir / "good-01.txt").write_text("y", encoding="utf-8")

        monkeypatch.delenv("REVOLVER_INSTANCE_PATH", raising=False)
        monkeypatch.delenv("REVOLVER_INSTANCE_LOG", raising=False)
        monkeypatch.setenv("REVOLVER_DATASET_DIR", str(dataset_dir))

        program = tmp_path / "program.py"
        program.write_text("def solve():\n    return 0\n", encoding="utf-8")

        result = wrapper.evaluate(str(program))

        # combined_score = mean(0.5, 1.0) = 0.75 — a real number, no exception.
        assert isinstance(result["combined_score"], (int, float))
        assert result["combined_score"] == pytest.approx(0.75)
        # accuracy present only for the numeric instance -> mean of one value.
        assert result["accuracy"] == pytest.approx(0.8)
        # Non-numeric fields are dropped from the aggregate entirely.
        assert "error" not in result
        # bool is an int subclass but must be excluded by the numeric guard.
        assert "passed" not in result
        assert all(isinstance(v, (int, float)) for v in result.values())

    def test_all_numeric_metrics_aggregate_normally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fully-numeric dataset aggregates unchanged (no regression)."""
        wrapper = self._build_wrapper(tmp_path)

        dataset_dir = tmp_path / "dataset"
        dataset_dir.mkdir()
        (dataset_dir / "good-01.txt").write_text("y", encoding="utf-8")
        (dataset_dir / "good-02.txt").write_text("z", encoding="utf-8")

        monkeypatch.delenv("REVOLVER_INSTANCE_PATH", raising=False)
        monkeypatch.delenv("REVOLVER_INSTANCE_LOG", raising=False)
        monkeypatch.setenv("REVOLVER_DATASET_DIR", str(dataset_dir))

        program = tmp_path / "program.py"
        program.write_text("def solve():\n    return 0\n", encoding="utf-8")

        result = wrapper.evaluate(str(program))

        assert result["combined_score"] == pytest.approx(1.0)
        assert result["accuracy"] == pytest.approx(0.8)
