"""CLI commands for ``revolver run``.

Registers commands on the ``run_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-005 section 2, FR-RUN-001..048, ADR-007.
"""

from __future__ import annotations

import os
import sys
from typing import Annotated

import typer

from revolver.cli import run_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import run as core_run
from revolver.core.exceptions import ValidationError
from revolver.infra.backends.base import AVAILABLE_BACKENDS
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
    backend: Annotated[
        str,
        typer.Option(
            "--backend",
            help=f"Evolution backend: {', '.join(AVAILABLE_BACKENDS)} (default: openevolve).",
        ),
    ] = "openevolve",
    iterations: Annotated[
        int | None,
        typer.Option("--iterations", help="Number of evolution iterations."),
    ] = None,
    alias: Annotated[
        str | None,
        typer.Option(
            "--alias",
            help="User-friendly alias for the rank-1 solution.",
        ),
    ] = None,
    config_override: Annotated[
        list[str] | None,
        typer.Option(
            "--config-override",
            help="Backend config override (key=value). Repeatable.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Display resolved config without launching.",
        ),
    ] = False,
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            help="Sampling temperature for the LLM (overrides LLM registry value).",
        ),
    ] = None,
    parallel: Annotated[
        int | None,
        typer.Option(
            "--parallel",
            help="Number of parallel evaluations.",
        ),
    ] = None,
    rewrite_mode: Annotated[
        bool,
        typer.Option(
            "--rewrite-mode",
            help=(
                "Full-rewrite mode: sets diff_based_evolution=false and "
                "max_code_length=50000. Overridable by --config-override."
            ),
        ),
    ] = False,
) -> None:
    """Launch an evolution run on the selected backend."""
    # If a subcommand was invoked, skip the launch logic
    if ctx.invoked_subcommand is not None:
        return

    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Smart defaults for --version and --dataset (S8a-10, S8a-11)
        if not version:
            version = core_run.resolve_default_version()
            if not json_mode and not quiet:
                sys.stderr.write(f"Using version {version} (only version)\n")
        if not llm:
            sys.stderr.write("Error: --llm is required.\n")
            raise typer.Exit(code=1)
        if not dataset:
            dataset = core_run.resolve_default_dataset()
            if not json_mode and not quiet:
                sys.stderr.write(f"Using dataset {dataset} (only train dataset)\n")

        config = RunConfig(
            problem_version=version,
            llm_name=llm,
            dataset_name=dataset,
            iterations=iterations,
            alias=alias,
            config_overrides=config_override or [],
            dry_run=dry_run,
            temperature=temperature,
            parallel=parallel,
            rewrite_mode=rewrite_mode,
            backend=backend,
        )

        if not dry_run:
            sys.stderr.write(
                f"Launching run: version={version}, llm={llm}, dataset={dataset}"
                f"{f', iterations={iterations}' if iterations else ''}\n"
            )

        # Real-time progress: stream engine output line-by-line (S8a-09)
        # Disable Python output buffering so child processes flush immediately.
        suppress_info = json_mode or quiet
        os.environ["PYTHONUNBUFFERED"] = "1"
        if not dry_run and not suppress_info:
            sys.stderr.write(f"Running {backend} evolution...\n")
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
                        "backend": backend,
                        "problem_version": result.problem_version,
                        "llm": result.llm,
                        "dataset": result.dataset,
                        "iterations": result.iterations,
                    },
                    json_mode=False,
                )
                # Display the resolved config section (S9a-08, S12-04/05/06,
                # FR-RUN-047): backend-neutral fields first, then a generic
                # loop over the backend-exclusive extras (ADR-007 D4).
                if result.resolved_config is not None:
                    rc = result.resolved_config
                    config_data: dict[str, object] = {"backend": rc.backend}
                    if rc.iterations is not None:
                        config_data["iterations"] = rc.iterations
                    if rc.num_islands is not None:
                        config_data["num_islands"] = rc.num_islands
                    if rc.temperature is not None:
                        config_data["temperature"] = rc.temperature
                    if rc.language is not None:
                        config_data["language"] = rc.language
                    if rc.llm_models is not None:
                        parts = []
                        for m in rc.llm_models:
                            name = m.get("name", m.get("model", "?"))
                            weight = m.get("weight")
                            if weight is not None:
                                parts.append(f"{name}\u00d7{weight}")
                            else:
                                parts.append(name)
                        config_data["llm_models"] = ", ".join(parts)
                    if rc.config_overrides is not None:
                        config_data["config_overrides"] = ", ".join(
                            f"{k}={v}" for k, v in rc.config_overrides.items()
                        )
                    for key, value in rc.backend_extras.items():
                        config_data[key] = value
                    sys.stderr.write(f"\nResolved {rc.backend} config:\n")
                    render(config_data, json_mode=False)
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
                if status.iterations_completed is not None and status.iterations_total is not None:
                    data["progress"] = f"{status.iterations_completed}/{status.iterations_total}"
                elif status.iterations_total is not None:
                    data["iterations_total"] = status.iterations_total
                if status.best_score is not None:
                    data["best_score"] = status.best_score
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
                if status.iterations_completed is not None and status.iterations_total is not None:
                    data["progress"] = f"{status.iterations_completed}/{status.iterations_total}"
                if status.best_score is not None:
                    data["best_score"] = status.best_score
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
    iterations: Annotated[
        int | None,
        typer.Option("--iterations", help="Number of iterations for the resumed run."),
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            help="LLM temperature override (0.0-2.0).",
        ),
    ] = None,
    parallel: Annotated[
        int | None,
        typer.Option(
            "--parallel",
            help="Number of parallel evaluations.",
        ),
    ] = None,
    llm: Annotated[
        str | None,
        typer.Option("--llm", help="Override LLM for the resumed run (must be registered)."),
    ] = None,
    config_override: Annotated[
        list[str] | None,
        typer.Option(
            "--config-override",
            help="Backend config override (key=value). Repeatable.",
        ),
    ] = None,
    rewrite_mode: Annotated[
        bool,
        typer.Option(
            "--rewrite-mode",
            help=(
                "Full-rewrite mode: sets diff_based_evolution=false and "
                "max_code_length=50000. Overridable by --config-override."
            ),
        ),
    ] = False,
) -> None:
    """Resume an interrupted or completed run from its checkpoint.

    The resumed run inherits the parent run's backend (FR-RUN-047).
    """
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Validate temperature range (same as run_start)
        if temperature is not None and not (0.0 <= temperature <= 2.0):
            sys.stderr.write("Error: --temperature must be between 0.0 and 2.0\n")
            raise typer.Exit(1)

        sys.stderr.write(f"Resuming run from: {run}\n")

        result = core_run.resume_run(
            run_id=run,
            iterations=iterations,
            temperature=temperature,
            parallel=parallel,
            llm_name=llm,
            config_overrides=config_override or None,
            rewrite_mode=rewrite_mode,
            quiet=(json_mode or quiet),
        )

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

        # Auto-detect zombie runs (S10-14)
        try:
            zombies = core_run.detect_zombie_runs()
            if zombies:
                sys.stderr.write(
                    f"Warning: {len(zombies)} zombie run(s) detected and marked as interrupted\n"
                )
        except Exception:
            pass  # Don't let zombie detection crash listing

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
                        "llm": (f"(E) {s.llm}" if s.llm_type == "ensemble" else s.llm),
                        "dataset": s.dataset,
                        "backend": s.backend,
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
            # Build LLM display string — enriched for ensemble runs (S11-09)
            llm_display: str = info.llm
            if info.llm_type == "ensemble" and info.llm_snapshot:
                try:
                    import json

                    snap = json.loads(info.llm_snapshot)
                    if snap.get("type") == "ensemble" and "members" in snap:
                        parts = []
                        for m in snap["members"]:
                            name = m.get("name", "?")
                            weight = m.get("weight", 1.0)
                            parts.append(f"{name}\u00d7{weight}")
                        llm_display = f"{info.llm} (ensemble: {', '.join(parts)})"
                except (ValueError, KeyError):
                    llm_display = f"{info.llm} (ensemble)"

            data: dict[str, object] = {
                "run_id": info.run_id,
                "problem_version": info.problem_version,
                "problem_hash": info.problem_hash,
                "llm": llm_display,
                "llm_model": info.llm_model,
                "dataset": info.dataset,
                "dataset_hash": info.dataset_hash,
                "status": info.status,
                "backend": info.backend,
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

            # Unproductive-run warning (#302): completed but 0 evolved children
            if info.produced_no_children:
                sys.stderr.write(
                    "WARNING: this run produced no successful child programs; "
                    "only the initial program(s) remain.\n"
                )

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
    run_id: Annotated[
        str | None,
        typer.Argument(help="Run ID to delete."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt."),
    ] = False,
    all_runs: Annotated[
        bool,
        typer.Option("--all", help="Delete all runs in the project."),
    ] = False,
) -> None:
    """Delete a run and its associated solutions, evals, and files."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Mutual exclusion: --all and run_id cannot be used together
        if all_runs and run_id is not None:
            raise ValidationError("Cannot use --all with a specific run ID")

        if all_runs:
            # Count runs first for confirmation
            summaries = core_run.list_runs()
            count = len(summaries)

            if count == 0:
                render(
                    {"status": "no-op", "message": "No runs to delete."},
                    json_mode=json_mode,
                )
                return

            if not force:
                if json_mode:
                    raise ValidationError(
                        "Use --force to delete in JSON mode (no interactive prompt)"
                    )
                typer.confirm(f"Delete all {count} run(s) and their data?", abort=True)

            bulk_result = core_run.delete_all_runs()
            deleted: int = bulk_result["deleted"]  # type: ignore[assignment]
            skipped: list[str] = bulk_result["skipped"]  # type: ignore[assignment]

            result_data: dict[str, object] = {
                "runs_deleted": deleted,
                "status": "deleted",
            }
            if skipped:
                result_data["skipped"] = skipped
            render(result_data, json_mode=json_mode)

            if not json_mode:
                msg = f"Done: {deleted} run(s) deleted"
                if skipped:
                    msg += f" ({len(skipped)} skipped — active)"
                print_confirmation(msg, quiet=quiet)
                for sid in skipped:
                    typer.echo(
                        f"Warning: Could not delete run '{sid}' (active), skipping.",
                        err=True,
                    )
            return

        # Single-run deletion: run_id is required
        if run_id is None:
            raise ValidationError("Run ID is required (or use --all to delete all runs)")

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
                quiet=quiet,
            )


# ── run population (S10-16) ──────────────────────────────────────────────────


@run_app.command("population")
def run_population(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="Run ID to inspect.")],
) -> None:
    """Display the MAP-Elites population of a run."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        population = core_run.get_population(run_id)

        if json_mode:
            render(population, json_mode=True)
            return

        if not population:
            sys.stderr.write("Population is empty (no programs found).\n")
            return

        # Determine whether to show the island column (only if >1 island).
        island_values = {
            prog.get("island") for prog in population if prog.get("island") is not None
        }
        show_island = len(island_values) > 1

        rows: list[dict[str, object]] = []
        for prog in population:
            row: dict[str, object] = {
                "rank": prog["rank"],
                "score": f"{prog['score']:.4f}",
                "cell": (
                    str(prog["cell_indices"]) if prog.get("cell_indices") is not None else "\u2014"
                ),
            }
            if show_island:
                row["island"] = prog.get("island") if prog.get("island") is not None else "\u2014"
            row["generation"] = prog["generation"]
            row["iteration"] = prog["iteration_found"]
            row["metrics"] = ", ".join(
                f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                for k, v in prog["metrics"].items()
            )
            row["program_id"] = prog["id"]
            rows.append(row)

        render(rows, json_mode=False)


# ── run cleanup (S10-15) ──────────────────────────────────────────────────────


@run_app.command("cleanup")
def run_cleanup(
    ctx: typer.Context,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Detect and mark zombie runs as interrupted."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        # Check how many running runs exist before prompting
        if not force:
            running = core_run.list_runs(status="running")
            if not running:
                if json_mode:
                    render({"zombies_cleaned": 0}, json_mode=True)
                else:
                    sys.stderr.write("No zombie runs found.\n")
                return

            if json_mode:
                raise ValidationError(
                    "Use --force to cleanup in JSON mode (no interactive prompt)"
                )
            typer.confirm(
                f"Scan and clean up to {len(running)} running run(s)?",
                abort=True,
            )

        zombies = core_run.detect_zombie_runs()

        if not zombies:
            if json_mode:
                render({"zombies_cleaned": 0}, json_mode=True)
            else:
                sys.stderr.write("No zombie runs found.\n")
            return

        if json_mode:
            render(
                {"zombies_cleaned": len(zombies), "run_ids": zombies},
                json_mode=True,
            )
        else:
            sys.stderr.write(f"Marked {len(zombies)} zombie run(s) as interrupted.\n")
