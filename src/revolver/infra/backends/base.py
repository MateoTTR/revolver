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
from typing import Any, Literal, Protocol, runtime_checkable

from revolver.core.exceptions import ResourceError, ValidationError
from revolver.models.llm import EnsembleEntry, LLMEntry
from revolver.models.run import ResolvedConfig, TokenUsage

# Names accepted by :func:`get_backend`, in display order.
AVAILABLE_BACKENDS: tuple[str, ...] = ("openevolve", "shinka", "loongflow")

# Timed-out-instance policy baked into generated wrappers (FR-RUN-054,
# U13/#367). "penalize" is the deliberate v0.18 default; "drop" restores
# the pre-0.18 survivor-mean. The launch-point validator derives its
# accepted values from this alias (single source of truth).
OnTimeoutPolicy = Literal["penalize", "drop"]

# Grace period between SIGTERM and SIGKILL when reaping run children (A2 /
# #314). Shared by both backends' post-run teardown.
_CHILD_REAP_GRACE_SECONDS = 3.0

# Poll interval of the reap grace loop.
_REAP_POLL_INTERVAL_SECONDS = 0.1


# ── Reap helpers (S18-18 / #359) ──────────────────────────────────────────────
# Raw-PID adaptations of the S17a ``infra/evaluator_runner.py`` pgid helpers
# (``_own_pgid`` / ``_signal_child`` / ``_reap_process_group``). Those operate
# on a live ``multiprocessing`` process handle; the reap backstop only has
# bare PIDs recovered from ``/proc``, so the same logic is lifted here in PID
# form and gated by an explicit PID-reuse guard — the #320 wedge showed the
# snapshot-to-reap gap is unbounded (hours-to-days), so a bare PID must never
# be trusted to still name the same process.


def _direct_child_pids(pid: int | str) -> set[int]:
    """Return the direct-children PIDs of *pid* (Linux ``/proc``).

    Reads ``/proc/<pid>/task/*/children`` — the kernel-maintained list of
    child PIDs — which needs no third-party dependency. Returns an empty set
    on any platform without that interface (macOS, Windows) or on any read
    error, so callers degrade to a no-op rather than failing the run.
    """
    children: set[int] = set()
    task_dir = Path(f"/proc/{pid}/task")
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


def _pid_stat_fields(pid: int) -> tuple[str, int] | None:
    """Return ``(state, start_time)`` for *pid* from ``/proc/<pid>/stat``.

    ``start_time`` is stat field 22 (clock ticks since boot); together with
    the PID it identifies one process *incarnation*, so a recycled PID is
    detectable (same number, different start time). Returns ``None`` when the
    process is gone or ``/proc`` is unavailable/unparsable.
    """
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # Field 2 (comm) may contain spaces and parentheses; the kernel format is
    # unambiguous after the LAST ')'.
    rparen = stat_text.rfind(")")
    if rparen < 0:
        return None
    rest = stat_text[rparen + 1 :].split()
    try:
        # rest[0] = state (field 3); rest[19] = starttime (field 22).
        return rest[0], int(rest[19])
    except (IndexError, ValueError):
        return None


def _pid_start_time(pid: int) -> int | None:
    """Return *pid*'s start time (see :func:`_pid_stat_fields`), or ``None``."""
    fields = _pid_stat_fields(pid)
    return None if fields is None else fields[1]


def _pid_has_terminated(pid: int, start_time: int) -> bool:
    """Whether the process incarnation ``(pid, start_time)`` no longer runs.

    True when the PID is gone, was recycled (start-time mismatch — the
    original process is dead), or is a zombie (already dead, merely awaiting
    its parent's ``wait()`` — signalling it again is pointless).
    """
    fields = _pid_stat_fields(pid)
    if fields is None or fields[1] != start_time:
        return True
    return fields[0] == "Z"


def _signal_pid_if_unchanged(pid: int, start_time: int, sig: signal.Signals) -> None:
    """Send *sig* to *pid* only if it is still the snapshotted incarnation.

    PID-reuse guard: re-checking the ``/proc`` start time right before the
    signal narrows the reuse window to the instant between the check and
    ``os.kill`` (bare PIDs have no race-free pinning primitive); a recycled
    PID is never signalled.
    """
    if _pid_start_time(pid) != start_time:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.kill(pid, sig)


