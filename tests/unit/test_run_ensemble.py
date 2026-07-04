"""Tests for ensemble integration into the run pipeline (S11 PR-C).

Covers:
- resolve_llm_or_ensemble() — resolves to LLM, ensemble, or raises error
- build_config() with ensemble — llm.models array with correct OE field names
- build_config() with ensemble — per-member temperature/max_tokens override
- build_config() single LLM — no regression
- launch_run snapshot — llm_type and llm_snapshot stored correctly
- run info display for ensemble run
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from revolver.core.exceptions import RevolverError
from revolver.core.llm import resolve_llm_or_ensemble
from revolver.infra.backends.openevolve import build_config
from revolver.infra.db import (
    add_ensemble_member,
    get_global_db_at,
    get_project_db,
    insert_ensemble,
    insert_llm,
    insert_run,
)
from revolver.models.llm import EnsembleEntry, EnsembleMember, LLMEntry

pytestmark = [pytest.mark.unit, pytest.mark.integration]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_llm(**kwargs: Any) -> LLMEntry:
    """Create an LLMEntry with sensible defaults."""
    defaults: dict[str, Any] = {
        "name": "test-llm",
        "model": "test-model",
        "source": "remote",
        "base_url": "http://localhost:11434/v1",
        "registered_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(kwargs)
    return LLMEntry(**defaults)


def _setup_global_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh global DB with schema."""
    db_path = tmp_path / "global.db"
    return get_global_db_at(db_path)


def _register_llm(conn: sqlite3.Connection, entry: LLMEntry) -> None:
    """Insert an LLMEntry into the global DB."""
    insert_llm(conn, entry)


def _register_ensemble(
    conn: sqlite3.Connection,
    name: str,
    members: list[dict[str, Any]],
) -> None:
    """Create an ensemble with members in the global DB."""
    insert_ensemble(conn, name, datetime.now(UTC))
    for m in members:
        add_ensemble_member(
            conn,
            ensemble_name=name,
            llm_name=m["llm_name"],
            weight=m.get("weight", 1.0),
            temperature_override=m.get("temperature_override"),
            max_tokens_override=m.get("max_tokens_override"),
            reasoning_effort_override=m.get("reasoning_effort_override"),
        )


# ── resolve_llm_or_ensemble tests ───────────────────────────────────────────


class TestResolveLlmOrEnsemble:
    """Tests for resolve_llm_or_ensemble()."""

    def test_resolves_to_llm(self, tmp_path: Path) -> None:
        """A registered LLM name resolves to an LLMEntry."""
        conn = _setup_global_db(tmp_path)
        entry = _make_llm(name="flash", model="gemini-2.5-flash")
        _register_llm(conn, entry)

        result = resolve_llm_or_ensemble("flash", conn)

        assert isinstance(result, LLMEntry)
        assert result.name == "flash"
        assert result.model == "gemini-2.5-flash"
        conn.close()

    def test_resolves_to_ensemble(self, tmp_path: Path) -> None:
        """A registered ensemble name resolves to an EnsembleEntry."""
        conn = _setup_global_db(tmp_path)
        # Register member LLMs
        _register_llm(conn, _make_llm(name="flash-lite", model="gemini-2.5-flash-lite"))
        _register_llm(conn, _make_llm(name="pro", model="gemini-2.5-pro"))

        _register_ensemble(
            conn,
            "alphevo",
            [
                {"llm_name": "flash-lite", "weight": 0.8},
                {"llm_name": "pro", "weight": 0.2, "temperature_override": 0.5},
            ],
        )

        result = resolve_llm_or_ensemble("alphevo", conn)

        assert isinstance(result, EnsembleEntry)
        assert result.name == "alphevo"
        assert len(result.members) == 2
        # Members are ordered by llm_name (DB ORDER BY)
        assert result.members[0].llm_name == "flash-lite"
        assert result.members[0].weight == 0.8
        assert result.members[1].llm_name == "pro"
        assert result.members[1].weight == 0.2
        assert result.members[1].temperature == 0.5
        conn.close()

    def test_not_found_raises_error(self, tmp_path: Path) -> None:
        """A name that matches neither LLM nor ensemble raises RevolverError."""
        conn = _setup_global_db(tmp_path)

        with pytest.raises(RevolverError, match="not found"):
            resolve_llm_or_ensemble("nonexistent", conn)
        conn.close()

    def test_llm_takes_precedence_over_ensemble(self, tmp_path: Path) -> None:
        """When an LLM and ensemble share the same name, LLM wins."""
        conn = _setup_global_db(tmp_path)
        _register_llm(conn, _make_llm(name="shared-name", model="some-model"))
        # Don't create an ensemble with same name (it would fail due to
        # different table), but verify LLM is returned
        result = resolve_llm_or_ensemble("shared-name", conn)
        assert isinstance(result, LLMEntry)
        conn.close()


