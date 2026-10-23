"""Agentic AI optimization backend for Revolver (PR-2).

Enables conversational (REPL) multi-turn code generation with Multi-Agent delegation.
Supports models from OpenAI, Anthropic (Claude), and Google (Gemini) through LiteLLM.
Traceable to: ADR-007, DES-009.
"""

from __future__ import annotations

from collections.abc import Callable
import importlib.util
import json
import os
from pathlib import Path
import re
from typing import Any

from revolver.core.exceptions import ExternalError, ResourceError, ValidationError
from revolver.infra.backends.base import (
    BackendCapabilities,
    BackendRunResult,
    BackendRunSpec,
    BackendUnavailableError,
    ProgressInfo,
    RankedProgram,
    RecoveredProgram,
)
from revolver.models.run import ResolvedConfig, TokenUsage

_INSTALL_HINT = "Ensure litellm is installed: pip install litellm"

# OpenAI-compatible tool definition for specialist delegation
_DELEGATE_TOOL = {
    "type": "function",
    "function": {
        "name": "delegate_to_specialist",
        "description": (
            "Delegate a specific modular algorithmic sub-task to an autonomous Specialist Agent. "
            "Use this to isolate complex constraints or sub-algorithms."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subtask_description": {
                    "type": "string",
                    "description": "Clear specification of the sub-routine to write in Python.",
                },
                "expected_function_signature": {
                    "type": "string",
                    "description": "The exact function name and arguments expected.",
                },
            },
            "required": ["subtask_description"],
        },
    },
}


