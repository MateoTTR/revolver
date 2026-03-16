"""Tests for the OpenEvolve wrapper (S4-01).

All tests mock the OpenEvolve controller to avoid a hard dependency.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from revolver.core.exceptions import ExternalError, ValidationError
from revolver.infra.openevolve import (
    SYSTEM_PROMPT_TEMPLATE,
    OpenEvolveRunner,
    RunOutput,
    build_config,
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
            config={"iterations": 10},
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
                    "iterations": 10,
                    "population_size": 5,
                    "llm": {"model": "base-model", "temperature": 0.8},
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

    def test_api_key_from_env(self, tmp_path: Path) -> None:
        """API key is read from the env var named in api_key_env."""
        llm = _make_llm(api_key_env="MY_API_KEY")
        with patch.dict(os.environ, {"MY_API_KEY": "sk-test-12345"}):
            result = build_config(problem_config=None, llm=llm)

        assert result["llm"]["api_key"] == "sk-test-12345"

    def test_api_key_env_not_set(self, tmp_path: Path) -> None:
        """Missing env var means no api_key in config."""
        llm = _make_llm(api_key_env="NONEXISTENT_KEY")
        # Ensure the env var is not set
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NONEXISTENT_KEY", None)
            result = build_config(problem_config=None, llm=llm)

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
