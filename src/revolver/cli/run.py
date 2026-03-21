"""CLI commands for ``revolver run``.

Registers commands on the ``run_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-005 section 2, FR-RUN-001..030.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from revolver.cli import run_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import run as core_run
from revolver.core.exceptions import ValidationError
from revolver.infra.output import print_confirmation, render
from revolver.models.run import RunConfig

# ── Default callback: launch run (DES-005 §2.1) ─────────────────────────────


@run_app.callback(invoke_without_command=True)
def run_launch(
    ctx: typer.Context,
    version: Annotated[
        str | None,
        typer.Option("--version", help="Problem version tag."),
    ] = None,
    llm: Annotated[
        str | None,
        typer.Option("--llm", help="Registered LLM name."),
    ] = None,
    dataset: Annotated[
        str | None,
        typer.Option("--dataset", help="Registered dataset name."),
    ] = None,
    iterations: Annotated[
        int | None,
        typer.Option("--iterations", help="Number of OpenEvolve iterations."),
    ] = None,
    alias: Annotated[
        str | None,
        typer.Option("--alias", help="User-friendly alias for the rank-1 solution."),
    ] = None,
    config_override: Annotated[
        list[str] | None,
        typer.Option(
            "--config-override",
            help="OpenEvolve config override (key=value). Repeatable.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Display resolved config without launching."),
    ] = False,
) -> None:
    """Launch an OpenEvolve evolution run."""
    # If a subcommand was invoked, skip the launch logic
    if ctx.invoked_subcommand is not None:
        return

    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Validate required options
        if not version:
            sys.stderr.write("Error: --version is required.\n")
            raise typer.Exit(code=1)
        if not llm:
            sys.stderr.write("Error: --llm is required.\n")
            raise typer.Exit(code=1)
        if not dataset:
            sys.stderr.write("Error: --dataset is required.\n")
            raise typer.Exit(code=1)

        config = RunConfig(
            problem_version=version,
            llm_name=llm,
            dataset_name=dataset,
            iterations=iterations,
            alias=alias,
            config_overrides=config_override or [],
            dry_run=dry_run,
        )

        if not dry_run:
            sys.stderr.write(
                f"Launching run: version={version}, llm={llm}, dataset={dataset}"
                f"{f', iterations={iterations}' if iterations else ''}\n"
            )

        # Progress indicator for OpenEvolve execution (NFR-005)
        use_progress = not dry_run and not json_mode and not quiet
        suppress_info = json_mode or quiet
        if use_progress:
            from rich.console import Console

            stderr_console = Console(stderr=True)
            with stderr_console.status("Running OpenEvolve evolution..."):
                result = core_run.launch_run(config, quiet=suppress_info)
        else:
            result = core_run.launch_run(config, quiet=suppress_info)

        if dry_run:
            if json_mode:
                render(
                    result.model_dump(mode="json"),
                    json_mode=True,
                )
            else:
                render(
                    {
                        "status": "dry-run",
                        "run_id": result.run_id,
                        "problem_version": result.problem_version,
                        "llm": result.llm,
                        "dataset": result.dataset,
                        "iterations": result.iterations,
                    },
                    json_mode=False,
                )
            return

        # Display token usage on stderr if available
        if result.token_usage is not None:
            sys.stderr.write(
                f"Token usage: {result.token_usage.prompt_tokens} prompt + "
                f"{result.token_usage.completion_tokens} completion = "
                f"{result.token_usage.total_tokens} total\n"
            )
            if result.token_usage.estimated_cost_usd is not None:
                sys.stderr.write(
                    f"Estimated cost: ${result.token_usage.estimated_cost_usd:.4f} USD\n"
                )

        # Display post-run evaluation info on stderr
        sys.stderr.write(
            f"Run completed: {result.run_id} "
            f"({result.generation_time_s:.1f}s, "
            f"{result.programs_stored} programs stored)\n"
        )

        if json_mode:
            render(
                result.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            data: dict[str, object] = {
                "run_id": result.run_id,
                "solution_id": result.solution.solution_id,
                "problem_version": result.problem_version,
                "llm": result.llm,
                "dataset": result.dataset,
                "iterations": result.iterations,
                "generation_time_s": f"{result.generation_time_s:.1f}",
                "programs_stored": result.programs_stored,
            }
            if result.solution.best_score is not None:
                data["best_score"] = result.solution.best_score
            if result.solution.alias:
                data["alias"] = result.solution.alias
            if result.token_usage is not None:
                data["total_tokens"] = result.token_usage.total_tokens
                if result.token_usage.estimated_cost_usd is not None:
                    data["estimated_cost_usd"] = f"${result.token_usage.estimated_cost_usd:.4f}"
            if result.resumed_from:
                data["resumed_from"] = result.resumed_from
            render(data, json_mode=False)

        # Confirmation summary (NFR-006)
        print_confirmation(
            f"Done: Run {result.run_id} completed (status: completed)",
            json_mode=json_mode,
            quiet=quiet,
        )


# ── run status (DES-005 §2.2) ───────────────────────────────────────────────


@run_app.command("status")
def run_status(
    ctx: typer.Context,
) -> None:
    """Show active or latest run status."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        status = core_run.get_run_status()

        if json_mode:
            render(
                status.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            if status.active:
                data: dict[str, object] = {
                    "status": "active",
                    "run_ids": ", ".join(status.run_ids),
                }
                if status.run_id:
                    data["current_run"] = status.run_id
                if status.problem_version:
                    data["problem_version"] = status.problem_version
                if status.llm:
                    data["llm"] = status.llm
                if status.dataset:
                    data["dataset"] = status.dataset
                if status.iterations_total is not None:
                    data["iterations_total"] = status.iterations_total
                if status.elapsed_s is not None:
                    data["elapsed_s"] = f"{status.elapsed_s:.1f}"
                render(data, json_mode=False)
            elif status.run_id:
                data = {
                    "status": "idle",
                    "latest_run": status.run_id,
                }
                if status.problem_version:
                    data["problem_version"] = status.problem_version
                if status.llm:
                    data["llm"] = status.llm
                if status.dataset:
                    data["dataset"] = status.dataset
                render(data, json_mode=False)
            else:
                render({"status": "idle", "message": "No runs found."}, json_mode=False)


# ── run resume (DES-005 §2.3) ───────────────────────────────────────────────


@run_app.command("resume")
def run_resume(
    ctx: typer.Context,
    run: Annotated[
        str,
        typer.Option("--run", help="Run ID to resume from."),
    ],
) -> None:
    """Resume an interrupted or completed run from its checkpoint."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        sys.stderr.write(f"Resuming run from: {run}\n")

        result = core_run.resume_run(run_id=run, quiet=(json_mode or quiet))

        # Display token usage on stderr
        if result.token_usage is not None:
            sys.stderr.write(
                f"Token usage: {result.token_usage.prompt_tokens} prompt + "
                f"{result.token_usage.completion_tokens} completion = "
                f"{result.token_usage.total_tokens} total\n"
            )
            if result.token_usage.estimated_cost_usd is not None:
                sys.stderr.write(
                    f"Estimated cost: ${result.token_usage.estimated_cost_usd:.4f} USD\n"
                )

        sys.stderr.write(
            f"Resumed run completed: {result.run_id} "
            f"(from {result.resumed_from}, "
            f"{result.generation_time_s:.1f}s)\n"
        )

        if json_mode:
            render(
                result.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            data: dict[str, object] = {
                "run_id": result.run_id,
                "resumed_from": result.resumed_from or run,
                "solution_id": result.solution.solution_id,
                "problem_version": result.problem_version,
                "llm": result.llm,
                "dataset": result.dataset,
                "iterations": result.iterations,
                "generation_time_s": f"{result.generation_time_s:.1f}",
                "programs_stored": result.programs_stored,
            }
            if result.solution.best_score is not None:
                data["best_score"] = result.solution.best_score
            if result.token_usage is not None:
                data["total_tokens"] = result.token_usage.total_tokens
            render(data, json_mode=False)


# ── run list (DES-005 §2.4) ─────────────────────────────────────────────────


@run_app.command("list")
def run_list(
    ctx: typer.Context,
    version: Annotated[
        str | None,
        typer.Option("--version", help="Filter by problem version tag."),
    ] = None,
    llm: Annotated[
        str | None,
        typer.Option("--llm", help="Filter by LLM name."),
    ] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", help="Filter by run status."),
    ] = None,
) -> None:
    """List runs with optional filters."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        summaries = core_run.list_runs(
            version=version,
            llm=llm,
            status=status,
        )

        if json_mode:
            render(
                [s.model_dump(mode="json") for s in summaries],
                json_mode=True,
            )
        else:
            if not summaries:
                render({"message": "No runs found."}, json_mode=False)
            else:
                rows = [
                    {
                        "run_id": s.run_id,
                        "version": s.problem_version,
                        "llm": s.llm,
                        "dataset": s.dataset,
                        "status": s.status,
                        "iterations": s.iterations,
                        "valid": (
                            f"{s.valid_iterations}/{s.iterations}"
                            if s.valid_iterations is not None
                            else "\u2014"
                        ),
                        "best_score": (f"{s.best_score:.4f}" if s.best_score is not None else "-"),
                        "alias": s.alias or "",
                        "created_at": str(s.created_at),
                    }
                    for s in summaries
                ]
                render(rows, json_mode=False)


