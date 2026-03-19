"""Core benchmark logic: orchestrate, compare, export, and list benchmarks.

Implements the benchmark domain layer (DES-007): validate solutions and datasets,
reuse or trigger evaluations, compute aggregates, build comparison matrices,
and export results to CSV/JSON.

Traceable to: DES-007, FR-BEN-001..017.
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from revolver.core.dataset import verify_dataset_integrity
from revolver.core.eval import compute_aggregates, evaluate_solution
from revolver.core.exceptions import (
    BenchmarkError,
    BenchmarkNotFoundError,
    EvalError,
    ExportError,
    RevolverError,
)
from revolver.infra.db import (
    delete_benchmark as db_delete_benchmark,
)
from revolver.infra.db import (
    get_benchmark,
    get_benchmark_solutions,
    get_dataset,
    get_eval_instances,
    get_eval_metadata,
    get_latest_benchmark,
    get_project_db,
    get_run,
    get_solution,
    insert_benchmark,
    insert_benchmark_solutions,
    list_benchmarks_with_count,
)
from revolver.infra.store import REVOLVER_DIR, find_project_root
from revolver.infra.store import ProjectNotFoundError as StoreProjectNotFoundError
from revolver.models.benchmark import (
    BenchmarkDetailResult,
    BenchmarkEntry,
    BenchmarkResult,
    BenchmarkSummary,
    EvalStatus,
    InstanceComparison,
    InstanceSolutionResult,
    SolutionLineage,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BenchmarkError",
    "BenchmarkNotFoundError",
    "ExportError",
    "delete_benchmark",
    "export_benchmark",
    "generate_benchmark_id",
    "get_benchmark_results",
    "list_benchmarks",
    "run_benchmark",
]

# ── ID generation ─────────────────────────────────────────────────────────────


def generate_benchmark_id(suffix: int | None = None) -> str:
    """Generate a benchmark ID in the format ``bench-YYYYMMDD-HHMMSS[-N]``.

    If ``suffix`` is provided (a positive integer), it is appended as
    ``-N`` to disambiguate same-second collisions.

    Args:
        suffix: Optional integer suffix for collision avoidance.

    Returns:
        A benchmark ID string.
    """
    now = datetime.now(UTC)
    base = now.strftime("bench-%Y%m%d-%H%M%S")
    if suffix is not None:
        return f"{base}-{suffix}"
    return base


# ── Project root helper ───────────────────────────────────────────────────────


def _resolve_project_root(project_root: Path | None = None) -> Path:
    """Resolve and return the project root directory."""
    try:
        return find_project_root(project_root or Path.cwd())
    except StoreProjectNotFoundError as exc:
        raise RevolverError(str(exc)) from exc


# ── Internal helpers ─────────────────────────────────────────────────────────


def _ensure_evaluated(
    solution_id: str,
    dataset_name: str,
    timeout_s: int,
    project_root: Path,
) -> EvalStatus:
    """Check for existing eval results; trigger evaluation if missing.

    Reuses existing evaluation results when available (FR-BEN-002).
    Triggers ``evaluate_solution(force=True)`` when no results exist (FR-BEN-003).

    Args:
        solution_id: Solution ID to check.
        dataset_name: Evaluation dataset name.
        timeout_s: Per-instance timeout for triggered evaluations.
        project_root: Resolved project root directory.

    Returns:
        An :class:`EvalStatus` with ``status="reused"``, ``"evaluated"``, or
        ``"failed"`` and the corresponding ``eval_id`` or ``error``.
    """
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        existing = get_eval_metadata(conn, solution_id, dataset_name)
    finally:
        conn.close()

    if existing is not None:
        return EvalStatus(status="reused", eval_id=existing.eval_id)

    try:
        result = evaluate_solution(
            solution_id_or_alias=solution_id,
            dataset_name=dataset_name,
            timeout_s=timeout_s,
            force=True,
            project_root=project_root,
        )
        return EvalStatus(status="evaluated", eval_id=result.metadata.eval_id)
    except EvalError as exc:
        return EvalStatus(status="failed", error=str(exc))


def _build_comparison_matrix(
    benchmark_id: str,
    dataset_name: str,
    metric_filter: str | None,
    sort_by: str | None,
    project_root: Path,
) -> tuple[list[InstanceComparison], dict[str, int]]:
    """Build per-instance comparison matrix and win counts.

    Implements DES-007 §5 / §9.5. For each instance, collects the metric values
    from each solution's eval results. Identifies the best solution per instance
    (FR-BEN-015). Ties are counted for all tied solutions.

    Args:
        benchmark_id: Benchmark ID to build the matrix for.
        dataset_name: Dataset name for eval lookup.
        metric_filter: Optional metric name to filter comparison to. If
            ``None``, all metrics are included and wins are counted on
            ``sort_by`` (default ``"combined_score"``).
        sort_by: Metric used for win counting. Defaults to ``"combined_score"``.
        project_root: Resolved project root directory.

    Returns:
        A tuple of (instances, wins) where ``instances`` is a list of
        :class:`InstanceComparison` and ``wins`` maps alias_or_id to win count.
    """
    win_metric = sort_by or "combined_score"

    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        sol_rows = get_benchmark_solutions(conn, benchmark_id, dataset_name)
        if not sol_rows:
            return [], {}

        # Build solution label → eval_id mapping
        sol_label_to_eval: dict[str, str] = {}
        for row in sol_rows:
            label = str(row["alias"]) if row.get("alias") else str(row["solution_id"])
            sol_label_to_eval[label] = str(row["eval_id"])

        # Load per-instance data for every solution
        sol_label_to_instances: dict[str, dict[str, InstanceSolutionResult]] = {}
        for label, eval_id in sol_label_to_eval.items():
            raw = get_eval_instances(conn, eval_id)
            imap: dict[str, InstanceSolutionResult] = {}
            for inst in raw:
                metrics = inst.metrics
                if metric_filter is not None:
                    metrics = {k: v for k, v in metrics.items() if k == metric_filter}
                imap[inst.instance_id] = InstanceSolutionResult(
                    status=inst.status,
                    metrics=metrics,
                    compute_time_s=inst.compute_time_s,
                )
            sol_label_to_instances[label] = imap
    finally:
        conn.close()

    # Collect all instance IDs across all solutions
    all_instance_ids: set[str] = set()
    for imap in sol_label_to_instances.values():
        all_instance_ids.update(imap.keys())

    # Build comparison matrix and count wins
    wins: dict[str, int] = {label: 0 for label in sol_label_to_eval}
    instances: list[InstanceComparison] = []

    for iid in sorted(all_instance_ids):
        sol_results: dict[str, InstanceSolutionResult] = {}
        for label, imap in sol_label_to_instances.items():
            if iid in imap:
                sol_results[label] = imap[iid]
            else:
                # Instance not found for this solution — treat as failed
                sol_results[label] = InstanceSolutionResult(status="failed", metrics={})

        # Identify best per instance on win_metric (FR-BEN-015)
        best_value: float | None = None
        for _label, result in sol_results.items():
            if result.status == "solved" and win_metric in result.metrics:
                val = result.metrics[win_metric]
                if best_value is None or val > best_value:
                    best_value = val

        if best_value is not None:
            for label, result in sol_results.items():
                if result.status == "solved" and result.metrics.get(win_metric) == best_value:
                    wins[label] = wins.get(label, 0) + 1

        instances.append(InstanceComparison(instance_id=iid, solutions=sol_results))

    return instances, wins


# ── Public functions ──────────────────────────────────────────────────────────


def run_benchmark(
    solution_ids_or_aliases: list[str],
    dataset_name: str,
    timeout_s: int = 300,
    alias: str | None = None,
    on_progress: Callable[[str, str], None] | None = None,
    project_root: Path | None = None,
) -> BenchmarkResult:
    """Run a comparative benchmark of multiple solutions.

    For each solution:

    1. Check for existing eval results (reuse if available — FR-BEN-002)
    2. If missing, trigger evaluation with ``force=True`` (FR-BEN-003)
    3. On eval failure, mark as failed and continue (DES-007 DD-07)

    Computes aggregates per solution from raw per-instance data.
    Stores benchmark metadata and solution references in SQLite.

    Args:
        solution_ids_or_aliases: Solutions to compare (at least 1).
        dataset_name: Registered evaluation dataset.
        timeout_s: Per-instance timeout for triggered evaluations.
        alias: Optional benchmark alias.
        on_progress: Callback ``(solution_id, status)`` for CLI progress display.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A :class:`BenchmarkResult` with all successfully evaluated solutions.

    Raises:
        BenchmarkError: If no solutions provided, or dataset not found, or
            evaluation fails for ALL solutions (exit code 4).
    """
    if not solution_ids_or_aliases:
        raise BenchmarkError("At least one solution must be provided.")

    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"

    # 1. Validate all solutions exist
    conn = get_project_db(db_path)
    try:
        resolved_ids: list[str] = []
        for id_or_alias in solution_ids_or_aliases:
            sol = get_solution(conn, id_or_alias)
            if sol is None:
                raise BenchmarkError(f"Solution '{id_or_alias}' not found.")
            resolved_ids.append(sol.id)

        # 2. Load dataset registration
        ds = get_dataset(conn, dataset_name)
        if ds is None:
            raise BenchmarkError(f"Dataset '{dataset_name}' not found.")

        # Warn if split != 'eval' (FR-BEN-001)
        if ds.split is not None and ds.split != "eval":
            logger.warning(
                "Dataset '%s' has split='%s' (expected 'eval').", dataset_name, ds.split
            )
    finally:
        conn.close()

    # 3. Quick integrity check
    try:
        integrity = verify_dataset_integrity(root, dataset_name)
        if not integrity.is_valid:
            logger.warning(
                "Dataset '%s' integrity check failed (%d mismatches, %d missing, %d extra). "
                "Proceeding with benchmark.",
                dataset_name,
                len(integrity.mismatches),
                len(integrity.missing),
                len(integrity.extra),
            )
    except Exception as exc:
        logger.warning("Could not verify dataset integrity: %s", exc)

    # 4. Per-solution: ensure evaluated (reuse or trigger)
    failed_solutions: list[str] = []
    successful_ids: list[str] = []

    for solution_id in resolved_ids:
        eval_status = _ensure_evaluated(solution_id, dataset_name, timeout_s, root)

        status_label = eval_status.status
        if on_progress is not None:
            on_progress(solution_id, status_label)

        if eval_status.status == "failed":
            logger.warning(
                "Evaluation failed for solution '%s': %s", solution_id, eval_status.error
            )
            failed_solutions.append(solution_id)
        else:
            successful_ids.append(solution_id)

    # 5. Abort if all solutions failed
    if not successful_ids:
        raise BenchmarkError("Evaluation failed for all solutions. Benchmark aborted.")

    # 6. Load raw instances, compute aggregates, build lineage per solution
    entries: list[BenchmarkEntry] = []
    instance_count: int = 0
    seen_instance_counts: list[int] = []

    conn2 = get_project_db(db_path)
    try:
        for solution_id in successful_ids:
            eval_meta = get_eval_metadata(conn2, solution_id, dataset_name)
            if eval_meta is None:
                # Should not happen after _ensure_evaluated succeeded
                failed_solutions.append(solution_id)
                continue

            seen_instance_counts.append(eval_meta.instance_count)
            if instance_count == 0:
                instance_count = eval_meta.instance_count

            raw_instances = get_eval_instances(conn2, eval_meta.eval_id)
            aggregates = compute_aggregates(raw_instances)

            sol = get_solution(conn2, solution_id)
            run = get_run(conn2, sol.run_id) if sol is not None else None

            if sol is None or run is None:
                failed_solutions.append(solution_id)
                continue

            lineage = SolutionLineage(
                problem_version=str(run["problem_version"]),
                llm=str(run["llm"]),
                llm_model=str(run["llm_model"]),
                train_dataset=str(run["dataset"]),
                iterations=int(str(run["iterations"])),
                generation_time_s=(
                    float(str(run["generation_time_s"]))
                    if run.get("generation_time_s") is not None
                    else None
                ),
            )

            user_agg = eval_meta.user_aggregates

            entries.append(
                BenchmarkEntry(
                    solution_id=solution_id,
                    alias=sol.alias,
                    run_id=sol.run_id,
                    lineage=lineage,
                    metrics=aggregates,
                    user_aggregates=user_agg,
                    eval_time_s=eval_meta.eval_time_s,
                    instances_count=eval_meta.instance_count,
                    instances_solved=eval_meta.instances_solved,
                )
            )
    finally:
        conn2.close()

    # Abort if all succeeded evals failed at lineage/aggregate stage
    if not entries:
        raise BenchmarkError("Failed to compute results for all solutions. Benchmark aborted.")

    # Warn if solutions were evaluated on datasets of different sizes (should not happen
    # for a well-formed benchmark, but guard against inconsistency).
    if len(set(seen_instance_counts)) > 1:
        logger.warning(
            "Instance count mismatch across solutions: %s. "
            "All solutions in a benchmark should share the same dataset. "
            "Using max instance count.",
            seen_instance_counts,
        )
        instance_count = max(seen_instance_counts)

    # 7. Generate benchmark ID and store (with collision-counter for same-second runs)
    now = datetime.now(UTC)
    benchmark_id: str = ""
    conn3 = get_project_db(db_path)
    try:
        for attempt in range(100):
            candidate = generate_benchmark_id(suffix=attempt if attempt > 0 else None)
            try:
                insert_benchmark(
                    conn3,
                    benchmark_id=candidate,
                    alias=alias,
                    dataset_name=dataset_name,
                    created_at=now,
                )
                benchmark_id = candidate
                break
            except sqlite3.IntegrityError:
                # ID collision (same second); try next suffix
                continue
        else:
            raise BenchmarkError("Failed to generate a unique benchmark ID after 100 attempts.")
        insert_benchmark_solutions(
            conn3,
            benchmark_id=benchmark_id,
            solution_ids=[entry.solution_id for entry in entries],
        )
    finally:
        conn3.close()

    return BenchmarkResult(
        benchmark_id=benchmark_id,
        alias=alias,
        dataset_name=dataset_name,
        instance_count=instance_count,
        entries=entries,
        failed_solutions=failed_solutions,
        created_at=now,
    )


def get_benchmark_results(
    benchmark_id: str | None = None,
    latest: bool = False,
    per_instance: bool = False,
    metric: str | None = None,
    sort_by: str | None = None,
    project_root: Path | None = None,
) -> BenchmarkResult | BenchmarkDetailResult:
    """Retrieve stored benchmark results.

    If ``per_instance=True``, returns a per-instance comparison matrix with
    best-per-instance identification (FR-BEN-014/015). Otherwise, computes
    aggregates from raw eval data.

    Args:
        benchmark_id: Explicit benchmark ID to look up.
        latest: If ``True``, retrieve the most recent benchmark.
        per_instance: If ``True``, return per-instance comparison matrix.
        metric: Optional metric filter (only relevant for per-instance).
        sort_by: Metric used for win counting (default: ``"combined_score"``).
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A :class:`BenchmarkResult` (aggregates) or :class:`BenchmarkDetailResult`
        (per-instance).

    Raises:
        BenchmarkNotFoundError: If no benchmark matches the criteria.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"

    conn = get_project_db(db_path)
    try:
        # 1. Resolve benchmark
        bench_row: dict[str, object] | None = None
        if benchmark_id is not None:
            bench_row = get_benchmark(conn, benchmark_id)
        elif latest:
            bench_row = get_latest_benchmark(conn)

        if bench_row is None:
            if benchmark_id:
                raise BenchmarkNotFoundError(f"Benchmark '{benchmark_id}' not found.")
            raise BenchmarkNotFoundError("No benchmark found. Run `revolver benchmark` first.")

        bench_id = str(bench_row["id"])
        bench_alias = bench_row.get("alias")
        bench_alias_str: str | None = str(bench_alias) if bench_alias is not None else None
        ds_name = str(bench_row["dataset_name"])
        created_at = datetime.fromisoformat(str(bench_row["created_at"]))

        # 2. Load benchmark solutions with eval metadata
        sol_rows = get_benchmark_solutions(conn, bench_id, ds_name)
    finally:
        conn.close()

    if per_instance:
        instances, wins = _build_comparison_matrix(bench_id, ds_name, metric, sort_by, root)
        solution_ids = [
            str(r["alias"]) if r.get("alias") else str(r["solution_id"]) for r in sol_rows
        ]
        return BenchmarkDetailResult(
            benchmark_id=bench_id,
            alias=bench_alias_str,
            dataset_name=ds_name,
            instance_count=len(instances),
            solution_ids=solution_ids,
            instances=instances,
            wins=wins,
            metric=sort_by or "combined_score",
        )

    # Aggregate mode
    entries: list[BenchmarkEntry] = []
    instance_count: int = 0
    seen_instance_counts: list[int] = []

    conn2 = get_project_db(db_path)
    try:
        for row in sol_rows:
            sol_id = str(row["solution_id"])
            sol_alias: str | None = str(row["alias"]) if row.get("alias") else None
            run_id = str(row["run_id"])
            eval_id = str(row["eval_id"])
            inst_count = int(str(row["instance_count"]))
            inst_solved = int(str(row["instances_solved"]))
            eval_time: float | None = (
                float(str(row["eval_time_s"])) if row.get("eval_time_s") is not None else None
            )
            # user_aggregates is stored as a JSON string in the DB row (from JOIN);
            # decode it here (it is not a parsed dict like EvalMetadata.user_aggregates).
            user_agg_raw = row.get("user_aggregates")
            user_agg: dict[str, float] | None = None
            if user_agg_raw is not None:
                try:
                    user_agg = json.loads(str(user_agg_raw))
                except (json.JSONDecodeError, TypeError):
                    user_agg = None

            seen_instance_counts.append(inst_count)
            if instance_count == 0:
                instance_count = inst_count

            # Compute aggregates from raw instances
            raw_instances = get_eval_instances(conn2, eval_id)
            aggregates = compute_aggregates(raw_instances)

            # Build lineage from run
            run = get_run(conn2, run_id)
            if run is None:
                continue

            lineage = SolutionLineage(
                problem_version=str(run["problem_version"]),
                llm=str(run["llm"]),
                llm_model=str(run["llm_model"]),
                train_dataset=str(run["dataset"]),
                iterations=int(str(run["iterations"])),
                generation_time_s=(
                    float(str(run["generation_time_s"]))
                    if run.get("generation_time_s") is not None
                    else None
                ),
            )

            entries.append(
                BenchmarkEntry(
                    solution_id=sol_id,
                    alias=sol_alias,
                    run_id=run_id,
                    lineage=lineage,
                    metrics=aggregates,
                    user_aggregates=user_agg,
                    eval_time_s=eval_time,
                    instances_count=inst_count,
                    instances_solved=inst_solved,
                )
            )
    finally:
        conn2.close()

    # Warn if solutions were evaluated on datasets of different sizes.
    if len(set(seen_instance_counts)) > 1:
        logger.warning(
            "Instance count mismatch across solutions: %s. Using max instance count.",
            seen_instance_counts,
        )
        instance_count = max(seen_instance_counts)

    return BenchmarkResult(
        benchmark_id=bench_id,
        alias=bench_alias_str,
        dataset_name=ds_name,
        instance_count=instance_count,
        entries=entries,
        created_at=created_at,
    )


