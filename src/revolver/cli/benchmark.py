"""CLI commands for ``revolver benchmark``.

Registers commands on the ``benchmark_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-007 section 11, FR-BEN-001..017.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from revolver.cli import benchmark_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import benchmark as core_benchmark
from revolver.infra.output import render
from revolver.models.benchmark import BenchmarkDetailResult, BenchmarkResult

# ── Default callback: run benchmark (DES-007 §11) ─────────────────────────────


@benchmark_app.callback(invoke_without_command=True)
def benchmark_default(
    ctx: typer.Context,
    solutions: Annotated[
        list[str] | None,
        typer.Option("--solutions", help="Solution IDs or aliases to compare."),
    ] = None,
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

        # Validate required options
        if not solutions:
            sys.stderr.write("Error: --solutions is required.\n")
            raise typer.Exit(code=1)
        if not dataset:
            sys.stderr.write("Error: --dataset is required.\n")
            raise typer.Exit(code=1)

        # Progress display for human mode
        if not json_mode:

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
                    for metric_name, agg in entry.metrics.items():
                        row[f"{metric_name}_mean"] = f"{agg.mean:.4f}"
                    rows.append(row)
                render(rows, json_mode=False)


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
        typer.Option("--metric", help="Filter to single metric."),
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

                inst_rows = []
                for comp in result.instances:
                    row: dict[str, object] = {"instance_id": comp.instance_id}
                    for sol_label, sol_result in comp.solutions.items():
                        if sol_result.status == "solved" and sol_result.metrics:
                            if metric:
                                val = sol_result.metrics.get(metric)
                                row[sol_label] = f"{val:.4f}" if val is not None else "-"
                            else:
                                # Use first metric available
                                first_metric_val = next(iter(sol_result.metrics.values()), None)
                                row[sol_label] = (
                                    f"{first_metric_val:.4f}"
                                    if first_metric_val is not None
                                    else "-"
                                )
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
                    rows_agg = []
                    for entry in result.entries:
                        row_agg: dict[str, object] = {
                            "solution": entry.alias or entry.solution_id,
                            "instances": f"{entry.instances_solved}/{entry.instances_count}",
                        }
                        if entry.eval_time_s is not None:
                            row_agg["eval_time_s"] = f"{entry.eval_time_s:.1f}"
                        for metric_name, agg in entry.metrics.items():
                            if metric and metric_name != metric:
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
    format: Annotated[
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

        # Require --id or --latest
        if not benchmark_id and not latest:
            sys.stderr.write("Error: either --id or --latest is required.\n")
            raise typer.Exit(code=1)

        written_path = core_benchmark.export_benchmark(
            benchmark_id=benchmark_id,
            latest=latest,
            output_format=format,
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
            render(
                {"status": "exported", "path": str(written_path)},
                json_mode=False,
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
