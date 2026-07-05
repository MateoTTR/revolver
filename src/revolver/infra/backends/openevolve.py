"""OpenEvolve backend — controller wrapper for Revolver integration.

Moved from ``revolver.infra.openevolve`` (ADR-007 D1, Sprint 013); that
module remains as a thin re-export shim until S15.

Wraps the OpenEvolve controller class to provide:
- Programmatic config building with merge order
- Environment variable injection via context manager
- Problem description injection into system prompt
- Token proxy integration for usage tracking
- Wrapper evaluator generation (DES-005 §3; moved from ``core.run`` in
  Sprint 013 PR-C)
- :class:`OpenEvolveBackend` — the ``EvolutionBackend`` protocol adapter
  over the functions above (ADR-007 D1)

Traceable to: DES-005 (Run Orchestration), ADR-006 (Instance Injection),
ADR-007 (Pluggable Evolution Backend).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
import contextlib
from contextlib import contextmanager
import copy
from dataclasses import dataclass
import importlib.util
import json as _json
import logging
import os
from pathlib import Path
import shutil
import sys
from types import ModuleType
from typing import Any

import yaml

from revolver.core.exceptions import (
    CheckpointRecoveryError,
    EvaluatorLoadError,
    ExternalError,
    RevolverError,
    ValidationError,
)
from revolver.infra.backends.base import (
    BackendCapabilities,
    BackendRunResult,
    BackendRunSpec,
    ChildProcessReaperMixin,
    ProgressInfo,
    RankedProgram,
    RecoveredProgram,
)
from revolver.models.llm import EnsembleEntry, LLMEntry
from revolver.models.run import ResolvedConfig, TokenUsage

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


# NOTE: ProgressInfo moved to revolver.infra.backends.base (ADR-007 D1) —
# it is part of the backend-neutral interface vocabulary. Re-exported here
# for compatibility.


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

# ── Revolver-specific top-level sections ─────────────────────────────────────
# Sections that Revolver owns and the engine never sees. They must be stripped
# before strict parsing so they do not trigger "unknown key" warnings. Mirrors
# the Shinka backend's ``_REVOLVER_SECTIONS`` (symmetric cross-backend
# treatment, not an OpenEvolve-schema allowlist widening):
# - ``evaluation``: wrapper settings (``timeout_per_instance``); consumed by
#   ``core.run`` (prefers ``evaluation:`` over ``evaluator:``) to size the
#   generated wrapper evaluator, never passed to the OpenEvolve Config schema.
REVOLVER_SECTIONS = frozenset({"evaluation"})

# Feature dimensions computed *inside* OpenEvolve (U8 / FR-RUN-056). They are
# legitimately absent from the evaluator's (and thus the seed's pre-flight)
# metrics, so validate_seed_metrics() must never require them: ``complexity``
# and ``diversity`` are engine builtins derived from the program itself, and
# ``combined_score`` is the fitness the engine reads from every evaluation.
OE_BUILTIN_FEATURE_DIMENSIONS = frozenset({"complexity", "diversity", "combined_score"})

# Default LLM request timeout (seconds) injected for ``--source local``
# endpoints when the LLM entry has no explicit ``timeout_s`` (#307). The
# OpenEvolve OpenAI client defaults to 60 s, which aborts slow local
# endpoints (e.g. the claude-ollama-bridge at 50-530 s/call) -> a retry
# storm and a proxy BrokenPipeError. Remote APIs keep OpenEvolve's default.
DEFAULT_LOCAL_LLM_TIMEOUT_S = 600

# Marker prefixing every "unknown key" finding emitted by validate_oe_config().
# Shared with _warn_noop_config_overrides()'s B9 filter (below) so that a reword
# of these messages cannot silently break no-op detection there.
_UNKNOWN_OE_KEY_MARKER = "Unknown OE config key"


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
    - ``evaluation`` — Revolver-owned top-level section listed in
      :data:`REVOLVER_SECTIONS` (holds the wrapper ``timeout_per_instance``)

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

    # Strip Revolver-owned top-level sections (e.g. ``evaluation``) — they are
    # not part of the OpenEvolve Config schema and would otherwise produce
    # false-positive "unknown key" warnings (A6/#318).
    for section in REVOLVER_SECTIONS:
        data.pop(section, None)

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
                    f"{_UNKNOWN_OE_KEY_MARKER} '{key}' at top level. "
                    f"Did you mean 'database.{key}'?"
                )
            else:
                warnings.append(
                    f"{_UNKNOWN_OE_KEY_MARKER} '{key}' (not in OpenEvolve Config schema)."
                )
        return warnings
    except Exception:
        # Any other parse error (type mismatch, etc.) — graceful degradation
        return []


def _warn_noop_config_overrides(
    config_overrides: list[str] | None,
    parsed_values: dict[str, Any],
) -> None:
    """Warn on ``--config-override`` keys that land on no OpenEvolve field (B9).

    ``build_config`` writes every override into the merged config via
    :func:`_set_nested` regardless of whether the dotted key names a real
    OpenEvolve ``Config`` field, so a typo (``llm.nonexistent_key=1``) is
    silently set-and-ignored by the engine. This surfaces the no-op instead
    of swallowing it (spec §4.5, ADR-007 A5) — the ``--config-override``
    escape hatch must never quietly do nothing.

    Detection reuses the strict-dacite machinery of :func:`validate_oe_config`
    (no hand-rolled schema): each override is validated **in isolation** as a
    minimal ``{path: value}`` config. Per-key isolation is required because a
    single dacite parse only reports the first dataclass it rejects, so a
    whole-config pass would miss unknown keys in later sections. Revolver-owned
    keys/sections (``evaluation:``, ``initial_program``, ``num_generations`` —
    :data:`REVOLVER_KEYS` / :data:`REVOLVER_SECTIONS`, stripped before the
    strict parse) never warn, so this cannot regress those tolerated paths.

    Degrades to silence when OpenEvolve/dacite are unavailable (validation
    returns ``[]``), mirroring ``problem version create``.

    Note: dacite recurses into JSON-object override *values*, so a whole-section
    override like ``evaluator={"bogus_sub": 1}`` is also caught here — a bonus,
    though the warning names the override key (``evaluator``) rather than the
    offending leaf (``bogus_sub``). The Shinka B9 probe deliberately substitutes
    an empty dict for the value and so does *not* recurse into JSON-object
    contents; this OE-vs-Shinka asymmetry is harmless (both err toward warning).

    Args:
        config_overrides: The raw ``key=value`` override strings.
        parsed_values: Map of dotted override key → already-parsed value, so
            the probe carries the real value (a type mismatch on a *recognized*
            key must not masquerade as an unknown key).
    """
    for override in config_overrides or []:
        if "=" not in override:
            continue
        key = override.split("=", 1)[0].strip()
        probe: dict[str, Any] = {}
        _set_nested(probe, key, parsed_values.get(key))
        # Only "unknown key" findings are no-ops. Deprecation notices (e.g.
        # ``num_generations``, which build_config remaps to ``max_iterations``)
        # are recognized keys and must NOT warn as no-ops.
        if any(_UNKNOWN_OE_KEY_MARKER in msg for msg in validate_oe_config(probe)):
            sys.stderr.write(
                f"Warning: --config-override '{key}' matches no field in the "
                f"OpenEvolve config schema; it will have no effect.\n"
            )


# ── OpenEvolve runner ─────────────────────────────────────────────────────────


class OpenEvolveRunner(ChildProcessReaperMixin):
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

        # Snapshot the process's child PIDs BEFORE the run so the post-run
        # backstop only reaps children the run itself spawned (B2 / S17-03,
        # symmetric to the Shinka teardown #314). Children predating the run
        # are excluded.
        pre_run_children = self._current_child_pids()

        # Ensure unbuffered output for real-time progress (S8a-09); this
        # affects any child processes OpenEvolve may spawn. Scoped through
        # revolver_env so the caller's PYTHONUNBUFFERED is restored on exit
        # (S15-15) — the env mutation must not leak past the run.
        with revolver_env({"PYTHONUNBUFFERED": "1"}):
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
            finally:
                # Orchestrator-owned teardown (B2 / S17-05, symmetric to the
                # Shinka path #314). OpenEvolve's own ``_cleanup`` normally
                # stops the ``ProcessParallelController`` and joins its
                # ``ProcessPoolExecutor``, yet on an abnormal exit a worker /
                # evaluator child can survive and pin the CLI at ~100% CPU.
                # This teardown is purely defensive: idempotent with the
                # engine's cleanup, never raises, and only touches the OE path.
                # By the time ``asyncio.run`` returns the best program is
                # already persisted in the checkpoint, so neither the resource
                # shutdown nor the child reap can truncate the result.
                self._shutdown_runner(self._controller)
                self._reap_run_children(pre_run_children)

    @staticmethod
    def _shutdown_runner(controller: Any) -> None:
        """Defensively tear down the OE controller's reachable process pool.

        OpenEvolve drives evaluations through a
        ``ProcessParallelController`` whose ``executor`` is a
        ``ProcessPoolExecutor``. On a clean run the controller's own cleanup
        already stops it, so this is a no-op backstop for the case where the
        controller returns with the pool still alive.

        ``shutdown(wait=False)`` is used **deliberately**: calling
        ``ProcessPoolExecutor.shutdown(wait=True)`` here would block the
        orchestrator on a wedged worker — the exact #159 hang. Every step is
        ``getattr``-guarded and suppressed so a partially-constructed
        controller (or a future upstream rename) can never turn teardown into
        a crash.
        """
        if controller is None:
            return

        parallel_controller = getattr(controller, "parallel_controller", None)
        executor = getattr(parallel_controller, "executor", None)
        executor_shutdown = getattr(executor, "shutdown", None)
        if callable(executor_shutdown):
            with contextlib.suppress(Exception):
                executor_shutdown(wait=False)


# ── Config builder (DES-005 §4.2) ────────────────────────────────────────────


def _build_ensemble_llm_config(
    config: dict[str, Any],
    ensemble: EnsembleEntry,
    primary_llm: LLMEntry,
    conn: Any | None,
    weight_overrides: dict[str, float] | None = None,
) -> None:
    """Build the ``llm.models`` array for ensemble mode (S11-07).

    Each ensemble member is resolved to its registered LLM entry, and the
    OE field mapping is applied:

    - ``LLMEntry.model`` → ``models[].name`` (NOT ``model``)
    - ``LLMEntry.base_url`` → ``models[].api_base`` (NOT ``base_url``)
    - ``LLMEntry.api_key_env`` → ``models[].api_key`` as ``${ENV_NAME}``;
      a key-less ``source == "local"`` member gets the ``"ollama"``
      placeholder instead (U2/S17a-09 — mirrors the single-LLM path)
    - ``EnsembleMember.weight`` → ``models[].weight``
    - ``EnsembleMember.temperature`` → ``models[].temperature`` (optional)
    - ``EnsembleMember.max_tokens`` → ``models[].max_tokens`` (optional)
    - ``EnsembleMember.reasoning_effort`` → ``models[].reasoning_effort``
      (optional; S17-26, FACT A: OpenEvolve honours effort per model)

    Falls back to the member's LLM registry defaults for temperature,
    max_tokens, and reasoning_effort when no per-member override is set.

    Args:
        config: The OE config dict to mutate (adds ``llm.models``).
        ensemble: The ensemble entry with member definitions.
        primary_llm: The first member's LLM entry, used for shared defaults.
        conn: Global DB connection for resolving member LLM details.
        weight_overrides: Per-run ``--llm-weight model=weight`` overrides keyed
            by member LLM registry name (ADR-007 A1/M3). When a member's name
            is present the override *wins* over the registry ``member.weight``;
            otherwise the registry weight is used unchanged.
    """
    from revolver.infra.db import get_llm

    config["llm"] = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    overrides = weight_overrides or {}

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

        # --llm-weight override wins over the registry weight (CLI wins).
        effective_weight = overrides.get(member.llm_name, member.weight)

        entry: dict[str, Any] = {
            "name": member_llm.model,
            "weight": effective_weight,
        }

        if member_llm.base_url:
            entry["api_base"] = member_llm.base_url

        if member_llm.api_key_env:
            entry["api_key"] = f"${{{member_llm.api_key_env}}}"
        elif member_llm.source == "local":
            # Key-less local member: the OpenAI SDK requires an api_key, and
            # leaving it unset both crashes at init AND silently forwards an
            # ambient OPENAI_API_KEY to the local endpoint. Inject the same
            # "ollama" placeholder as the single-LLM path (#115) — U2/S17a-09.
            entry["api_key"] = "ollama"

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

        # Per-member reasoning_effort override wins over the member LLM's
        # registry-level value (S17-26, ADR-007 A3.2). OpenEvolve honours
        # reasoning_effort per model in its llm.models array (FACT A).
        effective_reasoning_effort = (
            member.reasoning_effort
            if member.reasoning_effort is not None
            else member_llm.reasoning_effort
        )
        if effective_reasoning_effort is not None:
            entry["reasoning_effort"] = effective_reasoning_effort

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
    selection: str | None = None,
    llm_weight_overrides: dict[str, float] | None = None,
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
            (optional). When unset (``None``) on a ``--source local`` endpoint,
            ``parallel_evaluations`` is auto-pinned to ``1`` unless overridden via
            ``--config-override`` (A3/#315). An explicit value ``>1`` on a local
            endpoint is honoured with a warning (map-with-warn).
        rewrite_mode: Full-rewrite mode shortcut (optional). When ``True``, sets
            ``diff_based_evolution=false`` and ``max_code_length=50000``.
            Overridable by ``--config-override`` (step 5).
        ensemble: Ensemble entry for multi-model mode (optional).
        conn: Global database connection, required when *ensemble* is provided
            to resolve member LLM details.
        selection: Resolved ``--selection`` strategy (optional). OpenEvolve's
            only ensemble selection is the static weighted sampler, so any
            value other than ``None``/``"fixed"`` is rejected here as a
            defensive belt-and-braces guard behind the primary orchestrator
            check (ADR-007 A2/A4, DES-005 §4.2).
        llm_weight_overrides: Per-run ``--llm-weight model=weight`` overrides
            keyed by member LLM registry name, applied on top of the registry
            weights when building the ``llm.models`` array (ADR-007 A1/M3).

    Returns:
        Merged configuration dictionary.

    Raises:
        ValidationError: If *selection* is an adaptive strategy OpenEvolve
            cannot honor (only static weighted sampling is supported).
    """
    # 0. Defensive selection guard (ADR-007 A2/A4): OpenEvolve only offers the
    # static weighted sampler, whose sole neutral selection value is "fixed".
    # The orchestrator-level capability check (core.run._validate_selection) is
    # primary and rejects an unsupported value earlier; this belt-and-braces
    # guard keeps build_config honest if called directly.
    if selection is not None and selection != "fixed":
        raise ValidationError(
            f"Selection strategy '{selection}' is not supported by backend "
            f"'openevolve'. Supported: fixed."
        )

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
        _build_ensemble_llm_config(config, ensemble, llm, conn, llm_weight_overrides)
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
    elif llm.source == "local":
        # #307: a slow local endpoint aborts at OpenEvolve's 60 s OpenAI-client
        # default. When the registered LLM has no explicit timeout, raise the
        # default for --source local. setdefault respects a config.yaml
        # llm.timeout, and --config-override llm.timeout=… (step 5) still wins.
        config.setdefault("llm", {})
        if isinstance(config.get("llm"), dict):
            config["llm"].setdefault("timeout", DEFAULT_LOCAL_LLM_TIMEOUT_S)
    if llm.temperature is not None:
        config.setdefault("llm", {})
        if isinstance(config.get("llm"), dict):
            config["llm"]["temperature"] = llm.temperature
    # 2b (S17-26): single-LLM reasoning_effort from the registry entry. In
    # ensemble mode the per-member value is already mapped onto llm.models[]
    # above, so only inject the top-level key on the single-LLM path.
    # --config-override llm.reasoning_effort=… (step 5) still wins.
    if ensemble is None and llm.reasoning_effort is not None:
        config.setdefault("llm", {})
        if isinstance(config.get("llm"), dict):
            config["llm"]["reasoning_effort"] = llm.reasoning_effort

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

    # --parallel handling, incl. the local-endpoint auto-pin (A3/#315,
    # extends #309). A "local" source LLM is typically a serialized
    # subscription or single-GPU endpoint, so fanning out parallel
    # evaluations starves it -> staggered calls, 600 s timeouts, a retry
    # storm and a multi-hour hang (see DEFAULT_LOCAL_LLM_TIMEOUT_S / #307).
    # Policy:
    #   - parallel unset + source local + not set via --config-override
    #     -> pin parallel_evaluations = 1 (conservative default for ALL
    #        local endpoints, incl. genuine multi-GPU; cheap to override).
    #   - parallel explicitly >1 on a local endpoint -> warn but honour the
    #     user's value (map-with-warn, mirrors the Shinka pin in S16-21).
    #   - remote endpoints are unaffected.
    # --config-override evaluator.parallel_evaluations=N (step 5) always wins.
    overrides_set_parallel = any(
        override.split("=", 1)[0].strip()
        in ("parallel_evaluations", "evaluator.parallel_evaluations")
        for override in (config_overrides or [])
        if "=" in override
    )
    if parallel is not None:
        if llm.source == "local" and parallel > 1:
            sys.stderr.write(
                f"Warning: --parallel {parallel} on a --source local endpoint. Local "
                "endpoints (subscription-backed or single-GPU) usually serialize "
                "requests, so concurrency yields no speedup and can trigger timeouts "
                "and a retry storm. Honouring your value; pass --parallel 1 to pin.\n"
            )
        config.setdefault("evaluator", {})
        if isinstance(config.get("evaluator"), dict):
            config["evaluator"]["parallel_evaluations"] = parallel
    elif llm.source == "local" and not overrides_set_parallel:
        config.setdefault("evaluator", {})
        if isinstance(config.get("evaluator"), dict):
            config["evaluator"]["parallel_evaluations"] = 1

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
        parsed_overrides: dict[str, Any] = {}
        for override in config_overrides:
            if "=" not in override:
                raise ValidationError(
                    f"Malformed config override (expected key=value): {override!r}"
                )
            key, value = override.split("=", 1)
            parsed = _parse_value(value.strip())
            parsed_overrides[key.strip()] = parsed
            _set_nested(config, key.strip(), parsed)
        # B9 (S17-30): warn on override keys that land on no OpenEvolve field.
        _warn_noop_config_overrides(config_overrides, parsed_overrides)

    # 5a. U6 phase 2 (S18-13 / FR-RUN-057): default checkpoint cadence.
    # When checkpoint_interval is UNSET (absent from both the problem
    # config.yaml and --config-override — checked after step 5 so an
    # override counts as explicit), default it to max(1, min(100,
    # iterations // 10)) so a killed <=100-iteration run has a mid-run
    # checkpoint to resume from (the engine default of 100 meant zero
    # mid-run checkpoints for the whole default regime). An EXPLICIT value
    # is never touched; a defaulted one is always <= iterations, which
    # naturally defuses 5b's default-100-vs-small-iters clamp. Release-noted
    # v0.18 default-path change (sprint-018 exit criterion 10). Shinka has
    # no checkpoint_interval concept — this is OpenEvolve-only.
    interval_is_explicit = "checkpoint_interval" in config
    if not interval_is_explicit:
        cadence_iters = config.get("max_iterations")
        if isinstance(cadence_iters, int) and cadence_iters > 0:
            config["checkpoint_interval"] = max(1, min(100, cadence_iters // 10))

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

    # 5c. U6 phase 1 (S17a-12): an interval exactly equal to the iteration
    # count means the only checkpoint is the completion one — a killed or
    # interrupted run has nothing to resume from. Checked on the PRE-clamp
    # value so it never stacks on 5b (the strictly-> regime is 5b's: it has
    # already warned and clamped — S17a code review). Warn-only, and gated
    # on an EXPLICIT interval (U6 phase 2 / S18-13): the 5a default cadence
    # can legitimately equal iterations (max_iterations=1) and must not
    # nag the user about a value they never set.
    if (
        interval_is_explicit
        and effective_iters is not None
        and isinstance(effective_interval, int)
        and isinstance(effective_iters, int)
        and effective_iters > 0
        and effective_interval == effective_iters
    ):
        sys.stderr.write(
            f"Warning: checkpoint_interval ({effective_interval}) == iterations "
            f"({effective_iters}) — no mid-run checkpoint will exist, so a "
            f"killed or interrupted run cannot be resumed. Set a smaller "
            f"checkpoint_interval (e.g. --config-override "
            f"checkpoint_interval={max(1, effective_iters // 10)}) to keep "
            f"resume points.\n"
        )

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


def _display_score_from_metrics(metrics: dict[str, Any]) -> float | None:
    """Extract the display/ranking score from an OE metrics dict (FR-RUN-052).

    Prefers a numeric ``combined_score`` over the sum-of-numeric-metrics:
    the sum inflates the displayed score whenever auxiliary numeric metrics
    exist alongside ``combined_score`` (U13/#367 display guard). The sum is
    the fallback only when no numeric ``combined_score`` is present
    (population ranking still needs a number); the reserved ``instances_``
    coverage prefix (FR-RUN-053) is excluded from that fallback sum so the
    coverage keys can never inflate it. A metrics dict with no other
    numeric values yields ``None`` — never a crash.

    Booleans are excluded everywhere (``bool`` is an ``int`` subclass).

    Args:
        metrics: The program's metrics dict from an OE checkpoint.

    Returns:
        The score to display/rank by, or ``None`` if no numeric value exists.
    """
    combined = metrics.get("combined_score")
    if isinstance(combined, (int, float)) and not isinstance(combined, bool):
        return float(combined)
    numeric_vals = [
        v
        for k, v in metrics.items()
        if not k.startswith("instances_")
        and isinstance(v, (int, float))
        and not isinstance(v, bool)
    ]
    if numeric_vals:
        return float(sum(numeric_vals))
    return None


def parse_population(checkpoint_dir: Path) -> list[dict[str, Any]]:
    """Parse OE checkpoint programs into a ranked population list.

    Scans ``checkpoint_dir/programs/*.json``, loads each program,
    extracts key fields and computes the display score via
    :func:`_display_score_from_metrics` — a numeric ``combined_score``
    when present, else the sum of numeric metric values (FR-RUN-052).

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
            # Display guard (FR-RUN-052): prefer combined_score over the sum.
            score = _display_score_from_metrics(metrics)
            combined_score = score if score is not None else 0.0

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

    Score extraction mirrors :func:`parse_population` (FR-RUN-052):
    prefers a numeric ``combined_score``, falling back to the sum of
    numeric metric values only when no ``combined_score`` exists.

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

        # Display guard (FR-RUN-052, consistent with parse_population):
        # prefer combined_score, fall back to the numeric-metric sum.
        return _display_score_from_metrics(metrics)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def recover_best_from_checkpoint(run_dir: Path) -> RecoveredProgram:
    """Recover the best program from a run's latest OpenEvolve checkpoint (B7).

    Locates the latest ``oe-output/checkpoints/checkpoint_N/`` in *run_dir*,
    reads ``best_program_id`` from ``metadata.json``, and loads the program's
    ``code`` (and score) from ``programs/{id}.json`` — the state that survives
    a killed/interrupted run before it reaches the normal ``programs/``
    extraction path (FR-RUN-051, DES-005 §7.2).

    Args:
        run_dir: Directory of the interrupted/failed run
            (``.revolver/runs/<run_id>``).

    Returns:
        The recovered best :class:`RecoveredProgram`.

    Raises:
        CheckpointRecoveryError: No checkpoint exists yet (run too short), or
            the checkpoint / best program is missing or unreadable.
    """
    checkpoint = find_latest_checkpoint(run_dir)
    if checkpoint is None:
        raise CheckpointRecoveryError(
            f"No checkpoint found for run '{run_dir.name}'. The run may have "
            "been interrupted before its first checkpoint was written."
        )

    metadata_path = checkpoint / "metadata.json"
    try:
        metadata = _json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckpointRecoveryError(
            f"Failed to read checkpoint metadata at {metadata_path}: {exc}"
        ) from exc

    best_id = metadata.get("best_program_id")
    if not best_id:
        raise CheckpointRecoveryError(
            f"Checkpoint '{checkpoint.name}' has no tracked best program "
            "(no 'best_program_id' in metadata)."
        )

    program_path = checkpoint / "programs" / f"{best_id}.json"
    try:
        program_data = _json.loads(program_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckpointRecoveryError(
            f"Best program '{best_id}' not found or unreadable in checkpoint "
            f"'{checkpoint.name}': {exc}"
        ) from exc

    code = program_data.get("code")
    if not isinstance(code, str) or not code:
        raise CheckpointRecoveryError(
            f"Best program '{best_id}' in checkpoint '{checkpoint.name}' has no usable code."
        )

    # Score: the program's ``combined_score`` metric — the single scalar
    # solutions/populations are ranked by everywhere else. NOT the sum of all
    # numeric metrics: a program carrying ``combined_score`` alongside other
    # numeric metrics (accuracy, latency, ...) would otherwise be over-counted.
    # When the checkpoint predates aggregation and has no ``combined_score``,
    # fall back to ``None`` (unknown) rather than fabricating a summed value.
    metrics = program_data.get("metrics", {})
    score: float | None = None
    if isinstance(metrics, dict):
        raw_score = metrics.get("combined_score")
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
            score = float(raw_score)

    language = program_data.get("language")
    return RecoveredProgram(
        program_id=str(best_id),
        code=code,
        score=score,
        language=language if isinstance(language, str) and language else "python",
    )


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


# ── Wrapper evaluator generation (DES-005 §3) ────────────────────────────────
# Moved from core/run.py in Sprint 013 PR-C (ADR-007 D1): the wrapper is an
# OpenEvolve-facing artifact, so its generation belongs to this backend.
# core/run.py re-exports these names for backward compatibility until S15.

WRAPPER_FILENAME = "_revolver_evaluator.py"
EVALUATOR_FILENAME = "evaluator.py"

# Wrapper template (DES-005 §3.2)
_WRAPPER_TEMPLATE = '''\
"""Auto-generated by Revolver. Do not edit."""
import os
import sys
import sqlite3
import statistics
from pathlib import Path

# Import user's evaluator from the problem version snapshot
sys.path.insert(0, {snapshot_dir!r})
from evaluator import evaluate_instance

# Per-instance timeout in seconds (None = no timeout)
_TIMEOUT_PER_INSTANCE = {timeout_per_instance!r}

# Timed-out instance policy baked at generation time (FR-RUN-054):
# "penalize" (v0.18 default) counts the instance at _TIMEOUT_SCORE in the
# fitness mean; "drop" excludes it (pre-0.18 survivor-mean). Validated at
# the launch point; resume inherits this baked policy with the wrapper.
_ON_TIMEOUT = {on_timeout!r}
_TIMEOUT_SCORE = {timeout_score!r}


def _call_evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    """Call evaluate_instance with optional per-instance timeout guard."""
    if _TIMEOUT_PER_INSTANCE is None:
        return evaluate_instance(program_path, instance_path)

    import multiprocessing
    import queue as _queue_mod

    result_queue: multiprocessing.Queue[dict[str, float] | Exception] = multiprocessing.Queue()

    def _target() -> None:
        try:
            result_queue.put(evaluate_instance(program_path, instance_path))
        except Exception as exc:
            result_queue.put(exc)

    proc = multiprocessing.Process(target=_target)
    proc.start()
    proc.join(_TIMEOUT_PER_INSTANCE)
    if proc.is_alive():
        proc.kill()
        proc.join()
        raise TimeoutError(
            f"evaluate_instance timed out after {{_TIMEOUT_PER_INSTANCE}}s"
        )
    try:
        result = result_queue.get_nowait()
    except _queue_mod.Empty:
        raise RuntimeError("evaluate_instance process ended without returning a result")
    if isinstance(result, Exception):
        raise result
    return result


def evaluate(program_path: str) -> dict[str, float]:
    instance_path = os.environ.get("REVOLVER_INSTANCE_PATH")

    if instance_path:
        # Single-instance mode (revolver eval / revolver benchmark)
        return _call_evaluate_instance(program_path, instance_path)

    # Aggregated mode (OpenEvolve training)
    dataset_dir = os.environ["REVOLVER_DATASET_DIR"]
    instances = sorted(
        p for p in Path(dataset_dir).iterdir()
        if not p.name.startswith(".")
    )

    all_metrics: list[dict[str, float]] = []
    valid = 0  # instances that genuinely returned metrics (FR-RUN-053)
    for inst in instances:
        try:
            metrics = _call_evaluate_instance(program_path, str(inst))
            all_metrics.append(metrics)
            valid += 1
            _log_instance(inst.name, metrics)
        except TimeoutError as _te:
            # Distinct timeout branch (FR-RUN-053): record the timed-out
            # instance on the side-channel so it stays visible per instance.
            print(f"[revolver] timeout for {{inst.name}}: {{_te}}", file=sys.stderr)
            _log_timeout(inst.name)
            if _ON_TIMEOUT == "penalize":
                # FR-RUN-054 (v0.18 default): a timed-out instance
                # contributes the penalty score to the fitness mean
                # instead of silently vanishing from it.
                all_metrics.append({{"combined_score": _TIMEOUT_SCORE}})
            # "drop": fall through — survivor-mean (pre-0.18 behavior).
        except Exception as _e:
            print(f"[revolver] evaluation failed for {{inst.name}}: {{_e}}", file=sys.stderr)

    if not all_metrics:
        return {{
            "combined_score": 0.0,
            "instances_valid": 0.0,
            "instances_total": float(len(instances)),
        }}

    # Numeric guard (B1 / FR-EVL-021): a user evaluate_instance may emit
    # non-numeric fields (e.g. {{"error": "boom"}}) alongside numeric metrics.
    # Aggregation must skip those rather than crash statistics.mean on a str,
    # so filter to real numbers (bool is an int subclass -> exclude it).
    def _is_number(x) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    combined_vals = [
        m["combined_score"]
        for m in all_metrics
        if "combined_score" in m and _is_number(m["combined_score"])
    ]
    combined = statistics.mean(combined_vals) if combined_vals else 0.0
    result: dict[str, float] = {{"combined_score": combined}}

    # Include other metrics as aggregated means, dropping non-numeric values.
    # The reserved "instances_" coverage prefix is NEVER averaged into the
    # metrics (FR-RUN-053; read-path counterpart: FR-EVL-021 as amended).
    all_keys: set[str] = set()
    for m in all_metrics:
        all_keys.update(m.keys())
    for key in sorted(all_keys):
        if key != "combined_score" and not key.startswith("instances_"):
            vals = [m[key] for m in all_metrics if key in m and _is_number(m[key])]
            if vals:
                result[key] = statistics.mean(vals)

    # Coverage keys: metadata, not fitness (FR-RUN-053).
    result["instances_valid"] = float(valid)
    result["instances_total"] = float(len(instances))
    return result


def _log_instance(instance_id: str, metrics: dict[str, float]) -> None:
    """Optional: log per-instance results to SQLite side-channel."""
    log_path = os.environ.get("REVOLVER_INSTANCE_LOG")
    if not log_path:
        return
    try:
        conn = sqlite3.connect(log_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS instance_log "
            "(instance_id TEXT, metric TEXT, value REAL, pid INTEGER)"
        )
        for metric, value in metrics.items():
            conn.execute(
                "INSERT INTO instance_log VALUES (?, ?, ?, ?)",
                (instance_id, metric, value, os.getpid()),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Side-channel is best-effort


def _log_timeout(instance_id: str) -> None:
    """Record a timed-out instance on the SQLite side-channel (FR-RUN-053).

    Same best-effort channel as _log_instance, with a status marker row
    (metric "instances_timeout", value 1.0 — reserved "instances_" prefix,
    never aggregated) so timed-out instances stay visible per instance
    regardless of how the fitness mean treats them.
    """
    log_path = os.environ.get("REVOLVER_INSTANCE_LOG")
    if not log_path:
        return
    try:
        conn = sqlite3.connect(log_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS instance_log "
            "(instance_id TEXT, metric TEXT, value REAL, pid INTEGER)"
        )
        conn.execute(
            "INSERT INTO instance_log VALUES (?, ?, ?, ?)",
            (instance_id, "instances_timeout", 1.0, os.getpid()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Side-channel is best-effort
'''


def _load_evaluator_module(path: Path) -> ModuleType:
    """Load an evaluator Python file as a module for function detection.

    Unlike ``infra.evaluator_loader.load_evaluator()``, this function
    does **not** require ``evaluate()`` to be present. It loads the module
    purely for introspection of which functions are available.

    Args:
        path: Path to the evaluator ``.py`` file.

    Returns:
        The imported module.

    Raises:
        EvaluatorLoadError: If the module fails to import.
    """
    spec = importlib.util.spec_from_file_location(
        f"_revolver_eval_detect_{path.stem}_{id(path)}", path
    )
    if spec is None or spec.loader is None:
        raise EvaluatorLoadError(f"Cannot load evaluator from {path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise EvaluatorLoadError(f"Failed to import evaluator: {exc}") from exc

    return module


def generate_wrapper(
    snapshot_dir: Path,
    output_dir: Path,
    timeout_per_instance: float | None = None,
    on_timeout: str = "penalize",
    timeout_score: float = 0.0,
) -> Path:
    """Generate the wrapper evaluator file for OpenEvolve.

    Detection order (DES-005 D-005-a):
        1. If ``evaluate()`` exists in the user's evaluator -> legacy mode,
           copy the evaluator file directly as ``_revolver_evaluator.py``.
        2. Else if ``evaluate_instance()`` exists -> generate a wrapper that
           calls ``evaluate_instance()`` with instance iteration.
        3. Neither -> raise ``EvaluatorLoadError``.

    Args:
        snapshot_dir: Path to the problem version snapshot directory
            (e.g., ``.revolver/problem/<tag>/``).
        output_dir: Path to the run directory
            (e.g., ``.revolver/runs/<id>/``).
        timeout_per_instance: Optional per-instance timeout in seconds.
            When set, each ``evaluate_instance()`` call is guarded by a
            ``multiprocessing.Process`` with ``.join(timeout)`` + ``.kill()``.
            Defaults to ``None`` (no timeout).
        on_timeout: Timed-out instance policy baked into the wrapper
            (FR-RUN-054): ``"penalize"`` (default, v0.18 fitness-landscape
            flip) counts the instance at *timeout_score* in the fitness
            mean; ``"drop"`` excludes it (pre-0.18 survivor-mean).
            Validated upstream at the shared launch point in ``core.run``.
        timeout_score: Finite penalty score contributed by a timed-out
            instance under ``on_timeout="penalize"``. Defaults to ``0.0``.

    Returns:
        Path to the generated (or copied) ``_revolver_evaluator.py``.

    Raises:
        EvaluatorLoadError: If the evaluator file is missing or has
            neither ``evaluate()`` nor ``evaluate_instance()``.
        FileNotFoundError: If the evaluator file does not exist.
    """
    evaluator_path = snapshot_dir / EVALUATOR_FILENAME
    if not evaluator_path.exists():
        raise FileNotFoundError(f"Evaluator file not found: {evaluator_path}")

    module = _load_evaluator_module(evaluator_path)
    output_path = output_dir / WRAPPER_FILENAME

    has_evaluate = hasattr(module, "evaluate") and callable(module.evaluate)
    has_evaluate_instance = hasattr(module, "evaluate_instance") and callable(
        module.evaluate_instance
    )

    if has_evaluate:
        if has_evaluate_instance:
            print(
                "Warning: evaluator defines both evaluate() and evaluate_instance(). "
                "Using evaluate() (legacy mode). If evaluate() depends on "
                "REVOLVER_INSTANCE_PATH, it will fail during OpenEvolve runs. "
                "Consider removing evaluate().",
                file=sys.stderr,
            )
        # Legacy mode: copy evaluator as-is
        shutil.copy2(evaluator_path, output_path)
        return output_path

    if has_evaluate_instance:
        # Generate wrapper from template
        wrapper_code = _WRAPPER_TEMPLATE.format(
            snapshot_dir=str(snapshot_dir),
            timeout_per_instance=timeout_per_instance,
            on_timeout=on_timeout,
            timeout_score=timeout_score,
        )
        output_path.write_text(wrapper_code)
        return output_path

    raise EvaluatorLoadError(
        "Evaluator must define either 'evaluate(program_path)' or "
        "'evaluate_instance(program_path, instance_path)'"
    )


# ── Project-init config template (S13-13, FR-PRJ-005) ────────────────────────
# Moved from revolver.core.project (template ownership inverted per ADR-007:
# the backend serves its own config.yaml scaffold via config_template()).
# Originally byte-identical to the pre-S13 core/project template; reworked in
# S16a (A6/#318, schema-correct keys) and S18 (U13/#367, evaluation.on_timeout
# policy). The golden copy lives in tests/test_project_integration.py.

_CONFIG_TEMPLATE = """\
# OpenEvolve configuration — edit to match your problem.
#
# See OpenEvolve documentation for all available options.
# Revolver passes this file to OpenEvolve via --config.
# Keys here use OpenEvolve's own schema; a freshly-scaffolded project
# validates clean (zero warnings) at `problem version create`.

# Number of evolutionary iterations (generations).
max_iterations: 10

# LLM sampling settings.
llm:
  temperature: 0.8
  max_tokens: 4096

# MAP-Elites database settings.
# Population size — number of candidate programs kept in the archive.
# OpenEvolve defaults to 1000; uncomment to shrink it for quick experiments.
# feature_dimensions / feature_bins are the MAP-Elites feature axes and the
# per-axis bin counts (the archive grid); uncomment to customise the grid.
# database:
#   population_size: 10
#   feature_dimensions: ["complexity", "diversity"]
#   feature_bins: 10

# Evaluation settings (Revolver-specific; not part of the OpenEvolve schema).
evaluation:
  timeout_per_instance: 30  # seconds
  # Timed-out instance policy (v0.18): "penalize" counts the instance at
  # timeout_score in the fitness mean; "drop" excludes it (pre-0.18
  # survivor-mean). Note: with a negative timeout_score floor, lower
  # scores are the penalty — mind negative-is-good metrics.
  on_timeout: penalize
  timeout_score: 0.0
"""


# ── EvolutionBackend adapter (ADR-007 D1) ─────────────────────────────────────


class OpenEvolveBackend:
    """``EvolutionBackend`` protocol adapter over the OpenEvolve integration.

    Mechanical wrapping of the module-level functions above behind the
    protocol defined in :mod:`revolver.infra.backends.base`. Since the
    orchestration switch (S13 PR-C), ``core.run`` drives evolution through
    this adapter (the deprecated ``revolver.infra.openevolve`` re-export
    shim was removed in S15).
    """

    name: str = "openevolve"
    # Engine output directory name inside a run dir (ADR-007, S14-05).
    default_output_subdir: str = "oe-output"
    # Wrapper evaluator filename inside a run dir (S14-13: the resume
    # orchestrator copies the parent's wrapper by this backend-owned name).
    wrapper_filename: str = WRAPPER_FILENAME

    def capabilities(self) -> BackendCapabilities:
        """Return the OpenEvolve capability matrix (ADR-007)."""
        return BackendCapabilities(
            global_seed=True,
            map_elites_cells=True,
            native_cost_tracking=False,
            multi_language=False,
            ensemble_model="weighted",
            top_n_extraction=False,
            selection_strategies=("fixed",),
            per_member_reasoning_effort=True,
        )

    def is_available(self) -> tuple[bool, str | None]:
        """Report whether the ``openevolve`` package is installed."""
        if importlib.util.find_spec("openevolve") is None:
            return (False, "Install with: pip install 'revolver[openevolve]'")
        return (True, None)

    def config_template(self) -> str:
        """Return the OE-shaped ``config.yaml`` scaffold (project init)."""
        return _CONFIG_TEMPLATE

    def validate_config(self, config: Path | dict[str, Any]) -> list[str]:
        """Validate a problem config against the OpenEvolve Config schema."""
        return validate_oe_config(config)

    def build_config(self, spec: BackendRunSpec) -> dict[str, Any]:
        """Build the merged OpenEvolve config dict from *spec*."""
        return build_config(
            problem_config=spec.snapshot_dir / "config.yaml",
            llm=spec.llm,
            iterations=spec.iterations,
            config_overrides=spec.config_overrides,
            problem_description=spec.problem_description,
            temperature=spec.temperature,
            parallel=spec.parallel,
            rewrite_mode=spec.rewrite_mode,
            ensemble=spec.ensemble,
            conn=spec.conn,
            selection=spec.selection,
            llm_weight_overrides=spec.llm_weight_overrides,
        )

    def resolved_config(
        self,
        config: dict[str, Any],
        config_overrides: dict[str, Any] | None = None,
    ) -> ResolvedConfig:
        """Extract key parameters from a merged config for dry-run display.

        Backend-neutral fields (ADR-007 D4) are mapped from their
        OpenEvolve locations; OE-exclusive parameters go into
        ``backend_extras`` (only when present, so the generic dry-run
        renderer never prints empty values).
        """
        db_section = config.get("database", {})
        if not isinstance(db_section, dict):
            db_section = {}
        llm_section = config.get("llm", {})
        if not isinstance(llm_section, dict):
            llm_section = {}
        eval_section = config.get("evaluator", {})
        if not isinstance(eval_section, dict):
            eval_section = {}

        # Extract ensemble llm.models array when present
        llm_models: list[dict[str, Any]] | None = None
        raw_models = llm_section.get("models")
        if isinstance(raw_models, list) and raw_models:
            llm_models = raw_models

        # OE-exclusive parameters (ADR-007 D4): keep only the keys that
        # are actually set so the dry-run display stays clean.
        backend_extras: dict[str, Any] = {}
        for key, value in (
            ("checkpoint_interval", config.get("checkpoint_interval")),
            ("feature_dimensions", db_section.get("feature_dimensions")),
            ("feature_bins", db_section.get("feature_bins")),
            ("parallel_evaluations", eval_section.get("parallel_evaluations")),
            ("diff_based_evolution", config.get("diff_based_evolution")),
            ("max_code_length", config.get("max_code_length")),
        ):
            if value is not None:
                backend_extras[key] = value

        return ResolvedConfig(
            backend=self.name,
            iterations=config.get("max_iterations"),
            num_islands=db_section.get("num_islands"),
            temperature=llm_section.get("temperature"),
            language=config.get("language"),
            llm_models=llm_models,
            config_overrides=config_overrides if config_overrides else None,
            backend_extras=backend_extras,
        )

    def generate_wrapper(self, spec: BackendRunSpec) -> Path:
        """Generate the wrapper evaluator into the run directory."""
        run_dir = self._require_run_dir(spec)
        return generate_wrapper(
            spec.snapshot_dir,
            run_dir,
            timeout_per_instance=spec.timeout_per_instance,
            on_timeout=spec.on_timeout,
            timeout_score=spec.timeout_score,
        )

    def validate_seed_metrics(
        self,
        config: dict[str, Any],
        seed_metrics: dict[str, float] | None,
    ) -> None:
        """Fail fast when ``database.feature_dimensions`` names a metric the
        seed does not produce (U8 / FR-RUN-056, DES-005 §4.4).

        Every non-builtin dimension declared in *config* must be present and
        numeric in the seed's pre-flight metrics — otherwise the run would
        only crash at the engine's seed-add, after the run record, wrapper,
        and lock already exist. The :data:`OE_BUILTIN_FEATURE_DIMENSIONS`
        (``complexity``/``diversity``/``combined_score``) are computed inside
        OpenEvolve and never required. A non-float-coercible metric already
        fails pydantic validation inside ``run_instance``, so the live case
        here is the *absent* metric; the numeric check is a defensive belt.

        Raises:
            ValidationError: Naming the missing dimension and listing the
                available seed metrics (exit 1, before iteration 0).
        """
        db_section = config.get("database")
        if not isinstance(db_section, dict):
            return
        dimensions = db_section.get("feature_dimensions")
        if not isinstance(dimensions, list):
            return
        metrics = seed_metrics if isinstance(seed_metrics, dict) else {}
        for dim in dimensions:
            if not isinstance(dim, str) or dim in OE_BUILTIN_FEATURE_DIMENSIONS:
                continue
            value = metrics.get(dim)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                continue
            available = ", ".join(sorted(metrics)) if metrics else "none"
            raise ValidationError(
                f"Feature dimension '{dim}' not found in seed metrics. "
                f"Available metrics: {available}. Either make the evaluator "
                f"return a numeric '{dim}' metric or remove it from "
                f"database.feature_dimensions."
            )

    def launch(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Launch a fresh OpenEvolve run."""
        _run_dir, initial_program, evaluator, output_dir = self._runner_inputs(spec)
        output_dir.mkdir(exist_ok=True)
        config["output_dir"] = str(output_dir)
        # Iterations are resolved by the single owner (core.run, S14-05),
        # which defaults to core.run.DEFAULT_ITERATIONS, into spec.iterations
        # before this call. The dead engine-config fallback was removed in
        # S15-16; guard the contract instead of silently defaulting.
        if spec.iterations is None:  # pragma: no cover - core.run guarantees it
            raise ValidationError(
                "BackendRunSpec.iterations must be resolved before launch "
                "(core.run is the single owner — S14-05)."
            )
        iterations = spec.iterations
        runner = OpenEvolveRunner(
            initial_program=initial_program,
            evaluator=evaluator,
            config=config,
            output_dir=output_dir,
        )
        output = runner.run(iterations=iterations, on_progress=on_progress)
        return BackendRunResult(
            best_score=output.best_score,
            best_program=output.best_program,
            output_dir=output.output_dir,
        )

    def resume_precheck(self, parent_run_dir: Path) -> None:
        """No-op resume precheck (S16-10).

        OpenEvolve has no backend-specific resume precondition to enforce
        here: the orchestrator stages the parent checkpoint and raises if it
        is missing (``core.run.resume_run()``), so this hook inherits the
        protocol's default no-op behaviour.
        """
        return None

    def recover_best_from_checkpoint(self, run_dir: Path) -> RecoveredProgram:
        """Recover the best program from the run's latest checkpoint (B7).

        Delegates to the module-level :func:`recover_best_from_checkpoint`,
        which reads ``oe-output/checkpoints/checkpoint_N/`` (FR-RUN-051,
        DES-005 §7.2). Raises
        :class:`~revolver.core.exceptions.CheckpointRecoveryError` when no
        usable checkpoint exists yet.
        """
        return recover_best_from_checkpoint(run_dir)

    def extract_ranked_program(
        self,
        run_dir: Path,
        rank: int | None = None,
        program_id: str | None = None,
    ) -> RankedProgram:
        """Explicitly unsupported: OE has no reliable top-N store (FR-SOL-021).

        ``top_n_extraction=False`` is a conscious v0.18 deferral (ADR-007
        amendment, #299): only checkpointed populations are recoverable
        (granularity depends on ``checkpoint_interval``), and OE ranking
        must first ride on ``combined_score`` (post-U13, FR-RUN-052).
        Callers are expected to consult :meth:`capabilities` first — the
        ``solution extract`` gate does — so this body is defense in depth.
        """
        raise ValidationError(f"Top-N extraction is not supported on backend '{self.name}'.")

    def resume(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        parent_run_dir: Path,
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Resume from the parent run's latest checkpoint (FR-RUN-024).

        OpenEvolve resume semantics (ADR-007 D1): the parent's latest
        ``checkpoint_N`` directory is copied to ``<run_dir>/oe-checkpoint``
        (unless the orchestrator already staged it there) and fed to the
        controller as ``checkpoint_path``. OpenEvolve writes fresh
        checkpoints to ``oe-output/checkpoints/`` as usual.

        Ownership contract (PR-C): the orchestrator owns the fail-fast
        staging precheck *before* inserting the run record (today's
        ``core/run.py`` behavior); the copy below is a fallback only, not
        a parallel implementation. ``spec.iterations`` must already carry
        the parent-run fallback (FR-RUN-024) — the snapshot-config default
        used here is a last resort, not equivalent to it.
        """
        run_dir, initial_program, evaluator, output_dir = self._runner_inputs(spec)
        checkpoint = run_dir / "oe-checkpoint"
        if not checkpoint.exists():
            parent_checkpoint = find_latest_checkpoint(parent_run_dir)
            if parent_checkpoint is None:
                raise RevolverError(
                    f"No checkpoint found in parent run '{parent_run_dir.name}'. "
                    "The run may have been too short to produce a checkpoint."
                )
            from revolver.infra.store import copy_run_file

            copy_run_file(parent_checkpoint, checkpoint)

        output_dir.mkdir(exist_ok=True)
        config["output_dir"] = str(output_dir)
        # Iterations are resolved by the single owner (core.run, S14-05),
        # which defaults to core.run.DEFAULT_ITERATIONS, into spec.iterations
        # before this call. The dead engine-config fallback was removed in
        # S15-16; guard the contract instead of silently defaulting.
        if spec.iterations is None:  # pragma: no cover - core.run guarantees it
            raise ValidationError(
                "BackendRunSpec.iterations must be resolved before launch "
                "(core.run is the single owner — S14-05)."
            )
        iterations = spec.iterations
        runner = OpenEvolveRunner(
            initial_program=initial_program,
            evaluator=evaluator,
            config=config,
            output_dir=output_dir,
        )
        output = runner.run(
            iterations=iterations,
            checkpoint=checkpoint,
            on_progress=on_progress,
        )
        return BackendRunResult(
            best_score=output.best_score,
            best_program=output.best_program,
            output_dir=output.output_dir,
        )

    def read_progress(self, run_dir: Path) -> tuple[int | None, float | None]:
        """Live-progress read from the latest checkpoint (run status)."""
        checkpoint = find_latest_checkpoint(run_dir)
        if checkpoint is None:
            return (None, None)
        return (
            count_valid_programs(checkpoint),
            read_checkpoint_best_score(checkpoint),
        )

    def parse_population(self, run_dir: Path) -> list[dict[str, Any]] | None:
        """Parse the ranked population from the latest checkpoint."""
        checkpoint = find_latest_checkpoint(run_dir)
        if checkpoint is None:
            return None
        return parse_population(checkpoint)

    def count_valid(self, run_dir: Path) -> int | None:
        """Count valid programs (latest checkpoint first, oe-output fallback)."""
        valid: int | None = None
        checkpoint = find_latest_checkpoint(run_dir)
        if checkpoint is not None:
            valid = count_valid_programs(checkpoint)
        oe_output_dir = run_dir / "oe-output"
        if valid is None and oe_output_dir.exists():
            valid = count_valid_programs(oe_output_dir)
        return valid

    def count_total(self, run_dir: Path) -> int | None:
        """Return ``None`` — OpenEvolve has no cheap full program-store total.

        A complete total would require parsing every checkpoint, so
        ``run info`` shows ``programs_in_db`` only on backends with a
        complete program store (UX-4 / S16-19).
        """
        return None

    def count_evolved_children(self, run_dir: Path) -> int | None:
        """Return ``None`` — the checkpoint does not distinguish the initial
        program from evolved children, so the unproductive-run check
        (backlog #302) is skipped on OpenEvolve, which keeps its existing
        ratio-based status determination.
        """
        return None

    def wants_http_proxy(self) -> bool:
        """OpenEvolve tokens are measured via the HTTP proxy (ADR-007 D2)."""
        return True

    def collect_token_usage(self, run_dir: Path) -> TokenUsage | None:
        """OpenEvolve has no engine-native token accounting.

        Token usage comes from the HTTP ``TokenCountingProxy``, whose
        lifecycle stays owned by ``core.run`` until the PR-C switch.
        """
        return None

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _require_run_dir(spec: BackendRunSpec) -> Path:
        """Return ``spec.run_dir``, raising when missing."""
        if spec.run_dir is None:
            raise ValidationError("BackendRunSpec.run_dir is required for this operation.")
        return spec.run_dir

    def _runner_inputs(self, spec: BackendRunSpec) -> tuple[Path, Path, Path, Path]:
        """Resolve ``(run_dir, initial_program, evaluator, output_dir)``."""
        run_dir = self._require_run_dir(spec)
        initial_program = spec.snapshot_dir / "initial_program.py"
        if spec.wrapper_path is not None:
            evaluator = spec.wrapper_path
        else:
            # Conventional wrapper location written by generate_wrapper().
            evaluator = run_dir / WRAPPER_FILENAME
        output_dir = run_dir / "oe-output"
        return run_dir, initial_program, evaluator, output_dir


__all__ = [
    "EVALUATOR_FILENAME",
    "REVOLVER_KEYS",
    "WRAPPER_FILENAME",
    "OpenEvolveBackend",
    "OpenEvolveRunner",
    "ProgressInfo",
    "RunOutput",
    "build_config",
    "count_valid_programs",
    "find_latest_checkpoint",
    "generate_wrapper",
    "parse_population",
    "read_checkpoint_best_score",
    "resolve_api_keys",
    "revolver_env",
    "validate_oe_config",
]