def export_benchmark(
    benchmark_id: str | None = None,
    latest: bool = False,
    output_format: str = "csv",
    output_path: Path | None = None,
    per_instance: bool = False,
    project_root: Path | None = None,
) -> Path:
    """Export benchmark results to CSV or JSON.

    Aggregate export: one row/entry per (solution, metric).
    Per-instance export: one row/entry per (solution, instance, metric).

    No secrets in exports (FR-BEN-013): lineage uses symbolic names only —
    never file paths or env var names.

    Args:
        benchmark_id: Explicit benchmark ID to export.
        latest: If ``True``, export the most recent benchmark.
        output_format: Export format — ``"csv"`` or ``"json"``.
        output_path: Destination file path. Defaults to
            ``benchmark-results.csv`` in the current working directory when
            ``None``.
        per_instance: If ``True``, export raw per-instance data (FR-BEN-016).
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        Path to the written file.

    Raises:
        BenchmarkNotFoundError: If no benchmark matches.
        ExportError: If output path not writable or invalid format.
    """
    if output_format not in ("csv", "json"):
        raise ExportError(f"Invalid export format '{output_format}'. Must be 'csv' or 'json'.")

    if output_path is None:
        output_path = Path("benchmark-results.csv")

    result = get_benchmark_results(
        benchmark_id=benchmark_id,
        latest=latest,
        per_instance=per_instance,
        project_root=project_root,
    )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(f"Cannot create output directory: {exc}") from exc

    try:
        if output_format == "csv":
            _write_csv(result, output_path, per_instance=per_instance)
        else:
            _write_json(result, output_path, per_instance=per_instance)
    except OSError as exc:
        raise ExportError(f"Cannot write output file: {exc}") from exc

    return output_path


