"""Tests for the Agentic (Multi-Agent Tool Calling) evolution backend adapter (PR-2, DES-009)."""

from datetime import datetime
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from revolver.infra.backends import (
    AVAILABLE_BACKENDS,
    EvolutionBackend,
    get_backend,
)
from revolver.infra.backends.agentic import AgenticBackend, _extract_code
from revolver.infra.backends.base import BackendRunSpec
from revolver.models.llm import LLMEntry


def _make_llm(**kwargs: object) -> LLMEntry:
    defaults = {
        "name": "test-gemini",
        "model": "gemini/gemini-1.5-pro",
        "source": "remote",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_env": "GEMINI_API_KEY",
        "registered_at": datetime(2026, 1, 1),
    }
    defaults.update(kwargs)
    return LLMEntry(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestAgenticBackend:
    """Test suite for AgenticBackend with strict CI unit-marking."""

    def test_registered_in_available_backends(self) -> None:
        """Ensure agentic is exposed as an available backend."""
        assert "agentic" in AVAILABLE_BACKENDS
        backend = get_backend("agentic")
        assert isinstance(backend, AgenticBackend)
        assert isinstance(backend, EvolutionBackend)
        assert backend.name == "agentic"

    def test_capabilities(self) -> None:
        """Verify the declared capability matrix for Agentic."""
        backend = AgenticBackend()
        caps = backend.capabilities()
        assert caps.native_cost_tracking is True
        assert caps.ensemble_model == "none"
        assert "conversational" in caps.selection_strategies

    def test_config_template_contains_multi_agent_options(self) -> None:
        """Verify that scaffold template provides multi-agent configuration."""
        backend = AgenticBackend()
        tmpl = backend.config_template()
        assert "multi_agent" in tmpl
        assert "max_turns" in tmpl
        assert "system_prompt" in tmpl

    def test_resolved_config(self) -> None:
        """Verify standard parameters resolution for dry-run/orchestration."""
        backend = AgenticBackend()
        raw_config = {"agentic": {"max_turns": 25}}
        resolved = backend.resolved_config(raw_config)
        assert resolved.iterations == 25
        assert resolved.backend == "agentic"
        assert resolved.num_islands is None

    def test_extract_code(self) -> None:
        """Verify Python code extraction from LLM markdown response."""
        raw = "```python\ndef solve(data):\n    return 'optimized'\n```"
        assert _extract_code(raw) == "def solve(data):\n    return 'optimized'"

    def test_generate_wrapper_preserves_snapshot_immutability(self, tmp_path: Path) -> None:
        """Verify generation of wrapper inside run_dir and exposes evaluate_instance."""
        backend = AgenticBackend()
        llm = _make_llm()
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "evaluator.py").write_text(
            "def evaluate_solution(f): return 1.0, {}", encoding="utf-8"
        )

        run_dir = tmp_path / "run"
        spec = BackendRunSpec(snapshot_dir=snapshot_dir, run_dir=run_dir, llm=llm)

        wrapper_file = backend.generate_wrapper(spec)
        assert wrapper_file.exists()
        # Invariant check: wrapper must be in run_dir, NOT snapshot_dir!
        assert wrapper_file.parent == run_dir / "agentic-output"
        assert not (snapshot_dir / "_agentic_evaluator.py").exists()

        content = wrapper_file.read_text(encoding="utf-8")
        assert "evaluate_instance" in content
        assert "execute_candidate" in content

    @patch("litellm.completion")
    def test_launch_with_tool_calling_delegation(
        self, mock_completion: MagicMock, tmp_path: Path
    ) -> None:
        """Verify multi-agent flow: Lead Architect delegates a subtask via Tool Calling."""
        backend = AgenticBackend()
        llm = _make_llm()

        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir(parents=True)
        evaluator_code = """
def evaluate_solution(fn):
    return 95.0, {"valid": True, "score": 95.0}
"""
        (snapshot_dir / "evaluator.py").write_text(evaluator_code, encoding="utf-8")

        # 1. Lead Architect decides to call the specialist tool
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_abc123"
        mock_tool_call.function.name = "delegate_to_specialist"
        mock_tool_call.function.arguments = json.dumps(
            {"subtask_description": "Write a greedy target selector"}
        )

        turn1_msg = MagicMock()
        turn1_msg.content = None
        turn1_msg.tool_calls = [mock_tool_call]
        turn1_msg.model_dump.return_value = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "delegate_to_specialist",
                        "arguments": json.dumps({"subtask_description": "Greedy selector"}),
                    },
                }
            ],
        }

        # 2. Specialist Sub-Agent response
        spec_msg = MagicMock()
        spec_msg.content = "def helper(): return 42"

        # 3. Lead Architect synthesizes final code
        turn2_msg = MagicMock()
        turn2_msg.content = "```python\ndef solve(data):\n    return [42]\n```"
        turn2_msg.tool_calls = None
        turn2_msg.model_dump.return_value = {
            "role": "assistant",
            "content": "```python\ndef solve(data):\n    return [42]\n```",
        }

        mock_completion.side_effect = [
            MagicMock(choices=[MagicMock(message=turn1_msg)]),  # Lead invokes tool
            MagicMock(choices=[MagicMock(message=spec_msg)]),  # Specialist runs
            MagicMock(choices=[MagicMock(message=turn2_msg)]),  # Lead synthesizes final solution
        ]

        run_dir = tmp_path / "run"
        spec = BackendRunSpec(
            snapshot_dir=snapshot_dir,
            run_dir=run_dir,
            llm=llm,
            iterations=1,
        )

        result = backend.launch(spec, {})
        assert result.best_score == 95.0
        assert "def solve" in result.best_program
        assert mock_completion.call_count == 3


@pytest.mark.integration
def test_real_gemini_api_call() -> None:
    """Optional end-to-end integration test with Google Gemini API if GEMINI_API_KEY is set."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set in environment — skipping real API call.")

    import litellm

    response = litellm.completion(
        model="gemini/gemini-1.5-pro",
        messages=[{"role": "user", "content": "Write python function `solve(data)`: return []"}],
        api_key=api_key,
    )
    content = response.choices[0].message.content
    assert "def solve" in content
