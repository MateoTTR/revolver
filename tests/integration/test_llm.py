"""L2 integration tests for ``revolver llm`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner, mocking the
Ollama client at the infra boundary and using a temporary global database.

Traceable to: val-integration-tests.md section 2.2.
"""

from __future__ import annotations

from collections.abc import Generator
import json
import os
from pathlib import Path
import re
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

    # Remove (--force required in JSON mode to skip interactive prompt)
    result = runner.invoke(app, ["--json", "llm", "remove", "to-remove", "--force"])
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
    result = runner.invoke(app, ["llm", "remove", "does-not-exist", "--force"])
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


# ── Test 12: Add with --max-tokens and --timeout ─────────────────────────


@pytest.mark.integration
def test_llm_add_with_max_tokens_and_timeout(mock_global_db: Path) -> None:
    """Add a remote LLM with --max-tokens and --timeout -> stored in DB."""
    result = runner.invoke(
        app,
        [
            "--json",
            "llm",
            "add",
            "claude-config",
            "--model",
            "claude-sonnet-4-20250514",
            "--source",
            "remote",
            "--provider",
            "anthropic",
            "--api-key-env",
            "ANTHROPIC_API_KEY",
            "--max-tokens",
            "8192",
            "--timeout",
            "120",
        ],
    )

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["name"] == "claude-config"

    # Verify DB entry has max_tokens and timeout_s
    entries = _query_llms(mock_global_db)
    assert len(entries) == 1
    assert entries[0].max_tokens == 8192
    assert entries[0].timeout_s == 120


# ── Test 13: List shows max_tokens/timeout_s columns ─────────────────────


