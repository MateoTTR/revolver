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
from collections.abc import Callable, Iterator
import contextlib
from contextlib import contextmanager
import copy
from dataclasses import dataclass
import json as _json
import logging
import os
from pathlib import Path
import sys
from typing import Any

import yaml

from revolver.core.exceptions import ExternalError, ValidationError
from revolver.models.llm import EnsembleEntry, LLMEntry

logger = logging.getLogger(__name__)

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


# ── Known misplaced database keys ─────────────────────────────────────────────
# Keys that users commonly place at top level but belong under ``database:``.

_DATABASE_KEYS = frozenset(
    {
        "num_islands",
        "migration_interval",
        "population_size",
        "feature_dimensions",
        "feature_bins",
        "migration_rate",
    }
)

# ── Revolver-specific keys ───────────────────────────────────────────────────
# Keys that Revolver places in config.yaml but are NOT part of the OpenEvolve
# Config schema.  They must be stripped before dacite strict parsing to avoid
# false-positive "unknown key" warnings.

REVOLVER_KEYS = frozenset({"initial_program", "num_generations", "timeout_per_instance"})


def validate_oe_config(config: Path | dict[str, Any]) -> list[str]:
    """Validate a config dict or YAML file against the OpenEvolve Config schema.

    Attempts a strict dacite parse.  Returns warning messages for unknown
    keys (empty list means the config is valid).

    Before the strict parse, known Revolver-injected keys that are not part
    of the OpenEvolve schema are stripped so they do not trigger false
    positives:

    - ``output_dir`` at top level (Revolver passes it to OEController, not Config)
    - ``api_key_env`` inside ``llm`` (Revolver resolves it to ``api_key`` at runtime)
    - ``initial_program``, ``num_generations``, ``timeout_per_instance`` — Revolver-
      specific keys listed in :data:`REVOLVER_KEYS`

    Args:
        config: Path to a YAML config file **or** an already-loaded dict.

    Returns:
        A (possibly empty) list of human-readable warning strings.  Entries
        may be unknown-key warnings **or** deprecation notices (e.g. for
        ``num_generations``).
    """
    try:
        import dacite  # type: ignore[import-not-found,unused-ignore]
        from openevolve.config import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
            Config as OEConfig,
        )
    except ImportError:
        # OpenEvolve or dacite not installed — skip validation gracefully
        return []

    # Load YAML if a path was given
    data: dict[str, Any]
    if isinstance(config, Path):
        try:
            with open(config) as f:
                loaded = yaml.safe_load(f)
            if not isinstance(loaded, dict):
                return []
            data = loaded
        except Exception:
            return []
    else:
        data = config

    # Deep-copy to avoid mutating the caller's dict
    data = copy.deepcopy(data)

    # Strip Revolver-injected keys that are NOT part of OEConfig
    data.pop("output_dir", None)
    llm_section = data.get("llm")
    if isinstance(llm_section, dict):
        llm_section.pop("api_key_env", None)

    # Strip Revolver-specific keys (initial_program, num_generations, etc.)
    had_num_generations = "num_generations" in data
    for rk in REVOLVER_KEYS:
        data.pop(rk, None)

    # Build deprecation notice (independent of dacite parse outcome)
    warnings: list[str] = []
    if had_num_generations:
        warnings.append(
            "Deprecation: 'num_generations' is deprecated, use 'max_iterations' instead. "
            "It will still work but may be removed in a future version."
        )

    # Attempt strict parse
    try:
        dacite.from_dict(
            data_class=OEConfig,
            data=data,
            config=dacite.Config(
                cast=[list, type(None)],
                strict=True,
                forward_references={"LLMInterface": Any},
            ),
        )
        return warnings
    except dacite.UnexpectedDataError as exc:
        # exc.keys is a set of unknown key names
        for key in sorted(exc.keys):
            if key in _DATABASE_KEYS:
                warnings.append(
                    f"Unknown OE config key '{key}' at top level. Did you mean 'database.{key}'?"
                )
            else:
                warnings.append(
                    f"Unknown OE config key '{key}' (not in OpenEvolve Config schema)."
                )
        return warnings
    except Exception:
        # Any other parse error (type mismatch, etc.) — graceful degradation
        return []


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

        # NOTE: Config validation is intentionally NOT done here.
        # The raw config.yaml is validated at `problem version create` time
        # and at `launch_run`/`resume_run` entry. The config dict here is the
        # fully merged runtime config containing Revolver-injected keys
        # (api_key, api_base, prompt.system_message, etc.) which would
        # produce spurious unknown-key warnings in dacite strict mode.

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

        # Ensure unbuffered output for real-time progress (S8a-09).
        # This affects any child processes OpenEvolve may spawn.
        os.environ["PYTHONUNBUFFERED"] = "1"

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


