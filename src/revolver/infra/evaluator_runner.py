"""Subprocess-based evaluator runner with kill-on-timeout enforcement.

Executes an evaluator against a program/instance pair inside a child
process for isolation. The child runs in a **spawn**-context
:class:`multiprocessing.Process` in its own session (``os.setsid()``), so
that on timeout the whole process group can be terminated — no worker may
survive the call (U12, task 358). Spawn (not fork) is load-bearing: the
parent process may have numpy/OpenBLAS pre-initialized (e.g. via
``shinka.database`` imports), and a forked child would inherit that
uncapped state.

Before importing the evaluator, the child applies a BLAS/OpenMP
thread-cap environment family (mirroring ShinkaEvolve's scheduler) so
that evaluations do not oversubscribe cores (U14, task 358). The cap is
controlled by the ``REVOLVER_EVAL_NUM_THREADS`` environment variable
(``0`` disables the cap) and defaults to ``max(1, os.cpu_count() // 2)``.
If the user already set any cap variable, Revolver injects nothing.

Traceable to: DES-006 (Evaluation Loop), FR-EVL-002, NFR-007.
"""

from __future__ import annotations

from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import importlib.util
import multiprocessing
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue as MPQueue
import os
from pathlib import Path
import pickle
import queue as queue_module
import signal
import sys
import time
import traceback
from typing import Any, Literal

from revolver.models.problem import InstanceTestResult

# ── Thread-cap environment family (U14) ──────────────────────────────────────

#: Numeric-thread cap variables, mirroring ``shinka/launch/scheduler.py``.
THREAD_CAP_VARS: tuple[str, ...] = (
    "OMP_NUM_THREADS",
    "OMP_THREAD_LIMIT",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "NUMEXPR_MAX_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
    "GOTO_NUM_THREADS",
)

#: Fixed threading-policy variables injected alongside the cap.
THREAD_POLICY_VARS: dict[str, str] = {
    "OMP_DYNAMIC": "FALSE",
    "MKL_DYNAMIC": "FALSE",
    "OMP_WAIT_POLICY": "PASSIVE",
}

#: Environment variable controlling the per-eval-process thread cap.
THREADS_ENV_VAR = "REVOLVER_EVAL_NUM_THREADS"

# Poll/teardown tunables for the killable worker.
_POLL_INTERVAL_S = 0.1
_TERM_GRACE_S = 3.0
_DRAIN_GRACE_S = 1.0
_STRAGGLER_GRACE_S = 0.5

# One announce line per parent process (not per instance).
_cap_announced = False