def list_benchmarks(
    project_root: Path | None = None,
) -> list[BenchmarkSummary]:
    """List all benchmarks with date, dataset, and solution count.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A list of :class:`BenchmarkSummary` objects ordered by creation time
        (most recent first).
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        rows = list_benchmarks_with_count(conn)
    finally:
        conn.close()

    summaries: list[BenchmarkSummary] = []
    for row in rows:
        alias_raw = row.get("alias")
        summaries.append(
            BenchmarkSummary(
                benchmark_id=str(row["id"]),
                alias=str(alias_raw) if alias_raw is not None else None,
                dataset_name=str(row["dataset_name"]),
                solution_count=int(str(row["solution_count"])),
                created_at=datetime.fromisoformat(str(row["created_at"])),
            )
        )
    return summaries


def delete_benchmark(
    benchmark_id: str,
    *,
    project_root: Path | None = None,
) -> str:
    """Delete a benchmark and its associated solution references.

    This is a pure domain function — confirmation prompts belong in the CLI
    layer.  It resolves the benchmark, deletes the record, and returns the
    deleted ID.

    Args:
        benchmark_id: Benchmark ID to delete.
        project_root: Project root directory (auto-detected if None).

    Returns:
        The benchmark ID that was deleted.

    Raises:
        BenchmarkNotFoundError: If the benchmark is not found.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        deleted = db_delete_benchmark(conn, benchmark_id)
        if not deleted:
            raise BenchmarkNotFoundError(f"Benchmark '{benchmark_id}' not found.")
        return benchmark_id
    finally:
        conn.close()


