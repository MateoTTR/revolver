"""Tests for the OpenEvolve wrapper (S4-01).

All tests mock the OpenEvolve controller to avoid a hard dependency.
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from revolver.core.exceptions import ExternalError, ValidationError
from revolver.infra.openevolve import (
    SYSTEM_PROMPT_TEMPLATE,
    OpenEvolveRunner,
    RunOutput,
    _extract_best_score,
    _parse_value,
    build_config,
    resolve_api_keys,
    revolver_env,
)
from revolver.models.llm import LLMEntry

pytestmark = [pytest.mark.unit]

FIXTURES = Path(__file__).parents[2] / "fixtures"


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


# ── OpenEvolveRunner tests ────────────────────────────────────────────────────


class TestOpenEvolveRunner:
    """Tests for OpenEvolveRunner."""

    def test_run_calls_controller(self, tmp_path: Path) -> None:
        """Mocked controller, verify run() is called with correct args."""
        mock_controller = MagicMock()
        mock_run = AsyncMock(return_value=0.95)
        mock_controller.run = mock_run

        runner = OpenEvolveRunner(
            initial_program=tmp_path / "prog.py",
            evaluator=tmp_path / "eval.py",
            config={"max_iterations": 10},
            output_dir=tmp_path / "output",
        )

        with patch("revolver.infra.openevolve.OpenEvolveRunner._init_controller") as mock_init:

            def set_controller() -> None:
                runner._controller = mock_controller

            mock_init.side_effect = set_controller
            result = runner.run(iterations=10)

        mock_init.assert_called_once()
        mock_controller.run.assert_called_once()
        assert isinstance(result, RunOutput)
        assert result.best_score == pytest.approx(0.95)

    def test_run_with_checkpoint(self, tmp_path: Path) -> None:
        """Run with checkpoint path passes it to controller."""
        mock_controller = MagicMock()
        mock_controller.run = AsyncMock(return_value=0.8)

        runner = OpenEvolveRunner(
            initial_program=tmp_path / "prog.py",
            evaluator=tmp_path / "eval.py",
            config={},
            output_dir=tmp_path / "output",
        )
        runner._controller = mock_controller

        checkpoint = tmp_path / "checkpoint"
        result = runner.run(iterations=5, checkpoint=checkpoint)

        call_kwargs = mock_controller.run.call_args
        assert call_kwargs is not None
        assert call_kwargs[1]["checkpoint_path"] == str(checkpoint)
        assert isinstance(result, RunOutput)
        assert result.best_score == pytest.approx(0.8)

    def test_run_openevolve_not_installed(self, tmp_path: Path) -> None:
        """ExternalError raised when openevolve is not importable."""
        runner = OpenEvolveRunner(
            initial_program=tmp_path / "prog.py",
            evaluator=tmp_path / "eval.py",
            config={},
            output_dir=tmp_path / "output",
        )

        with (
            patch.dict("sys.modules", {"openevolve": None, "openevolve.controller": None}),
            pytest.raises(ExternalError, match="OpenEvolve is not installed"),
        ):
            runner._init_controller()

    def test_run_controller_exception(self, tmp_path: Path) -> None:
        """ExternalError raised when the controller fails."""
        mock_controller = MagicMock()
        mock_controller.run = AsyncMock(side_effect=RuntimeError("boom"))

        runner = OpenEvolveRunner(
            initial_program=tmp_path / "prog.py",
            evaluator=tmp_path / "eval.py",
            config={},
            output_dir=tmp_path / "output",
        )
        runner._controller = mock_controller

        with pytest.raises(ExternalError, match="OpenEvolve run failed"):
            runner.run(iterations=1)


# ── build_config tests ────────────────────────────────────────────────────────


class TestBuildConfig:
    """Tests for build_config()."""

    def test_merge_order(self, tmp_path: Path) -> None:
        """Base config + LLM + iterations + overrides applied in order."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "max_iterations": 10,
                    "population_size": 5,
                    "llm": {"primary_model": "base-model", "temperature": 0.8},
                }
            )
        )

        llm = _make_llm(
            base_url="http://myhost:1234/v1",
            model="override-model",
        )

        result = build_config(
            problem_config=config_file,
            llm=llm,
            iterations=20,
            config_overrides=["llm.temperature=0.5", "population_size=10"],
            output_dir=tmp_path / "output",
        )

        # Base values preserved
        assert result["population_size"] == 10  # overridden
        # LLM endpoint injected (OpenEvolve field names)
        assert result["llm"]["api_base"] == "http://myhost:1234/v1"
        assert result["llm"]["primary_model"] == "override-model"
        # Iterations overridden (OpenEvolve field name)
        assert result["max_iterations"] == 20
        # Config overrides applied
        assert result["llm"]["temperature"] == 0.5
        # Output dir set
        assert result["output_dir"] == str(tmp_path / "output")
        # Negative assertions: no stale legacy keys
        assert "iterations" not in result
        assert "model" not in result.get("llm", {})
        assert "base_url" not in result.get("llm", {})

    def test_problem_description_injection(self, tmp_path: Path) -> None:
        """System prompt includes problem.md content when provided."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            problem_description="Optimize the TSP solver.",
        )

        assert "prompt" in result
        assert "system_message" in result["prompt"]
        assert "Optimize the TSP solver." in result["prompt"]["system_message"]
        assert "EVOLVE-BLOCK" in result["prompt"]["system_message"]

    def test_no_problem_description(self, tmp_path: Path) -> None:
        """No prompt section when problem_description is None."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            problem_description=None,
        )
        assert "prompt" not in result

    def test_api_key_env_stored_not_resolved(self, tmp_path: Path) -> None:
        """build_config stores api_key_env name, NOT the resolved secret."""
        llm = _make_llm(api_key_env="MY_API_KEY")
        with patch.dict(os.environ, {"MY_API_KEY": "sk-test-12345"}):
            result = build_config(problem_config=None, llm=llm)

        # The env var NAME is stored, not the resolved value
        assert result["llm"]["api_key_env"] == "MY_API_KEY"
        assert "api_key" not in result["llm"]

    def test_api_key_env_stored_even_when_unset(self, tmp_path: Path) -> None:
        """api_key_env is stored even if the env var is not currently set."""
        llm = _make_llm(api_key_env="NONEXISTENT_KEY")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NONEXISTENT_KEY", None)
            result = build_config(problem_config=None, llm=llm)

        # The env var name is always stored when api_key_env is set on the LLM
        assert result["llm"]["api_key_env"] == "NONEXISTENT_KEY"
        assert "api_key" not in result.get("llm", {})

    def test_config_override_types(self) -> None:
        """Config overrides parse int, float, bool, and string values."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            config_overrides=[
                "count=42",
                "rate=3.14",
                "enabled=true",
                "disabled=false",
                "name=hello",
            ],
        )
        assert result["count"] == 42
        assert result["rate"] == pytest.approx(3.14)
        assert result["enabled"] is True
        assert result["disabled"] is False
        assert result["name"] == "hello"

    def test_config_override_json_array(self) -> None:
        """Config override with JSON array value is parsed as Python list (S9-12)."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            config_overrides=["feature_dimensions=[0,1]"],
        )
        assert result["feature_dimensions"] == [0, 1]
        assert isinstance(result["feature_dimensions"], list)

    def test_config_override_json_object(self) -> None:
        """Config override with JSON object value is parsed as Python dict (S9-12)."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            config_overrides=['evaluator.params={"key":"val"}'],
        )
        assert result["evaluator"]["params"] == {"key": "val"}
        assert isinstance(result["evaluator"]["params"], dict)

    def test_missing_config_file(self) -> None:
        """Missing config file produces empty base config."""
        llm = _make_llm()
        result = build_config(
            problem_config=Path("/nonexistent/config.yaml"),
            llm=llm,
        )
        # LLM config should still be present
        assert "llm" in result
        assert result["llm"]["primary_model"] == "test-model"

    def test_build_config_null_llm_key(self, tmp_path: Path) -> None:
        """build_config works when base config has ``llm: null``."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"llm": None, "prompt": None}))

        llm = _make_llm()
        result = build_config(
            problem_config=config_file,
            llm=llm,
            problem_description="Test problem",
        )

        assert isinstance(result["llm"], dict)
        assert result["llm"]["primary_model"] == "test-model"
        assert isinstance(result["prompt"], dict)
        assert "system_message" in result["prompt"]

    def test_strips_revolver_specific_keys(self, tmp_path: Path) -> None:
        """Revolver keys (evaluator, initial_program) are stripped from config dict.

        Regression test for v0.4.2: these strings clash with OpenEvolve's
        Config.evaluator (type EvaluatorConfig).
        """
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "initial_program": "initial_program.py",
                    "evaluator": "evaluator.py",
                    "max_iterations": 100,
                }
            )
        )

        llm = _make_llm()
        result = build_config(problem_config=config_file, llm=llm)

        # String-valued evaluator/initial_program are stripped;
        # evaluator is re-injected as a dict with cascade_evaluation.
        assert result.get("evaluator") != "evaluator.py"
        assert isinstance(result.get("evaluator"), dict)
        assert "initial_program" not in result
        assert result["max_iterations"] == 100

    def test_maps_num_generations_to_max_iterations(self, tmp_path: Path) -> None:
        """num_generations in config.yaml is mapped to max_iterations."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"num_generations": 50}))

        llm = _make_llm()
        result = build_config(problem_config=config_file, llm=llm)

        assert "num_generations" not in result
        assert result["max_iterations"] == 50

    def test_iterations_override_wins_over_num_generations(self, tmp_path: Path) -> None:
        """--iterations override takes precedence over num_generations."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"num_generations": 50}))

        llm = _make_llm()
        result = build_config(problem_config=config_file, llm=llm, iterations=3)

        assert "num_generations" not in result
        assert result["max_iterations"] == 3

    def test_max_iterations_wins_over_num_generations(self, tmp_path: Path) -> None:
        """When both num_generations and max_iterations are present, max_iterations wins."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"num_generations": 50, "max_iterations": 100}))

        llm = _make_llm()
        result = build_config(problem_config=config_file, llm=llm)

        assert "num_generations" not in result
        assert result["max_iterations"] == 100

    def test_malformed_override_raises(self) -> None:
        """Malformed config override (missing =) raises ValidationError."""
        llm = _make_llm()
        with pytest.raises(ValidationError, match="Malformed config override"):
            build_config(
                problem_config=None,
                llm=llm,
                config_overrides=["no-equals-sign"],
            )

    def test_system_prompt_template_format(self) -> None:
        """SYSTEM_PROMPT_TEMPLATE contains expected placeholders."""
        rendered = SYSTEM_PROMPT_TEMPLATE.format(problem_description="My test problem")
        assert "My test problem" in rendered
        assert "EVOLVE-BLOCK" in rendered
        assert "Problem Description" in rendered

    # ── FB-02: Google provider detection ─────────────────────────────────

    def test_build_config_google_disables_seed(self) -> None:
        """Google provider sets both top-level and llm random_seed to None."""
        llm = _make_llm(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        )
        result = build_config(problem_config=None, llm=llm)

        # Top-level random_seed is what OpenEvolve sends to the API
        assert result["random_seed"] is None
        # llm-level random_seed also set for completeness
        assert result["llm"]["random_seed"] is None

    def test_build_config_google_generic_url_no_seed_disable(self) -> None:
        """Generic googleapis.com URL does NOT trigger seed disabling.

        Only generativelanguage.googleapis.com is a known Google LLM provider.
        """
        llm = _make_llm(
            base_url="https://some-api.googleapis.com/v1",
        )
        result = build_config(problem_config=None, llm=llm)

        # random_seed should NOT be set to None for non-Gemini googleapis URLs
        llm_cfg = result.get("llm", {})
        assert "random_seed" not in llm_cfg

    def test_build_config_non_google_seed_unchanged(self) -> None:
        """Non-Google LLM does not have random_seed set to None."""
        llm = _make_llm(
            base_url="http://localhost:11434/v1",
        )
        result = build_config(problem_config=None, llm=llm)

        # random_seed should NOT be in the config at all (neither top-level nor llm)
        assert "random_seed" not in result
        llm_cfg = result.get("llm", {})
        assert "random_seed" not in llm_cfg

    def test_build_config_google_seed_override_preserved(self) -> None:
        """Explicit --config-override random_seed=42 wins over Google detection."""
        llm = _make_llm(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        )
        result = build_config(
            problem_config=None,
            llm=llm,
            config_overrides=["random_seed=42", "llm.random_seed=42"],
        )

        # User override (step 5) should win over Google detection (step 2.5)
        assert result["random_seed"] == 42
        assert result["llm"]["random_seed"] == 42

    # ── S9-10: --temperature CLI flag ──────────────────────────────────────

    def test_run_temperature_flag(self) -> None:
        """build_config(..., temperature=0.5) sets config['llm']['temperature'] (S9-10)."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            temperature=0.5,
        )
        assert result["llm"]["temperature"] == 0.5

    def test_run_temperature_none_leaves_existing(self, tmp_path: Path) -> None:
        """temperature=None leaves existing temperature value unchanged (S9-10)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("llm:\n  temperature: 0.8\n")

        llm = _make_llm()
        result = build_config(
            problem_config=config_file,
            llm=llm,
            temperature=None,
        )
        # Base config temperature should be preserved
        assert result["llm"]["temperature"] == 0.8

    def test_run_temperature_overrides_llm_registry(self) -> None:
        """CLI --temperature overrides LLM registry temperature (S9-10)."""
        llm = _make_llm(temperature=0.3)
        result = build_config(
            problem_config=None,
            llm=llm,
            temperature=0.9,
        )
        # CLI flag (step 2c) should win over LLM registry (step 2b)
        assert result["llm"]["temperature"] == 0.9

    def test_config_override_overrides_temperature_flag(self) -> None:
        """--config-override llm.temperature=X wins over --temperature (S9-10)."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            temperature=0.5,
            config_overrides=["llm.temperature=1.0"],
        )
        # Config override (step 5) should win over CLI flag (step 2c)
        assert result["llm"]["temperature"] == 1.0

    # ── S9-11: --parallel CLI flag ─────────────────────────────────────────

    def test_run_parallel_flag(self) -> None:
        """build_config(..., parallel=4) sets evaluator.parallel_evaluations (S9-11)."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            parallel=4,
        )
        assert result["evaluator"]["parallel_evaluations"] == 4

    def test_run_parallel_none_leaves_existing(self, tmp_path: Path) -> None:
        """parallel=None leaves existing parallel_evaluations unchanged (S9-11)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("evaluator:\n  parallel_evaluations: 8\n")

        llm = _make_llm()
        result = build_config(
            problem_config=config_file,
            llm=llm,
            parallel=None,
        )
        assert result["evaluator"]["parallel_evaluations"] == 8

    def test_config_override_overrides_parallel_flag(self) -> None:
        """--config-override evaluator.parallel_evaluations=X wins over --parallel."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            parallel=4,
            config_overrides=["evaluator.parallel_evaluations=8"],
        )
        # Config override (step 5) should win over CLI flag (step 2c)
        assert result["evaluator"]["parallel_evaluations"] == 8

    # ── S10-09: --rewrite-mode flag ───────────────────────────────────────

    def test_build_config_rewrite_mode(self) -> None:
        """rewrite_mode=True sets diff_based_evolution and max_code_length."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            rewrite_mode=True,
        )
        assert result["diff_based_evolution"] is False
        assert result["max_code_length"] == 50000

    def test_build_config_rewrite_mode_override_wins(self) -> None:
        """Explicit --config-override max_code_length wins over --rewrite-mode (S10-09)."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            rewrite_mode=True,
            config_overrides=["max_code_length=30000"],
        )
        # Config override (step 5) should win over rewrite_mode (step 4b)
        assert result["max_code_length"] == 30000
        # diff_based_evolution is still set by rewrite_mode (no override for it)
        assert result["diff_based_evolution"] is False

    def test_build_config_rewrite_mode_false_leaves_config_unchanged(self) -> None:
        """build_config(rewrite_mode=False) does not inject rewrite settings."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            rewrite_mode=False,
        )
        assert "diff_based_evolution" not in result
        assert "max_code_length" not in result

    def test_build_config_rewrite_mode_default_is_false(self) -> None:
        """build_config() default rewrite_mode=False does not inject rewrite settings."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
        )
        assert "diff_based_evolution" not in result
        assert "max_code_length" not in result

    def test_build_config_rewrite_mode_with_existing_llm_section(self, tmp_path: Path) -> None:
        """rewrite_mode merges into existing llm section without clobbering (S10-09)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("llm:\n  temperature: 0.8\n")

        llm = _make_llm()
        result = build_config(
            problem_config=config_file,
            llm=llm,
            rewrite_mode=True,
        )
        assert result["max_code_length"] == 50000
        # Existing LLM config should be preserved
        assert "primary_model" in result["llm"]

    def test_build_config_rewrite_mode_diff_override_wins(self) -> None:
        """--config-override diff_based_evolution=true wins over --rewrite-mode (S10-09)."""
        llm = _make_llm()
        result = build_config(
            problem_config=None,
            llm=llm,
            rewrite_mode=True,
            config_overrides=["diff_based_evolution=true"],
        )
        # Config override (step 5) wins over rewrite_mode (step 4b)
        assert result["diff_based_evolution"] is True


