"""L2 integration tests for ``revolver llm`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner, mocking the
Ollama client at the infra boundary and using a temporary global database.

Traceable to: val-integration-tests.md section 2.2.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.infra.db import get_global_db_at, list_llms
from revolver.infra.ollama import ModelInfo, PullProgress, RunningModel

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _get_all_output(result: object) -> str:
    """Combine stdout and stderr from a CliRunner result."""
    parts: list[str] = []
    for attr in ("stdout", "stderr", "output"):
        val = getattr(result, attr, None)
        if val:
            parts.append(val)
    return _strip_ansi("".join(parts))


def _query_llms(db_path: Path) -> list[object]:
    """Open a fresh connection to the DB and list all LLMs."""
    conn = get_global_db_at(db_path)
    try:
        return list_llms(conn)
    finally:
        conn.close()


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def global_db_path(tmp_path: Path) -> Path:
    """Return the path for a temporary global database.

    Also initializes the schema by opening and closing a connection once.
    """
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    conn.close()
    return db_path


@pytest.fixture()
def mock_global_db(
    global_db_path: Path,
) -> Generator[Path, None, None]:
    """Patch get_global_db so the CLI opens new connections to our temp DB.

    Each CLI command call gets a fresh connection to the same temp file,
    so closing it in the command's ``finally`` block does not break the test.
    """
    with patch(
        "revolver.cli.llm.get_global_db",
        side_effect=lambda: get_global_db_at(global_db_path),
    ):
        yield global_db_path


def _make_ollama_client_mock(
    *,
    health_ok: bool = True,
    running_models: list[RunningModel] | None = None,
) -> MagicMock:
    """Create a mock OllamaClient with configurable responses."""
    mock = MagicMock()
    mock.health_check.return_value = health_ok

    mock.list_local_models.return_value = []

    mock.show_model.return_value = ModelInfo(
        family="llama",
        parameter_size="22B",
        quantization="Q4_K_M",
        capabilities=["completion"],
        digest="sha256:abc123",
    )

    if running_models is None:
        running_models = []
    mock.list_running.return_value = running_models

    mock.pull_model.return_value = iter(
        [PullProgress(status="success", total=None, completed=None)]
    )

    mock.load_model.return_value = None
    mock.unload_model.return_value = None
    mock.delete_model.return_value = None
    mock.health_prompt.return_value = True

    mock.wait_loaded.return_value = RunningModel(
        name="codestral:22b",
        digest="sha256:abc123",
        size_bytes=12_000_000_000,
        size_vram=10_000_000_000,
        expires_at="2099-01-01T00:00:00Z",
    )

    mock.close.return_value = None
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)

    return mock


# ── Test 1: Add Ollama LLM with pull ────────────────────────────────────────


@pytest.mark.integration
def test_llm_add_ollama_with_pull(mock_global_db: Path) -> None:
    """Add a local (Ollama) LLM with --pull: health check, pull, show -> DB entry."""
    mock_client = _make_ollama_client_mock()

    with patch("revolver.cli.llm.OllamaClient", return_value=mock_client):
        result = runner.invoke(
            app,
            [
                "--json",
                "llm",
                "add",
                "codestral-local",
                "--model",
                "codestral:22b",
                "--source",
                "local",
                "--pull",
            ],
        )

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["name"] == "codestral-local"
    assert data["source"] == "local"
    assert data["model"] == "codestral:22b"
    assert data["base_url"] == "http://localhost:11434/v1"

    # Verify DB entry
    entries = _query_llms(mock_global_db)
    assert len(entries) == 1
    assert entries[0].name == "codestral-local"
    assert entries[0].source == "local"

    # Verify Ollama calls
    mock_client.health_check.assert_called_once()
    mock_client.pull_model.assert_called_once()
    mock_client.show_model.assert_called_once_with("codestral:22b")


# ── Test 2: Add remote LLM with pricing ────────────────────────────────────


@pytest.mark.integration
def test_llm_add_remote_with_pricing(mock_global_db: Path) -> None:
    """Add a remote LLM with pricing info -> DB entry with costs and default base_url."""
    result = runner.invoke(
        app,
        [
            "--json",
            "llm",
            "add",
            "claude-sonnet",
            "--model",
            "claude-sonnet-4-20250514",
            "--source",
            "remote",
            "--provider",
            "anthropic",
            "--api-key-env",
            "ANTHROPIC_API_KEY",
            "--input-cost",
            "3.0",
            "--output-cost",
            "15.0",
        ],
    )

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["name"] == "claude-sonnet"
    assert data["provider"] == "anthropic"
    assert data["base_url"] == "https://api.anthropic.com/v1"
    assert data["api_key_env"] == "ANTHROPIC_API_KEY"

    # Verify DB entry
    entries = _query_llms(mock_global_db)
    assert len(entries) == 1
    assert entries[0].input_cost_per_mtok == 3.0
    assert entries[0].output_cost_per_mtok == 15.0


# ── Test 3: Add openai-compat with custom base URL ─────────────────────────


@pytest.mark.integration
def test_llm_add_openai_compat(mock_global_db: Path) -> None:
    """Add an openai-compat LLM with --base-url -> custom base_url stored."""
    result = runner.invoke(
        app,
        [
            "--json",
            "llm",
            "add",
            "vllm-local",
            "--model",
            "meta-llama/Llama-3-8B",
            "--source",
            "remote",
            "--provider",
            "openai-compat",
            "--api-key-env",
            "VLLM_API_KEY",
            "--base-url",
            "http://localhost:8000/v1",
        ],
    )

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["base_url"] == "http://localhost:8000/v1"

    entries = _query_llms(mock_global_db)
    assert len(entries) == 1
    assert entries[0].base_url == "http://localhost:8000/v1"


# ── Test 4: Add duplicate name -> error ─────────────────────────────────────


@pytest.mark.integration
def test_llm_add_duplicate_name(mock_global_db: Path) -> None:
    """Adding an LLM with a name that already exists -> exit code 1."""
    # First add succeeds
    result1 = runner.invoke(
        app,
        [
            "llm",
            "add",
            "my-llm",
            "--model",
            "gpt-4o",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
        ],
    )
    assert result1.exit_code == 0, f"output: {_get_all_output(result1)}"

    # Second add with same name fails
    result2 = runner.invoke(
        app,
        [
            "llm",
            "add",
            "my-llm",
            "--model",
            "gpt-4o-mini",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
        ],
    )
    assert result2.exit_code == 1

    output = _get_all_output(result2)
    assert "already exists" in output.lower()


# ── Test 5: List after two adds ─────────────────────────────────────────────


@pytest.mark.integration
def test_llm_list_after_two_adds(mock_global_db: Path) -> None:
    """Add two LLMs -> list shows both."""
    # Add first
    runner.invoke(
        app,
        [
            "llm",
            "add",
            "llm-alpha",
            "--model",
            "gpt-4o",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
        ],
    )

    # Add second
    runner.invoke(
        app,
        [
            "llm",
            "add",
            "llm-beta",
            "--model",
            "claude-sonnet-4-20250514",
            "--source",
            "remote",
            "--provider",
            "anthropic",
            "--api-key-env",
            "ANTHROPIC_API_KEY",
        ],
    )

    # List in JSON mode
    result = runner.invoke(app, ["--json", "llm", "list"])
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) == 2
    names = {e["name"] for e in data}
    assert names == {"llm-alpha", "llm-beta"}


# ── Test 6: Remove existing LLM ────────────────────────────────────────────


@pytest.mark.integration
def test_llm_remove_existing(mock_global_db: Path) -> None:
    """Add then remove an LLM -> DB is empty."""
    # Add
    runner.invoke(
        app,
        [
            "llm",
            "add",
            "to-remove",
            "--model",
            "gpt-4o",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
        ],
    )

    # Verify it exists
    entries = _query_llms(mock_global_db)
    assert len(entries) == 1

    # Remove
    result = runner.invoke(app, ["--json", "llm", "remove", "to-remove"])
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["removed"] is True

    # Verify DB is empty
    entries = _query_llms(mock_global_db)
    assert len(entries) == 0


# ── Test 7: Remove nonexistent -> error ─────────────────────────────────────


@pytest.mark.integration
def test_llm_remove_nonexistent(mock_global_db: Path) -> None:
    """Removing a nonexistent LLM -> exit code 1."""
    result = runner.invoke(app, ["llm", "remove", "does-not-exist"])
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "not found" in output.lower()


# ── Test 8: Status with mock Ollama ─────────────────────────────────────────


@pytest.mark.integration
def test_llm_status_with_mock_ollama(mock_global_db: Path) -> None:
    """Status shows loaded/ready/unconfigured based on Ollama state and env vars."""
    # Add a local LLM
    mock_add_client = _make_ollama_client_mock()
    with patch("revolver.cli.llm.OllamaClient", return_value=mock_add_client):
        runner.invoke(
            app,
            [
                "llm",
                "add",
                "local-model",
                "--model",
                "codestral:22b",
                "--source",
                "local",
            ],
        )

    # Add a remote LLM
    runner.invoke(
        app,
        [
            "llm",
            "add",
            "remote-model",
            "--model",
            "gpt-4o",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
        ],
    )

    # Mock status: local model is loaded, remote env var not set
    mock_status_client = _make_ollama_client_mock(
        running_models=[
            RunningModel(
                name="codestral:22b",
                digest="sha256:abc123",
                size_bytes=12_000_000_000,
                size_vram=10_737_418_240,  # ~10240 MiB
                expires_at="2099-01-01T00:00:00Z",
            )
        ],
    )

    with (
        patch("revolver.cli.llm.OllamaClient", return_value=mock_status_client),
        patch("revolver.core.llm.get_gpu_info", return_value=None),
    ):
        # Ensure env var is NOT set for remote model
        env_backup = os.environ.pop("OPENAI_API_KEY", None)
        try:
            result = runner.invoke(app, ["--json", "llm", "status"])
        finally:
            if env_backup is not None:
                os.environ["OPENAI_API_KEY"] = env_backup

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["ollama_running"] is True

    llm_statuses = data["llms"]
    assert len(llm_statuses) == 2

    # Find by name
    status_by_name = {s["name"]: s for s in llm_statuses}
    assert status_by_name["local-model"]["status"] == "loaded"
    assert status_by_name["local-model"]["vram_mib"] is not None
    assert status_by_name["remote-model"]["status"] == "unconfigured"


# ── Test 9: Start with mock load ────────────────────────────────────────────


@pytest.mark.integration
def test_llm_start_mock_load(mock_global_db: Path) -> None:
    """Start a local LLM: load, wait, health check -> success."""
    # First register the LLM
    mock_add_client = _make_ollama_client_mock()
    with patch("revolver.cli.llm.OllamaClient", return_value=mock_add_client):
        result_add = runner.invoke(
            app,
            [
                "llm",
                "add",
                "test-model",
                "--model",
                "codestral:22b",
                "--source",
                "local",
            ],
        )
    assert result_add.exit_code == 0, f"output: {_get_all_output(result_add)}"

    # Now start it
    mock_start_client = _make_ollama_client_mock(
        running_models=[],  # No models loaded initially
    )
    mock_start_client.wait_loaded.return_value = RunningModel(
        name="codestral:22b",
        digest="sha256:abc123",
        size_bytes=12_000_000_000,
        size_vram=10_737_418_240,
        expires_at="2099-01-01T00:00:00Z",
    )

    with patch("revolver.cli.llm.OllamaClient", return_value=mock_start_client):
        result = runner.invoke(app, ["--json", "llm", "start", "test-model"])

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["name"] == "test-model"
    assert data["model"] == "codestral:22b"
    assert data["health_ok"] is True

    # Verify Ollama calls
    mock_start_client.load_model.assert_called_once_with("codestral:22b")
    mock_start_client.wait_loaded.assert_called_once()
    mock_start_client.health_prompt.assert_called_once_with("codestral:22b")


# ── Test 10: Start unloads previous model ───────────────────────────────────


@pytest.mark.integration
def test_llm_start_unloads_previous(mock_global_db: Path) -> None:
    """Starting a model when another is loaded -> unloads the previous one first."""
    # Register the LLM
    mock_add_client = _make_ollama_client_mock()
    with patch("revolver.cli.llm.OllamaClient", return_value=mock_add_client):
        runner.invoke(
            app,
            [
                "llm",
                "add",
                "new-model",
                "--model",
                "codestral:22b",
                "--source",
                "local",
            ],
        )

    # Start with another model already loaded
    mock_start_client = _make_ollama_client_mock(
        running_models=[
            RunningModel(
                name="other-model:7b",
                digest="sha256:other",
                size_bytes=4_000_000_000,
                size_vram=3_500_000_000,
                expires_at="2099-01-01T00:00:00Z",
            )
        ],
    )
    mock_start_client.wait_loaded.return_value = RunningModel(
        name="codestral:22b",
        digest="sha256:abc123",
        size_bytes=12_000_000_000,
        size_vram=10_737_418_240,
        expires_at="2099-01-01T00:00:00Z",
    )

    with patch("revolver.cli.llm.OllamaClient", return_value=mock_start_client):
        result = runner.invoke(app, ["--json", "llm", "start", "new-model"])

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["previous_unloaded"] == "other-model:7b"

    # Verify the previous model was unloaded
    mock_start_client.unload_model.assert_called_once_with("other-model:7b")


# ── Test 11: Stop with mock unload ──────────────────────────────────────────


@pytest.mark.integration
def test_llm_stop_mock_unload(mock_global_db: Path) -> None:
    """Stop a running model -> unload success."""
    # Register the LLM
    mock_add_client = _make_ollama_client_mock()
    with patch("revolver.cli.llm.OllamaClient", return_value=mock_add_client):
        runner.invoke(
            app,
            [
                "llm",
                "add",
                "running-model",
                "--model",
                "codestral:22b",
                "--source",
                "local",
            ],
        )

    # Stop with the model loaded
    mock_stop_client = _make_ollama_client_mock(
        running_models=[
            RunningModel(
                name="codestral:22b",
                digest="sha256:abc123",
                size_bytes=12_000_000_000,
                size_vram=10_737_418_240,
                expires_at="2099-01-01T00:00:00Z",
            )
        ],
    )

    with patch("revolver.cli.llm.OllamaClient", return_value=mock_stop_client):
        result = runner.invoke(app, ["--json", "llm", "stop", "running-model"])

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["was_loaded"] is True
    assert data["name"] == "running-model"
    assert data["model"] == "codestral:22b"

    # Verify unload was called
    mock_stop_client.unload_model.assert_called_once_with("codestral:22b")
