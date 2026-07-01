"""ShinkaEvolve backend — config + engine tiers (ADR-007, Sprint 014).

Implements the ``EvolutionBackend`` protocol for ShinkaEvolve:

Config tier (PR-B):

- :meth:`ShinkaBackend.is_available` — real ``import shinka.core`` probe;
- :meth:`ShinkaBackend.config_template` — Shinka-flavored ``config.yaml``
  scaffold (``evo_config``/``db_config``/``job_config`` sections);
- :meth:`ShinkaBackend.validate_config` — dataclass-key check against the
  ShinkaEvolve config dataclasses (graceful when shinka is absent);
- :meth:`ShinkaBackend.build_config` — projects a
  :class:`~revolver.infra.backends.base.BackendRunSpec` into the nested
  ``evo_config``/``db_config``/``job_config`` dict, including the LLM
  registry projection (ADR-007 D5);
- :meth:`ShinkaBackend.resolved_config` — neutral
  :class:`~revolver.models.run.ResolvedConfig` for dry-run display;
- :meth:`ShinkaBackend.generate_wrapper` — writes the Shinka CLI evaluator
  script (``--program_path``/``--results_dir`` argv contract) adapting the
  user's ``evaluate_instance()`` over the dataset (R4 risk materializer).

Engine tier (PR-C, S14-10..13):

- :meth:`ShinkaBackend.launch` — exports the ``llm_env`` map, constructs
  ``ShinkaEvolveRunner`` from the built config, runs the evolution, and
  materializes the best ranked program(s) into ``<results_dir>/best/``;
- :meth:`ShinkaBackend.resume` — clone-resume: copies the parent run's
  ``shinka-output/`` into the new run dir and continues evolution on the
  clone, leaving the parent untouched (S16-11, spike S16-09 GO);
- :meth:`ShinkaBackend.read_progress` / :meth:`ShinkaBackend.parse_population`
  / :meth:`ShinkaBackend.count_valid` — read ``programs.sqlite``;
- :meth:`ShinkaBackend.collect_token_usage` — engine-native token/cost
  accounting from per-program ``metadata`` JSON (ADR-007 D2).

Traceable to: ADR-007 (decisions D1/D2/D4/D5/D6), DES-005 §14.1,
DES-006 §1.3, FR-RUN-047/048, sprint-014 S14-07..13.
"""

from __future__ import annotations

from collections.abc import Callable
import contextlib
import dataclasses
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Any

import yaml

from revolver.core.exceptions import (
    EvaluatorLoadError,
    ExternalError,
    RecoveryNotSupportedError,
    RevolverError,
    ValidationError,
)
from revolver.infra.backends.base import (
    BackendCapabilities,
    BackendRunResult,
    BackendRunSpec,
    BackendUnavailableError,
    ChildProcessReaperMixin,
    ProgressInfo,
    RecoveredProgram,
)
from revolver.infra.backends.openevolve import (
    # Backend-neutral config plumbing shared with the OpenEvolve adapter.
    # Promotion to a shared module is deferred to S15 (shim removal).
    SYSTEM_PROMPT_TEMPLATE,
    _load_evaluator_module,
    _parse_value,
    _set_nested,
    revolver_env,
)
from revolver.models.llm import EnsembleEntry, EnsembleMember, LLMEntry
from revolver.models.run import ResolvedConfig, TokenUsage

_INSTALL_HINT = "Install with: pip install 'revolver[shinka]'"

# Filename of the generated Shinka CLI evaluator inside a run dir.
SHINKA_WRAPPER_FILENAME = "_shinka_evaluator.py"

# ShinkaEvolve's program database inside its results dir (dbase.py 0.0.7).
SHINKA_PROGRAMS_DB = "programs.sqlite"

# Placeholder API key exported for key-less local OpenAI-compatible
# endpoints — Shinka's resolve_local_openai_api_key() raises when a named
# api_key_env is unset (mirrors OE's "ollama" placeholder key).
_LOCAL_API_KEY_PLACEHOLDER = "ollama"

# Number of ranked programs materialized into <results_dir>/best/ after a
# run. Mirrors OpenEvolve's output (a single best/best_program.py) so the
# orchestrator's program collection behaves identically across backends;
# top-N extraction (capabilities().top_n_extraction) is an S15 extension.
_BEST_PROGRAMS_COUNT = 1

# Sane LLM-setting defaults for the Shinka path (Sprint 015 Scope B, #301).
# ShinkaEvolve's own defaults are tuned for cheap non-thinking models and
# silently break thinking-capable ones:
#   - llm_kwargs.max_tokens defaults to 4096 → thinking models exhaust the
#     budget on reasoning and return ``None`` content (revolver task #120);
#     ShinkaEvolve's example configs use 16384.
#   - EvolutionConfig.max_patch_attempts defaults to 1 → a single malformed
#     patch loses the whole generation; ShinkaEvolve's examples use 10.
_SHINKA_DEFAULT_MAX_TOKENS = 16384
_SHINKA_DEFAULT_MAX_PATCH_ATTEMPTS = 10

# ── Multi-LLM ensemble → bandit mapping (S17-19/20/21, ADR-007 A2/A5) ─────────
#
# ShinkaEvolve picks the *model* with a bandit; ``llm_dynamic_selection`` names
# the sampler and ``llm_dynamic_selection_kwargs`` is spread VERBATIM into that
# sampler's constructor (verified async_runner.py 0.0.7 L361-383 —
# ``<Sampler>(arm_names=llm_models, **llm_dynamic_selection_kwargs)``). A key the
# selected sampler's ``__init__`` does not accept therefore raises ``TypeError``
# at launch (AsymmetricUCB/ThompsonSampler have no ``**kwargs``), so Revolver
# must route kwargs per sampler and never send a union.
#
# Default selection strategy when ``--selection`` is unset: ``fixed`` keeps the
# S14 single-LLM path a one-member FixedSampler case (zero behaviour change).
_SHINKA_DEFAULT_SELECTION = "fixed"

# ``ucb`` and ``ucb1`` are aliases for the same ``AsymmetricUCB`` class
# (verified: no separate ucb1 class — v017 research §0 FACT B / §1).
_SHINKA_ADAPTIVE_SELECTIONS = frozenset({"ucb", "ucb1", "thompson"})

# Per-sampler accepted ``selection_kwargs`` keys (verified against
# shinka/llm/prioritization.py 0.0.7 constructor signatures). ``prior_probs`` is
# injected by build_config itself under ``fixed`` (weight vector) — it is NOT in
# the user-facing allow-list. Any kwarg not listed for the selected sampler is
# dropped with a warning rather than spread (would ``TypeError`` under
# ucb/ucb1/thompson, be silently ignored under fixed).
_SHINKA_SAMPLER_KWARG_KEYS: dict[str, frozenset[str]] = {
    "fixed": frozenset(),
    "ucb": frozenset(
        {
            "exploration_coef",
            "epsilon",
            "auto_decay",
            "shift_by_baseline",
            "shift_by_parent",
            "adaptive_scale",
            "asymmetric_scaling",
            "exponential_base",
            "cost_aware_coef",
            "cost_exploration_coef",
            "cost_power",
            "cost_ref_percentile",
        }
    ),
    "thompson": frozenset(
        {
            "epsilon",
            "prior_alpha",
            "prior_beta",
            "auto_decay",
            "shift_by_baseline",
            "shift_by_parent",
            "adaptive_scale",
            "asymmetric_scaling",
            "exponential_base",
        }
    ),
}
# ``ucb1`` is a bandit alias of ``ucb`` — same accepted-kwarg set.
_SHINKA_SAMPLER_KWARG_KEYS["ucb1"] = _SHINKA_SAMPLER_KWARG_KEYS["ucb"]

# Revolver's own default for the cost-aware coefficient on ucb/ucb1: 0 (flat-rate
# / bridge case), NOT ShinkaEvolve's own 0.5. Inert when per-model cost is
# undifferentiated (all-local/bridge) but must default correctly (M4, ADR-007 A5).
_SHINKA_DEFAULT_COST_AWARE_COEF = 0.0

# Total order over reasoning-effort levels (lowest → highest). ShinkaEvolve has
# a single global reasoning_efforts pool (FACT A: no per-member effort), so when
# ensemble members disagree Revolver picks the *highest* effort under this order
# — never under-thinking — and warns (S17-27, ADR-007 A3.2). Kept in sync with
# ``revolver.core.llm._REASONING_EFFORT_LEVELS``.
_REASONING_EFFORT_ORDER: tuple[str, ...] = ("min", "low", "medium", "high", "max")

# Default env var name synthesized for local OpenAI-compatible endpoints
# when the registry entry has no api_key_env (ADR-007 D5). launch()
# exports a placeholder value when this variable is unset — Shinka
# raises on a named-but-unset api_key_env, mirroring OE's "ollama" key.
_DEFAULT_LOCAL_API_KEY_ENV = "OLLAMA_API_KEY"

# Provider-standard env vars read by Shinka's native SDK clients
# (shinka/llm/client.py — ADR-007 D5). launch() exports each target
# var from the Revolver-resolved source before starting the engine.
_PROVIDER_ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
}