def _own_process_group() -> int | None:
    """Return the current process's own group id (``None`` off-POSIX)."""
    try:
        return os.getpgrp()
    except (AttributeError, OSError):
        return None


def _sweep_group(pgid: int, members: dict[int, int], sig: signal.Signals) -> bool:
    """Best-effort ``killpg`` of *pgid*, gated by member identity.

    The group is signalled only when at least one of *members* (``pid ->
    start_time`` captured at reap enumeration) verifiably still exists — if
    every member is gone or recycled, the group has dissolved and a
    same-numbered lookalike group must not be touched (PID-reuse guard).

    Returns ``True`` when no per-PID fallback is needed (group signalled, or
    verifiably empty); ``False`` when ``killpg`` itself failed and the caller
    should fall back to single-PID signalling of the members.
    """
    if not any(_pid_start_time(pid) == start for pid, start in members.items()):
        return True
    try:
        os.killpg(pgid, sig)
    except (AttributeError, OSError):
        return False
    return True


class ChildProcessReaperMixin:
    """Post-run child-process teardown shared by both backends (A2 / #314).

    An in-process engine ``run()`` (ShinkaEvolve's ``asyncio.run`` or
    OpenEvolve's ``ProcessPoolExecutor`` workers) can leave an evaluation
    child alive after the result is already persisted, keeping the CLI pinned
    at ~100% CPU. Both backends snapshot their child PIDs *before* the run and,
    in a ``finally`` block, reap any PID that appeared afterwards.

    Hoisted here (S17-04) so there is exactly one definition; ``ShinkaBackend``
    and ``OpenEvolveBackend`` inherit it. Hardened in S18-18 (#359): descendant
    enumeration is recursive (grandchildren are seen, e.g. the per-instance
    ``multiprocessing`` guard a Shinka eval job spawns — spike #320 §6),
    survivors are swept per process group (``killpg`` with a single-PID
    fallback, never our own group), and every signal is gated by a ``/proc``
    start-time identity check (PID-reuse guard). The reap is Linux-only (needs
    ``/proc``) and a no-op elsewhere, and never raises — it is a defensive
    backstop, not part of the run's correctness path.
    """

    @staticmethod
    def _current_child_pids() -> set[int]:
        """Return the PIDs of ALL live descendants of this process (Linux).

        S18-18 (#359): recursive — walks ``/proc/<pid>/task/*/children``
        starting from ``/proc/self``, so grandchildren are enumerated, not
        just direct children (a per-PID kill of a direct child would orphan
        them — the observed #320 process tree, spike §6). Returns an empty
        set on any platform without that interface (macOS, Windows) or on
        any read error, so the caller's reap backstop simply becomes a no-op
        rather than failing the run.
        """
        descendants: set[int] = set()
        frontier: list[int | str] = ["self"]
        while frontier:
            for child_pid in _direct_child_pids(frontier.pop()):
                if child_pid not in descendants:
                    descendants.add(child_pid)
                    frontier.append(child_pid)
        return descendants

    def _reap_run_children(self, pre_run_children: set[int]) -> None:
        """Terminate descendants that outlived the engine run (A2, S18-18).

        Survivors are re-derived from ``/proc`` at reap time — the pre-run
        snapshot only *excludes* pre-existing processes and is never used as
        a kill list: the snapshot-to-reap gap is unbounded (#320 wedge:
        hours-to-days), so a snapshot-era PID may long since belong to an
        unrelated process. Each survivor's identity ``(pid, start_time)`` is
        captured once at enumeration and re-verified before every signal
        (PID-reuse guard, ``/proc/<pid>/stat`` field 22).

        Kill strategy (S17a pgid helpers, adapted): survivors living in a
        process group of their own — i.e. NOT the orchestrator's group — are
        swept per-group via ``os.killpg`` (SIGTERM → grace → SIGKILL), so a
        whole evaluator session dies together; survivors sharing the
        orchestrator's group, or whose group cannot be determined, or whose
        ``killpg`` fails, fall back to single-PID signalling. Our own group
        is never signalled. The run's result is already persisted when the
        engine ``run()`` returns, so this cannot truncate persistence. No-op
        on platforms without ``/proc`` child enumeration.
        """
        survivors = self._current_child_pids() - pre_run_children
        if not survivors:
            return

        # PID-reuse guard: pin each survivor to its /proc start time. A PID
        # whose stat vanished between enumeration and here is already gone.
        targets: dict[int, int] = {}
        for pid in survivors:
            start_time = _pid_start_time(pid)
            if start_time is not None:
                targets[pid] = start_time
        if not targets:
            return

        # Partition into foreign process groups (killpg sweep) and single
        # PIDs (own/unknown group — per-PID signalling only).
        own_pgid = _own_process_group()
        groups: dict[int, dict[int, int]] = {}
        singles: dict[int, int] = {}
        for pid, start_time in targets.items():
            pgid: int | None = None
            with contextlib.suppress(OSError):
                pgid = os.getpgid(pid)
            if pgid is not None and own_pgid is not None and pgid != own_pgid:
                groups.setdefault(pgid, {})[pid] = start_time
            else:
                singles[pid] = start_time

        self._signal_targets(groups, singles, signal.SIGTERM)

        deadline = time.monotonic() + _CHILD_REAP_GRACE_SECONDS
        remaining = dict(targets)
        while remaining and time.monotonic() < deadline:
            for pid in list(remaining):
                if _pid_has_terminated(pid, remaining[pid]):
                    del remaining[pid]
            if remaining:
                time.sleep(_REAP_POLL_INTERVAL_SECONDS)
        if not remaining:
            return

        groups = {
            pgid: live
            for pgid, members in groups.items()
            if (live := {pid: st for pid, st in members.items() if pid in remaining})
        }
        singles = {pid: st for pid, st in singles.items() if pid in remaining}
        self._signal_targets(groups, singles, signal.SIGKILL)

    @staticmethod
    def _signal_targets(
        groups: dict[int, dict[int, int]],
        singles: dict[int, int],
        sig: signal.Signals,
    ) -> None:
        """One signalling pass over the partitioned reap targets.

        Foreign groups are swept via :func:`_sweep_group`; a group whose
        ``killpg`` fails degrades to per-PID signalling of its (identity-
        verified) members — the single-PID fallback. Single PIDs are always
        signalled individually, identity-verified.
        """
        for pgid, members in groups.items():
            if not _sweep_group(pgid, members, sig):
                for pid, start_time in members.items():
                    _signal_pid_if_unchanged(pid, start_time, sig)
        for pid, start_time in singles.items():
            _signal_pid_if_unchanged(pid, start_time, sig)


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
        on_timeout: Timed-out instance policy baked into the generated
            wrapper (FR-RUN-054): ``"penalize"`` (default — the deliberate
            v0.18 fitness-landscape flip) counts the instance at
            *timeout_score* in the metric mean; ``"drop"`` excludes it,
            restoring the pre-0.18 survivor-mean. Parsed and validated at
            the shared launch point in ``core.run`` on both backends.
        timeout_score: Finite penalty score a timed-out instance contributes
            under ``on_timeout="penalize"`` (FR-RUN-054). Default ``0.0``.
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
    on_timeout: OnTimeoutPolicy = "penalize"
    timeout_score: float = 0.0
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
class RankedProgram:
    """A population program addressed by rank or program id (FR-SOL-021).

    Returned by :meth:`EvolutionBackend.extract_ranked_program`. Carries
    enough to materialize ``programs/rank-<N>.py`` on demand and to record
    the promoted solution's ``best_score`` (top-N promotion, #299).

    Attributes:
        program_id: The backend's internal id of the program.
        code: The program source code.
        rank: 1-based rank of the program in the backend's scored
            population (``combined_score`` descending — the same ordering
            ``run population`` displays for scored programs).
        score: The program's ``combined_score`` (``None`` if unavailable).
        language: Program language (``"python"`` by default).
    """

    program_id: str
    code: str
    rank: int
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

    def validate_seed_metrics(
        self,
        config: dict[str, Any],
        seed_metrics: dict[str, float] | None,
    ) -> None:
        """Fail fast when the seed's metrics cannot feed the backend's config.

        Called by the orchestrator right after the pre-flight evaluation, on
        both launch and resume (U8 / FR-RUN-056, DES-005 §4.4) — and skipped
        whenever the pre-flight itself is skipped (empty dataset). OpenEvolve
        raises :class:`~revolver.core.exceptions.ValidationError` when a
        metric named in ``database.feature_dimensions`` is absent or
        non-numeric in the seed's pre-flight metrics (builtins computed
        inside the engine are allowlisted); ShinkaEvolve is a no-op (its only
        metric contract is ``combined_score``). Failing here aborts before
        iteration 0 — without the hook, a missing feature metric only
        crashes at the engine's seed-add.

        The default implementation is a **no-op**. Because ``EvolutionBackend``
        is a structural :class:`~typing.Protocol` (not subclassed), concrete
        backends without seed-metric requirements provide their own explicit
        no-op rather than inheriting this body.

        Args:
            config: The built engine config dict (as returned by
                :meth:`build_config`).
            seed_metrics: The seed's pre-flight ``InstanceTestResult.metrics``
                (``None`` when the evaluator reported no metrics).

        Raises:
            ValidationError: When a declared metric is absent or non-numeric
                in *seed_metrics* (exit 1, before iteration 0).
        """
        return None

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

    def extract_ranked_program(
        self,
        run_dir: Path,
        rank: int | None = None,
        program_id: str | None = None,
    ) -> RankedProgram:
        """Read an arbitrary-ranked or id-addressed population program.

        Serves top-N solution promotion (FR-SOL-021, #299): ``solution
        extract --rank N`` / ``--program-id <id>`` on a backend advertising
        :attr:`BackendCapabilities.top_n_extraction`. This is a **read-only**
        lookup — the orchestrator (``core.solution.extract_solution``)
        materializes the returned code to ``programs/rank-<N>.py`` only
        after its alias/duplicate validation passes, which makes the path
        retroactive on old run dirs with no layout change.

        The default implementation raises
        :class:`~revolver.core.exceptions.ValidationError`. Because
        ``EvolutionBackend`` is a structural :class:`~typing.Protocol`, each
        concrete backend provides its own body: ShinkaEvolve reads its
        ``programs.sqlite`` store; OpenEvolve raises the not-supported error
        explicitly (``top_n_extraction=False`` — consciously deferred,
        ADR-007 v0.18 amendment).

        Args:
            run_dir: Directory of the completed run.
            rank: 1-based rank in the scored population (``combined_score``
                descending). Exactly one of *rank*/*program_id* is required.
            program_id: Backend program id, resolved to its rank in the
                same ordering.

        Returns:
            The addressed :class:`RankedProgram`.

        Raises:
            ValidationError: The backend has no top-N extraction; neither or
                both of *rank*/*program_id* were given; the program store is
                missing/unreadable; the rank exceeds the scored population;
                or the program id is unknown or unscored.
        """
        from revolver.core.exceptions import ValidationError

        raise ValidationError(f"Top-N extraction is not supported on backend '{self.name}'.")

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
    from revolver.infra.backends.loongflow import LoongFlowBackend
    from revolver.infra.backends.openevolve import OpenEvolveBackend
    from revolver.infra.backends.shinka import ShinkaBackend

    registry: dict[str, Callable[[], EvolutionBackend]] = {
        "openevolve": OpenEvolveBackend,
        "shinka": ShinkaBackend,
        "loongflow": LoongFlowBackend,
    }
    # Guard against the registry and the display constant drifting apart.
    assert set(registry) == set(AVAILABLE_BACKENDS)
    factory = registry.get(name)
    if factory is None:
        available = ", ".join(sorted(registry))
        raise ValidationError(f"Unknown backend '{name}'. Available backends: {available}.")
    return factory()