@pytest.mark.integration
def test_llm_list_shows_config_columns(mock_global_db: Path) -> None:
    """List LLMs with config shows max_tokens/timeout_s in JSON output."""
    # Add an LLM with config
    runner.invoke(
        app,
        [
            "llm",
            "add",
            "llm-with-config",
            "--model",
            "gpt-4o",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
            "--max-tokens",
            "4096",
            "--timeout",
            "60",
        ],
    )

    # Add an LLM without config
    runner.invoke(
        app,
        [
            "llm",
            "add",
            "llm-no-config",
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

    # List in JSON mode
    result = runner.invoke(app, ["--json", "llm", "list"])
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    by_name = {e["name"]: e for e in data}

    assert by_name["llm-with-config"]["max_tokens"] == 4096
    assert by_name["llm-with-config"]["timeout_s"] == 60
    assert by_name["llm-no-config"]["max_tokens"] is None
    assert by_name["llm-no-config"]["timeout_s"] is None


# ── Test 14: Remove with --force skips confirmation ──────────────────────


@pytest.mark.integration
def test_llm_remove_force(mock_global_db: Path) -> None:
    """--force skips the confirmation prompt and removes the LLM."""
    # Add an LLM first
    runner.invoke(
        app,
        [
            "llm",
            "add",
            "force-remove",
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

    entries = _query_llms(mock_global_db)
    assert len(entries) == 1

    # Remove with --force: no prompt, exits 0
    result = runner.invoke(app, ["llm", "remove", "force-remove", "--force"])
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    output = _get_all_output(result)
    assert "removed" in output.lower()

    # Verify DB is empty
    entries = _query_llms(mock_global_db)
    assert len(entries) == 0


# ── Test 15: Remove without --force prompts for confirmation ─────────────


@pytest.mark.integration
def test_llm_remove_confirmation_abort(mock_global_db: Path) -> None:
    """Without --force, user declines confirmation → LLM is NOT removed."""
    # Add an LLM first
    runner.invoke(
        app,
        [
            "llm",
            "add",
            "keep-me",
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

    entries = _query_llms(mock_global_db)
    assert len(entries) == 1

    # Remove without --force, answer "n" → aborted
    interactive_runner = CliRunner()
    result = interactive_runner.invoke(
        app,
        ["llm", "remove", "keep-me"],
        input="n\n",
    )

    # typer.confirm with abort=True raises Abort → exit code 1
    assert result.exit_code == 1

    # Verify LLM is still in DB
    entries = _query_llms(mock_global_db)
    assert len(entries) == 1


# ── Test 16: Remove in JSON mode without --force → error ─────────────────


@pytest.mark.integration
def test_llm_remove_json_requires_force(mock_global_db: Path) -> None:
    """In --json mode, remove without --force exits with error."""
    # Add an LLM first
    runner.invoke(
        app,
        [
            "llm",
            "add",
            "json-test",
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

    # Attempt remove in JSON mode without --force
    result = runner.invoke(app, ["--json", "llm", "remove", "json-test"])
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "--force" in output.lower()

    # Verify LLM is still in DB
    entries = _query_llms(mock_global_db)
    assert len(entries) == 1


# ── Test 17: Update max_tokens ───────────────────────────────────────────


def _add_remote_llm(name: str = "test-llm") -> None:
    """Helper: add a remote LLM for update tests."""
    result = runner.invoke(
        app,
        [
            "llm",
            "add",
            name,
            "--model",
            "gpt-4o",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
            "--max-tokens",
            "4096",
            "--timeout",
            "60",
            "--input-cost",
            "2.5",
            "--output-cost",
            "10.0",
        ],
    )
    assert result.exit_code == 0, result.output


@pytest.mark.integration
def test_llm_update_max_tokens(mock_global_db: Path) -> None:
    """Update max_tokens on an existing LLM, verify reflected in list."""
    _add_remote_llm()

    # Update max_tokens
    result = runner.invoke(
        app,
        ["--json", "llm", "update", "test-llm", "--max-tokens", "16384"],
    )
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["name"] == "test-llm"
    assert data["max_tokens"] == 16384
    # Other fields unchanged
    assert data["timeout_s"] == 60

    # Verify via list
    list_result = runner.invoke(app, ["--json", "llm", "list"])
    list_data = json.loads(list_result.stdout)
    assert list_data[0]["max_tokens"] == 16384
    assert list_data[0]["timeout_s"] == 60


# ── Test 18: Update no fields error ──────────────────────────────────────


@pytest.mark.integration
def test_llm_update_no_fields_error(mock_global_db: Path) -> None:
    """No update flags provided -> exit code 1."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["llm", "update", "test-llm"],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "no update flags" in output.lower()


# ── Test 19: Update timeout_s ────────────────────────────────────────────


@pytest.mark.integration
def test_llm_update_timeout(mock_global_db: Path) -> None:
    """Update timeout_s on an existing LLM."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["--json", "llm", "update", "test-llm", "--timeout", "300"],
    )
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["timeout_s"] == 300
    assert data["max_tokens"] == 4096  # unchanged


# ── Test 20: Update multiple fields ──────────────────────────────────────


@pytest.mark.integration
def test_llm_update_multiple_fields(mock_global_db: Path) -> None:
    """Update multiple fields at once."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        [
            "--json",
            "llm",
            "update",
            "test-llm",
            "--max-tokens",
            "8192",
            "--timeout",
            "180",
            "--input-cost",
            "5.0",
            "--output-cost",
            "20.0",
        ],
    )
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["max_tokens"] == 8192
    assert data["timeout_s"] == 180
    assert data["input_cost_per_mtok"] == 5.0
    assert data["output_cost_per_mtok"] == 20.0


# ── Test 21: Update nonexistent LLM error ────────────────────────────────


@pytest.mark.integration
def test_llm_update_nonexistent(mock_global_db: Path) -> None:
    """Updating a nonexistent LLM -> exit code 1."""
    result = runner.invoke(
        app,
        ["llm", "update", "does-not-exist", "--max-tokens", "8192"],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "not found" in output.lower()


# ── Test 22: Update with invalid max_tokens error ────────────────────────


@pytest.mark.integration
def test_llm_update_invalid_max_tokens(mock_global_db: Path) -> None:
    """Updating with zero max_tokens -> exit code 1."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["llm", "update", "test-llm", "--max-tokens", "0"],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "positive" in output.lower()


# ── Test 23: Update with --timeout 0 error ─────────────────────────────


@pytest.mark.integration
def test_llm_update_invalid_timeout_zero(mock_global_db: Path) -> None:
    """Updating with timeout=0 -> exit code 1 (must be positive)."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["llm", "update", "test-llm", "--timeout", "0"],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "positive" in output.lower()


# ── Test 24: Update with negative input cost error ────────────────────


@pytest.mark.integration
def test_llm_update_negative_input_cost(mock_global_db: Path) -> None:
    """Updating with negative input cost -> exit code 1."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["llm", "update", "test-llm", "--input-cost", "-1.0"],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "non-negative" in output.lower()


# ── Test 25: Update with negative output cost error ───────────────────


@pytest.mark.integration
def test_llm_update_negative_output_cost(mock_global_db: Path) -> None:
    """Updating with negative output cost -> exit code 1."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["llm", "update", "test-llm", "--output-cost", "-0.01"],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "non-negative" in output.lower()


# ── Test 26: Update with zero input cost succeeds ─────────────────────


@pytest.mark.integration
def test_llm_update_zero_input_cost_valid(mock_global_db: Path) -> None:
    """Updating with input cost = 0.0 succeeds (zero is a valid cost)."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["--json", "llm", "update", "test-llm", "--input-cost", "0.0"],
    )
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["input_cost_per_mtok"] == 0.0


# ── Test 27: Add with --temperature ───────────────────────────────────


@pytest.mark.integration
def test_llm_add_temperature(mock_global_db: Path) -> None:
    """Add a remote LLM with --temperature -> stored in DB."""
    result = runner.invoke(
        app,
        [
            "--json",
            "llm",
            "add",
            "claude-temp",
            "--model",
            "claude-sonnet-4-20250514",
            "--source",
            "remote",
            "--provider",
            "anthropic",
            "--api-key-env",
            "ANTHROPIC_API_KEY",
            "--temperature",
            "0.7",
        ],
    )

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    # Verify DB entry has temperature
    entries = _query_llms(mock_global_db)
    assert len(entries) == 1
    assert entries[0].temperature == 0.7


# ── Test 28: Update --temperature ─────────────────────────────────────


@pytest.mark.integration
def test_llm_update_temperature(mock_global_db: Path) -> None:
    """Update temperature on an existing LLM, verify reflected in list."""
    _add_remote_llm()

    # Update temperature
    result = runner.invoke(
        app,
        ["--json", "llm", "update", "test-llm", "--temperature", "1.0"],
    )
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["name"] == "test-llm"
    assert data["temperature"] == 1.0

    # Verify via list
    list_result = runner.invoke(app, ["--json", "llm", "list"])
    list_data = json.loads(list_result.stdout)
    assert list_data[0]["temperature"] == 1.0


# ── Test 29: LLM temperature injected in build_config ─────────────────


@pytest.mark.integration
def test_llm_temperature_injected_in_build_config() -> None:
    """LLM with temperature -> build_config includes it in config['llm']['temperature']."""
    from datetime import datetime

    from revolver.infra.backends.openevolve import build_config
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="test-model",
        source="remote",
        base_url="http://localhost:11434/v1",
        temperature=0.7,
        registered_at=datetime(2026, 1, 1),
    )
    result = build_config(problem_config=None, llm=llm)

    assert result["llm"]["temperature"] == 0.7


# ── Test 30: CLI --temperature overrides LLM registry value ───────────


@pytest.mark.integration
def test_run_temperature_overrides_llm_registry() -> None:
    """CLI --temperature flag (via config_overrides) overrides LLM registry temperature."""
    from datetime import datetime

    from revolver.infra.backends.openevolve import build_config
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="test-model",
        source="remote",
        base_url="http://localhost:11434/v1",
        temperature=0.7,
        registered_at=datetime(2026, 1, 1),
    )
    # Simulate CLI --temperature override via config_overrides (step 5)
    result = build_config(
        problem_config=None,
        llm=llm,
        config_overrides=["llm.temperature=1.5"],
    )

    # Config override (step 5) should win over LLM registry (step 2b)
    assert result["llm"]["temperature"] == 1.5


# ── Test 31: Add with --temperature below range ───────────────────────


@pytest.mark.integration
def test_llm_add_temperature_below_range(mock_global_db: Path) -> None:
    """Adding with --temperature -0.1 -> exit code 1 (below 0.0)."""
    result = runner.invoke(
        app,
        [
            "llm",
            "add",
            "bad-temp",
            "--model",
            "gpt-4o",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
            "--temperature",
            "-0.1",
        ],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "temperature" in output.lower()
    assert "0.0" in output or "between" in output.lower()


# ── Test 32: Add with --temperature above range ───────────────────────


@pytest.mark.integration
def test_llm_add_temperature_above_range(mock_global_db: Path) -> None:
    """Adding with --temperature 2.01 -> exit code 1 (above 2.0)."""
    result = runner.invoke(
        app,
        [
            "llm",
            "add",
            "bad-temp",
            "--model",
            "gpt-4o",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
            "--temperature",
            "2.01",
        ],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "temperature" in output.lower()
    assert "2.0" in output or "between" in output.lower()


# ── Test 33: Update with --temperature below range ────────────────────


@pytest.mark.integration
def test_llm_update_temperature_below_range(mock_global_db: Path) -> None:
    """Updating with --temperature -0.1 -> exit code 1."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["llm", "update", "test-llm", "--temperature", "-0.1"],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "temperature" in output.lower()


# ── Test 34: Update with --temperature above range ────────────────────


@pytest.mark.integration
def test_llm_update_temperature_above_range(mock_global_db: Path) -> None:
    """Updating with --temperature 2.01 -> exit code 1."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["llm", "update", "test-llm", "--temperature", "2.01"],
    )
    assert result.exit_code == 1

    output = _get_all_output(result)
    assert "temperature" in output.lower()


# ── Test 35: Add JSON output includes temperature field ───────────────


@pytest.mark.integration
def test_llm_add_json_includes_temperature(mock_global_db: Path) -> None:
    """llm add --json output must include temperature (consistency with llm update)."""
    result = runner.invoke(
        app,
        [
            "--json",
            "llm",
            "add",
            "json-temp",
            "--model",
            "gpt-4o",
            "--source",
            "remote",
            "--provider",
            "openai",
            "--api-key-env",
            "OPENAI_API_KEY",
            "--temperature",
            "0.5",
        ],
    )

    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert "temperature" in data
    assert data["temperature"] == 0.5
    # Also verify other config fields are present for consistency
    assert "max_tokens" in data
    assert "timeout_s" in data


# ── Test 36: Update model identifier ───────────────────────────────────


@pytest.mark.integration
def test_llm_update_model(mock_global_db: Path) -> None:
    """Update model identifier on an existing LLM, verify reflected in JSON output."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["--json", "llm", "update", "test-llm", "--model", "gpt-4o-mini"],
    )
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    data = json.loads(result.stdout)
    assert data["name"] == "test-llm"
    assert data["model"] == "gpt-4o-mini"
    # Other fields unchanged
    assert data["max_tokens"] == 4096
    assert data["timeout_s"] == 60


# ── Test 37: Update model visible in list ──────────────────────────────


@pytest.mark.integration
def test_llm_update_model_visible_in_list(mock_global_db: Path) -> None:
    """After updating model, ``llm list`` shows the new model name."""
    _add_remote_llm()

    # Update model
    result = runner.invoke(
        app,
        ["llm", "update", "test-llm", "--model", "gemini-2.5-flash-lite"],
    )
    assert result.exit_code == 0, f"output: {_get_all_output(result)}"

    # Verify via list (JSON)
    list_result = runner.invoke(app, ["--json", "llm", "list"])
    assert list_result.exit_code == 0
    list_data = json.loads(list_result.stdout)
    assert list_data[0]["model"] == "gemini-2.5-flash-lite"
    # Other fields unchanged
    assert list_data[0]["max_tokens"] == 4096
    assert list_data[0]["timeout_s"] == 60


# ── Test 38: Update model empty string rejected ─────────────────────────


@pytest.mark.integration
def test_llm_update_model_empty_string_rejected(mock_global_db: Path) -> None:
    """Passing --model '' should fail with a validation error."""
    _add_remote_llm()

    result = runner.invoke(
        app,
        ["llm", "update", "test-llm", "--model", ""],
    )
    assert result.exit_code != 0, f"output: {_get_all_output(result)}"
    output = _get_all_output(result)
    assert "empty string" in output.lower() or "must not be" in output.lower()
