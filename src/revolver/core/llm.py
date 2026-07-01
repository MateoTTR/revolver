"""Domain logic for LLM registration and lifecycle management.

Implements the six orchestration functions for ``revolver llm`` commands:
register, remove, start, stop, list, and status.

Traceable to: DES-002 section 5, FR-LLM-001..008.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
import sqlite3
import sys
from typing import Literal

from revolver.core.exceptions import (
    DuplicateNameError,
    OllamaNotRunningError,
    RevolverError,
    ValidationError,
)
from revolver.infra import db
from revolver.infra.gpu import GpuInfo, get_gpu_info
from revolver.infra.ollama import OllamaClient, normalize_ollama_url
from revolver.models.llm import (
    EnsembleEntry,
    EnsembleMember,
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

# Valid reasoning-effort levels (FR-LLM-026, ADR-007 Amendment A3.2). Ordered
# lowest→highest so callers that need the ranking (e.g. the ShinkaEvolve
# disagreement policy — pick the *highest* effort) can index into it.
_REASONING_EFFORT_LEVELS: tuple[str, ...] = ("min", "low", "medium", "high", "max")


def _validate_reasoning_effort(reasoning_effort: str | None) -> None:
    """Raise :class:`ValidationError` if *reasoning_effort* is not a valid level.

    ``None`` is always valid (means "provider default"). Any non-``None`` value
    must be one of :data:`_REASONING_EFFORT_LEVELS`.
    """
    if reasoning_effort is not None and reasoning_effort not in _REASONING_EFFORT_LEVELS:
        raise ValidationError(
            f"--reasoning-effort must be one of "
            f"{', '.join(_REASONING_EFFORT_LEVELS)} (got {reasoning_effort!r})"
        )


# ── resolve_llm_or_ensemble (S11-06) ──────────────────────────────────────


def resolve_llm_or_ensemble(
    name: str,
    conn: sqlite3.Connection,
) -> LLMEntry | EnsembleEntry:
    """Resolve a name to either a single LLM or an ensemble.

    Tries ``get_llm()`` first, then ``get_ensemble()`` + ``get_ensemble_members()``.
    Raises :class:`RevolverError` if neither is found.

    Args:
        name: The LLM or ensemble name to resolve.
        conn: A connection to the global database.

    Returns:
        An :class:`LLMEntry` if a single LLM matches, or an :class:`EnsembleEntry`
        if an ensemble matches.

    Raises:
        RevolverError: If neither an LLM nor an ensemble with *name* exists.
    """
    # Try single LLM first
    llm = db.get_llm(conn, name)
    if llm is not None:
        return llm

    # Try ensemble
    ensemble_row = db.get_ensemble(conn, name)
    if ensemble_row is not None:
        member_rows = db.get_ensemble_members(conn, name)
        members = [
            EnsembleMember(
                llm_name=str(m["llm_name"]),
                weight=float(m["weight"]),  # type: ignore[arg-type]
                temperature=(
                    float(m["temperature_override"])  # type: ignore[arg-type]
                    if m.get("temperature_override") is not None
                    else None
                ),
                max_tokens=(
                    int(str(m["max_tokens_override"]))
                    if m.get("max_tokens_override") is not None
                    else None
                ),
                reasoning_effort=(
                    str(m["reasoning_effort"]) if m.get("reasoning_effort") is not None else None
                ),
            )
            for m in member_rows
        ]
        return EnsembleEntry(
            name=str(ensemble_row["name"]),
            members=members,
            created_at=datetime.fromisoformat(str(ensemble_row["created_at"])),
        )

    raise RevolverError(f"LLM or ensemble '{name}' not found.")


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
    max_tokens: int | None = None,
    timeout_s: int | None = None,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    client: OllamaClient | None = None,
) -> LLMEntry:
    """Register a new LLM in the global database.

    For local (Ollama) LLMs: performs health check, optionally pulls the
    model, retrieves the digest, and sets the base URL. When ``base_url`` is
    omitted the URL defaults from ``OLLAMA_HOST`` (if set), else localhost.

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
        max_tokens: Maximum tokens per LLM response (injected into OE config).
        timeout_s: Request timeout in seconds (injected into OE config).
        temperature: Sampling temperature (0.0-2.0) injected into OE config.
        reasoning_effort: Reasoning-effort level (``min|low|medium|high|max``;
            ``None`` = provider default). Per-member on OpenEvolve; merged into
            a single global pool on ShinkaEvolve (FR-LLM-026, ADR-007 A3.2).
        client: OllamaClient instance (local only; created if not provided).

    Returns:
        The created :class:`LLMEntry`.

    Raises:
        DuplicateNameError: If an LLM with *name* already exists.
        OllamaNotRunningError: If Ollama is not reachable (local only).
        ValidationError: If required parameters are missing or invalid.
    """
    # Validate positive values for optional config
    if max_tokens is not None and max_tokens < 1:
        raise ValidationError("--max-tokens must be a positive integer")
    if timeout_s is not None and timeout_s < 1:
        raise ValidationError("--timeout must be a positive integer")
    if temperature is not None and (temperature < 0.0 or temperature > 2.0):
        raise ValidationError("--temperature must be between 0.0 and 2.0")
    _validate_reasoning_effort(reasoning_effort)

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

            # Always store the OpenAI-compat (/v1) form so OE's api_base and
            # Shinka's local/<model>@<url> embed both resolve, regardless of
            # the shape the user gave: normalize --base-url (root or /v1,
            # scheme-less or not), else OLLAMA_HOST, else localhost (#313).
            _, resolved_base_url = normalize_ollama_url(base_url or os.environ.get("OLLAMA_HOST"))
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
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        registered_at=datetime.now(UTC),
    )

    db.insert_llm(conn, entry)
    return entry


# ── update_llm ──────────────────────────────────────────────────────────


def update_llm(
    name: str,
    conn: sqlite3.Connection,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout_s: int | None = None,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> LLMEntry:
    """Update mutable fields of a registered LLM.

    Only fields with non-None values are updated; the rest remain unchanged.

    Args:
        name: LLM registry name.
        conn: Global database connection.
        model: New model identifier (e.g. ``gemini-2.5-flash-lite``).
        max_tokens: New value for maximum tokens per response.
        timeout_s: New value for request timeout in seconds.
        temperature: New value for sampling temperature (0.0-2.0).
        reasoning_effort: New reasoning-effort level
            (``min|low|medium|high|max``; FR-LLM-026, ADR-007 A3.2).

    Returns:
        The updated :class:`LLMEntry`.

    Raises:
        RevolverError: If the LLM is not found.
        ValidationError: If any provided value is not positive.
    """
    # Validate model is not empty
    if model is not None and not model.strip():
        raise ValidationError("--model must not be an empty string")

    # Validate positive values
    if max_tokens is not None and max_tokens < 1:
        raise ValidationError("--max-tokens must be a positive integer")
    if timeout_s is not None and timeout_s < 1:
        raise ValidationError("--timeout must be a positive integer")
    if temperature is not None and (temperature < 0.0 or temperature > 2.0):
        raise ValidationError("--temperature must be between 0.0 and 2.0")
    _validate_reasoning_effort(reasoning_effort)

    row_count = db.update_llm(
        conn,
        name,
        model=model,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )

    if row_count == 0:
        # Distinguish "no fields provided" from "LLM not found".
        # If existing is not None, row_count == 0 means all provided values
        # matched the current values (no actual change). This is unreachable
        # today because the CLI layer requires at least one update flag, but
        # we keep the guard for defensive robustness.
        existing = db.get_llm(conn, name)
        if existing is None:
            raise RevolverError(f"LLM '{name}' not found")

    # Return the updated entry
    entry = db.get_llm(conn, name)
    if entry is None:
        raise RevolverError(f"LLM '{name}' not found after update")
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


# ── Ensemble operations ───────────────────────────────────────────────────


def _build_ensemble_entry(
    ensemble_row: dict[str, object],
    member_rows: list[dict[str, object]],
) -> EnsembleEntry:
    """Construct an EnsembleEntry from raw DB rows.

    Maps DB column names (``temperature_override``, ``max_tokens_override``)
    to Pydantic field names (``temperature``, ``max_tokens``). The
    ``reasoning_effort`` column keeps its name across DB and model.
    """
    members = [
        EnsembleMember(
            llm_name=str(row["llm_name"]),
            weight=float(row["weight"]),  # type: ignore[arg-type]
            temperature=(
                float(row["temperature_override"])  # type: ignore[arg-type]
                if row["temperature_override"] is not None
                else None
            ),
            max_tokens=(
                int(row["max_tokens_override"])  # type: ignore[call-overload]
                if row["max_tokens_override"] is not None
                else None
            ),
            reasoning_effort=(
                str(row["reasoning_effort"]) if row.get("reasoning_effort") is not None else None
            ),
        )
        for row in member_rows
    ]
    return EnsembleEntry(
        name=str(ensemble_row["name"]),
        members=members,
        created_at=datetime.fromisoformat(str(ensemble_row["created_at"])),
    )


def create_ensemble(name: str, conn: sqlite3.Connection) -> EnsembleEntry:
    """Create a new empty ensemble in the global database.

    Args:
        name: Unique ensemble name.
        conn: Global database connection.

    Returns:
        The created :class:`EnsembleEntry`.

    Raises:
        DuplicateNameError: If an ensemble with *name* already exists.
    """
    now = datetime.now(UTC)
    db.insert_ensemble(conn, name, now)
    return EnsembleEntry(name=name, members=[], created_at=now)


def add_ensemble_member(
    ensemble_name: str,
    llm_name: str,
    weight: float,
    conn: sqlite3.Connection,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> None:
    """Add a member LLM to an ensemble.

    Validates that the LLM exists in the registry. After adding, checks the
    total weight sum and emits a warning to stderr if it deviates from 1.0.

    Args:
        ensemble_name: Name of the ensemble.
        llm_name: Name of the registered LLM to add.
        weight: Sampling weight for this member.
        conn: Global database connection.
        temperature: Optional per-member temperature override.
        max_tokens: Optional per-member max_tokens override.
        reasoning_effort: Optional per-member reasoning-effort override
            (``min|low|medium|high|max``). When set, it wins over the member
            LLM's registry-level ``reasoning_effort`` (same precedence as
            ``temperature``/``max_tokens``; FR-LLM-026, ADR-007 A3.2).

    Raises:
        RevolverError: If the ensemble or LLM is not found.
        ValidationError: If ``reasoning_effort`` is not a valid level.
        DuplicateNameError: If the LLM is already a member.
    """
    _validate_reasoning_effort(reasoning_effort)

    # Validate ensemble exists
    ensemble_row = db.get_ensemble(conn, ensemble_name)
    if ensemble_row is None:
        raise RevolverError(f"Ensemble '{ensemble_name}' not found")

    # Validate LLM exists in registry
    llm_entry = db.get_llm(conn, llm_name)
    if llm_entry is None:
        raise RevolverError(f"LLM '{llm_name}' not found")

    db.add_ensemble_member(
        conn,
        ensemble_name,
        llm_name,
        weight,
        temperature_override=temperature,
        max_tokens_override=max_tokens,
        reasoning_effort_override=reasoning_effort,
    )

    # Check weight sum and warn if not close to 1.0
    members = db.get_ensemble_members(conn, ensemble_name)
    total_weight = sum(float(m["weight"]) for m in members)  # type: ignore[arg-type, misc]
    if abs(total_weight - 1.0) > 0.01:
        print(
            f"Warning: ensemble '{ensemble_name}' total weight is "
            f"{total_weight:.2f} (expected ~1.0)",
            file=sys.stderr,
        )


def remove_ensemble(name: str, conn: sqlite3.Connection) -> None:
    """Remove an ensemble from the global database.

    CASCADE deletes all associated members.

    Args:
        name: Ensemble name.
        conn: Global database connection.

    Raises:
        RevolverError: If the ensemble is not found.
    """
    deleted = db.delete_ensemble(conn, name)
    if deleted == 0:
        raise RevolverError(f"Ensemble '{name}' not found")


def list_ensembles(conn: sqlite3.Connection) -> list[EnsembleEntry]:
    """List all ensembles with their members.

    Args:
        conn: Global database connection.

    Returns:
        A list of :class:`EnsembleEntry` instances sorted by name.
    """
    ensemble_rows = db.list_ensembles(conn)
    result: list[EnsembleEntry] = []
    for row in ensemble_rows:
        member_rows = db.get_ensemble_members(conn, str(row["name"]))
        result.append(_build_ensemble_entry(row, member_rows))
    return result


def get_ensemble_info(name: str, conn: sqlite3.Connection) -> EnsembleEntry:
    """Get detailed information about an ensemble.

    Args:
        name: Ensemble name.
        conn: Global database connection.

    Returns:
        The :class:`EnsembleEntry` with its members.

    Raises:
        RevolverError: If the ensemble is not found.
    """
    ensemble_row = db.get_ensemble(conn, name)
    if ensemble_row is None:
        raise RevolverError(f"Ensemble '{name}' not found")
    member_rows = db.get_ensemble_members(conn, name)
    return _build_ensemble_entry(ensemble_row, member_rows)