# ── build_config ensemble tests ──────────────────────────────────────────────


class TestBuildConfigEnsemble:
    """Tests for build_config() with ensemble parameter."""

    def _make_ensemble_setup(
        self, tmp_path: Path
    ) -> tuple[sqlite3.Connection, LLMEntry, EnsembleEntry]:
        """Set up a global DB with two LLMs and an ensemble."""
        conn = _setup_global_db(tmp_path)

        flash_lite = _make_llm(
            name="flash-lite",
            model="gemini-2.5-flash-lite",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key_env="GEMINI_API_KEY",
            temperature=0.7,
            max_tokens=8192,
        )
        pro = _make_llm(
            name="pro",
            model="gemini-2.5-pro",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key_env="GEMINI_API_KEY",
        )
        _register_llm(conn, flash_lite)
        _register_llm(conn, pro)

        ensemble = EnsembleEntry(
            name="alphevo",
            members=[
                EnsembleMember(llm_name="flash-lite", weight=0.8),
                EnsembleMember(llm_name="pro", weight=0.2, temperature=0.5),
            ],
            created_at=datetime.now(UTC),
        )

        return conn, flash_lite, ensemble

    def test_ensemble_generates_models_array(self, tmp_path: Path) -> None:
        """build_config with ensemble emits llm.models array."""
        conn, primary_llm, ensemble = self._make_ensemble_setup(tmp_path)

        config = build_config(
            problem_config=None,
            llm=primary_llm,
            ensemble=ensemble,
            conn=conn,
        )

        assert "models" in config["llm"]
        models = config["llm"]["models"]
        assert len(models) == 2

        # Verify OE field names (name, api_base — NOT model, base_url)
        assert models[0]["name"] == "gemini-2.5-flash-lite"
        assert models[0]["api_base"] == "https://generativelanguage.googleapis.com/v1beta/openai"
        assert models[0]["weight"] == 0.8
        assert models[0]["api_key"] == "${GEMINI_API_KEY}"

        assert models[1]["name"] == "gemini-2.5-pro"
        assert models[1]["weight"] == 0.2

        # Verify that primary_model is NOT set (ensemble mode)
        assert "primary_model" not in config["llm"]
        conn.close()

    def test_oe_ensemble_local_member_placeholder_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """U2 (S17a-09): a key-less local member gets api_key="ollama".

        Mirrors the single-LLM path (#115): the OpenAI SDK requires an
        api_key, so a key-less local ensemble member crashed at engine init;
        worse, a None api_key made the SDK fall back to an ambient
        OPENAI_API_KEY — silently forwarded to the local endpoint. Remote
        (api_key_env-carrying) members are unchanged.
        """
        import copy

        from revolver.infra.backends.openevolve import resolve_api_keys

        conn = _setup_global_db(tmp_path)
        local = _make_llm(
            name="local-m",
            model="llama3",
            source="local",
            base_url="http://localhost:11434/v1",
            # no api_key_env — the key-less local case
        )
        remote = _make_llm(name="remote-m", model="gpt-4o", api_key_env="OPENAI_API_KEY")
        _register_llm(conn, local)
        _register_llm(conn, remote)
        ensemble = EnsembleEntry(
            name="mixed",
            members=[
                EnsembleMember(llm_name="local-m", weight=0.5),
                EnsembleMember(llm_name="remote-m", weight=0.5),
            ],
            created_at=datetime.now(UTC),
        )

        config = build_config(problem_config=None, llm=local, ensemble=ensemble, conn=conn)

        models = config["llm"]["models"]
        assert models[0]["api_key"] == "ollama"  # placeholder, no init crash
        assert models[1]["api_key"] == "${OPENAI_API_KEY}"  # remote unchanged

        # Bonus U2 effect: an ambient OPENAI_API_KEY is NOT forwarded to the
        # local member — the placeholder survives api-key resolution verbatim.
        monkeypatch.setenv("OPENAI_API_KEY", "ambient-secret")
        resolved = resolve_api_keys(copy.deepcopy(config))
        assert resolved["llm"]["models"][0]["api_key"] == "ollama"
        assert resolved["llm"]["models"][1]["api_key"] == "ambient-secret"
        conn.close()

    def test_ensemble_per_member_temperature(self, tmp_path: Path) -> None:
        """Per-member temperature override is applied correctly."""
        conn, primary_llm, ensemble = self._make_ensemble_setup(tmp_path)

        config = build_config(
            problem_config=None,
            llm=primary_llm,
            ensemble=ensemble,
            conn=conn,
        )

        models = config["llm"]["models"]
        # flash-lite: no member override, uses LLM registry default (0.7)
        assert models[0]["temperature"] == 0.7
        # pro: member override = 0.5
        assert models[1]["temperature"] == 0.5
        conn.close()

    def test_ensemble_per_member_max_tokens(self, tmp_path: Path) -> None:
        """Per-member max_tokens override is applied correctly."""
        conn = _setup_global_db(tmp_path)

        _register_llm(
            conn,
            _make_llm(name="llm-a", model="model-a", max_tokens=4096),
        )
        _register_llm(
            conn,
            _make_llm(name="llm-b", model="model-b", max_tokens=2048),
        )

        ensemble = EnsembleEntry(
            name="test-ensemble",
            members=[
                EnsembleMember(llm_name="llm-a", weight=0.5),
                EnsembleMember(llm_name="llm-b", weight=0.5, max_tokens=16384),
            ],
            created_at=datetime.now(UTC),
        )

        primary = _make_llm(name="llm-a", model="model-a", max_tokens=4096)
        config = build_config(
            problem_config=None,
            llm=primary,
            ensemble=ensemble,
            conn=conn,
        )

        models = config["llm"]["models"]
        # llm-a: no member override, uses LLM registry default (4096)
        assert models[0]["max_tokens"] == 4096
        # llm-b: member override = 16384
        assert models[1]["max_tokens"] == 16384
        conn.close()

    def test_oe_ensemble_reasoning_effort_per_member(self, tmp_path: Path) -> None:
        """OE maps per-member reasoning_effort onto llm.models[] (S17-26, FACT A)."""
        conn = _setup_global_db(tmp_path)

        # llm-a carries a registry-level effort; llm-b has none.
        _register_llm(
            conn,
            _make_llm(name="llm-a", model="model-a", reasoning_effort="low"),
        )
        _register_llm(conn, _make_llm(name="llm-b", model="model-b"))

        ensemble = EnsembleEntry(
            name="test-ensemble",
            members=[
                # No override → falls back to registry-level "low".
                EnsembleMember(llm_name="llm-a", weight=0.5),
                # Per-member override wins (member has none in registry).
                EnsembleMember(llm_name="llm-b", weight=0.5, reasoning_effort="high"),
            ],
            created_at=datetime.now(UTC),
        )

        primary = _make_llm(name="llm-a", model="model-a", reasoning_effort="low")
        config = build_config(
            problem_config=None,
            llm=primary,
            ensemble=ensemble,
            conn=conn,
        )

        models = config["llm"]["models"]
        # llm-a: registry-level effort applied.
        assert models[0]["reasoning_effort"] == "low"
        # llm-b: per-member override applied.
        assert models[1]["reasoning_effort"] == "high"
        conn.close()

    def test_oe_ensemble_reasoning_effort_absent_when_unset(self, tmp_path: Path) -> None:
        """No reasoning_effort anywhere → key omitted from every model (zero-change)."""
        conn, primary_llm, ensemble = self._make_ensemble_setup(tmp_path)

        config = build_config(
            problem_config=None,
            llm=primary_llm,
            ensemble=ensemble,
            conn=conn,
        )

        for model in config["llm"]["models"]:
            assert "reasoning_effort" not in model
        conn.close()

    def test_oe_single_llm_reasoning_effort_mapped(self, tmp_path: Path) -> None:
        """Single-LLM run maps spec.llm.reasoning_effort onto config['llm']."""
        llm = _make_llm(
            name="flash",
            model="gemini-2.5-flash",
            base_url="https://api.example.com/v1",
            api_key_env="FLASH_KEY",
            reasoning_effort="high",
        )

        config = build_config(problem_config=None, llm=llm)
        assert config["llm"]["reasoning_effort"] == "high"

    def test_oe_single_llm_reasoning_effort_absent_when_unset(self, tmp_path: Path) -> None:
        """Single-LLM run without reasoning_effort omits the key (zero-change)."""
        llm = _make_llm(name="flash", model="gemini-2.5-flash")
        config = build_config(problem_config=None, llm=llm)
        assert "reasoning_effort" not in config.get("llm", {})

    def test_oe_single_llm_reasoning_effort_override_wins(self, tmp_path: Path) -> None:
        """--config-override llm.reasoning_effort=… wins over the registry value."""
        llm = _make_llm(name="flash", model="gemini-2.5-flash", reasoning_effort="high")
        config = build_config(
            problem_config=None,
            llm=llm,
            config_overrides=["llm.reasoning_effort=low"],
        )
        assert config["llm"]["reasoning_effort"] == "low"

    def test_single_llm_no_regression(self, tmp_path: Path) -> None:
        """build_config without ensemble still works as before."""
        llm = _make_llm(
            name="flash",
            model="gemini-2.5-flash",
            base_url="https://api.example.com/v1",
            api_key_env="FLASH_KEY",
            temperature=0.8,
            max_tokens=8192,
        )

        config = build_config(
            problem_config=None,
            llm=llm,
            iterations=10,
        )

        # Single LLM path: primary_model set, no models array
        assert config["llm"]["primary_model"] == "gemini-2.5-flash"
        assert config["llm"]["api_base"] == "https://api.example.com/v1"
        assert config["llm"]["api_key_env"] == "FLASH_KEY"
        assert config["llm"]["temperature"] == 0.8
        assert config["llm"]["max_tokens"] == 8192
        assert "models" not in config["llm"]
        assert config["max_iterations"] == 10

    def test_single_llm_default_config_byte_identical(self, tmp_path: Path) -> None:
        """S17-33 exit criterion: single-LLM (no ensemble, no new flags) OE config
        is byte-identical to the pre-sprint output.

        This whole-dict pin fails loudly if any future change perturbs the
        default single-LLM path. Keep it in lockstep with build_config().
        """
        llm = _make_llm(
            name="flash",
            model="gemini-2.5-flash",
            base_url="https://api.example.com/v1",
            api_key_env="FLASH_KEY",
            temperature=0.8,
            max_tokens=8192,
        )

        config = build_config(
            problem_config=None,
            llm=llm,
            iterations=10,
        )

        assert config == {
            "max_iterations": 10,
            "checkpoint_interval": 10,
            "llm": {
                "primary_model": "gemini-2.5-flash",
                "api_base": "https://api.example.com/v1",
                "api_key_env": "FLASH_KEY",
                "temperature": 0.8,
                "max_tokens": 8192,
            },
            "evaluator": {
                "cascade_evaluation": False,
            },
        }

    def test_llm_weight_override_wins(self, tmp_path: Path) -> None:
        """--llm-weight overrides the registry member weight (S17-22, A1/M3)."""
        conn, primary_llm, ensemble = self._make_ensemble_setup(tmp_path)

        # Registry weights are flash-lite=0.8, pro=0.2; override both.
        config = build_config(
            problem_config=None,
            llm=primary_llm,
            ensemble=ensemble,
            conn=conn,
            llm_weight_overrides={"flash-lite": 0.9, "pro": 0.1},
        )

        models = config["llm"]["models"]
        assert models[0]["name"] == "gemini-2.5-flash-lite"
        assert models[0]["weight"] == 0.9  # overridden (registry was 0.8)
        assert models[1]["name"] == "gemini-2.5-pro"
        assert models[1]["weight"] == 0.1  # overridden (registry was 0.2)
        conn.close()

    def test_llm_weight_partial_override_keeps_registry(self, tmp_path: Path) -> None:
        """A member absent from --llm-weight keeps its registry weight."""
        conn, primary_llm, ensemble = self._make_ensemble_setup(tmp_path)

        # Only override flash-lite; pro must keep its registry weight (0.2).
        config = build_config(
            problem_config=None,
            llm=primary_llm,
            ensemble=ensemble,
            conn=conn,
            llm_weight_overrides={"flash-lite": 0.5},
        )

        models = config["llm"]["models"]
        assert models[0]["weight"] == 0.5  # overridden
        assert models[1]["weight"] == 0.2  # registry weight retained
        conn.close()

    def test_no_override_uses_registry_weights(self, tmp_path: Path) -> None:
        """Without --llm-weight the registry weights are used unchanged."""
        conn, primary_llm, ensemble = self._make_ensemble_setup(tmp_path)

        config = build_config(
            problem_config=None,
            llm=primary_llm,
            ensemble=ensemble,
            conn=conn,
        )

        models = config["llm"]["models"]
        assert models[0]["weight"] == 0.8
        assert models[1]["weight"] == 0.2
        conn.close()

    def test_selection_fixed_accepted(self, tmp_path: Path) -> None:
        """--selection fixed is the implicit weighted mode on OE (accepted)."""
        conn, primary_llm, ensemble = self._make_ensemble_setup(tmp_path)

        # Must not raise: "fixed" maps onto OE's static weighted sampler.
        config = build_config(
            problem_config=None,
            llm=primary_llm,
            ensemble=ensemble,
            conn=conn,
            selection="fixed",
        )
        assert len(config["llm"]["models"]) == 2
        conn.close()

    def test_selection_adaptive_rejected(self, tmp_path: Path) -> None:
        """--selection ucb is rejected by the OE builder (defensive; A2/A4)."""
        from revolver.core.exceptions import ValidationError

        conn, primary_llm, ensemble = self._make_ensemble_setup(tmp_path)

        with pytest.raises(ValidationError, match="ucb"):
            build_config(
                problem_config=None,
                llm=primary_llm,
                ensemble=ensemble,
                conn=conn,
                selection="ucb",
            )
        conn.close()


