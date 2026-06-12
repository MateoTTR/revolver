"""L2-Shinka contract tests for the generated ``evaluate.py`` wrapper (R4).

Front-loads the top silent-bug risk of the ShinkaEvolve backend (impact
analysis R4): the evaluator wrapper that ``ShinkaBackend.generate_wrapper()``
must produce in S14 PR-B. Two tiers:

- ``TestGoldenWrapperContract`` exercises the **reference golden wrapper**
  (``tests/fixtures/shinka_evaluate_py.py``) against the real
  ``shinka.core.run_shinka_eval`` — proving the contract is satisfiable
  and pinning the expected ``metrics.json`` / ``correct.json`` behavior
  before any implementation exists.
- ``TestGenerateWrapperContract`` runs the same five scenarios against
  ``ShinkaBackend.generate_wrapper()`` output. The backend is still the
  S13 stub (raises ``BackendUnavailableError``), so these are marked
  ``xfail(strict=False)`` until the implementation lands (S14 PR-B),
  keeping PR-A independently mergeable.

Skipped automatically when shinka-evolve is not installed (mirrors L2-OE).

Traceable to: sprint-014 S14-02, issue #190, DES-006 §1.3,
val-integration-tests.md §L2-Shinka.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("shinka.database", reason="shinka-evolve not installed")
pytest.importorskip("shinka.core", reason="shinka-evolve not installed")

from revolver.infra.backends.base import BackendRunSpec
from revolver.infra.backends.shinka import ShinkaBackend
from revolver.models.llm import LLMEntry
from tests.fixtures.shinka_evaluate_py import (
    GOLDEN_WRAPPER_MARKERS,
    golden_wrapper_content,
    write_golden_wrapper,
)

# Path to test fixtures
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

xfail_stub = pytest.mark.xfail(
    strict=False,
    reason="ShinkaBackend.generate_wrapper() is the S13 stub — implementation lands in S14 PR-B",
)

# ── Inline evaluator sources for failure-path scenarios ──────────────────────

_EVALUATOR_FAILING = '''\
"""Evaluator whose evaluate_instance() always raises."""


def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    raise RuntimeError("intentional evaluator failure")
'''

_EVALUATOR_NO_COMBINED_SCORE = '''\
"""Evaluator whose metrics dict is missing combined_score."""


def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    return {"accuracy": 0.5}
'''

_EVALUATOR_BOTH_MODES = '''\
"""Evaluator with both evaluate() and evaluate_instance().

