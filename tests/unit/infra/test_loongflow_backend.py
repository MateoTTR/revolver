"""Tests for the LoongFlow evolution backend adapter (PR-1)."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from revolver.infra.backends import (
    AVAILABLE_BACKENDS,
    EvolutionBackend,
    get_backend,
)
from revolver.infra.backends.base import BackendRunSpec
from revolver.infra.backends.loongflow import LoongFlowBackend, _extract_code
from revolver.models.llm import LLMEntry


def _make_llm(**kwargs: object) -> LLMEntry:
    defaults = {
        "name": "test-llm",
        "model": "gpt-4o",
        "source": "remote",
        "base_url": "http://localhost:11434/v1",
        "registered_at": datetime(2026, 1, 1),
    }
    defaults.update(kwargs)
    return LLMEntry(**defaults)  # type: ignore[arg-type]


class TestLoongFlowBackend:
    """Test suite for LoongFlowBackend."""

    def test_registered_in_available_backends(self) -> None:
        """Ensure loongflow is exposed as an available backend."""
        assert "loongflow" in AVAILABLE_BACKENDS
        backend = get_backend("loongflow")
        assert isinstance(backend, LoongFlowBackend)
        assert isinstance(backend, EvolutionBackend)
        assert backend.name == "loongflow"

    def test_capabilities(self) -> None:
        """Verify the declared capability matrix for LoongFlow."""
        backend = LoongFlowBackend()
        caps = backend.capabilities()
        assert caps.multi_language is True
        assert caps.ensemble_model == "bandit"
        assert "pes" in caps.selection_strategies

    def test_config_template_contains_pedagogical_comments(self) -> None:
        """Verify that scaffold template provides PES configuration with clear comments."""
        backend = LoongFlowBackend()
        tmpl = backend.config_template()
        assert "Plan-Execute-Summarize" in tmpl
        assert "map_elites_archive" in tmpl
        assert "boltzmann_selection" in tmpl
        assert "reflection_depth" in tmpl

    def test_resolved_config(self) -> None:
        """Verify standard parameters resolution for dry-run/orchestration."""
        backend = LoongFlowBackend()
        raw_config = {"execution": {"max_cognitive_steps": 120}}
        resolved = backend.resolved_config(raw_config)
        assert resolved.iterations == 120
        assert resolved.backend == "loongflow"
        assert resolved.num_islands == 1

    def test_extract_code(self) -> None:
        """Verify Python code extraction from LLM response markdown."""
        raw = "Code:\n```python\ndef solve(data):\n    return [1, 2]\n```\nExplanation."
        extracted = _extract_code(raw)
        assert extracted == "def solve(data):\n    return [1, 2]"

    def test_generate_wrapper(self, tmp_path: Path) -> None:
        """Verify generation of the _loongflow_evaluator.py wrapper."""
        backend = LoongFlowBackend()
        llm = _make_llm()
        spec = BackendRunSpec(snapshot_dir=tmp_path, llm=llm)

        wrapper_file = backend.generate_wrapper(spec)
        assert wrapper_file.exists()
        assert wrapper_file.name == "_loongflow_evaluator.py"
        content = wrapper_file.read_text(encoding="utf-8")
        assert "execute_candidate" in content
        assert "solve_func" in content

    @patch("litellm.completion")
    def test_launch_with_mocked_llm(self, mock_completion: MagicMock, tmp_path: Path) -> None:
        """Verify full launch loop with mocked LiteLLM completions."""
        backend = LoongFlowBackend()
        llm = _make_llm()

        # Create dummy evaluator in project
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir(parents=True)
        evaluator_code = """
def evaluate_solution(fn):
    return 100.0, {"valid": True, "score": 100.0}
"""
        (snapshot_dir / "evaluator.py").write_text(evaluator_code, encoding="utf-8")
        (snapshot_dir / "initial_program.py").write_text(
            "def solve(d): return 0\n", encoding="utf-8"
        )

        mock_choice = MagicMock()
        mock_choice.message.content = "```python\ndef solve(d):\n    return [42]\n```"
        mock_completion.return_value = MagicMock(choices=[mock_choice])

        spec = BackendRunSpec(
            snapshot_dir=snapshot_dir,
            run_dir=tmp_path / "run",
            llm=llm,
            iterations=2,
        )

        result = backend.launch(spec, {})
        assert result.best_score == 100.0
        assert "def solve" in result.best_program
        assert mock_completion.call_count == 2

        # Check recovery and progress reading
        rec = backend.recover_best_from_checkpoint(tmp_path / "run")
        assert rec.score == 100.0
        assert "def solve" in rec.code

        prog = backend.read_progress(tmp_path / "run")
        assert prog == (2, 100.0)
