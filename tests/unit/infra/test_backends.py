"""Tests for the evolution backend abstraction (S13 PR-A, ADR-007).

Covers the ``get_backend()`` factory, the ``OpenEvolveBackend`` adapter
delegation, the ``ShinkaBackend`` stub, and the ``revolver.infra.openevolve``
re-export shim.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from revolver.core.exceptions import ResourceError, RevolverError, ValidationError
from revolver.infra.backends import (
    AVAILABLE_BACKENDS,
    BackendCapabilities,
    BackendRunResult,
    BackendRunSpec,
    BackendUnavailableError,
    EvolutionBackend,
    OpenEvolveBackend,
    ShinkaBackend,
    get_backend,
)
from revolver.infra.backends.openevolve import RunOutput
from revolver.models.llm import LLMEntry
from revolver.models.run import ResolvedConfig

pytestmark = [pytest.mark.unit]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_llm(**kwargs: object) -> LLMEntry:
    """Create an LLMEntry with sensible defaults."""
    defaults = {
        "name": "test-llm",
        "model": "test-model",
        "source": "remote",
        "base_url": "http://localhost:11434/v1",
        "registered_at": datetime(2026, 1, 1),
    }
    defaults.update(kwargs)
    return LLMEntry(**defaults)  # type: ignore[arg-type]


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


def _write_checkpoint(run_dir: Path, n: int = 1) -> Path:
    """Create a minimal OE checkpoint with 2 programs and a database.json."""
    checkpoint = run_dir / "oe-output" / "checkpoints" / f"checkpoint_{n}"
    programs_dir = checkpoint / "programs"
    programs_dir.mkdir(parents=True)
    (programs_dir / "prog-a.json").write_text(
        json.dumps({"id": "prog-a", "metrics": {"combined_score": 0.9}, "generation": 1})
    )
    (programs_dir / "prog-b.json").write_text(
        json.dumps({"id": "prog-b", "metrics": {"combined_score": 0.5}, "generation": 1})
    )
    (checkpoint / "database.json").write_text(json.dumps([{"id": "prog-a"}, {"id": "prog-b"}]))
    (checkpoint / "metadata.json").write_text(json.dumps({"best_program_id": "prog-a"}))
    return checkpoint


# ── Factory tests ─────────────────────────────────────────────────────────────


class TestGetBackend:
    """Tests for the get_backend() factory."""

    def test_openevolve_returns_openevolve_backend(self) -> None:
        """get_backend('openevolve') returns an OpenEvolveBackend."""
        backend = get_backend("openevolve")
        assert isinstance(backend, OpenEvolveBackend)
        assert backend.name == "openevolve"

    def test_shinka_returns_shinka_backend(self) -> None:
        """get_backend('shinka') returns the registered ShinkaBackend stub."""
        backend = get_backend("shinka")
        assert isinstance(backend, ShinkaBackend)
        assert backend.name == "shinka"

    def test_unknown_backend_raises_validation_error_exit1(self) -> None:
        """Unknown backend name raises ValidationError (exit code 1)."""
        with pytest.raises(ValidationError) as exc_info:
            get_backend("nope")
        assert exc_info.value.exit_code == 1
        message = str(exc_info.value)
        assert "nope" in message
        for name in AVAILABLE_BACKENDS:
            assert name in message

    def test_backends_satisfy_protocol(self) -> None:
        """Both registered backends satisfy the EvolutionBackend protocol."""
        assert isinstance(get_backend("openevolve"), EvolutionBackend)
        assert isinstance(get_backend("shinka"), EvolutionBackend)

    def test_available_backends_constant(self) -> None:
        """AVAILABLE_BACKENDS lists both registered backends."""
        assert AVAILABLE_BACKENDS == ("openevolve", "shinka")


# ── Error type tests ──────────────────────────────────────────────────────────


class TestBackendUnavailableError:
    """Tests for BackendUnavailableError exit-code mapping."""

    def test_is_resource_error(self) -> None:
        """BackendUnavailableError integrates with the typed hierarchy."""
        assert issubclass(BackendUnavailableError, ResourceError)
        assert issubclass(BackendUnavailableError, RevolverError)

    def test_exit_code_is_3(self) -> None:
        """BackendUnavailableError maps to exit code 3 (resource error)."""
        assert BackendUnavailableError("nope").exit_code == 3


# ── OpenEvolveBackend tests ───────────────────────────────────────────────────


class TestOpenEvolveBackendCapabilities:
    """Capability matrix and token strategy of the OpenEvolve backend."""

    def test_capabilities_match_adr007(self) -> None:
        """Capabilities follow the ADR-007 matrix for OpenEvolve."""
        caps = OpenEvolveBackend().capabilities()
        assert caps == BackendCapabilities(
            global_seed=True,
            map_elites_cells=True,
            native_cost_tracking=False,
            multi_language=False,
            ensemble_model="weighted",
            top_n_extraction=False,
        )

    def test_wants_http_proxy(self) -> None:
        """OpenEvolve token counting goes through the HTTP proxy."""
        assert OpenEvolveBackend().wants_http_proxy() is True

    def test_collect_token_usage_returns_none(self) -> None:
        """No engine-native token accounting — proxy stays in core.run."""
        assert OpenEvolveBackend().collect_token_usage(Path("/nonexistent")) is None

    def test_is_available_reflects_package_presence(self) -> None:
        """is_available() reports the openevolve package install state."""
        available, hint = OpenEvolveBackend().is_available()
        if importlib.util.find_spec("openevolve") is None:
            assert available is False
            assert hint is not None and "revolver[openevolve]" in hint
        else:
            assert available is True
            assert hint is None


class TestOpenEvolveBackendDelegation:
    """Delegation smoke tests — the adapter wraps the existing functions."""

    def test_validate_config_delegates(self) -> None:
        """validate_config() delegates to validate_oe_config()."""
        with patch(
            "revolver.infra.backends.openevolve.validate_oe_config",
            return_value=["some warning"],
        ) as mock_validate:
            warnings = OpenEvolveBackend().validate_config({"max_iterations": 5})
        mock_validate.assert_called_once_with({"max_iterations": 5})
        assert warnings == ["some warning"]

    def test_validate_config_returns_list(self) -> None:
        """validate_config() returns a (possibly empty) warning list."""
        warnings = OpenEvolveBackend().validate_config({"max_iterations": 5})
        assert isinstance(warnings, list)

    def test_config_template_serves_project_init_scaffold(self) -> None:
        """config_template() returns the OE-shaped config.yaml template."""
        template = OpenEvolveBackend().config_template()
        assert "OpenEvolve configuration" in template
        assert "llm:" in template

    def test_build_config_merges_llm_and_iterations(self, tmp_path: Path) -> None:
        """build_config() delegates to the module-level config builder."""
        spec = _make_spec(tmp_path, iterations=42)
        (spec.snapshot_dir / "config.yaml").write_text("checkpoint_interval: 7\n")

        config = OpenEvolveBackend().build_config(spec)

        assert config["max_iterations"] == 42
        assert config["llm"]["primary_model"] == "test-model"
        assert config["llm"]["api_base"] == "http://localhost:11434/v1"
        assert config["checkpoint_interval"] == 7

    def test_resolved_config_extracts_dry_run_fields(self) -> None:
        """resolved_config() produces the neutral ResolvedConfig (ADR-007 D4)."""
        config = {
            "max_iterations": 5,
            "database": {"num_islands": 3},
            "llm": {"temperature": 0.4},
        }
        resolved = OpenEvolveBackend().resolved_config(config, {"k": "v"})
        assert isinstance(resolved, ResolvedConfig)
        assert resolved.backend == "openevolve"
        assert resolved.iterations == 5
        assert resolved.num_islands == 3
        assert resolved.temperature == 0.4
        assert resolved.config_overrides == {"k": "v"}
        # No OE-exclusive key is set in this config → extras stay empty
        assert resolved.backend_extras == {}

    def test_resolved_config_routes_oe_keys_into_backend_extras(self) -> None:
        """OE-exclusive parameters land in backend_extras (ADR-007 D4)."""
        config = {
            "max_iterations": 5,
            "checkpoint_interval": 2,
            "diff_based_evolution": False,
            "max_code_length": 50000,
            "database": {"feature_dimensions": ["complexity"], "feature_bins": 7},
            "evaluator": {"parallel_evaluations": 4},
        }
        resolved = OpenEvolveBackend().resolved_config(config)
        assert resolved.backend_extras == {
            "checkpoint_interval": 2,
            "feature_dimensions": ["complexity"],
            "feature_bins": 7,
            "parallel_evaluations": 4,
            "diff_based_evolution": False,
            "max_code_length": 50000,
        }

    def test_generate_wrapper_writes_into_run_dir(self, tmp_path: Path) -> None:
        """generate_wrapper() generates the wrapper evaluator in run_dir."""
        spec = _make_spec(tmp_path)
        (spec.snapshot_dir / "evaluator.py").write_text(
            "def evaluate_instance(program_path, instance_path):\n"
            "    return {'combined_score': 1.0}\n"
        )

        wrapper = OpenEvolveBackend().generate_wrapper(spec)

        assert wrapper == spec.run_dir / "_revolver_evaluator.py"
        assert wrapper.exists()

    def test_generate_wrapper_requires_run_dir(self, tmp_path: Path) -> None:
        """generate_wrapper() without run_dir raises ValidationError."""
        spec = _make_spec(tmp_path, run_dir=None)
        with pytest.raises(ValidationError):
            OpenEvolveBackend().generate_wrapper(spec)


class TestOpenEvolveBackendLaunch:
    """launch()/resume() wiring with a mocked OpenEvolveRunner."""

    def test_launch_runs_openevolve_and_maps_result(self, tmp_path: Path) -> None:
        """launch() drives OpenEvolveRunner and maps RunOutput."""
        spec = _make_spec(tmp_path)
        config: dict[str, Any] = {"max_iterations": 3}
        output_dir = spec.run_dir / "oe-output"  # type: ignore[operator]

        with patch("revolver.infra.backends.openevolve.OpenEvolveRunner") as mock_runner_cls:
            mock_runner_cls.return_value.run.return_value = RunOutput(
                best_score=0.95, best_program=None, output_dir=output_dir
            )
            result = OpenEvolveBackend().launch(spec, config)

        mock_runner_cls.assert_called_once_with(
            initial_program=spec.snapshot_dir / "initial_program.py",
            evaluator=spec.run_dir / "_revolver_evaluator.py",  # type: ignore[operator]
            config=config,
            output_dir=output_dir,
        )
        mock_runner_cls.return_value.run.assert_called_once_with(iterations=3, on_progress=None)
        assert isinstance(result, BackendRunResult)
        assert result.best_score == 0.95
        assert result.output_dir == output_dir
        assert config["output_dir"] == str(output_dir)
        assert output_dir.is_dir()

    def test_launch_prefers_spec_iterations_and_wrapper_path(self, tmp_path: Path) -> None:
        """launch() uses spec.iterations and spec.wrapper_path when given."""
        wrapper = tmp_path / "custom_wrapper.py"
        spec = _make_spec(tmp_path, iterations=9, wrapper_path=wrapper)

        with patch("revolver.infra.backends.openevolve.OpenEvolveRunner") as mock_runner_cls:
            mock_runner_cls.return_value.run.return_value = RunOutput()
            OpenEvolveBackend().launch(spec, {"max_iterations": 3})

        assert mock_runner_cls.call_args.kwargs["evaluator"] == wrapper
        mock_runner_cls.return_value.run.assert_called_once_with(iterations=9, on_progress=None)

    def test_launch_requires_run_dir(self, tmp_path: Path) -> None:
        """launch() without run_dir raises ValidationError."""
        spec = _make_spec(tmp_path, run_dir=None)
        with pytest.raises(ValidationError):
            OpenEvolveBackend().launch(spec, {})

    def test_resume_copies_parent_checkpoint(self, tmp_path: Path) -> None:
        """resume() stages the parent's latest checkpoint as oe-checkpoint."""
        parent_run_dir = tmp_path / "parent"
        parent_run_dir.mkdir()
        _write_checkpoint(parent_run_dir, n=5)
        spec = _make_spec(tmp_path)
        staged = spec.run_dir / "oe-checkpoint"  # type: ignore[operator]

        with patch("revolver.infra.backends.openevolve.OpenEvolveRunner") as mock_runner_cls:
            mock_runner_cls.return_value.run.return_value = RunOutput(best_score=0.7)
            result = OpenEvolveBackend().resume(spec, {"max_iterations": 4}, parent_run_dir)

        assert staged.is_dir()
        assert (staged / "database.json").exists()
        mock_runner_cls.return_value.run.assert_called_once_with(
            iterations=4, checkpoint=staged, on_progress=None
        )
        assert result.best_score == 0.7

    def test_resume_uses_pre_staged_checkpoint(self, tmp_path: Path) -> None:
        """resume() leaves an already-staged oe-checkpoint untouched."""
        parent_run_dir = tmp_path / "parent"
        parent_run_dir.mkdir()
        spec = _make_spec(tmp_path)
        staged = spec.run_dir / "oe-checkpoint"  # type: ignore[operator]
        staged.mkdir()
        (staged / "marker.txt").write_text("staged")

        with patch("revolver.infra.backends.openevolve.OpenEvolveRunner") as mock_runner_cls:
            mock_runner_cls.return_value.run.return_value = RunOutput()
            OpenEvolveBackend().resume(spec, {}, parent_run_dir)

        assert (staged / "marker.txt").read_text() == "staged"
        assert mock_runner_cls.return_value.run.call_args.kwargs["checkpoint"] == staged

    def test_resume_without_parent_checkpoint_raises(self, tmp_path: Path) -> None:
        """resume() with no parent checkpoint raises RevolverError (exit 1)."""
        parent_run_dir = tmp_path / "parent"
        parent_run_dir.mkdir()
        spec = _make_spec(tmp_path)

        with pytest.raises(RevolverError) as exc_info:
            OpenEvolveBackend().resume(spec, {}, parent_run_dir)
        assert "No checkpoint found" in str(exc_info.value)
        assert exc_info.value.exit_code == 1


