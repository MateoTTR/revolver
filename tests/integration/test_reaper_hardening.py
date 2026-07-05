"""L2 tests for the hardened ``ChildProcessReaperMixin`` (S18-18/19, #359).

The #320 spike (docs/analysis/spike-320-qwen15-deadlock.md §6) showed the
process tree the post-run reap must handle: a Shinka eval job is a plain
``subprocess.Popen`` direct child whose Revolver wrapper spawns a
``multiprocessing.Process`` **grandchild** per dataset instance. A per-PID
SIGTERM of the direct child orphans that grandchild, and the unbounded
wedge duration makes PID reuse between the pre-run snapshot and the reap a
real (not theoretical) hazard.

These tests exercise the S18-18 hardening at the mixin level (both backends
inherit it unchanged):

(a) ``test_reaper_grandchild_killpg`` — a direct child leading its own
    session with a ``multiprocessing`` grandchild is swept via ``killpg``;
    the grandchild is reaped, not just the direct child; our own process
    group is never signalled.
(b) ``test_reaper_killpg_failure_single_pid_fallback`` — when ``killpg``
    fails, the recursive descendant enumeration still reaches the
    grandchild through per-PID signalling.
(c) ``test_reaper_shared_group_single_pid_no_own_group_kill`` — survivors
    sharing the orchestrator's group are signalled per-PID only; ``killpg``
    is never invoked (killing our own group would kill the CLI itself).
(d) ``test_reaper_stale_snapshot_pid_never_signalled`` — PID-reuse guard:
    survivors are re-derived from ``/proc`` at reap time, so a post-snapshot
    child that already died (its PID now belonging to nothing reapable) is
    never signalled.
(e) ``test_signal_pid_if_unchanged_blocks_recycled_pid`` /
    ``test_pid_start_time_identity`` — the /proc start-time identity guard
    (stat field 22) blocks signals to a recycled PID.

Real processes are spawned (like the 017a shutdown backstop tests); every
test cleans them up in ``finally``. Linux-only (needs ``/proc``), like the
reap itself.

Traceable to: sprint-018.md S18-18/S18-19 + Exit Criterion 7, DES-005 §4.4,
issue #266 (#359 carry-over), spike #320 §6.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

import revolver.infra.backends.base as backends_base
from revolver.infra.backends.base import ChildProcessReaperMixin

pytestmark = [pytest.mark.integration]

# Real signalling primitives, captured before any test monkeypatches them —
# cleanup helpers must keep working under a patched ``os.kill``/``os.killpg``.
_REAL_KILL = os.kill
_REAL_KILLPG = os.killpg

# Direct child mirroring the spike §6 tree: (optionally) its own session,
# then a spawn-context ``multiprocessing.Process`` grandchild (the Revolver
# wrapper's per-instance timeout guard), then a long sleep. It prints the
# grandchild PID so the test can track it.
_CHILD_TREE_SCRIPT = '''\
"""Reaper-test process tree: direct child + multiprocessing grandchild."""

import multiprocessing
import os
import sys
import time


def _instance_guard() -> None:
    time.sleep(120)


if __name__ == "__main__":
    if os.environ.get("REAPER_TEST_SETSID") == "1":
        os.setsid()
    ctx = multiprocessing.get_context("spawn")
    grandchild = ctx.Process(target=_instance_guard)
    grandchild.start()
    print(grandchild.pid, flush=True)
    time.sleep(120)
'''


def _require_proc() -> None:
    if not Path("/proc/self/task").is_dir():
        pytest.skip("child PID enumeration requires Linux /proc")


def _spawn_tree(tmp_path: Path, *, setsid: bool) -> tuple[subprocess.Popen[str], int]:
    """Spawn the child+grandchild tree; return ``(child, grandchild_pid)``."""
    script = tmp_path / "reaper_child_tree.py"
    script.write_text(_CHILD_TREE_SCRIPT)
    env = dict(os.environ)
    env["REAPER_TEST_SETSID"] = "1" if setsid else "0"
    child = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        env=env,
        text=True,
    )
    assert child.stdout is not None
    line = child.stdout.readline()  # blocks until the grandchild started
    if not line.strip():
        # Child died before reporting its grandchild — fail legibly instead
        # of an opaque ValueError on int("").
        raise AssertionError(
            f"child tree died before reporting its grandchild (exit={child.poll()})"
        )
    return child, int(line.strip())


def _cleanup_tree(child: subprocess.Popen[str], grandchild_pid: int) -> None:
    """Best-effort teardown so no test process outlives its test."""
    with contextlib.suppress(OSError):
        _REAL_KILLPG(child.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        _REAL_KILL(grandchild_pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        _REAL_KILL(child.pid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        child.wait(timeout=5.0)


def _wait_descendants_visible(
    mixin: ChildProcessReaperMixin, pre: set[int], pids: set[int]
) -> None:
    """Wait until *pids* all appear as new descendants (recursion proof)."""
    deadline = time.monotonic() + 5.0
    while not pids <= (mixin._current_child_pids() - pre):
        assert time.monotonic() < deadline, "expected descendants never appeared in /proc"
        time.sleep(0.05)


def _assert_pid_dead(pid: int) -> None:
    """Assert *pid* is gone (or a zombie awaiting its parent's wait)."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        fields = backends_base._pid_stat_fields(pid)
        if fields is None or fields[0] == "Z":
            return
        time.sleep(0.05)
    pytest.fail(f"pid {pid} still alive after reap")


def test_reaper_grandchild_killpg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A leaked grandchild is reaped via recursive enumeration + killpg.

    The direct child leads its own session (like the S17a eval worker), so
    the whole tree lives in a foreign process group: the reap must sweep it
    with ``os.killpg`` — and must never signal our own group.
    """
    _require_proc()
    monkeypatch.setattr(backends_base, "_CHILD_REAP_GRACE_SECONDS", 1.0)
    mixin = ChildProcessReaperMixin()
    pre = mixin._current_child_pids()
    child, grandchild_pid = _spawn_tree(tmp_path, setsid=True)
    try:
        # Recursive-descendant enumeration sees the grandchild too.
        _wait_descendants_visible(mixin, pre, {child.pid, grandchild_pid})

        killpg_calls: list[tuple[int, int]] = []
        real_killpg = os.killpg

        def _recording_killpg(pgid: int, sig: int) -> None:
            killpg_calls.append((pgid, sig))
            real_killpg(pgid, sig)

        monkeypatch.setattr(os, "killpg", _recording_killpg)

        mixin._reap_run_children(pre)

        # killpg path: the child's own session/group was swept...
        assert (child.pid, signal.SIGTERM) in killpg_calls
        # ...and our own group was never signalled.
        assert all(pgid != os.getpgrp() for pgid, _ in killpg_calls)
        # Direct child terminated by a signal.
        assert child.wait(timeout=5.0) != 0
        # The grandchild is reaped too — the #359 caveat this PR closes.
        _assert_pid_dead(grandchild_pid)
    finally:
        _cleanup_tree(child, grandchild_pid)


def test_reaper_killpg_failure_single_pid_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When killpg fails, per-PID fallback still reaps the whole tree.

    Recursive enumeration makes the grandchild an explicit target, so the
    single-PID path reaches it even without a group sweep.
    """
    _require_proc()
    monkeypatch.setattr(backends_base, "_CHILD_REAP_GRACE_SECONDS", 1.0)
    mixin = ChildProcessReaperMixin()
    pre = mixin._current_child_pids()
    child, grandchild_pid = _spawn_tree(tmp_path, setsid=True)
    try:
        _wait_descendants_visible(mixin, pre, {child.pid, grandchild_pid})

        def _failing_killpg(pgid: int, sig: int) -> None:
            raise OSError("simulated killpg failure")

        monkeypatch.setattr(os, "killpg", _failing_killpg)

        mixin._reap_run_children(pre)

        assert child.wait(timeout=5.0) != 0
        _assert_pid_dead(grandchild_pid)
    finally:
        _cleanup_tree(child, grandchild_pid)


def test_reaper_shared_group_single_pid_no_own_group_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Survivors in the orchestrator's own group are signalled per-PID only.

    The child does NOT call ``setsid``, so child and grandchild share this
    test process's group: a group sweep would kill the test itself. The reap
    must never call ``killpg`` here, yet still reap both processes.
    """
    _require_proc()
    monkeypatch.setattr(backends_base, "_CHILD_REAP_GRACE_SECONDS", 1.0)
    mixin = ChildProcessReaperMixin()
    pre = mixin._current_child_pids()
    child, grandchild_pid = _spawn_tree(tmp_path, setsid=False)
    try:
        _wait_descendants_visible(mixin, pre, {child.pid, grandchild_pid})

        killpg_calls: list[tuple[int, int]] = []
        # Record-only stub: if the reap wrongly targeted our own group, the
        # assertion catches it without actually killing the test process.
        monkeypatch.setattr(os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)))

        mixin._reap_run_children(pre)

        assert killpg_calls == []
        assert child.wait(timeout=5.0) != 0
        _assert_pid_dead(grandchild_pid)
    finally:
        _cleanup_tree(child, grandchild_pid)


def test_reaper_stale_snapshot_pid_never_signalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PID-reuse guard: a dead post-snapshot PID is never signalled.

    Survivors are re-derived from ``/proc`` at reap time — a child that
    appeared after the snapshot but already exited (its PID now belonging
    to nothing reapable, or to an unrelated process) receives no signal.
    """
    _require_proc()
    mixin = ChildProcessReaperMixin()
    pre = mixin._current_child_pids()

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_pid = child.pid
    child.wait(timeout=10.0)  # fully reaped: /proc entry gone

    kill_calls: list[tuple[int, int]] = []
    killpg_calls: list[tuple[int, int]] = []
    real_kill = os.kill
    real_killpg = os.killpg

    def _recording_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        real_kill(pid, sig)

    def _recording_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append((pgid, sig))
        real_killpg(pgid, sig)

    monkeypatch.setattr(os, "kill", _recording_kill)
    monkeypatch.setattr(os, "killpg", _recording_killpg)

    # Reap against the ORIGINAL pre-run snapshot: dead_pid appeared after
    # it, yet must not be treated as a survivor. NOTE: dead_pid is excluded
    # by the `current - pre` set difference before the identity guard even
    # runs — this test pins the stale-snapshot filtering; the recycled-PID
    # identity guard itself is discriminated by
    # test_signal_pid_if_unchanged_blocks_recycled_pid.
    mixin._reap_run_children(pre)

    assert all(pid != dead_pid for pid, _ in kill_calls)
    assert all(pgid != dead_pid for pgid, _ in killpg_calls)


def test_signal_pid_if_unchanged_blocks_recycled_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The identity guard: a start-time mismatch means PID reuse — no signal."""
    _require_proc()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        start_time = backends_base._pid_start_time(child.pid)
        assert isinstance(start_time, int)

        calls: list[tuple[int, int]] = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: calls.append((pid, sig)))

        # Simulated PID reuse: the recorded identity no longer matches the
        # live process -> the guard must swallow the signal.
        backends_base._signal_pid_if_unchanged(child.pid, start_time + 1, signal.SIGTERM)
        assert calls == []

        # Matching identity -> signalled normally.
        backends_base._signal_pid_if_unchanged(child.pid, start_time, signal.SIGTERM)
        assert calls == [(child.pid, signal.SIGTERM)]
    finally:
        with contextlib.suppress(OSError):
            _REAL_KILL(child.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            child.wait(timeout=5.0)


def test_pid_start_time_identity() -> None:
    """Start-time reads: an int for a live process, changed/None once dead."""
    _require_proc()
    assert isinstance(backends_base._pid_start_time(os.getpid()), int)

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    original = backends_base._pid_start_time(child.pid)
    assert isinstance(original, int)
    child.wait(timeout=10.0)
    # After the wait() the incarnation is gone: the stat entry vanished (or,
    # in the pathological instant-reuse case, carries a different start time).
    assert backends_base._pid_start_time(child.pid) != original


def test_current_child_pids_includes_grandchildren(tmp_path: Path) -> None:
    """The descendant enumeration is recursive (S18-18)."""
    _require_proc()
    mixin = ChildProcessReaperMixin()
    pre = mixin._current_child_pids()
    child, grandchild_pid = _spawn_tree(tmp_path, setsid=False)
    try:
        _wait_descendants_visible(mixin, pre, {child.pid, grandchild_pid})
        descendants = mixin._current_child_pids()
        assert {child.pid, grandchild_pid} <= descendants
        assert os.getpid() not in descendants
    finally:
        _cleanup_tree(child, grandchild_pid)