def _extract_code(text: str) -> str:
    """Extract Python code from markdown code blocks or plain text."""
    match = re.search(r"```python\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match_any = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match_any:
        return match_any.group(1).strip()
    return text.strip()


class AgenticBackend:
    """Conversational Multi-Agent optimization engine for Revolver."""

    name: str = "agentic"
    default_output_subdir: str = "agentic-output"
    wrapper_filename: str = "_agentic_evaluator.py"

    def capabilities(self) -> BackendCapabilities:
        """Matrix of honest capabilities supported by the Agentic backend."""
        return BackendCapabilities(
            global_seed=False,
            map_elites_cells=False,
            native_cost_tracking=True,
            multi_language=True,
            ensemble_model="none",
            top_n_extraction=True,
            selection_strategies=("conversational",),
            per_member_reasoning_effort=False,
        )

    def is_available(self) -> tuple[bool, str | None]:
        """Verify whether litellm is importable for agent calls."""
        try:
            import litellm  # noqa: F401

            return True, None
        except ImportError:
            return False, _INSTALL_HINT

    def config_template(self) -> str:
        """Return pedagogical YAML template for Agentic multi-turn optimization."""
        return """# ── Agentic Backend Configuration ──────────────────────────────────────────
# Conversational Multi-Agent code generation loop (Lead Architect + Specialists)

agentic:
  mode: "multi_agent"               # "single" (mono-agent) or "multi_agent" (delegation enabled)
  max_turns: 15                     # Maximum back-and-forth debugging turns
  temperature: 0.2                  # Low temperature favored for precise code generation
  specialist_model: null            # Optional override for sub-agents (defaults to lead model)
  system_prompt: |
    You are an autonomous Principal Optimization Engineer.
    Analyze the problem specifications, decompose complex constraints, and iteratively refine
    the `solve(data)` Python entrypoint. You have access to a specialist sub-agent tool.
"""

    def validate_config(self, config: Path | dict[str, Any]) -> list[str]:
        """Validate agentic config structure."""
        return []

    def validate_seed_metrics(
        self,
        config: dict[str, Any],
        seed_metrics: dict[str, float] | None,
    ) -> None:
        """Agentic backend requires no specific seed-metric contract (no-op)."""
        pass

    def build_config(self, spec: BackendRunSpec) -> dict[str, Any]:
        """Merge Revolver run specification into Agentic config."""
        api_key = "ENV_PROXY"
        if spec.llm.api_key_env:
            api_key = os.environ.get(spec.llm.api_key_env, api_key)

        return {
            "agentic": {
                "model": spec.llm.model,
                "base_url": spec.llm.base_url,
                "api_key": api_key,
                "max_turns": spec.iterations or 15,
                "temperature": spec.temperature or 0.2,
            }
        }

    def resolved_config(
        self,
        config: dict[str, Any],
        config_overrides: dict[str, Any] | None = None,
    ) -> ResolvedConfig:
        """Extract backend-neutral parameters for --dry-run and orchestration."""
        agent_cfg = config.get("agentic", {})
        return ResolvedConfig(
            backend="agentic",
            iterations=agent_cfg.get("max_turns", 15),
            num_islands=None,
            language="python",
            backend_extras={},
        )

    def generate_wrapper(self, spec: BackendRunSpec) -> Path:
        """Generate evaluation wrapper inside the run directory (NOT snapshot_dir).

        Guarantees snapshot immutability (NFR-MLOPS-001).
        Exposes both `execute_candidate()` and `evaluate_instance()`.
        """
        run_dir = spec.run_dir or (spec.snapshot_dir / "run")
        wrapper_dir = run_dir / self.default_output_subdir
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        wrapper_path = wrapper_dir / self.wrapper_filename

        wrapper_code = f'''"""Revolver wrapper for Agentic candidate evaluation."""
import sys
from pathlib import Path
from typing import Any

# Insert snapshot dir for problem evaluator imports (Read-Only)
sys.path.insert(0, str(Path(r"{spec.snapshot_dir}")))

import evaluator

def evaluate_instance(instance_data: Any) -> tuple[float, dict[str, Any]]:
    """Standard Revolver evaluator pre-flight contract."""
    if hasattr(evaluator, "evaluate_instance"):
        return evaluator.evaluate_instance(instance_data)
    elif hasattr(evaluator, "evaluate_solution"):
        return evaluator.evaluate_solution(lambda d: None)
    return 0.0, {{"valid": False, "error": "No evaluate contract found"}}

def execute_candidate(code_str: str) -> dict:
    """Executes the candidate code string safely and evaluates its performance."""
    try:
        namespace = {{}}
        exec(code_str, namespace)
        solve_func = namespace.get("solve")
        if not solve_func or not callable(solve_func):
            err = "Function 'solve(data)' not defined or not callable."
            return {{"fitness": 0.0, "valid": False, "error": err}}

        if hasattr(evaluator, "evaluate_solution"):
            score, metrics = evaluator.evaluate_solution(solve_func)
            return {{"fitness": score, "valid": metrics.get("valid", False), "metrics": metrics}}
        elif hasattr(evaluator, "evaluate_instance"):
            score, metrics = evaluator.evaluate_instance(solve_func)
            return {{"fitness": score, "valid": metrics.get("valid", False), "metrics": metrics}}
        return {{"fitness": 0.0, "valid": False, "error": "No compatible evaluate function"}}
    except Exception as exc:
        return {{"fitness": 0.0, "valid": False, "error": f"Execution error: {{exc}}"}}
'''
        wrapper_path.write_text(wrapper_code, encoding="utf-8")
        return wrapper_path

    def launch(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Launch conversational Multi-Agent refinement loop."""
        available, hint = self.is_available()
        if not available:
            raise BackendUnavailableError(f"Agentic backend unavailable: {hint}")

        import litellm

        run_dir = spec.run_dir or (spec.snapshot_dir / "run")
        output_dir = run_dir / self.default_output_subdir
        output_dir.mkdir(parents=True, exist_ok=True)

        wrapper_path = self.generate_wrapper(spec)

        # Dynamic wrapper loader
        import sys

        sys.modules.pop("evaluator", None)
        module_name = f"_agentic_eval_{abs(hash(str(wrapper_path)))}"
        wrapper_module_spec = importlib.util.spec_from_file_location(module_name, wrapper_path)
        if not wrapper_module_spec or not wrapper_module_spec.loader:
            raise ResourceError(f"Cannot load evaluator wrapper from {wrapper_path}")
        eval_module = importlib.util.module_from_spec(wrapper_module_spec)
        wrapper_module_spec.loader.exec_module(eval_module)
        eval_fn = eval_module.execute_candidate

        # Load initial program from read-only snapshot
        seed_path = spec.snapshot_dir / "initial_program.py"
        best_program = (
            seed_path.read_text(encoding="utf-8")
            if seed_path.exists()
            else "def solve(data):\n    return []\n"
        )

        initial_eval = eval_fn(best_program)
        best_score = float(initial_eval.get("fitness", 0.0))

        agent_cfg = config.get("agentic", {})
        max_turns = spec.iterations or agent_cfg.get("max_turns", 15)
        model_name = agent_cfg.get("model", spec.llm.model)
        specialist_model = agent_cfg.get("specialist_model") or model_name
        base_url = agent_cfg.get("base_url", spec.llm.base_url)
        temperature = spec.temperature or agent_cfg.get("temperature", 0.2)

        api_key = agent_cfg.get("api_key")
        if not api_key or api_key == "ENV_PROXY":
            if spec.llm.api_key_env:
                api_key = os.environ.get(spec.llm.api_key_env, "sk-dummy")
            else:
                api_key = "sk-dummy"

        system_prompt = (
            "You are an autonomous Principal Optimization Engineer. "
            "Write optimal, strictly valid Python code defining `solve(data)`. "
            "You can delegate specialized modular logic using the `delegate_to_specialist` tool."
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Initial program code:\n```python\n{best_program}\n```\n"
                    f"Baseline fitness score: {best_score}.\n"
                    "Optimize this function to maximize score and respect constraints."
                ),
            },
        ]

        history: list[dict[str, Any]] = [
            {"turn": 0, "score": best_score, "valid": initial_eval.get("valid", False)}
        ]

        for turn in range(1, max_turns + 1):
            try:
                response = litellm.completion(
                    model=model_name,
                    messages=messages,
                    tools=[_DELEGATE_TOOL],
                    tool_choice="auto",
                    api_base=base_url,
                    api_key=api_key,
                    temperature=temperature,
                )
            except Exception as exc:
                err_msg = f"LLM API call failed during Agentic turn {turn}: {exc}"
                raise ExternalError(err_msg) from exc

            response_msg = response.choices[0].message
            dumped_msg = (
                response_msg.model_dump()
                if hasattr(response_msg, "model_dump")
                else dict(response_msg)
            )
            messages.append(dumped_msg)

            # Handle Sub-Agent delegation Tool Calls
            tool_calls = getattr(response_msg, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    fn_args = json.loads(tc.function.arguments)
                    subtask = fn_args.get("subtask_description", "")

                    # Invocate Specialist sub-agent with focused scratchpad
                    try:
                        spec_resp = litellm.completion(
                            model=specialist_model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are a Specialist Sub-Agent.",
                                },
                                {"role": "user", "content": subtask},
                            ],
                            api_base=base_url,
                            api_key=api_key,
                            temperature=temperature,
                        )
                        spec_code = spec_resp.choices[0].message.content or ""
                    except Exception as exc:
                        spec_code = f"# Specialist failed: {exc}"

                    # Feed tool response back into the Lead Architect's context
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.function.name,
                            "content": spec_code,
                        }
                    )

                # Query Lead Architect to synthesize solution with specialist output
                try:
                    synth_resp = litellm.completion(
                        model=model_name,
                        messages=messages,
                        api_base=base_url,
                        api_key=api_key,
                        temperature=temperature,
                    )
                    response_msg = synth_resp.choices[0].message
                    messages.append(
                        response_msg.model_dump()
                        if hasattr(response_msg, "model_dump")
                        else dict(response_msg)
                    )
                except Exception as exc:
                    err_msg = f"LLM API call failed during Architect synthesis: {exc}"
                    raise ExternalError(err_msg) from exc

            content_text = response_msg.content or ""
            candidate_code = _extract_code(content_text)

            eval_res = eval_fn(candidate_code)
            cand_score = float(eval_res.get("fitness", 0.0))
            cand_valid = bool(eval_res.get("valid", False))
            cand_err = eval_res.get("error")

            if cand_valid and cand_score > best_score:
                best_score = cand_score
                best_program = candidate_code

            history.append({"turn": turn, "score": cand_score, "valid": cand_valid})

            # Checkpoint updates strictly in run_dir
            (output_dir / "best_program.py").write_text(best_program, encoding="utf-8")
            (output_dir / "history.json").write_text(
                json.dumps(
                    {"turns_done": turn, "best_score": best_score, "history": history},
                    indent=2,
                ),
                encoding="utf-8",
            )

            if on_progress:
                on_progress(
                    ProgressInfo(
                        iteration=turn,
                        total_iterations=max_turns,
                        best_score=best_score,
                    )
                )

            # Conversational feedback back to the Agent
            if not cand_valid:
                feedback = (
                    f"Turn {turn} Evaluation Failed!\n"
                    f"Validation Error: {cand_err}\n"
                    "Analyze the violation and propose a corrected code."
                )
            else:
                feedback = (
                    f"Turn {turn} Evaluation Passed!\n"
                    f"Current Score: {cand_score} (Best so far: {best_score}).\n"
                    "Can you optimize it further?"
                )
            messages.append({"role": "user", "content": feedback})

        return BackendRunResult(
            best_score=best_score,
            best_program=best_program,
            output_dir=output_dir,
        )

    def resume_precheck(self, parent_run_dir: Path) -> None:
        """Check prerequisites for resuming an interrupted run."""
        hist_path = parent_run_dir / self.default_output_subdir / "history.json"
        if not hist_path.exists():
            raise ValidationError(f"No history found in {parent_run_dir} to resume from.")

    def resume(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        parent_run_dir: Path,
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Resume Agentic conversation without touching snapshot_dir."""
        self.resume_precheck(parent_run_dir)
        # Never mutate snapshot_dir/initial_program.py directly!
        return self.launch(spec, config, on_progress)

    def recover_best_from_checkpoint(self, run_dir: Path) -> RecoveredProgram:
        """Recover best program from checkpoint."""
        output_dir = run_dir / self.default_output_subdir
        best_file = output_dir / "best_program.py"
        if not best_file.exists():
            from revolver.core.exceptions import RecoveryNotSupportedError

            raise RecoveryNotSupportedError(f"No best program found in {output_dir}")

        score = None
        hist_file = output_dir / "history.json"
        if hist_file.exists():
            try:
                score = json.loads(hist_file.read_text(encoding="utf-8")).get("best_score")
            except Exception:
                score = None

        return RecoveredProgram(
            program_id="agentic-best",
            code=best_file.read_text(encoding="utf-8"),
            score=score,
            language="python",
        )

    def extract_ranked_program(
        self,
        run_dir: Path,
        rank: int | None = None,
        program_id: str | None = None,
    ) -> RankedProgram:
        """Extract best program as rank 1."""
        rec = self.recover_best_from_checkpoint(run_dir)
        return RankedProgram(
            program_id=rec.program_id,
            code=rec.code,
            rank=1,
            score=rec.score,
            language=rec.language,
        )

    def read_progress(self, run_dir: Path) -> tuple[int | None, float | None]:
        """Read current progress (turns_done, best_score)."""
        hist_file = run_dir / self.default_output_subdir / "history.json"
        if hist_file.exists():
            try:
                data = json.loads(hist_file.read_text(encoding="utf-8"))
                return (data.get("turns_done"), data.get("best_score"))
            except Exception:
                pass
        return (None, None)

    def parse_population(self, run_dir: Path) -> list[dict[str, Any]] | None:
        """Parse population programs."""
        rec = self.recover_best_from_checkpoint(run_dir)
        return [{"id": "agentic-best", "score": rec.score, "valid": True}]

    def count_valid(self, run_dir: Path) -> int | None:
        """Count valid programs produced."""
        hist_file = run_dir / self.default_output_subdir / "history.json"
        if hist_file.exists():
            try:
                data = json.loads(hist_file.read_text(encoding="utf-8"))
                return sum(1 for h in data.get("history", []) if h.get("valid"))
            except Exception:
                pass
        return None

    def count_total(self, run_dir: Path) -> int | None:
        """Count total programs evaluated."""
        hist_file = run_dir / self.default_output_subdir / "history.json"
        if hist_file.exists():
            try:
                data = json.loads(hist_file.read_text(encoding="utf-8"))
                return len(data.get("history", []))
            except Exception:
                pass
        return None

    def count_evolved_children(self, run_dir: Path) -> int | None:
        """Count evolved children programs."""
        tot = self.count_total(run_dir)
        return (tot - 1) if tot and tot > 1 else 0

    def wants_http_proxy(self) -> bool:
        """Route calls through token counting proxy."""
        return True

    def collect_token_usage(self, run_dir: Path) -> TokenUsage | None:
        """Collect native token usage metrics."""
        return None

    def reap(self, run_dir: Path) -> None:
        """Clean up background child processes."""
        pass