# Top-level config sections owned by Revolver, not ShinkaEvolve. They are
# tolerated by validate_config() and ignored by the engine projection:
# - evaluation: wrapper settings (timeout_per_instance);
# - output_dir: injected by the orchestrator (DES-005 §14.1);
# - llm_env: env-var export map produced by build_config() (D5).
_REVOLVER_SECTIONS = frozenset({"evaluation", "output_dir", "llm_env"})

# Shinka config sections and their backing dataclass import paths.
_SECTION_DATACLASSES: dict[str, tuple[str, str]] = {
    "evo_config": ("shinka.core", "EvolutionConfig"),
    "db_config": ("shinka.database", "DatabaseConfig"),
    "job_config": ("shinka.launch", "LocalJobConfig"),
}


# ── Project-init config template (S14-07, FR-PRJ-005) ────────────────────────

_CONFIG_TEMPLATE = """\
# ShinkaEvolve configuration — edit to match your problem.
#
# Sections map 1:1 to ShinkaEvolve dataclasses:
#   evo_config -> shinka.core.EvolutionConfig
#   db_config  -> shinka.database.DatabaseConfig
#   job_config -> shinka.launch.LocalJobConfig
# The `evaluation` section is Revolver-specific (not passed to ShinkaEvolve).
# Revolver injects run-time settings (LLM model, iterations, results_dir,
# evaluator script) when launching `revolver run --backend shinka`.

evo_config:
  # Number of evolution generations (overridden by --iterations).
  num_generations: 10
  # Patch generation modes sampled by the engine (diff edits / full rewrites).
  patch_types:
    - diff
    - full
  # Sampling probabilities, one per patch type.
  patch_type_probs:
    - 0.6
    - 0.4
  # Language of the evolved program (Revolver supports python in S14).
  language: python
  # Hard cap on LLM API spend in USD (null = no cap).
  max_api_costs: null
  # Max LLM patch attempts per generation before giving up. Shinka's own
  # default is 1 → one malformed patch loses the generation. Revolver
  # defaults to 10 (matches ShinkaEvolve's example configs).
  max_patch_attempts: 10
  # Per-query LLM sampling settings (ShinkaEvolve llm_kwargs).
  llm_kwargs:
    # Output token budget. Revolver defaults to 16384 (Shinka's 4096 starves
    # thinking-capable models, which then return empty content). Raising this
    # increases thinking-token spend.
    max_tokens: 16384
    # Reasoning effort for thinking-capable models — the primary cost lever
    # (lower effort = fewer billed thinking tokens). Provider-specific values
    # (e.g. "low"/"medium"/"high"); leave unset for the provider default.
    # Uncomment to control thinking-token spend:
    # reasoning_efforts: low

db_config:
  # Number of evolution islands.
  num_islands: 2
  # Size of the elite program archive.
  archive_size: 40
  # Migrate programs across islands every N generations.
  migration_interval: 10

job_config:
  # Local evaluation job settings (SLURM is not supported by Revolver).
  # Conda env to activate for evaluation jobs (null = current env).
  conda_env: null

# Evaluation settings (Revolver-specific).
evaluation:
  timeout_per_instance: 30  # seconds
"""


# ── Wrapper evaluator template (S14-09, DES-006 §1.3) ────────────────────────
# The generated script is the Shinka CLI evaluator: Shinka's local job
# scheduler invokes it as
#   python <script> --program_path <evolved.py> --results_dir <dir>
# and reads metrics.json / correct.json from results_dir. When shinka is
# importable the script delegates the harness work to run_shinka_eval();
# otherwise a standalone fallback writes the same JSON contract (used by
# unit tests and available for debugging).

_WRAPPER_TEMPLATE = '''\
"""Auto-generated by Revolver for the ShinkaEvolve backend. Do not edit.

CLI contract (Shinka job scheduler):
    python {wrapper_name} --program_path <evolved.py> --results_dir <dir>

Evaluates the evolved program with the user's evaluate_instance() over
every instance in $REVOLVER_DATASET_DIR, aggregates metrics (mean per
key), and writes metrics.json (including combined_score) + correct.json
to --results_dir.
"""
import argparse
import json
import os
import statistics
import sys
from pathlib import Path

# Import user's evaluator from the problem version snapshot
sys.path.insert(0, {snapshot_dir!r})
from evaluator import evaluate_instance

# Per-instance timeout in seconds (None = no timeout)
_TIMEOUT_PER_INSTANCE = {timeout_per_instance!r}


def _call_evaluate_instance(program_path, instance_path):
    """Call evaluate_instance with optional per-instance timeout guard."""
    if _TIMEOUT_PER_INSTANCE is None:
        return evaluate_instance(program_path, instance_path)

    import multiprocessing
    import queue as _queue_mod

    result_queue = multiprocessing.Queue()

    def _target():
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
            "evaluate_instance timed out after " + str(_TIMEOUT_PER_INSTANCE) + "s"
        )
    try:
        result = result_queue.get_nowait()
    except _queue_mod.Empty:
        raise RuntimeError("evaluate_instance process ended without returning a result")
    if isinstance(result, Exception):
        raise result
    return result


def run_experiment(program_path, seed=0):
    """Evaluate *program_path* on every dataset instance (one Shinka run).

    Returns the list of per-instance metric dicts. Instances whose
    evaluation raises are skipped (logged to stderr); when every instance
    fails a RuntimeError is raised so the run is marked incorrect.
    """
    dataset_dir = os.environ["REVOLVER_DATASET_DIR"]
    instances = sorted(
        p for p in Path(dataset_dir).iterdir()
        if not p.name.startswith(".") and p.is_file()
    )
    per_instance = []
    for inst in instances:
        try:
            per_instance.append(_call_evaluate_instance(program_path, str(inst)))
        except Exception as exc:
            print(
                "[revolver] evaluation failed for " + inst.name + ": " + str(exc),
                file=sys.stderr,
            )
    if not per_instance:
        raise RuntimeError("all instance evaluations failed")
    return per_instance


def aggregate_metrics(results):
    """Aggregate per-instance metrics: mean per numeric key.

    *results* is the run_shinka_eval results list (one entry per run);
    each entry is the per-instance metrics list from run_experiment().
    """
    all_metrics = [m for run_result in results for m in run_result]
    aggregated = {{}}
    keys = set()
    for m in all_metrics:
        if isinstance(m, dict):
            keys.update(m.keys())
    for key in sorted(keys):
        values = [
            m[key]
            for m in all_metrics
            if isinstance(m, dict)
            and isinstance(m.get(key), (int, float))
            and not isinstance(m.get(key), bool)
        ]
        if values:
            aggregated[key] = statistics.mean(values)
    # Shinka's metrics consumers (DB scoring, display) expect combined_score
    # to exist; validate_result() independently marks the run incorrect when
    # the user metrics lacked it, so this default never masks a failure.
    aggregated.setdefault("combined_score", 0.0)
    return aggregated


def validate_result(per_instance):
    """Every instance result must be a dict with a numeric combined_score."""
    if not isinstance(per_instance, list) or not per_instance:
        return False, "no instance results"
    for m in per_instance:
        if not isinstance(m, dict):
            return False, "evaluate_instance must return a dict of metrics"
        score = m.get("combined_score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            return False, "missing numeric 'combined_score' in instance metrics"
    return True, None


def _save_results(results_dir, metrics, correct, error):
    """Write metrics.json + correct.json (Shinka save_json_results shapes)."""
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "correct.json"), "w") as f:
        json.dump({{"correct": correct, "error": error}}, f, indent=4)
    with open(os.path.join(results_dir, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=4)


def main():
    parser = argparse.ArgumentParser(description="Revolver evaluator for ShinkaEvolve")
    parser.add_argument("--program_path", required=True)
    parser.add_argument("--results_dir", required=True)
    args = parser.parse_args()

    try:
        from shinka.core import run_shinka_eval
    except ImportError:
        run_shinka_eval = None

    if run_shinka_eval is not None:
        run_shinka_eval(
            program_path=__file__,
            results_dir=args.results_dir,
            experiment_fn_name="run_experiment",
            num_runs=1,
            get_experiment_kwargs=lambda _i: {{"program_path": args.program_path}},
            aggregate_metrics_fn=aggregate_metrics,
            validate_fn=validate_result,
        )
        return

    # Standalone fallback (shinka not importable): same JSON contract.
    try:
        per_instance = run_experiment(args.program_path)
        correct, error = validate_result(per_instance)
        metrics = aggregate_metrics([per_instance])
    except Exception as exc:
        metrics = {{"combined_score": 0.0}}
        correct = False
        error = str(exc)
    _save_results(args.results_dir, metrics, correct, error)


if __name__ == "__main__":
    main()
'''


# ── LLM registry projection (ADR-007 D5) ─────────────────────────────────────


