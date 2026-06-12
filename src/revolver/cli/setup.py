"""CLI command for ``revolver setup``.

Registers ``setup`` as a top-level command on the root ``app``.
Installs or upgrades missing Python-installable dependencies.

Traceable to: spec-setup.md, FR-SET-007..011, FR-SET-014..017.
"""

from __future__ import annotations

import typer

from revolver.cli import app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core.doctor import CheckStatus, run_doctor
from revolver.core.setup import (
    InstallMethod,
    compute_install_plan,
    detect_package_managers,
    execute_install_plan,
)
from revolver.infra.output import render


@app.command("setup")
def setup_command(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be installed without making changes.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reinstall even if already present; skip confirmation.",
    ),
) -> None:
    """Install or upgrade missing dependencies."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        # 1. Run doctor
        report = run_doctor()

        # 2. Detect package managers
        managers = detect_package_managers()

        # 3. Compute install plan
        plan = compute_install_plan(report, managers)

        # Nothing to do? (optional-only entries are informational, not issues)
        if not plan.items and not plan.manual_instructions:
            if json_mode:
                payload: dict[str, object] = {
                    "status": "ok",
                    "message": "All dependencies are satisfied.",
                }
                if plan.optional_instructions:
                    payload["optional"] = plan.optional_instructions
                render(payload, json_mode=True)
            else:
                from rich.console import Console
                from rich.markup import escape

                ok_console = Console()
                ok_console.print("[green]All dependencies are already satisfied.[/green]")
                for instruction in plan.optional_instructions:
                    ok_console.print(f"  [dim]{escape(instruction)}[/dim]")
            return

        # 4. Display plan
        auto_items = [i for i in plan.items if i.method != InstallMethod.MANUAL]
        manual_items = [i for i in plan.items if i.method == InstallMethod.MANUAL]

        if json_mode:
            plan_data: dict[str, object] = {
                "dry_run": dry_run,
                "install": [
                    {
                        "name": item.name,
                        "method": item.method.value,
                        "version": item.version,
                    }
                    for item in auto_items
                ],
                "manual": plan.manual_instructions,
                "optional": plan.optional_instructions,
            }

            if dry_run:
                plan_data["status"] = "dry_run"
                render(plan_data, json_mode=True)
                return

        if not json_mode:
            from rich.console import Console
            from rich.markup import escape

            console = Console()

            if auto_items:
                verb = "would be" if dry_run else "will be"
                console.print(f"\nThe following {verb} installed:")
                for item in auto_items:
                    console.print(
                        f"  {item.name:<16s} ({item.version})    via {item.method.value}"
                    )

            if manual_items or plan.manual_instructions:
                console.print()
                if managers.get("conda", False) or managers.get("mamba", False):
                    pass  # Ollama handled via conda, not manual
                else:
                    console.print("Not auto-installable (no conda detected):")
                    for item in manual_items:
                        console.print(f"  {item.name}")
                for instruction in plan.manual_instructions:
                    console.print(f"  [dim]{escape(instruction)}[/dim]")

            if plan.optional_instructions:
                # Escape: instructions may contain literal brackets (e.g.
                # "pip install 'revolver[shinka]'") that rich would
                # otherwise swallow as markup tags.
                console.print()
                console.print("Optional (not installed automatically):")
                for instruction in plan.optional_instructions:
                    console.print(f"  [dim]{escape(instruction)}[/dim]")

            if dry_run:
                console.print("\n[yellow]No changes made (dry run).[/yellow]")
                return

            # 5. Ask confirmation (unless --force)
            if not force and auto_items:
                console.print()
                confirmed = typer.confirm("Proceed?", default=True)
                if not confirmed:
                    console.print("[yellow]Aborted.[/yellow]")
                    raise typer.Exit(code=0)

        # 6. Execute plan
        results = execute_install_plan(plan, dry_run=False, force=force)

        # 7. Show results
        any_failure = False
        if json_mode:
            results_data = []
            for r in results:
                entry: dict[str, object] = {
                    "name": r.name,
                    "success": r.success,
                }
                if r.version:
                    entry["version"] = r.version
                if r.error:
                    entry["error"] = r.error
                results_data.append(entry)
                if not r.success:
                    any_failure = True

            # Re-run doctor for verification
            post_report = run_doctor()
            output: dict[str, object] = {
                "status": "fail" if any_failure else "ok",
                "results": results_data,
                "manual": plan.manual_instructions,
                "optional": plan.optional_instructions,
                "post_check": {
                    "status": post_report.overall_status.value,
                    "errors": post_report.error_count,
                    "warnings": post_report.warning_count,
                },
            }
            render(output, json_mode=True)
        else:
            console.print()
            for r in results:
                if r.success:
                    version_str = f" ({r.version})" if r.version else ""
                    console.print(
                        f"[green]Installing {r.name} via pip... done{version_str}[/green]"
                    )
                else:
                    any_failure = True
                    console.print(f"[red]Installing {r.name}... failed: {r.error}[/red]")

            # Re-run doctor for verification
            post_report = run_doctor()

            console.print()
            if post_report.overall_status == CheckStatus.OK:
                console.print("[bold green]All dependencies are now satisfied.[/bold green]")
            else:
                remaining = post_report.error_count + post_report.warning_count
                console.print(
                    f"[yellow]{remaining} dependency issue(s) remain."
                    " See above for manual instructions.[/yellow]"
                )

            if plan.manual_instructions:
                count = len(plan.manual_instructions)
                console.print(
                    f"\n[yellow]{count} dependency/ies require(s)"
                    " manual installation. See above.[/yellow]"
                )

        if any_failure:
            raise typer.Exit(code=1)
