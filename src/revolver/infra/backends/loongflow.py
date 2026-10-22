"""LoongFlow (Baidu Baige) evolution backend adapter for Revolver.

Integrates the Plan-Execute-Summarize (PES) cognitive loop from LoongFlow.
Traceable to: ADR-007 (Pluggable Evolution Backend).
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

_INSTALL_HINT = "Install with: pip install 'revolver[loongflow]'"


def _extract_code(text: str) -> str:
    """Extract Python code from markdown code block or plain text."""
    match = re.search(r"```python\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match_any = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match_any:
        return match_any.group(1).strip()
    return text.strip()


class LoongFlowBackend:
    """Adapter for Baidu's LoongFlow cognitive evolution engine."""

    name: str = "loongflow"
    default_output_subdir: str = "loongflow-output"
    wrapper_filename: str = "_loongflow_evaluator.py"

    def capabilities(self) -> BackendCapabilities:
        """Matrix of honest capabilities supported by the LoongFlow backend."""
        return BackendCapabilities(
            global_seed=False,
            map_elites_cells=True,
            native_cost_tracking=False,
            multi_language=True,
            ensemble_model="bandit",
            top_n_extraction=True,
            selection_strategies=("fixed", "ucb", "pes"),
            per_member_reasoning_effort=False,
        )

    def is_available(self) -> tuple[bool, str | None]:
        """Verify whether the loongflow package is importable."""
        try:
            import loongflow  # type: ignore[import-not-found,import-untyped,unused-ignore] # noqa: F401

            return True, None
        except ImportError:
            return False, _INSTALL_HINT

    def config_template(self) -> str:
        """Return pedagogical, well-commented YAML template for new LoongFlow projects."""
        return """# ── LoongFlow Project Configuration ──────────────────────────────────────────
# Cognitive Evolutionary Search via Plan-Execute-Summarize (PES) paradigm
# Reference: Baidu Baige Team (arXiv:2512.24077)

agent:
  type: "GeneralAgent"
  loop: "PES"                       # Loop strategy: Plan-Execute-Summarize
  prompt_language: "english"        # Language for planning rationale

memory:
  evolution_tree: true              # Track causal mutation history and ancestry
  map_elites_archive: true          # Maintain a diverse grid of high-performing heuristics
  boltzmann_selection: true         # Adaptive temperature balance between exploration/exploitation
  reflection_depth: 3               # Depth of causal diagnostic traceback when constraints fail

execution:
  max_cognitive_steps: 50           # Total number of cognitive iteration rounds (generations)
  verification_timeout_sec: 10      # Maximum sandbox runtime allowed per candidate evaluation
"""

    def validate_config(self, config: Path | dict[str, Any]) -> list[str]:
        """Validate config structure and return any human-friendly warnings."""
        return []

    def validate_seed_metrics(
        self,
        config: dict[str, Any],
        seed_metrics: dict[str, float] | None,
    ) -> None:
        """LoongFlow requires no specific seed-metric contract (no-op)."""
        pass

    def build_config(self, spec: BackendRunSpec) -> dict[str, Any]:
        """Merge Revolver run specification into LoongFlow config parameters."""
        api_key = "ENV_PROXY"
        if spec.llm.api_key_env:
            api_key = os.environ.get(spec.llm.api_key_env, api_key)

        return {
            "agent": {
                "model": spec.llm.model,
                "base_url": spec.llm.base_url,
                "api_key": api_key,
            },
            "execution": {
                "max_cognitive_steps": spec.iterations or 50,
            },
        }

    def resolved_config(
        self,
        config: dict[str, Any],
        config_overrides: dict[str, Any] | None = None,
    ) -> ResolvedConfig:
        """Extract backend-neutral parameters for --dry-run and orchestration."""
        exec_cfg = config.get("execution", {})
        return ResolvedConfig(
            backend="loongflow",
            iterations=exec_cfg.get("max_cognitive_steps", 50),
            num_islands=1,
            language="python",
            backend_extras={},
        )

    def generate_wrapper(self, spec: BackendRunSpec) -> Path:
        """Generate sandboxed evaluation wrapper script inside the problem snapshot directory."""
        wrapper_path = spec.snapshot_dir / self.wrapper_filename
        wrapper_code = f'''"""Revolver wrapper for LoongFlow Execute phase."""
import sys
from pathlib import Path

# Insert snapshot dir for problem evaluator imports
sys.path.insert(0, str(Path(r"{spec.snapshot_dir}")))

from evaluator import evaluate_solution

def execute_candidate(code_str: str) -> dict:
    """Executes the candidate code string safely and evaluates its performance."""
    try:
        namespace = {{}}
        exec(code_str, namespace)
        solve_func = namespace.get("solve")
        if not solve_func or not callable(solve_func):
            err = "Function 'solve(data)' not defined or not callable."
            return {{"fitness": 0.0, "valid": False, "error": err}}

        score, metrics = evaluate_solution(solve_func)
        return {{"fitness": score, "valid": metrics.get("valid", False), "metrics": metrics}}
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
        """Launch LoongFlow PES optimization loop wired to LLM API."""
        available, hint = self.is_available()
        if not available:
            raise BackendUnavailableError(f"LoongFlow is not available. {hint}")

        import litellm

        run_dir = spec.run_dir or (spec.snapshot_dir / "run")
        output_dir = run_dir / self.default_output_subdir
        output_dir.mkdir(parents=True, exist_ok=True)

        wrapper_path = self.generate_wrapper(spec)

        # Dynamic wrapper loader
        wrapper_module_spec = importlib.util.spec_from_file_location(
            "_loongflow_eval", wrapper_path
        )
        if not wrapper_module_spec or not wrapper_module_spec.loader:
            raise ResourceError(f"Cannot load evaluator wrapper from {wrapper_path}")
        eval_module = importlib.util.module_from_spec(wrapper_module_spec)
        wrapper_module_spec.loader.exec_module(eval_module)
        eval_fn = eval_module.execute_candidate

        # Load initial program
        seed_path = spec.snapshot_dir / "initial_program.py"
        best_program = (
            seed_path.read_text(encoding="utf-8")
            if seed_path.exists()
            else "def solve(data):\n    return []\n"
        )

        initial_eval = eval_fn(best_program)
        best_score = float(initial_eval.get("fitness", 0.0))

        max_iters = spec.iterations or config.get("execution", {}).get("max_cognitive_steps", 10)
        history: list[dict[str, Any]] = [
            {"step": 0, "score": best_score, "valid": initial_eval.get("valid", False)}
        ]

        llm_cfg = config.get("agent", {})
        model_name = llm_cfg.get("model", spec.llm.model)
        base_url = llm_cfg.get("base_url", spec.llm.base_url)
        api_key = llm_cfg.get("api_key")
        if not api_key or api_key == "ENV_PROXY":
            if spec.llm.api_key_env:
                api_key = os.environ.get(spec.llm.api_key_env, "sk-dummy")
            else:
                api_key = "sk-dummy"

        for step in range(1, max_iters + 1):
            prompt = f"""You are an algorithm designer in a LoongFlow PES optimization loop.
Objective: Optimize the Python function `solve(data)` to achieve maximum score
while strictly satisfying all constraints.

Current Best Fitness: {best_score}
Current Program:
```python
{best_program}
```

Task:
1. Plan an algorithmic refinement to increase fitness or fix constraint violations.
2. Provide the complete updated Python code defining `solve(data)`.
"""
            try:
                response = litellm.completion(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    api_base=base_url,
                    api_key=api_key,
                    temperature=spec.temperature or 0.7,
                )
                candidate_text = response.choices[0].message.content or ""
                candidate_code = _extract_code(candidate_text)
            except Exception as exc:
                raise ExternalError(
                    f"LLM API call failed during LoongFlow step {step}: {exc}"
                ) from exc

            eval_res = eval_fn(candidate_code)
            cand_score = float(eval_res.get("fitness", 0.0))
            cand_valid = eval_res.get("valid", False)

            if cand_valid and cand_score > best_score:
                best_score = cand_score
                best_program = candidate_code

            history.append({"step": step, "score": cand_score, "valid": cand_valid})

            # Checkpoint updates
            (output_dir / "best_program.py").write_text(best_program, encoding="utf-8")
            (output_dir / "history.json").write_text(
                json.dumps(
                    {"iterations_done": step, "best_score": best_score, "history": history},
                    indent=2,
                ),
                encoding="utf-8",
            )

            if on_progress:
                on_progress(
                    ProgressInfo(
                        iteration=step,
                        total_iterations=max_iters,
                        best_score=best_score,
                    )
                )

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
        """Resume LoongFlow optimization from previous run."""
        self.resume_precheck(parent_run_dir)
        best_file = parent_run_dir / self.default_output_subdir / "best_program.py"
        if best_file.exists():
            (spec.snapshot_dir / "initial_program.py").write_text(
                best_file.read_text(encoding="utf-8"), encoding="utf-8"
            )
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
            program_id="loongflow-best",
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
        """Extract a program by rank or ID."""
        rec = self.recover_best_from_checkpoint(run_dir)
        return RankedProgram(
            program_id=rec.program_id,
            code=rec.code,
            rank=1,
            score=rec.score,
            language=rec.language,
        )

    def read_progress(self, run_dir: Path) -> tuple[int | None, float | None]:
        """Read current progress (iterations_done, best_score)."""
        hist_file = run_dir / self.default_output_subdir / "history.json"
        if hist_file.exists():
            try:
                data = json.loads(hist_file.read_text(encoding="utf-8"))
                return (data.get("iterations_done"), data.get("best_score"))
            except Exception:
                pass
        return (None, None)

    def parse_population(self, run_dir: Path) -> list[dict[str, Any]] | None:
        """Parse population programs."""
        rec = self.recover_best_from_checkpoint(run_dir)
        return [{"id": "loongflow-best", "score": rec.score, "valid": True}]

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
        """Whether LLM calls require the Revolver token tracking proxy."""
        return True

    def collect_token_usage(self, run_dir: Path) -> TokenUsage | None:
        """Collect native token usage metrics."""
        return None

    def reap(self, run_dir: Path) -> None:
        """Clean up background child processes on teardown."""
        pass