# ── run info (DES-005 §2.5) ─────────────────────────────────────────────────


@run_app.command("info")
def run_info(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="Run ID to inspect.")],
) -> None:
    """Show detailed run information."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        info = core_run.get_run_info(run_id)

        if json_mode:
            render(
                info.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            data: dict[str, object] = {
                "run_id": info.run_id,
                "problem_version": info.problem_version,
                "problem_hash": info.problem_hash,
                "llm": info.llm,
                "llm_model": info.llm_model,
                "dataset": info.dataset,
                "dataset_hash": info.dataset_hash,
                "status": info.status,
                "iterations": info.iterations,
                "created_at": str(info.created_at),
            }
            if info.valid_iterations is not None:
                pct = (
                    f"{info.valid_iterations / info.iterations * 100:.0f}"
                    if info.iterations > 0
                    else "0"
                )
                data["valid_iterations"] = f"{info.valid_iterations}/{info.iterations} ({pct}%)"
            if info.generation_time_s is not None:
                data["generation_time_s"] = f"{info.generation_time_s:.1f}"
            if info.resumed_from:
                data["resumed_from"] = info.resumed_from
            if info.resume_chain:
                data["resume_chain"] = " → ".join(info.resume_chain)
            if info.token_usage is not None:
                data["prompt_tokens"] = info.token_usage.prompt_tokens
                data["completion_tokens"] = info.token_usage.completion_tokens
                data["total_tokens"] = info.token_usage.total_tokens
                if info.token_usage.estimated_cost_usd is not None:
                    data["estimated_cost_usd"] = f"${info.token_usage.estimated_cost_usd:.4f}"

            render(data, json_mode=False)

            # Display solutions
            if info.solutions:
                sol_rows = [
                    {
                        "solution_id": s.solution_id,
                        "rank": s.rank,
                        "best_score": (f"{s.best_score:.4f}" if s.best_score is not None else "-"),
                        "alias": s.alias or "",
                    }
                    for s in info.solutions
                ]
                render(sol_rows, json_mode=False)

            # Display programs
            if info.programs:
                prog_rows = [
                    {
                        "rank": p.rank,
                        "score": (f"{p.score:.4f}" if p.score is not None else "-"),
                        "file": p.file,
                    }
                    for p in info.programs
                ]
                render(prog_rows, json_mode=False)


# ── run delete (FR-RUN-027) ──────────────────────────────────────────────────


@run_app.command("delete")
def run_delete(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="Run ID to delete.")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete a run and its associated solutions, evals, and files."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Confirmation logic lives in the CLI layer, not in core
        if not force:
            if json_mode:
                raise ValidationError("Use --force to delete in JSON mode (no interactive prompt)")
            typer.confirm(f"Delete run '{run_id}' and all its data?", abort=True)

        summary = core_run.delete_run(run_id)

        result = {
            "run_id": summary["run_id"],
            "solutions_deleted": summary["solutions_deleted"],
            "evals_deleted": summary["evals_deleted"],
            "status": "deleted",
        }

        render(result, json_mode=json_mode)

        if not json_mode:
            print_confirmation(
                f"Done: Run {run_id} deleted "
                f"({summary['solutions_deleted']} solutions, "
                f"{summary['evals_deleted']} evals removed)",
                json_mode=json_mode,
                quiet=quiet,
            )