# ── resolve_api_keys tests ────────────────────────────────────────────────────


class TestResolveApiKeys:
    """Tests for resolve_api_keys()."""

    def test_resolves_env_var_to_api_key(self) -> None:
        """api_key_env is resolved to api_key and removed from config."""
        config: dict[str, Any] = {"llm": {"api_key_env": "MY_KEY", "primary_model": "m"}}
        with patch.dict(os.environ, {"MY_KEY": "secret123"}):
            result = resolve_api_keys(config)

        assert result["llm"]["api_key"] == "secret123"
        assert "api_key_env" not in result["llm"]
        # Other keys preserved
        assert result["llm"]["primary_model"] == "m"

    def test_api_key_missing_fatal(self) -> None:
        """ValidationError raised when env var is not set (S8-02)."""
        config: dict[str, Any] = {"llm": {"api_key_env": "MISSING_KEY"}}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_KEY", None)
            with pytest.raises(ValidationError, match="MISSING_KEY"):
                resolve_api_keys(config)

    def test_api_key_empty_fatal(self) -> None:
        """ValidationError raised when env var is set but empty (S8-02)."""
        config: dict[str, Any] = {"llm": {"api_key_env": "EMPTY_KEY"}}
        with (
            patch.dict(os.environ, {"EMPTY_KEY": ""}),
            pytest.raises(ValidationError, match="EMPTY_KEY"),
        ):
            resolve_api_keys(config)

    def test_api_key_missing_error_message_includes_env_name(self) -> None:
        """Error message includes the env var name for user clarity (S8-02)."""
        config: dict[str, Any] = {"llm": {"api_key_env": "GEMINI_API_KEY"}}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            with pytest.raises(
                ValidationError,
                match=r"API key environment variable 'GEMINI_API_KEY' is not set",
            ):
                resolve_api_keys(config)

    def test_no_llm_section(self) -> None:
        """Config without llm section is returned unchanged."""
        config: dict[str, Any] = {"max_iterations": 10}
        result = resolve_api_keys(config)
        assert result == {"max_iterations": 10}

    def test_llm_without_api_key_env(self) -> None:
        """Config with llm section but no api_key_env is returned unchanged."""
        config: dict[str, Any] = {"llm": {"api_key": "ollama"}}
        result = resolve_api_keys(config)
        assert result["llm"]["api_key"] == "ollama"

    def test_mutates_in_place(self) -> None:
        """resolve_api_keys mutates the config dict in place."""
        config: dict[str, Any] = {"llm": {"api_key_env": "MY_KEY"}}
        with patch.dict(os.environ, {"MY_KEY": "secret"}):
            result = resolve_api_keys(config)
        assert result is config


