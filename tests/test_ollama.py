"""L1 unit tests for revolver.infra.ollama — OllamaClient HTTP client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from revolver.core.exceptions import (
    ModelHealthCheckError,
    ModelLoadTimeoutError,
    ModelNotFoundError,
    ModelPullError,
    OllamaNotRunningError,
)
from revolver.infra.ollama import (
    DEFAULT_OLLAMA_ROOT_URL,
    LocalModel,
    ModelInfo,
    OllamaClient,
    PullProgress,
    RunningModel,
    normalize_ollama_url,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_response(
    status_code: int = 200,
    json_data: object = None,
) -> httpx.Response:
    """Build a fake httpx.Response with the given status and JSON body."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "http://test"),
    )
    return resp


# ── Health ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_health_check_ok() -> None:
    """health_check returns True when Ollama responds 200."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.return_value = _mock_response(200)

    assert client.health_check() is True
    client._client.get.assert_called_once_with("/")


@pytest.mark.unit
def test_health_check_connect_error() -> None:
    """health_check raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        client.health_check()


@pytest.mark.unit
def test_version_ok() -> None:
    """version() returns the version string from /api/version."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.return_value = _mock_response(200, {"version": "0.6.2"})

    assert client.version() == "0.6.2"
    client._client.get.assert_called_once_with("/api/version")


@pytest.mark.unit
def test_version_connect_error() -> None:
    """version() raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        client.version()


# ── Model management ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_local_models() -> None:
    """list_local_models returns a list of LocalModel from /api/tags."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.return_value = _mock_response(
        200,
        {
            "models": [
                {
                    "name": "codestral:22b",
                    "digest": "sha256:abc123",
                    "size": 12345678,
                    "modified_at": "2026-01-15T10:00:00Z",
                },
                {
                    "name": "llama3:8b",
                    "digest": "sha256:def456",
                    "size": 87654321,
                    "modified_at": "2026-01-16T11:00:00Z",
                },
            ]
        },
    )

    models = client.list_local_models()
    assert len(models) == 2
    assert isinstance(models[0], LocalModel)
    assert models[0].name == "codestral:22b"
    assert models[0].digest == "sha256:abc123"
    assert models[0].size_bytes == 12345678
    assert models[1].name == "llama3:8b"


@pytest.mark.unit
def test_list_local_models_empty() -> None:
    """list_local_models returns empty list when no models exist."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.return_value = _mock_response(200, {"models": []})

    models = client.list_local_models()
    assert models == []


@pytest.mark.unit
def test_list_local_models_connect_error() -> None:
    """list_local_models raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        client.list_local_models()


@pytest.mark.unit
def test_show_model_ok() -> None:
    """show_model returns ModelInfo with parsed details."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.return_value = _mock_response(
        200,
        {
            "details": {
                "family": "llama",
                "parameter_size": "22B",
                "quantization_level": "Q4_K_M",
            },
            "model_info": {},
            "digest": "sha256:abc123",
        },
    )

    info = client.show_model("codestral:22b")
    assert isinstance(info, ModelInfo)
    assert info.family == "llama"
    assert info.parameter_size == "22B"
    assert info.quantization == "Q4_K_M"
    assert info.digest == "sha256:abc123"
    client._client.post.assert_called_once_with("/api/show", json={"name": "codestral:22b"})


@pytest.mark.unit
def test_show_model_not_found() -> None:
    """show_model raises ModelNotFoundError on HTTP 404."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.return_value = _mock_response(404)

    with pytest.raises(ModelNotFoundError, match="not found"):
        client.show_model("nonexistent:latest")


@pytest.mark.unit
def test_show_model_connect_error() -> None:
    """show_model raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        client.show_model("codestral:22b")


@pytest.mark.unit
def test_pull_model_no_stream() -> None:
    """pull_model with stream=False yields a single PullProgress."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.return_value = _mock_response(200, {"status": "success"})

    events = list(client.pull_model("llama3:8b", stream=False))
    assert len(events) == 1
    assert isinstance(events[0], PullProgress)
    assert events[0].status == "success"


@pytest.mark.unit
def test_pull_model_http_error() -> None:
    """pull_model raises ModelPullError on HTTP error (non-stream)."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.return_value = _mock_response(500)

    with pytest.raises(ModelPullError, match="HTTP 500"):
        list(client.pull_model("bad-model", stream=False))


@pytest.mark.unit
def test_pull_model_error_in_response() -> None:
    """pull_model raises ModelPullError when response contains 'error' key."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.return_value = _mock_response(200, {"error": "model not found"})

    with pytest.raises(ModelPullError, match="model not found"):
        list(client.pull_model("bad-model", stream=False))


@pytest.mark.unit
def test_pull_model_connect_error() -> None:
    """pull_model raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        list(client.pull_model("llama3:8b", stream=False))


@pytest.mark.unit
def test_delete_model_ok() -> None:
    """delete_model calls DELETE /api/delete."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.request.return_value = _mock_response(200)

    client.delete_model("codestral:22b")
    client._client.request.assert_called_once_with(
        "DELETE", "/api/delete", json={"name": "codestral:22b"}
    )


@pytest.mark.unit
def test_delete_model_not_found() -> None:
    """delete_model raises ModelNotFoundError on 404."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.request.return_value = _mock_response(404)

    with pytest.raises(ModelNotFoundError, match="not found"):
        client.delete_model("nonexistent:latest")


