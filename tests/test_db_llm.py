"""L1 unit tests for LLM CRUD operations in revolver.infra.db."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.core.exceptions import DuplicateNameError
from revolver.infra.db import (
    delete_llm,
    get_global_db_at,
    get_llm,
    insert_llm,
    list_llms,
    update_llm_stats,
)
from revolver.models.llm import LLMEntry

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_entry(
    name: str = "codestral-local",
    *,
    provider: str | None = "ollama",
    model: str = "codestral:22b",
    source: str = "local",
    base_url: str | None = "http://localhost:11434",
    api_key_env: str | None = None,
    input_cost: float | None = None,
    output_cost: float | None = None,
) -> LLMEntry:
    """Build an LLMEntry with sensible defaults for testing."""
    return LLMEntry(
        name=name,
        provider=provider,
        model=model,
        source=source,
        base_url=base_url,
        api_key_env=api_key_env,
        input_cost_per_mtok=input_cost,
        output_cost_per_mtok=output_cost,
        registered_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
    )


# ── WAL mode ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_global_db_wal_mode(tmp_path: Path) -> None:
    """Global DB uses WAL journal mode."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"
    finally:
        conn.close()


# ── Insert + Get ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_insert_and_get_llm(tmp_path: Path) -> None:
    """Round-trip: insert an LLM then retrieve it by name."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        entry = _make_entry()
        insert_llm(conn, entry)

        retrieved = get_llm(conn, "codestral-local")
        assert retrieved is not None
        assert retrieved.name == "codestral-local"
        assert retrieved.provider == "ollama"
        assert retrieved.model == "codestral:22b"
        assert retrieved.source == "local"
        assert retrieved.base_url == "http://localhost:11434"
        assert retrieved.api_key_env is None
        assert retrieved.input_cost_per_mtok is None
        assert retrieved.output_cost_per_mtok is None
    finally:
        conn.close()


@pytest.mark.unit
def test_get_llm_not_found(tmp_path: Path) -> None:
    """get_llm returns None for a non-existent name."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        assert get_llm(conn, "nonexistent") is None
    finally:
        conn.close()


@pytest.mark.unit
def test_insert_remote_llm_with_costs(tmp_path: Path) -> None:
    """Insert a remote LLM with cost info and api_key_env."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        entry = _make_entry(
            name="claude-api",
            provider="anthropic",
            model="claude-3-opus",
            source="remote",
            base_url="https://api.anthropic.com",
            api_key_env="ANTHROPIC_API_KEY",
            input_cost=15.0,
            output_cost=75.0,
        )
        insert_llm(conn, entry)

        retrieved = get_llm(conn, "claude-api")
        assert retrieved is not None
        assert retrieved.source == "remote"
        assert retrieved.api_key_env == "ANTHROPIC_API_KEY"
        assert retrieved.input_cost_per_mtok == 15.0
        assert retrieved.output_cost_per_mtok == 75.0
    finally:
        conn.close()


# ── Duplicate name ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_insert_duplicate_raises(tmp_path: Path) -> None:
    """Inserting two LLMs with the same name raises DuplicateNameError."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        entry = _make_entry()
        insert_llm(conn, entry)

        with pytest.raises(DuplicateNameError, match="already exists"):
            insert_llm(conn, entry)
    finally:
        conn.close()


# ── List ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_llms_empty(tmp_path: Path) -> None:
    """list_llms returns an empty list on a fresh database."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        assert list_llms(conn) == []
    finally:
        conn.close()


@pytest.mark.unit
def test_list_llms_ordered(tmp_path: Path) -> None:
    """list_llms returns entries ordered alphabetically by name."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        insert_llm(conn, _make_entry(name="zeta-model", model="z:1b"))
        insert_llm(conn, _make_entry(name="alpha-model", model="a:1b"))
        insert_llm(conn, _make_entry(name="mid-model", model="m:1b"))

        entries = list_llms(conn)
        assert len(entries) == 3
        names = [e.name for e in entries]
        assert names == ["alpha-model", "mid-model", "zeta-model"]
    finally:
        conn.close()


# ── Delete ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_delete_llm(tmp_path: Path) -> None:
    """delete_llm removes the entry from the database."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        insert_llm(conn, _make_entry())
        assert get_llm(conn, "codestral-local") is not None

        delete_llm(conn, "codestral-local")
        assert get_llm(conn, "codestral-local") is None
    finally:
        conn.close()


@pytest.mark.unit
def test_delete_llm_nonexistent(tmp_path: Path) -> None:
    """delete_llm on a non-existent name does not raise."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        delete_llm(conn, "nonexistent")  # Should not raise
    finally:
        conn.close()


# ── Update stats ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_update_llm_stats_no_op(tmp_path: Path) -> None:
    """update_llm_stats runs without error (placeholder for future)."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        insert_llm(conn, _make_entry())
        # Should not raise — currently a no-op.
        update_llm_stats(conn, "codestral-local", vram_mib=12000, throughput_tps=42.5)
    finally:
        conn.close()


# ── api_key_env stored correctly ─────────────────────────────────────────────


@pytest.mark.unit
def test_api_key_env_stored_not_value(tmp_path: Path) -> None:
    """api_key_env stores the env var NAME, not the actual key value."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        entry = _make_entry(
            name="openai-gpt",
            provider="openai",
            model="gpt-4o",
            source="remote",
            api_key_env="OPENAI_API_KEY",
        )
        insert_llm(conn, entry)

        # Verify at the raw SQL level that we stored the env var name.
        cursor = conn.execute("SELECT api_key_env FROM llms WHERE name = ?", ("openai-gpt",))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "OPENAI_API_KEY"
    finally:
        conn.close()
