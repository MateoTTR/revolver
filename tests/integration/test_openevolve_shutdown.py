"""L2 test for orchestrator-owned OpenEvolve teardown (B2 / S17-05, S17-06).

Symmetric to ``test_shinka_shutdown.py`` (A2 / #314): after an OpenEvolve run
returns (best program already persisted to the checkpoint), a surviving
``ProcessParallelController`` worker / evaluator child could keep the CLI
pinned at ~100% CPU. ``OpenEvolveRunner.run()`` now wraps ``asyncio.run(...)``
in ``try/finally`` and, in the ``finally`` block, defensively shuts down the
controller's ``ProcessPoolExecutor`` (``wait=False`` — never ``wait=True``,
which would reintroduce the #159 hang) and reaps any child that outlived the
run.

These tests mock the controller so they run **without** the ``[openevolve]``
extra installed (no real ``openevolve`` import). They assert:

(a) ``test_run_invokes_teardown_on_success`` — the happy path runs the engine
    then shuts down the controller's executor.
(b) ``test_run_teardown_runs_on_failure`` — teardown still fires (the
    ``finally`` block) when the controller raises, and the failure is wrapped.
(c) ``test_run_leaves_no_lingering_thread`` — no extra non-daemon background
    thread survives ``run()``.
(d) ``test_reap_run_children_terminates_survivor`` — a real child process that
    outlives the run is terminated by the reap backstop.
(e) ``test_shutdown_runner_never_raises`` — teardown is fully defensive on a
    misshapen / None controller, and never uses ``wait=True``.

Traceable to: sprint-017 S17-03..06, issue #226, ADR-007, DES-005 §4.4/§7.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from revolver.core.exceptions import ExternalError
from revolver.infra.backends.openevolve import OpenEvolveRunner

pytestmark = [pytest.mark.integration]


def _make_runner(tmp_path: Path) -> OpenEvolveRunner:
    """Build a runner whose input files exist; controller is stubbed later."""
    initial = tmp_path / "initial_program.py"
    initial.write_text("def solve():\n    return 0\n", encoding="utf-8")
    evaluator = tmp_path / "_revolver_evaluator.py"
    evaluator.write_text("def evaluate(p):\n    return {}\n", encoding="utf-8")
    output_dir = tmp_path / "oe-output"
    output_dir.mkdir()
    return OpenEvolveRunner(
        initial_program=initial,
        evaluator=evaluator,
        config={},
        output_dir=output_dir,
    )


def _make_controller_with_executor() -> tuple[MagicMock, MagicMock]:
    """Build a mock controller exposing parallel_controller.executor."""
    executor = MagicMock(name="ProcessPoolExecutor")
    parallel_controller = MagicMock(name="ProcessParallelController")
    parallel_controller.executor = executor
    controller = MagicMock(name="OpenEvolve")
    controller.parallel_controller = parallel_controller
    return controller, executor


def test_run_invokes_teardown_on_success(tmp_path: Path) -> None:
    """The happy path runs the engine then shuts down the executor (B2)."""
    runner = _make_runner(tmp_path)
    controller, executor = _make_controller_with_executor()
    # Pre-set the controller so run() skips _init_controller (no real import).
    runner._controller = controller

    with (
        patch(
            "revolver.infra.backends.openevolve.asyncio.run",
            return_value=MagicMock(name="best"),
        ),
        patch(
            "revolver.infra.backends.openevolve._extract_best_score",
            return_value=0.9,
        ),
    ):
        output = runner.run(iterations=3)

    assert output.best_score == 0.9
    # Executor is shut down without blocking (never wait=True — the #159 hang).
    executor.shutdown.assert_called_once_with(wait=False)


def test_run_teardown_runs_on_failure(tmp_path: Path) -> None:
    """Teardown still fires (finally) when the controller run raises."""
    runner = _make_runner(tmp_path)
    controller, executor = _make_controller_with_executor()
    runner._controller = controller

    with (
        patch(
            "revolver.infra.backends.openevolve.asyncio.run",
            side_effect=RuntimeError("engine boom"),
        ),
        pytest.raises(ExternalError, match="OpenEvolve run failed"),
    ):
        runner.run(iterations=3)

    executor.shutdown.assert_called_once_with(wait=False)


def test_run_leaves_no_lingering_thread(tmp_path: Path) -> None:
    """No extra non-daemon background thread survives ``run()``."""
    runner = _make_runner(tmp_path)
    controller, _executor = _make_controller_with_executor()
    runner._controller = controller

    before = {t.ident for t in threading.enumerate()}
    with (
        patch(
            "revolver.infra.backends.openevolve.asyncio.run",
            return_value=MagicMock(name="best"),
        ),
        patch(
            "revolver.infra.backends.openevolve._extract_best_score",
            return_value=0.0,
        ),
    ):
        runner.run(iterations=1)
    after_non_daemon = {
        t.ident for t in threading.enumerate() if not t.daemon and t.ident not in before
    }
    assert after_non_daemon == set()


def test_reap_run_children_terminates_survivor(tmp_path: Path) -> None:
    """A child that outlives the run is reaped by the backstop (Linux only)."""
    if not Path("/proc/self/task").is_dir():
        pytest.skip("child PID enumeration requires Linux /proc")

    runner = _make_runner(tmp_path)
    pre_run_children = runner._current_child_pids()

    # Spawn a long-lived child that would otherwise keep the CLI alive.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        deadline = time.monotonic() + 5.0
        while child.pid not in (runner._current_child_pids() - pre_run_children):
            assert time.monotonic() < deadline, "child never appeared in /proc children"
            time.sleep(0.05)

        runner._reap_run_children(pre_run_children)

        assert child.wait(timeout=5.0) is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5.0)


def test_reap_run_children_no_survivors_is_noop(tmp_path: Path) -> None:
    """With no new children, the reap backstop does nothing and never raises."""
    runner = _make_runner(tmp_path)
    current = runner._current_child_pids()
    with patch("os.kill") as mock_kill:
        runner._reap_run_children(current)
    mock_kill.assert_not_called()


def test_shutdown_runner_never_raises() -> None:
    """Teardown is fully defensive: None / misshapen controllers are tolerated.

    Also asserts the shutdown is never called with ``wait=True`` (the #159
    ``ProcessPoolExecutor.shutdown(wait=True)`` hang must never be reintroduced).
    """
    # None controller (construction failed before assignment).
    OpenEvolveRunner._shutdown_runner(None)

    # Controller whose executor shutdown raises — must be swallowed.
    bad_executor = MagicMock()
    bad_executor.shutdown.side_effect = RuntimeError("executor boom")
    bad_parallel = MagicMock()
    bad_parallel.executor = bad_executor
    bad_controller = MagicMock()
    bad_controller.parallel_controller = bad_parallel
    OpenEvolveRunner._shutdown_runner(bad_controller)  # must not raise
    # It was still called with wait=False (never wait=True).
    bad_executor.shutdown.assert_called_once_with(wait=False)

    # Controller missing the attributes entirely.
    bare = object()
    OpenEvolveRunner._shutdown_runner(bare)  # must not raise

    # Controller with parallel_controller but no executor yet (early exit).
    partial = MagicMock()
    partial.parallel_controller = MagicMock(spec=[])
    OpenEvolveRunner._shutdown_runner(partial)  # must not raise


def test_current_child_pids_returns_set(tmp_path: Path) -> None:
    """``_current_child_pids`` returns a set of ints and never raises."""
    runner = _make_runner(tmp_path)
    pids = runner._current_child_pids()
    assert isinstance(pids, set)
    assert all(isinstance(pid, int) for pid in pids)
    assert os.getpid() not in pids
