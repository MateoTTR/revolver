"""CLI commands for ``revolver llm``.

Registers commands on the ``llm_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-002 section 6, FR-LLM-001..008.
"""

from __future__ import annotations

import os
from typing import Annotated

import typer

from revolver.cli import llm_app
from revolver.cli._global_options import GlobalOptionGroup
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import llm as llm_core
from revolver.infra.db import get_global_db
from revolver.infra.ollama import OllamaClient, normalize_ollama_url
from revolver.infra.output import print_confirmation, render

# ── Ensemble sub-app ──────────────────────────────────────────────────────

ensemble_app = typer.Typer(cls=GlobalOptionGroup, help="LLM ensemble management.")
llm_app.add_typer(ensemble_app, name="ensemble")


@llm_app.command("add")
def llm_add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Unique name for this LLM registration.")],
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Model identifier (e.g. 'codestral:22b')."),
    ],
    source: Annotated[
        str,
        typer.Option(
            "--source",
            "-s",
            help=(
                "Model source: use 'local' for Ollama "
                "(provider is set automatically), 'remote' for API."
            ),
        ),
    ] = "remote",
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help="Provider (anthropic, openai, google, openai-compat).",
        ),
    ] = None,
    api_key_env: Annotated[
        str | None,
        typer.Option(
            "--api-key-env",
            help="Environment variable name holding the API key.",
        ),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            help="Override for the OpenAI-compatible endpoint URL.",
        ),
    ] = None,
    pull: Annotated[
        bool,
        typer.Option(
            "--pull",
            help="Pull the model from Ollama registry (local only).",
        ),
    ] = False,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens",
            help="Maximum tokens per LLM response (injected into OE config).",
        ),
    ] = None,
    timeout: Annotated[
        int | None,
        typer.Option(
            "--timeout",
            help=(
                "Per-request LLM timeout in seconds, mapped per backend "
                "(OE: llm.timeout; Shinka: client timeout for the run)."
            ),
        ),
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            help="Sampling temperature 0.0-2.0 (injected into OE config).",
        ),
    ] = None,
    reasoning_effort: Annotated[
        str | None,
        typer.Option(
            "--reasoning-effort",
            help=(
                "Reasoning-effort level (min|low|medium|high|max). Per-member "
                "on OpenEvolve; merged into a single global pool on ShinkaEvolve."
            ),
        ),
    ] = None,
) -> None:
    """Register a new LLM (local Ollama or remote API)."""
    with cli_error_boundary():
        conn = get_global_db()
        try:
            # Only create OllamaClient for local sources.
            # The probe must target the host the user asked for (#313):
            # derive the native-API root from --base-url, falling back to
            # OLLAMA_HOST, then to localhost. The OpenAI-compat /v1 form is
            # stripped because the /api/* probe calls live at the root.
            client: OllamaClient | None = None
            if source == "local":
                probe_url = base_url or os.environ.get("OLLAMA_HOST")
                probe_root, _ = normalize_ollama_url(probe_url)
                client = OllamaClient(base_url=probe_root)

            try:
                entry = llm_core.register_llm(
                    name=name,
                    model=model,
                    conn=conn,
                    source=source,  # type: ignore[arg-type]
                    provider=provider,
                    api_key_env=api_key_env,
                    base_url=base_url,
                    pull=pull,
                    max_tokens=max_tokens,
                    timeout_s=timeout,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    client=client,
                )
            finally:
                if client is not None:
                    client.close()
        finally:
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        if json_mode:
            render(
                {
                    "name": entry.name,
                    "model": entry.model,
                    "source": entry.source,
                    "provider": entry.provider,
                    "base_url": entry.base_url,
                    "api_key_env": entry.api_key_env,
                    "max_tokens": entry.max_tokens,
                    "timeout_s": entry.timeout_s,
                    "temperature": entry.temperature,
                    "reasoning_effort": entry.reasoning_effort,
                    "registered_at": entry.registered_at.isoformat(),
                },
                json_mode=True,
            )
        else:
            registered_row: dict[str, object] = {
                "status": "registered",
                "name": entry.name,
                "model": entry.model,
                "source": entry.source,
                "provider": entry.provider or "",
                "base_url": entry.base_url or "",
            }
            if entry.reasoning_effort is not None:
                registered_row["reasoning_effort"] = entry.reasoning_effort
            render(registered_row, json_mode=False)
            print_confirmation(
                f"Done: LLM '{entry.name}' registered",
                json_mode=json_mode,
                quiet=quiet,
            )


