"""Pydantic models for LLM registry data.

Frozen (immutable) models used across the ``revolver llm`` command group
and the global SQLite database.

Traceable to: DES-002, FR-LLM-001..008.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LLMEntry(BaseModel):
    """A registered LLM in the global database.

    Attributes:
        name: Unique user-chosen identifier (e.g. ``"codestral-local"``).
        provider: Optional provider hint (``"anthropic"``, ``"openai"``, etc.).
        model: Actual model identifier (e.g. ``"codestral:22b"``).
        source: ``"local"`` for Ollama-managed or ``"remote"`` for API-based.
        base_url: OpenAI-compatible endpoint URL.
        api_key_env: Name of the environment variable holding the API key.
        input_cost_per_mtok: Cost per million input tokens (USD).
        output_cost_per_mtok: Cost per million output tokens (USD).
        max_tokens: Maximum tokens per LLM response (injected into OE config).
        timeout_s: Request timeout in seconds (injected into OE config).
        temperature: Sampling temperature (0.0-2.0) injected into OE config.
        registered_at: Timestamp of registration.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    provider: str | None = None
    model: str
    source: Literal["local", "remote"]
    base_url: str | None = None
    api_key_env: str | None = None
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None
    max_tokens: int | None = None
    timeout_s: int | None = None
    temperature: float | None = None
    registered_at: datetime


class LLMStatus(BaseModel):
    """Runtime status of a registered LLM.

    Attributes:
        name: LLM registry name.
        source: ``"local"`` or ``"remote"``.
        status: One of ``"loaded"``, ``"stopped"``, ``"unavailable"``,
                ``"ready"``, ``"unconfigured"``.
        vram_mib: VRAM occupied in MiB (local models only).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    source: Literal["local", "remote"]
    status: Literal["loaded", "stopped", "unavailable", "ready", "unconfigured"]
    vram_mib: int | None = None


class StartResult(BaseModel):
    """Result of loading a local model into GPU memory.

    Attributes:
        name: LLM registry name.
        model: Actual model identifier.
        vram_mib: VRAM occupied after loading (MiB).
        health_ok: Whether the health prompt succeeded.
        previous_unloaded: Name of the model unloaded to make room, if any.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    model: str
    vram_mib: int | None = None
    health_ok: bool = False
    previous_unloaded: str | None = None


class StopResult(BaseModel):
    """Result of unloading a local model from GPU memory.

    Attributes:
        name: LLM registry name.
        model: Actual model identifier.
        was_loaded: Whether the model was actually loaded before stopping.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    model: str
    was_loaded: bool = True


class EnsembleMember(BaseModel):
    """A member of an LLM ensemble.

    Attributes:
        llm_name: Name of the registered LLM.
        weight: Sampling weight for this member (default 1.0).
        temperature: Optional per-member temperature override.
        max_tokens: Optional per-member max_tokens override.
    """

    model_config = ConfigDict(frozen=True)

    llm_name: str
    weight: float = 1.0
    temperature: float | None = None
    max_tokens: int | None = None


class EnsembleEntry(BaseModel):
    """A named LLM ensemble stored in the global registry.

    Attributes:
        name: Unique ensemble name.
        members: List of ensemble member configurations.
        created_at: Timestamp of registration.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    members: list[EnsembleMember]
    created_at: datetime


class LLMStatusReport(BaseModel):
    """Aggregated status report for ``revolver llm status``.

    Attributes:
        llms: Per-LLM status entries.
        gpu: GPU information dict (name, vram_used_mib, vram_total_mib) or ``None``.
        ollama_running: Whether the Ollama daemon is reachable.
    """

    model_config = ConfigDict(frozen=True)

    llms: list[LLMStatus]
    gpu: dict[str, int | str] | None = None
    ollama_running: bool = False
