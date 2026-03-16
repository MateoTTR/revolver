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

oe_config_mod = pytest.importorskip("openevolve.config", reason="openevolve not installed")
oe_controller_mod = pytest.importorskip("openevolve.controller", reason="openevolve not installed")

from openevolve.config import Config as OEConfig  # noqa: E402
from openevolve.controller import OpenEvolve as OEController  # noqa: E402

from revolver.infra.openevolve import OpenEvolveRunner, build_config  # noqa: E402
from revolver.models.llm import LLMEntry  # noqa: E402

# Path to test fixtures
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _make_llm_entry() -> LLMEntry:
    """Create a minimal LLMEntry for testing."""
    return LLMEntry(
        name="test-llm",
        source="local",
        model="test-model",
        base_url="http://localhost:11434/v1",
        api_key_env=None,
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