def _resolve_thread_cap(numeric_threads: int | None) -> int | None:
    """Resolve the numeric thread cap to apply to eval subprocesses.

    Precedence among Revolver-managed sources: explicit ``numeric_threads``
    argument > ``REVOLVER_EVAL_NUM_THREADS`` environment variable (``0`` =
    uncapped, invalid = warn and ignore) > default
    ``max(1, os.cpu_count() // 2)``.

    Note: :func:`_build_thread_cap_env` gates this function entirely — when
    ANY cap/policy variable is already set in the parent environment,
    nothing is injected and this resolution never runs, **including for an
    explicit** ``numeric_threads`` **argument**: user-env presence wins
    over everything, the user owns threading (issue #240 rule).

    Args:
        numeric_threads: Explicit cap from the caller, or ``None``.

    Returns:
        The cap as a positive integer, or ``None`` for uncapped.
    """
    if numeric_threads is not None:
        if numeric_threads == 0:
            return None
        return max(1, numeric_threads)

    raw = os.environ.get(THREADS_ENV_VAR)
    if raw is not None:
        try:
            value = int(raw)
        except ValueError:
            value = -1
        if value == 0:
            return None
        if value > 0:
            return value
        print(
            f"[revolver] Warning: invalid {THREADS_ENV_VAR}={raw!r} (expected a "
            "non-negative integer); using the default thread cap.",
            file=sys.stderr,
        )

    return max(1, (os.cpu_count() or 1) // 2)


def _build_thread_cap_env(numeric_threads: int | None) -> dict[str, str]:
    """Build the thread-cap env overrides for an eval subprocess.

    If ANY cap or policy variable is already set in the parent environment,
    nothing is injected: the user owns threading (this preserves e.g. a
    manual ``OMP_NUM_THREADS=2`` workaround). Otherwise the full 9-variable
    cap family plus the fixed policy variables are returned.

    A single stderr line announces the applied cap, once per process.

    Args:
        numeric_threads: Explicit cap from the caller, or ``None``.

    Returns:
        Env overrides to apply in the child (possibly empty).
    """
    global _cap_announced

    if any(var in os.environ for var in (*THREAD_CAP_VARS, *THREAD_POLICY_VARS)):
        return {}

    cap = _resolve_thread_cap(numeric_threads)
    if cap is None:
        return {}

    env = dict.fromkeys(THREAD_CAP_VARS, str(cap))
    env.update(THREAD_POLICY_VARS)

    if not _cap_announced:
        print(
            f"[revolver] numeric thread cap per eval process: {cap} "
            f"({THREADS_ENV_VAR}=0 to disable)",
            file=sys.stderr,
        )
        _cap_announced = True

    return env


# ── Child-side worker functions ───────────────────────────────────────────────


def _run_in_subprocess(
    evaluator_path: str,
    program_path: str,
    instance_path: str,
    instance_id: str,
) -> dict[str, float]:
    """Worker function executed in a child process.

    Sets environment variables and dynamically loads the evaluator module,
    then calls ``evaluate(program_path)`` or
    ``evaluate_instance(program_path, instance_path)`` depending on which
    function the evaluator defines.
    """
    os.environ["REVOLVER_INSTANCE_PATH"] = instance_path
    os.environ["REVOLVER_INSTANCE_ID"] = instance_id

    spec = importlib.util.spec_from_file_location("evaluator", evaluator_path)
    if spec is None or spec.loader is None:
        msg = f"Cannot load evaluator from {evaluator_path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if hasattr(module, "evaluate") and callable(module.evaluate):
        has_both = hasattr(module, "evaluate_instance") and callable(module.evaluate_instance)
        # Skip warning for auto-generated wrapper (has both functions by design)
        is_wrapper = Path(evaluator_path).name == "_revolver_evaluator.py"
        if has_both and not is_wrapper:
            print(
                "[revolver] Warning: evaluator defines both evaluate() "
                "and evaluate_instance(). Using evaluate() (legacy mode).",
                file=sys.stderr,
            )
        result: dict[str, float] = module.evaluate(program_path)
    elif hasattr(module, "evaluate_instance") and callable(module.evaluate_instance):
        result = module.evaluate_instance(program_path, instance_path)
    else:
        raise RuntimeError(
            f"Evaluator {evaluator_path} defines neither evaluate() nor evaluate_instance()"
        )
    return result


def _worker_entrypoint(
    result_queue: MPQueue[tuple[Any, ...]],
    worker: Callable[..., dict[str, float]],
    worker_args: tuple[str, ...],
    env_overrides: dict[str, str],
) -> None:
    """Child-process entrypoint for :func:`run_killable_worker`.

    Detaches into its own session first (so the parent can kill the whole
    process group, including any grandchildren the evaluator spawns), then
    applies the env overrides **before** importing the evaluator (BLAS
    libraries read the cap variables at load time), then runs ``worker``.

    Sends ``("ok", metrics)`` or ``("err", message, traceback)`` on the
    result queue — error payloads are strings only, so unpicklable user
    exceptions cannot wedge the pipe.
    """
    with contextlib.suppress(AttributeError, OSError):
        os.setsid()
    os.environ.update(env_overrides)

    payload: tuple[Any, ...]
    try:
        payload = ("ok", worker(*worker_args))
    except Exception as exc:
        payload = ("err", str(exc), traceback.format_exc())
    try:
        # Pre-check picklability here (mp.Queue pickles in a feeder thread,
        # where failures would be silent and the parent would see a crash).
        pickle.dumps(payload)
    except Exception as exc:
        payload = ("err", f"Evaluator returned an unpicklable result: {exc}", None)
    result_queue.put(payload)


# ── Parent-side killable worker primitive (U12) ───────────────────────────────


@dataclass(frozen=True)
class WorkerOutcome:
    """Outcome of a killable eval worker run.

    Attributes:
        status: ``"ok"`` (worker returned metrics), ``"err"`` (worker
            raised), ``"timeout"`` (deadline hit, child killed), or
            ``"crashed"`` (child exited without reporting a result).
        metrics: Metrics returned by the worker (``status == "ok"``).
        error: Error message (``"err"``/``"crashed"``).
        traceback: Child-side traceback string, if available.
        elapsed_s: Wall-clock seconds spent before the outcome.
    """

    status: Literal["ok", "err", "timeout", "crashed"]
    metrics: dict[str, float] | None = None
    error: str | None = None
    traceback: str | None = None
    elapsed_s: float = 0.0


def _own_pgid(process: BaseProcess) -> int | None:
    """Return the child's process-group id if it leads its own group.

    The group id is returned only when the child established its own
    session (``getpgid(pid) == pid``): if ``os.setsid()`` had not run yet
    (e.g. the deadline fired during spawn bootstrap), the child still
    shares the parent's process group and ``killpg`` would signal the
    parent too. Returns ``None`` on any ``getpgid`` failure.

    Note: ``getpgid``/``killpg`` carry an inherent TOCTOU / PID-reuse
    window; hardening was deferred to v0.18 (Sprint 017a decision) and shipped
    there as the ``base.py`` reap hardening (backlog row 359).
    """
    pid = process.pid
    if pid is None:
        return None
    try:
        pgid = os.getpgid(pid)
    except (AttributeError, OSError):
        return None
    return pgid if pgid == pid else None


def _signal_child(process: BaseProcess, sig: signal.Signals) -> None:
    """Signal the child's process group, falling back to the single PID.

    Falls back to a single-PID ``terminate()``/``kill()`` when the child
    does not lead its own group (see :func:`_own_pgid`) or ``killpg``
    fails.
    """
    pgid = _own_pgid(process)
    if pgid is not None:
        try:
            os.killpg(pgid, sig)
            return
        except (AttributeError, OSError):
            pass

    with contextlib.suppress(OSError, ValueError):
        if sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()


def _kill_child(process: BaseProcess) -> None:
    """Terminate the child (and its process group): SIGTERM, grace, SIGKILL."""
    if process.pid is None or not process.is_alive():
        if process.pid is not None:
            # Reap a finished child so it does not linger as a zombie.
            process.join(timeout=_TERM_GRACE_S)
        return
    _signal_child(process, signal.SIGTERM)
    process.join(timeout=_TERM_GRACE_S)
    if process.is_alive():
        # SIGKILL is undefined on non-POSIX platforms; degrade to SIGTERM
        # (process.terminate() is a hard TerminateProcess there anyway).
        _signal_child(process, getattr(signal, "SIGKILL", signal.SIGTERM))
        process.join(timeout=_TERM_GRACE_S)


def _reap_process_group(pgid: int) -> None:
    """Best-effort SIGTERM → grace → SIGKILL sweep of a process group.

    Called after the direct child has been reaped: any process still in
    the group is a straggler the evaluator backgrounded (grandchild). A
    ``ProcessLookupError`` on the first signal means the group is already
    empty — the common case — and returns without sleeping.
    """
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (AttributeError, OSError):
        return
    # At least one straggler was signalled: short grace, then hard kill.
    time.sleep(_STRAGGLER_GRACE_S)
    with contextlib.suppress(AttributeError, OSError):
        os.killpg(pgid, getattr(signal, "SIGKILL", signal.SIGTERM))


def run_killable_worker(
    worker: Callable[..., dict[str, float]],
    worker_args: tuple[str, ...],
    timeout_s: float,
    numeric_threads: int | None = None,
) -> WorkerOutcome:
    """Run ``worker(*worker_args)`` in a killable spawn-context subprocess.

    The parent polls the result queue against a deadline (it does NOT join
    first: a child blocked writing a large result must not read as a
    timeout). On deadline the child's process group receives SIGTERM, then
    after a grace period SIGKILL — no child survives this call.

    Args:
        worker: Module-level (picklable) function returning a metrics dict.
        worker_args: Positional string arguments for ``worker``.
        timeout_s: Deadline in seconds.
        numeric_threads: Explicit thread cap (see :func:`_resolve_thread_cap`).

    Returns:
        A :class:`WorkerOutcome`.
    """
    start = time.monotonic()
    env_overrides = _build_thread_cap_env(numeric_threads)

    ctx = multiprocessing.get_context("spawn")
    result_queue: MPQueue[tuple[Any, ...]] = ctx.Queue()
    process = ctx.Process(
        target=_worker_entrypoint,
        args=(result_queue, worker, worker_args, env_overrides),
    )

    payload: tuple[Any, ...] | None = None
    timed_out = False
    try:
        process.start()
        deadline = start + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                timed_out = True
                break
            try:
                payload = result_queue.get(timeout=min(remaining, _POLL_INTERVAL_S))
                break
            except queue_module.Empty:
                if not process.is_alive():
                    # Child exited: drain a result that raced the exit.
                    try:
                        payload = result_queue.get(timeout=_DRAIN_GRACE_S)
                    except queue_module.Empty:
                        payload = None
                    break

        elapsed = time.monotonic() - start

        # Capture the group id now: once the child is joined (reaped),
        # getpgid(pid) no longer works, but stragglers keep the group alive.
        pgid = _own_pgid(process)

        if timed_out:
            _kill_child(process)
            if pgid is not None:
                # Sweep grandchildren that survived the group SIGTERM.
                _reap_process_group(pgid)
            return WorkerOutcome(status="timeout", elapsed_s=elapsed)

        # Child finished (or crashed): reap it, then group-reap stragglers —
        # a *passing* eval must not leak a backgrounded grandchild either.
        process.join(timeout=_TERM_GRACE_S)
        if process.is_alive():
            _kill_child(process)
        if pgid is not None:
            _reap_process_group(pgid)

        if payload is None:
            exitcode = process.exitcode
            return WorkerOutcome(
                status="crashed",
                error=(
                    "Evaluator subprocess exited unexpectedly "
                    f"(exit code {exitcode}) before returning a result"
                ),
                elapsed_s=elapsed,
            )
        if payload[0] == "ok":
            return WorkerOutcome(status="ok", metrics=payload[1], elapsed_s=elapsed)
        return WorkerOutcome(
            status="err", error=payload[1], traceback=payload[2], elapsed_s=elapsed
        )
    except BaseException:
        # Never leak a live child, even on KeyboardInterrupt or internal errors.
        _kill_child(process)
        raise
    finally:
        result_queue.close()


# ── Public API ────────────────────────────────────────────────────────────────


def run_instance(
    evaluator_path: Path,
    program_path: Path,
    instance_path: Path,
    timeout_s: float = 300.0,
    numeric_threads: int | None = None,
) -> InstanceTestResult:
    """Run an evaluator on a single instance with subprocess isolation and timeout.

    Sets ``REVOLVER_INSTANCE_PATH`` and ``REVOLVER_INSTANCE_ID`` environment
    variables in the child process before invoking the evaluator. On
    timeout, the child process (and its process group) is killed — no
    worker survives the call.

    Args:
        evaluator_path: Path to the evaluator ``.py`` file.
        program_path: Path to the program being evaluated.
        instance_path: Path to the instance data file.
        timeout_s: Maximum wall-clock time (seconds) before the run is
            considered timed out.  Defaults to 300.
        numeric_threads: Explicit BLAS/OpenMP thread cap for the child
            (``0`` = uncapped). ``None`` defers to
            ``REVOLVER_EVAL_NUM_THREADS``, then ``max(1, cpu_count // 2)``.

    Returns:
        An :class:`InstanceTestResult` with status ``"pass"``, ``"fail"``,
        or ``"timeout"``.
    """
    instance_id = instance_path.name

    try:
        outcome = run_killable_worker(
            _run_in_subprocess,
            (
                str(evaluator_path),
                str(program_path),
                str(instance_path.resolve()),
                instance_id,
            ),
            timeout_s=timeout_s,
            numeric_threads=numeric_threads,
        )
    except Exception as exc:
        return InstanceTestResult(
            instance_id=instance_id,
            status="fail",
            time_s=0.0,
            error=str(exc),
            traceback=traceback.format_exc(),
        )

    if outcome.status == "timeout":
        return InstanceTestResult(
            instance_id=instance_id,
            status="timeout",
            time_s=outcome.elapsed_s,
            error=f"Evaluation timed out after {timeout_s}s",
        )
    if outcome.status == "ok":
        try:
            return InstanceTestResult(
                instance_id=instance_id,
                status="pass",
                metrics=outcome.metrics,
                time_s=outcome.elapsed_s,
            )
        except Exception as exc:
            # Invalid metrics payload (e.g. non-float values) — same
            # status="fail" contract as the pre-rewrite except-Exception path.
            return InstanceTestResult(
                instance_id=instance_id,
                status="fail",
                time_s=outcome.elapsed_s,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
    # "err" (worker raised) or "crashed" (child died without a result).
    return InstanceTestResult(
        instance_id=instance_id,
        status="fail",
        time_s=outcome.elapsed_s,
        error=outcome.error,
        traceback=outcome.traceback,
    )
