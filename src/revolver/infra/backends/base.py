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
import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import time
from typing import Any, Protocol, runtime_checkable

from revolver.core.exceptions import ResourceError, ValidationError
from revolver.models.llm import EnsembleEntry, LLMEntry
from revolver.models.run import ResolvedConfig, TokenUsage

# Names accepted by :func:`get_backend`, in display order.
AVAILABLE_BACKENDS: tuple[str, ...] = ("openevolve", "shinka")

# Grace period between SIGTERM and SIGKILL when reaping run children (A2 /
# #314). Shared by both backends' post-run teardown.
_CHILD_REAP_GRACE_SECONDS = 3.0


class ChildProcessReaperMixin:
    """Post-run child-process teardown shared by both backends (A2 / #314).

    An in-process engine ``run()`` (ShinkaEvolve's ``asyncio.run`` or
    OpenEvolve's ``ProcessPoolExecutor`` workers) can leave an evaluation
    child alive after the result is already persisted, keeping the CLI pinned
    at ~100% CPU. Both backends snapshot their child PIDs *before* the run and,
    in a ``finally`` block, reap any PID that appeared afterwards.

    Hoisted here (S17-04) so there is exactly one definition; ``ShinkaBackend``
    and ``OpenEvolveBackend`` inherit it. The reap is Linux-only (needs
    ``/proc``) and a no-op elsewhere, and never raises — it is a defensive
    backstop, not part of the run's correctness path.
    """

    @staticmethod
    def _current_child_pids() -> set[int]:
        """Return the PIDs of the current process's direct children (Linux).

        Reads ``/proc/self/task/*/children`` — the kernel-maintained list of
        child PIDs — which needs no third-party dependency. Returns an empty
        set on any platform without that interface (macOS, Windows) or on any
        read error, so the caller's reap backstop simply becomes a no-op
        rather than failing the run.
        """
        children: set[int] = set()
        task_dir = Path("/proc/self/task")
        if not task_dir.is_dir():
            return children
        try:
            for tid_dir in task_dir.iterdir():
                children_file = tid_dir / "children"
                with contextlib.suppress(OSError):
                    for token in children_file.read_text().split():
                        with contextlib.suppress(ValueError):
                            children.add(int(token))
        except OSError:
            return children
        return children

    def _reap_run_children(self, pre_run_children: set[int]) -> None:
        """Terminate evaluator children that outlived the engine run (A2).

        Any child PID that appeared *after* the pre-run snapshot is sent
        ``SIGTERM``, then ``SIGKILL`` after a short grace period. The run's
        result is already persisted when the engine ``run()`` returns, so this
        cannot truncate persistence. No-op on platforms without ``/proc`` child
        enumeration.
        """
        survivors = self._current_child_pids() - pre_run_children
        if not survivors:
            return

        for pid in survivors:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGTERM)

        deadline = time.monotonic() + _CHILD_REAP_GRACE_SECONDS
        remaining = set(survivors)
        while remaining and time.monotonic() < deadline:
            for pid in list(remaining):
                try:
                    os.kill(pid, 0)
                except (ProcessLookupError, OSError):
                    remaining.discard(pid)
            if remaining:
                time.sleep(0.1)

        for pid in remaining:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGKILL)


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
        selection_strategies: Accepted ``--selection`` values (ADR-007
            Amendment A4). OpenEvolve exposes only ``("fixed",)`` — the neutral
            vocabulary for its static weighted sampler (``ensemble_model`` is a
            separate axis); ShinkaEvolve exposes
            ``("fixed", "ucb", "ucb1", "thompson")``. ``--selection`` values
            outside this tuple are rejected for the resolved backend rather
            than silently dropped.
        per_member_reasoning_effort: Whether the backend honors a distinct
            ``reasoning_effort`` per ensemble member (ADR-007 Amendment A4).
            OpenEvolve: True (per-model ``LLMModelConfig.reasoning_effort``);
            ShinkaEvolve: False (single global ``reasoning_efforts`` pool —
            per-member values are merged with a disagreement warning).
    """

    global_seed: bool
    map_elites_cells: bool
    native_cost_tracking: bool
    multi_language: bool
    ensemble_model: str
    top_n_extraction: bool
    selection_strategies: tuple[str, ...]
    per_member_reasoning_effort: bool


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
        selection: Resolved ensemble selection strategy (ADR-007 Amendment
            A2). ``None`` means the backend's implicit default (OpenEvolve:
            static weighted; ShinkaEvolve: ``"fixed"`` — the S14 single-LLM
            path). Validated against the resolved backend's
            :attr:`BackendCapabilities.selection_strategies`.
        selection_kwargs: Parsed per-sampler keyword arguments for the
            adaptive selection strategy (e.g. ``{"cost_aware_coef": 0.0}``
            for ``ucb``/``ucb1``). ``None`` when no ``--selection-kwarg`` was
            supplied. Routed per-sampler by the backend (never spread as a
            union — ADR-007 Amendment A5).
        llm_weight_overrides: Per-run ``--llm-weight model=w`` overrides keyed
            by LLM registry name (ADR-007 Amendment A1/M3). Applied on top of
            registry weights. Honored on OpenEvolve (weighted) and on
            ShinkaEvolve only under ``fixed``; warned-and-ignored under the
            adaptive Shinka modes.
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
    selection: str | None = None
    selection_kwargs: dict[str, Any] | None = None
    llm_weight_overrides: dict[str, float] | None = None
    conn: Any | None = None
    timeout_per_instance: float | None = None
    wrapper_path: Path | None = None


@dataclass
class RecoveredProgram:
    """A best program recovered from an interrupted/failed run (B7).

    Returned by :meth:`EvolutionBackend.recover_best_from_checkpoint`. Carries
    just enough to materialize a solution program file from a run that never
    reached the normal ``programs/`` extraction path (FR-RUN-051).

    Attributes:
        program_id: The backend's internal id of the recovered best program.
        code: The program source code.
        score: The recovered ``combined_score`` (``None`` if unavailable).
        language: Program language (``"python"`` by default).
    """

    program_id: str
    code: str
    score: float | None = None
    language: str = "python"


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

    def recover_best_from_checkpoint(self, run_dir: Path) -> RecoveredProgram:
        """Recover the best program of an interrupted/failed run (B7).

        For backends that periodically checkpoint their population to disk
        (OpenEvolve), this reads the latest checkpoint and returns its tracked
        best program — letting ``solution extract --from-checkpoint`` promote
        a program from a run that never reached the normal ``programs/``
        extraction path (FR-RUN-051, DES-005 §7.2).

        The default implementation raises
        :class:`~revolver.core.exceptions.RecoveryNotSupportedError`. Because
        ``EvolutionBackend`` is a structural :class:`~typing.Protocol`, each
        concrete backend provides its own body: OpenEvolve implements
        checkpoint recovery; ShinkaEvolve (whose interrupted-run state is its
        ``programs.sqlite``, not a filesystem checkpoint) raises the
        not-supported error explicitly.

        Args:
            run_dir: Directory of the interrupted/failed run.

        Returns:
            The recovered best :class:`RecoveredProgram`.

        Raises:
            RecoveryNotSupportedError: The backend has no checkpoint recovery.
            CheckpointRecoveryError: Recovery is supported but no usable
                checkpoint exists yet (run too short) or it is unreadable.
        """
        from revolver.core.exceptions import RecoveryNotSupportedError

        raise RecoveryNotSupportedError(
            "This backend does not support best-of-checkpoint recovery."
        )

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
