"""CLI commands for ``revolver problem``.

Registers commands on the ``problem_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-003 section 6, FR-PRB-006..013.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from revolver.cli import problem_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import problem as core_problem
from revolver.infra.output import render


@problem_app.command("test")
def problem_test(
    ctx: typer.Context,
    instance: Annotated[
        Path | None,
        typer.Option(
            "--instance",
            help="Path to a single instance file.",
        ),
    ] = None,
    dataset: Annotated[
        Path | None,
        typer.Option(
            "--dataset",
            help="Path to a directory of instance files.",
        ),
    ] = None,
    program: Annotated[
        Path | None,
        typer.Option(
            "--program",
            help="Path to the program to evaluate (default: ./initial_program.py).",
        ),
    ] = None,
    evaluator: Annotated[
        Path | None,
        typer.Option(
            "--evaluator",
            help="Path to the evaluator file (default: ./evaluator.py).",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            help="Maximum seconds per instance evaluation.",
        ),
    ] = 300,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Show detailed output including tracebacks.",
        ),
    ] = False,
) -> None:
    """Test a problem evaluator against one instance or a dataset."""
    with cli_error_boundary():
        # Validate at least one of --instance or --dataset
        if instance is None and dataset is None:
            raise typer.BadParameter("At least one of --instance or --dataset must be provided.")

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        ctx_verbose: bool = ctx.obj.get("verbose", False) if ctx.obj else False
        is_verbose = verbose or ctx_verbose

        result = core_problem.test_problem(
            instance=instance,
            dataset=dataset,
            program=program,
            evaluator=evaluator,
            timeout=timeout,
        )

        if json_mode:
            render(
                result.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            # Human-readable output
            rows: list[dict[str, object]] = []
            for r in result.results:
                row: dict[str, object] = {
                    "instance": r.instance_id,
                    "status": r.status,
                    "time_s": f"{r.time_s:.3f}",
                }
                if r.metrics:
                    for key, val in r.metrics.items():
                        row[key] = f"{val:.4f}"
                if is_verbose and r.error:
                    row["error"] = r.error
                if is_verbose and r.traceback:
                    row["traceback"] = r.traceback
                rows.append(row)

            if rows:
                render(rows, json_mode=False)

            # Summary line
            summary = {
                "total": result.total,
                "passed": result.passed,
                "failed": result.failed,
                "mean_time_s": f"{result.mean_time_s:.3f}",
                "max_time_s": f"{result.max_time_s:.3f}",
            }
            render(summary, json_mode=False)


@problem_app.command("version")
def problem_version(
    ctx: typer.Context,
    tag: Annotated[
        str,
        typer.Option(
            "--tag",
            help="Version tag (e.g. v1.0).",
        ),
    ],
    message: Annotated[
        str,
        typer.Option(
            "--message",
            "-m",
            help="Optional description for this version.",
        ),
    ] = "",
) -> None:
    """Create a new problem version snapshot."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        pv = core_problem.create_version(tag=tag, message=message)

        if json_mode:
            render(
                pv.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            render(
                {
                    "tag": pv.tag,
                    "hash": pv.hash,
                    "message": pv.message,
                    "files": len(pv.files),
                    "created_at": str(pv.created_at),
                },
                json_mode=False,
            )


@problem_app.command("versions")
def problem_versions(
    ctx: typer.Context,
) -> None:
    """List all problem versions."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        versions = core_problem.list_versions()

        if json_mode:
            render(
                [v.model_dump(mode="json") for v in versions],
                json_mode=True,
            )
        else:
            if not versions:
                render({"message": "No problem versions found."}, json_mode=False)
            else:
                rows = [
                    {
                        "tag": v.tag,
                        "hash": v.hash[:20] + "...",
                        "message": v.message,
                        "created_at": str(v.created_at),
                    }
                    for v in versions
                ]
                render(rows, json_mode=False)
