"""L2 integration tests for ``revolver llm ensemble`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner, using a
temporary global database.

Traceable to: S11-05, val-integration-tests.md.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.infra.db import get_global_db_at, insert_llm
from revolver.models.llm import LLMEntry

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


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def global_db_path(tmp_path: Path) -> Path:
    """Return the path for a temporary global database."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    conn.close()
    return db_path


@pytest.fixture()
def mock_global_db(
    global_db_path: Path,
) -> Generator[Path, None, None]:
    """Patch get_global_db so the CLI opens new connections to our temp DB."""
    with patch(
        "revolver.cli.llm.get_global_db",
        side_effect=lambda: get_global_db_at(global_db_path),
    ):
        yield global_db_path


def _register_llm(db_path: Path, name: str = "flash-lite") -> None:
    """Register a dummy LLM directly in the DB."""
    conn = get_global_db_at(db_path)
    try:
        entry = LLMEntry(
            name=name,
            provider="google",
            model=f"{name}:latest",
            source="remote",
            base_url="https://example.com/v1",
            api_key_env="GOOGLE_API_KEY",
            registered_at=datetime.now(UTC),
        )
        insert_llm(conn, entry)
    finally:
        conn.close()


# ── ensemble create ───────────────────────────────────────────────────────


@pytest.mark.integration
class TestEnsembleCreate:
    def test_create_json(self, mock_global_db: Path) -> None:
        result = runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])
        assert result.exit_code == 0, _get_all_output(result)
        data = json.loads(result.stdout)
        assert data["name"] == "alphevo"
        assert data["members"] == []
        assert "created_at" in data

    def test_create_human(self, mock_global_db: Path) -> None:
        result = runner.invoke(app, ["llm", "ensemble", "create", "alphevo"])
        assert result.exit_code == 0, _get_all_output(result)
        output = _get_all_output(result)
        assert "alphevo" in output
        assert "created" in output.lower()

    def test_create_duplicate(self, mock_global_db: Path) -> None:
        runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])
        result = runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])
        assert result.exit_code != 0


# ── ensemble add ──────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEnsembleAdd:
    def test_add_member_json(self, mock_global_db: Path) -> None:
        _register_llm(mock_global_db, "flash-lite")
        runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])

        result = runner.invoke(
            app,
            [
                "--json",
                "llm",
                "ensemble",
                "add",
                "alphevo",
                "--llm",
                "flash-lite",
                "--weight",
                "0.8",
            ],
        )
        assert result.exit_code == 0, _get_all_output(result)
        data = json.loads(result.stdout)
        assert data["ensemble"] == "alphevo"
        assert data["added"] == "flash-lite"
        assert data["weight"] == 0.8
        assert data["member_count"] == 1

    def test_add_member_with_overrides(self, mock_global_db: Path) -> None:
        _register_llm(mock_global_db, "flash-lite")
        runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])

        result = runner.invoke(
            app,
            [
                "--json",
                "llm",
                "ensemble",
                "add",
                "alphevo",
                "--llm",
                "flash-lite",
                "--weight",
                "1.0",
                "--temperature",
                "0.5",
                "--max-tokens",
                "1024",
            ],
        )
        assert result.exit_code == 0, _get_all_output(result)
        data = json.loads(result.stdout)
        assert data["temperature"] == 0.5
        assert data["max_tokens"] == 1024

    def test_add_member_llm_not_found(self, mock_global_db: Path) -> None:
        runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])
        result = runner.invoke(
            app,
            [
                "--json",
                "llm",
                "ensemble",
                "add",
                "alphevo",
                "--llm",
                "nonexistent",
                "--weight",
                "1.0",
            ],
        )
        assert result.exit_code != 0

    def test_add_member_human(self, mock_global_db: Path) -> None:
        _register_llm(mock_global_db, "flash-lite")
        runner.invoke(app, ["llm", "ensemble", "create", "alphevo"])

        result = runner.invoke(
            app,
            [
                "llm",
                "ensemble",
                "add",
                "alphevo",
                "--llm",
                "flash-lite",
                "--weight",
                "0.8",
            ],
        )
        assert result.exit_code == 0, _get_all_output(result)
        output = _get_all_output(result)
        assert "flash-lite" in output