class TestOpenEvolveBackendCheckpointReads:
    """read_progress() / parse_population() / count_valid() over run dirs."""

    def test_read_progress_without_checkpoint(self, tmp_path: Path) -> None:
        """No checkpoint yet — read_progress() returns (None, None)."""
        assert OpenEvolveBackend().read_progress(tmp_path) == (None, None)

    def test_read_progress_with_checkpoint(self, tmp_path: Path) -> None:
        """read_progress() returns (valid_count, best_score) from checkpoint."""
        _write_checkpoint(tmp_path)
        iterations_done, best_score = OpenEvolveBackend().read_progress(tmp_path)
        assert iterations_done == 2
        assert best_score == 0.9

    def test_parse_population_without_checkpoint_returns_none(self, tmp_path: Path) -> None:
        """No checkpoint — parse_population() returns None (not [])."""
        assert OpenEvolveBackend().parse_population(tmp_path) is None

    def test_parse_population_ranks_programs(self, tmp_path: Path) -> None:
        """parse_population() returns programs ranked by score descending."""
        _write_checkpoint(tmp_path)
        population = OpenEvolveBackend().parse_population(tmp_path)
        assert population is not None
        assert [p["id"] for p in population] == ["prog-a", "prog-b"]
        assert population[0]["rank"] == 1

    def test_count_valid_without_any_state(self, tmp_path: Path) -> None:
        """No checkpoint and no oe-output — count_valid() returns None."""
        assert OpenEvolveBackend().count_valid(tmp_path) is None

    def test_count_valid_from_checkpoint(self, tmp_path: Path) -> None:
        """count_valid() counts database.json entries in the checkpoint."""
        _write_checkpoint(tmp_path)
        assert OpenEvolveBackend().count_valid(tmp_path) == 2

    def test_count_valid_falls_back_to_oe_output(self, tmp_path: Path) -> None:
        """Without a checkpoint, count_valid() falls back to oe-output/."""
        oe_output = tmp_path / "oe-output"
        oe_output.mkdir()
        (oe_output / "database.json").write_text(
            json.dumps([{"id": "a"}, {"id": "b"}, {"id": "c"}])
        )
        assert OpenEvolveBackend().count_valid(tmp_path) == 3