def _build_ensemble_llm_config(
    config: dict[str, Any],
    ensemble: EnsembleEntry,
    primary_llm: LLMEntry,
    conn: Any | None,
) -> None:
    """Build the ``llm.models`` array for ensemble mode (S11-07).

    Each ensemble member is resolved to its registered LLM entry, and the
    OE field mapping is applied:

    - ``LLMEntry.model`` → ``models[].name`` (NOT ``model``)
    - ``LLMEntry.base_url`` → ``models[].api_base`` (NOT ``base_url``)
    - ``LLMEntry.api_key_env`` → ``models[].api_key`` as ``${ENV_NAME}``
    - ``EnsembleMember.weight`` → ``models[].weight``
    - ``EnsembleMember.temperature`` → ``models[].temperature`` (optional)
    - ``EnsembleMember.max_tokens`` → ``models[].max_tokens`` (optional)

    Falls back to the member's LLM registry defaults for temperature and
    max_tokens when no per-member override is set.

    Args:
        config: The OE config dict to mutate (adds ``llm.models``).
        ensemble: The ensemble entry with member definitions.
        primary_llm: The first member's LLM entry, used for shared defaults.
        conn: Global DB connection for resolving member LLM details.
    """
    from revolver.infra.db import get_llm

    config["llm"] = config.get("llm") if isinstance(config.get("llm"), dict) else {}

    models: list[dict[str, Any]] = []
    for member in ensemble.members:
        # Resolve member LLM details
        member_llm: LLMEntry | None = None
        if conn is not None:
            member_llm = get_llm(conn, member.llm_name)
        if member_llm is None:
            raise ValidationError(
                f"Ensemble member LLM '{member.llm_name}' not found in registry."
            )

        entry: dict[str, Any] = {
            "name": member_llm.model,
            "weight": member.weight,
        }

        if member_llm.base_url:
            entry["api_base"] = member_llm.base_url

        if member_llm.api_key_env:
            entry["api_key"] = f"${{{member_llm.api_key_env}}}"

        # Per-member overrides take precedence over LLM registry defaults
        effective_temperature = (
            member.temperature if member.temperature is not None else member_llm.temperature
        )
        if effective_temperature is not None:
            entry["temperature"] = effective_temperature

        effective_max_tokens = (
            member.max_tokens if member.max_tokens is not None else member_llm.max_tokens
        )
        if effective_max_tokens is not None:
            entry["max_tokens"] = effective_max_tokens

        models.append(entry)

    config["llm"]["models"] = models


