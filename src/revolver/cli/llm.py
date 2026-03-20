"""CLI commands for ``revolver llm``.

Registers commands on the ``llm_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-002 section 6, FR-LLM-001..008.
"""

from __future__ import annotations

from typing import Annotated

import typer

from revolver.cli import llm_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import llm as llm_core
from revolver.infra.db import get_global_db
from revolver.infra.ollama import OllamaClient
from revolver.infra.output import render


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
            help="Model source: 'local' for Ollama, 'remote' for API.",
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
    input_cost: Annotated[
        float | None,
        typer.Option(
            "--input-cost",
            help="Cost per million input tokens (USD).",
        ),
    ] = None,
    output_cost: Annotated[
        float | None,
        typer.Option(
            "--output-cost",
            help="Cost per million output tokens (USD).",
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
            help="Request timeout in seconds (injected into OE config).",
        ),
    ] = None,
) -> None:
    """Register a new LLM (local Ollama or remote API)."""
    with cli_error_boundary():
        conn = get_global_db()
        try:
            # Only create OllamaClient for local sources
            client: OllamaClient | None = None
            if source == "local":
                client = OllamaClient()

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
                    input_cost_per_mtok=input_cost,
                    output_cost_per_mtok=output_cost,
                    max_tokens=max_tokens,
                    timeout_s=timeout,
                    client=client,
                )
            finally:
                if client is not None:
                    client.close()
        finally:
            conn.close()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        if json_mode:
            render(
                {
                    "name": entry.name,
                    "model": entry.model,
                    "source": entry.source,
                    "provider": entry.provider,
                    "base_url": entry.base_url,
                    "api_key_env": entry.api_key_env,
                    "registered_at": entry.registered_at.isoformat(),
                },
                json_mode=True,
            )
        else:
            render(
                {
                    "status": "registered",
                    "name": entry.name,
                    "model": entry.model,
                    "source": entry.source,
                    "provider": entry.provider or "",
                    "base_url": entry.base_url or "",
                },
                json_mode=False,
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
                    }
                    for e in entries
                ],
                json_mode=True,
            )
        else:
            if entries:
                # Show max_tokens/timeout_s columns only if any LLM has them set
                has_config = any(
                    e.max_tokens is not None or e.timeout_s is not None for e in entries
                )
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
                    rows.append(row)
                render(rows, json_mode=False)
            else:
                render({"info": "No LLMs registered"}, json_mode=False)


@llm_app.command("remove")
def llm_remove(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the LLM to remove.")],
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

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        if json_mode:
            render({"name": name, "removed": True}, json_mode=True)
        else:
            render({"status": "removed", "name": name}, json_mode=False)