@llm_app.command("start")
def llm_start(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the LLM to start.")],
    timeout: Annotated[
        int,
        typer.Option("--timeout", "-t", help="Seconds to wait for model loading."),
    ] = 120,
) -> None:
    """Load a local LLM into GPU memory via Ollama."""
    with cli_error_boundary():
        conn = get_global_db()
        client = OllamaClient()
        try:
            result = llm_core.start_llm(
                name=name,
                conn=conn,
                timeout=timeout,
                client=client,
            )
        finally:
            client.close()
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        data: dict[str, object] = {
            "name": result.name,
            "model": result.model,
            "health_ok": result.health_ok,
        }
        if result.vram_mib is not None:
            data["vram_mib"] = result.vram_mib
        if result.previous_unloaded is not None:
            data["previous_unloaded"] = result.previous_unloaded

        if json_mode:
            render(data, json_mode=True)
        else:
            render({"status": "started", **data}, json_mode=False)


@llm_app.command("stop")
def llm_stop(
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(help="Name of the LLM to stop (optional, stops current if omitted)."),
    ] = None,
) -> None:
    """Unload a local LLM from GPU memory."""
    with cli_error_boundary():
        conn = get_global_db()
        client = OllamaClient()
        try:
            result = llm_core.stop_llm(
                conn=conn,
                name=name,
                client=client,
            )
        finally:
            client.close()
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        if json_mode:
            render(
                {
                    "name": result.name,
                    "model": result.model,
                    "was_loaded": result.was_loaded,
                },
                json_mode=True,
            )
        else:
            if result.was_loaded:
                render(
                    {"status": "stopped", "name": result.name, "model": result.model},
                    json_mode=False,
                )
            else:
                render({"status": "no model was loaded"}, json_mode=False)


@llm_app.command("status")
def llm_status(
    ctx: typer.Context,
    loaded_only: Annotated[
        bool,
        typer.Option(
            "--loaded-only",
            help="Only show currently loaded models.",
        ),
    ] = False,
) -> None:
    """Show runtime status of all registered LLMs."""
    with cli_error_boundary():
        conn = get_global_db()
        client = OllamaClient()
        try:
            report = llm_core.get_llm_status(
                conn=conn,
                loaded_only=loaded_only,
                client=client,
            )
        finally:
            client.close()
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        if json_mode:
            render(
                {
                    "llms": [s.model_dump() for s in report.llms],
                    "gpu": report.gpu,
                    "ollama_running": report.ollama_running,
                },
                json_mode=True,
            )
        else:
            if report.llms:
                rows = [
                    {
                        "name": s.name,
                        "source": s.source,
                        "status": s.status,
                        "vram_mib": str(s.vram_mib) if s.vram_mib is not None else "-",
                    }
                    for s in report.llms
                ]
                render(rows, json_mode=False)
            else:
                render({"info": "No LLMs registered"}, json_mode=False)

            if report.gpu:
                render(
                    {
                        "gpu": str(report.gpu.get("name", "")),
                        "vram_used_mib": str(report.gpu.get("vram_used_mib", "")),
                        "vram_total_mib": str(report.gpu.get("vram_total_mib", "")),
                    },
                    json_mode=False,
                )