def _project_llm_model(llm: LLMEntry) -> tuple[str, dict[str, str | None]]:
    """Project a registered LLM into a Shinka model string + env-var map.

    Per ADR-007 D5:

    - Local (Ollama) entries become
      ``local/<model>@<base_url>?api_key_env=<env>`` — Shinka's dynamic
      local-OpenAI syntax. When the registry entry has no ``api_key_env``,
      :data:`_DEFAULT_LOCAL_API_KEY_ENV` is synthesized.
    - Remote entries use the model id as-is (it must be recognized by
      Shinka's bundled ``pricing.csv`` — documented limitation) and map the
      provider-standard env var to Revolver's registered key env var.

    Returns:
        ``(model_string, llm_env)`` where *llm_env* maps the target env var
        Shinka reads to the Revolver source env var holding the key
        (``None`` source = export a placeholder for key-less local
        endpoints). The export itself happens in ``launch()`` (PR-C).
    """
    if llm.source == "local":
        base_url = llm.base_url or "http://localhost:11434/v1"
        env_name = llm.api_key_env or _DEFAULT_LOCAL_API_KEY_ENV
        # Keep the URL valid when a registered base_url already carries a
        # query string (Shinka strips the api_key_env param on parse).
        separator = "&" if "?" in base_url else "?"
        model_string = f"local/{llm.model}@{base_url}{separator}api_key_env={env_name}"
        return model_string, {env_name: llm.api_key_env}

    provider = (llm.provider or "").lower()
    target_env = _PROVIDER_ENV_VARS.get(provider)
    if target_env is None:
        sys.stderr.write(
            f"Warning: no provider-standard env var known for provider "
            f"'{llm.provider}' on the shinka backend. The engine will rely "
            f"on ambient environment variables for model '{llm.model}'.\n"
        )
        return llm.model, {}
    if llm.api_key_env:
        return llm.model, {target_env: llm.api_key_env}
    return llm.model, {}


def _resolve_ensemble_members(
    ensemble: EnsembleEntry,
    conn: Any | None,
) -> list[tuple[EnsembleMember, LLMEntry]]:
    """Resolve every ensemble member to its registered ``LLMEntry`` (ADR-007 A2).

    Mirrors the OpenEvolve adapter's member resolution: each
    :class:`~revolver.models.llm.EnsembleMember` is looked up by name in the
    global registry via ``conn`` so the projection sees the endpoint details
    (model id, base_url, api_key_env, source).

    Returns:
        A list of ``(member, member_llm)`` pairs in ``ensemble.members`` order —
        which becomes the ``llm_models`` / ``prior_probs`` alignment order.

    Raises:
        ValidationError: When a member LLM is not found in the registry (or no
            DB connection was provided to resolve it).
    """
    from revolver.infra.db import get_llm

    resolved: list[tuple[EnsembleMember, LLMEntry]] = []
    for member in ensemble.members:
        member_llm: LLMEntry | None = None
        if conn is not None:
            member_llm = get_llm(conn, member.llm_name)
        if member_llm is None:
            raise ValidationError(
                f"Ensemble member LLM '{member.llm_name}' not found in registry."
            )
        resolved.append((member, member_llm))
    return resolved


def _prior_probs_vector(
    members: list[tuple[EnsembleMember, LLMEntry]],
    weight_overrides: dict[str, float] | None,
) -> list[float]:
    """Build the ``FixedSampler.prior_probs`` vector aligned to ``llm_models``.

    Registry/member weights are taken first, then any per-run
    ``--llm-weight model=w`` override (keyed by LLM registry name) is applied on
    top (CLI wins). The vector is renormalized to sum 1 (Shinka renormalizes too,
    but doing it here keeps the dry-run/display honest). A degenerate all-zero /
    negative sum falls back to a uniform vector so the sampler never rejects it.

    Args:
        members: ``(member, member_llm)`` pairs in ``llm_models`` order.
        weight_overrides: ``--llm-weight`` overrides keyed by LLM registry name.

    Returns:
        The renormalized weight vector, one entry per member, in order.
    """
    overrides = weight_overrides or {}
    raw = [float(overrides.get(member.llm_name, member.weight)) for member, _llm in members]
    total = sum(raw)
    if total <= 0.0:
        # Degenerate weights → uniform (never send a sum<=0 vector: FixedSampler
        # raises on it). This also matches the bandit's uniform default.
        n = len(raw)
        return [1.0 / n for _ in raw] if n else []
    return [value / total for value in raw]


