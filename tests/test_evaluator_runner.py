"""Tests for the evaluator runner (S2-08)."""

from __future__ import annotations

from pathlib import Path

from revolver.infra.evaluator_runner import run_instance

FIXTURES = Path(__file__).parent / "fixtures"


class TestRunInstance:
    """Tests for run_instance()."""

    def test_successful_evaluation(self) -> None:
        """evaluator_simple + initial_program_simple + instance_001 -> pass."""
        result = run_instance(
            evaluator_path=FIXTURES / "evaluator_simple.py",
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=FIXTURES / "instances" / "instance_001.json",
        )
        assert result.status == "pass"
        assert result.metrics is not None
        assert "combined_score" in result.metrics
        assert result.metrics["combined_score"] > 0
        assert result.time_s > 0

    def test_evaluator_exception(self, tmp_path: Path) -> None:
        """An evaluator that raises produces status='fail' with error."""
        bad_eval = tmp_path / "bad_eval.py"
        bad_eval.write_text(
            "def evaluate(program_path):\n    raise ValueError('intentional failure')\n"
        )
        result = run_instance(
            evaluator_path=bad_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=FIXTURES / "instances" / "instance_001.json",
        )
        assert result.status == "fail"
        assert result.error is not None
        assert "intentional failure" in result.error

    def test_timeout(self, tmp_path: Path) -> None:
        """An evaluator that sleeps too long produces status='timeout'."""
        slow_eval = tmp_path / "slow_eval.py"
        slow_eval.write_text(
            "import time\n"
            "def evaluate(program_path):\n"
            "    time.sleep(10)\n"
            "    return {'combined_score': 0.0}\n"
        )
        result = run_instance(
            evaluator_path=slow_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=FIXTURES / "instances" / "instance_001.json",
            timeout_s=0.5,
        )
        assert result.status == "timeout"
        assert result.error is not None
        assert "timed out" in result.error

    def test_env_vars_set(self, tmp_path: Path) -> None:
        """The child process receives REVOLVER_INSTANCE_PATH in env vars."""
        env_eval = tmp_path / "env_eval.py"
        env_eval.write_text(
            "import os\n"
            "def evaluate(program_path):\n"
            "    path = os.environ.get('REVOLVER_INSTANCE_PATH', '')\n"
            "    iid = os.environ.get('REVOLVER_INSTANCE_ID', '')\n"
            "    return {\n"
            "        'path_len': float(len(path)),\n"
            "        'id_len': float(len(iid)),\n"
            "    }\n"
        )
        instance = FIXTURES / "instances" / "instance_001.json"
        result = run_instance(
            evaluator_path=env_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
        )
        assert result.status == "pass"
        assert result.metrics is not None
        assert result.metrics["path_len"] > 0
        assert result.metrics["id_len"] > 0