# ── revolver_env tests ────────────────────────────────────────────────────────


class TestRevolverEnv:
    """Tests for the revolver_env() context manager."""

    def test_sets_and_cleans_env_vars(self) -> None:
        """Environment variables are set inside and removed after."""
        key = "REVOLVER_TEST_VAR_42"
        assert key not in os.environ

        with revolver_env({key: "/tmp/test"}):
            assert os.environ[key] == "/tmp/test"

        assert key not in os.environ

    def test_restores_previous_value(self) -> None:
        """Previous value is restored after the context manager exits."""
        key = "REVOLVER_TEST_RESTORE"
        os.environ[key] = "original"
        try:
            with revolver_env({key: "temporary"}):
                assert os.environ[key] == "temporary"
            assert os.environ[key] == "original"
        finally:
            os.environ.pop(key, None)

    def test_restores_on_exception(self) -> None:
        """Previous value is restored even if an exception occurs."""
        key = "REVOLVER_TEST_EXCEPT"
        assert key not in os.environ

        with pytest.raises(ValueError, match="intentional"), revolver_env({key: "value"}):
            assert os.environ[key] == "value"
            raise ValueError("intentional")

        assert key not in os.environ

    def test_multiple_vars(self) -> None:
        """Multiple env vars are set and cleaned up."""
        keys = {
            "REVOLVER_DATASET_DIR": "/data",
            "REVOLVER_INSTANCE_LOG": "/log.db",
        }
        for k in keys:
            assert k not in os.environ

        with revolver_env(keys):
            for k, v in keys.items():
                assert os.environ[k] == v

        for k in keys:
            assert k not in os.environ