def build_config(
    problem_config: Path | None,
    llm: LLMEntry,
    iterations: int | None = None,
    config_overrides: list[str] | None = None,
    output_dir: Path | None = None,
    problem_description: str | None = None,
    temperature: float | None = None,
    parallel: int | None = None,
    rewrite_mode: bool = False,
    ensemble: EnsembleEntry | None = None,
    conn: Any | None = None,
) -> dict[str, Any]:
    """Build the OpenEvolve config dict.

    Merge order (last wins):
        1. Problem version's config.yaml (base)
        2. LLM endpoint configuration (api_base, primary_model, api_key_env)
        2b. LLM per-model config (max_tokens, timeout, temperature) from LLM registry
        2c. CLI flags: --temperature, --parallel (override LLM registry values)
        3. Problem description injection into prompt.system_message
        4. --iterations override
        4b. --rewrite-mode shortcut (diff_based_evolution=false, max_code_length=50000)
        5. --config-override key=value pairs
        6. Output directory (always Revolver-controlled)

    When *ensemble* is provided, ``llm.models`` (array) is emitted instead of
    ``llm.model`` (singular). Each member is resolved via ``get_llm()`` and
    mapped to OpenEvolve field names: ``name`` (model), ``api_base`` (base_url),
    ``api_key`` (``${API_KEY_ENV}`` syntax), ``weight``, and optional
    ``temperature``/``max_tokens``.

    Args:
        problem_config: Path to the problem's config.yaml file (optional).
        llm: Registered LLM entry with endpoint details. For ensemble mode,
            this is used as the "primary" LLM for shared settings.
        iterations: Override for iteration count (optional).
        config_overrides: List of ``key=value`` override strings (optional).
        output_dir: Revolver-controlled output directory (optional).
        problem_description: Content of problem.md for prompt injection (optional).
        temperature: CLI ``--temperature`` override (optional). Overrides LLM
            registry temperature (step 2b) but is itself overridden by
            ``--config-override llm.temperature=X`` (step 5).
        parallel: CLI ``--parallel`` override for ``evaluator.parallel_evaluations``
            (optional).
        rewrite_mode: Full-rewrite mode shortcut (optional). When ``True``, sets
            ``diff_based_evolution=false`` and ``max_code_length=50000``.
            Overridable by ``--config-override`` (step 5).
        ensemble: Ensemble entry for multi-model mode (optional).
        conn: Global database connection, required when *ensemble* is provided
            to resolve member LLM details.

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
    if ensemble is not None:
        # Ensemble mode: emit llm.models array (S11-07)
        _build_ensemble_llm_config(config, ensemble, llm, conn)
    else:
        # Single-LLM mode (unchanged)
        llm_config: dict[str, Any] = {}
        if llm.base_url:
            llm_config["api_base"] = llm.base_url
        llm_config["primary_model"] = llm.model
        if llm.api_key_env:
            llm_config["api_key_env"] = llm.api_key_env

        # Local LLMs (Ollama) require an api_key for the OpenAI SDK
        # but don't have a real key — inject a placeholder.
        if llm.source == "local" and "api_key" not in llm_config:
            llm_config["api_key"] = "ollama"

        if llm_config:
            config["llm"] = config.get("llm") if isinstance(config.get("llm"), dict) else {}
            config["llm"].update(llm_config)

    # 2b. LLM per-model config (max_tokens, timeout, temperature) from registry
    # In ensemble mode these act as shared defaults in the top-level llm section.
    if llm.max_tokens is not None:
        config.setdefault("llm", {})
        if isinstance(config.get("llm"), dict):
            config["llm"]["max_tokens"] = llm.max_tokens
    if llm.timeout_s is not None:
        config.setdefault("llm", {})
        if isinstance(config.get("llm"), dict):
            config["llm"]["timeout"] = llm.timeout_s
    if llm.temperature is not None:
        config.setdefault("llm", {})
        if isinstance(config.get("llm"), dict):
            config["llm"]["temperature"] = llm.temperature

    # Google provider detection (FB-02): Google's Generative Language API
    # rejects the ``seed`` parameter with HTTP 400.  Disable random_seed.
    # Must run after LLM injection (step 2) so llm.base_url is available,
    # and before config overrides (step 5) so --config-override can still win.
    # Only Gemini (generativelanguage) is a known Google LLM provider
    if llm.base_url and "generativelanguage.googleapis.com" in llm.base_url:
        config["random_seed"] = None  # Top-level: this is what OE sends to the API
        config.setdefault("llm", {})
        if isinstance(config.get("llm"), dict):
            config["llm"]["random_seed"] = None

    # Force cascade_evaluation: false unless user explicitly set it.
    # OpenEvolve defaults to true, but Revolver evaluators don't define
    # evaluate_stage1/2/3 methods so cascade must be disabled.
    config.setdefault("evaluator", {})
    if isinstance(config.get("evaluator"), dict):
        config["evaluator"].setdefault("cascade_evaluation", False)

    # 2c. CLI flags: --temperature and --parallel (override LLM registry values)
    if temperature is not None:
        config.setdefault("llm", {})
        if isinstance(config.get("llm"), dict):
            config["llm"]["temperature"] = temperature
    if parallel is not None:
        config.setdefault("evaluator", {})
        if isinstance(config.get("evaluator"), dict):
            config["evaluator"]["parallel_evaluations"] = parallel

    # 3. Problem description injection (DES-005 §4.4)
    if problem_description:
        config["prompt"] = config.get("prompt") if isinstance(config.get("prompt"), dict) else {}
        config["prompt"]["system_message"] = SYSTEM_PROMPT_TEMPLATE.format(
            problem_description=problem_description,
        )

    # 4. Iterations override
    if iterations is not None:
        config["max_iterations"] = iterations

    # 4b. Rewrite mode (full-rewrite shortcut)
    if rewrite_mode:
        config["diff_based_evolution"] = False
        config["max_code_length"] = 50000

    # 5. Config overrides (key=value pairs, dotted keys supported)
    if config_overrides:
        for override in config_overrides:
            if "=" not in override:
                raise ValidationError(
                    f"Malformed config override (expected key=value): {override!r}"
                )
            key, value = override.split("=", 1)
            _set_nested(config, key.strip(), _parse_value(value.strip()))

    # 5b. Guard: ensure checkpoint_interval <= iterations for resume capability
    effective_interval = config.get("checkpoint_interval", 100)  # OE default
    effective_iters = config.get("max_iterations")
    if (
        effective_iters is not None
        and isinstance(effective_interval, int)
        and isinstance(effective_iters, int)
        and effective_iters > 0
        and effective_interval > effective_iters
    ):
        msg = (
            f"Warning: checkpoint_interval ({effective_interval}) > "
            f"iterations ({effective_iters}) — no checkpoint would be saved. "
            f"Overriding to checkpoint_interval={effective_iters}.\n"
        )
        logger.warning(
            "checkpoint_interval (%d) > iterations (%d) — no checkpoint would be saved. "
            "Overriding to checkpoint_interval=%d to ensure a final checkpoint.",
            effective_interval,
            effective_iters,
            effective_iters,
        )
        sys.stderr.write(msg)
        config["checkpoint_interval"] = effective_iters

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

    Supports: JSON arrays/objects, None (null/none), int, float, bool,
    and string fallback.
    """
    # JSON array or object: try json.loads first
    if value.startswith("[") or value.startswith("{"):
        try:
            return _json.loads(value)
        except _json.JSONDecodeError:
            pass  # Fall through to scalar parsing / string fallback

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


