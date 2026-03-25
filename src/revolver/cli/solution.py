"""CLI commands for ``revolver solution``.

Registers commands on the ``solution_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-005 §7, FR-SOL-001..013.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
from typing import Annotated

import typer

from revolver.cli import solution_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import solution as core_solution
from revolver.infra.output import print_confirmation, render

# ── solution list (FR-SOL-001, FR-SOL-002) ──────────────────────────────────


@solution_app.command("list")
def solution_list(
    ctx: typer.Context,
    version: Annotated[
        str | None,
        typer.Option("--version", help="Filter by problem version tag."),
    ] = None,
    llm: Annotated[
        str | None,
        typer.Option("--llm", help="Filter by LLM name."),
    ] = None,
    rank: Annotated[
        int | None,
        typer.Option("--rank", help="Filter by solution rank."),
    ] = None,
) -> None:
    """List solutions with optional filters."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        solutions = core_solution.list_solutions(
            version=version,
            llm=llm,
            rank=rank,
        )

        if json_mode:
            render(solutions, json_mode=True)
        else:
            if not solutions:
                render({"message": "No solutions found."}, json_mode=False)
            else:
                rows = [
                    {
                        "id": str(s.get("id", "")),
                        "alias": str(s.get("alias", "") or ""),
                        "version": str(s.get("problem_version", "")),
                        "llm": str(s.get("llm", "")),
                        "score": (
                            f"{s['best_score']:.4f}" if s.get("best_score") is not None else "-"
                        ),
                        "rank": str(s.get("rank", "")),
                    }
                    for s in solutions
                ]
                render(rows, json_mode=False)


# ── solution info (FR-SOL-003..005, FR-SOL-009) ─────────────────────────────


@solution_app.command("info")
def solution_info(
    ctx: typer.Context,
    solution_id: Annotated[
        str,
        typer.Argument(help="Solution ID or alias."),
    ],
) -> None:
    """Display full solution detail: lineage, program path, siblings."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        info = core_solution.get_solution_info(solution_id)

        if json_mode:
            render(info, json_mode=True)
        else:
            # Main detail
            data: dict[str, object] = {
                "id": info.get("id", ""),
                "alias": info.get("alias", "") or "",
                "run_id": info.get("run_id", ""),
                "rank": info.get("rank", ""),
                "best_score": (
                    f"{info['best_score']:.4f}" if info.get("best_score") is not None else "-"
                ),
                "problem_version": info.get("problem_version", ""),
                "llm": info.get("llm", ""),
                "dataset": info.get("dataset", ""),
                "llm_model": info.get("llm_model", ""),
                "program_path": info.get("program_path", ""),
            }
            render(data, json_mode=False)

            # Siblings (FR-SOL-009)
            raw_siblings = info.get("siblings", [])
            siblings_list: list[dict[str, object]] = (
                list(raw_siblings) if isinstance(raw_siblings, list) else []
            )
            if siblings_list:
                typer.echo("\nSibling solutions from same run:")
                sibling_rows: list[dict[str, object]] = [
                    {
                        "id": str(s.get("id", "")),
                        "rank": str(s.get("rank", "")),
                        "best_score": (
                            f"{s['best_score']:.4f}" if s.get("best_score") is not None else "-"
                        ),
                        "alias": str(s.get("alias", "") or ""),
                    }
                    for s in siblings_list
                ]
                render(sibling_rows, json_mode=False)


# ── solution alias (FR-SOL-006, FR-SOL-007) ─────────────────────────────────


@solution_app.command("alias")
def solution_alias(
    ctx: typer.Context,
    solution_id: Annotated[
        str,
        typer.Argument(help="Solution ID or alias to modify."),
    ],
    alias_name: Annotated[
        str,
        typer.Argument(help="New alias to set."),
    ],
) -> None:
    """Set an alias on a solution."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        core_solution.set_alias(solution_id, alias_name)

        if json_mode:
            render(
                {"solution_id": solution_id, "alias": alias_name},
                json_mode=True,
            )
        else:
            render(
                {"solution_id": solution_id, "alias": alias_name, "status": "updated"},
                json_mode=False,
            )
            print_confirmation(
                f"Done: Alias '{alias_name}' set for solution {solution_id}",
                json_mode=json_mode,
                quiet=quiet,
            )


# ── solution show (FR-SOL-003, FR-SOL-004) ────────────────────────────────


