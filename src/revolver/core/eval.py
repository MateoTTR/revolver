"""Core evaluation logic: evaluate solutions against datasets.

Implements the evaluation loop (DES-006): iterate over dataset instances,
call the evaluator in a subprocess, store raw per-instance results in SQLite,
and compute aggregates at read time.

Traceable to: DES-006, FR-EVL-001..020.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time
from typing import Literal

from revolver.core.dataset import resolve_dataset_path, verify_dataset_integrity
from revolver.core.exceptions import (
    EvalError,
    EvalNotFoundError,
    RevolverError,
)
from revolver.infra.db import (
    delete_eval,
    get_dataset,
    get_dataset_compat,
    get_eval_instances,
    get_eval_metadata,
    get_project_db,
    get_run,
    get_solution,
    insert_eval_instance,
    insert_eval_metadata,
    update_eval_metadata,
)
from revolver.infra.evaluator_runner import run_instance
from revolver.infra.store import (
    PROBLEM_DIR,
    REVOLVER_DIR,
    RUNS_DIR,
    ProjectNotFoundError as StoreProjectNotFoundError,
    find_project_root,
)
from revolver.models.eval import (
    ComputeTimeSummary,
    EvalDetailResult,
    EvalMetadata,
    EvalResult,
    InstanceResult,
    MetricAggregate,
)


def _resolve_project_root(project_root: Path | None = None) -> Path:
    """Resolve and return the project root directory."""
    try:
        return find_project_root(project_root or Path.cwd())
    except StoreProjectNotFoundError as exc:
        raise RevolverError(str(exc)) from exc


def generate_eval_id(suffix: int | None = None) -> str:
    """Generate an evaluation ID in the format ``eval-YYYYMMDD-HHMMSS[-N]``.

    If ``suffix`` is provided (a positive integer), it is appended as
    ``-N`` to disambiguate same-second collisions.

    Args:
        suffix: Optional integer suffix for collision avoidance.

    Returns:
        An evaluation ID string.
    """
    now = datetime.now(UTC)
    base = now.strftime("eval-%Y%m%d-%H%M%S")
    if suffix is not None:
        return f"{base}-{suffix}"
    return base


def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile using linear interpolation (same as numpy default).

    Args:
        sorted_values: Pre-sorted list of float values.
        p: Percentile as a fraction in [0, 1].

    Returns:
        The interpolated percentile value.
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    k = (n - 1) * p
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_values[-1]
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])


def compute_aggregates(
    instances: list[InstanceResult],
) -> dict[str, MetricAggregate]:
    """Compute aggregate statistics from raw per-instance results.

    For each metric key found across solved instances:
    mean, min, max, p10, p50 (median), p90, std (sample; 0.0 if n=1).

    Args:
        instances: List of per-instance evaluation results.

    Returns:
        Dict mapping metric_name to :class:`MetricAggregate`.
    """
    solved = [i for i in instances if i.status == "solved"]
    if not solved:
        return {}

    # Discover all metric keys
    all_keys: set[str] = set()
    for inst in solved:
        all_keys.update(inst.metrics.keys())

    aggregates: dict[str, MetricAggregate] = {}
    for key in sorted(all_keys):
        values = [inst.metrics[key] for inst in solved if key in inst.metrics]
        if not values:
            continue
        values_sorted = sorted(values)
        n = len(values_sorted)
        aggregates[key] = MetricAggregate(
            mean=statistics.mean(values),
            min=min(values),
            max=max(values),
            p10=_percentile(values_sorted, 0.10),
            p50=_percentile(values_sorted, 0.50),
            p90=_percentile(values_sorted, 0.90),
            std=statistics.stdev(values) if n > 1 else 0.0,
            count=n,
        )
    return aggregates


def _detect_evaluator_mode(evaluator_path: Path) -> str:
    """Detect evaluator mode by checking which functions are defined.

    Detection priority (DES-006 DD-06):
    1. If ``evaluate()`` exists -> "legacy" mode
    2. Else if ``evaluate_instance()`` exists -> "instance" mode
    3. Else -> error

    Args:
        evaluator_path: Path to the evaluator Python file.

    Returns:
        ``"legacy"`` or ``"instance"``.

    Raises:
        EvalError: If neither function is found.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_eval_detect", str(evaluator_path))
    if spec is None or spec.loader is None:
        raise EvalError(f"Cannot load evaluator from {evaluator_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise EvalError(f"Failed to load evaluator: {exc}") from exc

    if hasattr(module, "evaluate") and callable(module.evaluate):
        return "legacy"
    if hasattr(module, "evaluate_instance") and callable(module.evaluate_instance):
        return "instance"

    raise EvalError(
        f"Evaluator {evaluator_path} defines neither evaluate() nor evaluate_instance()"
    )


def _run_legacy_global_aggregation(
    evaluator_path: Path,
    program_path: Path,
    dataset_dir: Path,
    timeout_s: int = 300,
) -> dict[str, float] | None:
    """Run the legacy evaluate() global aggregation call.

    Calls evaluate() with REVOLVER_DATASET_DIR set and REVOLVER_INSTANCE_PATH
    NOT set. This allows the evaluator to compute custom aggregates across the
    entire dataset.

    Args:
        evaluator_path: Path to the evaluator file.
        program_path: Path to the program being evaluated.
        dataset_dir: Path to the dataset directory.
        timeout_s: Timeout in seconds.

    Returns:
        Dict of aggregate metrics, or ``None`` on failure.
    """
    from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError
    import importlib.util
    import os

    def _global_eval_worker(
        eval_path_str: str,
        prog_path_str: str,
        dataset_dir_str: str,
    ) -> dict[str, float]:
        """Worker for global aggregation call in subprocess."""
        os.environ["REVOLVER_DATASET_DIR"] = dataset_dir_str
        os.environ.pop("REVOLVER_INSTANCE_PATH", None)
        os.environ.pop("REVOLVER_INSTANCE_ID", None)

        spec = importlib.util.spec_from_file_location("evaluator", eval_path_str)
        if spec is None or spec.loader is None:
            msg = f"Cannot load evaluator from {eval_path_str}"
            raise RuntimeError(msg)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result: dict[str, float] = mod.evaluate(prog_path_str)
        return result

    executor = ProcessPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            _global_eval_worker,
            str(evaluator_path),
            str(program_path),
            str(dataset_dir.resolve()),
        )
        result = future.result(timeout=timeout_s)
        return result
    except FuturesTimeoutError:
        future.cancel()
        sys.stderr.write("Warning: legacy global aggregation timed out\n")
        return None
    except Exception as exc:
        sys.stderr.write(f"Warning: legacy global aggregation failed: {exc}\n")
        return None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def evaluate_solution(
    solution_id_or_alias: str,
    dataset_name: str,
    timeout_s: int = 300,
    force: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
    project_root: Path | None = None,
) -> EvalResult:
    """Evaluate a solution against a dataset.

    Resolves solution -> run -> program path, iterates dataset instances,
    stores raw results immediately, computes aggregates.

    Called by both ``revolver eval`` (CLI) and ``core.run`` (post-run eval).

    Args:
        solution_id_or_alias: Solution ID or alias to evaluate.
        dataset_name: Registered dataset name.
        timeout_s: Per-instance timeout in seconds.
        force: If ``True``, delete existing evaluation before re-evaluating.
        on_progress: Callback ``(completed, total)`` for progress reporting.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        An :class:`EvalResult` with metadata, aggregates, and compute time.

    Raises:
        EvalError: If the solution or dataset is not found, or if an
            evaluation already exists and ``force`` is ``False``.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)

    try:
        # 1. Resolve solution
        solution = get_solution(conn, solution_id_or_alias)
        if solution is None:
            raise EvalError(f"Solution '{solution_id_or_alias}' not found.")

        # 2. Resolve run
        run = get_run(conn, solution.run_id)
        if run is None:
            raise EvalError(f"Run '{solution.run_id}' not found for solution '{solution.id}'.")
        problem_version = str(run["problem_version"])

        # 3. Load dataset registration
        ds = get_dataset(conn, dataset_name)
        if ds is None:
            raise EvalError(f"Dataset '{dataset_name}' not found.")

        # 4. Verify dataset integrity (warn only, FR-EVL-007)
        try:
            integrity = verify_dataset_integrity(root, dataset_name)
            if not integrity.is_valid:
                sys.stderr.write(
                    f"Warning: dataset '{dataset_name}' integrity check failed "
                    f"({len(integrity.mismatches)} mismatches, "
                    f"{len(integrity.missing)} missing, "
                    f"{len(integrity.extra)} extra). "
                    f"Proceeding with evaluation.\n"
                )
        except Exception as exc:
            sys.stderr.write(f"Warning: could not verify dataset integrity: {exc}\n")

        # 5. Warn if split != 'eval' (FR-EVL-009)
        if ds.split is not None and ds.split != "eval":
            sys.stderr.write(
                f"Warning: dataset '{dataset_name}' has split='{ds.split}' (expected 'eval').\n"
            )

        # 6. Warn if incompatible version (FR-EVL-008)
        compat_versions = get_dataset_compat(conn, dataset_name)
        if compat_versions and problem_version not in compat_versions:
            sys.stderr.write(
                f"Warning: dataset '{dataset_name}' is not marked compatible "
                f"with problem version '{problem_version}'.\n"
            )

        # 7. Check for existing eval results — re-eval handling (S5-06)
        #    The CLI layer is responsible for user confirmation before calling
        #    this function. If force=False and results exist, raise an error.
        existing = get_eval_metadata(conn, solution.id, dataset_name)
        if existing is not None:
            if not force:
                raise EvalError(
                    f"Evaluation already exists for solution '{solution.id}' "
                    f"on dataset '{dataset_name}'. Use --force to re-evaluate."
                )
            delete_eval(conn, existing.eval_id)

        # 8. Resolve program path
        program_path = (
            root
            / REVOLVER_DIR
            / RUNS_DIR
            / solution.run_id
            / "programs"
            / f"rank-{solution.rank}.py"
        )
        if not program_path.exists():
            raise EvalError(f"Program file not found: {program_path}")

        # 9. Resolve evaluator path from problem version snapshot (FR-EVL-003)
        evaluator_path = root / REVOLVER_DIR / PROBLEM_DIR / problem_version / "evaluator.py"
        if not evaluator_path.exists():
            raise EvalError(f"Evaluator not found: {evaluator_path}")

        # 10. Detect evaluator mode
        evaluator_mode = _detect_evaluator_mode(evaluator_path)

        # 11. Resolve dataset path and enumerate instances
        dataset_path = resolve_dataset_path(root, dataset_name)
        instances = sorted(p for p in dataset_path.iterdir() if not p.name.startswith("."))
        if not instances:
            raise EvalError(f"No instances found in dataset '{dataset_name}' at {dataset_path}.")

        # 12. Generate eval ID and insert metadata (with collision-counter)
        results: list[InstanceResult] = []
        total = len(instances)
        now = datetime.now(UTC)

        eval_id: str = ""
        for attempt in range(100):
            candidate = generate_eval_id(suffix=attempt if attempt > 0 else None)
            try:
                insert_eval_metadata(
                    conn,
                    eval_id=candidate,
                    solution_id=solution.id,
                    dataset_name=dataset_name,
                    instance_count=total,
                    instances_solved=0,
                    eval_time_s=None,
                    user_aggregates=None,
                    evaluated_at=now,
                )
                eval_id = candidate
                break
            except sqlite3.IntegrityError:
                # ID collision (same second); try next suffix
                continue
        else:
            raise EvalError("Failed to generate a unique eval ID after 100 attempts.")

        # 14. Evaluation loop
        eval_start = time.monotonic()

        for idx, inst_path in enumerate(instances):
            instance_id = inst_path.name

            # Call evaluator via evaluator_runner
            test_result = run_instance(
                evaluator_path=evaluator_path,
                program_path=program_path,
                instance_path=inst_path,
                timeout_s=float(timeout_s),
            )

            # Map InstanceTestResult to InstanceResult
            status: Literal["solved", "failed", "timeout"]
            if test_result.status == "pass":
                status = "solved"
                metrics = test_result.metrics or {}
                error = None
            elif test_result.status == "timeout":
                status = "timeout"
                metrics = {}
                error = test_result.error
            else:
                status = "failed"
                metrics = {}
                error = test_result.error

            inst_result = InstanceResult(
                instance_id=instance_id,
                status=status,
                metrics=metrics,
                error=error,
                compute_time_s=test_result.time_s,
            )
            results.append(inst_result)

            # Store result immediately in SQLite (DD-03)
            if metrics:
                for metric_name, value in metrics.items():
                    insert_eval_instance(
                        conn,
                        eval_id=eval_id,
                        instance_id=instance_id,
                        metric_name=metric_name,
                        value=value,
                        status=status,
                        error_message=error,
                        compute_time_s=test_result.time_s,
                    )
            else:
                # Store a single row for failed/timeout instances
                insert_eval_instance(
                    conn,
                    eval_id=eval_id,
                    instance_id=instance_id,
                    metric_name="_status",
                    value=None,
                    status=status,
                    error_message=error,
                    compute_time_s=test_result.time_s,
                )

            # Report progress
            if on_progress is not None:
                on_progress(idx + 1, total)

        eval_elapsed = time.monotonic() - eval_start

        # 15. Legacy mode: global aggregation call (S5-05, D-006-g)
        user_aggregates: dict[str, float] | None = None
        user_aggregates_json: str | None = None
        if evaluator_mode == "legacy":
            user_aggregates = _run_legacy_global_aggregation(
                evaluator_path=evaluator_path,
                program_path=program_path,
                dataset_dir=dataset_path,
                timeout_s=timeout_s,
            )
            if user_aggregates is not None:
                user_aggregates_json = json.dumps(user_aggregates)

        # 16. Compute aggregates
        aggregates = compute_aggregates(results)

        # 17. Compute time summary
        compute_times = [r.compute_time_s for r in results if r.compute_time_s is not None]
        compute_time_summary: ComputeTimeSummary | None = None
        if compute_times:
            compute_time_summary = ComputeTimeSummary(
                mean_s=statistics.mean(compute_times),
                max_s=max(compute_times),
                total_s=sum(compute_times),
            )

        # 18. Update eval metadata with final counts
        instances_solved = sum(1 for r in results if r.status == "solved")

        update_eval_metadata(
            conn,
            eval_id=eval_id,
            instances_solved=instances_solved,
            eval_time_s=eval_elapsed,
            user_aggregates=user_aggregates_json,
        )

        # 19. Build and return result
        metadata = EvalMetadata(
            eval_id=eval_id,
            solution_id=solution.id,
            dataset_name=dataset_name,
            instance_count=total,
            instances_solved=instances_solved,
            eval_time_s=eval_elapsed,
            evaluated_at=now,
            user_aggregates=user_aggregates,
        )

        return EvalResult(
            metadata=metadata,
            aggregates=aggregates,
            user_aggregates=user_aggregates,
            compute_time=compute_time_summary,
        )

    finally:
        conn.close()


def get_eval_results(
    solution_id_or_alias: str,
    dataset_name: str | None = None,
    per_instance: bool = False,
    project_root: Path | None = None,
) -> EvalResult | EvalDetailResult:
    """Retrieve stored evaluation results.

    If ``per_instance=True``, returns all raw instance data.
    Otherwise, computes aggregates from raw data.

    Args:
        solution_id_or_alias: Solution ID or alias.
        dataset_name: Optional dataset name filter.
        per_instance: If ``True``, return per-instance detail.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        :class:`EvalResult` (aggregates) or :class:`EvalDetailResult` (instances).

    Raises:
        EvalNotFoundError: If no evaluation results are found (D-006-b).
        EvalError: If the solution is not found.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)

    try:
        # Resolve solution
        solution = get_solution(conn, solution_id_or_alias)
        if solution is None:
            raise EvalError(f"Solution '{solution_id_or_alias}' not found.")

        # Query eval metadata
        metadata = get_eval_metadata(conn, solution.id, dataset_name)
        if metadata is None:
            ds_part = f" on dataset '{dataset_name}'" if dataset_name else ""
            raise EvalNotFoundError(
                f"No evaluation found for solution '{solution_id_or_alias}'{ds_part}. "
                f"Run `revolver eval --solution {solution_id_or_alias}"
                f"{f' --dataset {dataset_name}' if dataset_name else ''}` first."
            )

        # Query raw instance results
        raw_instances = get_eval_instances(conn, metadata.eval_id)

        if per_instance:
            return EvalDetailResult(
                metadata=metadata,
                instances=raw_instances,
            )

        # Compute aggregates from raw data
        aggregates = compute_aggregates(raw_instances)

        # Compute time summary
        compute_times = [r.compute_time_s for r in raw_instances if r.compute_time_s is not None]
        compute_time_summary: ComputeTimeSummary | None = None
        if compute_times:
            compute_time_summary = ComputeTimeSummary(
                mean_s=statistics.mean(compute_times),
                max_s=max(compute_times),
                total_s=sum(compute_times),
            )

        return EvalResult(
            metadata=metadata,
            aggregates=aggregates,
            user_aggregates=metadata.user_aggregates,
            compute_time=compute_time_summary,
        )

    finally:
        conn.close()
