"""CLI commands for ``revolver eval``.

Registers commands on the ``eval_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-006 section 9, FR-EVL-001..020.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from revolver.cli import eval_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import eval as core_eval
from revolver.infra.output import render
from revolver.models.eval import EvalDetailResult, EvalResult

# ── Default callback: run evaluation (DES-006 §9) ────────────────────────────


@eval_app.callback(invoke_without_command=True)
def eval_default(
    ctx: typer.Context,
    solution: Annotated[
        str | None,
        typer.Option("--solution", help="Solution ID or alias."),
    ] = None,
    dataset: Annotated[
        str | None,
        typer.Option("--dataset", help="Evaluation dataset name."),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Per-instance timeout (seconds)."),
    ] = 300,
    force: Annotated[
        bool,
        typer.Option("--force", help="Skip confirmation for re-evaluation."),
    ] = False,
    per_instance: Annotated[
        bool,
        typer.Option("--per-instance", help="Show per-instance results on completion."),
    ] = False,
) -> None:
    """Evaluate a solution against an evaluation dataset."""
    # If a subcommand was invoked, skip the eval logic
    if ctx.invoked_subcommand is not None:
        return

    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        # Validate required options
        if not solution:
            sys.stderr.write("Error: --solution is required.\n")
            raise typer.Exit(code=1)
        if not dataset:
            sys.stderr.write("Error: --dataset is required.\n")
            raise typer.Exit(code=1)

        # Progress bar setup
        if not json_mode:
            from rich.console import Console
            from rich.progress import (
                BarColumn,
                MofNCompleteColumn,
                Progress,
                TextColumn,
                TimeElapsedColumn,
            )

            stderr_console = Console(stderr=True)
            progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=stderr_console,
            )
            task_id = None

            def on_progress(completed: int, total: int) -> None:
                nonlocal task_id
                if task_id is None:
                    task_id = progress.add_task("Evaluating", total=total)
                progress.update(task_id, completed=completed)

            progress.start()
            try:
                result = core_eval.evaluate_solution(
                    solution_id_or_alias=solution,
                    dataset_name=dataset,
                    timeout_s=timeout,
                    force=force,
                    json_mode=json_mode,
                    on_progress=on_progress,
                )
            finally:
                progress.stop()
        else:
            result = core_eval.evaluate_solution(
                solution_id_or_alias=solution,
                dataset_name=dataset,
                timeout_s=timeout,
                force=force,
                json_mode=json_mode,
                on_progress=None,
            )

        # Display results
        if json_mode:
            render(
                result.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            # Summary line on stderr
            time_part = ""
            if result.metadata.eval_time_s:
                time_part = f", {result.metadata.eval_time_s:.1f}s"
            solved = result.metadata.instances_solved
            total = result.metadata.instance_count
            sys.stderr.write(
                f"Evaluation complete: {result.metadata.eval_id} "
                f"({solved}/{total} solved{time_part})\n"
            )

            # Display Revolver aggregates
            if result.aggregates:
                agg_rows = []
                for metric_name, agg in result.aggregates.items():
                    agg_rows.append(
                        {
                            "metric": metric_name,
                            "mean": f"{agg.mean:.4f}",
                            "min": f"{agg.min:.4f}",
                            "max": f"{agg.max:.4f}",
                            "p10": f"{agg.p10:.4f}",
                            "p50": f"{agg.p50:.4f}",
                            "p90": f"{agg.p90:.4f}",
                            "std": f"{agg.std:.4f}",
                            "count": str(agg.count),
                        }
                    )
                render(agg_rows, json_mode=False)

            # Display user aggregates (legacy mode, D-006-g)
            if result.user_aggregates:
                sys.stderr.write("\nUser aggregates (legacy evaluator):\n")
                user_agg_data = {k: f"{v:.4f}" for k, v in result.user_aggregates.items()}
                render(user_agg_data, json_mode=False)

            # Display per-instance breakdown if requested
            if per_instance:
                detail = core_eval.get_eval_results(
                    solution_id_or_alias=solution,
                    dataset_name=dataset,
                    per_instance=True,
                )
                if isinstance(detail, EvalDetailResult) and detail.instances:
                    inst_rows: list[dict[str, str]] = []
                    for inst in detail.instances:
                        row: dict[str, str] = {
                            "instance_id": inst.instance_id,
                            "status": inst.status,
                        }
                        for k, v in inst.metrics.items():
                            row[k] = f"{v:.4f}"
                        if inst.compute_time_s is not None:
                            row["time_s"] = f"{inst.compute_time_s:.3f}"
                        inst_rows.append(row)
                    render(inst_rows, json_mode=False)


# ── results subcommand (DES-006 §9) ──────────────────────────────────────────


@eval_app.command()
def results(
    ctx: typer.Context,
    solution: Annotated[
        str,
        typer.Option("--solution", help="Solution ID or alias."),
    ],
    dataset: Annotated[
        str | None,
        typer.Option("--dataset", help="Filter by dataset."),
    ] = None,
    per_instance: Annotated[
        bool,
        typer.Option("--per-instance", help="Show per-instance results."),
    ] = False,
) -> None:
    """Display stored evaluation results."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        result = core_eval.get_eval_results(
            solution_id_or_alias=solution,
            dataset_name=dataset,
            per_instance=per_instance,
        )

        if json_mode:
            render(
                result.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            if isinstance(result, EvalDetailResult):
                # Per-instance view
                inst_rows = []
                for inst in result.instances:
                    row: dict[str, str] = {
                        "instance_id": inst.instance_id,
                        "status": inst.status,
                    }
                    for k, v in inst.metrics.items():
                        row[k] = f"{v:.4f}"
                    if inst.compute_time_s is not None:
                        row["time_s"] = f"{inst.compute_time_s:.3f}"
                    if inst.error:
                        row["error"] = inst.error
                    inst_rows.append(row)

                if inst_rows:
                    render(inst_rows, json_mode=False)
                else:
                    render(
                        {"message": "No per-instance results found."},
                        json_mode=False,
                    )
            elif isinstance(result, EvalResult):
                # Aggregates view
                meta_data: dict[str, object] = {
                    "eval_id": result.metadata.eval_id,
                    "solution_id": result.metadata.solution_id,
                    "dataset": result.metadata.dataset_name,
                    "instances": (
                        f"{result.metadata.instances_solved}"
                        f"/{result.metadata.instance_count} solved"
                    ),
                    "evaluated_at": str(result.metadata.evaluated_at),
                }
                if result.metadata.eval_time_s is not None:
                    meta_data["eval_time_s"] = f"{result.metadata.eval_time_s:.1f}"
                render(meta_data, json_mode=False)

                # Revolver aggregates
                if result.aggregates:
                    agg_rows = []
                    for metric_name, agg in result.aggregates.items():
                        agg_rows.append(
                            {
                                "metric": metric_name,
                                "mean": f"{agg.mean:.4f}",
                                "min": f"{agg.min:.4f}",
                                "max": f"{agg.max:.4f}",
                                "p10": f"{agg.p10:.4f}",
                                "p50": f"{agg.p50:.4f}",
                                "p90": f"{agg.p90:.4f}",
                                "std": f"{agg.std:.4f}",
                                "count": str(agg.count),
                            }
                        )
                    render(agg_rows, json_mode=False)

                # User aggregates (legacy mode)
                if result.user_aggregates:
                    sys.stderr.write("\nUser aggregates (legacy evaluator):\n")
                    user_agg_data = {k: f"{v:.4f}" for k, v in result.user_aggregates.items()}
                    render(user_agg_data, json_mode=False)