@llm_app.command("list")
def llm_list(
    ctx: typer.Context,
) -> None:
    """List all registered LLMs."""
    with cli_error_boundary():
        conn = get_global_db()
        try:
            entries = llm_core.list_llms(conn)
        finally:
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        if json_mode:
            render(
                [
                    {
                        "name": e.name,
                        "model": e.model,
                        "source": e.source,
                        "provider": e.provider,
                        "base_url": e.base_url,
                        "max_tokens": e.max_tokens,
                        "timeout_s": e.timeout_s,
                        "temperature": e.temperature,
                        "reasoning_effort": e.reasoning_effort,
                    }
                    for e in entries
                ],
                json_mode=True,
            )
        else:
            if entries:
                # Show config columns only if any LLM has them set
                has_config = any(
                    e.max_tokens is not None or e.timeout_s is not None for e in entries
                )
                has_temperature = any(e.temperature is not None for e in entries)
                has_reasoning_effort = any(e.reasoning_effort is not None for e in entries)
                rows: list[dict[str, object]] = []
                for e in entries:
                    row: dict[str, object] = {
                        "name": e.name,
                        "model": e.model,
                        "source": e.source,
                        "provider": e.provider or "",
                    }
                    if has_config:
                        row["max_tokens"] = str(e.max_tokens) if e.max_tokens is not None else "-"
                        row["timeout_s"] = str(e.timeout_s) if e.timeout_s is not None else "-"
                    if has_temperature:
                        row["temperature"] = (
                            str(e.temperature) if e.temperature is not None else "-"
                        )
                    if has_reasoning_effort:
                        row["reasoning_effort"] = (
                            e.reasoning_effort if e.reasoning_effort is not None else "-"
                        )
                    rows.append(row)
                render(rows, json_mode=False)
            else:
                render({"info": "No LLMs registered"}, json_mode=False)


@llm_app.command("update")
def llm_update(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the LLM to update.")],
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help="New model identifier (e.g. gemini-2.5-flash-lite).",
        ),
    ] = None,
    max_tokens: Annotated[
        int | None,
        typer.Option(
            "--max-tokens",
            help="Maximum tokens per LLM response (injected into OE config).",
        ),
    ] = None,
    timeout: Annotated[
        int | None,
        typer.Option(
            "--timeout",
            help=(
                "Per-request LLM timeout in seconds, mapped per backend "
                "(OE: llm.timeout; Shinka: client timeout for the run)."
            ),
        ),
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option(
            "--temperature",
            help="Sampling temperature 0.0-2.0 (injected into OE config).",
        ),
    ] = None,
    reasoning_effort: Annotated[
        str | None,
        typer.Option(
            "--reasoning-effort",
            help="Reasoning-effort level (min|low|medium|high|max).",
        ),
    ] = None,
) -> None:
    """Update configuration fields of a registered LLM."""
    with cli_error_boundary():
        # Require at least one update flag
        if all(v is None for v in (model, max_tokens, timeout, temperature, reasoning_effort)):
            from revolver.core.exceptions import ValidationError

            raise ValidationError(
                "No update flags provided. Use at least one of: "
                "--model, --max-tokens, --timeout, --temperature, --reasoning-effort"
            )

        conn = get_global_db()
        try:
            entry = llm_core.update_llm(
                name=name,
                conn=conn,
                model=model,
                max_tokens=max_tokens,
                timeout_s=timeout,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
            )
        finally:
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        if json_mode:
            render(
                {
                    "name": entry.name,
                    "model": entry.model,
                    "source": entry.source,
                    "provider": entry.provider,
                    "base_url": entry.base_url,
                    "api_key_env": entry.api_key_env,
                    "max_tokens": entry.max_tokens,
                    "timeout_s": entry.timeout_s,
                    "temperature": entry.temperature,
                    "reasoning_effort": entry.reasoning_effort,
                    "registered_at": entry.registered_at.isoformat(),
                },
                json_mode=True,
            )
        else:
            render(
                {
                    "status": "updated",
                    "name": entry.name,
                    "model": entry.model,
                    "max_tokens": str(entry.max_tokens) if entry.max_tokens is not None else "-",
                    "timeout_s": str(entry.timeout_s) if entry.timeout_s is not None else "-",
                    "temperature": (
                        str(entry.temperature) if entry.temperature is not None else "-"
                    ),
                    "reasoning_effort": (
                        entry.reasoning_effort if entry.reasoning_effort is not None else "-"
                    ),
                },
                json_mode=False,
            )
            print_confirmation(
                f"Done: LLM '{entry.name}' updated",
                json_mode=json_mode,
                quiet=quiet,
            )


