"""Tests for the evaluator runner (S2-08, S17a-01..04).

The kill-on-timeout and thread-cap tests (S17a) spawn real subprocesses;
the whole module is marked ``integration`` so it runs in the CI test job
(``-m "unit or integration"``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

import revolver.infra.evaluator_runner as evaluator_runner_module
from revolver.infra.evaluator_runner import (
    THREAD_CAP_VARS,
    THREAD_POLICY_VARS,
    THREADS_ENV_VAR,
    _run_in_subprocess,
    run_instance,
)
from revolver.models.problem import InstanceTestResult

pytestmark = [pytest.mark.integration]

FIXTURES = Path(__file__).parent / "fixtures"


def _pid_dead(pid: int) -> bool:
    """Return True if ``pid`` no longer exists (or is only a zombie)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    # Process entry still exists — a reaped-by-init zombie counts as dead.
    try:
        with open(f"/proc/{pid}/stat") as fh:
            state = fh.read().rpartition(")")[2].split()[0]
        return state == "Z"
    except OSError:
        return True


def _assert_pid_dead(pid: int, label: str, timeout_s: float = 10.0) -> None:
    """Poll until ``pid`` is dead; fail after ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _pid_dead(pid):
            return
        time.sleep(0.1)
    pytest.fail(f"{label} (pid={pid}) survived run_instance() by more than {timeout_s}s")


def _clear_thread_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every cap/policy var + REVOLVER_EVAL_NUM_THREADS from the env."""
    for var in (*THREAD_CAP_VARS, *THREAD_POLICY_VARS, THREADS_ENV_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(evaluator_runner_module, "_cap_announced", False)


#: Evaluator that reports the thread-cap env vars it sees (-1.0 = unset).
_ENV_PROBE_EVALUATOR = """\
import os

def evaluate(program_path):
    def val(name):
        return float(os.environ.get(name, "-1"))
    return {
        "omp": val("OMP_NUM_THREADS"),
        "openblas": val("OPENBLAS_NUM_THREADS"),
        "mkl": val("MKL_NUM_THREADS"),
        "passive": 1.0 if os.environ.get("OMP_WAIT_POLICY") == "PASSIVE" else 0.0,
    }
"""

#: Evaluator that records its PID (and a grandchild's), then hangs.
_HUNG_EVALUATOR_WITH_GRANDCHILD = """\
import json
import os
import subprocess
import time

def evaluate(program_path):
    grandchild = subprocess.Popen(["sleep", "120"])
    probe = os.environ["REVOLVER_INSTANCE_PATH"] + ".pids"
    with open(probe, "w") as fh:
        json.dump({"child": os.getpid(), "grandchild": grandchild.pid}, fh)
    time.sleep(120)
    return {"combined_score": 0.0}
"""

#: Evaluator that records its PID, then hangs (no grandchild).
_HUNG_EVALUATOR = """\
import json
import os
import time

def evaluate(program_path):
    probe = os.environ["REVOLVER_INSTANCE_PATH"] + ".pids"
    with open(probe, "w") as fh:
        json.dump({"child": os.getpid()}, fh)
    time.sleep(120)
    return {"combined_score": 0.0}
"""

#: Evaluator that backgrounds a grandchild, then returns successfully.
_PASSING_EVALUATOR_WITH_GRANDCHILD = """\
import json
import os
import subprocess

def evaluate(program_path):
    grandchild = subprocess.Popen(["sleep", "120"])
    probe = os.environ["REVOLVER_INSTANCE_PATH"] + ".pids"
    with open(probe, "w") as fh:
        json.dump({"grandchild": grandchild.pid}, fh)
    return {"combined_score": 1.0}
"""


class TestRunInstance:
    """Tests for run_instance()."""

    def test_successful_evaluation(self) -> None:
        """evaluator_simple + initial_program_simple + instance_001 -> pass."""
        result = run_instance(
            evaluator_path=FIXTURES / "evaluator_simple.py",
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=FIXTURES / "instances" / "instance_001.json",
        )
        assert isinstance(result, InstanceTestResult)
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


class TestDualFunctionWarning:
    """Tests for FB-06: dual-function warning suppression on wrapper."""

    def test_wrapper_no_dual_function_warning(self, tmp_path: Path) -> None:
        """Auto-generated wrapper (_revolver_evaluator.py) should not emit warning."""
        import io
        import sys

        wrapper = tmp_path / "_revolver_evaluator.py"
        wrapper.write_text(
            "def evaluate(program_path):\n"
            "    return {'combined_score': 1.0}\n"
            "def evaluate_instance(program_path, instance_path):\n"
            "    return {'combined_score': 1.0}\n"
        )
        program = tmp_path / "prog.py"
        program.write_text("# dummy program\n")

        captured_stderr = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured_stderr
        try:
            result = _run_in_subprocess(
                str(wrapper),
                str(program),
                str(tmp_path),
                "test-instance",
            )
        finally:
            sys.stderr = old_stderr

        assert result == {"combined_score": 1.0}
        assert "Warning" not in captured_stderr.getvalue()

    def test_user_evaluator_dual_function_warning(self, tmp_path: Path) -> None:
        """User evaluator with both functions should emit warning."""
        import io
        import sys

        user_eval = tmp_path / "my_evaluator.py"
        user_eval.write_text(
            "def evaluate(program_path):\n"
            "    return {'combined_score': 1.0}\n"
            "def evaluate_instance(program_path, instance_path):\n"
            "    return {'combined_score': 1.0}\n"
        )
        program = tmp_path / "prog.py"
        program.write_text("# dummy program\n")

        captured_stderr = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured_stderr
        try:
            result = _run_in_subprocess(
                str(user_eval),
                str(program),
                str(tmp_path),
                "test-instance",
            )
        finally:
            sys.stderr = old_stderr

        assert result == {"combined_score": 1.0}
        assert "Warning" in captured_stderr.getvalue()
        assert "evaluate()" in captured_stderr.getvalue()
        assert "evaluate_instance()" in captured_stderr.getvalue()


# ── S17a-01: U12 kill-on-timeout (task 358) ───────────────────────────────────


class TestKillOnTimeout:
    """run_instance() must kill the child (and its process group) on timeout."""

    def test_run_instance_kills_on_timeout(self, tmp_path: Path) -> None:
        """A deliberately-hung evaluator is killed at the deadline: no child
        (nor grandchild) survives the call."""
        hung_eval = tmp_path / "hung_eval.py"
        hung_eval.write_text(_HUNG_EVALUATOR_WITH_GRANDCHILD)
        instance = tmp_path / "instance.json"
        instance.write_text("{}")

        result = run_instance(
            evaluator_path=hung_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
            timeout_s=4.0,
        )

        assert result.status == "timeout"
        assert result.error == "Evaluation timed out after 4.0s"

        pids = json.loads((tmp_path / "instance.json.pids").read_text())
        _assert_pid_dead(pids["child"], "evaluator child")
        _assert_pid_dead(pids["grandchild"], "evaluator grandchild")

    def test_run_instance_reaps_grandchild_on_success(self, tmp_path: Path) -> None:
        """A grandchild backgrounded by a *passing* evaluator is group-reaped
        after the result is returned: a clean eval must not leak either
        (PR #242 review, comment 3523719357)."""
        passing_eval = tmp_path / "passing_eval.py"
        passing_eval.write_text(_PASSING_EVALUATOR_WITH_GRANDCHILD)
        instance = tmp_path / "instance.json"
        instance.write_text("{}")

        result = run_instance(
            evaluator_path=passing_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
            timeout_s=30.0,
        )

        assert result.status == "pass"
        assert result.metrics == {"combined_score": 1.0}

        pids = json.loads((tmp_path / "instance.json.pids").read_text())
        _assert_pid_dead(pids["grandchild"], "backgrounded grandchild of a passing eval")

    def test_run_instance_single_pid_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When getpgid fails, the single-PID kill fallback still terminates
        the child."""

        def _getpgid_fails(pid: int) -> int:
            raise OSError("getpgid blocked (test)")

        monkeypatch.setattr(os, "getpgid", _getpgid_fails)

        hung_eval = tmp_path / "hung_eval.py"
        hung_eval.write_text(_HUNG_EVALUATOR)
        instance = tmp_path / "instance.json"
        instance.write_text("{}")

        result = run_instance(
            evaluator_path=hung_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
            timeout_s=4.0,
        )

        assert result.status == "timeout"
        assert result.error == "Evaluation timed out after 4.0s"

        pids = json.loads((tmp_path / "instance.json.pids").read_text())
        _assert_pid_dead(pids["child"], "evaluator child")


# ── S17a-02: U14 thread caps (task 358) ───────────────────────────────────────


class TestThreadCaps:
    """run_instance() injects the BLAS/OpenMP thread-cap env family (U14)."""

    def test_run_instance_thread_cap_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """With a clean env, the default cap max(1, cpu//2) is injected and
        exactly one stderr line announces it (once per process)."""
        _clear_thread_env(monkeypatch)
        probe_eval = tmp_path / "probe_eval.py"
        probe_eval.write_text(_ENV_PROBE_EVALUATOR)
        instance = tmp_path / "instance.json"
        instance.write_text("{}")

        expected = float(max(1, (os.cpu_count() or 1) // 2))
        result = run_instance(
            evaluator_path=probe_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
        )
        # Second call: the announce line must NOT repeat.
        run_instance(
            evaluator_path=probe_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
        )

        assert result.status == "pass"
        assert result.metrics is not None
        assert result.metrics["omp"] == expected
        assert result.metrics["openblas"] == expected
        assert result.metrics["mkl"] == expected
        assert result.metrics["passive"] == 1.0

        cap_lines = [
            line
            for line in capsys.readouterr().err.splitlines()
            if "numeric thread cap per eval process" in line
        ]
        assert cap_lines == [
            f"[revolver] numeric thread cap per eval process: {int(expected)} "
            f"({THREADS_ENV_VAR}=0 to disable)"
        ]

    def test_run_instance_thread_cap_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REVOLVER_EVAL_NUM_THREADS is honored, including 0 = uncapped."""
        _clear_thread_env(monkeypatch)
        probe_eval = tmp_path / "probe_eval.py"
        probe_eval.write_text(_ENV_PROBE_EVALUATOR)
        instance = tmp_path / "instance.json"
        instance.write_text("{}")

        monkeypatch.setenv(THREADS_ENV_VAR, "3")
        result = run_instance(
            evaluator_path=probe_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
        )
        assert result.status == "pass"
        assert result.metrics is not None
        assert result.metrics["omp"] == 3.0
        assert result.metrics["openblas"] == 3.0

        monkeypatch.setenv(THREADS_ENV_VAR, "0")
        uncapped = run_instance(
            evaluator_path=probe_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
        )
        assert uncapped.status == "pass"
        assert uncapped.metrics is not None
        assert uncapped.metrics["omp"] == -1.0
        assert uncapped.metrics["openblas"] == -1.0
        assert uncapped.metrics["passive"] == 0.0

    def test_run_instance_thread_cap_invalid_env_warns_and_defaults(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An invalid REVOLVER_EVAL_NUM_THREADS warns and falls back to the
        default cap."""
        _clear_thread_env(monkeypatch)
        probe_eval = tmp_path / "probe_eval.py"
        probe_eval.write_text(_ENV_PROBE_EVALUATOR)
        instance = tmp_path / "instance.json"
        instance.write_text("{}")

        monkeypatch.setenv(THREADS_ENV_VAR, "not-a-number")
        result = run_instance(
            evaluator_path=probe_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
        )

        assert result.status == "pass"
        assert result.metrics is not None
        assert result.metrics["omp"] == float(max(1, (os.cpu_count() or 1) // 2))
        assert f"invalid {THREADS_ENV_VAR}" in capsys.readouterr().err

    def test_run_instance_thread_cap_respects_user_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Any pre-set cap var in the parent env means Revolver injects
        nothing (preserves a manual OMP_NUM_THREADS=2 workaround)."""
        _clear_thread_env(monkeypatch)
        monkeypatch.setenv("OMP_NUM_THREADS", "2")
        probe_eval = tmp_path / "probe_eval.py"
        probe_eval.write_text(_ENV_PROBE_EVALUATOR)
        instance = tmp_path / "instance.json"
        instance.write_text("{}")

        result = run_instance(
            evaluator_path=probe_eval,
            program_path=FIXTURES / "initial_program_simple.py",
            instance_path=instance,
        )

        assert result.status == "pass"
        assert result.metrics is not None
        # The user's own setting is inherited by the child...
        assert result.metrics["omp"] == 2.0
        # ...and Revolver injected none of the other family members.
        assert result.metrics["openblas"] == -1.0
        assert result.metrics["mkl"] == -1.0
        assert result.metrics["passive"] == 0.0
        assert "numeric thread cap per eval process" not in capsys.readouterr().err


# ── S17a-01/02: InstanceTestResult contract (byte-identical) ──────────────────


class TestResultContract:
    """Statuses, timeout message, and error strings must match the
    pre-rewrite ProcessPoolExecutor implementation byte for byte."""

    def test_run_instance_result_contract_byte_identical(self, tmp_path: Path) -> None:
        instance = tmp_path / "instance.json"
        instance.write_text("{}")
        program = FIXTURES / "initial_program_simple.py"

        # status="pass": metrics returned unchanged.
        ok_eval = tmp_path / "ok_eval.py"
        ok_eval.write_text("def evaluate(program_path):\n    return {'combined_score': 0.5}\n")
        ok = run_instance(evaluator_path=ok_eval, program_path=program, instance_path=instance)
        assert ok.status == "pass"
        assert ok.metrics == {"combined_score": 0.5}
        assert ok.error is None

        # status="fail": error is the raised exception's message, verbatim.
        bad_eval = tmp_path / "bad_eval.py"
        bad_eval.write_text(
            "def evaluate(program_path):\n    raise ValueError('intentional failure')\n"
        )
        fail = run_instance(evaluator_path=bad_eval, program_path=program, instance_path=instance)
        assert fail.status == "fail"
        assert fail.error == "intentional failure"
        assert fail.traceback is not None
        assert "ValueError: intentional failure" in fail.traceback

        # status="fail": neither-function error string, verbatim.
        neither_eval = tmp_path / "neither_eval.py"
        neither_eval.write_text("def something_else():\n    pass\n")
        neither = run_instance(
            evaluator_path=neither_eval, program_path=program, instance_path=instance
        )
        assert neither.status == "fail"
        assert neither.error == (
            f"Evaluator {neither_eval} defines neither evaluate() nor evaluate_instance()"
        )

        # status="timeout": exact message, including the float formatting.
        slow_eval = tmp_path / "slow_eval.py"
        slow_eval.write_text(
            "import time\n"
            "def evaluate(program_path):\n"
            "    time.sleep(120)\n"
            "    return {'combined_score': 0.0}\n"
        )
        timeout = run_instance(
            evaluator_path=slow_eval,
            program_path=program,
            instance_path=instance,
            timeout_s=1.5,
        )
        assert timeout.status == "timeout"
        assert timeout.error == "Evaluation timed out after 1.5s"
        assert timeout.metrics is None