# ── ShinkaBackend availability contract ──────────────────────────────────────


class TestShinkaBackendAvailability:
    """ShinkaEvolve availability surface on an env WITHOUT shinka.

    The config tier is covered by ``tests/unit/infra/test_shinka_backend.py``
    (S14 PR-B), the engine tier by the same file's launch/resume classes
    (S14 PR-C, fake runner). This class pins the run-path fail-fast: the
    engine-launching methods raise the typed not-installed error (exit 3)
    before any side effect. The ``programs.sqlite`` readers
    (read_progress/parse_population/count_valid/collect_token_usage) are
    pure SQLite readers since PR-C and intentionally work without shinka
    (they return ``None``-ish values for a missing database instead).
    """

    def test_capabilities_match_adr007(self) -> None:
        """Capabilities follow the ADR-007 matrix for ShinkaEvolve."""
        caps = ShinkaBackend().capabilities()
        assert caps == BackendCapabilities(
            global_seed=False,
            map_elites_cells=False,
            native_cost_tracking=True,
            multi_language=True,
            ensemble_model="bandit",
            top_n_extraction=True,
        )

    def test_is_available_false_with_install_hint(self, no_shinka: None) -> None:
        """is_available() reports not installed with the install hint."""
        available, hint = ShinkaBackend().is_available()
        assert available is False
        assert hint is not None
        assert "pip install 'revolver[shinka]'" in hint

    def test_wants_http_proxy_false(self) -> None:
        """ShinkaEvolve tracks tokens natively — no HTTP proxy."""
        assert ShinkaBackend().wants_http_proxy() is False

    @pytest.mark.parametrize(
        "call",
        [
            # build_config gates on is_available() so `run --backend shinka`
            # keeps failing fast (exit 3) before any side effect (S14-08);
            # launch()/resume() gate again when reached directly (S14-10/13;
            # resume's not-installed path needs a parent programs DB and is
            # covered in test_shinka_backend.py::TestShinkaResume).
            pytest.param(lambda b, s: b.build_config(s), id="build_config"),
            pytest.param(lambda b, s: b.launch(s, {}), id="launch"),
        ],
    )
    def test_engine_launch_methods_raise_backend_unavailable(
        self,
        no_shinka: None,
        call: Callable[[ShinkaBackend, BackendRunSpec], object],
        tmp_path: Path,
    ) -> None:
        """Engine-launching methods raise BackendUnavailableError (exit 3)."""
        spec = _make_spec(tmp_path)
        with pytest.raises(BackendUnavailableError) as exc_info:
            call(ShinkaBackend(), spec)
        assert exc_info.value.exit_code == 3
        assert "pip install 'revolver[shinka]'" in str(exc_info.value)

    def test_db_readers_tolerate_missing_database(self, tmp_path: Path) -> None:
        """The sqlite readers need no engine install (ADR-007 D2)."""
        backend = ShinkaBackend()
        assert backend.read_progress(tmp_path) == (None, None)
        assert backend.parse_population(tmp_path) is None
        assert backend.count_valid(tmp_path) is None
        assert backend.collect_token_usage(tmp_path) is None


# ── Re-export shim tests ──────────────────────────────────────────────────────


class TestOpenEvolveReexportShim:
    """The deprecated revolver.infra.openevolve shim keeps old imports working."""

    def test_public_names_resolve_to_backend_module(self) -> None:
        """Every name in the shim's __all__ is the backends.openevolve object."""
        from revolver.infra import openevolve as shim
        from revolver.infra.backends import openevolve as impl

        for name in shim.__all__:
            assert getattr(shim, name) is getattr(impl, name), name

    def test_legacy_imports_still_work(self) -> None:
        """Existing import style (incl. private helpers) keeps working."""
        from revolver.infra.openevolve import (
            SYSTEM_PROMPT_TEMPLATE,
            OpenEvolveRunner,
            RunOutput,
            _extract_best_score,
            _parse_value,
            build_config,
            resolve_api_keys,
            revolver_env,
            validate_oe_config,
        )

        assert callable(build_config)
        assert callable(resolve_api_keys)
        assert callable(validate_oe_config)
        assert callable(_extract_best_score)
        assert _parse_value("42") == 42
        assert "{problem_description}" in SYSTEM_PROMPT_TEMPLATE
        assert OpenEvolveRunner is not None
        assert RunOutput is not None
        assert revolver_env is not None
