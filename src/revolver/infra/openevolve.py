"""OpenEvolve controller wrapper for Revolver integration.

Wraps the OpenEvolve controller class to provide:
- Programmatic config building with merge order
- Environment variable injection via context manager
- Problem description injection into system prompt
- Token proxy integration for usage tracking

Traceable to: DES-005 (Run Orchestration), ADR-006 (Instance Injection).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from revolver.core.exceptions import ExternalError, ValidationError
from revolver.models.llm import LLMEntry

# ── System prompt template (DES-005 §4.4) ────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """\
You are an expert programmer tasked with improving code \
to optimize a specific problem.

## Problem Description

{problem_description}

## Instructions

Analyze the provided code and suggest improvements to optimize the metrics \
returned by the evaluator. Focus on the code sections marked with EVOLVE-BLOCK."""


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class RunOutput:
    """Results collected after an OpenEvolve run completes.

    Attributes:
        best_score: Score of the best program found.
        best_program: Raw result returned by the controller.
        output_dir: Path to the OpenEvolve output directory.
    """

    best_score: float | None = None
    best_program: Any = None
    output_dir: Path | None = None


@dataclass
class ProgressInfo:
    """Progress callback data from OpenEvolve.

    Attributes:
        iteration: Current iteration number.
        total_iterations: Total iterations requested.
        best_score: Best score so far.
        elapsed_s: Elapsed time in seconds.
    """

    iteration: int = 0
    total_iterations: int = 0
    best_score: float = 0.0
    elapsed_s: float = 0.0


# ── OpenEvolve runner ─────────────────────────────────────────────────────────


class OpenEvolveRunner:
    """Wrapper around the OpenEvolve controller for Revolver integration.

    Uses conditional import to avoid hard dependency on OpenEvolve
    at module level. The ``openevolve`` package must be installed when
    ``run()`` is actually called.

    Args:
        initial_program: Path to the initial program file.
        evaluator: Path to the evaluator Python file.
        config: OpenEvolve configuration dictionary.
        output_dir: Path to the run output directory.
    """

    def __init__(
        self,
        initial_program: Path,
        evaluator: Path,
        config: dict[str, Any],
        output_dir: Path,
    ) -> None:
        self.initial_program = initial_program
        self.evaluator = evaluator
        self.config = config
        self.output_dir = output_dir
        self._controller: Any = None

    def _init_controller(self) -> None:
        """Lazily import and instantiate the OpenEvolve controller."""
        try:
            from openevolve.config import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
                Config as OEConfig,
            )
            from openevolve.controller import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
                OpenEvolve as OEController,
            )
        except ImportError as exc:
            raise ExternalError(
                "OpenEvolve is not installed. Install it with: pip install 'revolver[openevolve]'"
            ) from exc

        # Convert dict to Config dataclass (OpenEvolve expects Config, not dict)
        config_obj = OEConfig.from_dict(self.config)

        self._controller = OEController(
            str(self.initial_program),
            str(self.evaluator),
            config_obj,
            str(self.output_dir),
        )

    def run(
        self,
        iterations: int,
        checkpoint: Path | None = None,
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> RunOutput:
        """Launch the OpenEvolve evolution loop.

        Uses ``asyncio.run()`` internally, so this method **must not** be
        called from within an already-running async event loop (e.g. inside
        an ``async def`` or Jupyter notebook).  If nested-loop support is
        needed in the future, consider ``nest_asyncio`` or refactoring to
        an ``async run()`` method.

        Args:
            iterations: Number of evolution iterations.
            checkpoint: Path to checkpoint directory for resume (optional).
            on_progress: Callback invoked after each iteration (optional).

        Returns:
            RunOutput with best programs and metrics.

        Raises:
            ExternalError: If OpenEvolve is not installed or the run fails.
        """
        if self._controller is None:
            self._init_controller()

        try:
            checkpoint_str = str(checkpoint) if checkpoint else None
            best = asyncio.run(
                self._controller.run(
                    iterations=iterations,
                    checkpoint_path=checkpoint_str,
                )
            )
            best_score = _extract_best_score(best)
            return RunOutput(
                best_score=best_score,
                best_program=best,
                output_dir=self.output_dir,
            )
        except Exception as exc:
            raise ExternalError(f"OpenEvolve run failed: {exc}") from exc


# ── Config builder (DES-005 §4.2) ────────────────────────────────────────────


def build_config(
    problem_config: Path | None,
    llm: LLMEntry,
    iterations: int | None = None,
    config_overrides: list[str] | None = None,
    output_dir: Path | None = None,
    problem_description: str | None = None,
) -> dict[str, Any]:
    """Build the OpenEvolve config dict.

    Merge order (last wins):
        1. Problem version's config.yaml (base)
        2. LLM endpoint configuration (api_base, primary_model, api_key)
        3. Problem description injection into prompt.system_message
        4. --iterations override
        5. --config-override key=value pairs
        6. Output directory (always Revolver-controlled)

    Args:
        problem_config: Path to the problem's config.yaml file (optional).
        llm: Registered LLM entry with endpoint details.
        iterations: Override for iteration count (optional).
        config_overrides: List of ``key=value`` override strings (optional).
        output_dir: Revolver-controlled output directory (optional).
        problem_description: Content of problem.md for prompt injection (optional).

    Returns:
        Merged configuration dictionary.
    """
    # 1. Base config from problem version
    config: dict[str, Any] = {}
    if problem_config and problem_config.exists():
        with open(problem_config) as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                config = loaded

    # Strip Revolver-specific keys that clash with OpenEvolve Config fields.
    # These are passed separately to the OEController constructor, not via Config.
    # Only strip string values (Revolver paths); dicts are valid OpenEvolve sub-configs.
    for key in ("evaluator", "initial_program"):
        if isinstance(config.get(key), str):
            config.pop(key, None)

    # Map num_generations → max_iterations (OpenEvolve uses max_iterations).
    # If both keys are present, max_iterations wins and num_generations is dropped.
    if "num_generations" in config and "max_iterations" not in config:
        config["max_iterations"] = config.pop("num_generations")
    else:
        config.pop("num_generations", None)

    # 2. LLM endpoint injection (DES-005 §4.3)
    llm_config: dict[str, Any] = {}
    if llm.base_url:
        llm_config["api_base"] = llm.base_url
    llm_config["primary_model"] = llm.model
    if llm.api_key_env:
        api_key = os.environ.get(llm.api_key_env, "")
        if api_key:
            llm_config["api_key"] = api_key

    # Local LLMs (Ollama) require an api_key for the OpenAI SDK
    # but don't have a real key — inject a placeholder.
    if llm.source == "local" and "api_key" not in llm_config:
        llm_config["api_key"] = "ollama"

    if llm_config:
        config["llm"] = config.get("llm") if isinstance(config.get("llm"), dict) else {}
        config["llm"].update(llm_config)

    # Google provider detection (FB-02): Google's Generative Language API
    # rejects the ``seed`` parameter with HTTP 400.  Disable random_seed.
    # Must run after LLM injection (step 2) so llm.base_url is available,
    # and before config overrides (step 5) so --config-override can still win.
    # Only Gemini (generativelanguage) is a known Google LLM provider
    if llm.base_url and "generativelanguage.googleapis.com" in llm.base_url:
        config.setdefault("llm", {})
        if isinstance(config.get("llm"), dict):
            config["llm"]["random_seed"] = None

    # Force cascade_evaluation: false unless user explicitly set it.
    # OpenEvolve defaults to true, but Revolver evaluators don't define
    # evaluate_stage1/2/3 methods so cascade must be disabled.
    config.setdefault("evaluator", {})
    if isinstance(config.get("evaluator"), dict):
        config["evaluator"].setdefault("cascade_evaluation", False)

    # 3. Problem description injection (DES-005 §4.4)
    if problem_description:
        config["prompt"] = config.get("prompt") if isinstance(config.get("prompt"), dict) else {}
        config["prompt"]["system_message"] = SYSTEM_PROMPT_TEMPLATE.format(
            problem_description=problem_description,
        )

    # 4. Iterations override
    if iterations is not None:
        config["max_iterations"] = iterations

    # 5. Config overrides (key=value pairs, dotted keys supported)
    if config_overrides:
        for override in config_overrides:
            if "=" not in override:
                raise ValidationError(
                    f"Malformed config override (expected key=value): {override!r}"
                )
            key, value = override.split("=", 1)
            _set_nested(config, key.strip(), _parse_value(value.strip()))

    # 6. Output directory
    if output_dir is not None:
        config["output_dir"] = str(output_dir)

    return config


def _extract_best_score(best: Any) -> float | None:
    """Extract a numeric score from the OpenEvolve best result.

    OpenEvolve may return a raw number or a ``Program`` object with a
    ``.metrics`` dict containing ``"combined_score"``.
    """
    if isinstance(best, (int, float)):
        return float(best)
    if hasattr(best, "metrics") and isinstance(best.metrics, dict):
        score = best.metrics.get("combined_score")
        if isinstance(score, (int, float)):
            return float(score)
    return None


def _set_nested(d: dict[str, Any], key: str, value: Any) -> None:
    """Set a value in a nested dict using dotted key notation.

    Example: ``_set_nested(d, "llm.temperature", 0.5)`` sets
    ``d["llm"]["temperature"] = 0.5``.
    """
    parts = key.split(".")
    current = d
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _parse_value(value: str) -> Any:
    """Parse a string value into the appropriate Python type.

    Supports: None (null/none), int, float, bool, and string fallback.
    """
    if value.lower() in ("null", "none"):
        return None
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


# ── Environment variable context manager (DES-005 §5) ────────────────────────


@contextmanager
def revolver_env(env_vars: dict[str, str]) -> Iterator[None]:
    """Context manager to set and clean up REVOLVER_* environment variables.

    On entry, sets all provided env vars (saving previous values).
    On exit, restores previous values or removes variables that were not
    previously set.

    Args:
        env_vars: Mapping of env var names to values.
    """
    old: dict[str, str | None] = {}
    for key, value in env_vars.items():
        old[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key in env_vars:
            prev = old[key]
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


__all__ = ["OpenEvolveRunner", "ProgressInfo", "RunOutput", "build_config", "revolver_env"]
