"""Evolution backend abstraction — protocol, capabilities, factory.

Defines the ``EvolutionBackend`` protocol that every evolution engine
adapter must satisfy, the ``BackendCapabilities`` matrix that declares
what each backend can honestly do, the neutral ``BackendRunSpec`` /
``BackendRunResult`` data carriers, and the ``get_backend()`` factory.

Traceable to: ADR-007 (Pluggable Evolution Backend, decisions D1-D6),
top-down analysis #267 §2.2, DES-005 §14.1.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from revolver.core.exceptions import ResourceError, ValidationError
from revolver.models.llm import EnsembleEntry, LLMEntry
from revolver.models.run import ResolvedOEConfig, TokenUsage

# Names accepted by :func:`get_backend`, in display order.
AVAILABLE_BACKENDS: tuple[str, ...] = ("openevolve", "shinka")


class BackendUnavailableError(ResourceError):
    """Raised when a selected evolution backend is not installed/usable.

    Subclasses :class:`~revolver.core.exceptions.ResourceError` so the
    CLI error boundary maps it to exit code 3 (resource error).
    """

    exit_code: int = 3


@dataclass(frozen=True)
class BackendCapabilities:
    """What an evolution backend can honestly do (ADR-007 D1/D3).

    Drives warnings and documentation instead of silent divergence
    (e.g. warn when ``--seed`` is requested on a backend without
    global-seed support).

    Attributes:
        global_seed: Search-level reproducibility via a global seed
            (OpenEvolve: True, ShinkaEvolve: False).
        map_elites_cells: MAP-Elites feature-grid cells in the population
            (OpenEvolve: True, ShinkaEvolve: False — island index only).
        native_cost_tracking: Engine persists token/cost accounting itself
            (OpenEvolve: False — HTTP proxy; ShinkaEvolve: True — SQLite).
        multi_language: Evolution of non-Python programs
            (OpenEvolve: False, ShinkaEvolve: True).
        ensemble_model: Multi-LLM selection semantics —
            ``"weighted"`` (OpenEvolve) or ``"bandit"`` (ShinkaEvolve).
        top_n_extraction: Reliable top-N program extraction
            (OpenEvolve: False, ShinkaEvolve: True).
    """

    global_seed: bool
    map_elites_cells: bool
    native_cost_tracking: bool
    multi_language: bool
    ensemble_model: str
    top_n_extraction: bool


@dataclass
class ProgressInfo:
    """Progress callback data emitted during an evolution run.

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


@dataclass
class BackendRunSpec:
    """Engine-neutral description of a run to launch or resume.

    Field shapes mirror the data ``core.run.launch_run()`` /
    ``core.run.resume_run()`` assemble today before calling into
    ``infra.backends.openevolve`` — so the PR-C switch to backend
    mediation is a mechanical re-plumbing, not a redesign.

    Attributes:
        snapshot_dir: Problem version snapshot directory
            (contains ``config.yaml``, ``initial_program.py``, ``evaluator.py``).
        llm: Registered LLM entry (primary LLM in ensemble mode).
        run_dir: Run directory (``.revolver/runs/<id>``). ``None`` for
            build-only flows (e.g. ``--dry-run`` before a run dir exists).
        iterations: Iteration count override (``None`` = use config default).
            Contract: for :meth:`EvolutionBackend.resume` the orchestrator
            must pass the **already-resolved** count (parent-run fallback
            applied per FR-RUN-024) — the backend does not know the parent
            run's iteration count.
        config_overrides: Raw ``key=value`` override strings from the CLI.
        problem_description: Content of ``problem.md`` for prompt injection.
        temperature: CLI ``--temperature`` override.
        parallel: CLI ``--parallel`` override for parallel evaluations.
        rewrite_mode: Full-rewrite mode shortcut (``--rewrite-mode``).
        ensemble: Ensemble entry for multi-model mode.
        conn: Global DB connection, required when *ensemble* is provided
            (member LLM resolution at config-build time).
        timeout_per_instance: Per-instance evaluation timeout in seconds.
        wrapper_path: Path to the generated wrapper evaluator. Populated
            by the orchestrator from :meth:`EvolutionBackend.generate_wrapper`;
            when ``None`` the backend derives its conventional location.
    """

    snapshot_dir: Path
    llm: LLMEntry
    run_dir: Path | None = None
    iterations: int | None = None
    config_overrides: list[str] | None = None
    problem_description: str | None = None
    temperature: float | None = None
    parallel: int | None = None
    rewrite_mode: bool = False
    ensemble: EnsembleEntry | None = None
    conn: Any | None = None
    timeout_per_instance: float | None = None
    wrapper_path: Path | None = None