The Shinka wrapper must use evaluate_instance(); calling the legacy
evaluate() would yield combined_score 99.0 and no via_instance key.
"""


def evaluate(program_path: str) -> dict[str, float]:
    return {"combined_score": 99.0}


def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    return {"combined_score": 0.5, "via_instance": 1.0}
'''

_PROGRAM_SOURCE = "def solve(data):\n    return sum(data)\n"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_llm_entry() -> LLMEntry:
    """Create a minimal local LLMEntry for BackendRunSpec."""
    return LLMEntry(
        name="test-llm",
        source="local",
        model="test-model",
        base_url="http://localhost:11434/v1",
        api_key_env=None,
        registered_at=datetime.now(UTC),
    )


def _make_snapshot(base_dir: Path, evaluator_source: str | Path) -> Path:
    """Build a problem snapshot dir (config, initial program, evaluator).

    Args:
        base_dir: Parent directory (e.g. ``tmp_path``).
        evaluator_source: Inline evaluator source, or a fixture file path
            to copy.

    Returns:
        The snapshot directory.
    """
    snapshot = base_dir / "snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "config_simple.yaml", snapshot / "config.yaml")
    shutil.copy(FIXTURES / "initial_program_simple.py", snapshot / "initial_program.py")
    if isinstance(evaluator_source, Path):
        shutil.copy(evaluator_source, snapshot / "evaluator.py")
    else:
        (snapshot / "evaluator.py").write_text(evaluator_source)
    return snapshot


def _run_wrapper(
    wrapper: Path,
    program: Path,
    results_dir: Path,
    dataset_dir: Path,
) -> subprocess.CompletedProcess[str]:
    """Execute a wrapper the way Shinka's local scheduler does.

    Command shape verified in ``shinka/launch/scheduler.py::_build_command``:
    ``python <wrapper> --program_path <program> --results_dir <dir>``.
    """
    env = {**os.environ, "REVOLVER_DATASET_DIR": str(dataset_dir)}
    return subprocess.run(
        [
            sys.executable,
            str(wrapper),
            "--program_path",
            str(program),
            "--results_dir",
            str(results_dir),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _make_program(base_dir: Path) -> Path:
    """Write the program-under-evaluation file."""
    program = base_dir / "program.py"
    program.write_text(_PROGRAM_SOURCE)
    return program


def _read_json(path: Path) -> dict[str, object]:
    """Load a JSON results file."""
    data = json.loads(path.read_text())
    assert isinstance(data, dict)
    return data


def _generate_wrapper(tmp_path: Path, evaluator_source: str | Path) -> Path:
    """Call ShinkaBackend.generate_wrapper() on a fresh snapshot/run dir."""
    snapshot = _make_snapshot(tmp_path, evaluator_source)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    spec = BackendRunSpec(snapshot_dir=snapshot, llm=_make_llm_entry(), run_dir=run_dir)
    return ShinkaBackend().generate_wrapper(spec)


# ── Golden reference wrapper — executable contract (passes today) ────────────


@pytest.mark.integration
@pytest.mark.shinkaevolve
class TestGoldenWrapperContract:
    """The reference golden wrapper satisfies the R4 contract end-to-end."""

    def test_golden_content_has_contract_markers(self, tmp_path: Path) -> None:
        """(a) Golden wrapper calls run_shinka_eval and exposes the CLI args."""
        content = golden_wrapper_content(tmp_path / "snapshot")
        for marker in GOLDEN_WRAPPER_MARKERS:
            assert marker in content, f"golden wrapper is missing marker: {marker}"

    def test_golden_calls_evaluate_instance_not_evaluate(self, tmp_path: Path) -> None:
        """(b) evaluate_instance() is used even when legacy evaluate() exists."""
        snapshot = _make_snapshot(tmp_path, _EVALUATOR_BOTH_MODES)
        wrapper = write_golden_wrapper(snapshot, tmp_path / "evaluate.py")
        results_dir = tmp_path / "results"

        proc = _run_wrapper(wrapper, _make_program(tmp_path), results_dir, FIXTURES / "instances")

        assert proc.returncode == 0, proc.stderr
        metrics = _read_json(results_dir / "metrics.json")
        # Legacy evaluate() would have produced 99.0 and no via_instance.
        assert metrics["combined_score"] == pytest.approx(0.5)
        assert metrics["via_instance"] == pytest.approx(1.0)

    def test_golden_writes_metrics_and_correct_json(self, tmp_path: Path) -> None:
        """(c) metrics.json (with combined_score) + correct.json in results_dir."""
        snapshot = _make_snapshot(tmp_path, FIXTURES / "evaluator_instance.py")
        wrapper = write_golden_wrapper(snapshot, tmp_path / "evaluate.py")
        results_dir = tmp_path / "results"
        program = _make_program(tmp_path)

        proc = _run_wrapper(wrapper, program, results_dir, FIXTURES / "instances")

        assert proc.returncode == 0, proc.stderr
        metrics = _read_json(results_dir / "metrics.json")
        correct = _read_json(results_dir / "correct.json")
        # evaluator_instance.py scores len(source)/100 per instance; the
        # mean over identical per-instance metrics is that same value.
        expected_score = len(_PROGRAM_SOURCE) / 100.0
        assert metrics["combined_score"] == pytest.approx(expected_score)
        assert correct["correct"] is True
        assert correct["error"] is None

    def test_golden_failing_evaluator_marks_incorrect(self, tmp_path: Path) -> None:
        """(d) A raising evaluate_instance() yields correct: false."""
        snapshot = _make_snapshot(tmp_path, _EVALUATOR_FAILING)
        wrapper = write_golden_wrapper(snapshot, tmp_path / "evaluate.py")
        results_dir = tmp_path / "results"

        proc = _run_wrapper(wrapper, _make_program(tmp_path), results_dir, FIXTURES / "instances")

        assert proc.returncode == 0, proc.stderr
        correct = _read_json(results_dir / "correct.json")
        assert correct["correct"] is False
        assert "intentional evaluator failure" in str(correct["error"])

    def test_golden_missing_combined_score_marks_incorrect(self, tmp_path: Path) -> None:
        """(e) Metrics without combined_score yield correct: false."""
        snapshot = _make_snapshot(tmp_path, _EVALUATOR_NO_COMBINED_SCORE)
        wrapper = write_golden_wrapper(snapshot, tmp_path / "evaluate.py")
        results_dir = tmp_path / "results"

        proc = _run_wrapper(wrapper, _make_program(tmp_path), results_dir, FIXTURES / "instances")

        assert proc.returncode == 0, proc.stderr
        correct = _read_json(results_dir / "correct.json")
        assert correct["correct"] is False


# ── ShinkaBackend.generate_wrapper() — xfail until S14 PR-B ──────────────────


@pytest.mark.integration
@pytest.mark.shinkaevolve
class TestGenerateWrapperContract:
    """Same five scenarios against the backend-generated wrapper (S14-02)."""

    @xfail_stub
    def test_wrapper_calls_run_shinka_eval_with_correct_args(self, tmp_path: Path) -> None:
        """(a) Generated evaluate.py calls run_shinka_eval with correct args."""
        wrapper = _generate_wrapper(tmp_path, FIXTURES / "evaluator_instance.py")

        assert wrapper.exists()
        content = wrapper.read_text()
        for marker in GOLDEN_WRAPPER_MARKERS:
            assert marker in content, f"generated wrapper is missing marker: {marker}"

    @xfail_stub
    def test_wrapper_calls_evaluate_instance_not_evaluate(self, tmp_path: Path) -> None:
        """(b) Wrapper imports/calls evaluate_instance(), not legacy evaluate()."""
        wrapper = _generate_wrapper(tmp_path, _EVALUATOR_BOTH_MODES)

        assert "evaluate_instance" in wrapper.read_text()
        results_dir = tmp_path / "results"
        proc = _run_wrapper(wrapper, _make_program(tmp_path), results_dir, FIXTURES / "instances")

        assert proc.returncode == 0, proc.stderr
        metrics = _read_json(results_dir / "metrics.json")
        # Legacy evaluate() would have produced 99.0 and no via_instance.
        assert metrics["combined_score"] == pytest.approx(0.5)
        assert metrics["via_instance"] == pytest.approx(1.0)

    @xfail_stub
    def test_wrapper_writes_metrics_and_correct_json(self, tmp_path: Path) -> None:
        """(c) Wrapper writes metrics.json (combined_score) + correct.json."""
        wrapper = _generate_wrapper(tmp_path, FIXTURES / "evaluator_instance.py")
        results_dir = tmp_path / "results"

        proc = _run_wrapper(wrapper, _make_program(tmp_path), results_dir, FIXTURES / "instances")

        assert proc.returncode == 0, proc.stderr
        metrics = _read_json(results_dir / "metrics.json")
        correct = _read_json(results_dir / "correct.json")
        assert metrics["combined_score"] == pytest.approx(len(_PROGRAM_SOURCE) / 100.0)
        assert correct["correct"] is True

    @xfail_stub
    def test_wrapper_failing_evaluator_marks_incorrect(self, tmp_path: Path) -> None:
        """(d) Wrapper with a failing evaluator writes correct: false."""
        wrapper = _generate_wrapper(tmp_path, _EVALUATOR_FAILING)
        results_dir = tmp_path / "results"

        proc = _run_wrapper(wrapper, _make_program(tmp_path), results_dir, FIXTURES / "instances")

        assert proc.returncode == 0, proc.stderr
        correct = _read_json(results_dir / "correct.json")
        assert correct["correct"] is False

    @xfail_stub
    def test_wrapper_missing_combined_score_raises_or_incorrect(self, tmp_path: Path) -> None:
        """(e) Missing combined_score in metrics raises or marks incorrect."""
        wrapper = _generate_wrapper(tmp_path, _EVALUATOR_NO_COMBINED_SCORE)
        results_dir = tmp_path / "results"

        proc = _run_wrapper(wrapper, _make_program(tmp_path), results_dir, FIXTURES / "instances")

        correct_path = results_dir / "correct.json"
        if proc.returncode == 0:
            # Marked incorrect via the run_shinka_eval error path.
            assert _read_json(correct_path)["correct"] is False
        else:
            # Raised: the wrapper aborted instead of reporting a result.
            assert not correct_path.exists() or _read_json(correct_path)["correct"] is False
