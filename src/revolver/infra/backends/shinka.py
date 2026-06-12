"""ShinkaEvolve backend — config tier (ADR-007, Sprint 014 PR-B).

Implements the configuration surface of the ``EvolutionBackend`` protocol
for ShinkaEvolve:

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

The engine tier (``launch``/``resume``/``read_progress``/
``parse_population``/``count_valid``/``collect_token_usage``) lands in
Sprint 014 PR-C and still raises
:class:`~revolver.infra.backends.base.BackendUnavailableError`.

Traceable to: ADR-007 (decisions D1/D4/D5), DES-005 §14.1, DES-006 §1.3,
FR-RUN-047/048, sprint-014 S14-07..09.
"""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
from pathlib import Path
import sys
from typing import Any

import yaml

from revolver.core.exceptions import EvaluatorLoadError, ValidationError
from revolver.infra.backends.base import (
    BackendCapabilities,
    BackendRunResult,
    BackendRunSpec,
    BackendUnavailableError,
    ProgressInfo,
)
from revolver.infra.backends.openevolve import (
    # Backend-neutral config plumbing shared with the OpenEvolve adapter.
    # Promotion to a shared module is deferred to S15 (shim removal).
    SYSTEM_PROMPT_TEMPLATE,
    _load_evaluator_module,
    _parse_value,
    _set_nested,
)
from revolver.models.llm import LLMEntry
from revolver.models.run import ResolvedConfig, TokenUsage

_INSTALL_HINT = "Install with: pip install 'revolver[shinka]'"

# Filename of the generated Shinka CLI evaluator inside a run dir.
SHINKA_WRAPPER_FILENAME = "_shinka_evaluator.py"

# Default env var name synthesized for local OpenAI-compatible endpoints
# when the registry entry has no api_key_env (ADR-007 D5). launch() (PR-C)
# must export a placeholder value when this variable is unset — Shinka
# raises on a named-but-unset api_key_env, mirroring OE's "ollama" key.
_DEFAULT_LOCAL_API_KEY_ENV = "OLLAMA_API_KEY"

# Provider-standard env vars read by Shinka's native SDK clients
# (shinka/llm/client.py — ADR-007 D5). launch() (PR-C) exports each target
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


def _ensure_section(config: dict[str, Any], name: str) -> dict[str, Any]:
    """Return ``config[name]`` as a dict, (re)creating it when needed."""
    section = config.get(name)
    if not isinstance(section, dict):
        section = {}
        config[name] = section
    return section


class ShinkaBackend:
    """``EvolutionBackend`` adapter for ShinkaEvolve (config tier — S14 PR-B).

    The engine tier (launch/resume/inspection/token collection) lands in
    PR-C; those methods still raise :class:`BackendUnavailableError`.
    """

    name: str = "shinka"
    # Engine output directory name inside a run dir (ADR-007, S14-05).
    default_output_subdir: str = "shinka-output"

    def capabilities(self) -> BackendCapabilities:
        """Return the ShinkaEvolve capability matrix (ADR-007)."""
        return BackendCapabilities(
            global_seed=False,
            map_elites_cells=False,
            native_cost_tracking=True,
            multi_language=True,
            ensemble_model="bandit",
            top_n_extraction=True,
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
            2. LLM projection (ADR-007 D5): ``llm_models`` single entry,
               ``llm_dynamic_selection="fixed"``, ``llm_kwargs`` from the
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
            ValidationError: For ensembles (bandit mapping is S15) or
                malformed config overrides.
        """
        available, _hint = self.is_available()
        if not available:
            raise self._unavailable()

        if spec.ensemble is not None:
            raise ValidationError(
                "Ensembles are not supported on the shinka backend yet "
                "(weighted-to-bandit mapping is planned for Sprint 015). "
                "Use a single registered LLM."
            )

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

        # 2. LLM projection (ADR-007 D5) — single LLM, fixed selection
        model_string, llm_env = _project_llm_model(spec.llm)
        evo["llm_models"] = [model_string]
        evo["llm_dynamic_selection"] = "fixed"
        if llm_env:
            config["llm_env"] = llm_env

        # 2/2b. llm_kwargs from the registry entry + CLI --temperature
        llm_kwargs = evo.get("llm_kwargs")
        if not isinstance(llm_kwargs, dict):
            llm_kwargs = {}
        temperature = spec.temperature if spec.temperature is not None else spec.llm.temperature
        if temperature is not None:
            llm_kwargs["temperatures"] = [temperature]
        if spec.llm.max_tokens is not None:
            llm_kwargs.setdefault("max_tokens", spec.llm.max_tokens)
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

        # 5. Config overrides last (dotted keys, e.g. db_config.num_islands=4)
        for override in spec.config_overrides or []:
            if "=" not in override:
                raise ValidationError(
                    f"Malformed config override (expected key=value): {override!r}"
                )
            key, value = override.split("=", 1)
            _set_nested(config, key.strip(), _parse_value(value.strip()))

        return config

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

        llm_models: list[dict[str, Any]] | None = None
        raw_models = evo.get("llm_models")
        if isinstance(raw_models, list) and raw_models:
            llm_models = [{"name": model} for model in raw_models]

        # Single global temperature only when unambiguous (Shinka uses a
        # per-query temperatures list in llm_kwargs).
        temperature: float | None = None
        llm_kwargs = evo.get("llm_kwargs")
        if isinstance(llm_kwargs, dict):
            temps = llm_kwargs.get("temperatures")
            if isinstance(temps, list) and len(temps) == 1 and isinstance(temps[0], int | float):
                temperature = float(temps[0])

        backend_extras: dict[str, Any] = {}
        for key, value in (
            ("patch_types", evo.get("patch_types")),
            ("llm_dynamic_selection", evo.get("llm_dynamic_selection")),
            ("max_api_costs", evo.get("max_api_costs")),
            ("embedding_model", evo.get("embedding_model")),
            ("archive_size", db.get("archive_size")),
            ("parent_selection_strategy", db.get("parent_selection_strategy")),
            ("migration_interval", db.get("migration_interval")),
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

    # ── Engine tier — PR-C (S14-10..13) ──────────────────────────────────────

    def launch(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Not available until S14 PR-C."""
        raise self._unavailable()

    def resume(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        parent_run_dir: Path,
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Not available until S14 PR-C."""
        raise self._unavailable()

    def read_progress(self, run_dir: Path) -> tuple[int | None, float | None]:
        """Not available until S14 PR-C."""
        raise self._unavailable()

    def parse_population(self, run_dir: Path) -> list[dict[str, Any]] | None:
        """Not available until S14 PR-C."""
        raise self._unavailable()

    def count_valid(self, run_dir: Path) -> int | None:
        """Not available until S14 PR-C."""
        raise self._unavailable()

    def collect_token_usage(self, run_dir: Path) -> TokenUsage | None:
        """Not available until S14 PR-C."""
        raise self._unavailable()


__all__ = ["SHINKA_WRAPPER_FILENAME", "ShinkaBackend"]
