"""CLI command for ``revolver doctor``.

Registers ``doctor`` as a top-level command on the root ``app``.
Works outside project directories (no ``.revolver/`` needed).

Traceable to: spec-setup.md, FR-SET-001..006, FR-SET-012, FR-SET-013.
"""

from __future__ import annotations

import typer

from revolver.cli import app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core.doctor import CheckStatus, DoctorReport, run_doctor
from revolver.infra.output import render

# ── Status icons ──────────────────────────────────────────────────────────────

_STATUS_ICONS: dict[CheckStatus, str] = {
    CheckStatus.OK: "\u2713",  # check mark
    CheckStatus.INFO: "\u2139",  # information source
    CheckStatus.WARN: "\u26a0",  # warning sign
    CheckStatus.FAIL: "\u2717",  # cross mark
}


def _render_human(report: DoctorReport) -> None:
    """Render a DoctorReport as human-readable output."""
    from rich.console import Console
    from rich.markup import escape

    console = Console()

    console.print("\nRevolver dependency check:\n")

    # Group checks by type
    python_checks = [c for c in report.checks if c.type == "python"]
    external_checks = [c for c in report.checks if c.type == "external"]
    system_checks = [c for c in report.checks if c.type == "system"]

    if python_checks:
        console.print("  Python packages:")
        for check in python_checks:
            icon = _STATUS_ICONS[check.status]
            # Escape: messages may contain literal brackets (e.g. the
            # "pip install 'revolver[shinka]'" hint) that rich would
            # otherwise swallow as markup tags.
            version_str = escape(check.version or check.message or "")
            line = f"    {icon} {check.name:<16s} {version_str}"
            if check.status == CheckStatus.OK:
                console.print(f"[green]{line}[/green]")
            elif check.status == CheckStatus.INFO:
                # Informational entry (optional backend): the message
                # already carries its own install instruction.
                console.print(f"[dim]{line}[/dim]")
            elif check.status == CheckStatus.WARN:
                console.print(f"[yellow]{line}[/yellow]")
            else:
                console.print(f"[red]{line}[/red]")
            if check.status in (CheckStatus.WARN, CheckStatus.FAIL) and check.message:
                console.print("      [dim]\u2192 Run `revolver setup` to install it[/dim]")
        console.print()

    if external_checks or system_checks:
        console.print("  External tools:")
        for check in external_checks + system_checks:
            icon = _STATUS_ICONS[check.status]
            version_str = check.version or ""
            extra = f"  {check.message}" if check.message else ""
            line = f"    {icon} {check.name:<16s} {version_str}{extra}"
            if check.status == CheckStatus.OK:
                console.print(f"[green]{line}[/green]")
            elif check.status == CheckStatus.WARN:
                console.print(f"[yellow]{line}[/yellow]")
            else:
                console.print(f"[red]{line}[/red]")
            if check.status != CheckStatus.OK and check.name == "ollama":
                console.print(
                    "      [dim]\u2192 Run `revolver setup` to install via conda-forge[/dim]"
                )
                console.print(
                    "      [dim]\u2192 Or install manually: https://ollama.com/download[/dim]"
                )
            elif check.status != CheckStatus.OK and check.name == "nvidia-smi":
                console.print(
                    "      [dim]\u2192 Install NVIDIA drivers for GPU support."
                    " Local LLM inference requires a compatible GPU.[/dim]"
                )
                console.print(
                    "      [dim]\u2192 Remote-only workflows will still work without GPU.[/dim]"
                )
        console.print()

    # Summary
    if report.overall_status == CheckStatus.OK:
        console.print("[bold green]All checks passed.[/bold green]")
    else:
        parts = []
        if report.error_count > 0:
            parts.append(f"{report.error_count} error{'s' if report.error_count != 1 else ''}")
        if report.warning_count > 0:
            parts.append(
                f"{report.warning_count} warning{'s' if report.warning_count != 1 else ''}"
            )
        summary = ", ".join(parts)
        console.print(f"[bold]{summary}.[/bold]", end="")
        if report.error_count > 0:
            console.print(" Run `revolver setup` to fix installable issues.")
        else:
            console.print()


def _render_json(report: DoctorReport) -> None:
    """Render a DoctorReport as JSON."""
    checks_data = []
    for check in report.checks:
        entry: dict[str, object] = {
            "name": check.name,
            "type": check.type,
            "status": check.status.value,
        }
        if check.version is not None:
            entry["version"] = check.version
        if check.status == CheckStatus.INFO and check.message:
            # Informational entries (optional backends) are not errors.
            entry["message"] = check.message
        elif check.status != CheckStatus.OK and check.message:
            entry["error"] = check.message
        if check.name == "ollama" and check.status == CheckStatus.OK and check.message:
            entry["url"] = "http://localhost:11434"
        entry["fixable"] = check.fixable
        checks_data.append(entry)

    output = {
        "status": report.overall_status.value,
        "checks": checks_data,
        "errors": report.error_count,
        "warnings": report.warning_count,
    }
    render(output, json_mode=True)


# ── CLI command ───────────────────────────────────────────────────────────────


@app.command("doctor")
def doctor_command(
    ctx: typer.Context,
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Attempt to fix issues (alias for `revolver setup`).",
    ),
) -> None:
    """Check the health of all dependencies."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        if fix:
            # Delegate to setup
            from revolver.core.setup import run_setup

            _plan, _results, post_report = run_setup(dry_run=False, force=False)
            report = post_report
        else:
            report = run_doctor()

        if json_mode:
            _render_json(report)
        else:
            _render_human(report)

        # Exit 1 if any FAIL
        if report.overall_status == CheckStatus.FAIL:
            raise typer.Exit(code=1)
