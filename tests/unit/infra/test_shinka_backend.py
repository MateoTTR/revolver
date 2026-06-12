"""Unit tests for the ShinkaBackend config tier (S14 PR-B, ADR-007).

Covers S14-05..09: the ``default_output_subdir`` protocol seam, the
backend-delegated crash-status counting, ``is_available()``,
``config_template()``, ``validate_config()``, ``build_config()`` (LLM
projection per ADR-007 D5), ``resolved_config()`` and
``generate_wrapper()`` (R4 risk materializer).

All tests run WITHOUT shinka installed: availability-dependent paths use
fake ``shinka.*`` modules injected into ``sys.modules``, and the wrapper
execution tests exercise the generated script's standalone fallback.
"""

from __future__ import annotations

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

from revolver.core.exceptions import EvaluatorLoadError, ValidationError
from revolver.core.run import _determine_crash_status
from revolver.infra.backends.base import (
    BackendRunSpec,
    BackendUnavailableError,
)
from revolver.infra.backends.openevolve import OpenEvolveBackend
from revolver.infra.backends.shinka import (
    SHINKA_WRAPPER_FILENAME,
    ShinkaBackend,
)
from revolver.models.llm import EnsembleEntry, EnsembleMember, LLMEntry

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
    """Field-name stand-in for shinka.launch.LocalJobConfig (subset)."""

    eval_program_path: str | None = "evaluate.py"
    extra_cmd_args: dict[str, Any] = dataclasses.field(default_factory=dict)
    time: str | None = None
    conda_env: str | None = None


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
    monkeypatch.setitem(sys.modules, "shinka", pkg)
    monkeypatch.setitem(sys.modules, "shinka.core", core)
    monkeypatch.setitem(sys.modules, "shinka.database", database)
    monkeypatch.setitem(sys.modules, "shinka.launch", launch)


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

    def test_unavailable_without_shinka(self) -> None:
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


# ── validate_config (S14-07) ─────────────────────────────────────────────────


class TestShinkaValidateConfig:
    """validate_config() checks keys against the Shinka dataclasses."""

    def test_graceful_without_shinka(self) -> None:
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

    def test_unavailable_raises_backend_unavailable(self, tmp_path: Path) -> None:
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