def resolve_api_keys(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve api_key_env references in a config dict to actual API keys.

    Replaces ``llm.api_key_env`` with ``llm.api_key`` by reading the
    environment variable at call time.  This keeps secrets out of stored
    config snapshots while allowing runtime resolution.

    Also resolves ``${ENV_NAME}`` syntax in ``llm.models[].api_key`` entries
    for ensemble configurations.

    Args:
        config: OpenEvolve config dict (mutated in place and returned).

    Returns:
        The same config dict with api_key resolved.
    """
    llm_section = config.get("llm")
    if isinstance(llm_section, dict):
        # Single-LLM mode: resolve api_key_env
        env_name = llm_section.pop("api_key_env", None)
        if env_name:
            key = os.environ.get(env_name, "")
            if key:
                llm_section["api_key"] = key
            else:
                raise ValidationError(f"API key environment variable '{env_name}' is not set")

        # Ensemble mode: resolve ${ENV_NAME} syntax in models[].api_key
        models = llm_section.get("models")
        if isinstance(models, list):
            for model_entry in models:
                if isinstance(model_entry, dict):
                    api_key_ref = model_entry.get("api_key", "")
                    if (
                        isinstance(api_key_ref, str)
                        and api_key_ref.startswith("${")
                        and api_key_ref.endswith("}")
                    ):
                        env_var = api_key_ref[2:-1]
                        resolved = os.environ.get(env_var, "")
                        if resolved:
                            model_entry["api_key"] = resolved
                        else:
                            raise ValidationError(
                                f"API key environment variable '{env_var}' is not set"
                            )
    return config


def find_latest_checkpoint(run_dir: Path) -> Path | None:
    """Find the latest OpenEvolve checkpoint in a run directory.

    OpenEvolve saves checkpoints to ``oe-output/checkpoints/checkpoint_N/``.
    This helper scans that directory, sorts by numeric suffix, and returns
    the path with the highest iteration number.

    This function encodes knowledge of OpenEvolve's internal directory layout
    and belongs in the infrastructure layer (alongside ``count_valid_programs``).

    Args:
        run_dir: Path to the run directory (e.g. ``.revolver/runs/<run_id>``).

    Returns:
        Path to the latest ``checkpoint_N`` directory, or ``None`` if no
        checkpoint directory exists.
    """
    checkpoints_dir = run_dir / "oe-output" / "checkpoints"
    if not checkpoints_dir.is_dir():
        return None

    checkpoint_dirs: list[tuple[int, Path]] = []
    for child in checkpoints_dir.iterdir():
        if child.is_dir() and child.name.startswith("checkpoint_"):
            suffix = child.name.removeprefix("checkpoint_")
            with contextlib.suppress(ValueError):
                checkpoint_dirs.append((int(suffix), child))

    if not checkpoint_dirs:
        return None

    # Return the checkpoint with the highest iteration number
    checkpoint_dirs.sort(key=lambda t: t[0])
    return checkpoint_dirs[-1][1]


def _build_cell_reverse_map(
    checkpoint_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Build a reverse map from program ID to MAP-Elites cell info.

    Reads ``metadata.json`` from *checkpoint_dir* and parses the
    ``island_feature_maps`` field — a list (one per island) of dicts
    mapping ``"dim0-dim1"`` cell keys to program IDs.

    Returns:
        A dict mapping ``program_id`` to
        ``{"cell_indices": [int, ...], "island": int}``.
        Returns an empty dict on any failure (missing file, parse error).
    """
    metadata_path = checkpoint_dir / "metadata.json"
    if not metadata_path.is_file():
        return {}

    try:
        metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Failed to read or parse %s", metadata_path)
        return {}

    island_maps = metadata.get("island_feature_maps")
    if not isinstance(island_maps, list):
        return {}

    reverse: dict[str, dict[str, Any]] = {}
    for island_idx, feature_map in enumerate(island_maps):
        if not isinstance(feature_map, dict):
            continue
        for cell_key, prog_id in feature_map.items():
            try:
                cell_indices = [int(x) for x in cell_key.split("-")]
            except (ValueError, AttributeError):
                logger.warning(
                    "Skipping unparseable cell key '%s' in island %d",
                    cell_key,
                    island_idx,
                )
                continue
            # Last-write-wins: a program ID should appear in at most one island's
            # feature map (OE creates new UUIDs on migration). If duplicates ever
            # occur, we keep the last island's entry.
            reverse[prog_id] = {
                "cell_indices": cell_indices,
                "island": island_idx,
            }

    return reverse


def parse_population(checkpoint_dir: Path) -> list[dict[str, Any]]:
    """Parse OE checkpoint programs into a ranked population list.

    Scans ``checkpoint_dir/programs/*.json``, loads each program,
    extracts key fields and computes combined_score (sum of numeric
    metric values, matching OpenEvolve's ``_safe_sum_metrics`` convention).

    Also reads ``metadata.json`` to resolve MAP-Elites cell indices
    and island assignments for each program.

    Args:
        checkpoint_dir: Path to the OpenEvolve checkpoint directory
            (e.g. ``checkpoint_N/``).

    Returns:
        List of dicts sorted by combined_score descending, each with
        keys: ``rank``, ``id``, ``score``, ``metrics``, ``generation``,
        ``iteration_found``, ``parent_id``, ``cell_indices``, ``island``.
    """
    programs_dir = checkpoint_dir / "programs"
    if not programs_dir.is_dir():
        return []

    cell_map = _build_cell_reverse_map(checkpoint_dir)

    population: list[dict[str, Any]] = []
    for prog_file in sorted(programs_dir.glob("*.json")):
        try:
            data = _json.loads(prog_file.read_text(encoding="utf-8"))
            metrics = data.get("metrics", {})
            # Combined score = sum of numeric metric values (OE convention)
            numeric_vals = [
                v
                for v in metrics.values()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
            combined_score = sum(numeric_vals) if numeric_vals else 0.0

            prog_id = data.get("id", prog_file.stem)
            cell_info = cell_map.get(prog_id, {})

            population.append(
                {
                    "id": prog_id,
                    "score": combined_score,
                    "metrics": metrics,
                    "generation": data.get("generation", 0),
                    "iteration_found": data.get("iteration_found", 0),
                    "parent_id": data.get("parent_id"),
                    "cell_indices": cell_info.get("cell_indices"),
                    "island": cell_info.get("island"),
                }
            )
        except (OSError, ValueError, KeyError):
            continue  # Skip unparseable files

    # Sort by score descending, assign rank
    population.sort(key=lambda p: p["score"], reverse=True)
    for i, prog in enumerate(population, 1):
        prog["rank"] = i

    return population


def read_checkpoint_best_score(checkpoint_dir: Path) -> float | None:
    """Read the best program score from an OpenEvolve checkpoint.

    Reads ``metadata.json`` to find ``best_program_id``, then loads the
    corresponding program file from ``programs/{id}.json`` and extracts
    the score.

    Score extraction mirrors :func:`parse_population`: sums all numeric
    metric values.

    All file operations are read-only and error-tolerant — the checkpoint
    may be mid-write by a concurrent OpenEvolve process.

    Args:
        checkpoint_dir: Path to the OpenEvolve checkpoint directory
            (e.g. ``checkpoint_N/``).

    Returns:
        The best program's score, or ``None`` if unavailable.
    """
    try:
        metadata_path = checkpoint_dir / "metadata.json"
        if not metadata_path.exists():
            return None

        metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
        best_id = metadata.get("best_program_id")
        if not best_id:
            return None

        program_path = checkpoint_dir / "programs" / f"{best_id}.json"
        if not program_path.exists():
            return None

        program_data = _json.loads(program_path.read_text(encoding="utf-8"))
        metrics = program_data.get("metrics", {})
        if not isinstance(metrics, dict):
            return None

        # Sum of all numeric metric values (consistent with parse_population)
        numeric_vals = [
            v for v in metrics.values() if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        if numeric_vals:
            return float(sum(numeric_vals))

        return None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def count_valid_programs(checkpoint_dir: Path) -> int | None:
    """Count valid program entries in an OpenEvolve checkpoint database.

    Scans for ``database.json`` in the checkpoint directory or its
    immediate subdirectories (e.g. ``checkpoint_N/database.json``).

    Args:
        checkpoint_dir: Path to the OpenEvolve checkpoint directory.

    Returns:
        The number of program entries in the database, or ``None`` if
        the file is not found or cannot be parsed.
    """

    # Look for database.json directly or in subdirectories
    candidates = [checkpoint_dir / "database.json"]
    if checkpoint_dir.exists():
        for child in sorted(checkpoint_dir.iterdir()):
            if child.is_dir():
                candidates.append(child / "database.json")

    for db_path in candidates:
        if db_path.exists():
            try:
                data = _json.loads(db_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return len(data)
                if isinstance(data, dict) and "programs" in data:
                    programs = data["programs"]
                    if isinstance(programs, list):
                        return len(programs)
                # Unknown dict format — cannot determine program count
                return None
            except (OSError, ValueError, KeyError):
                return None
    return None


__all__ = [
    "REVOLVER_KEYS",
    "OpenEvolveRunner",
    "ProgressInfo",
    "RunOutput",
    "build_config",
    "count_valid_programs",
    "find_latest_checkpoint",
    "parse_population",
    "read_checkpoint_best_score",
    "resolve_api_keys",
    "revolver_env",
    "validate_oe_config",
]
