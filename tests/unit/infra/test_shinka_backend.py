"""Unit tests for the ShinkaBackend config + engine tiers (S14, ADR-007).

Covers S14-05..13: the ``default_output_subdir`` protocol seam, the
backend-delegated crash-status counting, ``is_available()``,
``config_template()``, ``validate_config()``, ``build_config()`` (LLM
projection per ADR-007 D5), ``resolved_config()``, ``generate_wrapper()``
(R4 risk materializer), the engine tier (``launch()``/``resume()`` with a
fake ``ShinkaEvolveRunner``), and the ``programs.sqlite`` reading methods
(``collect_token_usage``/``parse_population``/``count_valid``/
``read_progress``).

All tests run WITHOUT shinka installed: availability-dependent paths use
fake ``shinka.*`` modules injected into ``sys.modules``, the wrapper
execution tests exercise the generated script's standalone fallback, and
the DB-reading tests use the shared fixture factory (the install-gated
contract twins live in ``tests/integration/test_shinka_db.py``; the unit
twins keep the engine-tier code covered on the shinka-less CI env).
"""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from typing import Any

import pytest
import yaml

from revolver.core.exceptions import (
    EvaluatorLoadError,
    ExternalError,
    RevolverError,
    ValidationError,
)
from revolver.core.run import _determine_crash_status
from revolver.infra.backends.base import (
    BackendRunSpec,
    BackendUnavailableError,
)
from revolver.infra.backends.openevolve import OpenEvolveBackend
from revolver.infra.backends.shinka import (
    SHINKA_PROGRAMS_DB,
    SHINKA_WRAPPER_FILENAME,
    ShinkaBackend,
)
from revolver.infra.db import get_global_db_at, insert_llm
from revolver.models.llm import EnsembleEntry, EnsembleMember, LLMEntry
from tests.fixtures.programs_sqlite import (
    EXPECTED_BEST_SCORE,
    EXPECTED_COMPLETION_TOKENS,
    EXPECTED_LAST_GENERATION,
    EXPECTED_PROMPT_TOKENS,
    EXPECTED_RANKED_IDS,
    EXPECTED_VALID_COUNT,
    FIXTURE_PROGRAM_ROWS,
    build_programs_db,
    build_shinka_run_dir,
)

pytestmark = [pytest.mark.unit]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_llm(**kwargs: object) -> LLMEntry:
    """Create an LLMEntry with sensible defaults (local Ollama shape)."""
    defaults: dict[str, Any] = {
        "name": "test-llm",
        "model": "llama3",
        "source": "local",
        "base_url": "http://localhost:11434/v1",
        "registered_at": datetime(2026, 1, 1),
    }
    defaults.update(kwargs)
    return LLMEntry(**defaults)


