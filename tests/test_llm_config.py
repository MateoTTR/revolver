"""L1 unit tests for LLM per-model config (max_tokens, timeout_s) — Sprint 006c.

Covers:
- LLMEntry with max_tokens/timeout_s round-trips correctly (model + DB)
- build_config() injects values from LLMEntry
- --config-override wins over LLM registry values
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.infra.backends.openevolve import DEFAULT_LOCAL_LLM_TIMEOUT_S, build_config
from revolver.infra.db import get_global_db_at, get_llm, insert_llm, list_llms
from revolver.models.llm import LLMEntry

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_entry(
    name: str = "test-llm",
    *,
    max_tokens: int | None = None,
    timeout_s: int | None = None,
) -> LLMEntry:
    return LLMEntry(
        name=name,
        provider="anthropic",
        model="claude-3-opus",
        source="remote",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        registered_at=datetime(2026, 3, 20, 10, 0, 0, tzinfo=UTC),
    )


def _make_llm(**kwargs: object) -> LLMEntry:
    defaults: dict[str, object] = {
        "name": "test-llm",
        "model": "test-model",
        "source": "remote",
        "base_url": "http://localhost:11434/v1",
        "registered_at": datetime(2026, 1, 1),
    }
    defaults.update(kwargs)
    return LLMEntry(**defaults)  # type: ignore[arg-type]


# ── LLMEntry model tests ────────────────────────────────────────────────────


@pytest.mark.unit
def test_llm_entry_max_tokens_and_timeout() -> None:
    """LLMEntry stores max_tokens and timeout_s correctly."""
    entry = _make_entry(max_tokens=8192, timeout_s=120)
    assert entry.max_tokens == 8192
    assert entry.timeout_s == 120


@pytest.mark.unit
def test_llm_entry_max_tokens_defaults_to_none() -> None:
    """LLMEntry defaults max_tokens and timeout_s to None."""
    entry = _make_entry()
    assert entry.max_tokens is None
    assert entry.timeout_s is None


@pytest.mark.unit
def test_llm_entry_model_dump_includes_new_fields() -> None:
    """model_dump includes max_tokens and timeout_s."""
    entry = _make_entry(max_tokens=4096, timeout_s=60)
    dumped = entry.model_dump()
    assert dumped["max_tokens"] == 4096
    assert dumped["timeout_s"] == 60


# ── DB round-trip tests ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_db_insert_and_get_with_config(tmp_path: Path) -> None:
    """Round-trip: insert an LLM with max_tokens/timeout_s then retrieve."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        entry = _make_entry(max_tokens=8192, timeout_s=120)
        insert_llm(conn, entry)

        retrieved = get_llm(conn, "test-llm")
        assert retrieved is not None
        assert retrieved.max_tokens == 8192
        assert retrieved.timeout_s == 120
    finally:
        conn.close()


@pytest.mark.unit
def test_db_insert_without_config(tmp_path: Path) -> None:
    """LLM inserted without config has None for max_tokens/timeout_s."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        entry = _make_entry()
        insert_llm(conn, entry)

        retrieved = get_llm(conn, "test-llm")
        assert retrieved is not None
        assert retrieved.max_tokens is None
        assert retrieved.timeout_s is None
    finally:
        conn.close()


@pytest.mark.unit
def test_db_list_with_config(tmp_path: Path) -> None:
    """list_llms returns entries with max_tokens/timeout_s preserved."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    try:
        insert_llm(conn, _make_entry(name="a", max_tokens=1000))
        insert_llm(conn, _make_entry(name="b", timeout_s=30))

        entries = list_llms(conn)
        by_name = {e.name: e for e in entries}
        assert by_name["a"].max_tokens == 1000
        assert by_name["a"].timeout_s is None
        assert by_name["b"].max_tokens is None
        assert by_name["b"].timeout_s == 30
    finally:
        conn.close()


# ── build_config injection tests ─────────────────────────────────────────────


@pytest.mark.unit
def test_build_config_injects_max_tokens() -> None:
    """build_config injects max_tokens from LLMEntry."""
    llm = _make_llm(max_tokens=8192)
    result = build_config(problem_config=None, llm=llm)
    assert result["llm"]["max_tokens"] == 8192


@pytest.mark.unit
def test_build_config_injects_timeout() -> None:
    """build_config injects timeout from LLMEntry."""
    llm = _make_llm(timeout_s=120)
    result = build_config(problem_config=None, llm=llm)
    assert result["llm"]["timeout"] == 120


