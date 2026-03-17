"""Subprocess-based evaluator runner with timeout enforcement.

Executes an evaluator against a program/instance pair inside a child
process for isolation. Timeout is enforced via
``concurrent.futures.ProcessPoolExecutor``.

Traceable to: DES-006 (Evaluation Loop), FR-EVL-002, NFR-007.
"""

from __future__ import annotations

import importlib.util
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

from revolver.models.problem import InstanceTestResult


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
        if hasattr(module, "evaluate_instance") and callable(module.evaluate_instance):
            import sys

            print(
                "[revolver] Warning: evaluator defines both evaluate() and evaluate_instance(). "
                "Using evaluate() (legacy mode).",
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


def run_instance(
    evaluator_path: Path,
    program_path: Path,
    instance_path: Path,
    timeout_s: float = 300.0,
) -> InstanceTestResult:
    """Run an evaluator on a single instance with subprocess isolation and timeout.

    Sets ``REVOLVER_INSTANCE_PATH`` and ``REVOLVER_INSTANCE_ID`` environment
    variables in the child process before invoking the evaluator.

    Args:
        evaluator_path: Path to the evaluator ``.py`` file.
        program_path: Path to the program being evaluated.
        instance_path: Path to the instance data file.
        timeout_s: Maximum wall-clock time (seconds) before the run is
            considered timed out.  Defaults to 300.

    Returns:
        An :class:`InstanceTestResult` with status ``"pass"``, ``"fail"``,
        or ``"timeout"``.
    """
    instance_id = instance_path.name
    start = time.monotonic()

    executor = ProcessPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            _run_in_subprocess,
            str(evaluator_path),
            str(program_path),
            str(instance_path.resolve()),
            instance_id,
        )
        metrics = future.result(timeout=timeout_s)
        elapsed = time.monotonic() - start
        return InstanceTestResult(
            instance_id=instance_id,
            status="pass",
            metrics=metrics,
            time_s=elapsed,
        )
    except FuturesTimeoutError:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        elapsed = time.monotonic() - start
        return InstanceTestResult(
            instance_id=instance_id,
            status="timeout",
            time_s=elapsed,
            error=f"Evaluation timed out after {timeout_s}s",
        )
    except Exception as exc:
        elapsed = time.monotonic() - start
        return InstanceTestResult(
            instance_id=instance_id,
            status="fail",
            time_s=elapsed,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