# ── CSV / JSON export helpers ─────────────────────────────────────────────────


def _write_csv(
    result: BenchmarkResult | BenchmarkDetailResult,
    output_path: Path,
    per_instance: bool,
) -> None:
    """Write benchmark results to a CSV file.

    Aggregate CSV: one row per (solution, metric) — ConOps §8.1.
    Per-instance CSV: one row per (solution, instance, metric) — ConOps §8.1 variant.

    Args:
        result: The benchmark result to export (aggregate or per-instance).
        output_path: Destination file path.
        per_instance: If ``True``, write per-instance rows.
    """
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        if per_instance:
            _write_csv_per_instance(result, fh)
        else:
            _write_csv_aggregate(result, fh)


def _write_csv_aggregate(
    result: BenchmarkResult | BenchmarkDetailResult,
    fh: object,
) -> None:
    """Write aggregate CSV rows: one row per (solution, metric)."""
    fieldnames = [
        "benchmark_id",
        "solution_id",
        "solution_alias",
        "run_id",
        "problem_version",
        "llm",
        "llm_model",
        "train_dataset",
        "eval_dataset",
        "metric_name",
        "mean",
        "min",
        "max",
        "p10",
        "p50",
        "p90",
        "std",
        "gen_time_s",
        "eval_time_s",
        "instances_count",
        "instances_solved",
    ]
    writer = csv.DictWriter(fh, fieldnames=fieldnames)  # type: ignore[arg-type]
    writer.writeheader()

    if not isinstance(result, BenchmarkResult):
        raise ExportError(
            "Aggregate CSV export requires BenchmarkResult, got BenchmarkDetailResult. "
            "Pass per_instance=True to export per-instance data."
        )

    for entry in result.entries:
        base: dict[str, object] = {
            "benchmark_id": result.benchmark_id,
            "solution_id": entry.solution_id,
            "solution_alias": entry.alias or "",
            "run_id": entry.run_id,
            # problem_version: symbolic tag only — no file paths (FR-BEN-013)
            "problem_version": entry.lineage.problem_version,
            "llm": entry.lineage.llm,
            "llm_model": entry.lineage.llm_model,
            "train_dataset": entry.lineage.train_dataset,
            "eval_dataset": result.dataset_name,
            "gen_time_s": (
                entry.lineage.generation_time_s
                if entry.lineage.generation_time_s is not None
                else ""
            ),
            "eval_time_s": entry.eval_time_s if entry.eval_time_s is not None else "",
            "instances_count": entry.instances_count,
            "instances_solved": entry.instances_solved,
        }
        for metric_name, agg in entry.metrics.items():
            row = dict(base)
            row["metric_name"] = metric_name
            row["mean"] = agg.mean
            row["min"] = agg.min
            row["max"] = agg.max
            row["p10"] = agg.p10
            row["p50"] = agg.p50
            row["p90"] = agg.p90
            row["std"] = agg.std
            writer.writerow(row)

        # Include user aggregate rows if present (prefixed with [user])
        if entry.user_aggregates:
            for ua_name, ua_val in entry.user_aggregates.items():
                row = dict(base)
                row["metric_name"] = f"[user] {ua_name}"
                row["mean"] = ua_val
                row["min"] = ""
                row["max"] = ""
                row["p10"] = ""
                row["p50"] = ""
                row["p90"] = ""
                row["std"] = ""
                writer.writerow(row)