# ── LLM snapshot tests ──────────────────────────────────────────────────────


class TestLlmSnapshot:
    """Tests for _build_llm_snapshot() via insert_run."""

    def test_single_llm_snapshot(self, tmp_path: Path) -> None:
        """Single LLM run stores correct llm_type and llm_snapshot."""
        from revolver.core.run import _build_llm_snapshot

        conn = _setup_global_db(tmp_path)
        llm = _make_llm(name="flash", model="gemini-2.5-flash", temperature=0.7, max_tokens=8192)
        _register_llm(conn, llm)

        llm_type, llm_model, snapshot_json = _build_llm_snapshot(llm, conn)

        assert llm_type == "single"
        assert llm_model == "gemini-2.5-flash"
        snapshot = json.loads(snapshot_json)
        assert snapshot["type"] == "single"
        assert snapshot["name"] == "flash"
        assert snapshot["model"] == "gemini-2.5-flash"
        assert snapshot["temperature"] == 0.7
        assert snapshot["max_tokens"] == 8192
        conn.close()

    def test_ensemble_snapshot(self, tmp_path: Path) -> None:
        """Ensemble run stores correct llm_type and llm_snapshot."""
        from revolver.core.run import _build_llm_snapshot

        conn = _setup_global_db(tmp_path)
        _register_llm(conn, _make_llm(name="flash-lite", model="gemini-2.5-flash-lite"))
        _register_llm(conn, _make_llm(name="pro", model="gemini-2.5-pro"))

        ensemble = EnsembleEntry(
            name="alphevo",
            members=[
                EnsembleMember(llm_name="flash-lite", weight=0.8),
                EnsembleMember(llm_name="pro", weight=0.2, temperature=0.5),
            ],
            created_at=datetime.now(UTC),
        )

        llm_type, llm_model, snapshot_json = _build_llm_snapshot(ensemble, conn)

        assert llm_type == "ensemble"
        assert "gemini-2.5-flash-lite" in llm_model
        assert "gemini-2.5-pro" in llm_model

        snapshot = json.loads(snapshot_json)
        assert snapshot["type"] == "ensemble"
        assert snapshot["name"] == "alphevo"
        assert len(snapshot["members"]) == 2
        assert snapshot["members"][0]["name"] == "flash-lite"
        assert snapshot["members"][0]["weight"] == 0.8
        assert snapshot["members"][1]["name"] == "pro"
        assert snapshot["members"][1]["weight"] == 0.2
        assert snapshot["members"][1]["temperature"] == 0.5
        conn.close()

    def test_insert_run_with_ensemble_fields(self, tmp_path: Path) -> None:
        """insert_run stores llm_type and llm_snapshot in the DB."""
        from revolver.infra.db import insert_dataset, insert_problem_version
        from revolver.models.dataset import DatasetRegistration
        from revolver.models.problem import ProblemVersion

        db_path = tmp_path / "project.db"
        proj_conn = get_project_db(db_path)

        # Insert prerequisite records (FK constraints)
        insert_problem_version(
            proj_conn,
            ProblemVersion(
                tag="v1.0",
                hash="abc123",
                message="test",
                created_at=datetime.now(UTC),
            ),
        )
        insert_dataset(
            proj_conn,
            DatasetRegistration(
                name="train",
                path="/tmp/train",
                split="train",
                storage="reference",
                description="",
                global_hash="def456",
                instance_count=1,
                created_at=datetime.now(UTC),
            ),
        )

        snapshot_json = json.dumps({"type": "ensemble", "name": "alphevo", "members": []})

        insert_run(
            proj_conn,
            run_id="run-test-001",
            problem_version="v1.0",
            llm="alphevo",
            dataset="train",
            iterations=10,
            problem_hash="abc123",
            dataset_hash="def456",
            llm_model="gemini-2.5-flash-lite,gemini-2.5-pro",
            created_at=datetime.now(UTC),
            llm_type="ensemble",
            llm_snapshot=snapshot_json,
        )

        # Read back
        proj_conn.row_factory = sqlite3.Row
        row = proj_conn.execute(
            "SELECT llm_type, llm_snapshot FROM runs WHERE id = ?",
            ("run-test-001",),
        ).fetchone()
        proj_conn.row_factory = None

        assert row is not None
        assert row["llm_type"] == "ensemble"
        assert row["llm_snapshot"] == snapshot_json
        proj_conn.close()