# ── _extract_best_score tests ────────────────────────────────────────────────


class TestExtractBestScore:
    """Tests for _extract_best_score() helper.

    These tests don't require OpenEvolve to be installed — they use local
    fake objects to exercise the extraction logic.
    """

    def test_best_score_from_program_object(self) -> None:
        """Extract score from a Program-like object with .metrics dict."""

        class FakeProgram:
            def __init__(self) -> None:
                self.metrics: dict[str, float] = {"combined_score": 1.065}

        result = _extract_best_score(FakeProgram())
        assert result == 1.065

    def test_best_score_from_number(self) -> None:
        """Extract score from a raw numeric return value."""
        assert _extract_best_score(42) == 42.0
        assert _extract_best_score(3.14) == 3.14

    def test_best_score_none_when_not_extractable(self) -> None:
        """Return None when best is neither a number nor a Program."""
        assert _extract_best_score("some_string") is None
        assert _extract_best_score(None) is None

    def test_best_score_none_when_metrics_missing_key(self) -> None:
        """Return None when metrics dict exists but lacks combined_score."""

        class FakeProgram:
            def __init__(self) -> None:
                self.metrics: dict[str, float] = {"other_metric": 0.5}

        assert _extract_best_score(FakeProgram()) is None


# ── _parse_value tests ─────────────────────────────────────────────────────