def _write_csv_per_instance(
    result: BenchmarkResult | BenchmarkDetailResult,
    fh: object,
) -> None:
    """Write per-instance CSV rows: one row per (solution, instance, metric)."""
    fieldnames = [
        "benchmark_id",
        "solution_id",
        "solution_alias",
        "instance_id",
        "metric_name",
        "value",
        "status",
        "compute_time_s",
    ]
    writer = csv.DictWriter(fh, fieldnames=fieldnames)  # type: ignore[arg-type]
    writer.writeheader()

    if not isinstance(result, BenchmarkDetailResult):
        raise ExportError(
            "Per-instance CSV export requires BenchmarkDetailResult, got BenchmarkResult. "
            "Pass per_instance=False to export aggregate data."
        )

    for comp in result.instances:
        for sol_label, sol_result in comp.solutions.items():
            if sol_result.status != "solved" or not sol_result.metrics:
                # Write one row for failed/timeout (no metric value)
                writer.writerow(
                    {
                        "benchmark_id": result.benchmark_id,
                        "solution_id": sol_label,
                        "solution_alias": sol_label,
                        "instance_id": comp.instance_id,
                        "metric_name": "",
                        "value": "",
                        "status": sol_result.status,
                        "compute_time_s": (
                            sol_result.compute_time_s
                            if sol_result.compute_time_s is not None
                            else ""
                        ),
                    }
                )
            else:
                for metric_name, value in sol_result.metrics.items():
                    writer.writerow(
                        {
                            "benchmark_id": result.benchmark_id,
                            "solution_id": sol_label,
                            "solution_alias": sol_label,
                            "instance_id": comp.instance_id,
                            "metric_name": metric_name,
                            "value": value,
                            "status": sol_result.status,
                            "compute_time_s": (
                                sol_result.compute_time_s
                                if sol_result.compute_time_s is not None
                                else ""
                            ),
                        }
                    )