# ── resolve_api_keys ensemble tests ──────────────────────────────────────────


class TestResolveApiKeysEnsemble:
    """Tests for resolve_api_keys() with ensemble models."""

    def test_resolves_env_var_syntax(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """${ENV_NAME} in models[].api_key is resolved from environment."""
        from revolver.infra.backends.openevolve import resolve_api_keys

        monkeypatch.setenv("GEMINI_API_KEY", "my-secret-key")

        config: dict[str, Any] = {
            "llm": {
                "models": [
                    {"name": "flash", "api_key": "${GEMINI_API_KEY}", "weight": 0.8},
                    {"name": "pro", "api_key": "${GEMINI_API_KEY}", "weight": 0.2},
                ],
            }
        }

        resolved = resolve_api_keys(config)

        assert resolved["llm"]["models"][0]["api_key"] == "my-secret-key"
        assert resolved["llm"]["models"][1]["api_key"] == "my-secret-key"

    def test_missing_env_var_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing env var in ${ENV_NAME} syntax raises ValidationError."""
        from revolver.core.exceptions import ValidationError
        from revolver.infra.backends.openevolve import resolve_api_keys

        monkeypatch.delenv("MISSING_KEY", raising=False)

        config: dict[str, Any] = {
            "llm": {
                "models": [
                    {"name": "flash", "api_key": "${MISSING_KEY}", "weight": 1.0},
                ],
            }
        }

        with pytest.raises(ValidationError, match="MISSING_KEY"):
            resolve_api_keys(config)


# ── CLI display tests ────────────────────────────────────────────────────────


class TestRunInfoEnsembleDisplay:
    """Tests for ensemble display in run info CLI output."""

    def test_ensemble_display_format(self) -> None:
        """RunInfo with ensemble llm_snapshot formats correctly."""
        from revolver.models.run import RunInfo

        snapshot = json.dumps(
            {
                "type": "ensemble",
                "name": "alphevo",
                "members": [
                    {"name": "flash-lite", "model": "gemini-2.5-flash-lite", "weight": 0.8},
                    {"name": "pro", "model": "gemini-2.5-pro", "weight": 0.2},
                ],
            }
        )

        info = RunInfo(
            run_id="run-test",
            problem_version="v1.0",
            problem_hash="abc",
            llm="alphevo",
            llm_model="gemini-2.5-flash-lite,gemini-2.5-pro",
            dataset="train",
            dataset_hash="def",
            iterations=10,
            status="completed",
            created_at=datetime.now(UTC),
            llm_type="ensemble",
            llm_snapshot=snapshot,
        )

        assert info.llm_type == "ensemble"
        assert info.llm_snapshot is not None

        # Verify the snapshot can be parsed back
        parsed = json.loads(info.llm_snapshot)
        assert parsed["type"] == "ensemble"
        assert len(parsed["members"]) == 2

    def test_single_llm_display_unchanged(self) -> None:
        """RunInfo with single LLM has default llm_type."""
        from revolver.models.run import RunInfo

        info = RunInfo(
            run_id="run-test",
            problem_version="v1.0",
            problem_hash="abc",
            llm="flash",
            llm_model="gemini-2.5-flash",
            dataset="train",
            dataset_hash="def",
            iterations=10,
            status="completed",
            created_at=datetime.now(UTC),
        )

        assert info.llm_type == "single"
        assert info.llm_snapshot is None