@dataclass
class BackendRunResult:
    """Engine-neutral result of a completed evolution run.

    Mirrors the OpenEvolve ``RunOutput`` shape consumed by
    ``core.run`` today.

    Attributes:
        best_score: Score of the best program found.
        best_program: Raw best-program object returned by the engine.
        output_dir: Path to the engine's output directory.
    """

    best_score: float | None = None
    best_program: Any = None
    output_dir: Path | None = None


@runtime_checkable
class EvolutionBackend(Protocol):
    """Protocol every evolution engine adapter must satisfy (ADR-007 D1).

    Serves exactly the engine-coupled command surface identified in
    #267 §1: ``run`` (build/validate/wrapper/launch + token strategy),
    ``run resume``, ``run status`` (active path), ``run population``,
    ``--dry-run``, plus the four shims (``doctor``/``setup``,
    ``project init``, ``problem version create``).
    """

    name: str

    def capabilities(self) -> BackendCapabilities:
        """Return the static capability matrix for this backend."""
        ...

    def is_available(self) -> tuple[bool, str | None]:
        """Report whether the engine is installed (doctor/setup).

        Returns:
            ``(available, hint)`` — *hint* is an install instruction
            when unavailable, ``None`` otherwise.
        """
        ...

    def config_template(self) -> str:
        """Return the per-backend ``config.yaml`` scaffold (project init)."""
        ...

    def validate_config(self, config: Path | dict[str, Any]) -> list[str]:
        """Validate a problem config; return human-readable warnings."""
        ...

    def build_config(self, spec: BackendRunSpec) -> dict[str, Any]:
        """Build the merged engine config dict from a run spec."""
        ...

    def resolved_config(
        self,
        config: dict[str, Any],
        config_overrides: dict[str, Any] | None = None,
    ) -> ResolvedOEConfig:
        """Extract key parameters for dry-run display.

        TODO(S13 PR-C): transitional signature — returns the OE-shaped
        ``ResolvedOEConfig`` until the neutral ``ResolvedConfig`` +
        ``backend_extras`` lands (ADR-007 D4, PR-B/PR-C).
        """
        ...

    def generate_wrapper(self, spec: BackendRunSpec) -> Path:
        """Generate the wrapper evaluator file; return its path."""
        ...

    def launch(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Launch a fresh evolution run.

        Contract: the backend overwrites ``config['output_dir']`` for its
        own layout; orchestrators must persist any config snapshot *before*
        calling. Backends MAY ignore *on_progress* (live progress is served
        by :meth:`read_progress` polling).
        """
        ...

    def resume(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        parent_run_dir: Path,
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Resume evolution from a parent run (backend-defined semantics).

        Same ``config['output_dir']`` / *on_progress* contract as
        :meth:`launch`. ``spec.iterations`` must already carry the
        parent-run fallback (see :class:`BackendRunSpec`).
        """
        ...

    def read_progress(self, run_dir: Path) -> tuple[int | None, float | None]:
        """Cheap live-progress read: ``(iterations_done, best_score)``."""
        ...

    def parse_population(self, run_dir: Path) -> list[dict[str, Any]] | None:
        """Parse the current population, ranked by score descending.

        Returns:
            The ranked population, or ``None`` when the engine has not
            produced any population state yet (no checkpoint).
        """
        ...

    def count_valid(self, run_dir: Path) -> int | None:
        """Count valid programs produced so far (``None`` if unknown)."""
        ...

    def wants_http_proxy(self) -> bool:
        """Whether token usage must be measured via the HTTP proxy."""
        ...

    def collect_token_usage(self, run_dir: Path) -> TokenUsage | None:
        """Collect engine-native token accounting (``None`` if not supported)."""
        ...


def get_backend(name: str) -> EvolutionBackend:
    """Resolve a backend name to an :class:`EvolutionBackend` instance.

    Args:
        name: Backend name (see :data:`AVAILABLE_BACKENDS`).

    Returns:
        The backend adapter instance.

    Raises:
        ValidationError: If *name* is not a registered backend (exit 1).
    """
    # Imported lazily: the implementation modules import this module.
    from revolver.infra.backends.openevolve import OpenEvolveBackend
    from revolver.infra.backends.shinka import ShinkaBackend

    registry: dict[str, Callable[[], EvolutionBackend]] = {
        "openevolve": OpenEvolveBackend,
        "shinka": ShinkaBackend,
    }
    # Guard against the registry and the display constant drifting apart.
    assert set(registry) == set(AVAILABLE_BACKENDS)
    factory = registry.get(name)
    if factory is None:
        available = ", ".join(sorted(registry))
        raise ValidationError(f"Unknown backend '{name}'. Available backends: {available}.")
    return factory()