def _write_json(
    result: BenchmarkResult | BenchmarkDetailResult,
    output_path: Path,
    per_instance: bool,
) -> None:
    """Write benchmark results to a JSON file.

    Aggregate JSON: nested structure matching ConOps §8.2.
    Per-instance JSON: same top-level with instances array.

    No secrets: only symbolic names used in lineage (FR-BEN-013).

    Args:
        result: The benchmark result to export.
        output_path: Destination file path.
        per_instance: If ``True``, write per-instance structure.
    """
    if per_instance and isinstance(result, BenchmarkDetailResult):
        payload = _build_json_per_instance(result)
    elif isinstance(result, BenchmarkResult):
        payload = _build_json_aggregate(result)
    else:
        payload = {}

    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def _build_json_aggregate(result: BenchmarkResult) -> dict[str, object]:
    """Build aggregate JSON structure matching ConOps §8.2."""
    results_list = []
    for entry in result.entries:
        metrics_dict: dict[str, dict[str, float]] = {}
        for metric_name, agg in entry.metrics.items():
            metrics_dict[metric_name] = {
                "mean": agg.mean,
                "min": agg.min,
                "max": agg.max,
                "p10": agg.p10,
                "p50": agg.p50,
                "p90": agg.p90,
                "std": agg.std,
                "count": agg.count,
            }

        results_list.append(
            {
                "solution_id": entry.solution_id,
                "alias": entry.alias,
                "run_id": entry.run_id,
                # Lineage: symbolic names only — no file paths (FR-BEN-013)
                "lineage": {
                    "problem_version": entry.lineage.problem_version,
                    "llm": entry.lineage.llm,
                    "llm_model": entry.lineage.llm_model,
                    "train_dataset": entry.lineage.train_dataset,
                    "iterations": entry.lineage.iterations,
                    "generation_time_s": entry.lineage.generation_time_s,
                },
                "metrics": metrics_dict,
                "user_aggregates": entry.user_aggregates,
                "eval_time_s": entry.eval_time_s,
                "instances_count": entry.instances_count,
                "instances_solved": entry.instances_solved,
            }
        )

    return {
        "benchmark_id": result.benchmark_id,
        "alias": result.alias,
        "eval_dataset": result.dataset_name,
        "instance_count": result.instance_count,
        "created_at": result.created_at.isoformat(),
        "results": results_list,
    }


def _build_json_per_instance(result: BenchmarkDetailResult) -> dict[str, object]:
    """Build per-instance JSON structure."""
    instances_list = []
    for comp in result.instances:
        solutions_dict: dict[str, dict[str, object]] = {}
        for sol_label, sol_result in comp.solutions.items():
            solutions_dict[sol_label] = {
                "status": sol_result.status,
                "metrics": sol_result.metrics,
                "compute_time_s": sol_result.compute_time_s,
            }
        instances_list.append(
            {
                "instance_id": comp.instance_id,
                "solutions": solutions_dict,
            }
        )

    return {
        "benchmark_id": result.benchmark_id,
        "alias": result.alias,
        "eval_dataset": result.dataset_name,
        "instance_count": result.instance_count,
        "solution_ids": result.solution_ids,
        "wins": result.wins,
        "metric": result.metric,
        "instances": instances_list,
    }