def _route_selection_kwargs(
    selection: str,
    selection_kwargs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Filter ``selection_kwargs`` to what the selected sampler's ctor accepts.

    ``llm_dynamic_selection_kwargs`` is spread verbatim into the chosen sampler's
    constructor (async_runner.py 0.0.7 L361-383), and AsymmetricUCB /
    ThompsonSampler have no ``**kwargs`` — a stray key raises ``TypeError`` at
    launch. Keys the selected sampler does not accept are therefore **dropped
    with a stderr warning** rather than forwarded (never spread as a union —
    ADR-007 A5). For ``ucb``/``ucb1`` the Revolver-specific ``cost_aware_coef``
    default (0, not Shinka's 0.5 — M4) is applied when the user did not set it.

    Args:
        selection: The resolved sampler name (``fixed``/``ucb``/``ucb1``/
            ``thompson``).
        selection_kwargs: Parsed per-sampler kwargs from ``--selection-kwarg``
            (``None`` when none supplied).

    Returns:
        The accepted-only kwargs dict for the sampler (may be empty). Never
        contains ``prior_probs`` — that is set separately for ``fixed``.
    """
    accepted = _SHINKA_SAMPLER_KWARG_KEYS.get(selection, frozenset())
    routed: dict[str, Any] = {}
    for key, value in (selection_kwargs or {}).items():
        if key in accepted:
            routed[key] = value
        else:
            sys.stderr.write(
                f"Warning: --selection-kwarg '{key}' is not accepted by the "
                f"'{selection}' selection strategy on the shinka backend and was "
                f"dropped (it would otherwise be ignored or raise a TypeError).\n"
            )
    # M4: default cost_aware_coef to 0 (flat-rate/bridge) on ucb/ucb1 only.
    if selection in ("ucb", "ucb1"):
        routed.setdefault("cost_aware_coef", _SHINKA_DEFAULT_COST_AWARE_COEF)
    return routed


def _ensure_section(config: dict[str, Any], name: str) -> dict[str, Any]:
    """Return ``config[name]`` as a dict, (re)creating it when needed."""
    section = config.get(name)
    if not isinstance(section, dict):
        section = {}
        config[name] = section
    return section


def _as_number(value: Any) -> float:
    """Coerce a best-effort numeric JSON field to ``float`` (default 0.0)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


class ShinkaBackend(ChildProcessReaperMixin):
    """``EvolutionBackend`` adapter for ShinkaEvolve (ADR-007, Sprint 014)."""

    name: str = "shinka"
    # Engine output directory name inside a run dir (ADR-007, S14-05).
    default_output_subdir: str = "shinka-output"
    # Wrapper evaluator filename inside a run dir (S14-13: the resume
    # orchestrator copies the parent's wrapper by this backend-owned name).
    wrapper_filename: str = SHINKA_WRAPPER_FILENAME

    def capabilities(self) -> BackendCapabilities:
        """Return the ShinkaEvolve capability matrix (ADR-007)."""
        return BackendCapabilities(
            global_seed=False,
            map_elites_cells=False,
            native_cost_tracking=True,
            multi_language=True,
            ensemble_model="bandit",
            top_n_extraction=True,
            selection_strategies=("fixed", "ucb", "ucb1", "thompson"),
            per_member_reasoning_effort=False,
        )

    def is_available(self) -> tuple[bool, str | None]:
        """Report whether the ``shinka-evolve`` package is importable."""
        try:
            import shinka.core  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: F401
        except ImportError:
            return (False, _INSTALL_HINT)
        return (True, None)

    def wants_http_proxy(self) -> bool:
        """ShinkaEvolve tracks tokens natively — no HTTP proxy (ADR-007 D2)."""
        return False

    def _unavailable(self) -> BackendUnavailableError:
        """Build the typed not-installed error (CLI maps it to exit 3)."""
        return BackendUnavailableError(
            f"The ShinkaEvolve backend is not available. {_INSTALL_HINT}"
        )

    # ── Config tier (S14-07/08/09) ────────────────────────────────────────────

    def config_template(self) -> str:
        """Return the Shinka-shaped ``config.yaml`` scaffold (project init)."""
        return _CONFIG_TEMPLATE

    def validate_config(self, config: Path | dict[str, Any]) -> list[str]:
        """Validate a problem config against the ShinkaEvolve dataclasses.

        Checks each known section (``evo_config``/``db_config``/
        ``job_config``) for keys that are not fields of the backing
        dataclass, and flags unknown top-level sections. Degrades
        gracefully (returns ``[]``) when shinka is not installed,
        mirroring the OpenEvolve pattern used by ``problem version create``.

        Args:
            config: Path to a YAML config file **or** an already-loaded dict.

        Returns:
            A (possibly empty) list of human-readable warning strings.
        """
        section_types = self._import_section_dataclasses()
        if section_types is None:
            return []  # shinka not installed — skip validation gracefully

        data: dict[str, Any]
        if isinstance(config, Path):
            try:
                with open(config) as f:
                    loaded = yaml.safe_load(f)
            except Exception:
                return []
            if not isinstance(loaded, dict):
                return []
            data = loaded
        else:
            data = config

        warnings: list[str] = []
        known_sections = set(_SECTION_DATACLASSES) | _REVOLVER_SECTIONS
        for key in sorted(set(data) - known_sections):
            warnings.append(
                f"Unknown config section '{key}' (expected one of: "
                f"{', '.join(sorted(_SECTION_DATACLASSES))})."
            )

        for section_name, dataclass_type in section_types.items():
            section = data.get(section_name)
            if section is None:
                continue
            if not isinstance(section, dict):
                warnings.append(f"Config section '{section_name}' must be a mapping.")
                continue
            valid_keys = {f.name for f in dataclasses.fields(dataclass_type)}
            for key in sorted(set(section) - valid_keys):
                warnings.append(
                    f"Unknown {section_name} key '{key}' (not in ShinkaEvolve "
                    f"{dataclass_type.__name__} schema)."
                )
        return warnings

    @staticmethod
    def _import_section_dataclasses() -> dict[str, Any] | None:
        """Import the Shinka config dataclasses; ``None`` when unavailable."""
        import importlib

        section_types: dict[str, Any] = {}
        for section_name, (module_name, attr) in _SECTION_DATACLASSES.items():
            try:
                module = importlib.import_module(module_name)
                section_types[section_name] = getattr(module, attr)
            except (ImportError, AttributeError):
                return None
        return section_types

    def build_config(self, spec: BackendRunSpec) -> dict[str, Any]:
        """Build the nested ShinkaEvolve config dict from *spec*.

        Output shape (YAML-serialisable plain dicts, not dataclasses):
        ``evo_config`` (EvolutionConfig keys), ``db_config``
        (DatabaseConfig keys), ``job_config`` (LocalJobConfig keys), plus
        the Revolver-owned ``evaluation`` passthrough and ``llm_env``
        (env-var export map, see :func:`_project_llm_model`).

        Merge order (last wins):
            1. Problem version's ``config.yaml`` (base sections)
            2. LLM projection (ADR-007 D5 + A2/A5): ``llm_models`` (the single
               primary LLM, or every ensemble member in order),
               ``llm_dynamic_selection`` from ``spec.selection`` (default
               ``"fixed"``); under ``fixed`` an ensemble's member weights
               (registry + ``--llm-weight`` overrides) become
               ``llm_dynamic_selection_kwargs.prior_probs`` (renormalized to sum
               1) — inert-and-warned under ``ucb``/``ucb1``/``thompson``;
               per-sampler ``--selection-kwarg`` routing (dropped-with-warning
               when the sampler rejects the key); ``llm_kwargs`` from the primary
               registry entry
            2b. CLI ``--temperature`` (overrides registry temperature)
            3. Problem description → ``task_sys_msg``
            4. ``spec.iterations`` → ``num_generations`` (the orchestrator
               owns the resolution — S14-05)
            4b. ``--rewrite-mode`` → ``patch_types=["full"]``
            5. ``--config-override`` dotted ``key=value`` pairs (e.g.
               ``evo_config.max_api_costs=5.0``)

        Fixed S14 MVP projections: ``language="python"``,
        ``job_type="local"``, ``patch_types=["diff","full"]`` default,
        ``embedding_model=None`` (novelty/embeddings are S15),
        ``results_dir=<run_dir>/shinka-output`` when the run dir is known.

        Raises:
            BackendUnavailableError: When shinka is not installed — keeps
                ``revolver run --backend shinka`` failing fast before any
                side effect (exit 3).
            ValidationError: For an ensemble member LLM missing from the
                registry, or malformed config overrides.
        """
        available, _hint = self.is_available()
        if not available:
            raise self._unavailable()

        # 1. Base config from the problem version snapshot
        config: dict[str, Any] = {}
        problem_config = spec.snapshot_dir / "config.yaml"
        if problem_config.exists():
            with open(problem_config) as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                config = loaded
        evo = _ensure_section(config, "evo_config")
        _ensure_section(config, "db_config")
        job = _ensure_section(config, "job_config")

        # 2. LLM projection (ADR-007 D5 + A2/A5) — single LLM or ensemble bandit.
        #    The single-LLM path (no ensemble) stays a one-member ``fixed`` case
        #    and produces the identical config as before this change (no
        #    ``prior_probs`` / ``llm_dynamic_selection_kwargs`` are emitted for it).
        self._project_llm_selection(spec, config, evo)

        # 2/2b. llm_kwargs from the registry entry + CLI --temperature
        llm_kwargs = evo.get("llm_kwargs")
        if not isinstance(llm_kwargs, dict):
            llm_kwargs = {}
        temperature = spec.temperature if spec.temperature is not None else spec.llm.temperature
        if temperature is not None:
            llm_kwargs["temperatures"] = [temperature]
        # B (#301/S15-06): always set max_tokens — prefer the registered
        # LLMEntry value, else default to 16384 (Shinka's 4096 default
        # starves thinking models). An explicit config.yaml
        # llm_kwargs.max_tokens still wins (setdefault). Raising max_tokens
        # inflates thinking-token spend — reasoning_efforts (see the config
        # template) is the cost lever.
        default_max_tokens = (
            spec.llm.max_tokens if spec.llm.max_tokens is not None else _SHINKA_DEFAULT_MAX_TOKENS
        )
        llm_kwargs.setdefault("max_tokens", default_max_tokens)
        # Collapse per-member reasoning_effort into Shinka's single global pool
        # (FACT A: no per-member effort). Disagreements pick the highest level
        # (never under-think) with a warning; local/bridge members warn as inert
        # (S17-27, ADR-007 A3.2).
        self._project_reasoning_efforts(spec, llm_kwargs)
        if llm_kwargs:
            evo["llm_kwargs"] = llm_kwargs

        # --parallel has no neutral Shinka mapping in S14 (eval job pools
        # are engine-tier concerns) — warn instead of silently ignoring
        # (ADR-007 D4 map-with-warn).
        if spec.parallel is not None:
            sys.stderr.write(
                "Warning: --parallel has no effect on the shinka backend in "
                "this release; the engine manages its own evaluation jobs.\n"
            )

        # 3. Problem description → task system message
        if spec.problem_description:
            evo["task_sys_msg"] = SYSTEM_PROMPT_TEMPLATE.format(
                problem_description=spec.problem_description,
            )

        # 4. Iterations (resolved by the orchestrator — S14-05)
        if spec.iterations is not None:
            evo["num_generations"] = spec.iterations

        # 4b. Rewrite mode / patch types
        if spec.rewrite_mode:
            evo["patch_types"] = ["full"]
            evo["patch_type_probs"] = [1.0]
        elif "patch_types" not in evo:
            evo["patch_types"] = ["diff", "full"]
            evo.setdefault("patch_type_probs", [0.6, 0.4])

        # B (#301/S15-05): default max_patch_attempts to 10. Shinka's own
        # default of 1 loses a whole generation on a single malformed patch
        # (the dominant cheap-model failure mode). An explicit config.yaml
        # value or --config-override (applied last) still wins.
        evo.setdefault("max_patch_attempts", _SHINKA_DEFAULT_MAX_PATCH_ATTEMPTS)

        # Fixed S14 MVP projections
        evo["language"] = "python"
        evo["job_type"] = "local"
        evo["init_program_path"] = str(spec.snapshot_dir / "initial_program.py")
        # Novelty/embedding models are S15 — disable so local-only runs
        # never require an OpenAI embedding key.
        evo.setdefault("embedding_model", None)

        # Engine output dir + evaluator script (when the run dir is known;
        # for build-only flows such as --dry-run these stay unset and the
        # orchestrator/launch() fill them in later).
        if spec.run_dir is not None:
            evo["results_dir"] = str(spec.run_dir / self.default_output_subdir)
        wrapper_path = spec.wrapper_path
        if wrapper_path is None and spec.run_dir is not None:
            wrapper_path = spec.run_dir / SHINKA_WRAPPER_FILENAME
        if wrapper_path is not None:
            job["eval_program_path"] = str(wrapper_path)

        # 4c. Local-endpoint concurrency pin (UX-5 / S16-21): a "local"
        #     source LLM is typically a serialized subscription or single-GPU
        #     endpoint, so fanning out parallel proposal jobs starves it.
        #     Pin job_config.max_proposal_jobs=1 unless the user set it
        #     explicitly via --config-override (the override loop below still
        #     wins for any value they pass).
        overrides_set_proposal_jobs = any(
            override.split("=", 1)[0].strip().split(".")[-1] == "max_proposal_jobs"
            for override in (spec.config_overrides or [])
            if "=" in override
        )
        if spec.llm.source == "local" and not overrides_set_proposal_jobs:
            job["max_proposal_jobs"] = 1

        # 5. Config overrides last (dotted keys, e.g. db_config.num_islands=4)
        for override in spec.config_overrides or []:
            if "=" not in override:
                raise ValidationError(
                    f"Malformed config override (expected key=value): {override!r}"
                )
            key, value = override.split("=", 1)
            _set_nested(config, key.strip(), _parse_value(value.strip()))

        return config

    @staticmethod
    def _project_llm_selection(
        spec: BackendRunSpec,
        config: dict[str, Any],
        evo: dict[str, Any],
    ) -> None:
        """Project the LLM(s) + selection strategy into ``evo_config`` (A2/A5).

        Sets ``llm_models`` (all ensemble members, or the single primary LLM),
        ``llm_dynamic_selection`` (from ``spec.selection``, default ``fixed``),
        and merges the members' env-var export maps into ``config['llm_env']``.

        Weight / kwarg mapping (verified v017 research §0 FACT B / §1):

        - **fixed** (or unset): member weights (registry, then ``--llm-weight``
          overrides on top) become ``FixedSampler.prior_probs`` — a vector
          aligned to ``llm_models`` order, renormalized to sum 1. Emitted only
          when there is a real weighting to express (an ensemble, or a weight
          override): a plain single-LLM run stays byte-identical to the pre-A2
          projection (no ``prior_probs`` / ``llm_dynamic_selection_kwargs``).
        - **ucb/ucb1/thompson**: the bandit learns from a uniform start;
          ``prior_probs`` is FixedSampler-only and would ``TypeError`` on these
          samplers, so weights are **ignored with a warning** when non-uniform
          weights are present (registry or ``--llm-weight``).

        Per-sampler ``--selection-kwarg`` routing (never a union): kwargs the
        selected sampler's constructor does not accept are dropped with a warning
        (see :func:`_route_selection_kwargs`).
        """
        selection = spec.selection or _SHINKA_DEFAULT_SELECTION

        # Members in llm_models / prior_probs order: the ensemble members, or a
        # synthetic single-member view of the primary LLM (single-LLM path).
        if spec.ensemble is not None:
            members = _resolve_ensemble_members(spec.ensemble, spec.conn)
        else:
            members = [(EnsembleMember(llm_name=spec.llm.name), spec.llm)]

        llm_models: list[str] = []
        llm_env: dict[str, str | None] = {}
        for _member, member_llm in members:
            model_string, member_env = _project_llm_model(member_llm)
            llm_models.append(model_string)
            llm_env.update(member_env)

        evo["llm_models"] = llm_models
        evo["llm_dynamic_selection"] = selection
        if llm_env:
            config["llm_env"] = llm_env

        overrides = spec.llm_weight_overrides or None
        # Whether any non-uniform weighting is present (ensemble member weights
        # or a --llm-weight override). A plain single-LLM run has neither.
        has_ensemble = spec.ensemble is not None
        has_weight_signal = has_ensemble or bool(overrides)

        selection_kwargs = _route_selection_kwargs(selection, spec.selection_kwargs)

        if selection == "fixed":
            if has_weight_signal:
                # Only emit prior_probs when there is a weighting to express, so
                # the single-LLM default path stays byte-identical (no extra key).
                selection_kwargs["prior_probs"] = _prior_probs_vector(members, overrides)
        elif selection in _SHINKA_ADAPTIVE_SELECTIONS and has_weight_signal:
            # FACT B: prior_probs is FixedSampler-only — sending it to
            # ucb/ucb1/thompson raises TypeError. The bandit starts uniform, so
            # weights are inert here; warn and do NOT send them.
            sys.stderr.write(
                f"Warning: ensemble weights (registry weights / --llm-weight) are "
                f"ignored under '--selection {selection}' on the shinka backend — "
                f"the bandit learns arm weights adaptively from a uniform start.\n"
            )

        if selection_kwargs:
            evo["llm_dynamic_selection_kwargs"] = selection_kwargs

    @staticmethod
    def _project_reasoning_efforts(
        spec: BackendRunSpec,
        llm_kwargs: dict[str, Any],
    ) -> None:
        """Collapse per-member reasoning_effort into Shinka's single global pool.

        FACT A (v017 research §0, ADR-007 A3.2): ShinkaEvolve exposes a single
        ``llm_kwargs.reasoning_efforts`` pool — it cannot honour a *different*
        effort per ensemble member. This projection:

        - collects each member's **effective** effort (per-member override else
          the member LLM's registry ``reasoning_effort``);
        - if no member sets one → leaves ``reasoning_efforts`` unset (zero
          behaviour change);
        - if the set members agree (or only one is set) → writes
          ``llm_kwargs["reasoning_efforts"] = [<value>]`` **silently**;
        - if they **disagree** → picks the **highest** effort under
          :data:`_REASONING_EFFORT_ORDER` (never under-think) and **warns**;
        - warns **once** that effort is *inert* for ``local``/bridge-sourced
          members (Shinka classes them ``is_reasoning_model=False``).

        Mutates *llm_kwargs* in place (the caller writes it back into
        ``evo['llm_kwargs']``). An explicit ``config.yaml`` /
        ``--config-override`` ``reasoning_efforts`` is preserved: only unset when
        the setdefault-style guard below sees no existing value.
        """
        # Resolve members in the same order as _project_llm_selection.
        if spec.ensemble is not None:
            members = _resolve_ensemble_members(spec.ensemble, spec.conn)
        else:
            members = [(EnsembleMember(llm_name=spec.llm.name), spec.llm)]

        efforts: list[str] = []
        any_local_with_effort = False
        for member, member_llm in members:
            effective = (
                member.reasoning_effort
                if member.reasoning_effort is not None
                else member_llm.reasoning_effort
            )
            if effective is None:
                continue
            efforts.append(effective)
            if member_llm.source == "local":
                any_local_with_effort = True

        if not efforts:
            # Nothing to project — keep the config byte-identical to pre-S17-27.
            return

        # A config.yaml / --config-override value takes precedence: config
        # overrides are applied *after* build_config's llm_kwargs assembly, but
        # a value already present in llm_kwargs came from the problem config.yaml
        # and must win over the registry-derived pool (mirrors max_tokens).
        if "reasoning_efforts" in llm_kwargs:
            return

        distinct = set(efforts)
        if len(distinct) > 1:
            chosen = max(distinct, key=_REASONING_EFFORT_ORDER.index)
            sys.stderr.write(
                "Warning: ensemble members request different reasoning_effort "
                f"levels ({', '.join(sorted(distinct, key=_REASONING_EFFORT_ORDER.index))}), "
                "but the shinka backend has a single global reasoning_efforts pool "
                "(it cannot honour per-member effort). Choosing the highest level "
                f"'{chosen}' so no member under-thinks.\n"
            )
        else:
            chosen = efforts[0]

        if any_local_with_effort:
            sys.stderr.write(
                "Warning: reasoning_effort is inert for local/bridge-sourced members "
                "on the shinka backend (they are treated as non-reasoning models); "
                "it applies only to reasoning-capable remote models.\n"
            )

        llm_kwargs["reasoning_efforts"] = [chosen]

    def resolved_config(
        self,
        config: dict[str, Any],
        config_overrides: dict[str, Any] | None = None,
    ) -> ResolvedConfig:
        """Extract key parameters from a built config for dry-run display.

        Backend-neutral fields (ADR-007 D4) are mapped from their Shinka
        locations (``num_generations`` → iterations, ``db_config.num_islands``
        → num_islands, …); Shinka-exclusive parameters go into
        ``backend_extras`` (only when present, so the generic dry-run
        renderer never prints empty values).
        """
        evo = config.get("evo_config")
        if not isinstance(evo, dict):
            evo = {}
        db = config.get("db_config")
        if not isinstance(db, dict):
            db = {}
        job = config.get("job_config")
        if not isinstance(job, dict):
            job = {}

        llm_models: list[dict[str, Any]] | None = None
        raw_models = evo.get("llm_models")
        if isinstance(raw_models, list) and raw_models:
            llm_models = [{"name": model} for model in raw_models]

        # Single global temperature only when unambiguous (Shinka uses a
        # per-query temperatures list in llm_kwargs).
        temperature: float | None = None
        max_tokens: Any = None
        reasoning_efforts: Any = None
        llm_kwargs = evo.get("llm_kwargs")
        if isinstance(llm_kwargs, dict):
            temps = llm_kwargs.get("temperatures")
            if isinstance(temps, list) and len(temps) == 1 and isinstance(temps[0], int | float):
                temperature = float(temps[0])
            max_tokens = llm_kwargs.get("max_tokens")
            # Surface reasoning_efforts only when meaningfully set (not the
            # Shinka "" default), so a plain run's dry-run stays uncluttered.
            # The value may legitimately be list-valued (Shinka accepts
            # Union[List[str], str]) — keep the membership check, do not
            # narrow it to a string-only test.
            # NOTE: a misspelled nested key (e.g. ``reasoning_effort``) lands
            # silently in llm_kwargs and Shinka ignores it; validating known
            # llm_kwargs keys is the deferred Scope G concern (S15-23 → S16).
            effort = llm_kwargs.get("reasoning_efforts")
            if effort not in (None, "", []):
                reasoning_efforts = effort

        backend_extras: dict[str, Any] = {}
        for key, value in (
            ("patch_types", evo.get("patch_types")),
            ("llm_dynamic_selection", evo.get("llm_dynamic_selection")),
            ("max_patch_attempts", evo.get("max_patch_attempts")),
            ("max_tokens", max_tokens),
            ("reasoning_efforts", reasoning_efforts),
            ("max_api_costs", evo.get("max_api_costs")),
            ("embedding_model", evo.get("embedding_model")),
            ("archive_size", db.get("archive_size")),
            ("parent_selection_strategy", db.get("parent_selection_strategy")),
            ("migration_interval", db.get("migration_interval")),
            ("max_proposal_jobs", job.get("max_proposal_jobs")),
            ("results_dir", evo.get("results_dir")),
        ):
            if value is not None:
                backend_extras[key] = value

        return ResolvedConfig(
            backend=self.name,
            iterations=evo.get("num_generations"),
            num_islands=db.get("num_islands"),
            temperature=temperature,
            language=evo.get("language"),
            llm_models=llm_models,
            config_overrides=config_overrides if config_overrides else None,
            backend_extras=backend_extras,
        )

    def generate_wrapper(self, spec: BackendRunSpec) -> Path:
        """Write the Shinka CLI evaluator script into the run directory.

        The generated ``_shinka_evaluator.py`` (R4 risk materializer —
        S14-09, DES-006 §1.3):

        - honors Shinka's job-scheduler argv contract
          (``--program_path``/``--results_dir``);
        - imports and calls the user's ``evaluate_instance()`` over every
          instance in ``$REVOLVER_DATASET_DIR``;
        - aggregates metrics as the mean per numeric key;
        - writes ``results_dir/metrics.json`` (with ``combined_score``) and
          ``results_dir/correct.json`` via ``run_shinka_eval`` (or a
          standalone fallback when shinka is not importable).

        Raises:
            ValidationError: When ``spec.run_dir`` is missing.
            EvaluatorLoadError: When the user's evaluator does not define
                ``evaluate_instance()`` (the legacy ``evaluate()``-only
                contract is OpenEvolve-specific and not supported here).
            FileNotFoundError: When the evaluator file does not exist.
        """
        if spec.run_dir is None:
            raise ValidationError("BackendRunSpec.run_dir is required for this operation.")

        evaluator_path = spec.snapshot_dir / "evaluator.py"
        if not evaluator_path.exists():
            raise FileNotFoundError(f"Evaluator file not found: {evaluator_path}")

        module = _load_evaluator_module(evaluator_path)
        if not (hasattr(module, "evaluate_instance") and callable(module.evaluate_instance)):
            raise EvaluatorLoadError(
                "The shinka backend requires the evaluator to define "
                "'evaluate_instance(program_path, instance_path)'. The legacy "
                "'evaluate(program_path)' contract is not supported."
            )

        output_path = spec.run_dir / SHINKA_WRAPPER_FILENAME
        wrapper_code = _WRAPPER_TEMPLATE.format(
            wrapper_name=SHINKA_WRAPPER_FILENAME,
            snapshot_dir=str(spec.snapshot_dir),
            timeout_per_instance=spec.timeout_per_instance,
        )
        output_path.write_text(wrapper_code)
        return output_path

    # ── Engine tier — S14-10..13 ──────────────────────────────────────────────

    def launch(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Launch a fresh ShinkaEvolve run (S14-10).

        Exports the ``llm_env`` map (ADR-007 D5), constructs
        ``ShinkaEvolveRunner`` from the built config dict sections, runs
        the evolution synchronously, then materializes the best ranked
        program from ``programs.sqlite`` into ``<results_dir>/best/`` so
        the orchestrator's backend-neutral program collection picks it up
        (without this, the collection would fall through to the engine's
        own root ``init_program.py`` — a silent wrong-solution bug).

        *on_progress* is ignored: live progress is served by
        :meth:`read_progress` polling (run status path).

        Raises:
            BackendUnavailableError: When shinka is not installed.
            ExternalError: When the engine fails (exit code 4); the
                orchestrator's crash-status path relies on this.
        """
        run_dir = self._require_run_dir(spec)
        output_dir = run_dir / self.default_output_subdir
        output_dir.mkdir(exist_ok=True)
        config["output_dir"] = str(output_dir)
        self._run_engine(spec, config, output_dir)
        best_score, best_program = self._materialize_best_programs(output_dir)
        return BackendRunResult(
            best_score=best_score,
            best_program=best_program,
            output_dir=output_dir,
        )

    def resume_precheck(self, parent_run_dir: Path) -> None:
        """Fail-fast guard before a Shinka clone-resume (S16-10).

        ShinkaEvolve resume is DB-driven: the runner only continues an
        existing search when its ``results_dir`` contains a
        ``programs.sqlite`` whose ``last_iteration > 0`` (verified against
        upstream ``async_runner.py`` 0.0.7 — ``resuming_run = db_path.exists()
        and self.db.last_iteration > 0``). This precheck enforces those two
        preconditions on the **parent** run so the orchestrator aborts the
        resume *before* the new run-record insert (DES-005 §14.1) rather
        than letting :meth:`resume` silently restart from generation 0.

        Args:
            parent_run_dir: Directory of the parent run being resumed.

        Raises:
            RevolverError: When the parent has no ``programs.sqlite`` or its
                ``last_iteration`` is ``0``/unreadable (not resumable).
        """
        parent_db = parent_run_dir / self.default_output_subdir / SHINKA_PROGRAMS_DB
        if not parent_db.exists():
            raise RevolverError(
                f"No programs database found in parent run '{parent_run_dir.name}'. "
                "The run may have been too short to produce any programs."
            )
        last_iteration = self._read_last_iteration_from_db(parent_db)
        if last_iteration is None or last_iteration <= 0:
            raise RevolverError(
                f"Parent run '{parent_run_dir.name}' is not resumable: its programs "
                "database has no completed generation (last_iteration is 0). "
                "The run may have been interrupted before its first generation."
            )

    def recover_best_from_checkpoint(self, run_dir: Path) -> RecoveredProgram:
        """Not supported on ShinkaEvolve (B7 / FR-RUN-051).

        ShinkaEvolve does not write filesystem checkpoints that survive an
        interrupted run: its state is ``programs.sqlite``. There is no
        checkpoint to recover a best program *from*, so this raises
        :class:`~revolver.core.exceptions.RecoveryNotSupportedError`
        (distinct from OpenEvolve's checkpoint recovery) to be surfaced
        cleanly by ``solution extract --from-checkpoint``.
        """
        raise RecoveryNotSupportedError(
            "ShinkaEvolve has no filesystem checkpoint to recover from "
            "(interrupted-run state lives in programs.sqlite). "
            "Best-of-checkpoint recovery is an OpenEvolve capability."
        )

    def resume(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        parent_run_dir: Path,
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Resume by cloning the parent's results dir and continuing on it (S16-11).

        ShinkaEvolve resume is DB-driven: when ``results_dir`` contains a
        ``programs.sqlite`` with ``last_iteration > 0``, the runner
        auto-resumes from it (``async_runner.py`` 0.0.7 — ``db_path`` is
        derived from ``results_dir`` at runtime, ``resuming_run =
        db_path.exists() and self.db.last_iteration > 0``, init-program
        seeding runs only in the non-resume branch, and the DB is opened
        with ``CREATE TABLE IF NOT EXISTS`` — never truncated). The resolved
        absolute path is **never written into the DB**, so a ``copytree``
        clone resumes correctly from a new location (S16-09 spike, GO).

        Implementation (clone-resume parity):

        1. ``shutil.copytree`` the parent's ``shinka-output/`` —
           ``programs.sqlite`` (+ any ``-wal``/``-shm`` sidecars), every
           ``gen_*/`` directory, and ``bandit_state.pkl`` / ``prompts.sqlite``
           when present — into the **new** run's ``shinka-output/``.
        2. Extend the generation target on the clone: Shinka's
           ``num_generations`` is a *total* over the shared database, so
           continuing for ``spec.iterations`` more generations means
           ``last_iteration + N`` (the already-resolved count per
           FR-RUN-024). This is already applied by ``build_config`` and only
           recomputed here against the clone's ``last_iteration``.
        3. Point the engine at the **clone** and run it; the parent run's
           ``shinka-output/`` is never opened for writing and stays
           byte-unchanged.

        The clone IS the resumed run's artifact tree, so backend-neutral
        post-processing (program collection, ``count_valid``,
        ``collect_token_usage``, ``parse_population``) reads the new run dir
        directly — no post-run snapshot copy is needed.

        Raises:
            RevolverError: When the parent has no programs database
                (fallback only — the orchestrator owns the fail-fast
                :meth:`resume_precheck` before the run-record insert,
                DES-005 §14.1).
            BackendUnavailableError: When shinka is not installed.
            ExternalError: When the engine fails (exit code 4).
        """
        run_dir = self._require_run_dir(spec)
        parent_output_dir = parent_run_dir / self.default_output_subdir
        parent_db = parent_output_dir / SHINKA_PROGRAMS_DB
        if not parent_db.exists():
            raise RevolverError(
                f"No programs database found in parent run '{parent_run_dir.name}'. "
                "The run may have been too short to produce any programs."
            )

        # 1. Clone the parent's shinka-output/ into the new run dir. The
        #    clone becomes the resumed run's working tree; the parent is left
        #    untouched (clone-resume isolation — S16-11). build_config()
        #    already created an empty <run_dir>/shinka-output for the config
        #    snapshot; copytree refuses an existing target, so remove it first.
        new_output_dir = run_dir / self.default_output_subdir
        if new_output_dir.exists():
            shutil.rmtree(new_output_dir)
        shutil.copytree(parent_output_dir, new_output_dir)
        cloned_db = new_output_dir / SHINKA_PROGRAMS_DB

        # 2. Extend the generation target against the CLONE's last_iteration.
        last_iteration = self._read_last_iteration_from_db(cloned_db)
        if spec.iterations is not None and last_iteration is not None:
            _ensure_section(config, "evo_config")["num_generations"] = (
                last_iteration + spec.iterations
            )

        # 3. Run the engine on the clone; the parent dir is never written to.
        config["output_dir"] = str(new_output_dir)
        self._run_engine(spec, config, new_output_dir)

        best_score, best_program = self._materialize_best_programs(new_output_dir)
        return BackendRunResult(
            best_score=best_score,
            best_program=best_program,
            output_dir=new_output_dir,
        )

    def read_progress(self, run_dir: Path) -> tuple[int | None, float | None]:
        """Cheap live-progress read from ``programs.sqlite`` (S14-12).

        Returns:
            ``(last_generation, best_combined_score)`` — both ``None``
            when the database does not exist yet or cannot be read (the
            engine may be mid-write).
        """
        db_path = self._programs_db_path(run_dir)
        if not db_path.exists():
            return (None, None)
        try:
            conn = sqlite3.connect(db_path)
            try:
                last_generation = self._read_last_iteration(conn)
                row = conn.execute("SELECT MAX(combined_score) FROM programs").fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return (None, None)
        best_score = float(row[0]) if row is not None and row[0] is not None else None
        return (last_generation, best_score)

    def parse_population(self, run_dir: Path) -> list[dict[str, Any]] | None:
        """Parse the population from ``programs.sqlite``, ranked by score.

        Programs are ranked by ``combined_score`` descending; rows with a
        SQL ``NULL`` score (failed evaluations) are excluded from the
        ranking order and listed last. Each entry carries ``id``,
        ``generation``, ``combined_score``, ``correct``, and
        ``public_metrics`` (S14-12 contract), plus the display-oriented
        aliases the ``run population`` renderer expects (``rank``,
        ``score``, ``metrics``, ``iteration_found``, ``parent_id``).

        .. warning::
            ShinkaEvolve has no MAP-Elites feature grid: entries carry
            **no** ``cell_indices`` and **no** ``island`` fields — callers
            must not assume them (ADR-007 D1). ``iteration_found`` aliases
            ``generation`` (the engine has no separate iteration counter).

        Returns:
            The ranked population, or ``None`` when the database does not
            exist yet (no population state).
        """
        db_path = self._programs_db_path(run_dir)
        if not db_path.exists():
            return None
        try:
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT id, generation, combined_score, correct, "
                    "public_metrics, parent_id FROM programs "
                    "ORDER BY (combined_score IS NULL), combined_score DESC, "
                    "timestamp"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return None

        population: list[dict[str, Any]] = []
        for rank, (prog_id, generation, score, correct, metrics_json, parent_id) in enumerate(
            rows, start=1
        ):
            public_metrics: dict[str, Any] = {}
            if metrics_json:
                try:
                    loaded = json.loads(metrics_json)
                    if isinstance(loaded, dict):
                        public_metrics = loaded
                except ValueError:
                    pass
            population.append(
                {
                    "rank": rank,
                    "id": prog_id,
                    "score": float(score) if score is not None else 0.0,
                    "combined_score": float(score) if score is not None else None,
                    "correct": bool(correct),
                    "metrics": public_metrics,
                    "public_metrics": public_metrics,
                    "generation": generation,
                    "iteration_found": generation,
                    "parent_id": parent_id,
                }
            )
        return population

    def count_valid(self, run_dir: Path) -> int | None:
        """Count programs marked ``correct = 1`` in ``programs.sqlite``.

        Returns ``None`` when the database does not exist or cannot be
        read (e.g. the run failed before producing any programs).
        """
        db_path = self._programs_db_path(run_dir)
        if not db_path.exists():
            return None
        try:
            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute("SELECT COUNT(*) FROM programs WHERE correct = 1").fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        return int(row[0]) if row is not None else None

    def count_total(self, run_dir: Path) -> int | None:
        """Count *all* rows in ``programs.sqlite`` (valid or not — UX-4 / S16-19).

        Unlike :meth:`count_valid` (``correct = 1`` only), this returns the
        full program store size: initial seed(s) plus every attempted child,
        which is what ``run info`` surfaces as ``programs_in_db``. Returns
        ``None`` when the database does not exist or cannot be read.
        """
        db_path = self._programs_db_path(run_dir)
        if not db_path.exists():
            return None
        try:
            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute("SELECT COUNT(*) FROM programs").fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        return int(row[0]) if row is not None else None

    def count_evolved_children(self, run_dir: Path) -> int | None:
        """Count evolved children (programs carrying an ``llm_result``).

        Initial seed programs are stored with ``metadata.llm_result`` null
        (no LLM call produced them); each evolved child carries the full
        ``QueryResult`` dict. A return of ``0`` after the engine completes
        means the run was unproductive (backlog #302, S15-09). Returns
        ``None`` when the database is absent or unreadable.
        """
        db_path = self._programs_db_path(run_dir)
        if not db_path.exists():
            return None
        try:
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute("SELECT metadata FROM programs").fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        children = 0
        for (metadata_json,) in rows:
            if not metadata_json:
                continue
            try:
                metadata = json.loads(metadata_json)
            except ValueError:
                continue
            if isinstance(metadata, dict) and isinstance(metadata.get("llm_result"), dict):
                children += 1
        return children

    def collect_token_usage(self, run_dir: Path) -> TokenUsage | None:
        """Collect engine-native token accounting (ADR-007 D2, S14-11).

        Sums, across all rows of the ``programs`` table (verified
        shinka-evolve 0.0.7 schema — sprint-014 §"Verified schema facts"):

        - prompt tokens from ``metadata.llm_result.input_tokens``;
        - completion tokens as ``metadata.llm_result.output_tokens`` +
          ``metadata.llm_result.thinking_tokens`` (the sum equals the
          total completion-side token count across all 0.0.7 providers).

        Cost is intentionally not collected (S15 / backlog #300): the
        per-attempt and reasoning/thinking tokens are never persisted by
        the engine, so no realistic cost figure is reachable. Token counts
        cover stored programs only and slightly undercount retried
        generations (``llm_result`` is the last response only) — retry/
        failed-attempt and thinking tokens are not counted.

        ``llm_result`` may be absent or ``null`` (file-based init program,
        failed attempts) and the ``metadata`` column itself may be SQL
        ``NULL`` — all fields are best-effort with default 0.

        Returns:
            The accumulated :class:`TokenUsage`, or ``None`` when the
            database does not exist (run failed before any programs).
        """
        db_path = self._programs_db_path(run_dir)
        if not db_path.exists():
            return None
        try:
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute("SELECT metadata FROM programs").fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return None

        prompt_tokens = 0
        completion_tokens = 0
        for (metadata_json,) in rows:
            if not metadata_json:
                continue
            try:
                metadata = json.loads(metadata_json)
            except ValueError:
                continue
            if not isinstance(metadata, dict):
                continue
            llm_result = metadata.get("llm_result")
            if isinstance(llm_result, dict):
                prompt_tokens += int(_as_number(llm_result.get("input_tokens")))
                completion_tokens += int(_as_number(llm_result.get("output_tokens"))) + int(
                    _as_number(llm_result.get("thinking_tokens"))
                )
        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    # ── Engine-tier internals ─────────────────────────────────────────────────

    @staticmethod
    def _require_run_dir(spec: BackendRunSpec) -> Path:
        """Return ``spec.run_dir``, raising when missing."""
        if spec.run_dir is None:
            raise ValidationError("BackendRunSpec.run_dir is required for this operation.")
        return spec.run_dir

    def _programs_db_path(self, run_dir: Path) -> Path:
        """Return the conventional ``programs.sqlite`` path for a run dir."""
        return run_dir / self.default_output_subdir / SHINKA_PROGRAMS_DB

    def _engine_classes(self) -> tuple[Any, Any, Any, Any]:
        """Import the engine classes; raise the typed error when absent.

        Returns:
            ``(ShinkaEvolveRunner, EvolutionConfig, DatabaseConfig,
            LocalJobConfig)``.
        """
        try:
            from shinka.core import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
                EvolutionConfig,
                ShinkaEvolveRunner,
            )
            from shinka.database import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
                DatabaseConfig,
            )
            from shinka.launch import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
                LocalJobConfig,
            )
        except ImportError as exc:
            raise self._unavailable() from exc
        return ShinkaEvolveRunner, EvolutionConfig, DatabaseConfig, LocalJobConfig

    @staticmethod
    def _dataclass_kwargs(
        section: dict[str, Any],
        dataclass_type: Any,
        section_name: str,
    ) -> dict[str, Any]:
        """Filter a config section to the dataclass's declared fields.

        Unknown keys (e.g. typos that survived ``--config-override``) are
        dropped with a stderr warning naming the keys — never their values
        — instead of crashing the engine construction.
        """
        valid_keys = {f.name for f in dataclasses.fields(dataclass_type)}
        unknown = sorted(set(section) - valid_keys)
        if unknown:
            sys.stderr.write(
                f"Warning: ignoring unknown {section_name} key(s) for the "
                f"shinka backend: {', '.join(unknown)}.\n"
            )
        return {key: value for key, value in section.items() if key in valid_keys}

    @staticmethod
    def _env_exports(config: dict[str, Any]) -> dict[str, str]:
        """Build the env-var exports for the ``llm_env`` map (ADR-007 D5).

        For each ``target: source`` entry produced by ``build_config()``:

        - target already set (non-empty) → leave the ambient value;
        - source ``None`` (key-less local endpoint) → export the
          placeholder value;
        - source set and present in the environment → copy its value to
          the target var;
        - source named but unset → leave the target unset so the engine
          raises its own explicit missing-env error at construction.

        Values are NEVER logged; the export is applied via
        :func:`revolver_env` so the ambient environment is restored after
        the run.
        """
        exports: dict[str, str] = {}
        llm_env = config.get("llm_env")
        if not isinstance(llm_env, dict):
            return exports
        for target, source in llm_env.items():
            if os.environ.get(target, "").strip():
                continue
            if source is None:
                exports[target] = _LOCAL_API_KEY_PLACEHOLDER
            elif isinstance(source, str) and os.environ.get(source, "").strip():
                exports[target] = os.environ[source]
        return exports

    def _run_engine(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        results_dir: Path,
    ) -> None:
        """Construct ``ShinkaEvolveRunner`` from *config* and run it.

        The ``llm_env`` exports MUST be active before construction:
        ``_validate_evo_config_model_env_access()`` runs in the runner's
        ``__init__``. The initial program and the generated wrapper are
        passed as string contents (``init_program_str``/``evaluate_str``)
        — shinka saves them into *results_dir* and updates the config
        paths itself.

        Raises:
            ExternalError: Wrapping any engine failure (construction or
                run) so the orchestrator's crash-status flow applies.
        """
        runner_cls, evo_cls, db_cls, job_cls = self._engine_classes()

        initial_program = spec.snapshot_dir / "initial_program.py"
        if not initial_program.exists():
            raise FileNotFoundError(f"Initial program not found: {initial_program}")
        wrapper_path = spec.wrapper_path
        if wrapper_path is None:
            run_dir = self._require_run_dir(spec)
            wrapper_path = run_dir / SHINKA_WRAPPER_FILENAME
        if not wrapper_path.exists():
            raise FileNotFoundError(f"Wrapper evaluator not found: {wrapper_path}")
        init_program_str = initial_program.read_text(encoding="utf-8")
        evaluate_str = wrapper_path.read_text(encoding="utf-8")

        evo_section = dict(config.get("evo_config") or {})
        evo_section["results_dir"] = str(results_dir)
        db_section = dict(config.get("db_config") or {})
        job_section = dict(config.get("job_config") or {})

        # Ensure unbuffered output for real-time progress (S8a-09); this
        # affects the evaluation jobs the engine spawns. Carried inside the
        # revolver_env block so the caller's PYTHONUNBUFFERED is restored on
        # exit (S15-15) — the env mutation must not leak past the run.
        exports = self._env_exports(config)
        exports["PYTHONUNBUFFERED"] = "1"

        # Snapshot the orchestrator's child PIDs BEFORE the run so the
        # post-run backstop only reaps children the run itself spawned
        # (A2 / #314). Children predating the run (none expected, but be
        # safe) are excluded.
        pre_run_children = self._current_child_pids()

        runner: Any = None
        try:
            with revolver_env(exports):
                runner = runner_cls(
                    evo_config=evo_cls(
                        **self._dataclass_kwargs(evo_section, evo_cls, "evo_config")
                    ),
                    job_config=job_cls(
                        **self._dataclass_kwargs(job_section, job_cls, "job_config")
                    ),
                    db_config=db_cls(**self._dataclass_kwargs(db_section, db_cls, "db_config")),
                    init_program_str=init_program_str,
                    evaluate_str=evaluate_str,
                    verbose=True,
                )
                runner.run()
        except RevolverError:
            raise
        except Exception as exc:
            raise ExternalError(f"ShinkaEvolve run failed: {exc}") from exc
        finally:
            # Orchestrator-owned teardown (A2 / #314). ``run()`` drives an
            # in-process ``asyncio.run()`` whose ``_cleanup_async()`` already
            # joins the scheduler/DB thread pools, yet the process can still
            # busy-loop at ~100% CPU afterwards (leaked async LLM transports /
            # default executor / a surviving evaluator child). This teardown
            # is purely defensive: it is idempotent with the runner's own
            # cleanup, never raises, and only runs on the Shinka path (the OE
            # adapter is untouched). The result is already persisted in
            # ``programs.sqlite`` by the time ``run()`` returns, so neither
            # the resource shutdown nor the child reap can truncate it.
            self._shutdown_runner(runner)
            self._reap_run_children(pre_run_children)

    @staticmethod
    def _shutdown_runner(runner: Any) -> None:
        """Defensively tear down a ``ShinkaEvolveRunner``'s reachable pools.

        ``ShinkaEvolveRunner.run_async()`` already calls ``_cleanup_async()``
        (which joins the ``JobScheduler`` ``ThreadPoolExecutor`` and both
        ``AsyncProgramDatabase`` executors with ``wait=True``), so on a clean
        run this is a no-op. It exists as a backstop for the case where the
        runner returns with one of those pools still alive — every step is
        guarded so a partially-constructed or differently-shaped runner (or a
        future upstream rename) can never turn teardown into a crash.

        ``wait=False`` is used deliberately: the orchestrator must not block
        on a pool worker that is itself wedged (cf. the OE
        ``ProcessPoolExecutor.shutdown(wait=True)`` hang in backlog #159).
        The surviving worker, if any, is a daemon-less thread the
        ``_reap_run_children`` backstop and the interpreter exit handle.
        """
        if runner is None:
            return

        scheduler = getattr(runner, "scheduler", None)
        scheduler_shutdown = getattr(scheduler, "shutdown", None)
        if callable(scheduler_shutdown):
            with contextlib.suppress(Exception):
                scheduler_shutdown(wait=False)

        async_db = getattr(runner, "async_db", None)
        for attr in ("executor", "write_executor"):
            executor = getattr(async_db, attr, None)
            executor_shutdown = getattr(executor, "shutdown", None)
            if callable(executor_shutdown):
                with contextlib.suppress(Exception):
                    executor_shutdown(wait=False)

    # ``_current_child_pids`` / ``_reap_run_children`` are inherited from
    # ``ChildProcessReaperMixin`` (base.py) — hoisted in S17-04 so both
    # backends share one definition.

    def _materialize_best_programs(self, results_dir: Path) -> tuple[float | None, Path | None]:
        """Write the top ranked program(s) into ``<results_dir>/best/``.

        ShinkaEvolve keeps evolved programs in ``programs.sqlite`` only
        and writes its ``init_program.py`` + ``evaluate.py`` at the
        results-dir root; without this materialization the orchestrator's
        program collection (which scans ``best/`` then falls back to root
        ``*.py``) would silently collect the initial program as rank-1.

        Programs with a non-NULL ``combined_score`` are ranked descending
        (ties broken by insertion timestamp) and the top
        :data:`_BEST_PROGRAMS_COUNT` are written as ``best_program.py``
        (then ``best_program_NN.py``), matching OpenEvolve's single
        best-program output count.

        ``best/`` is created even when no scored program exists: an
        existing (possibly empty) named dir is what keeps the
        orchestrator's collection from falling back to the root ``*.py``
        files (review #196 W2).

        Returns:
            ``(best_score, best_program_path)`` — both ``None`` when no
            scored program exists.
        """
        best_dir = results_dir / "best"
        best_dir.mkdir(parents=True, exist_ok=True)

        db_path = results_dir / SHINKA_PROGRAMS_DB
        if not db_path.exists():
            return (None, None)
        try:
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT id, code, combined_score FROM programs "
                    "WHERE combined_score IS NOT NULL "
                    "ORDER BY combined_score DESC, timestamp LIMIT ?",
                    (_BEST_PROGRAMS_COUNT,),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return (None, None)
        if not rows:
            return (None, None)

        best_path: Path | None = None
        for rank, (_prog_id, code, _score) in enumerate(rows, start=1):
            name = "best_program.py" if rank == 1 else f"best_program_{rank:02d}.py"
            path = best_dir / name
            path.write_text(code or "", encoding="utf-8")
            if rank == 1:
                best_path = path
        return (float(rows[0][2]), best_path)

    @staticmethod
    def _read_last_iteration(conn: sqlite3.Connection) -> int | None:
        """Read the last completed generation from an open connection.

        Prefers Shinka's own ``metadata_store.last_iteration`` bookkeeping
        and falls back to ``MAX(generation)`` over the programs table.
        """
        try:
            row = conn.execute(
                "SELECT value FROM metadata_store WHERE key = 'last_iteration'"
            ).fetchone()
            if row is not None and row[0] is not None:
                return int(row[0])
        except (sqlite3.Error, ValueError):
            pass
        try:
            row = conn.execute("SELECT MAX(generation) FROM programs").fetchone()
        except sqlite3.Error:
            return None
        if row is None or row[0] is None:
            return None
        return int(row[0])

    def _read_last_iteration_from_db(self, db_path: Path) -> int | None:
        """Open *db_path* read-only and return the last completed generation."""
        try:
            conn = sqlite3.connect(db_path)
            try:
                return self._read_last_iteration(conn)
            finally:
                conn.close()
        except sqlite3.Error:
            return None


__all__ = ["SHINKA_PROGRAMS_DB", "SHINKA_WRAPPER_FILENAME", "ShinkaBackend"]