@pytest.mark.unit
def test_delete_model_connect_error() -> None:
    """delete_model raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.request.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        client.delete_model("codestral:22b")


# ── Runtime ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_running() -> None:
    """list_running returns a list of RunningModel from /api/ps."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.return_value = _mock_response(
        200,
        {
            "models": [
                {
                    "name": "codestral:22b",
                    "digest": "sha256:abc123",
                    "size": 12345678,
                    "size_vram": 12000000,
                    "expires_at": "2026-01-15T12:00:00Z",
                }
            ]
        },
    )

    running = client.list_running()
    assert len(running) == 1
    assert isinstance(running[0], RunningModel)
    assert running[0].name == "codestral:22b"
    assert running[0].size_vram == 12000000


@pytest.mark.unit
def test_list_running_connect_error() -> None:
    """list_running raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        client.list_running()


@pytest.mark.unit
def test_load_model_ok() -> None:
    """load_model sends POST /api/chat with keep_alive=-1."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.return_value = _mock_response(200)

    client.load_model("codestral:22b")
    client._client.post.assert_called_once_with(
        "/api/chat",
        json={"model": "codestral:22b", "keep_alive": -1, "messages": []},
    )


@pytest.mark.unit
def test_load_model_connect_error() -> None:
    """load_model raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        client.load_model("codestral:22b")


@pytest.mark.unit
def test_unload_model_ok() -> None:
    """unload_model sends POST /api/chat with keep_alive=0."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.return_value = _mock_response(200)

    client.unload_model("codestral:22b")
    client._client.post.assert_called_once_with(
        "/api/chat",
        json={"model": "codestral:22b", "keep_alive": 0, "messages": []},
    )


@pytest.mark.unit
def test_unload_model_connect_error() -> None:
    """unload_model raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        client.unload_model("codestral:22b")


@pytest.mark.unit
def test_wait_loaded_immediate() -> None:
    """wait_loaded returns immediately when model is already loaded."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.return_value = _mock_response(
        200,
        {
            "models": [
                {
                    "name": "codestral:22b",
                    "digest": "sha256:abc",
                    "size": 100,
                    "size_vram": 100,
                    "expires_at": "2026-01-15T12:00:00Z",
                }
            ]
        },
    )

    result = client.wait_loaded("codestral:22b", timeout_s=5)
    assert isinstance(result, RunningModel)
    assert result.name == "codestral:22b"


@pytest.mark.unit
def test_wait_loaded_timeout() -> None:
    """wait_loaded raises ModelLoadTimeoutError when model never appears."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get.return_value = _mock_response(200, {"models": []})

    with patch("revolver.infra.ollama.time") as mock_time:
        # Simulate time advancing past deadline immediately.
        mock_time.monotonic.side_effect = [0.0, 999.0]
        mock_time.sleep = MagicMock()

        with pytest.raises(ModelLoadTimeoutError, match="did not load"):
            client.wait_loaded("codestral:22b", timeout_s=5)


@pytest.mark.unit
def test_health_prompt_ok() -> None:
    """health_prompt returns True on successful response."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.return_value = _mock_response(
        200,
        {
            "message": {"role": "assistant", "content": "pong"},
        },
    )

    assert client.health_prompt("codestral:22b") is True
    client._client.post.assert_called_once_with(
        "/api/chat",
        json={
            "model": "codestral:22b",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
        },
    )


@pytest.mark.unit
def test_health_prompt_failure() -> None:
    """health_prompt raises ModelHealthCheckError on HTTP error."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.return_value = _mock_response(500)

    with pytest.raises(ModelHealthCheckError, match="Health check failed"):
        client.health_prompt("codestral:22b")


@pytest.mark.unit
def test_health_prompt_connect_error() -> None:
    """health_prompt raises OllamaNotRunningError on connection failure."""
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post.side_effect = httpx.ConnectError("refused")

    with pytest.raises(OllamaNotRunningError):
        client.health_prompt("codestral:22b")


# ── normalize_ollama_url (S16a-01, #313) ──────────────────────────────────────


@pytest.mark.unit
def test_normalize_ollama_url_root_form() -> None:
    """A root URL keeps its host for the probe and gains /v1 for the API."""
    root, api = normalize_ollama_url("http://sirius:11434")
    assert root == "http://sirius:11434"
    assert api == "http://sirius:11434/v1"


@pytest.mark.unit
def test_normalize_ollama_url_v1_form() -> None:
    """A /v1 URL is stripped to the root for the probe; the API form is kept."""
    root, api = normalize_ollama_url("http://sirius:11434/v1")
    assert root == "http://sirius:11434"
    assert api == "http://sirius:11434/v1"


@pytest.mark.unit
def test_normalize_ollama_url_none_defaults_localhost() -> None:
    """None falls back to the local default for both forms."""
    root, api = normalize_ollama_url(None)
    assert root == DEFAULT_OLLAMA_ROOT_URL
    assert root == "http://localhost:11434"
    assert api == "http://localhost:11434/v1"


@pytest.mark.unit
def test_normalize_ollama_url_strips_trailing_slash() -> None:
    """Trailing slashes are normalized away in both forms."""
    root, api = normalize_ollama_url("http://sirius:11434/v1/")
    assert root == "http://sirius:11434"
    assert api == "http://sirius:11434/v1"

    root2, api2 = normalize_ollama_url("http://sirius:11434/")
    assert root2 == "http://sirius:11434"
    assert api2 == "http://sirius:11434/v1"


@pytest.mark.unit
def test_normalize_ollama_url_schemeless_defaults_http() -> None:
    """A scheme-less host (as OLLAMA_HOST is often set) defaults to http://."""
    root, api = normalize_ollama_url("sirius:11434")
    assert root == "http://sirius:11434"
    assert api == "http://sirius:11434/v1"

    # Scheme-less /v1 form is handled too.
    root2, api2 = normalize_ollama_url("sirius:11434/v1")
    assert root2 == "http://sirius:11434"
    assert api2 == "http://sirius:11434/v1"
