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
from revolver.cli._global_options import GlobalOptionGroup
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import problem as core_problem
from revolver.core.exceptions import ValidationError
from revolver.infra.backends.base import AVAILABLE_BACKENDS
from revolver.infra.output import print_confirmation, render

# ── version sub-app ──────────────────────────────────────────────────────────
version_app = typer.Typer(
    cls=GlobalOptionGroup,
    help="Problem version management (create, list, delete).",
)
problem_app.add_typer(version_app, name="version")


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
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False
        ctx_verbose: bool = ctx.obj.get("verbose", False) if ctx.obj else False
        is_verbose = verbose or ctx_verbose

        # Progress indicator for dataset evaluation (NFR-005)
        use_progress = dataset is not None and not json_mode and not quiet
        if use_progress:
            from rich.console import Console

            stderr_console = Console(stderr=True)
            with stderr_console.status("Evaluating dataset instances..."):
                result = core_problem.test_problem(
                    instance=instance,
                    dataset=dataset,
                    program=program,
                    evaluator=evaluator,
                    timeout=timeout,
                )
        else:
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


@version_app.command("create")
def problem_version_create(
    ctx: typer.Context,
    tag_positional: Annotated[
        str | None,
        typer.Argument(
            metavar="TAG",
            help="Version tag (e.g. v1.0).",
        ),
    ] = None,
    tag_option: Annotated[
        str | None,
        typer.Option(
            "--tag",
            help="Version tag (e.g. v1.0). Deprecated: prefer the positional TAG.",
        ),
    ] = None,
    message: Annotated[
        str,
        typer.Option(
            "--message",
            "-m",
            help="Optional description for this version.",
        ),
    ] = "",
    backend: Annotated[
        str,
        typer.Option(
            "--backend",
            help=(
                f"Evolution backend that validates config.yaml: "
                f"{', '.join(AVAILABLE_BACKENDS)} (default: openevolve)."
            ),
        ),
    ] = "openevolve",
) -> None:
    """Create a new problem version snapshot."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Resolve the tag from either the positional argument or the
        # backward-compat ``--tag`` option (positional wins when both
        # are supplied — UX-2 / S16-17).
        tag = tag_positional or tag_option
        if tag is None:
            raise ValidationError(
                "A version tag is required. Provide it as a positional "
                "argument (e.g. 'revolver problem version create v1.0') or "
                "via the --tag option."
            )

        pv, config_warnings = core_problem.create_version(
            tag=tag, message=message, backend=backend
        )

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
            print_confirmation(
                f"Done: Problem versioned as {pv.hash[:12]}",
                json_mode=json_mode,
                quiet=quiet,
            )

        # S9a-04/S14-15: Display backend config validation warnings
        if config_warnings and not quiet:
            from rich.console import Console

            console = Console(stderr=True)
            for w in config_warnings:
                console.print(f"[yellow]Warning: {w}[/yellow]")


@version_app.command("list")
def problem_version_list(
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


@version_app.command("delete")
def problem_version_delete(
    ctx: typer.Context,
    tag: Annotated[str, typer.Argument(help="Version tag to delete.")],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Skip confirmation and delete even if runs reference this version.",
        ),
    ] = False,
) -> None:
    """Delete a problem version snapshot (DB record + files)."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Confirmation logic lives in the CLI layer, not in core
        if not force:
            if json_mode:
                raise ValidationError("Use --force to delete in JSON mode (no interactive prompt)")
            typer.confirm(f"Delete problem version '{tag}' and its snapshot?", abort=True)

        summary = core_problem.delete_version(tag=tag, force=force)

        result = {
            "tag": summary["tag"],
            "runs_referencing": summary["runs_referencing"],
            "status": "deleted",
        }

        render(result, json_mode=json_mode)

        if not json_mode:
            print_confirmation(
                f"Done: Problem version '{tag}' deleted",
                json_mode=json_mode,
                quiet=quiet,
            )
