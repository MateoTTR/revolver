"""Regression tests for issue #29 fixes.

Covers:
- F9: _collect_programs() finds programs in oe-output/best/
- F6: evaluator_runner supports evaluate_instance() mode
- F7: wrapper template logs errors to stderr instead of silent pass
- Warning when evaluator defines both evaluate() and evaluate_instance()
"""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from revolver.core.run import (
    _WRAPPER_TEMPLATE,
    WRAPPER_FILENAME,
    _collect_programs,
    generate_wrapper,
)
from revolver.infra.evaluator_runner import run_instance
from revolver.models.problem import InstanceTestResult

pytestmark = [pytest.mark.unit]

FIXTURES = Path(__file__).parents[2] / "fixtures"


# ── F9: _collect_programs() finds best/ directory ────────────────────────────


class TestCollectProgramsBestDir:
    """_collect_programs() must find programs in oe-output/best/."""

    def test_collect_from_best_dir(self, tmp_path: Path) -> None:
        """Programs in best/ are collected as rank-1."""
        oe_dir = tmp_path / "oe-output"
        best_dir = oe_dir / "best"
        best_dir.mkdir(parents=True)
        (best_dir / "best_program.py").write_text("# best program\n")

        programs_dir = tmp_path / "programs"

        programs = _collect_programs(oe_dir, programs_dir)

        assert len(programs) == 1
        assert programs[0].rank == 1
        assert programs[0].file == "programs/rank-1.py"
        assert (programs_dir / "rank-1.py").exists()
        assert (programs_dir / "rank-1.py").read_text() == "# best program\n"

    def test_top_programs_takes_priority_over_best(self, tmp_path: Path) -> None:
        """top_programs/ is searched before best/, so it takes priority."""
        oe_dir = tmp_path / "oe-output"

        top_dir = oe_dir / "top_programs"
        top_dir.mkdir(parents=True)
        (top_dir / "program_0.py").write_text("# top\n")

        best_dir = oe_dir / "best"
        best_dir.mkdir(parents=True)
        (best_dir / "best_program.py").write_text("# best\n")

        programs_dir = tmp_path / "programs"

        programs = _collect_programs(oe_dir, programs_dir)

        assert len(programs) == 1
        assert (programs_dir / "rank-1.py").read_text() == "# top\n"


# ── F6: evaluator_runner supports evaluate_instance() ────────────────────────


class TestEvaluatorRunnerInstanceMode:
    """_run_in_subprocess() calls evaluate_instance() when no evaluate() exists."""

    def test_evaluate_instance_only(self, tmp_path: Path) -> None:
        """Evaluator with only evaluate_instance() is called correctly."""
        eval_file = tmp_path / "eval_inst.py"
        eval_file.write_text(
            "def evaluate_instance(program_path, instance_path):\n"
            "    return {'combined_score': 42.0, 'instance_mode': 1.0}\n"
        )
        program_file = tmp_path / "program.py"
        program_file.write_text("# program\n")
        instance_file = tmp_path / "instance.json"
        instance_file.write_text("{}")

        result = run_instance(
            evaluator_path=eval_file,
            program_path=program_file,
            instance_path=instance_file,
        )

        assert isinstance(result, InstanceTestResult)
        assert result.status == "pass"
        assert result.metrics is not None
        assert result.metrics["combined_score"] == 42.0
        assert result.metrics["instance_mode"] == 1.0

    def test_evaluate_legacy_still_works(self, tmp_path: Path) -> None:
        """Evaluator with only evaluate() still works (no regression)."""
        eval_file = tmp_path / "eval_legacy.py"
        eval_file.write_text("def evaluate(program_path):\n    return {'combined_score': 99.0}\n")
        program_file = tmp_path / "program.py"
        program_file.write_text("# program\n")
        instance_file = tmp_path / "instance.json"
        instance_file.write_text("{}")

        result = run_instance(
            evaluator_path=eval_file,
            program_path=program_file,
            instance_path=instance_file,
        )

        assert isinstance(result, InstanceTestResult)
        assert result.status == "pass"
        assert result.metrics is not None
        assert result.metrics["combined_score"] == 99.0

    def test_neither_function_fails(self, tmp_path: Path) -> None:
        """Evaluator with neither function produces status='fail'."""
        eval_file = tmp_path / "eval_neither.py"
        eval_file.write_text("def something_else(): pass\n")
        program_file = tmp_path / "program.py"
        program_file.write_text("# program\n")
        instance_file = tmp_path / "instance.json"
        instance_file.write_text("{}")

        result = run_instance(
            evaluator_path=eval_file,
            program_path=program_file,
            instance_path=instance_file,
        )

        assert result.status == "fail"
        assert result.error is not None
        assert "neither evaluate() nor evaluate_instance()" in result.error


# ── F7: wrapper template logs errors to stderr ───────────────────────────────


class TestWrapperTemplateErrorLogging:
    """Wrapper template logs evaluation errors instead of silent pass."""

    def test_template_contains_stderr_logging(self) -> None:
        """_WRAPPER_TEMPLATE uses stderr instead of pass for errors."""
        assert "file=sys.stderr" in _WRAPPER_TEMPLATE
        assert "pass  # Skip failed instances" not in _WRAPPER_TEMPLATE

    def test_template_captures_exception(self) -> None:
        """_WRAPPER_TEMPLATE captures the exception variable."""
        assert "except Exception as _e:" in _WRAPPER_TEMPLATE

    def test_template_logs_instance_name(self) -> None:
        """_WRAPPER_TEMPLATE includes the instance name in the log message."""
        assert "[revolver] evaluation failed for" in _WRAPPER_TEMPLATE


# ── Warning for dual-function evaluators ─────────────────────────────────────


class TestGenerateWrapperDualFunctionWarning:
    """generate_wrapper() emits a warning when both functions exist."""

    def test_warning_emitted_for_both_functions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Evaluator with both evaluate() and evaluate_instance() triggers warning."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_both.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        result = generate_wrapper(snapshot_dir, output_dir)

        captured = capsys.readouterr()
        assert "Warning: evaluator defines both evaluate() and evaluate_instance()" in captured.err
        assert "legacy mode" in captured.err

        # Should still produce a valid output (copied as legacy)
        assert result.exists()
        assert result.name == WRAPPER_FILENAME

    def test_no_warning_for_instance_only(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Evaluator with only evaluate_instance() does not trigger warning."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_instance.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        generate_wrapper(snapshot_dir, output_dir)

        captured = capsys.readouterr()
        assert "Warning" not in captured.err

    def test_no_warning_for_legacy_only(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Evaluator with only evaluate() does not trigger warning."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        shutil.copy(FIXTURES / "evaluator_legacy.py", snapshot_dir / "evaluator.py")

        output_dir = tmp_path / "run"
        output_dir.mkdir()

        generate_wrapper(snapshot_dir, output_dir)

        captured = capsys.readouterr()
        assert "Warning" not in captured.err
