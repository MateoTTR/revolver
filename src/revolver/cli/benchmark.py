"""CLI commands for ``revolver benchmark``.

Registers commands on the ``benchmark_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-007 section 11, FR-BEN-001..017.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Annotated

import typer

from revolver.cli import benchmark_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import benchmark as core_benchmark, solution as core_solution
from revolver.infra.output import print_confirmation, render
from revolver.models.benchmark import BenchmarkDetailResult, BenchmarkResult

_DEFAULT_METRIC = "combined_score"

# ── Default callback: run benchmark (DES-007 §11) ─────────────────────────────


@benchmark_app.callback(invoke_without_command=True)
def benchmark_default(
    ctx: typer.Context,
    solutions: Annotated[
        list[str] | None,
        typer.Option("--solutions", help="Solution IDs or aliases (comma-separated ok)."),
    ] = None,
    all_solutions: Annotated[
        bool,
        typer.Option("--all", help="Include all solutions in the project."),
    ] = False,
    dataset: Annotated[
        str | None,
        typer.Option("--dataset", help="Evaluation dataset name."),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Per-instance timeout (seconds)."),
    ] = 300,
    alias: Annotated[
        str | None,
        typer.Option("--alias", help="Optional benchmark alias."),
    ] = None,
) -> None:
    """Run a comparative benchmark of multiple solutions."""
    # If a subcommand was invoked, skip the benchmark logic
    if ctx.invoked_subcommand is not None:
        return

    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Mutual exclusion: --all and --solutions
        if all_solutions and solutions:
            sys.stderr.write("Error: --all and --solutions are mutually exclusive.\n")
            raise typer.Exit(code=1)

        # Resolve --all: list all project solutions
        if all_solutions:
            all_sols = core_solution.list_solutions()
            if not all_sols:
                sys.stderr.write("Error: no solutions found in the project.\n")
                raise typer.Exit(code=1)
            solutions = [str(s.get("alias") or s["id"]) for s in all_sols]

        # Expand comma-separated values (--solutions A,B,C)
        if solutions:
            expanded: list[str] = []
            for s in solutions:
                expanded.extend(part.strip() for part in s.split(",") if part.strip())
            solutions = expanded

        # Validate required options
        if not solutions:
            sys.stderr.write("Error: --solutions or --all is required.\n")
            raise typer.Exit(code=1)
        if not dataset:
            sys.stderr.write("Error: --dataset is required.\n")
            raise typer.Exit(code=1)

        # Progress display for human mode (suppressed in --quiet, NFR-005)
        if not json_mode and not quiet:

            def on_progress(solution_id: str, status: str) -> None:
                sys.stderr.write(f"  [{status}] {solution_id}\n")
        else:
            on_progress = None  # type: ignore[assignment]

        result = core_benchmark.run_benchmark(
            solution_ids_or_aliases=solutions,
            dataset_name=dataset,
            timeout_s=timeout,
            alias=alias,
            on_progress=on_progress,
        )

        # Display results
        if json_mode:
            render(
                result.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            # Summary on stderr
            failed_part = (
                f", {len(result.failed_solutions)} failed" if result.failed_solutions else ""
            )
            sys.stderr.write(
                f"Benchmark complete: {result.benchmark_id} "
                f"({len(result.entries)} solutions evaluated{failed_part})\n"
            )

            if result.failed_solutions:
                sys.stderr.write(
                    f"Warning: evaluation failed for: {', '.join(result.failed_solutions)}\n"
                )

            # Comparative table: one row per solution, key metrics
            if result.entries:
                rows = []
                for entry in result.entries:
                    row: dict[str, object] = {
                        "solution": entry.alias or entry.solution_id,
                        "dataset": result.dataset_name,
                        "instances": f"{entry.instances_solved}/{entry.instances_count}",
                    }
                    if entry.eval_time_s is not None:
                        row["eval_time_s"] = f"{entry.eval_time_s:.1f}"
                    # Show only combined_score (default) to keep table readable
                    if _DEFAULT_METRIC in entry.metrics:
                        agg = entry.metrics[_DEFAULT_METRIC]
                        row[f"{_DEFAULT_METRIC}_mean"] = f"{agg.mean:.4f}"
                    else:
                        # Fallback: show first metric if combined_score absent
                        for metric_name, agg in entry.metrics.items():
                            row[f"{metric_name}_mean"] = f"{agg.mean:.4f}"
                            break
                    rows.append(row)
                render(rows, json_mode=False)

        # Confirmation summary (NFR-006)
        bm_alias = result.alias or result.benchmark_id
        print_confirmation(
            f"Done: Benchmark '{bm_alias}' completed",
            json_mode=json_mode,
            quiet=quiet,
        )


# ── results subcommand (DES-007 §11) ──────────────────────────────────────────


@benchmark_app.command()
def results(
    ctx: typer.Context,
    benchmark_id: Annotated[
        str | None,
        typer.Option("--id", help="Benchmark ID."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest", help="Show most recent benchmark."),
    ] = False,
    metric: Annotated[
        str | None,
        typer.Option(
            "--metric",
            help=(
                "Metric to display (default: combined_score, 'all' for everything). "
                "Tip: use --format csv for wide tables, or pipe to less -S."
            ),
        ),
    ] = None,
    per_instance: Annotated[
        bool,
        typer.Option("--per-instance", help="Per-instance comparison."),
    ] = False,
    sort_by: Annotated[
        str | None,
        typer.Option("--sort-by", help="Sort instances by solution metric."),
    ] = None,
) -> None:
    """Display results of a previous benchmark."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        # Require --id or --latest
        if not benchmark_id and not latest:
            sys.stderr.write("Error: either --id or --latest is required.\n")
            raise typer.Exit(code=1)

        result = core_benchmark.get_benchmark_results(
            benchmark_id=benchmark_id,
            latest=latest,
            per_instance=per_instance,
            metric=metric,
            sort_by=sort_by,
        )

        if json_mode:
            render(
                result.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            if isinstance(result, BenchmarkDetailResult):
                # Per-instance comparison view
                sys.stderr.write(
                    f"Benchmark: {result.benchmark_id}"
                    f"{' (' + result.alias + ')' if result.alias else ''}\n"
                    f"Dataset: {result.dataset_name} | "
                    f"Instances: {result.instance_count} | "
                    f"Solutions: {len(result.solution_ids)}\n"
                )

                # Determine display metric for per-instance view
                # --metric all → show all metrics (comma-separated)
                # --metric <name> → show that metric
                # (no --metric) → default to combined_score
                pi_show_all = metric and metric.lower() == "all"
                pi_metric = None if pi_show_all else (metric or _DEFAULT_METRIC)

                inst_rows = []
                for comp in result.instances:
                    row: dict[str, object] = {"instance_id": comp.instance_id}
                    for sol_label, sol_result in comp.solutions.items():
                        if sol_result.status == "solved" and sol_result.metrics:
                            if pi_metric:
                                val = sol_result.metrics.get(pi_metric)
                                row[sol_label] = f"{val:.4f}" if val is not None else "-"
                            else:
                                # Show all metrics with names
                                parts = [f"{k}={v:.4f}" for k, v in sol_result.metrics.items()]
                                row[sol_label] = ", ".join(parts) if parts else "-"
                        else:
                            row[sol_label] = sol_result.status.upper()
                    inst_rows.append(row)

                if inst_rows:
                    render(inst_rows, json_mode=False)

                # Win summary
                if result.wins:
                    total = result.instance_count
                    win_parts = [f"{sol}: {wins}/{total}" for sol, wins in result.wins.items()]
                    sys.stderr.write(f"\nWins: {', '.join(win_parts)}\n")

            elif isinstance(result, BenchmarkResult):
                # Aggregate view
                sys.stderr.write(
                    f"Benchmark: {result.benchmark_id}"
                    f"{' (' + result.alias + ')' if result.alias else ''}\n"
                    f"Dataset: {result.dataset_name} | "
                    f"Instances: {result.instance_count}\n"
                )

                if result.entries:
                    # Determine which metrics to display:
                    # --metric all → show everything
                    # --metric <name> → show only that metric
                    # (no --metric) → default to combined_score
                    show_all = metric and metric.lower() == "all"
                    effective_metric = None if show_all else (metric or _DEFAULT_METRIC)

                    rows_agg = []
                    for entry in result.entries:
                        row_agg: dict[str, object] = {
                            "solution": entry.alias or entry.solution_id,
                            "instances": f"{entry.instances_solved}/{entry.instances_count}",
                        }
                        if entry.eval_time_s is not None:
                            row_agg["eval_time_s"] = f"{entry.eval_time_s:.1f}"
                        for metric_name, agg in entry.metrics.items():
                            if effective_metric and metric_name != effective_metric:
                                continue
                            row_agg[f"{metric_name}_mean"] = f"{agg.mean:.4f}"
                            row_agg[f"{metric_name}_min"] = f"{agg.min:.4f}"
                            row_agg[f"{metric_name}_max"] = f"{agg.max:.4f}"
                        rows_agg.append(row_agg)
                    render(rows_agg, json_mode=False)

                if result.failed_solutions:
                    sys.stderr.write(f"\nFailed solutions: {', '.join(result.failed_solutions)}\n")


# ── export subcommand (DES-007 §11) ───────────────────────────────────────────


@benchmark_app.command()
def export(
    ctx: typer.Context,
    benchmark_id: Annotated[
        str | None,
        typer.Option("--id", help="Benchmark ID."),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest", help="Export most recent benchmark."),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Export format: csv or json."),
    ] = ...,  # type: ignore[assignment]
    output: Annotated[
        Path,
        typer.Option("--output", help="Output file path."),
    ] = ...,  # type: ignore[assignment]
    per_instance: Annotated[
        bool,
        typer.Option("--per-instance", help="Export per-instance data."),
    ] = False,
) -> None:
    """Export benchmark results to a file."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Require --id or --latest
        if not benchmark_id and not latest:
            sys.stderr.write("Error: either --id or --latest is required.\n")
            raise typer.Exit(code=1)

        written_path = core_benchmark.export_benchmark(
            benchmark_id=benchmark_id,
            latest=latest,
            output_format=output_format,
            output_path=output,
            per_instance=per_instance,
        )

        if json_mode:
            render(
                {"status": "exported", "path": str(written_path)},
                json_mode=True,
            )
        else:
            sys.stderr.write(f"Exported benchmark results to: {written_path}\n")

        # Confirmation summary (NFR-006)
        print_confirmation(
            f"Done: Exported to {written_path}",
            json_mode=json_mode,
            quiet=quiet,
        )


# ── list subcommand (DES-007 §11) ─────────────────────────────────────────────


@benchmark_app.command(name="list")
def list_cmd(
    ctx: typer.Context,
) -> None:
    """List all benchmarks."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        benchmarks = core_benchmark.list_benchmarks()

        if json_mode:
            render(
                [b.model_dump(mode="json") for b in benchmarks],
                json_mode=True,
            )
        else:
            if not benchmarks:
                render({"message": "No benchmarks found."}, json_mode=False)
            else:
                rows = [
                    {
                        "benchmark_id": b.benchmark_id,
                        "alias": b.alias or "",
                        "dataset": b.dataset_name,
                        "solutions": str(b.solution_count),
                        "created_at": str(b.created_at),
                    }
                    for b in benchmarks
                ]
                render(rows, json_mode=False)


# ── delete subcommand (F8 — Sprint 006b) ──────────────────────────────────


@benchmark_app.command("delete")
def delete(
    ctx: typer.Context,
    benchmark_id: Annotated[
        str,
        typer.Argument(help="Benchmark ID to delete."),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete a benchmark and its associated solution references."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Confirmation logic lives in the CLI layer, not in core
        if not force:
            if json_mode:
                from revolver.core.exceptions import ValidationError

                raise ValidationError("Use --force to delete in JSON mode (no interactive prompt)")
            typer.confirm(f"Delete benchmark '{benchmark_id}'?", abort=True)

        deleted_id = core_benchmark.delete_benchmark(benchmark_id)

        if json_mode:
            render(
                {"benchmark_id": deleted_id, "status": "deleted"},
                json_mode=True,
            )
        else:
            render(
                {"benchmark_id": deleted_id, "status": "deleted"},
                json_mode=False,
            )
            print_confirmation(
                f"Done: Benchmark '{deleted_id}' deleted",
                json_mode=json_mode,
                quiet=quiet,
            )