def _make_spec(tmp_path: Path, **kwargs: Any) -> BackendRunSpec:
    """Create a BackendRunSpec with snapshot and run directories."""
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir(exist_ok=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    defaults: dict[str, Any] = {
        "snapshot_dir": snapshot_dir,
        "llm": _make_llm(),
        "run_dir": run_dir,
    }
    defaults.update(kwargs)
    return BackendRunSpec(**defaults)


@dataclasses.dataclass
class _FakeEvolutionConfig:
    """Field-name stand-in for shinka.core.EvolutionConfig (0.0.7 subset)."""

    task_sys_msg: str | None = None
    patch_types: list[str] = dataclasses.field(default_factory=list)
    patch_type_probs: list[float] = dataclasses.field(default_factory=list)
    num_generations: int = 50
    job_type: str = "local"
    language: str = "python"
    llm_models: list[str] = dataclasses.field(default_factory=list)
    llm_dynamic_selection: str | None = "ucb"
    llm_kwargs: dict[str, Any] = dataclasses.field(default_factory=dict)
    embedding_model: str | None = None
    init_program_path: str | None = "initial.py"
    results_dir: str | None = None
    max_api_costs: float | None = None
    max_patch_attempts: int = 1


@dataclasses.dataclass
class _FakeDatabaseConfig:
    """Field-name stand-in for shinka.database.DatabaseConfig (subset)."""

    db_path: str | None = None
    num_islands: int = 2
    archive_size: int = 40
    migration_interval: int = 10
    parent_selection_strategy: str = "weighted"


@dataclasses.dataclass
class _FakeLocalJobConfig:
    """Field-name stand-in for shinka.launch.LocalJobConfig (subset).

    Deliberately has NO ``max_proposal_jobs`` field, matching the real
    shinka 0.0.7 schema (verified by introspection — spike #320 §4): the
    value is a ``ShinkaEvolveRunner`` constructor kwarg, popped out of the
    job section and threaded to the runner by ``_run_engine`` (R1 / #253).
    """

    eval_program_path: str | None = "evaluate.py"
    extra_cmd_args: dict[str, Any] = dataclasses.field(default_factory=dict)
    time: str | None = None
    conda_env: str | None = None


# Matches shinka 0.0.7's hard-coded default (shinka/llm/constants.py:1) —
# spike #320 §3.2 L1. The R2 lever tests assert set/restore against it.
_FAKE_SHINKA_DEFAULT_TIMEOUT = 1200


@pytest.fixture
def fake_shinka(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject fake ``shinka.*`` modules so availability checks succeed."""
    pkg = types.ModuleType("shinka")
    core = types.ModuleType("shinka.core")
    core.EvolutionConfig = _FakeEvolutionConfig  # type: ignore[attr-defined]
    database = types.ModuleType("shinka.database")
    database.DatabaseConfig = _FakeDatabaseConfig  # type: ignore[attr-defined]
    launch = types.ModuleType("shinka.launch")
    launch.LocalJobConfig = _FakeLocalJobConfig  # type: ignore[attr-defined]
    # shinka.llm.client carries the module-global request timeout the R2
    # lever (#320/#260) set/restores around an engine run. A fresh module
    # object per test — mutations can never leak across tests.
    llm_pkg = types.ModuleType("shinka.llm")
    llm_client = types.ModuleType("shinka.llm.client")
    llm_client.TIMEOUT = _FAKE_SHINKA_DEFAULT_TIMEOUT  # type: ignore[attr-defined]
    pkg.llm = llm_pkg  # type: ignore[attr-defined]
    llm_pkg.client = llm_client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shinka", pkg)
    monkeypatch.setitem(sys.modules, "shinka.core", core)
    monkeypatch.setitem(sys.modules, "shinka.database", database)
    monkeypatch.setitem(sys.modules, "shinka.launch", launch)
    monkeypatch.setitem(sys.modules, "shinka.llm", llm_pkg)
    monkeypatch.setitem(sys.modules, "shinka.llm.client", llm_client)


# The "shinka not installed" tests use the shared ``no_shinka`` fixture
# from tests/conftest.py (sys.modules None injection — env-independent).


# ── default_output_subdir seam (S14-05) ──────────────────────────────────────


class TestDefaultOutputSubdir:
    """The engine output dir name is backend-owned (protocol property)."""

    def test_openevolve_output_subdir(self) -> None:
        """OpenEvolveBackend stages into oe-output/."""
        assert OpenEvolveBackend().default_output_subdir == "oe-output"

    def test_shinka_output_subdir(self) -> None:
        """ShinkaBackend stages into shinka-output/."""
        assert ShinkaBackend().default_output_subdir == "shinka-output"


# ── Crash-status delegation (S14-06) ─────────────────────────────────────────


class _CountingBackend:
    """Minimal backend double for count_valid delegation tests."""

    def __init__(self, count: int | None) -> None:
        self._count = count
        self.seen: list[Path] = []

    def count_valid(self, run_dir: Path) -> int | None:
        self.seen.append(run_dir)
        return self._count


class _RaisingBackend:
    """Backend double whose count_valid raises (stub behavior)."""

    def count_valid(self, run_dir: Path) -> int | None:
        raise BackendUnavailableError("not installed")


class TestDetermineCrashStatusDelegation:
    """_determine_crash_status() delegates counting to the backend."""

    def test_delegates_to_backend_count_valid(self, tmp_path: Path) -> None:
        """The provided backend's count_valid() is consulted with run_dir."""
        backend = _CountingBackend(count=10)
        status, valid = _determine_crash_status(
            tmp_path,
            30,
            backend=backend,  # type: ignore[arg-type]
        )
        assert status == "completed_with_errors"
        assert valid == 10
        assert backend.seen == [tmp_path]

    def test_none_count_is_failed(self, tmp_path: Path) -> None:
        """No countable programs -> ('failed', None)."""
        backend = _CountingBackend(count=None)
        status, valid = _determine_crash_status(
            tmp_path,
            30,
            backend=backend,  # type: ignore[arg-type]
        )
        assert status == "failed"
        assert valid is None

    def test_full_count_never_completed(self, tmp_path: Path) -> None:
        """A crash is never 'completed', even with all iterations valid."""
        backend = _CountingBackend(count=30)
        status, valid = _determine_crash_status(
            tmp_path,
            30,
            backend=backend,  # type: ignore[arg-type]
        )
        assert status == "completed_with_errors"
        assert valid == 30

    def test_count_valid_error_does_not_mask_crash(self, tmp_path: Path) -> None:
        """A backend counting failure degrades to ('failed', None)."""
        status, valid = _determine_crash_status(
            tmp_path,
            30,
            backend=_RaisingBackend(),  # type: ignore[arg-type]
        )
        assert status == "failed"
        assert valid is None

    def test_default_backend_is_openevolve(self, tmp_path: Path) -> None:
        """Without an explicit backend the OE layout is consulted (compat)."""
        run_dir = tmp_path / "run-abc"
        ckpt_dir = run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
        ckpt_dir.mkdir(parents=True)
        db_data = {"programs": [{"id": f"prog_{i}"} for i in range(4)]}
        (ckpt_dir / "database.json").write_text(json.dumps(db_data))

        status, valid = _determine_crash_status(run_dir, 30)
        assert status == "completed_with_errors"
        assert valid == 4


# ── is_available (S14-07) ─────────────────────────────────────────────────────


class TestShinkaIsAvailable:
    """is_available() probes the real shinka import."""

    def test_unavailable_without_shinka(self, no_shinka: None) -> None:
        """Without shinka installed: (False, install hint)."""
        available, hint = ShinkaBackend().is_available()
        assert available is False
        assert hint is not None
        assert "pip install 'revolver[shinka]'" in hint

    def test_available_with_shinka(self, fake_shinka: None) -> None:
        """With an importable shinka.core: (True, None)."""
        assert ShinkaBackend().is_available() == (True, None)


# ── config_template (S14-07) ─────────────────────────────────────────────────


class TestShinkaConfigTemplate:
    """config_template() returns a parseable Shinka-shaped scaffold."""

    def test_template_is_valid_yaml_with_sections(self) -> None:
        """The scaffold parses as YAML with the three Shinka sections."""
        data = yaml.safe_load(ShinkaBackend().config_template())
        assert isinstance(data, dict)
        assert set(data) >= {"evo_config", "db_config", "job_config"}
        assert data["evo_config"]["num_generations"] == 10
        assert data["evo_config"]["patch_types"] == ["diff", "full"]
        assert data["db_config"]["num_islands"] == 2

    def test_template_passes_validate_config(self, fake_shinka: None) -> None:
        """The shipped template raises no validation warnings."""
        data = yaml.safe_load(ShinkaBackend().config_template())
        assert ShinkaBackend().validate_config(data) == []

    def test_template_documents_llm_settings(self) -> None:
        """B (#301): the scaffold surfaces the thinking-model defaults."""
        template = ShinkaBackend().config_template()
        assert "max_patch_attempts: 10" in template
        assert "max_tokens: 16384" in template
        assert "reasoning_efforts" in template


# ── validate_config (S14-07) ─────────────────────────────────────────────────


class TestShinkaValidateConfig:
    """validate_config() checks keys against the Shinka dataclasses."""

    def test_graceful_without_shinka(self, no_shinka: None) -> None:
        """Without shinka the validation degrades to no warnings."""
        warnings = ShinkaBackend().validate_config({"evo_config": {"bogus_key": 1}})
        assert warnings == []

    def test_unknown_section_key_caught(self, fake_shinka: None) -> None:
        """An unknown evo_config key produces a warning naming the schema."""
        warnings = ShinkaBackend().validate_config(
            {"evo_config": {"num_generations": 3, "bogus_key": 1}}
        )
        assert len(warnings) == 1
        assert "bogus_key" in warnings[0]
        assert "EvolutionConfig" in warnings[0]

    def test_unknown_top_level_section_caught(self, fake_shinka: None) -> None:
        """An unknown top-level section produces a warning."""
        warnings = ShinkaBackend().validate_config({"max_iterations": 5})
        assert len(warnings) == 1
        assert "max_iterations" in warnings[0]

    def test_revolver_sections_tolerated(self, fake_shinka: None) -> None:
        """Revolver-owned sections (evaluation/output_dir/llm_env) pass."""
        warnings = ShinkaBackend().validate_config(
            {
                "evaluation": {"timeout_per_instance": 30},
                "output_dir": "/tmp/x",
                "llm_env": {"OLLAMA_API_KEY": None},
            }
        )
        assert warnings == []

    def test_non_mapping_section_warned(self, fake_shinka: None) -> None:
        """A scalar section value is flagged instead of crashing."""
        warnings = ShinkaBackend().validate_config({"db_config": 5})
        assert warnings == ["Config section 'db_config' must be a mapping."]

    def test_yaml_path_input(self, fake_shinka: None, tmp_path: Path) -> None:
        """A Path input is loaded from YAML before validation."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text("db_config:\n  bogus: 1\n")
        warnings = ShinkaBackend().validate_config(cfg)
        assert len(warnings) == 1
        assert "DatabaseConfig" in warnings[0]


# ── build_config (S14-08) ────────────────────────────────────────────────────


class TestShinkaBuildConfig:
    """build_config() projects BackendRunSpec into the nested Shinka dict."""

    def test_unavailable_raises_backend_unavailable(self, no_shinka: None, tmp_path: Path) -> None:
        """Without shinka, build_config fails fast (exit-3 contract)."""
        with pytest.raises(BackendUnavailableError):
            ShinkaBackend().build_config(_make_spec(tmp_path))

    def test_local_llm_projection(self, fake_shinka: None, tmp_path: Path) -> None:
        """Local Ollama LLM -> local/<model>@<url>?api_key_env=... (D5)."""
        spec = _make_spec(tmp_path)
        config = ShinkaBackend().build_config(spec)

        evo = config["evo_config"]
        assert evo["llm_models"] == [
            "local/llama3@http://localhost:11434/v1?api_key_env=OLLAMA_API_KEY"
        ]
        assert evo["llm_dynamic_selection"] == "fixed"
        # Synthesized env name with no Revolver source -> placeholder export
        assert config["llm_env"] == {"OLLAMA_API_KEY": None}

    def test_local_llm_custom_api_key_env(self, fake_shinka: None, tmp_path: Path) -> None:
        """A registered api_key_env is kept in the local model string."""
        spec = _make_spec(tmp_path, llm=_make_llm(api_key_env="MY_LOCAL_KEY"))
        config = ShinkaBackend().build_config(spec)

        assert config["evo_config"]["llm_models"] == [
            "local/llama3@http://localhost:11434/v1?api_key_env=MY_LOCAL_KEY"
        ]
        assert config["llm_env"] == {"MY_LOCAL_KEY": "MY_LOCAL_KEY"}

    def test_remote_llm_projection(self, fake_shinka: None, tmp_path: Path) -> None:
        """Remote LLM -> plain model id + provider-standard env var (D5)."""
        llm = _make_llm(
            name="claude",
            model="claude-sonnet-4-5",
            source="remote",
            provider="anthropic",
            base_url=None,
            api_key_env="MY_ANTHROPIC_KEY",
        )
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=llm))

        assert config["evo_config"]["llm_models"] == ["claude-sonnet-4-5"]
        assert config["llm_env"] == {"ANTHROPIC_API_KEY": "MY_ANTHROPIC_KEY"}

    def test_remote_unknown_provider_warns(
        self,
        fake_shinka: None,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Unknown provider: no env mapping, explicit stderr warning."""
        llm = _make_llm(
            model="exotic-model",
            source="remote",
            provider="exotic",
            api_key_env="EXOTIC_KEY",
        )
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=llm))

        assert config["evo_config"]["llm_models"] == ["exotic-model"]
        assert "llm_env" not in config
        assert "no provider-standard env var" in capsys.readouterr().err

    def test_ensemble_rejected(self, fake_shinka: None, tmp_path: Path) -> None:
        """Ensembles are S15 — rejected with a clear error."""
        ensemble = EnsembleEntry(
            name="duo",
            members=[
                EnsembleMember(llm_name="a", weight=0.5),
                EnsembleMember(llm_name="b", weight=0.5),
            ],
            created_at=datetime(2026, 1, 1),
        )
        with pytest.raises(ValidationError, match=r"[Ee]nsemble"):
            ShinkaBackend().build_config(_make_spec(tmp_path, ensemble=ensemble))

    def test_iterations_projected_to_num_generations(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """spec.iterations (orchestrator-resolved) -> num_generations."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, iterations=7))
        assert config["evo_config"]["num_generations"] == 7
        # No OE-specific keys leak into the Shinka config
        assert "max_iterations" not in config
        assert "llm" not in config

    def test_no_iterations_keeps_config_value(self, fake_shinka: None, tmp_path: Path) -> None:
        """Without spec.iterations the problem-config value is preserved."""
        spec = _make_spec(tmp_path)
        (spec.snapshot_dir / "config.yaml").write_text(
            "evo_config:\n  num_generations: 5\ndb_config:\n  num_islands: 4\n"
        )
        config = ShinkaBackend().build_config(spec)
        assert config["evo_config"]["num_generations"] == 5
        assert config["db_config"]["num_islands"] == 4

    def test_problem_description_injected(self, fake_shinka: None, tmp_path: Path) -> None:
        """problem.md content lands in task_sys_msg."""
        config = ShinkaBackend().build_config(
            _make_spec(tmp_path, problem_description="Sort numbers fast.")
        )
        assert "Sort numbers fast." in config["evo_config"]["task_sys_msg"]

    def test_default_patch_types(self, fake_shinka: None, tmp_path: Path) -> None:
        """Default projection: patch_types=['diff', 'full'] (no 'cross')."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path))
        assert config["evo_config"]["patch_types"] == ["diff", "full"]
        assert config["evo_config"]["patch_type_probs"] == [0.6, 0.4]

    def test_rewrite_mode_full_patches(self, fake_shinka: None, tmp_path: Path) -> None:
        """--rewrite-mode -> patch_types=['full']."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, rewrite_mode=True))
        assert config["evo_config"]["patch_types"] == ["full"]
        assert config["evo_config"]["patch_type_probs"] == [1.0]

    def test_mvp_fixed_projections(self, fake_shinka: None, tmp_path: Path) -> None:
        """language/job_type/init_program_path/embedding_model projections."""
        spec = _make_spec(tmp_path)
        config = ShinkaBackend().build_config(spec)
        evo = config["evo_config"]
        assert evo["language"] == "python"
        assert evo["job_type"] == "local"
        assert evo["init_program_path"] == str(spec.snapshot_dir / "initial_program.py")
        assert evo["embedding_model"] is None

    def test_results_dir_from_run_dir(self, fake_shinka: None, tmp_path: Path) -> None:
        """results_dir = <run_dir>/shinka-output when the run dir is known."""
        spec = _make_spec(tmp_path)
        config = ShinkaBackend().build_config(spec)
        assert config["evo_config"]["results_dir"] == str(spec.run_dir / "shinka-output")
        assert config["job_config"]["eval_program_path"] == str(
            spec.run_dir / SHINKA_WRAPPER_FILENAME
        )

    def test_no_run_dir_leaves_results_dir_unset(self, fake_shinka: None, tmp_path: Path) -> None:
        """Build-only flows (--dry-run) have no run dir yet."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, run_dir=None))
        assert "results_dir" not in config["evo_config"]
        assert "eval_program_path" not in config["job_config"]

    def test_temperature_cli_overrides_registry(self, fake_shinka: None, tmp_path: Path) -> None:
        """CLI --temperature wins over the registry temperature."""
        llm = _make_llm(temperature=0.8, max_tokens=2048)
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=llm, temperature=0.2))
        assert config["evo_config"]["llm_kwargs"]["temperatures"] == [0.2]
        assert config["evo_config"]["llm_kwargs"]["max_tokens"] == 2048

    def test_registry_temperature_fallback(self, fake_shinka: None, tmp_path: Path) -> None:
        """Registry temperature is used when no CLI override is given."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=_make_llm(temperature=0.8)))
        assert config["evo_config"]["llm_kwargs"]["temperatures"] == [0.8]

    def test_parallel_warns(
        self,
        fake_shinka: None,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--parallel is map-with-warn (no silent no-op — D4)."""
        ShinkaBackend().build_config(_make_spec(tmp_path, parallel=4))
        assert "--parallel has no effect" in capsys.readouterr().err

    def test_config_overrides_dotted(self, fake_shinka: None, tmp_path: Path) -> None:
        """Dotted overrides reach the nested sections and win last."""
        config = ShinkaBackend().build_config(
            _make_spec(
                tmp_path,
                config_overrides=[
                    "db_config.num_islands=8",
                    "evo_config.max_api_costs=5.5",
                ],
            )
        )
        assert config["db_config"]["num_islands"] == 8
        assert config["evo_config"]["max_api_costs"] == 5.5

    def test_malformed_override_raises(self, fake_shinka: None, tmp_path: Path) -> None:
        """An override without '=' raises ValidationError."""
        with pytest.raises(ValidationError, match="Malformed config override"):
            ShinkaBackend().build_config(_make_spec(tmp_path, config_overrides=["num_islands"]))

    # ── B9: no-op --config-override key warning (S17-30) ──────────────────────

    def test_config_override_noop_key_warns(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An override key on no Shinka field warns naming the key (spec §4.5)."""
        ShinkaBackend().build_config(
            _make_spec(tmp_path, config_overrides=["evo_config.nonexistent_key=1"])
        )
        err = capsys.readouterr().err
        assert "evo_config.nonexistent_key" in err
        assert "no effect" in err

    def test_config_override_unknown_section_warns(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An override key under an unknown top-level section warns (build time)."""
        ShinkaBackend().build_config(
            _make_spec(tmp_path, config_overrides=["bogus_section.key=1"])
        )
        err = capsys.readouterr().err
        assert "bogus_section.key" in err
        assert "no effect" in err

    def test_config_override_recognized_key_silent(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A recognized override key emits no no-op warning."""
        ShinkaBackend().build_config(
            _make_spec(tmp_path, config_overrides=["db_config.num_islands=4"])
        )
        err = capsys.readouterr().err
        assert "no effect" not in err

    def test_config_override_nested_dict_field_silent(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A deep key under a dict-valued field (llm_kwargs) is not a no-op."""
        ShinkaBackend().build_config(
            _make_spec(tmp_path, config_overrides=["evo_config.llm_kwargs.max_tokens=8192"])
        )
        err = capsys.readouterr().err
        assert "no effect" not in err

    def test_config_override_revolver_key_silent(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Revolver-owned sections (evaluation/output_dir/llm_env) are silent."""
        ShinkaBackend().build_config(
            _make_spec(
                tmp_path,
                config_overrides=[
                    "evaluation.timeout_per_instance=5",
                    "output_dir=/tmp/x",
                    "llm_env.OLLAMA_API_KEY=none",
                ],
            )
        )
        err = capsys.readouterr().err
        assert "no effect" not in err

    def test_config_override_noop_names_only_the_bad_key(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With a mix, only the genuinely unrecognized key is warned about."""
        ShinkaBackend().build_config(
            _make_spec(
                tmp_path,
                config_overrides=["db_config.num_islands=4", "db_config.bogus_field=1"],
            )
        )
        err = capsys.readouterr().err
        assert "db_config.bogus_field" in err
        assert "db_config.num_islands" not in err

    # ── B (#301/S15-05..07): thinking-model LLM-setting defaults ──────────────

    def test_max_patch_attempts_default(self, fake_shinka: None, tmp_path: Path) -> None:
        """S15-05: max_patch_attempts defaults to 10 (Shinka's own default is 1)."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path))
        assert config["evo_config"]["max_patch_attempts"] == 10

    def test_max_patch_attempts_config_value_respected(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """An explicit config.yaml value wins over the Revolver default."""
        spec = _make_spec(tmp_path)
        (spec.snapshot_dir / "config.yaml").write_text("evo_config:\n  max_patch_attempts: 3\n")
        config = ShinkaBackend().build_config(spec)
        assert config["evo_config"]["max_patch_attempts"] == 3

    def test_max_patch_attempts_override_wins(self, fake_shinka: None, tmp_path: Path) -> None:
        """--config-override (applied last) wins over the default."""
        config = ShinkaBackend().build_config(
            _make_spec(tmp_path, config_overrides=["evo_config.max_patch_attempts=1"])
        )
        assert config["evo_config"]["max_patch_attempts"] == 1

    def test_max_tokens_default_escalation(self, fake_shinka: None, tmp_path: Path) -> None:
        """S15-06: max_tokens defaults to 16384 when the LLM entry sets none."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=_make_llm()))
        assert config["evo_config"]["llm_kwargs"]["max_tokens"] == 16384

    def test_max_tokens_registry_value_preferred(self, fake_shinka: None, tmp_path: Path) -> None:
        """A registered LLMEntry.max_tokens is preferred over the 16384 default."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=_make_llm(max_tokens=2048)))
        assert config["evo_config"]["llm_kwargs"]["max_tokens"] == 2048

    def test_max_tokens_override_wins(self, fake_shinka: None, tmp_path: Path) -> None:
        """--config-override (applied last) wins over the 16384 default."""
        config = ShinkaBackend().build_config(
            _make_spec(tmp_path, config_overrides=["evo_config.llm_kwargs.max_tokens=8192"])
        )
        assert config["evo_config"]["llm_kwargs"]["max_tokens"] == 8192

    def test_reasoning_efforts_via_override(self, fake_shinka: None, tmp_path: Path) -> None:
        """S15-07: reasoning_efforts is reachable via a dotted --config-override."""
        config = ShinkaBackend().build_config(
            _make_spec(
                tmp_path,
                config_overrides=["evo_config.llm_kwargs.reasoning_efforts=low"],
            )
        )
        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == "low"

    # ── S17-27: per-member reasoning_effort → single global pool (FACT A) ─────

    def test_reasoning_efforts_absent_when_unset(self, fake_shinka: None, tmp_path: Path) -> None:
        """No reasoning_effort anywhere → llm_kwargs gains no reasoning_efforts key."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=_make_llm()))
        assert "reasoning_efforts" not in config["evo_config"]["llm_kwargs"]

    def test_reasoning_efforts_single_llm_from_registry(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """A single reasoning-capable remote LLM projects its registry effort."""
        llm = _make_llm(source="remote", provider="openai", reasoning_effort="high")
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=llm))
        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == ["high"]

    def test_reasoning_efforts_config_value_wins(self, fake_shinka: None, tmp_path: Path) -> None:
        """A config.yaml llm_kwargs.reasoning_efforts wins over the registry value."""
        llm = _make_llm(source="remote", provider="openai", reasoning_effort="high")
        spec = _make_spec(tmp_path, llm=llm)
        (spec.snapshot_dir / "config.yaml").write_text(
            "evo_config:\n  llm_kwargs:\n    reasoning_efforts: low\n"
        )
        config = ShinkaBackend().build_config(spec)
        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == "low"

    def test_shinka_reasoning_effort_global_pool(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Uniform effort across members → single pool, set silently (S17-27)."""
        db_path = tmp_path / "global.db"
        conn = get_global_db_at(db_path)
        try:
            insert_llm(
                conn,
                _make_llm(name="m-a", source="remote", provider="openai", reasoning_effort="high"),
            )
            insert_llm(
                conn,
                _make_llm(name="m-b", source="remote", provider="openai", reasoning_effort="high"),
            )
            ensemble = EnsembleEntry(
                name="ens",
                members=[
                    EnsembleMember(llm_name="m-a", weight=0.5),
                    EnsembleMember(llm_name="m-b", weight=0.5),
                ],
                created_at=datetime(2026, 1, 1),
            )
            spec = _make_spec(
                tmp_path,
                llm=_make_llm(name="m-a", source="remote", provider="openai"),
                ensemble=ensemble,
                conn=conn,
            )
            config = ShinkaBackend().build_config(spec)
        finally:
            conn.close()

        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == ["high"]
        # Uniform, all-remote → no warning at all.
        assert capsys.readouterr().err == ""

    def test_shinka_reasoning_effort_disagreement_picks_highest(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Disagreeing efforts → highest chosen (never under-think) + warning."""
        db_path = tmp_path / "global.db"
        conn = get_global_db_at(db_path)
        try:
            insert_llm(
                conn,
                _make_llm(name="m-a", source="remote", provider="openai", reasoning_effort="low"),
            )
            insert_llm(
                conn,
                _make_llm(name="m-b", source="remote", provider="openai", reasoning_effort="high"),
            )
            ensemble = EnsembleEntry(
                name="ens",
                members=[
                    EnsembleMember(llm_name="m-a", weight=0.5),
                    # Per-member override to "medium" (still lower than m-a's? no:
                    # low < medium < high; m-b registry is high, override medium wins).
                    EnsembleMember(llm_name="m-b", weight=0.5, reasoning_effort="medium"),
                ],
                created_at=datetime(2026, 1, 1),
            )
            spec = _make_spec(
                tmp_path,
                llm=_make_llm(name="m-a", source="remote", provider="openai"),
                ensemble=ensemble,
                conn=conn,
            )
            config = ShinkaBackend().build_config(spec)
        finally:
            conn.close()

        # Effective efforts are {low, medium} → highest is "medium".
        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == ["medium"]
        err = capsys.readouterr().err
        assert "different reasoning_effort" in err
        # Assert on the distinct "chosen" phrase, not the bare level (which also
        # appears in the listed distinct levels), to lock the highest-wins policy.
        assert "Choosing the highest level 'medium'" in err

    def test_shinka_reasoning_effort_inert_local_warns(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """All-local ensemble with effort set → inert warning (FACT A)."""
        db_path = tmp_path / "global.db"
        conn = get_global_db_at(db_path)
        try:
            insert_llm(conn, _make_llm(name="m-a", source="local", reasoning_effort="high"))
            insert_llm(conn, _make_llm(name="m-b", source="local", reasoning_effort="high"))
            ensemble = EnsembleEntry(
                name="ens",
                members=[
                    EnsembleMember(llm_name="m-a", weight=0.5),
                    EnsembleMember(llm_name="m-b", weight=0.5),
                ],
                created_at=datetime(2026, 1, 1),
            )
            spec = _make_spec(
                tmp_path,
                llm=_make_llm(name="m-a", source="local"),
                ensemble=ensemble,
                conn=conn,
            )
            config = ShinkaBackend().build_config(spec)
        finally:
            conn.close()

        # Effort still projected (uniform "high"), but flagged inert for local.
        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == ["high"]
        err = capsys.readouterr().err
        assert "inert for local" in err

    def test_evaluation_section_passthrough(self, fake_shinka: None, tmp_path: Path) -> None:
        """The Revolver 'evaluation' section survives the projection."""
        spec = _make_spec(tmp_path)
        (spec.snapshot_dir / "config.yaml").write_text("evaluation:\n  timeout_per_instance: 12\n")
        config = ShinkaBackend().build_config(spec)
        assert config["evaluation"]["timeout_per_instance"] == 12

    def test_output_is_yaml_serialisable(self, fake_shinka: None, tmp_path: Path) -> None:
        """The built config round-trips through YAML (config snapshot)."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, iterations=3))
        dumped = yaml.dump(config, default_flow_style=False)
        assert yaml.safe_load(dumped) == config

    def test_local_source_pins_max_proposal_jobs(self, fake_shinka: None, tmp_path: Path) -> None:
        """UX-5/S16-21: a --source local LLM auto-pins job_config.max_proposal_jobs=1."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=_make_llm(source="local")))
        assert config["job_config"]["max_proposal_jobs"] == 1

    def test_remote_source_does_not_pin_max_proposal_jobs(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """A remote LLM does not get the local concurrency pin."""
        llm = _make_llm(
            name="remote-llm",
            source="remote",
            provider="openai",
            base_url=None,
            api_key_env="OPENAI_API_KEY",
        )
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=llm))
        assert "max_proposal_jobs" not in config.get("job_config", {})

    def test_max_proposal_jobs_override_wins(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An explicit --config-override overrides the local auto-pin (UX-5).

        Also guards the B9 exemption (R1/#253): the key is not a
        LocalJobConfig field, yet it IS honored (routed to the runner
        constructor by ``_run_engine``), so the no-op-override probe must
        stay silent for it.
        """
        config = ShinkaBackend().build_config(
            _make_spec(
                tmp_path,
                llm=_make_llm(source="local"),
                config_overrides=["job_config.max_proposal_jobs=3"],
            )
        )
        assert config["job_config"]["max_proposal_jobs"] == 3
        assert "max_proposal_jobs" not in capsys.readouterr().err

    def test_misplaced_section_key_keeps_pin_and_warns(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A same-named leaf under another section does not disable the pin.

        PR #254 review: pin-skip detection uses the exact full key
        ``job_config.max_proposal_jobs`` (same convention as the B9
        exemption). ``evo_config.max_proposal_jobs=8`` never reaches the
        runner, so the local auto-pin stays active and the misplaced key
        draws the B9 no-op warning (EvolutionConfig has no such field —
        matches the real 0.0.7 schema).
        """
        config = ShinkaBackend().build_config(
            _make_spec(
                tmp_path,
                llm=_make_llm(source="local"),
                config_overrides=["evo_config.max_proposal_jobs=8"],
            )
        )
        assert config["job_config"]["max_proposal_jobs"] == 1
        err = capsys.readouterr().err
        assert "evo_config.max_proposal_jobs" in err
        assert "no effect" in err

    def test_resolved_config_surfaces_max_proposal_jobs(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """The injected max_proposal_jobs appears in the dry-run backend_extras."""
        backend = ShinkaBackend()
        config = backend.build_config(_make_spec(tmp_path, llm=_make_llm(source="local")))
        resolved = backend.resolved_config(config)
        assert resolved.backend_extras["max_proposal_jobs"] == 1

    def test_selection_kwarg_residual_string_fails_fast(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """U1 (S17a-08): a residual string on an accepted sampler key raises.

        ``epsilon=abc`` survives the CLI-side ``_parse_value`` coercion as a
        string; every accepted sampler parameter is numeric/boolean, so the
        routing raises ``ValidationError`` at build_config time — which runs
        before the ``--dry-run`` early return, so garbage fails at dry-run
        instead of as an engine ``TypeError`` at launch.
        """
        spec = _make_spec(tmp_path, selection="ucb", selection_kwargs={"epsilon": "abc"})
        with pytest.raises(ValidationError, match="epsilon=abc"):
            ShinkaBackend().build_config(spec)

    def test_selection_kwarg_json_array_fails_fast(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """U1 (S17a-08, review): non-scalar JSON values fail fast too.

        ``epsilon=[1,2]`` parses to a *list* under ``_parse_value`` — no
        longer a string, but still a launch-time ``TypeError`` for a numeric
        sampler parameter. The guard rejects anything that is not
        int/float/bool/None.
        """
        spec = _make_spec(tmp_path, selection="ucb", selection_kwargs={"epsilon": [1, 2]})
        with pytest.raises(ValidationError, match="epsilon="):
            ShinkaBackend().build_config(spec)

    def test_selection_kwarg_typed_values_still_routed(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """Typed (coerced) kwargs pass the U1 fail-fast and reach the config."""
        spec = _make_spec(
            tmp_path,
            selection="ucb",
            selection_kwargs={"epsilon": 0.4, "adaptive_scale": False},
        )
        config = ShinkaBackend().build_config(spec)
        kwargs = config["evo_config"]["llm_dynamic_selection_kwargs"]
        assert kwargs["epsilon"] == 0.4
        assert kwargs["adaptive_scale"] is False
        # M4 do-not-regress: cost_aware_coef still injected as float 0.0.
        assert kwargs["cost_aware_coef"] == 0.0

    def test_shinka_reasoning_efforts_config_path_inert_warns(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """U7 residual (S17a-13): --config-override reasoning_efforts on an
        all-local fleet warns inert (the member-path warning cannot see it)."""
        spec = _make_spec(
            tmp_path,
            llm=_make_llm(source="local"),
            config_overrides=["evo_config.llm_kwargs.reasoning_efforts=high"],
        )
        config = ShinkaBackend().build_config(spec)
        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == "high"
        err = capsys.readouterr().err
        assert "reasoning_efforts is set via config.yaml/--config-override" in err
        assert "inert" in err

    def test_shinka_reasoning_efforts_config_yaml_path_inert_warns(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """U7 residual: a config.yaml llm_kwargs.reasoning_efforts on an
        all-local fleet warns inert too (the projection defers to it silently)."""
        spec = _make_spec(tmp_path, llm=_make_llm(source="local"))
        (spec.snapshot_dir / "config.yaml").write_text(
            "evo_config:\n  llm_kwargs:\n    reasoning_efforts: low\n"
        )
        config = ShinkaBackend().build_config(spec)
        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == "low"
        assert "inert" in capsys.readouterr().err

    def test_shinka_reasoning_efforts_config_path_remote_fleet_silent(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """U7 residual: the same override on a reasoning-capable remote fleet
        warns nothing (the pool takes effect there)."""
        llm = _make_llm(
            name="remote-llm",
            source="remote",
            provider="openai",
            base_url=None,
            api_key_env="OPENAI_API_KEY",
        )
        spec = _make_spec(
            tmp_path,
            llm=llm,
            config_overrides=["evo_config.llm_kwargs.reasoning_efforts=high"],
        )
        config = ShinkaBackend().build_config(spec)
        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == "high"
        assert "inert" not in capsys.readouterr().err

    def test_shinka_reasoning_efforts_no_config_path_no_extra_warning(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """U7 residual: a registry-derived (member-path) effort on a local
        fleet warns exactly once — via the member path, not the U7 check."""
        spec = _make_spec(tmp_path, llm=_make_llm(source="local", reasoning_effort="high"))
        ShinkaBackend().build_config(spec)
        err = capsys.readouterr().err
        # Member-path warning (S17-27/W2a) fires...
        assert "inert for local" in err
        # ...and the config-path warning does not double up.
        assert "set via config.yaml/--config-override" not in err

    def test_shinka_reasoning_efforts_member_and_override_warns_once(
        self, fake_shinka: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """U7 double-warn fix (S17a review WARNING): a local member carrying a
        registry effort COMBINED with a --config-override reasoning_efforts
        emits exactly ONE inert warning — the member-path one; the config-path
        check is suppressed for that build."""
        spec = _make_spec(
            tmp_path,
            llm=_make_llm(source="local", reasoning_effort="high"),
            config_overrides=["evo_config.llm_kwargs.reasoning_efforts=low"],
        )
        config = ShinkaBackend().build_config(spec)
        # The override still wins over the member-projected pool.
        assert config["evo_config"]["llm_kwargs"]["reasoning_efforts"] == "low"
        err = capsys.readouterr().err
        assert err.count("inert") == 1
        # The single warning is the member-path one, not the config-path one.
        assert "inert for local" in err
        assert "set via config.yaml/--config-override" not in err


# ── resolved_config (S14-08) ─────────────────────────────────────────────────


class TestShinkaResolvedConfig:
    """resolved_config() maps the nested dict to the neutral model."""

    def test_neutral_fields_populated(self) -> None:
        """Neutral fields come from their Shinka locations (D4)."""
        config = {
            "evo_config": {
                "num_generations": 7,
                "language": "python",
                "llm_models": ["local/llama3@http://localhost:11434/v1"],
                "llm_kwargs": {"temperatures": [0.4]},
                "patch_types": ["diff", "full"],
                "llm_dynamic_selection": "fixed",
                "max_api_costs": 5.0,
                "results_dir": "/runs/r1/shinka-output",
            },
            "db_config": {"num_islands": 4, "archive_size": 16},
        }
        resolved = ShinkaBackend().resolved_config(config, config_overrides={"a": 1})

        assert resolved.backend == "shinka"
        assert resolved.iterations == 7
        assert resolved.num_islands == 4
        assert resolved.temperature == 0.4
        assert resolved.language == "python"
        assert resolved.llm_models == [{"name": "local/llama3@http://localhost:11434/v1"}]
        assert resolved.config_overrides == {"a": 1}
        assert resolved.backend_extras["patch_types"] == ["diff", "full"]
        assert resolved.backend_extras["llm_dynamic_selection"] == "fixed"
        assert resolved.backend_extras["max_api_costs"] == 5.0
        assert resolved.backend_extras["archive_size"] == 16
        assert resolved.backend_extras["results_dir"] == "/runs/r1/shinka-output"

    def test_empty_config(self) -> None:
        """An empty config resolves to backend-only fields."""
        resolved = ShinkaBackend().resolved_config({})
        assert resolved.backend == "shinka"
        assert resolved.iterations is None
        assert resolved.llm_models is None
        assert resolved.backend_extras == {}

    def test_ambiguous_temperatures_not_flattened(self) -> None:
        """A multi-entry temperatures list yields no single temperature."""
        resolved = ShinkaBackend().resolved_config(
            {"evo_config": {"llm_kwargs": {"temperatures": [0.0, 0.5, 1.0]}}}
        )
        assert resolved.temperature is None

    def test_surfaces_llm_settings(self, fake_shinka: None, tmp_path: Path) -> None:
        """S15-07: max_patch_attempts + max_tokens surfaced for dry-run."""
        backend = ShinkaBackend()
        config = backend.build_config(_make_spec(tmp_path))
        resolved = backend.resolved_config(config)
        assert resolved.backend_extras["max_patch_attempts"] == 10
        assert resolved.backend_extras["max_tokens"] == 16384
        # reasoning_efforts is not set on a plain run → stays out of dry-run
        assert "reasoning_efforts" not in resolved.backend_extras

    def test_surfaces_reasoning_efforts_when_set(self) -> None:
        """reasoning_efforts appears in backend_extras only when meaningfully set."""
        resolved = ShinkaBackend().resolved_config(
            {"evo_config": {"llm_kwargs": {"reasoning_efforts": "high"}}}
        )
        assert resolved.backend_extras["reasoning_efforts"] == "high"

    def test_empty_reasoning_efforts_not_surfaced(self) -> None:
        """The Shinka \"\" default for reasoning_efforts stays out of dry-run."""
        resolved = ShinkaBackend().resolved_config(
            {"evo_config": {"llm_kwargs": {"reasoning_efforts": ""}}}
        )
        assert "reasoning_efforts" not in resolved.backend_extras

    def test_shinka_dry_run_surfaces_selection_kwargs(self) -> None:
        """U10 (S17a-14): llm_dynamic_selection_kwargs reaches backend_extras
        and prior_probs is zipped into llm_models entries as weights."""
        resolved = ShinkaBackend().resolved_config(
            {
                "evo_config": {
                    "llm_models": ["local/m-a", "local/m-b"],
                    "llm_dynamic_selection": "fixed",
                    "llm_dynamic_selection_kwargs": {"prior_probs": [0.8, 0.2]},
                }
            }
        )
        assert resolved.backend_extras["llm_dynamic_selection_kwargs"] == {
            "prior_probs": [0.8, 0.2]
        }
        assert resolved.llm_models == [
            {"name": "local/m-a", "weight": 0.8},
            {"name": "local/m-b", "weight": 0.2},
        ]

    def test_shinka_dry_run_surfaces_cost_aware_coef(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """U10: the M4-injected cost_aware_coef is visible via a build→resolve
        round trip on ucb (no launch needed to validate kwargs)."""
        backend = ShinkaBackend()
        config = backend.build_config(_make_spec(tmp_path, selection="ucb"))
        resolved = backend.resolved_config(config)
        kwargs = resolved.backend_extras["llm_dynamic_selection_kwargs"]
        assert kwargs["cost_aware_coef"] == 0.0

    def test_shinka_dry_run_prior_probs_length_mismatch_not_zipped(self) -> None:
        """U10 guard: a prior_probs vector of the wrong length is surfaced in
        backend_extras but NOT zipped into the member entries."""
        resolved = ShinkaBackend().resolved_config(
            {
                "evo_config": {
                    "llm_models": ["local/m-a", "local/m-b"],
                    "llm_dynamic_selection_kwargs": {"prior_probs": [1.0]},
                }
            }
        )
        assert resolved.llm_models == [{"name": "local/m-a"}, {"name": "local/m-b"}]
        assert resolved.backend_extras["llm_dynamic_selection_kwargs"] == {"prior_probs": [1.0]}

    def test_shinka_single_llm_dry_run_unchanged(self, fake_shinka: None, tmp_path: Path) -> None:
        """U10 regression pin: a plain single-LLM build has no
        llm_dynamic_selection_kwargs in backend_extras and no member weights."""
        backend = ShinkaBackend()
        config = backend.build_config(_make_spec(tmp_path))
        resolved = backend.resolved_config(config)
        assert "llm_dynamic_selection_kwargs" not in resolved.backend_extras
        assert resolved.llm_models is not None
        assert all("weight" not in entry for entry in resolved.llm_models)


# ── generate_wrapper (S14-09, R4) ─────────────────────────────────────────────


_EVALUATOR_OK = """\
def evaluate_instance(program_path, instance_path):
    return {"combined_score": 1.0, "accuracy": 0.5}
"""

_EVALUATOR_FAILING = """\
def evaluate_instance(program_path, instance_path):
    raise RuntimeError("boom")
"""

_EVALUATOR_NO_SCORE = """\
def evaluate_instance(program_path, instance_path):
    return {"accuracy": 0.5}
"""

_EVALUATOR_LEGACY = """\
def evaluate(program_path):
    return {"combined_score": 1.0}
"""


def _write_snapshot(spec: BackendRunSpec, evaluator_code: str) -> None:
    """Write evaluator.py + initial_program.py into the snapshot dir."""
    (spec.snapshot_dir / "evaluator.py").write_text(evaluator_code)
    (spec.snapshot_dir / "initial_program.py").write_text("x = 1\n")


def _make_dataset(tmp_path: Path, n: int = 2) -> Path:
    """Create a dataset directory with *n* instance files."""
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir(exist_ok=True)
    for i in range(n):
        (dataset_dir / f"instance{i}.txt").write_text(f"data {i}\n")
    return dataset_dir


def _run_wrapper(
    wrapper: Path, tmp_path: Path, dataset_dir: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute the generated wrapper with the Shinka argv contract.

    Runs in the test environment (no shinka installed) so the wrapper's
    standalone fallback is exercised; returns (metrics, correct) payloads.
    """
    results_dir = tmp_path / "results"
    program = tmp_path / "program.py"
    program.write_text("y = 2\n")
    env = dict(os.environ)
    env["REVOLVER_DATASET_DIR"] = str(dataset_dir)
    proc = subprocess.run(
        [
            sys.executable,
            str(wrapper),
            "--program_path",
            str(program),
            "--results_dir",
            str(results_dir),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    metrics = json.loads((results_dir / "metrics.json").read_text())
    correct = json.loads((results_dir / "correct.json").read_text())
    return metrics, correct


class TestShinkaGenerateWrapper:
    """generate_wrapper() writes the Shinka CLI evaluator script."""

    def test_writes_wrapper_file(self, tmp_path: Path) -> None:
        """The wrapper lands at <run_dir>/_shinka_evaluator.py."""
        spec = _make_spec(tmp_path)
        _write_snapshot(spec, _EVALUATOR_OK)

        path = ShinkaBackend().generate_wrapper(spec)

        assert path == spec.run_dir / SHINKA_WRAPPER_FILENAME
        assert path.exists()

    def test_wrapper_content_contracts(self, tmp_path: Path) -> None:
        """argv contract, run_shinka_eval delegation, evaluate_instance."""
        spec = _make_spec(tmp_path, timeout_per_instance=2.5)
        _write_snapshot(spec, _EVALUATOR_OK)

        content = ShinkaBackend().generate_wrapper(spec).read_text()

        assert "--program_path" in content
        assert "--results_dir" in content
        assert "run_shinka_eval" in content
        assert "from evaluator import evaluate_instance" in content
        assert "REVOLVER_DATASET_DIR" in content
        assert "_TIMEOUT_PER_INSTANCE = 2.5" in content
        # The OE legacy entry point is never used (contract S14-02b)
        assert "def evaluate(" not in content

    def test_missing_run_dir_raises(self, tmp_path: Path) -> None:
        """A spec without run_dir cannot host the wrapper."""
        spec = _make_spec(tmp_path, run_dir=None)
        _write_snapshot(spec, _EVALUATOR_OK)
        with pytest.raises(ValidationError):
            ShinkaBackend().generate_wrapper(spec)

    def test_missing_evaluator_raises(self, tmp_path: Path) -> None:
        """A snapshot without evaluator.py fails fast."""
        spec = _make_spec(tmp_path)
        with pytest.raises(FileNotFoundError):
            ShinkaBackend().generate_wrapper(spec)

    def test_legacy_evaluate_only_rejected(self, tmp_path: Path) -> None:
        """evaluate()-only evaluators are an OE-only contract."""
        spec = _make_spec(tmp_path)
        _write_snapshot(spec, _EVALUATOR_LEGACY)
        with pytest.raises(EvaluatorLoadError, match="evaluate_instance"):
            ShinkaBackend().generate_wrapper(spec)

    def test_wrapper_execution_writes_metrics_and_correct(self, tmp_path: Path) -> None:
        """Standalone run: mean metrics + combined_score + correct=true."""
        spec = _make_spec(tmp_path)
        _write_snapshot(spec, _EVALUATOR_OK)
        wrapper = ShinkaBackend().generate_wrapper(spec)
        dataset_dir = _make_dataset(tmp_path)

        metrics, correct = _run_wrapper(wrapper, tmp_path, dataset_dir)

        assert metrics["combined_score"] == 1.0
        assert metrics["accuracy"] == 0.5
        assert correct == {"correct": True, "error": None}

    def test_wrapper_failing_evaluator_marks_incorrect(self, tmp_path: Path) -> None:
        """All instances failing -> combined_score 0.0, correct=false."""
        spec = _make_spec(tmp_path)
        _write_snapshot(spec, _EVALUATOR_FAILING)
        wrapper = ShinkaBackend().generate_wrapper(spec)
        dataset_dir = _make_dataset(tmp_path)

        metrics, correct = _run_wrapper(wrapper, tmp_path, dataset_dir)

        assert metrics["combined_score"] == 0.0
        assert correct["correct"] is False
        assert correct["error"]

    def test_wrapper_missing_combined_score_marks_incorrect(self, tmp_path: Path) -> None:
        """Metrics without combined_score -> incorrect, score defaults 0.0."""
        spec = _make_spec(tmp_path)
        _write_snapshot(spec, _EVALUATOR_NO_SCORE)
        wrapper = ShinkaBackend().generate_wrapper(spec)
        dataset_dir = _make_dataset(tmp_path)

        metrics, correct = _run_wrapper(wrapper, tmp_path, dataset_dir)

        assert metrics["combined_score"] == 0.0
        assert metrics["accuracy"] == 0.5
        assert correct["correct"] is False
        assert "combined_score" in (correct["error"] or "")


# ── Engine tier: launch/resume (S14-10/13) ────────────────────────────────────

# Env vars probed inside the fake runner ctor (llm_env export assertions).
_ENV_PROBES = ("OLLAMA_API_KEY", "ANTHROPIC_API_KEY")


def _install_fake_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    on_run: Callable[[dict[str, Any]], None] | None = None,
    run_exc: Exception | None = None,
) -> list[dict[str, Any]]:
    """Install a recording ``ShinkaEvolveRunner`` on the fake shinka.core.

    Each construction appends its kwargs (plus an ``_env`` snapshot of
    :data:`_ENV_PROBES` taken at construction time — the moment shinka's
    real ``_validate_evo_config_model_env_access`` would run) to the
    returned list. ``run()`` raises *run_exc* when given, else invokes
    *on_run* with the recorded kwargs.
    """
    calls: list[dict[str, Any]] = []

    class _FakeRunner:
        def __init__(self, **kwargs: Any) -> None:
            kwargs["_env"] = {name: os.environ.get(name) for name in _ENV_PROBES}
            calls.append(kwargs)

        def run(self) -> None:
            if run_exc is not None:
                raise run_exc
            if on_run is not None:
                on_run(calls[-1])

    monkeypatch.setattr(
        sys.modules["shinka.core"], "ShinkaEvolveRunner", _FakeRunner, raising=False
    )
    return calls


def _make_engine_spec(tmp_path: Path, **kwargs: Any) -> BackendRunSpec:
    """Spec with snapshot files and a generated wrapper, ready to launch."""
    spec = _make_spec(tmp_path, **kwargs)
    _write_snapshot(spec, _EVALUATOR_OK)
    spec.wrapper_path = ShinkaBackend().generate_wrapper(spec)
    return spec


def _write_fixture_db(call: dict[str, Any]) -> None:
    """on_run callback: write the fixture programs DB into results_dir."""
    results_dir = Path(call["evo_config"].results_dir)
    build_programs_db(results_dir / SHINKA_PROGRAMS_DB)


class TestShinkaLaunch:
    """launch() constructs the runner, runs it, materializes best/."""

    def test_unavailable_without_shinka(self, no_shinka: None, tmp_path: Path) -> None:
        """launch() raises the typed not-installed error (exit 3)."""
        spec = _make_spec(tmp_path)
        with pytest.raises(BackendUnavailableError):
            ShinkaBackend().launch(spec, {})

    def test_constructs_runner_and_materializes_best(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Runner gets dataclass configs + string contents; best/ written."""
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path, iterations=3)
        config = backend.build_config(spec)

        result = backend.launch(spec, config)

        assert spec.run_dir is not None
        output_dir = spec.run_dir / "shinka-output"
        assert len(calls) == 1
        call = calls[0]
        evo_config = call["evo_config"]
        assert evo_config.results_dir == str(output_dir)
        assert evo_config.num_generations == 3
        assert evo_config.llm_models == [
            "local/llama3@http://localhost:11434/v1?api_key_env=OLLAMA_API_KEY"
        ]
        assert call["init_program_str"] == "x = 1\n"
        assert "--program_path" in call["evaluate_str"]
        assert call["verbose"] is True
        # The orchestrator contract: config['output_dir'] is overwritten.
        assert config["output_dir"] == str(output_dir)

        # Materialization: best program from the DB, never init_program.py.
        best_file = output_dir / "best" / "best_program.py"
        assert best_file.exists()
        assert best_file.read_text() != call["init_program_str"]
        assert result.best_score == pytest.approx(EXPECTED_BEST_SCORE)
        assert result.best_program == best_file
        assert result.output_dir == output_dir

    def test_exports_local_placeholder_key(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Key-less local endpoint: placeholder exported, then restored."""
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path)
        config = backend.build_config(spec)
        assert config["llm_env"] == {"OLLAMA_API_KEY": None}

        backend.launch(spec, config)

        assert calls[0]["_env"]["OLLAMA_API_KEY"] == "ollama"
        # revolver_env restored the ambient environment after the run.
        assert os.environ.get("OLLAMA_API_KEY") is None

    def test_existing_target_env_untouched(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An ambient target var wins over the placeholder."""
        monkeypatch.setenv("OLLAMA_API_KEY", "user-key")
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path)

        backend.launch(spec, backend.build_config(spec))

        assert calls[0]["_env"]["OLLAMA_API_KEY"] == "user-key"
        assert os.environ["OLLAMA_API_KEY"] == "user-key"

    def test_remote_provider_env_copied_from_source(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Remote LLM: provider-standard var copied from the Revolver var."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("MY_ANTHROPIC_KEY", "secret-key")
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(
            tmp_path,
            llm=_make_llm(
                source="remote",
                provider="anthropic",
                model="claude-x",
                base_url="https://api.anthropic.com/v1",
                api_key_env="MY_ANTHROPIC_KEY",
            ),
        )
        config = backend.build_config(spec)
        assert config["llm_env"] == {"ANTHROPIC_API_KEY": "MY_ANTHROPIC_KEY"}

        backend.launch(spec, config)

        assert calls[0]["_env"]["ANTHROPIC_API_KEY"] == "secret-key"
        assert os.environ.get("ANTHROPIC_API_KEY") is None

    def test_engine_error_wrapped_as_external(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Engine failures surface as ExternalError (crash-status path)."""
        _install_fake_runner(monkeypatch, run_exc=RuntimeError("boom"))
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path)

        with pytest.raises(ExternalError, match="ShinkaEvolve run failed"):
            backend.launch(spec, backend.build_config(spec))

    def test_no_scored_programs_yields_no_best(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A DB without scored programs materializes an EMPTY best/ dir.

        The empty ``best/`` is deliberate (review #196 W2): an existing
        named dir keeps the orchestrator's program collection from falling
        back to the engine's own root scripts (``init_program.py``,
        ``evaluate.py``) and collecting them as bogus solutions.
        """
        unscored = tuple(row for row in FIXTURE_PROGRAM_ROWS if row["combined_score"] is None)

        def _write_unscored(call: dict[str, Any]) -> None:
            results_dir = Path(call["evo_config"].results_dir)
            build_programs_db(results_dir / SHINKA_PROGRAMS_DB, rows=unscored)

        _install_fake_runner(monkeypatch, on_run=_write_unscored)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path)

        result = backend.launch(spec, backend.build_config(spec))

        assert result.best_score is None
        assert result.best_program is None
        assert spec.run_dir is not None
        best_dir = spec.run_dir / "shinka-output" / "best"
        assert best_dir.exists()
        assert sorted(best_dir.glob("*.py")) == []

    def test_missing_run_dir_raises(self, fake_shinka: None, tmp_path: Path) -> None:
        """launch() requires spec.run_dir."""
        spec = _make_spec(tmp_path, run_dir=None)
        with pytest.raises(ValidationError):
            ShinkaBackend().launch(spec, {})


class TestMaxProposalJobsThreading:
    """R1 (#320/#253): max_proposal_jobs reaches the runner constructor.

    In shinka 0.0.7 ``max_proposal_jobs`` is a ``ShinkaEvolveRunner``
    constructor kwarg (default 6), not a ``LocalJobConfig`` field —
    ``_run_engine`` must pop it out of the job section and pass it to the
    constructor, otherwise the local-endpoint pin (UX-5/S16-21) and explicit
    overrides are silently dropped and every run fans out 6 concurrent
    proposal streams (spike #320 §4).
    """

    def test_local_pin_reaches_runner_ctor(
        self,
        fake_shinka: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The local-endpoint auto-pin (=1) is passed to the constructor."""
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path, llm=_make_llm(source="local"))

        backend.launch(spec, backend.build_config(spec))

        assert calls[0]["max_proposal_jobs"] == 1
        # The key was popped BEFORE the LocalJobConfig projection: the
        # _dataclass_kwargs unknown-key drop-warning must not fire for it.
        assert "max_proposal_jobs" not in capsys.readouterr().err

    def test_explicit_override_reaches_runner_ctor(
        self,
        fake_shinka: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An explicit job_config.max_proposal_jobs override wins end-to-end."""
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(
            tmp_path,
            llm=_make_llm(source="local"),
            config_overrides=["job_config.max_proposal_jobs=2"],
        )

        backend.launch(spec, backend.build_config(spec))

        assert calls[0]["max_proposal_jobs"] == 2
        # Neither the B9 no-op-override warning (build time) nor the
        # _dataclass_kwargs drop-warning (run time) fires for this key.
        assert "max_proposal_jobs" not in capsys.readouterr().err

    def test_default_omits_ctor_kwarg(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No pin, no override: the kwarg is omitted (engine default 6)."""
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(
            tmp_path,
            llm=_make_llm(
                name="remote-llm",
                source="remote",
                provider="anthropic",
                model="claude-x",
                base_url="https://api.anthropic.com/v1",
                api_key_env="MY_ANTHROPIC_KEY",
            ),
        )

        backend.launch(spec, backend.build_config(spec))

        assert "max_proposal_jobs" not in calls[0]

    def test_explicit_null_opts_out_of_pin(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """job_config.max_proposal_jobs=null on a local LLM = engine default.

        PR #254 review: an explicit ``=null`` is the documented opt-out —
        it skips the local auto-pin, and ``_run_engine``'s ``is not None``
        guard omits the constructor kwarg so the engine default (6,
        CPU/memory-scaled) applies. Dry-run drops the ``None`` entry
        (``resolved_config`` filters unset values), consistent with the
        engine receiving no explicit value.
        """
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(
            tmp_path,
            llm=_make_llm(source="local"),
            config_overrides=["job_config.max_proposal_jobs=null"],
        )
        config = backend.build_config(spec)
        assert config["job_config"]["max_proposal_jobs"] is None

        resolved = backend.resolved_config(config)
        backend.launch(spec, config)

        assert "max_proposal_jobs" not in resolved.backend_extras
        assert "max_proposal_jobs" not in calls[0]

    def test_dry_run_display_still_shows_pin(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """resolved_config() keeps surfacing the value the engine receives."""
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path, llm=_make_llm(source="local"))
        config = backend.build_config(spec)

        resolved = backend.resolved_config(config)
        backend.launch(spec, config)

        assert resolved.backend_extras["max_proposal_jobs"] == 1
        assert calls[0]["max_proposal_jobs"] == 1


class TestLlmRequestTimeoutLever:
    """R2 (#320/#260): registry ``timeout_s`` → ``shinka.llm.client.TIMEOUT``.

    shinka 0.0.7 hard-codes its LLM request timeout (1200 s) with no config
    seam; the module global is read at call time, so ``_run_engine``
    set/restores it around the engine run (empirically verified seam —
    spike #320 §2 Run 2). ``build_config`` resolves the neutral per-LLM
    ``timeout_s`` into the Revolver-owned top-level ``llm_timeout`` key
    (ensemble: max over the members that set it) and ``resolved_config``
    surfaces it so ``--dry-run`` is honest about it. Mirrors the OE twins in
    ``tests/test_llm_config.py`` (``test_build_config_injects_timeout``).
    """

    # ── build_config resolution ──────────────────────────────────────────

    def test_build_config_resolves_llm_timeout(self, fake_shinka: None, tmp_path: Path) -> None:
        """A single LLM with timeout_s=300 resolves llm_timeout=300."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path, llm=_make_llm(timeout_s=300)))
        assert config["llm_timeout"] == 300

    def test_build_config_no_llm_timeout_when_unset(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """No timeout_s anywhere → the key stays absent (engine default)."""
        config = ShinkaBackend().build_config(_make_spec(tmp_path))
        assert "llm_timeout" not in config

    def test_ensemble_max_member_timeout_wins(self, fake_shinka: None, tmp_path: Path) -> None:
        """Mixed member timeouts (120/600/unset) → max wins (never truncate
        the slowest member)."""
        db_path = tmp_path / "global.db"
        conn = get_global_db_at(db_path)
        try:
            insert_llm(conn, _make_llm(name="m-a", timeout_s=120))
            insert_llm(conn, _make_llm(name="m-b", timeout_s=600))
            insert_llm(conn, _make_llm(name="m-c"))
            ensemble = EnsembleEntry(
                name="ens",
                members=[
                    EnsembleMember(llm_name="m-a"),
                    EnsembleMember(llm_name="m-b"),
                    EnsembleMember(llm_name="m-c"),
                ],
                created_at=datetime(2026, 1, 1),
            )
            spec = _make_spec(
                tmp_path,
                llm=_make_llm(name="m-a", timeout_s=120),
                ensemble=ensemble,
                conn=conn,
            )
            config = ShinkaBackend().build_config(spec)
        finally:
            conn.close()
        assert config["llm_timeout"] == 600

    def test_ensemble_without_timeouts_leaves_key_absent(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """No member sets timeout_s → the key stays absent (engine default)."""
        db_path = tmp_path / "global.db"
        conn = get_global_db_at(db_path)
        try:
            insert_llm(conn, _make_llm(name="m-a"))
            insert_llm(conn, _make_llm(name="m-b"))
            ensemble = EnsembleEntry(
                name="ens",
                members=[
                    EnsembleMember(llm_name="m-a"),
                    EnsembleMember(llm_name="m-b"),
                ],
                created_at=datetime(2026, 1, 1),
            )
            spec = _make_spec(tmp_path, llm=_make_llm(name="m-a"), ensemble=ensemble, conn=conn)
            config = ShinkaBackend().build_config(spec)
        finally:
            conn.close()
        assert "llm_timeout" not in config

    # ── dry-run surface ──────────────────────────────────────────────────

    def test_resolved_config_surfaces_llm_timeout(self, fake_shinka: None, tmp_path: Path) -> None:
        """The resolved llm_timeout appears in the dry-run backend_extras."""
        backend = ShinkaBackend()
        config = backend.build_config(_make_spec(tmp_path, llm=_make_llm(timeout_s=300)))
        assert backend.resolved_config(config).backend_extras["llm_timeout"] == 300

    def test_resolved_config_omits_llm_timeout_when_unset(
        self, fake_shinka: None, tmp_path: Path
    ) -> None:
        """No timeout resolved → dry-run stays uncluttered (no entry)."""
        backend = ShinkaBackend()
        config = backend.build_config(_make_spec(tmp_path))
        assert "llm_timeout" not in backend.resolved_config(config).backend_extras

    # ── set/restore around the engine run ────────────────────────────────

    def test_launch_sets_and_restores_global_timeout(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """TIMEOUT is 300 for the duration of run() and restored afterwards."""
        observed: list[Any] = []

        def _capture_and_write(call: dict[str, Any]) -> None:
            observed.append(sys.modules["shinka.llm.client"].TIMEOUT)
            _write_fixture_db(call)

        _install_fake_runner(monkeypatch, on_run=_capture_and_write)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path, llm=_make_llm(timeout_s=300))

        backend.launch(spec, backend.build_config(spec))

        assert observed == [300]
        assert sys.modules["shinka.llm.client"].TIMEOUT == _FAKE_SHINKA_DEFAULT_TIMEOUT

    def test_restores_global_timeout_when_engine_raises(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The previous value is restored even when the engine run raises."""
        observed: list[Any] = []

        def _capture_then_boom(call: dict[str, Any]) -> None:
            observed.append(sys.modules["shinka.llm.client"].TIMEOUT)
            raise RuntimeError("boom")

        _install_fake_runner(monkeypatch, on_run=_capture_then_boom)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path, llm=_make_llm(timeout_s=300))

        with pytest.raises(ExternalError, match="ShinkaEvolve run failed"):
            backend.launch(spec, backend.build_config(spec))

        assert observed == [300]
        assert sys.modules["shinka.llm.client"].TIMEOUT == _FAKE_SHINKA_DEFAULT_TIMEOUT

    def test_no_timeout_leaves_global_untouched(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No timeout_s anywhere → the module global is never touched."""
        observed: list[Any] = []

        def _capture_and_write(call: dict[str, Any]) -> None:
            observed.append(sys.modules["shinka.llm.client"].TIMEOUT)
            _write_fixture_db(call)

        _install_fake_runner(monkeypatch, on_run=_capture_and_write)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path)

        backend.launch(spec, backend.build_config(spec))

        assert observed == [_FAKE_SHINKA_DEFAULT_TIMEOUT]
        assert sys.modules["shinka.llm.client"].TIMEOUT == _FAKE_SHINKA_DEFAULT_TIMEOUT

    # ── override escape hatch + degradation ──────────────────────────────

    def test_override_wins_over_registry_timeout(
        self,
        fake_shinka: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--config-override llm_timeout=450 wins over the registry value.

        ``llm_timeout`` is Revolver-owned (:data:`_REVOLVER_SECTIONS`), so
        the B9 no-op-override probe must stay silent for it.
        """
        observed: list[Any] = []

        def _capture_and_write(call: dict[str, Any]) -> None:
            observed.append(sys.modules["shinka.llm.client"].TIMEOUT)
            _write_fixture_db(call)

        _install_fake_runner(monkeypatch, on_run=_capture_and_write)
        backend = ShinkaBackend()
        spec = _make_engine_spec(
            tmp_path,
            llm=_make_llm(timeout_s=300),
            config_overrides=["llm_timeout=450"],
        )
        config = backend.build_config(spec)
        assert config["llm_timeout"] == 450

        backend.launch(spec, config)

        assert observed == [450]
        assert sys.modules["shinka.llm.client"].TIMEOUT == _FAKE_SHINKA_DEFAULT_TIMEOUT
        assert "llm_timeout" not in capsys.readouterr().err

    def test_explicit_null_override_opts_out(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """llm_timeout=null opts out: the global stays untouched (same
        convention as the max_proposal_jobs null opt-out, PR #254)."""
        observed: list[Any] = []

        def _capture_and_write(call: dict[str, Any]) -> None:
            observed.append(sys.modules["shinka.llm.client"].TIMEOUT)
            _write_fixture_db(call)

        _install_fake_runner(monkeypatch, on_run=_capture_and_write)
        backend = ShinkaBackend()
        spec = _make_engine_spec(
            tmp_path,
            llm=_make_llm(timeout_s=300),
            config_overrides=["llm_timeout=null"],
        )
        config = backend.build_config(spec)
        assert config["llm_timeout"] is None

        resolved = backend.resolved_config(config)
        backend.launch(spec, config)

        assert "llm_timeout" not in resolved.backend_extras
        assert observed == [_FAKE_SHINKA_DEFAULT_TIMEOUT]

    def test_invalid_value_warns_and_engine_default_applies(
        self,
        fake_shinka: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A non-numeric llm_timeout warns and never reaches the global —
        a tuning lever must never crash (or silently corrupt) the run."""
        observed: list[Any] = []

        def _capture_and_write(call: dict[str, Any]) -> None:
            observed.append(sys.modules["shinka.llm.client"].TIMEOUT)
            _write_fixture_db(call)

        _install_fake_runner(monkeypatch, on_run=_capture_and_write)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path, config_overrides=["llm_timeout=abc"])

        backend.launch(spec, backend.build_config(spec))

        assert observed == [_FAKE_SHINKA_DEFAULT_TIMEOUT]
        assert sys.modules["shinka.llm.client"].TIMEOUT == _FAKE_SHINKA_DEFAULT_TIMEOUT
        assert "invalid llm_timeout" in capsys.readouterr().err

    def test_missing_client_module_warns_and_run_completes(
        self,
        fake_shinka: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An unexpected shinka layout degrades to a warning, not a crash."""
        # None in sys.modules makes ``import shinka.llm.client`` raise
        # ImportError (halted import) — simulates an upstream restructure.
        monkeypatch.setitem(sys.modules, "shinka.llm", None)  # type: ignore[arg-type]
        monkeypatch.setitem(sys.modules, "shinka.llm.client", None)  # type: ignore[arg-type]
        calls = _install_fake_runner(monkeypatch, on_run=_write_fixture_db)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path, llm=_make_llm(timeout_s=300))

        backend.launch(spec, backend.build_config(spec))

        assert len(calls) == 1  # the run went through
        assert "could not apply llm_timeout" in capsys.readouterr().err


class TestShinkaResume:
    """resume() clones the parent dir and continues on the clone (S16-11)."""

    def test_clones_parent_dir_and_runs_on_clone(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Engine runs on the NEW run's shinka-output/ (a clone of parent)."""
        parent_run_dir = tmp_path / "parent"
        build_shinka_run_dir(parent_run_dir)
        calls = _install_fake_runner(monkeypatch)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path, iterations=4)
        config = backend.build_config(spec)

        result = backend.resume(spec, config, parent_run_dir)

        assert spec.run_dir is not None
        new_output = spec.run_dir / "shinka-output"
        evo_config = calls[0]["evo_config"]
        # The engine runs on the CLONE, never the parent.
        assert evo_config.results_dir == str(new_output)
        assert config["output_dir"] == str(new_output)
        # "Run 4 more": total target = clone last_iteration + iterations.
        assert evo_config.num_generations == EXPECTED_LAST_GENERATION + 4

        # The clone carries the parent's programs DB.
        assert (new_output / SHINKA_PROGRAMS_DB).exists()
        best_file = new_output / "best" / "best_program.py"
        assert best_file.exists()
        assert result.best_score == pytest.approx(EXPECTED_BEST_SCORE)
        assert result.output_dir == new_output

    def test_parent_dir_untouched(
        self, fake_shinka: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The engine writes only to the clone; the parent dir is untouched."""
        parent_run_dir = tmp_path / "parent"
        build_shinka_run_dir(parent_run_dir)
        parent_output = parent_run_dir / "shinka-output"
        parent_db = parent_output / SHINKA_PROGRAMS_DB
        parent_bytes_before = parent_db.read_bytes()

        # The fake engine writes a marker into whatever results_dir it is
        # handed; a parent-mutation regression would drop it in the parent.
        def _write_marker(call: dict[str, Any]) -> None:
            results_dir = Path(call["evo_config"].results_dir)
            (results_dir / "engine_marker.txt").write_text("ran here")

        _install_fake_runner(monkeypatch, on_run=_write_marker)
        backend = ShinkaBackend()
        spec = _make_engine_spec(tmp_path, iterations=4)

        backend.resume(spec, backend.build_config(spec), parent_run_dir)

        assert spec.run_dir is not None
        clone_output = spec.run_dir / "shinka-output"
        # The engine ran on the clone, not the parent.
        assert (clone_output / "engine_marker.txt").exists()
        assert not (parent_output / "engine_marker.txt").exists()
        # And the parent's DB is byte-unchanged.
        assert parent_db.read_bytes() == parent_bytes_before

    def test_missing_parent_db_raises(self, fake_shinka: None, tmp_path: Path) -> None:
        """A parent without programs.sqlite cannot be resumed (fallback)."""
        parent_run_dir = tmp_path / "parent"
        parent_run_dir.mkdir()
        spec = _make_engine_spec(tmp_path)

        with pytest.raises(RevolverError, match="programs database"):
            ShinkaBackend().resume(spec, {}, parent_run_dir)

    def test_unavailable_without_shinka(self, no_shinka: None, tmp_path: Path) -> None:
        """resume() raises the typed not-installed error (exit 3)."""
        parent_run_dir = tmp_path / "parent"
        build_shinka_run_dir(parent_run_dir)
        spec = _make_spec(tmp_path)
        with pytest.raises(BackendUnavailableError):
            ShinkaBackend().resume(spec, {}, parent_run_dir)


class TestShinkaResumePrecheck:
    """resume_precheck() fails fast on a non-resumable parent (S16-10)."""

    def test_passes_on_resumable_parent(self, tmp_path: Path) -> None:
        """A parent with a populated programs.sqlite passes the precheck."""
        parent_run_dir = tmp_path / "parent"
        build_shinka_run_dir(parent_run_dir)
        # No raise (does not require shinka to be importable — pure SQLite).
        ShinkaBackend().resume_precheck(parent_run_dir)

    def test_missing_db_raises(self, tmp_path: Path) -> None:
        """A parent without programs.sqlite is rejected before the insert."""
        parent_run_dir = tmp_path / "parent"
        parent_run_dir.mkdir()
        with pytest.raises(RevolverError, match="programs database"):
            ShinkaBackend().resume_precheck(parent_run_dir)

    def test_zero_last_iteration_raises(self, tmp_path: Path) -> None:
        """A parent whose run never completed a generation is rejected."""
        parent_run_dir = tmp_path / "parent"
        gen0_rows = tuple(row for row in FIXTURE_PROGRAM_ROWS if row["generation"] == 0)
        build_programs_db(parent_run_dir / "shinka-output" / SHINKA_PROGRAMS_DB, rows=gen0_rows)
        with pytest.raises(RevolverError, match="not resumable"):
            ShinkaBackend().resume_precheck(parent_run_dir)


# ── Engine tier: programs.sqlite readers (S14-11/12) ──────────────────────────


@pytest.fixture()
def shinka_run_dir(tmp_path: Path) -> Path:
    """A run dir with the fixture ``shinka-output/programs.sqlite``."""
    return build_shinka_run_dir(tmp_path / "run")


class TestShinkaCollectTokenUsage:
    """collect_token_usage() per the verified 0.0.7 metadata schema."""

    def test_sums_tokens(self, shinka_run_dir: Path) -> None:
        """llm_result token sums; null metadata tolerated; no cost (#300)."""
        usage = ShinkaBackend().collect_token_usage(shinka_run_dir)

        assert usage is not None
        assert usage.prompt_tokens == EXPECTED_PROMPT_TOKENS
        assert usage.completion_tokens == EXPECTED_COMPLETION_TOKENS
        assert not hasattr(usage, "estimated_cost_usd")

    def test_missing_db_returns_none(self, tmp_path: Path) -> None:
        """No programs.sqlite (run died early) -> None, no crash."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        assert ShinkaBackend().collect_token_usage(run_dir) is None


class TestShinkaParsePopulation:
    """parse_population() ranking and field contract (S14-12)."""

    def test_ranked_by_combined_score_desc(self, shinka_run_dir: Path) -> None:
        """Scored programs first, descending; NULL scores listed last."""
        population = ShinkaBackend().parse_population(shinka_run_dir)

        assert population is not None
        assert len(population) == len(FIXTURE_PROGRAM_ROWS)
        scored = [p for p in population if p["combined_score"] is not None]
        assert [p["id"] for p in scored] == list(EXPECTED_RANKED_IDS)
        assert [p["rank"] for p in population] == list(range(1, len(population) + 1))

    def test_no_map_elites_fields(self, shinka_run_dir: Path) -> None:
        """No cell_indices / island keys (ADR-007: no MAP-Elites grid)."""
        population = ShinkaBackend().parse_population(shinka_run_dir)
        assert population is not None
        for entry in population:
            assert "cell_indices" not in entry
            assert "island" not in entry

    def test_display_aliases_for_cli_renderer(self, shinka_run_dir: Path) -> None:
        """run population renderer keys: score/metrics/iteration_found."""
        population = ShinkaBackend().parse_population(shinka_run_dir)
        assert population is not None
        for entry in population:
            assert isinstance(entry["score"], float)
            assert entry["metrics"] == entry["public_metrics"]
            assert entry["iteration_found"] == entry["generation"]
        # NULL combined_score renders as 0.0 (display) but stays None (raw).
        broken = next(p for p in population if p["id"] == "prog-gen2-broken")
        assert broken["score"] == 0.0
        assert broken["combined_score"] is None

    def test_missing_db_returns_none(self, tmp_path: Path) -> None:
        """No programs.sqlite -> None (run population shows 'no checkpoint')."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        assert ShinkaBackend().parse_population(run_dir) is None


class TestShinkaCountValidAndProgress:
    """count_valid() / read_progress() against the fixture DB."""

    def test_count_valid_counts_correct_rows(self, shinka_run_dir: Path) -> None:
        assert ShinkaBackend().count_valid(shinka_run_dir) == EXPECTED_VALID_COUNT

    def test_count_valid_missing_db_returns_none(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        assert ShinkaBackend().count_valid(run_dir) is None

    def test_read_progress_returns_generation_and_best(self, shinka_run_dir: Path) -> None:
        iterations_done, best_score = ShinkaBackend().read_progress(shinka_run_dir)
        assert iterations_done == EXPECTED_LAST_GENERATION
        assert best_score == pytest.approx(EXPECTED_BEST_SCORE)

    def test_read_progress_missing_db(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        assert ShinkaBackend().read_progress(run_dir) == (None, None)