@llm_app.command("remove")
def llm_remove(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the LLM to remove.")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt."),
    ] = False,
    delete_model: Annotated[
        bool,
        typer.Option(
            "--delete-model",
            help="Also delete the model files from Ollama (local only).",
        ),
    ] = False,
) -> None:
    """Remove a registered LLM from the database."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        # Confirmation logic: require --force in JSON mode, prompt interactively otherwise
        if not force:
            if json_mode:
                from revolver.core.exceptions import ValidationError

                raise ValidationError("Use --force to remove in JSON mode (no interactive prompt)")
            typer.confirm(f"Remove LLM '{name}'?", abort=True)

        conn = get_global_db()
        try:
            # Only create OllamaClient if needed
            client: OllamaClient | None = None
            if delete_model:
                client = OllamaClient()
            try:
                llm_core.remove_llm(
                    name=name,
                    conn=conn,
                    delete_model=delete_model,
                    client=client,
                )
            finally:
                if client is not None:
                    client.close()
        finally:
            conn.close()

        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        if json_mode:
            render({"name": name, "removed": True}, json_mode=True)
        else:
            render({"status": "removed", "name": name}, json_mode=False)
            print_confirmation(
                f"Done: LLM '{name}' removed",
                json_mode=json_mode,
                quiet=quiet,
            )


# ── Ensemble CLI commands ──────────────────────────────────────────────────


@ensemble_app.command("create")
def ensemble_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Unique name for the ensemble.")],
) -> None:
    """Create an empty LLM ensemble."""
    with cli_error_boundary():
        conn = get_global_db()
        try:
            entry = llm_core.create_ensemble(name=name, conn=conn)
        finally:
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        if json_mode:
            render(
                {
                    "name": entry.name,
                    "members": [],
                    "created_at": entry.created_at.isoformat(),
                },
                json_mode=True,
            )
        else:
            render(
                {"status": "created", "name": entry.name},
                json_mode=False,
            )
            print_confirmation(
                f"Done: ensemble '{entry.name}' created",
                json_mode=json_mode,
                quiet=quiet,
            )


@ensemble_app.command("add")
def ensemble_add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the ensemble.")],
    llm: Annotated[
        str,
        typer.Option("--llm", help="Name of the registered LLM to add."),
    ],
    weight: Annotated[
        float,
        typer.Option("--weight", help="Sampling weight for this member."),
    ],
    temperature: Annotated[
        float | None,
        typer.Option("--temperature", help="Per-member temperature override."),
    ] = None,
    max_tokens: Annotated[
        int | None,
        typer.Option("--max-tokens", help="Per-member max_tokens override."),
    ] = None,
    reasoning_effort: Annotated[
        str | None,
        typer.Option(
            "--reasoning-effort",
            help=(
                "Per-member reasoning-effort override (min|low|medium|high|max); "
                "wins over the member LLM's registry-level reasoning_effort."
            ),
        ),
    ] = None,
) -> None:
    """Add a member LLM to an ensemble."""
    with cli_error_boundary():
        conn = get_global_db()
        try:
            llm_core.add_ensemble_member(
                ensemble_name=name,
                llm_name=llm,
                weight=weight,
                conn=conn,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
            # Fetch updated ensemble for display
            entry = llm_core.get_ensemble_info(name=name, conn=conn)
        finally:
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        if json_mode:
            render(
                {
                    "ensemble": name,
                    "added": llm,
                    "weight": weight,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "reasoning_effort": reasoning_effort,
                    "total_weight": sum(m.weight for m in entry.members),
                    "member_count": len(entry.members),
                },
                json_mode=True,
            )
        else:
            total_weight = sum(m.weight for m in entry.members)
            render(
                {
                    "status": "added",
                    "ensemble": name,
                    "llm": llm,
                    "weight": str(weight),
                    "total_weight": f"{total_weight:.2f}",
                },
                json_mode=False,
            )
            print_confirmation(
                f"Done: LLM '{llm}' added to ensemble '{name}'",
                json_mode=json_mode,
                quiet=quiet,
            )


@ensemble_app.command("list")
def ensemble_list(
    ctx: typer.Context,
) -> None:
    """List all LLM ensembles."""
    with cli_error_boundary():
        conn = get_global_db()
        try:
            entries = llm_core.list_ensembles(conn)
        finally:
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        if json_mode:
            render(
                [
                    {
                        "name": e.name,
                        "member_count": len(e.members),
                        "total_weight": sum(m.weight for m in e.members),
                        "created_at": e.created_at.isoformat(),
                    }
                    for e in entries
                ],
                json_mode=True,
            )
        else:
            if entries:
                rows = [
                    {
                        "name": e.name,
                        "members": str(len(e.members)),
                        "total_weight": f"{sum(m.weight for m in e.members):.2f}",
                        "created_at": e.created_at.isoformat(),
                    }
                    for e in entries
                ]
                render(rows, json_mode=False)
            else:
                render({"info": "No ensembles registered"}, json_mode=False)


@ensemble_app.command("info")
def ensemble_info(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the ensemble.")],
) -> None:
    """Show detailed information about an ensemble."""
    with cli_error_boundary():
        conn = get_global_db()
        try:
            entry = llm_core.get_ensemble_info(name=name, conn=conn)
        finally:
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        if json_mode:
            render(
                {
                    "name": entry.name,
                    "created_at": entry.created_at.isoformat(),
                    "members": [
                        {
                            "llm_name": m.llm_name,
                            "weight": m.weight,
                            "temperature": m.temperature,
                            "max_tokens": m.max_tokens,
                            "reasoning_effort": m.reasoning_effort,
                        }
                        for m in entry.members
                    ],
                    "total_weight": sum(m.weight for m in entry.members),
                },
                json_mode=True,
            )
        else:
            # Show ensemble header
            render(
                {
                    "name": entry.name,
                    "members": str(len(entry.members)),
                    "total_weight": f"{sum(m.weight for m in entry.members):.2f}",
                    "created_at": entry.created_at.isoformat(),
                },
                json_mode=False,
            )
            # Show member table
            if entry.members:
                member_rows = [
                    {
                        "llm_name": m.llm_name,
                        "weight": str(m.weight),
                        "temperature": str(m.temperature) if m.temperature is not None else "-",
                        "max_tokens": str(m.max_tokens) if m.max_tokens is not None else "-",
                        "reasoning_effort": (
                            m.reasoning_effort if m.reasoning_effort is not None else "-"
                        ),
                    }
                    for m in entry.members
                ]
                render(member_rows, json_mode=False)


@ensemble_app.command("remove")
def ensemble_remove(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the ensemble to remove.")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Remove an ensemble from the database."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        if not force:
            if json_mode:
                from revolver.core.exceptions import ValidationError

                raise ValidationError("Use --force to remove in JSON mode (no interactive prompt)")
            typer.confirm(f"Remove ensemble '{name}'?", abort=True)

        conn = get_global_db()
        try:
            llm_core.remove_ensemble(name=name, conn=conn)
        finally:
            conn.close()

        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        if json_mode:
            render({"name": name, "removed": True}, json_mode=True)
        else:
            render({"status": "removed", "name": name}, json_mode=False)
            print_confirmation(
                f"Done: ensemble '{name}' removed",
                json_mode=json_mode,
                quiet=quiet,
            )
