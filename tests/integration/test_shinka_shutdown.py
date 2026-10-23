"""L2 test for orchestrator-owned Shinka teardown (A2 / #314, S16a-06).

After a ShinkaEvolve run prints ``Done: … completed`` (result persisted to
``programs.sqlite``), the in-process ``ShinkaEvolveRunner.run()`` could leave
the orchestrator busy-looping at ~100% CPU (leaked async LLM transports /
default executor / a surviving evaluator child — see the §A2 spike of the
Sprint 016a record). ``ShinkaBackend._run_engine()`` now wraps
``runner.run()`` in ``try/finally`` and invokes a defensive teardown.

These tests mock the runner at the ``_engine_classes`` boundary so they run
**without** the ``[shinka]`` extra installed (no real ``shinka`` import, no env
mutation). They assert:

(a) ``test_run_engine_invokes_runner_teardown`` — the happy path runs the
    engine and then tears down the runner's scheduler/DB executors.
(b) ``test_run_engine_teardown_runs_on_failure`` — teardown still happens when
    ``runner.run()`` raises (the ``finally`` fires) and the failure is wrapped.
(c) ``test_run_engine_leaves_no_lingering_thread`` — no extra non-daemon
    background thread survives ``_run_engine()``.
(d) ``test_reap_run_children_terminates_survivor`` — a real child process that
    outlives the run is terminated by the reap backstop.
(e) ``test_shutdown_runner_never_raises`` — teardown is fully defensive on a
    misshapen runner.

Traceable to: sprint-016a §A2, issue #223/#314, ADR-007.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from revolver.core.exceptions import ExternalError
from revolver.infra.backends.base import BackendRunSpec
from revolver.infra.backends.shinka import SHINKA_WRAPPER_FILENAME, ShinkaBackend

pytestmark = [pytest.mark.integration]


def _make_spec(tmp_path: Path) -> BackendRunSpec:
    """Build a minimal spec whose snapshot/wrapper files exist on disk."""
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    (snapshot_dir / "initial_program.py").write_text("def solve():\n    return 0\n")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    wrapper_path = run_dir / SHINKA_WRAPPER_FILENAME
    wrapper_path.write_text("# wrapper\n")

    return BackendRunSpec(
        snapshot_dir=snapshot_dir,
        llm=MagicMock(name="llm"),
        run_dir=run_dir,
        wrapper_path=wrapper_path,
    )


def _make_runner_with_pools() -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build a mock runner exposing the scheduler/DB executors teardown touches."""
    scheduler = MagicMock(name="scheduler")
    db_executor = MagicMock(name="db_executor")
    db_write_executor = MagicMock(name="db_write_executor")
    async_db = MagicMock(name="async_db")
    async_db.executor = db_executor
    async_db.write_executor = db_write_executor

    runner = MagicMock(name="runner")
    runner.scheduler = scheduler
    runner.async_db = async_db
    return runner, scheduler, db_executor, db_write_executor


def _engine_classes_returning(runner: MagicMock) -> MagicMock:
    """Return a ``_engine_classes`` stub yielding a runner class -> *runner*."""
    runner_cls = MagicMock(name="ShinkaEvolveRunner", return_value=runner)
    evo_cls = MagicMock(name="EvolutionConfig")
    db_cls = MagicMock(name="DatabaseConfig")
    job_cls = MagicMock(name="LocalJobConfig")
    return MagicMock(return_value=(runner_cls, evo_cls, db_cls, job_cls))


def _empty_config() -> dict[str, Any]:
    return {"evo_config": {}, "db_config": {}, "job_config": {}}


def _patch_engine(backend: ShinkaBackend, engine_classes: MagicMock) -> Any:
    """Patch the engine-class import + dataclass filtering for a mock runner.

    The engine classes are mocks (not real dataclasses), so ``_dataclass_kwargs``
    (which calls ``dataclasses.fields``) is stubbed to a passthrough.
    """
    return patch.multiple(
        backend,
        _engine_classes=engine_classes,
        _dataclass_kwargs=MagicMock(side_effect=lambda section, _cls, _name: dict(section)),
    )