# ── ensemble list ─────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEnsembleList:
    def test_list_empty_json(self, mock_global_db: Path) -> None:
        result = runner.invoke(app, ["--json", "llm", "ensemble", "list"])
        assert result.exit_code == 0, _get_all_output(result)
        data = json.loads(result.stdout)
        assert data == []

    def test_list_populated_json(self, mock_global_db: Path) -> None:
        _register_llm(mock_global_db, "flash-lite")
        runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])
        runner.invoke(
            app,
            [
                "--json",
                "llm",
                "ensemble",
                "add",
                "alphevo",
                "--llm",
                "flash-lite",
                "--weight",
                "0.8",
            ],
        )

        result = runner.invoke(app, ["--json", "llm", "ensemble", "list"])
        assert result.exit_code == 0, _get_all_output(result)
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["name"] == "alphevo"
        assert data[0]["member_count"] == 1
        assert data[0]["total_weight"] == 0.8

    def test_list_human_empty(self, mock_global_db: Path) -> None:
        result = runner.invoke(app, ["llm", "ensemble", "list"])
        assert result.exit_code == 0, _get_all_output(result)
        output = _get_all_output(result)
        assert "No ensembles" in output

    def test_list_human_populated(self, mock_global_db: Path) -> None:
        runner.invoke(app, ["llm", "ensemble", "create", "alphevo"])
        result = runner.invoke(app, ["llm", "ensemble", "list"])
        assert result.exit_code == 0, _get_all_output(result)
        output = _get_all_output(result)
        assert "alphevo" in output


# ── ensemble info ─────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEnsembleInfo:
    def test_info_json(self, mock_global_db: Path) -> None:
        _register_llm(mock_global_db, "flash-lite")
        runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])
        runner.invoke(
            app,
            [
                "--json",
                "llm",
                "ensemble",
                "add",
                "alphevo",
                "--llm",
                "flash-lite",
                "--weight",
                "1.0",
                "--temperature",
                "0.5",
            ],
        )

        result = runner.invoke(app, ["--json", "llm", "ensemble", "info", "alphevo"])
        assert result.exit_code == 0, _get_all_output(result)
        data = json.loads(result.stdout)
        assert data["name"] == "alphevo"
        assert len(data["members"]) == 1
        assert data["members"][0]["llm_name"] == "flash-lite"
        assert data["members"][0]["weight"] == 1.0
        assert data["members"][0]["temperature"] == 0.5
        assert data["total_weight"] == 1.0

    def test_info_not_found(self, mock_global_db: Path) -> None:
        result = runner.invoke(app, ["--json", "llm", "ensemble", "info", "nonexistent"])
        assert result.exit_code != 0

    def test_info_human(self, mock_global_db: Path) -> None:
        _register_llm(mock_global_db, "flash-lite")
        runner.invoke(app, ["llm", "ensemble", "create", "alphevo"])
        runner.invoke(
            app,
            [
                "llm",
                "ensemble",
                "add",
                "alphevo",
                "--llm",
                "flash-lite",
                "--weight",
                "1.0",
            ],
        )

        result = runner.invoke(app, ["llm", "ensemble", "info", "alphevo"])
        assert result.exit_code == 0, _get_all_output(result)
        output = _get_all_output(result)
        assert "alphevo" in output
        assert "flash-lite" in output


# ── ensemble remove ───────────────────────────────────────────────────────


@pytest.mark.integration
class TestEnsembleRemove:
    def test_remove_json_force(self, mock_global_db: Path) -> None:
        runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])
        result = runner.invoke(app, ["--json", "llm", "ensemble", "remove", "alphevo", "--force"])
        assert result.exit_code == 0, _get_all_output(result)
        data = json.loads(result.stdout)
        assert data["name"] == "alphevo"
        assert data["removed"] is True

        # Verify it's gone
        result = runner.invoke(app, ["--json", "llm", "ensemble", "list"])
        data = json.loads(result.stdout)
        assert data == []

    def test_remove_json_without_force(self, mock_global_db: Path) -> None:
        runner.invoke(app, ["--json", "llm", "ensemble", "create", "alphevo"])
        result = runner.invoke(app, ["--json", "llm", "ensemble", "remove", "alphevo"])
        # Should fail because JSON mode requires --force
        assert result.exit_code != 0

    def test_remove_not_found(self, mock_global_db: Path) -> None:
        result = runner.invoke(
            app, ["--json", "llm", "ensemble", "remove", "nonexistent", "--force"]
        )
        assert result.exit_code != 0

    def test_remove_human_force(self, mock_global_db: Path) -> None:
        runner.invoke(app, ["llm", "ensemble", "create", "alphevo"])
        result = runner.invoke(app, ["llm", "ensemble", "remove", "alphevo", "--force"])
        assert result.exit_code == 0, _get_all_output(result)
        output = _get_all_output(result)
        assert "alphevo" in output
        assert "removed" in output.lower()

    def test_remove_human_with_confirm(self, mock_global_db: Path) -> None:
        runner.invoke(app, ["llm", "ensemble", "create", "alphevo"])
        result = runner.invoke(app, ["llm", "ensemble", "remove", "alphevo"], input="y\n")
        assert result.exit_code == 0, _get_all_output(result)
