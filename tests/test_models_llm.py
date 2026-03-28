"""L1 unit tests for revolver.models.llm — LLM Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from revolver.models.llm import (
    EnsembleEntry,
    EnsembleMember,
    LLMEntry,
    LLMStatus,
    LLMStatusReport,
    StartResult,
    StopResult,
)

# ── LLMEntry ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_llm_entry_valid() -> None:
    """LLMEntry validates with all fields provided."""
    entry = LLMEntry(
        name="codestral-local",
        provider="ollama",
        model="codestral:22b",
        source="local",
        base_url="http://localhost:11434",
        api_key_env=None,
        input_cost_per_mtok=None,
        output_cost_per_mtok=None,
        registered_at=datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
    )
    assert entry.name == "codestral-local"
    assert entry.source == "local"
    assert entry.model == "codestral:22b"


@pytest.mark.unit
def test_llm_entry_minimal() -> None:
    """LLMEntry validates with only required fields."""
    entry = LLMEntry(
        name="gpt4o",
        model="gpt-4o",
        source="remote",
        registered_at=datetime.now(UTC),
    )
    assert entry.provider is None
    assert entry.base_url is None
    assert entry.api_key_env is None
    assert entry.input_cost_per_mtok is None
    assert entry.output_cost_per_mtok is None


@pytest.mark.unit
def test_llm_entry_frozen() -> None:
    """LLMEntry is immutable (frozen)."""
    entry = LLMEntry(
        name="test",
        model="test-model",
        source="local",
        registered_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        entry.name = "changed"  # type: ignore[misc]


@pytest.mark.unit
def test_llm_entry_model_dump() -> None:
    """LLMEntry.model_dump() produces correct dict."""
    ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    entry = LLMEntry(
        name="claude-api",
        provider="anthropic",
        model="claude-3-opus",
        source="remote",
        base_url="https://api.anthropic.com",
        api_key_env="ANTHROPIC_API_KEY",
        input_cost_per_mtok=15.0,
        output_cost_per_mtok=75.0,
        registered_at=ts,
    )
    dumped = entry.model_dump()
    assert dumped["name"] == "claude-api"
    assert dumped["provider"] == "anthropic"
    assert dumped["model"] == "claude-3-opus"
    assert dumped["source"] == "remote"
    assert dumped["base_url"] == "https://api.anthropic.com"
    assert dumped["api_key_env"] == "ANTHROPIC_API_KEY"
    assert dumped["input_cost_per_mtok"] == 15.0
    assert dumped["output_cost_per_mtok"] == 75.0
    assert dumped["registered_at"] == ts


@pytest.mark.unit
def test_llm_entry_from_dict() -> None:
    """LLMEntry.model_validate() works from a raw dict."""
    data = {
        "name": "local-llama",
        "model": "llama3:8b",
        "source": "local",
        "registered_at": "2026-03-14T10:00:00Z",
    }
    entry = LLMEntry.model_validate(data)
    assert entry.name == "local-llama"
    assert entry.model == "llama3:8b"


# ── LLMStatus ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_llm_status_valid() -> None:
    """LLMStatus validates correctly."""
    status = LLMStatus(
        name="codestral-local",
        source="local",
        status="loaded",
        vram_mib=12000,
    )
    assert status.status == "loaded"
    assert status.vram_mib == 12000


@pytest.mark.unit
def test_llm_status_frozen() -> None:
    """LLMStatus is immutable."""
    status = LLMStatus(name="test", source="local", status="stopped")
    with pytest.raises(ValidationError):
        status.status = "loaded"  # type: ignore[misc]


# ── StartResult ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_start_result_valid() -> None:
    """StartResult validates with all fields."""
    result = StartResult(
        name="codestral-local",
        model="codestral:22b",
        vram_mib=12000,
        health_ok=True,
        previous_unloaded="llama3:8b",
    )
    assert result.health_ok is True
    assert result.previous_unloaded == "llama3:8b"


@pytest.mark.unit
def test_start_result_defaults() -> None:
    """StartResult defaults are correct."""
    result = StartResult(name="test", model="test-model")
    assert result.vram_mib is None
    assert result.health_ok is False
    assert result.previous_unloaded is None


@pytest.mark.unit
def test_start_result_frozen() -> None:
    """StartResult is immutable."""
    result = StartResult(name="test", model="test-model")
    with pytest.raises(ValidationError):
        result.health_ok = True  # type: ignore[misc]


# ── StopResult ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_stop_result_valid() -> None:
    """StopResult validates correctly."""
    result = StopResult(name="test", model="test-model", was_loaded=True)
    assert result.was_loaded is True


@pytest.mark.unit
def test_stop_result_default() -> None:
    """StopResult.was_loaded defaults to True."""
    result = StopResult(name="test", model="test-model")
    assert result.was_loaded is True


@pytest.mark.unit
def test_stop_result_frozen() -> None:
    """StopResult is immutable."""
    result = StopResult(name="test", model="test-model")
    with pytest.raises(ValidationError):
        result.was_loaded = False  # type: ignore[misc]


# ── LLMStatusReport ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_llm_status_report_valid() -> None:
    """LLMStatusReport validates with full data."""
    report = LLMStatusReport(
        llms=[
            LLMStatus(name="a", source="local", status="loaded", vram_mib=1024),
            LLMStatus(name="b", source="remote", status="ready"),
        ],
        gpu={"name": "RTX 5090", "vram_used_mib": 1024, "vram_total_mib": 32768},
        ollama_running=True,
    )
    assert len(report.llms) == 2
    assert report.gpu is not None
    assert report.gpu["name"] == "RTX 5090"
    assert report.ollama_running is True


@pytest.mark.unit
def test_llm_status_report_defaults() -> None:
    """LLMStatusReport defaults are correct."""
    report = LLMStatusReport(llms=[])
    assert report.gpu is None
    assert report.ollama_running is False


@pytest.mark.unit
def test_llm_status_report_frozen() -> None:
    """LLMStatusReport is immutable."""
    report = LLMStatusReport(llms=[])
    with pytest.raises(ValidationError):
        report.ollama_running = True  # type: ignore[misc]


@pytest.mark.unit
def test_llm_status_report_model_dump() -> None:
    """LLMStatusReport.model_dump() serializes cleanly."""
    report = LLMStatusReport(
        llms=[LLMStatus(name="x", source="local", status="stopped")],
        ollama_running=False,
    )
    dumped = report.model_dump()
    assert len(dumped["llms"]) == 1
    assert dumped["llms"][0]["name"] == "x"
    assert dumped["ollama_running"] is False


# ── EnsembleMember ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ensemble_member_valid() -> None:
    """EnsembleMember validates with all fields provided."""
    member = EnsembleMember(
        llm_name="flash-lite",
        weight=0.8,
        temperature=0.5,
        max_tokens=4096,
    )
    assert member.llm_name == "flash-lite"
    assert member.weight == 0.8
    assert member.temperature == 0.5
    assert member.max_tokens == 4096


@pytest.mark.unit
def test_ensemble_member_defaults() -> None:
    """EnsembleMember defaults are correct."""
    member = EnsembleMember(llm_name="pro")
    assert member.weight == 1.0
    assert member.temperature is None
    assert member.max_tokens is None


@pytest.mark.unit
def test_ensemble_member_frozen() -> None:
    """EnsembleMember is immutable."""
    member = EnsembleMember(llm_name="pro")
    with pytest.raises(ValidationError):
        member.weight = 0.5  # type: ignore[misc]


@pytest.mark.unit
def test_ensemble_member_model_dump() -> None:
    """EnsembleMember.model_dump() produces correct dict."""
    member = EnsembleMember(llm_name="flash", weight=0.6, temperature=0.3)
    dumped = member.model_dump()
    assert dumped["llm_name"] == "flash"
    assert dumped["weight"] == 0.6
    assert dumped["temperature"] == 0.3
    assert dumped["max_tokens"] is None


# ── EnsembleEntry ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ensemble_entry_valid() -> None:
    """EnsembleEntry validates with all fields."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    entry = EnsembleEntry(
        name="alphevo",
        members=[
            EnsembleMember(llm_name="flash-lite", weight=0.8),
            EnsembleMember(llm_name="pro", weight=0.2, temperature=0.5),
        ],
        created_at=ts,
    )
    assert entry.name == "alphevo"
    assert len(entry.members) == 2
    assert entry.members[0].llm_name == "flash-lite"
    assert entry.members[1].temperature == 0.5