@pytest.mark.unit
def test_build_config_no_injection_when_none() -> None:
    """build_config does not inject max_tokens/timeout when None."""
    llm = _make_llm()
    result = build_config(problem_config=None, llm=llm)
    assert "max_tokens" not in result.get("llm", {})
    assert "timeout" not in result.get("llm", {})


@pytest.mark.unit
def test_build_config_override_wins_over_llm_config() -> None:
    """--config-override key=value wins over LLM registry values."""
    llm = _make_llm(max_tokens=8192, timeout_s=120)
    result = build_config(
        problem_config=None,
        llm=llm,
        config_overrides=["llm.max_tokens=4096", "llm.timeout=60"],
    )
    # Config overrides (step 5) should win over LLM config (step 2b)
    assert result["llm"]["max_tokens"] == 4096
    assert result["llm"]["timeout"] == 60


# ── #307: slow-local-endpoint default timeout ────────────────────────────────


@pytest.mark.unit
def test_build_config_local_default_timeout() -> None:
    """#307: a --source local LLM without explicit timeout gets the raised default."""
    llm = _make_llm(source="local")
    result = build_config(problem_config=None, llm=llm)
    assert result["llm"]["timeout"] == DEFAULT_LOCAL_LLM_TIMEOUT_S


@pytest.mark.unit
def test_build_config_remote_no_default_timeout() -> None:
    """#307: a remote LLM keeps OpenEvolve's own default (no timeout injected)."""
    llm = _make_llm(source="remote")
    result = build_config(problem_config=None, llm=llm)
    assert "timeout" not in result.get("llm", {})


@pytest.mark.unit
def test_build_config_local_explicit_timeout_wins() -> None:
    """#307: an explicit LLMEntry.timeout_s wins over the local default."""
    llm = _make_llm(source="local", timeout_s=120)
    result = build_config(problem_config=None, llm=llm)
    assert result["llm"]["timeout"] == 120


@pytest.mark.unit
def test_build_config_local_timeout_override_wins() -> None:
    """#307: --config-override llm.timeout=… still wins over the local default."""
    llm = _make_llm(source="local")
    result = build_config(
        problem_config=None,
        llm=llm,
        config_overrides=["llm.timeout=45"],
    )
    assert result["llm"]["timeout"] == 45


# ── DB migration test ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_db_migration_v3_to_v4(tmp_path: Path) -> None:
    """Migration v3->v4 preserves existing data and adds new columns."""
    import sqlite3

    db_path = tmp_path / "global.db"

    # Create a v3 schema database manually
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""\
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            applied_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS llms (
            name            TEXT PRIMARY KEY,
            provider        TEXT,
            model           TEXT NOT NULL,
            source          TEXT NOT NULL CHECK (source IN ('local', 'remote')),
            base_url        TEXT,
            api_key_env     TEXT,
            input_cost_per_mtok  REAL,
            output_cost_per_mtok REAL,
            registered_at   TEXT NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (3, '2026-03-20T00:00:00')"
    )
    # Insert a v3 LLM entry (no max_tokens/timeout_s columns)
    conn.execute(
        "INSERT INTO llms (name, provider, model, source, base_url, "
        "api_key_env, input_cost_per_mtok, output_cost_per_mtok, registered_at) "
        "VALUES ('old-llm', 'ollama', 'test:7b', 'local', 'http://localhost:11434', "
        "NULL, NULL, NULL, '2026-03-19T10:00:00')"
    )
    conn.commit()
    conn.close()

    # Now open via get_global_db_at which runs migrations
    conn = get_global_db_at(db_path)
    try:
        # Verify the old entry survived and has the new columns
        retrieved = get_llm(conn, "old-llm")
        assert retrieved is not None
        assert retrieved.name == "old-llm"
        assert retrieved.model == "test:7b"
        assert retrieved.max_tokens is None
        assert retrieved.timeout_s is None

        # Verify we can insert with the new columns
        new_entry = _make_entry(name="new-llm", max_tokens=4096, timeout_s=30)
        insert_llm(conn, new_entry)
        retrieved_new = get_llm(conn, "new-llm")
        assert retrieved_new is not None
        assert retrieved_new.max_tokens == 4096
        assert retrieved_new.timeout_s == 30
    finally:
        conn.close()
