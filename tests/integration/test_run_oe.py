"""L2-OE integration tests -- real OpenEvolve, no LLM.

These tests validate the contract between Revolver and OpenEvolve
by exercising real OpenEvolve classes (Config, Controller) with
test fixtures. No LLM server or GPU is required.

Skipped automatically when openevolve is not installed.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("openevolve.config", reason="openevolve not installed")
pytest.importorskip("openevolve.controller", reason="openevolve not installed")

from openevolve.config import Config as OEConfig
from openevolve.controller import OpenEvolve as OEController

from revolver.infra.openevolve import OpenEvolveRunner, build_config
from revolver.models.llm import LLMEntry

# Path to test fixtures
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _make_llm_entry(*, source: str = "local") -> LLMEntry:
    """Create a minimal LLMEntry for testing.

    Args:
        source: ``"local"`` for Ollama or ``"remote"`` for API-based.
    """
    if source == "local":
        return LLMEntry(
            name="test-llm",
            source="local",
            model="test-model",
            base_url="http://localhost:11434/v1",
            api_key_env=None,
            registered_at=datetime.now(UTC),
        )
    return LLMEntry(
        name="test-llm-remote",
        source="remote",
        model="claude-sonnet-4-20250514",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        registered_at=datetime.now(UTC),
    )


@pytest.mark.integration
@pytest.mark.openevolve
class TestBuildConfigRoundtrip:
    """Verify build_config() output is accepted by Config.from_dict()."""

    def test_build_config_roundtrip_to_oe_config(self, tmp_path: Path) -> None:
        """Config dict fields map correctly to OpenEvolve Config attributes."""
        # Write a minimal config.yaml
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("max_iterations: 50\n")

        llm = _make_llm_entry()
        config_dict = build_config(
            problem_config=config_yaml,
            llm=llm,
            iterations=5,
            output_dir=tmp_path / "output",
            problem_description="Test problem for L2-OE",
        )

        # Round-trip through Config.from_dict() -- must not crash
        config_obj = OEConfig.from_dict(config_dict)

        # Verify field mapping
        assert config_obj.llm.api_base == "http://localhost:11434/v1"
        assert config_obj.llm.primary_model == "test-model"
        assert config_obj.max_iterations == 5  # override wins over config.yaml's 50
        assert "Test problem" in config_obj.prompt.system_message

        # Verify log_dir access doesn't crash (the v0.4.0 regression)
        _ = config_obj.log_dir

    def test_build_config_strips_revolver_keys(self, tmp_path: Path) -> None:
        """Revolver-specific keys (evaluator, initial_program) are stripped.

        Regression test for v0.4.2 bug: config.yaml with evaluator/initial_program
        strings caused Config.from_dict() to crash because 'evaluator' clashes
        with Config.evaluator (type EvaluatorConfig).
        """
        # Write a realistic config.yaml matching the TSP template
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "initial_program: initial_program.py\n"
            "evaluator: evaluator.py\n"
            "population_size: 20\n"
            "num_islands: 2\n"
            "num_generations: 50\n"
        )

        llm = _make_llm_entry()
        config_dict = build_config(
            problem_config=config_yaml,
            llm=llm,
            output_dir=tmp_path / "output",
        )

        # Revolver-specific string values must be stripped from the dict
        # (evaluator is now a dict with cascade_evaluation, not the original string)
        assert config_dict.get("evaluator") != "evaluator.py"
        assert isinstance(config_dict.get("evaluator"), dict)
        assert "initial_program" not in config_dict

        # num_generations must be mapped to max_iterations
        assert "num_generations" not in config_dict
        assert config_dict["max_iterations"] == 50

        # Round-trip through Config.from_dict() -- the v0.4.2 crash
        config_obj = OEConfig.from_dict(config_dict)
        assert config_obj.max_iterations == 50

    def test_build_config_local_llm_api_key(self, tmp_path: Path) -> None:
        """Local LLM without api_key_env gets api_key='ollama' injected."""
        llm = _make_llm_entry(source="local")
        config_dict = build_config(
            problem_config=None,
            llm=llm,
            output_dir=tmp_path / "output",
        )

        assert config_dict["llm"]["api_key"] == "ollama"

        # Round-trip through Config.from_dict()
        config_obj = OEConfig.from_dict(config_dict)
        assert config_obj.llm.api_key == "ollama"

    def test_build_config_remote_llm_no_dummy_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Remote LLM with api_key_env does not get the 'ollama' placeholder."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-key-for-test")
        llm = _make_llm_entry(source="remote")
        config_dict = build_config(
            problem_config=None,
            llm=llm,
            output_dir=tmp_path / "output",
        )

        assert config_dict["llm"]["api_key"] == "sk-ant-real-key-for-test"
        assert config_dict["llm"]["api_key"] != "ollama"

    def test_build_config_cascade_evaluation_default(self, tmp_path: Path) -> None:
        """cascade_evaluation is forced to False when not set by user."""
        llm = _make_llm_entry()
        config_dict = build_config(
            problem_config=None,
            llm=llm,
            output_dir=tmp_path / "output",
        )

        assert config_dict["evaluator"]["cascade_evaluation"] is False

        # Round-trip through Config.from_dict()
        config_obj = OEConfig.from_dict(config_dict)
        assert config_obj.evaluator.cascade_evaluation is False

    def test_build_config_cascade_evaluation_user_override(self, tmp_path: Path) -> None:
        """User-set cascade_evaluation: true is preserved."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("evaluator:\n  cascade_evaluation: true\n")

        llm = _make_llm_entry()
        config_dict = build_config(
            problem_config=config_yaml,
            llm=llm,
            output_dir=tmp_path / "output",
        )

        assert config_dict["evaluator"]["cascade_evaluation"] is True

    def test_build_config_num_generations_override(self, tmp_path: Path) -> None:
        """--iterations override wins over num_generations from config.yaml."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("num_generations: 50\n")

        llm = _make_llm_entry()
        config_dict = build_config(
            problem_config=config_yaml,
            llm=llm,
            iterations=3,
        )

        # --iterations sets max_iterations, which takes precedence
        assert config_dict["max_iterations"] == 3
        assert "num_generations" not in config_dict

        # Round-trip through Config.from_dict()
        config_obj = OEConfig.from_dict(config_dict)
        assert config_obj.max_iterations == 3


@pytest.mark.integration
@pytest.mark.openevolve
class TestControllerInstantiation:
    """Verify real OpenEvolve controller instantiation."""

    def test_oe_controller_instantiation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real OpenEvolve constructor accepts our fixtures without crash."""
        # OpenEvolve's LLM client requires an API key even though we never call the LLM
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-key-for-l2oe")

        # Copy fixtures to tmp_path
        program = tmp_path / "initial_program.py"
        evaluator = tmp_path / "evaluator.py"
        output_dir = tmp_path / "oe-output"
        output_dir.mkdir()

        shutil.copy(FIXTURES / "initial_program_simple.py", program)
        shutil.copy(FIXTURES / "evaluator_simple.py", evaluator)

        # Config with a model so the LLM ensemble is created
        config = OEConfig.from_dict(
            {
                "max_iterations": 1,
                "llm": {"primary_model": "test-model", "api_base": "http://localhost:11434/v1"},
            }
        )

        # Instantiate -- must not crash
        controller = OEController(
            str(program),
            str(evaluator),
            config,
            str(output_dir),
        )

        assert controller.config is not None
        assert isinstance(controller.config, OEConfig)


@pytest.mark.integration
@pytest.mark.openevolve
class TestOpenEvolveRunnerInitController:
    """Verify OpenEvolveRunner._init_controller() with real OpenEvolve."""

    def test_openevolve_runner_init_controller(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exact code path that crashed in v0.4.0 now works."""
        # OpenEvolve's LLM client requires an API key even though we never call the LLM
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy-key-for-l2oe")

        program = tmp_path / "initial_program.py"
        evaluator = tmp_path / "evaluator.py"
        output_dir = tmp_path / "oe-output"
        output_dir.mkdir()

        shutil.copy(FIXTURES / "initial_program_simple.py", program)
        shutil.copy(FIXTURES / "evaluator_simple.py", evaluator)

        llm = _make_llm_entry()
        config_dict = build_config(
            problem_config=None,
            llm=llm,
            iterations=1,
            output_dir=output_dir,
        )

        runner = OpenEvolveRunner(
            initial_program=program,
            evaluator=evaluator,
            config=config_dict,
            output_dir=output_dir,
        )

        # This is the exact call that crashed in v0.4.0
        runner._init_controller()

        assert runner._controller is not None
        assert runner._controller.config.llm.api_base == "http://localhost:11434/v1"