def test_run_engine_invokes_runner_teardown(tmp_path: Path) -> None:
    """The happy path runs the engine then shuts down its pools (A2)."""
    backend = ShinkaBackend()
    spec = _make_spec(tmp_path)
    runner, scheduler, db_executor, db_write_executor = _make_runner_with_pools()
    engine_classes = _engine_classes_returning(runner)

    with _patch_engine(backend, engine_classes):
        backend._run_engine(spec, _empty_config(), tmp_path / "out")

    runner.run.assert_called_once_with()
    # Scheduler + both DB executors are shut down without blocking (wait=False).
    scheduler.shutdown.assert_called_once_with(wait=False)
    db_executor.shutdown.assert_called_once_with(wait=False)
    db_write_executor.shutdown.assert_called_once_with(wait=False)


def test_run_engine_teardown_runs_on_failure(tmp_path: Path) -> None:
    """Teardown still fires (finally) when ``runner.run()`` raises."""
    backend = ShinkaBackend()
    spec = _make_spec(tmp_path)
    runner, scheduler, db_executor, db_write_executor = _make_runner_with_pools()
    runner.run.side_effect = RuntimeError("engine boom")
    engine_classes = _engine_classes_returning(runner)

    with (
        _patch_engine(backend, engine_classes),
        pytest.raises(ExternalError, match="ShinkaEvolve run failed"),
    ):
        backend._run_engine(spec, _empty_config(), tmp_path / "out")

    scheduler.shutdown.assert_called_once_with(wait=False)
    db_executor.shutdown.assert_called_once_with(wait=False)
    db_write_executor.shutdown.assert_called_once_with(wait=False)


def test_run_engine_leaves_no_lingering_thread(tmp_path: Path) -> None:
    """No extra non-daemon background thread survives ``_run_engine()``."""
    backend = ShinkaBackend()
    spec = _make_spec(tmp_path)
    runner, *_ = _make_runner_with_pools()
    engine_classes = _engine_classes_returning(runner)

    before = {t.ident for t in threading.enumerate()}
    with _patch_engine(backend, engine_classes):
        backend._run_engine(spec, _empty_config(), tmp_path / "out")
    after_non_daemon = {
        t.ident for t in threading.enumerate() if not t.daemon and t.ident not in before
    }
    assert after_non_daemon == set()


def test_reap_run_children_terminates_survivor(tmp_path: Path) -> None:
    """A child that outlives the run is reaped by the backstop (Linux only)."""
    if not Path("/proc/self/task").is_dir():
        pytest.skip("child PID enumeration requires Linux /proc")

    backend = ShinkaBackend()
    pre_run_children = backend._current_child_pids()

    # Spawn a long-lived child that would otherwise keep the CLI alive.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        # The child must now be visible as a new survivor.
        deadline = time.monotonic() + 5.0
        while child.pid not in (backend._current_child_pids() - pre_run_children):
            assert time.monotonic() < deadline, "child never appeared in /proc children"
            time.sleep(0.05)

        backend._reap_run_children(pre_run_children)

        # The reaped child has terminated (Popen.wait reaps the zombie).
        assert child.wait(timeout=5.0) is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5.0)


def test_reap_run_children_no_survivors_is_noop() -> None:
    """With no new children, the reap backstop does nothing and never raises."""
    backend = ShinkaBackend()
    current = backend._current_child_pids()
    # Passing the *current* set as the pre-run snapshot leaves zero survivors.
    with patch("os.kill") as mock_kill:
        backend._reap_run_children(current)
    mock_kill.assert_not_called()


def test_shutdown_runner_never_raises() -> None:
    """Teardown is fully defensive: a misshapen / None runner is tolerated."""
    backend = ShinkaBackend()

    # None runner (construction failed before assignment).
    backend._shutdown_runner(None)

    # Runner whose shutdown hooks raise — must be swallowed.
    bad_scheduler = MagicMock()
    bad_scheduler.shutdown.side_effect = RuntimeError("scheduler boom")
    bad_executor = MagicMock()
    bad_executor.shutdown.side_effect = RuntimeError("executor boom")
    bad_async_db = MagicMock()
    bad_async_db.executor = bad_executor
    bad_async_db.write_executor = bad_executor
    bad_runner = MagicMock()
    bad_runner.scheduler = bad_scheduler
    bad_runner.async_db = bad_async_db

    backend._shutdown_runner(bad_runner)  # must not raise

    # Runner missing the attributes entirely.
    bare = object()
    backend._shutdown_runner(bare)  # must not raise


def test_current_child_pids_returns_set() -> None:
    """``_current_child_pids`` returns a set of ints and never raises."""
    backend = ShinkaBackend()
    pids = backend._current_child_pids()
    assert isinstance(pids, set)
    assert all(isinstance(pid, int) for pid in pids)
    # The current process's own PID is never its own child.
    assert os.getpid() not in pids