class TestParseValue:
    """Tests for _parse_value() helper (FB-05: null/none support)."""

    def test_parse_value_null(self) -> None:
        """_parse_value('null') returns None."""
        assert _parse_value("null") is None

    def test_parse_value_none(self) -> None:
        """_parse_value('None') returns None."""
        assert _parse_value("None") is None

    def test_parse_value_none_upper(self) -> None:
        """_parse_value('NULL') returns None."""
        assert _parse_value("NULL") is None

    def test_parse_value_existing_types_unaffected(self) -> None:
        """Existing int, float, bool, and string parsing is unaffected."""
        # Integers
        assert _parse_value("42") == 42
        assert _parse_value("-1") == -1
        # Floats
        assert _parse_value("3.14") == pytest.approx(3.14)
        # Booleans
        assert _parse_value("true") is True
        assert _parse_value("false") is False
        assert _parse_value("yes") is True
        assert _parse_value("no") is False
        assert _parse_value("TRUE") is True
        assert _parse_value("FALSE") is False
        # Strings
        assert _parse_value("hello") == "hello"
        assert _parse_value("some value") == "some value"

    # ── JSON array/object support (S9-12) ─────────────────────────────────

    def test_config_override_json_array(self) -> None:
        """_parse_value('[1,2,3]') returns a Python list."""
        result = _parse_value("[1,2,3]")
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_config_override_json_array_strings(self) -> None:
        """_parse_value with JSON array of strings."""
        result = _parse_value('["a","b","c"]')
        assert result == ["a", "b", "c"]

    def test_config_override_json_object(self) -> None:
        """_parse_value('{"a":1}') returns a Python dict."""
        result = _parse_value('{"a":1}')
        assert result == {"a": 1}
        assert isinstance(result, dict)

    def test_config_override_json_nested_object(self) -> None:
        """_parse_value with nested JSON object."""
        result = _parse_value('{"key":"val","nested":{"x":1}}')
        assert result == {"key": "val", "nested": {"x": 1}}

    def test_config_override_json_malformed_array(self) -> None:
        """Malformed JSON array falls back to string (no crash)."""
        result = _parse_value("[1,2,")
        assert result == "[1,2,"
        assert isinstance(result, str)

    def test_config_override_json_malformed_object(self) -> None:
        """Malformed JSON object falls back to string (no crash)."""
        result = _parse_value("{bad json}")
        assert result == "{bad json}"
        assert isinstance(result, str)

    def test_config_override_json_empty_array(self) -> None:
        """Empty JSON array parses correctly."""
        result = _parse_value("[]")
        assert result == []

    def test_config_override_json_empty_object(self) -> None:
        """Empty JSON object parses correctly."""
        result = _parse_value("{}")
        assert result == {}
