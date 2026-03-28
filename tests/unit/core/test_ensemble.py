"""Unit tests for ensemble domain logic in core.llm.

Covers:
- create_ensemble: success, duplicate name
- add_ensemble_member: success, LLM not found, ensemble not found,
  duplicate member, weight sum warning
- remove_ensemble: success, not found
- list_ensembles: empty, populated
- get_ensemble_info: success, not found

Traceable to: S11-04.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.core.exceptions import DuplicateNameError, RevolverError
from revolver.core.llm import (
    add_ensemble_member,
    create_ensemble,
    get_ensemble_info,
    list_ensembles,
    remove_ensemble,
)
from revolver.infra.db import get_global_db_at, insert_llm
from revolver.models.llm import LLMEntry


@pytest.fixture()
def conn(tmp_path: Path):
    """Provide a fresh global DB connection."""
    db_path = tmp_path / "global.db"
    connection = get_global_db_at(db_path)
    yield connection
    connection.close()


def _register_llm(conn, name: str = "flash-lite", model: str = "flash-lite:latest") -> None:
    """Helper to register a dummy LLM for ensemble membership tests."""
    entry = LLMEntry(
        name=name,
        provider="google",
        model=model,
        source="remote",
        base_url="https://example.com/v1",
        api_key_env="GOOGLE_API_KEY",
        registered_at=datetime.now(UTC),
    )
    insert_llm(conn, entry)


# ── create_ensemble ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCreateEnsemble:
    def test_create_returns_entry(self, conn) -> None:
        entry = create_ensemble("alphevo", conn)
        assert entry.name == "alphevo"
        assert entry.members == []
        assert entry.created_at is not None

    def test_create_duplicate_raises(self, conn) -> None:
        create_ensemble("alphevo", conn)
        with pytest.raises(DuplicateNameError, match="already exists"):
            create_ensemble("alphevo", conn)


# ── add_ensemble_member ────────────────────────────────────────────────────


@pytest.mark.unit
class TestAddEnsembleMember:
    def test_add_member_success(self, conn) -> None:
        _register_llm(conn, "flash-lite")
        create_ensemble("alphevo", conn)
        add_ensemble_member("alphevo", "flash-lite", 1.0, conn)

        entry = get_ensemble_info("alphevo", conn)
        assert len(entry.members) == 1
        assert entry.members[0].llm_name == "flash-lite"
        assert entry.members[0].weight == 1.0

    def test_add_member_with_overrides(self, conn) -> None:
        _register_llm(conn, "flash-lite")
        create_ensemble("alphevo", conn)
        add_ensemble_member("alphevo", "flash-lite", 0.8, conn, temperature=0.5, max_tokens=1024)

        entry = get_ensemble_info("alphevo", conn)
        assert entry.members[0].temperature == 0.5
        assert entry.members[0].max_tokens == 1024

    def test_add_member_llm_not_found(self, conn) -> None:
        create_ensemble("alphevo", conn)
        with pytest.raises(RevolverError, match="LLM 'nonexistent' not found"):
            add_ensemble_member("alphevo", "nonexistent", 1.0, conn)

    def test_add_member_ensemble_not_found(self, conn) -> None:
        _register_llm(conn, "flash-lite")
        with pytest.raises(RevolverError, match="Ensemble 'nonexistent' not found"):
            add_ensemble_member("nonexistent", "flash-lite", 1.0, conn)

    def test_add_duplicate_member_raises(self, conn) -> None:
        _register_llm(conn, "flash-lite")
        create_ensemble("alphevo", conn)
        add_ensemble_member("alphevo", "flash-lite", 0.5, conn)
        with pytest.raises(DuplicateNameError, match="already a member"):
            add_ensemble_member("alphevo", "flash-lite", 0.5, conn)

    def test_weight_sum_warning(self, conn, capsys) -> None:
        """Weights not summing to ~1.0 should emit a warning to stderr."""
        _register_llm(conn, "flash-lite")
        _register_llm(conn, "sonnet", model="sonnet:latest")
        create_ensemble("alphevo", conn)

        # First member: weight 0.3 — sum is 0.3, should warn
        add_ensemble_member("alphevo", "flash-lite", 0.3, conn)
        captured = capsys.readouterr()
        assert "total weight is 0.30" in captured.err

        # Second member: weight 0.7 — sum is 1.0, should NOT warn
        add_ensemble_member("alphevo", "sonnet", 0.7, conn)
        captured = capsys.readouterr()
        assert "total weight" not in captured.err

    def test_weight_sum_no_warning_at_1(self, conn, capsys) -> None:
        """Weights summing to exactly 1.0 should not warn."""
        _register_llm(conn, "flash-lite")
        create_ensemble("alphevo", conn)
        add_ensemble_member("alphevo", "flash-lite", 1.0, conn)
        captured = capsys.readouterr()
        assert "total weight" not in captured.err


# ── remove_ensemble ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRemoveEnsemble:
    def test_remove_success(self, conn) -> None:
        create_ensemble("alphevo", conn)
        remove_ensemble("alphevo", conn)
        # Should be gone
        with pytest.raises(RevolverError, match="not found"):
            get_ensemble_info("alphevo", conn)

    def test_remove_not_found(self, conn) -> None:
        with pytest.raises(RevolverError, match="not found"):
            remove_ensemble("nonexistent", conn)

    def test_remove_cascades_members(self, conn) -> None:
        _register_llm(conn, "flash-lite")
        create_ensemble("alphevo", conn)
        add_ensemble_member("alphevo", "flash-lite", 1.0, conn)
        remove_ensemble("alphevo", conn)
        # Ensemble is gone
        assert list_ensembles(conn) == []


# ── list_ensembles ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestListEnsembles:
    def test_list_empty(self, conn) -> None:
        result = list_ensembles(conn)
        assert result == []

    def test_list_populated(self, conn) -> None:
        create_ensemble("alpha", conn)
        create_ensemble("beta", conn)
        result = list_ensembles(conn)
        assert len(result) == 2
        assert result[0].name == "alpha"
        assert result[1].name == "beta"

    def test_list_includes_members(self, conn) -> None:
        _register_llm(conn, "flash-lite")
        create_ensemble("alphevo", conn)
        add_ensemble_member("alphevo", "flash-lite", 1.0, conn)

        result = list_ensembles(conn)
        assert len(result) == 1
        assert len(result[0].members) == 1


# ── get_ensemble_info ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestGetEnsembleInfo:
    def test_info_success(self, conn) -> None:
        _register_llm(conn, "flash-lite")
        create_ensemble("alphevo", conn)
        add_ensemble_member("alphevo", "flash-lite", 1.0, conn)

        entry = get_ensemble_info("alphevo", conn)
        assert entry.name == "alphevo"
        assert len(entry.members) == 1
        assert entry.members[0].llm_name == "flash-lite"

    def test_info_not_found(self, conn) -> None:
        with pytest.raises(RevolverError, match="not found"):
            get_ensemble_info("nonexistent", conn)
