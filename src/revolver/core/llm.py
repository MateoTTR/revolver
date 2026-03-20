"""Domain logic for LLM registration and lifecycle management.

Implements the six orchestration functions for ``revolver llm`` commands:
register, remove, start, stop, list, and status.

Traceable to: DES-002 section 5, FR-LLM-001..008.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
import sqlite3
from typing import Literal

from revolver.core.exceptions import (
    DuplicateNameError,
    OllamaNotRunningError,
    RevolverError,
    ValidationError,
)
from revolver.infra import db
from revolver.infra.gpu import GpuInfo, get_gpu_info
from revolver.infra.ollama import OllamaClient
from revolver.models.llm import (
    LLMEntry,
    LLMStatus,
    LLMStatusReport,
    StartResult,
    StopResult,
)

# ── Provider base-URL defaults ──────────────────────────────────────────────

_PROVIDER_BASE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com/v1",
    "openai": "https://api.openai.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
}

_KNOWN_PROVIDERS = {"anthropic", "openai", "google", "openai-compat"}


def _ensure_client(client: OllamaClient | None) -> tuple[OllamaClient, bool]:
    """Return a guaranteed non-None client and whether we own it.

    If *client* is ``None``, a default OllamaClient is created and the
    caller is responsible for closing it (``own=True``).
    """
    if client is not None:
        return client, False
    return OllamaClient(), True


# ── register_llm ────────────────────────────────────────────────────────────


def register_llm(
    name: str,
    model: str,
    conn: sqlite3.Connection,
    *,
    source: Literal["local", "remote"] = "remote",
    provider: str | None = None,
    api_key_env: str | None = None,
    base_url: str | None = None,
    pull: bool = False,
    input_cost_per_mtok: float | None = None,
    output_cost_per_mtok: float | None = None,
    max_tokens: int | None = None,
    timeout_s: int | None = None,
    client: OllamaClient | None = None,
) -> LLMEntry:
    """Register a new LLM in the global database.

    For local (Ollama) LLMs: performs health check, optionally pulls the
    model, retrieves the digest, and sets the base URL to localhost.

    For remote LLMs: validates the provider and API key env var, sets
    the default base URL per provider.

    Args:
        name: Unique user-chosen identifier.
        model: Actual model identifier (e.g. ``"codestral:22b"``).
        conn: Global database connection.
        source: ``"local"`` for Ollama or ``"remote"`` for API.
        provider: Provider hint (``"anthropic"``, ``"openai"``, etc.).
        api_key_env: Name of the environment variable holding the API key.
        base_url: Override for the OpenAI-compatible endpoint URL.
        pull: Whether to pull the model from Ollama registry (local only).
        input_cost_per_mtok: Cost per million input tokens (USD).
        output_cost_per_mtok: Cost per million output tokens (USD).
        max_tokens: Maximum tokens per LLM response (injected into OE config).
        timeout_s: Request timeout in seconds (injected into OE config).
        client: OllamaClient instance (local only; created if not provided).

    Returns:
        The created :class:`LLMEntry`.

    Raises:
        DuplicateNameError: If an LLM with *name* already exists.
        OllamaNotRunningError: If Ollama is not reachable (local only).
        ValidationError: If required parameters are missing or invalid.
    """
    # Check uniqueness
    existing = db.get_llm(conn, name)
    if existing is not None:
        raise DuplicateNameError(f"An LLM named '{name}' already exists")

    resolved_base_url = base_url

    if source == "local":
        # Local (Ollama) path
        resolved_provider = provider or "ollama"
        oc, own = _ensure_client(client)
        try:
            oc.health_check()

            if pull:
                # Consume the pull generator to completion
                for _progress in oc.pull_model(model, stream=False):
                    pass

            # Get digest via show_model
            oc.show_model(model)

            # Set base_url to Ollama's OpenAI-compat endpoint
            if resolved_base_url is None:
                resolved_base_url = "http://localhost:11434/v1"
        finally:
            if own:
                oc.close()

    else:
        # Remote path
        if provider is None:
            raise ValidationError(
                "Provider is required for remote LLMs. "
                "Use --provider (anthropic, openai, google, openai-compat)."
            )
        if provider not in _KNOWN_PROVIDERS:
            raise ValidationError(
                f"Unknown provider '{provider}'. "
                f"Known providers: {', '.join(sorted(_KNOWN_PROVIDERS))}"
            )
        if api_key_env is None:
            raise ValidationError(
                "API key environment variable is required for remote LLMs. Use --api-key-env."
            )
        if provider == "openai-compat" and base_url is None:
            raise ValidationError(
                "Base URL is required for openai-compat provider. Use --base-url."
            )

        resolved_provider = provider

        # Set default base_url per provider if not overridden
        if resolved_base_url is None:
            resolved_base_url = _PROVIDER_BASE_URLS.get(provider)

    entry = LLMEntry(
        name=name,
        provider=resolved_provider,
        model=model,
        source=source,
        base_url=resolved_base_url,
        api_key_env=api_key_env,
        input_cost_per_mtok=input_cost_per_mtok,
        output_cost_per_mtok=output_cost_per_mtok,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        registered_at=datetime.now(UTC),
    )

    db.insert_llm(conn, entry)
    return entry


# ── remove_llm ──────────────────────────────────────────────────────────────


def remove_llm(
    name: str,
    conn: sqlite3.Connection,
    *,
    delete_model: bool = False,
    client: OllamaClient | None = None,
) -> None:
    """Remove a registered LLM from the global database.

    For local models with ``delete_model=True``, also deletes the model
    files from Ollama and unloads it if currently loaded.

    Args:
        name: LLM registry name.
        conn: Global database connection.
        delete_model: If True and source is local, delete from Ollama too.
        client: OllamaClient instance (created if not provided and needed).

    Raises:
        RevolverError: If the LLM is not found.
    """
    entry = db.get_llm(conn, name)
    if entry is None:
        raise RevolverError(f"LLM '{name}' not found")

    if entry.source == "local" and delete_model:
        oc, own = _ensure_client(client)
        try:
            try:
                oc.health_check()
                # Check if loaded and unload
                running = oc.list_running()
                for m in running:
                    if m.name == entry.model:
                        oc.unload_model(entry.model)
                        break
                # Delete the model files
                oc.delete_model(entry.model)
            except OllamaNotRunningError:
                # Ollama not running -- skip Ollama operations, just remove from DB
                pass
        finally:
            if own:
                oc.close()

    db.delete_llm(conn, name)


# ── start_llm ───────────────────────────────────────────────────────────────


def start_llm(
    name: str,
    conn: sqlite3.Connection,
    *,
    timeout: int = 120,
    client: OllamaClient | None = None,
) -> StartResult:
    """Load a local LLM into GPU memory via Ollama.

    Enforces single-model loading (FR-LLM-008): if another model is
    already loaded, it will be unloaded first.

    Args:
        name: LLM registry name.
        conn: Global database connection.
        timeout: Seconds to wait for model to finish loading.
        client: OllamaClient instance (created if not provided).

    Returns:
        A :class:`StartResult` with VRAM usage and health status.

    Raises:
        RevolverError: If the LLM is not found.
        ValidationError: If the LLM is not a local model.
        OllamaNotRunningError: If Ollama is not reachable.
    """
    entry = db.get_llm(conn, name)
    if entry is None:
        raise RevolverError(f"LLM '{name}' not found")

    if entry.source != "local":
        raise ValidationError(
            f"LLM '{name}' is a remote model (source='{entry.source}'). "
            "Only local (Ollama) models can be started."
        )

    oc, own = _ensure_client(client)
    try:
        oc.health_check()

        # Single-model enforcement: unload any other loaded model
        previous_unloaded: str | None = None
        running = oc.list_running()
        for m in running:
            if m.name != entry.model:
                oc.unload_model(m.name)
                previous_unloaded = m.name

        # Load the model
        oc.load_model(entry.model)

        # Wait for it to appear in /api/ps
        loaded = oc.wait_loaded(entry.model, timeout_s=timeout)

        # Health-check prompt
        health_ok = oc.health_prompt(entry.model)

        # Read VRAM from the loaded model info
        vram_mib: int | None = None
        if loaded.size_vram > 0:
            vram_mib = loaded.size_vram // (1024 * 1024)

        return StartResult(
            name=name,
            model=entry.model,
            vram_mib=vram_mib,
            health_ok=health_ok,
            previous_unloaded=previous_unloaded,
        )
    finally:
        if own:
            oc.close()


# ── stop_llm ────────────────────────────────────────────────────────────────


def stop_llm(
    conn: sqlite3.Connection,
    *,
    name: str | None = None,
    client: OllamaClient | None = None,
) -> StopResult:
    """Unload a local LLM from GPU memory.

    If *name* is given, validates it's the loaded model. If *name* is
    ``None``, unloads whatever model is currently loaded.

    Args:
        conn: Global database connection.
        name: Optional LLM registry name. If None, stops the current model.
        client: OllamaClient instance (created if not provided).

    Returns:
        A :class:`StopResult` indicating whether a model was unloaded.

    Raises:
        OllamaNotRunningError: If Ollama is not reachable.
        RevolverError: If *name* is specified but not found in DB.
    """
    oc, own = _ensure_client(client)
    try:
        oc.health_check()
        running = oc.list_running()

        if name is not None:
            # Validate it exists in DB
            entry = db.get_llm(conn, name)
            if entry is None:
                raise RevolverError(f"LLM '{name}' not found")
            target_model = entry.model
            target_name = name
        elif running:
            # Use whatever is loaded; try to find it in DB
            target_model = running[0].name
            target_name = target_model
            # Try to find a DB entry matching this model
            all_llms = db.list_llms(conn)
            for llm in all_llms:
                if llm.model == target_model:
                    target_name = llm.name
                    break
        else:
            # Nothing loaded
            return StopResult(name="", model="", was_loaded=False)

        # Check if the target model is actually loaded
        is_loaded = any(m.name == target_model for m in running)

        if not is_loaded:
            return StopResult(name=target_name, model=target_model, was_loaded=False)

        oc.unload_model(target_model)
        return StopResult(name=target_name, model=target_model, was_loaded=True)
    finally:
        if own:
            oc.close()


# ── list_llms ───────────────────────────────────────────────────────────────


def list_llms(conn: sqlite3.Connection) -> list[LLMEntry]:
    """List all registered LLMs from the global database.

    Args:
        conn: Global database connection.

    Returns:
        A list of :class:`LLMEntry` instances sorted by name.
    """
    return db.list_llms(conn)


# ── get_llm_status ──────────────────────────────────────────────────────────


def get_llm_status(
    conn: sqlite3.Connection,
    *,
    loaded_only: bool = False,
    client: OllamaClient | None = None,
) -> LLMStatusReport:
    """Build a status report for all registered LLMs.

    Cross-references the database with Ollama runtime state and GPU info.
    For remote LLMs, checks whether the ``api_key_env`` is set.

    Args:
        conn: Global database connection.
        loaded_only: If True, only include currently loaded models.
        client: OllamaClient instance (created if not provided).

    Returns:
        A :class:`LLMStatusReport` with per-LLM status and GPU info.
    """
    all_entries = db.list_llms(conn)

    # Check Ollama status
    ollama_running = False
    running_models: dict[str, int] = {}  # model name -> vram bytes

    oc, own = _ensure_client(client)
    try:
        try:
            oc.health_check()
            ollama_running = True
            running = oc.list_running()
            for m in running:
                running_models[m.name] = m.size_vram
        except OllamaNotRunningError:
            pass
    finally:
        if own:
            oc.close()

    # Get GPU info
    gpu_info: GpuInfo | None = get_gpu_info()
    gpu_dict: dict[str, int | str] | None = None
    if gpu_info is not None:
        gpu_dict = {
            "name": gpu_info.name,
            "vram_used_mib": gpu_info.vram_used_mib,
            "vram_total_mib": gpu_info.vram_total_mib,
        }

    # Build per-LLM status
    statuses: list[LLMStatus] = []
    for entry in all_entries:
        if entry.source == "local":
            if entry.model in running_models:
                vram_bytes = running_models[entry.model]
                vram_mib = vram_bytes // (1024 * 1024) if vram_bytes > 0 else None
                status = LLMStatus(
                    name=entry.name,
                    source=entry.source,
                    status="loaded",
                    vram_mib=vram_mib,
                )
            elif ollama_running:
                status = LLMStatus(
                    name=entry.name,
                    source=entry.source,
                    status="stopped",
                )
            else:
                status = LLMStatus(
                    name=entry.name,
                    source=entry.source,
                    status="unavailable",
                )
        else:
            # Remote LLM: check if api_key_env is set in environment
            if entry.api_key_env and os.environ.get(entry.api_key_env):
                status = LLMStatus(
                    name=entry.name,
                    source=entry.source,
                    status="ready",
                )
            else:
                status = LLMStatus(
                    name=entry.name,
                    source=entry.source,
                    status="unconfigured",
                )

        if loaded_only and status.status != "loaded":
            continue
        statuses.append(status)

    return LLMStatusReport(
        llms=statuses,
        gpu=gpu_dict,
        ollama_running=ollama_running,
    )
