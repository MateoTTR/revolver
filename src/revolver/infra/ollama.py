"""HTTP client for the Ollama REST API.

Wraps httpx.Client to provide typed access to Ollama endpoints for
listing, pulling, loading, and health-checking local LLM models.

Traceable to: ADR-001 (Ollama as local LLM backend), DES-002.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import json
import time
from typing import Any

import httpx

from revolver.core.exceptions import (
    ModelHealthCheckError,
    ModelLoadTimeoutError,
    ModelNotFoundError,
    ModelPullError,
    OllamaNotRunningError,
)

DEFAULT_OLLAMA_ROOT_URL = "http://localhost:11434"
"""Default root URL of a local Ollama server (native ``/api/*`` endpoints)."""


def normalize_ollama_url(url: str | None) -> tuple[str, str]:
    """Derive the root and OpenAI-compatible URLs for an Ollama endpoint.

    Ollama exposes two surfaces on the same host: the native REST API at the
    **root** (``http://host:11434``, used by ``/api/*`` probe calls) and the
    OpenAI-compatible API under **``/v1``** (``http://host:11434/v1``, used by
    OpenEvolve's ``api_base`` and Shinka's ``local/<model>@<url>`` embed).

    Given any of these forms, this returns both so the probe and the stored
    entry agree on the same host.

    Args:
        url: A base URL in either root or ``/v1`` form (a scheme-less value
            such as ``sirius:11434`` — as ``OLLAMA_HOST`` is often set — is
            treated as ``http://``), or ``None`` to use the local default
            (``http://localhost:11434``).

    Returns:
        ``(root_url, api_url)`` — *root_url* has any trailing ``/v1`` stripped;
        *api_url* always ends with ``/v1``. Both have trailing slashes removed.
    """
    base = (url or DEFAULT_OLLAMA_ROOT_URL).strip()
    # Ollama-native env vars (e.g. ``OLLAMA_HOST=sirius:11434``) are commonly
    # set scheme-less; default to ``http://`` so httpx can connect (#313).
    if "://" not in base:
        base = f"http://{base}"
    base = base.rstrip("/")
    root_url = base[: -len("/v1")].rstrip("/") if base.endswith("/v1") else base
    api_url = f"{root_url}/v1"
    return root_url, api_url


@dataclass
class LocalModel:
    """A model available in the local Ollama library."""

    name: str
    digest: str
    size_bytes: int
    modified_at: str


@dataclass
class ModelInfo:
    """Detailed information about a model from ``/api/show``."""

    family: str
    parameter_size: str
    quantization: str
    capabilities: list[str]
    digest: str


@dataclass
class RunningModel:
    """A model currently loaded in memory (from ``/api/ps``)."""

    name: str
    digest: str
    size_bytes: int
    size_vram: int
    expires_at: str


@dataclass
class PullProgress:
    """A single progress event emitted during ``/api/pull``."""

    status: str
    total: int | None
    completed: int | None


class OllamaClient:
    """Synchronous HTTP client for the Ollama REST API.

    Args:
        base_url: Root URL of the Ollama server (default ``http://localhost:11434``).
    """

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url
        self._client = httpx.Client(base_url=base_url, timeout=30.0)

    # ── Resource management ─────────────────────────────────────────────────

    def close(self) -> None:
        """Close the underlying httpx client and release resources."""
        self._client.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ── Health ───────────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Check whether the Ollama server is reachable (``GET /``).

        Returns:
            ``True`` if the server responds with HTTP 200.
            ``False`` if the server responds with a non-200 status code.

        Raises:
            OllamaNotRunningError: If the server cannot be reached at all
                (connection refused / timeout).
        """
        try:
            resp = self._client.get("/")
            return resp.status_code == 200
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc

    def version(self) -> str:
        """Return the Ollama server version string (``GET /api/version``)."""
        try:
            resp = self._client.get("/api/version")
            resp.raise_for_status()
            return str(resp.json()["version"])
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc

    # ── Model management ─────────────────────────────────────────────────────

    def list_local_models(self) -> list[LocalModel]:
        """List all locally available models (``GET /api/tags``)."""
        try:
            resp = self._client.get("/api/tags")
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc

        models_data: list[dict[str, Any]] = resp.json().get("models", [])
        return [
            LocalModel(
                name=str(m["name"]),
                digest=str(m["digest"]),
                size_bytes=int(m["size"]),
                modified_at=str(m["modified_at"]),
            )
            for m in models_data
        ]

    def show_model(self, name: str) -> ModelInfo:
        """Get detailed information about a model (``POST /api/show``).

        Raises:
            ModelNotFoundError: If the model is not found locally.
        """
        try:
            resp = self._client.post("/api/show", json={"name": name})
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc

        if resp.status_code == 404:
            raise ModelNotFoundError(f"Model '{name}' not found locally")

        resp.raise_for_status()
        data = resp.json()
        details: dict[str, Any] = data.get("details", {})
        model_info = data.get("model_info", {})

        # Extract capabilities from model_info if available
        capabilities: list[str] = []
        if isinstance(model_info, dict):
            # Ollama reports capabilities in the model_info block
            for key in model_info:
                if "capabilities" in key.lower():
                    val = model_info[key]
                    if isinstance(val, list):
                        capabilities = [str(c) for c in val]

        return ModelInfo(
            family=str(details.get("family", "")),
            parameter_size=str(details.get("parameter_size", "")),
            quantization=str(details.get("quantization_level", "")),
            capabilities=capabilities,
            digest=str(data.get("digest", "")),
        )

    def pull_model(self, name: str, stream: bool = True) -> Iterator[PullProgress]:
        """Pull a model from the Ollama registry (``POST /api/pull``).

        Yields:
            PullProgress events as they arrive.

        Raises:
            ModelPullError: If the pull fails.
        """
        try:
            if stream:
                with self._client.stream(
                    "POST", "/api/pull", json={"name": name, "stream": True}, timeout=None
                ) as resp:
                    if resp.status_code >= 400:
                        raise ModelPullError(
                            f"Failed to pull model '{name}': HTTP {resp.status_code}"
                        )
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        status = str(data.get("status", ""))
                        if "error" in data:
                            raise ModelPullError(f"Failed to pull model '{name}': {data['error']}")
                        yield PullProgress(
                            status=status,
                            total=data.get("total"),
                            completed=data.get("completed"),
                        )
            else:
                resp = self._client.post(
                    "/api/pull", json={"name": name, "stream": False}, timeout=None
                )
                if resp.status_code >= 400:
                    raise ModelPullError(f"Failed to pull model '{name}': HTTP {resp.status_code}")
                data = resp.json()
                if "error" in data:
                    raise ModelPullError(f"Failed to pull model '{name}': {data['error']}")
                yield PullProgress(
                    status=str(data.get("status", "success")),
                    total=None,
                    completed=None,
                )
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc

    def delete_model(self, name: str) -> None:
        """Delete a model from the local library (``DELETE /api/delete``)."""
        try:
            resp = self._client.request("DELETE", "/api/delete", json={"name": name})
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc

        if resp.status_code == 404:
            raise ModelNotFoundError(f"Model '{name}' not found locally")
        resp.raise_for_status()

    # ── Runtime ──────────────────────────────────────────────────────────────

    def list_running(self) -> list[RunningModel]:
        """List currently loaded/running models (``GET /api/ps``)."""
        try:
            resp = self._client.get("/api/ps")
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc

        models_data: list[dict[str, Any]] = resp.json().get("models", [])
        return [
            RunningModel(
                name=str(m["name"]),
                digest=str(m["digest"]),
                size_bytes=int(m["size"]),
                size_vram=int(m["size_vram"]),
                expires_at=str(m["expires_at"]),
            )
            for m in models_data
        ]

    def load_model(self, name: str) -> None:
        """Load a model into memory with infinite keep-alive (``POST /api/chat``).

        Uses ``keep_alive=-1`` to prevent automatic unloading.
        """
        try:
            resp = self._client.post(
                "/api/chat",
                json={"model": name, "keep_alive": -1, "messages": []},
            )
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc

    def unload_model(self, name: str) -> None:
        """Unload a model from memory (``POST /api/chat`` with ``keep_alive=0``)."""
        try:
            resp = self._client.post(
                "/api/chat",
                json={"model": name, "keep_alive": 0, "messages": []},
            )
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc

    def wait_loaded(self, name: str, timeout_s: int = 120) -> RunningModel:
        """Poll ``/api/ps`` until the model appears as loaded.

        Args:
            name: Model name to wait for.
            timeout_s: Maximum seconds to wait before raising.

        Raises:
            ModelLoadTimeoutError: If the model does not appear within *timeout_s*.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            running = self.list_running()
            for m in running:
                if m.name == name:
                    return m
            time.sleep(1.0)
        raise ModelLoadTimeoutError(f"Model '{name}' did not load within {timeout_s}s")

    def health_prompt(self, name: str) -> bool:
        """Send a trivial prompt to verify the model can generate (``POST /api/chat``).

        Returns:
            ``True`` if the model responds successfully.

        Raises:
            ModelHealthCheckError: If the model fails to respond.
        """
        try:
            resp = self._client.post(
                "/api/chat",
                json={
                    "model": name,
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": False,
                },
            )
            if resp.status_code >= 400:
                raise ModelHealthCheckError(
                    f"Health check failed for model '{name}': HTTP {resp.status_code}"
                )
            return True
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc
