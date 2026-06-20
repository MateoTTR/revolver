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
from revolver.models.run import ResolvedConfig, TokenUsage

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

    Attributes:
        name: Registry name of the backend (``"openevolve"``/``"shinka"``).
        default_output_subdir: Name of the engine output directory inside a
            run dir (``"oe-output"`` for OpenEvolve, ``"shinka-output"`` for
            ShinkaEvolve — S14-05). The orchestrator stages
            ``<run_dir>/<default_output_subdir>`` and never hard-codes an
            engine-specific name.
        wrapper_filename: Name of the generated wrapper evaluator inside a
            run dir (``"_revolver_evaluator.py"`` for OpenEvolve,
            ``"_shinka_evaluator.py"`` for ShinkaEvolve — S14-13). The
            resume orchestrator copies the parent run's wrapper by this
            backend-owned name instead of hard-coding it.
    """

    name: str
    default_output_subdir: str
    wrapper_filename: str

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
    ) -> ResolvedConfig:
        """Extract key parameters for dry-run display (ADR-007 D4).

        Returns the backend-neutral :class:`~revolver.models.run.ResolvedConfig`;
        backend-exclusive parameters go into ``backend_extras``.
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

    def resume_precheck(self, parent_run_dir: Path) -> None:
        """Fail-fast guard the orchestrator runs before a resume (S16-10).

        Called by ``core.run.resume_run()`` *before* the new run-record
        insert and lock acquisition so a parent that lacks usable resume
        state aborts cleanly (DES-005 §14.1). Resume-state formats are
        backend-specific, so each backend validates its own preconditions
        and raises a clear :class:`~revolver.core.exceptions.RevolverError`
        (or subclass) when they are not met.

        The default implementation is a **no-op**. Because ``EvolutionBackend``
        is a structural :class:`~typing.Protocol` (not subclassed), concrete
        backends without resume preconditions (e.g. OpenEvolve, whose
        checkpoint staging is handled by the orchestrator) provide their own
        explicit no-op rather than inheriting this body.

        Args:
            parent_run_dir: Directory of the parent run being resumed.

        Raises:
            RevolverError: When the parent run is not resumable (subclasses
                override to enforce backend-specific preconditions).
        """
        return None

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

    def count_total(self, run_dir: Path) -> int | None:
        """Count *all* programs in the backend's store, valid or not.

        Distinct from :meth:`count_valid` (correct programs only) and from
        the number of programs extracted to the run's ``programs/`` dir.
        On backends that keep a complete program store (ShinkaEvolve's
        ``programs.sqlite``) this is the total row count; backends that
        cannot cheaply produce a full total (OpenEvolve — needs checkpoint
        parsing) return ``None`` (UX-4 / S16-19).
        """
        ...

    def count_evolved_children(self, run_dir: Path) -> int | None:
        """Count successfully evolved child programs, excluding seed(s).

        Distinct from :meth:`count_valid`, which counts all valid programs
        including the initial seed(s): a run whose evolved-children count is
        ``0`` produced no useful evolution even though the seeds remain
        valid (the unproductive-run case — backlog #302). Returns ``None``
        when the backend cannot distinguish children from seeds, in which
        case the caller skips the unproductive-run check.
        """
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