@pytest.mark.unit
def test_ensemble_entry_empty_members() -> None:
    """EnsembleEntry can have an empty members list."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    entry = EnsembleEntry(name="empty", members=[], created_at=ts)
    assert entry.members == []


@pytest.mark.unit
def test_ensemble_entry_frozen() -> None:
    """EnsembleEntry is immutable."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    entry = EnsembleEntry(name="test", members=[], created_at=ts)
    with pytest.raises(ValidationError):
        entry.name = "changed"  # type: ignore[misc]


@pytest.mark.unit
def test_ensemble_entry_model_dump() -> None:
    """EnsembleEntry.model_dump() serializes cleanly."""
    ts = datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC)
    entry = EnsembleEntry(
        name="alphevo",
        members=[EnsembleMember(llm_name="flash", weight=1.0)],
        created_at=ts,
    )
    dumped = entry.model_dump()
    assert dumped["name"] == "alphevo"
    assert len(dumped["members"]) == 1
    assert dumped["members"][0]["llm_name"] == "flash"
    assert dumped["created_at"] == ts


@pytest.mark.unit
def test_ensemble_entry_from_dict() -> None:
    """EnsembleEntry.model_validate() works from a raw dict."""
    data = {
        "name": "test-ens",
        "members": [
            {"llm_name": "a", "weight": 0.5},
            {"llm_name": "b", "weight": 0.5},
        ],
        "created_at": "2026-03-28T10:00:00Z",
    }
    entry = EnsembleEntry.model_validate(data)
    assert entry.name == "test-ens"
    assert len(entry.members) == 2