@solution_app.command("show")
def solution_show(
    ctx: typer.Context,
    alias_or_id: Annotated[
        str,
        typer.Argument(help="Solution ID or alias."),
    ],
) -> None:
    """Print solution program source code to stdout."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        code, sol = core_solution.show_solution(alias_or_id)

        if json_mode:
            render(
                {"alias": sol.alias or sol.id, "code": code},
                json_mode=True,
            )
        else:
            sys.stdout.write(code)


# ── solution export (FR-SOL-003, FR-SOL-004) ─────────────────────────────


@solution_app.command("export")
def solution_export(
    ctx: typer.Context,
    alias_or_id: Annotated[
        str,
        typer.Argument(help="Solution ID or alias."),
    ],
    output: Annotated[
        str | None,
        typer.Option("-o", "--output", help="Target file path (default: ./<alias>.py)."),
    ] = None,
) -> None:
    """Copy the solution program file to a local path."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        # Resolve solution and get validated program path (core layer)
        sol, program_path = core_solution.get_solution_program_path(alias_or_id)

        # Determine target path
        default_name = f"{sol.alias}.py" if sol.alias else f"{sol.id}.py"
        target = Path(output) if output else Path(default_name)

        shutil.copy2(program_path, target)

        if json_mode:
            render({"exported_to": str(target)}, json_mode=True)
        else:
            sys.stderr.write(f"Exported to {target}\n")


# ── solution diff ────────────────────────────────────────────────────────


@solution_app.command("diff")
def solution_diff(
    ctx: typer.Context,
    a: Annotated[
        str,
        typer.Argument(help="First solution ID or alias."),
    ],
    b: Annotated[
        str,
        typer.Argument(help="Second solution ID or alias."),
    ],
) -> None:
    """Print unified diff between two solution programs."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        diff_lines = core_solution.diff_solutions(a, b)

        if json_mode:
            diff_text = "".join(diff_lines)
            identical = len(diff_lines) == 0
            render({"diff": diff_text, "identical": identical}, json_mode=True)
        else:
            sys.stdout.write("".join(diff_lines))


# ── solution extract (FR-SOL-011..013) ──────────────────────────────────────


@solution_app.command("extract")
def solution_extract(
    ctx: typer.Context,
    run: Annotated[
        str,
        typer.Option("--run", help="Run ID to extract from."),
    ],
    alias: Annotated[
        str | None,
        typer.Option("--alias", help="Optional alias for the new solution."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace existing solution for this run."),
    ] = False,
) -> None:
    """Promote the best program from a run to a solution entry.

    Extracts rank-1 (best) program. Use --force to replace an existing
    extraction for the same run.
    """
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        solution = core_solution.extract_solution(
            run_id=run,
            rank=1,
            alias=alias,
            force=force,
        )

        sys.stderr.write(
            f"Extracted solution {solution.id} (run={solution.run_id}, rank={solution.rank})\n"
        )

        if json_mode:
            render(
                solution.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            data: dict[str, object] = {
                "solution_id": solution.id,
                "run_id": solution.run_id,
                "rank": solution.rank,
            }
            if solution.best_score is not None:
                data["best_score"] = solution.best_score
            if solution.alias:
                data["alias"] = solution.alias
            render(data, json_mode=False)

        # Confirmation summary (NFR-006)
        program_path = getattr(solution, "program_path", None)
        if program_path:
            extract_msg = f"Done: Solution extracted to {program_path}"
        else:
            extract_msg = f"Done: Solution {solution.id} extracted"
        print_confirmation(
            extract_msg,
            json_mode=json_mode,
            quiet=quiet,
        )


# ── solution delete (F4 — Sprint 005a) ──────────────────────────────────────


@solution_app.command("delete")
def solution_delete(
    ctx: typer.Context,
    solution: Annotated[
        str,
        typer.Argument(help="Solution ID or alias to delete."),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete a solution and its associated evaluation data."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Confirmation logic lives in the CLI layer, not in core
        if not force:
            if json_mode:
                from revolver.core.exceptions import ValidationError

                raise ValidationError("Use --force to delete in JSON mode (no interactive prompt)")
            typer.confirm(f"Delete solution '{solution}'?", abort=True)

        deleted_id = core_solution.delete_solution(solution)

        if json_mode:
            render(
                {"solution_id": deleted_id, "status": "deleted"},
                json_mode=True,
            )
        else:
            render(
                {"solution_id": deleted_id, "status": "deleted"},
                json_mode=False,
            )
            print_confirmation(
                f"Done: Solution {deleted_id} deleted",
                json_mode=json_mode,
                quiet=quiet,
            )
