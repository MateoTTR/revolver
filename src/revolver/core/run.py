"""Core run logic: orchestration, resume, list, info.

Implements the full domain layer for ``revolver run`` commands:
- ``launch_run()`` — full orchestration (DES-005 section 2.1)
- ``resume_run()`` — resume from checkpoint (DES-005 section 2.3)
- ``get_run_status()`` — active/latest run status (DES-005 section 2.2)
- ``list_runs()`` — query with filters (DES-005 section 2.4)
- ``get_run_info()`` — detailed run info (DES-005 section 2.5)

Engine-specific work (config build, wrapper generation, launch/resume,
progress/population parsing, token strategy) is mediated through the
``EvolutionBackend`` resolved via ``get_backend()`` (ADR-007, Sprint 013
PR-C). The orchestrator keeps owning the run lifecycle: DB records, lock
files, the HTTP token proxy, the checkpoint-staging precheck, and the
config snapshot (persisted *before* ``backend.launch()``/``resume()``,
which overwrite ``config['output_dir']``).

Traceable to: DES-005 (incl. §14.1), ADR-006, ADR-007, FR-RUN-001..048.
"""

from __future__ import annotations

import contextlib
import copy
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
from typing import Any, Literal

import yaml

from revolver.core.dataset import resolve_dataset_path, verify_dataset_integrity
from revolver.core.exceptions import (
    ActiveRunError,
    ExternalError,
    IntegrityError,
    ProjectNotFoundError,
    RevolverError,
    ValidationError,
)
from revolver.core.llm import resolve_llm_or_ensemble
from revolver.infra.backends import get_backend
from revolver.infra.backends.base import (
    BackendRunResult,
    BackendRunSpec,
    EvolutionBackend,
)
from revolver.infra.backends.openevolve import (
    # DEPRECATED shim re-exports: wrapper generation moved into
    # OpenEvolveBackend in Sprint 013 PR-C (ADR-007); valid-program
    # counting moved behind backend.count_valid() in Sprint 014 PR-B
    # (S14-06); the wrapper filename moved behind backend.wrapper_filename
    # in Sprint 014 PR-C (S14-13). These aliases keep pre-existing
    # ``core.run`` imports working. Scheduled for removal in Sprint 015
    # (grep marker: DEPRECATED shim).
    _WRAPPER_TEMPLATE as _WRAPPER_TEMPLATE,
    # Engine helpers still owned by the orchestrator: the resume
    # checkpoint-staging precheck must run in core (fail fast BEFORE the
    # run-record insert — DES-005 §14.1). count_valid_programs,
    # generate_wrapper and WRAPPER_FILENAME are DEPRECATED shim
    # re-exports only.
    EVALUATOR_FILENAME,
    WRAPPER_FILENAME as WRAPPER_FILENAME,
    count_valid_programs as count_valid_programs,
    find_latest_checkpoint,
    generate_wrapper as generate_wrapper,
    resolve_api_keys,
    revolver_env,
)
from revolver.infra.db import (
    count_evals_for_run,
    count_solutions_for_run,
    delete_run as db_delete_run,
    get_dataset,
    get_dataset_compat,
    get_global_db,
    get_latest_run,
    get_llm,
    get_problem_version,
    get_project_db,
    get_resume_chain,
    get_run,
    get_solutions_for_run,
    insert_run,
    insert_solution,
    list_datasets as db_list_datasets,
    list_problem_versions as db_list_problem_versions,
    list_runs as db_list_runs,
    update_run_generation_time,
    update_run_status,
    update_run_tokens,
    update_run_valid_iterations,
)
from revolver.infra.evaluator_runner import run_instance as eval_run_instance
from revolver.infra.store import (
    PROBLEM_DIR,
    REVOLVER_DIR,
    ProjectNotFoundError as StoreProjectNotFoundError,
    copy_run_file,
    create_run_dir,
    delete_run_dir,
    find_project_root,
    get_active_locks,
    get_run_dir,
    read_run_manifest,
    remove_run_lock,
    write_run_lock,
    write_run_manifest,
)
from revolver.infra.token_proxy import TokenCountingProxy, estimate_cost
from revolver.models.llm import EnsembleEntry, LLMEntry
from revolver.models.run import (
    ProgramEntry,
    RunConfig,
    RunInfo,
    RunManifest,
    RunResult,
    RunStatus,
    RunSummary,
    SolutionResult,
    TokenUsage as PydanticTokenUsage,
)

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "openevolve"

# Revolver default when neither the CLI nor the problem config provides an
# iteration count. The orchestrator owns this single resolution point
# (S14-05); backends never apply their own fallback on the run path.
DEFAULT_ITERATIONS = 10


def _determine_run_status(
    valid_iters: int | None, total_iters: int
) -> Literal["failed", "completed_with_errors", "completed"]:
    """Determine final run status based on valid iteration count.

    Returns ``"failed"`` if no valid iterations were produced,
    ``"completed_with_errors"`` if some but not all iterations were valid,
    and ``"completed"`` if all iterations produced valid programs.

    Args:
        valid_iters: Number of iterations that produced valid programs,
            or ``None`` if the count could not be determined.
        total_iters: Total number of iterations executed.

    Returns:
        One of ``"failed"``, ``"completed_with_errors"``, or ``"completed"``.
    """
    if valid_iters is None or valid_iters == 0:
        return "failed"
    if valid_iters < total_iters:
        return "completed_with_errors"
    return "completed"


def _determine_crash_status(
    run_dir: Path,
    iterations: int,
    backend: EvolutionBackend | None = None,
) -> tuple[Literal["failed", "completed_with_errors"], int | None]:
    """Determine status for a run that crashed (engine exception).

    Checks whether the run produced any valid programs before the crash
    by delegating the counting to the run's backend
    (:meth:`EvolutionBackend.count_valid` — ADR-007 D1, S14-06). If valid
    programs exist, the status is derived from
    :func:`_determine_run_status`; otherwise ``"failed"`` is returned.

    Args:
        run_dir: Path to the run directory.
        iterations: Total number of iterations requested for the run.
        backend: Resolved evolution backend of the crashed run. Defaults
            to the OpenEvolve backend for backward compatibility.

    Returns:
        A tuple of (status, valid_iterations) where status is
        ``"failed"`` or ``"completed_with_errors"`` and valid_iterations
        is the count of valid programs found (or ``None`` if none were
        found).
    """
    if backend is None:
        backend = get_backend(DEFAULT_BACKEND)
    valid_iters: int | None = None
    try:
        valid_iters = backend.count_valid(run_dir)
    except Exception:
        # Crash-status determination runs inside exception handlers — a
        # backend counting failure must never mask the original error.
        logger.debug("backend.count_valid() failed during crash handling", exc_info=True)

    if valid_iters is not None and valid_iters > 0:
        status = _determine_run_status(valid_iters, iterations)
        # A crash can never be "completed" — at best "completed_with_errors"
        if status == "completed":
            return "completed_with_errors", valid_iters
        return status, valid_iters
    return "failed", valid_iters


# Shared wording for the unproductive-run signal so the run-time warning and
# the ``run info`` warning line stay in lockstep (#302). "evolved child
# programs" (not "successful"): the flag fires only when zero children of any
# kind were produced — count_evolved_children counts every llm_result row,
# including ones that failed evaluation.
UNPRODUCTIVE_RUN_MESSAGE = (
    "run produced no evolved child programs (only the initial program(s) remain)"
)


def _apply_unproductive_override(
    backend: EvolutionBackend,
    run_dir: Path,
    iterations: int,
    final_status: Literal["failed", "completed_with_errors", "completed"],
    *,
    quiet: bool,
) -> Literal["failed", "completed_with_errors", "completed"]:
    """Downgrade an unproductive run to ``completed_with_errors`` (#302).

    A run can complete without producing a single evolved child program —
    every proposal failed, only the initial seed(s) remain — yet
    :func:`_determine_run_status` may still report ``"completed"`` (the
    seeds count as valid programs). Backends that can tell children from
    seeds (:meth:`EvolutionBackend.count_evolved_children` returns an int)
    let us detect this and flag it distinctly, with a user-visible warning.
    Backends returning ``None`` (e.g. OpenEvolve) are left untouched, as are
    already-``"failed"`` runs and zero-iteration (dry) runs.

    Returns:
        ``"completed_with_errors"`` when the run is unproductive, else the
        unchanged *final_status*.
    """
    if final_status == "failed" or iterations <= 0:
        return final_status
    try:
        children = backend.count_evolved_children(run_dir)
    except Exception:
        logger.debug("backend.count_evolved_children() failed", exc_info=True)
        return final_status
    if children != 0:
        return final_status
    if not quiet:
        sys.stderr.write(f"Warning: {UNPRODUCTIVE_RUN_MESSAGE}.\n")
    return "completed_with_errors"


# ── ID generation (FR-RUN-007) ────────────────────────────────────────────────


def generate_run_id() -> str:
    """Generate a unique run ID in format ``run-YYYYMMDD-HHMMSS``.

    Returns:
        A run ID string like ``"run-20260310-143000"``.
    """
    now = datetime.now(UTC)
    return f"run-{now.strftime('%Y%m%d-%H%M%S')}"


def generate_solution_id() -> str:
    """Generate a unique solution ID in format ``sol-YYYYMMDD-HHMMSS``.

    Returns:
        A solution ID string like ``"sol-20260310-143000"``.
    """
    now = datetime.now(UTC)
    return f"sol-{now.strftime('%Y%m%d-%H%M%S')}"


# ── LLM/Ensemble snapshot helpers (S11-08) ──────────────────────────────────


def _build_llm_snapshot(
    llm_or_ensemble: LLMEntry | EnsembleEntry,
    global_conn: Any,
) -> tuple[str, str, str]:
    """Build llm_type, llm_model, and llm_snapshot JSON for a run record.

    Args:
        llm_or_ensemble: Resolved LLM or ensemble entry.
        global_conn: Global DB connection (for resolving ensemble member LLMs).

    Returns:
        A tuple of ``(llm_type, llm_model, llm_snapshot_json)``.
    """
    if isinstance(llm_or_ensemble, EnsembleEntry):
        members_snapshot: list[dict[str, Any]] = []
        model_names: list[str] = []
        for member in llm_or_ensemble.members:
            member_llm = get_llm(global_conn, member.llm_name)
            entry: dict[str, Any] = {
                "name": member.llm_name,
                "model": member_llm.model if member_llm else member.llm_name,
                "weight": member.weight,
            }
            if member.temperature is not None:
                entry["temperature"] = member.temperature
            if member.max_tokens is not None:
                entry["max_tokens"] = member.max_tokens
            members_snapshot.append(entry)
            model_names.append(member_llm.model if member_llm else member.llm_name)

        snapshot = {
            "type": "ensemble",
            "name": llm_or_ensemble.name,
            "members": members_snapshot,
        }
        llm_model_str = ",".join(model_names)
        return "ensemble", llm_model_str, json.dumps(snapshot)

    # Single LLM
    snapshot_single: dict[str, Any] = {
        "type": "single",
        "name": llm_or_ensemble.name,
        "model": llm_or_ensemble.model,
    }
    if llm_or_ensemble.temperature is not None:
        snapshot_single["temperature"] = llm_or_ensemble.temperature
    if llm_or_ensemble.max_tokens is not None:
        snapshot_single["max_tokens"] = llm_or_ensemble.max_tokens
    return "single", llm_or_ensemble.model, json.dumps(snapshot_single)


# ── Project root resolution ──────────────────────────────────────────────────


def _resolve_project_root(project_root: Path | None) -> Path:
    """Resolve and return the project root directory.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The resolved project root path.

    Raises:
        ProjectNotFoundError: If no ``.revolver/`` directory is found
            in the hierarchy (caught by ``cli_error_boundary`` to show
            a user-friendly workspace message).
    """
    try:
        return find_project_root(project_root or Path.cwd())
    except StoreProjectNotFoundError as exc:
        raise ProjectNotFoundError(str(exc)) from exc


# ── Smart defaults (S8a-10, S8a-11) ──────────────────────────────────────────


def resolve_default_version(
    project_root: Path | None = None,
) -> str:
    """Auto-select the problem version when exactly one exists.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The single version tag.

    Raises:
        RevolverError: If zero or multiple versions exist.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    proj_conn = get_project_db(db_path)
    try:
        versions = db_list_problem_versions(proj_conn)
    finally:
        proj_conn.close()

    if len(versions) == 0:
        raise RevolverError(
            "No problem versions found. Create one with 'revolver problem version'."
        )
    if len(versions) == 1:
        return versions[0].tag
    # Multiple versions: list them in the error message
    tags = ", ".join(v.tag for v in versions)
    raise RevolverError(f"Multiple problem versions exist ({tags}). Specify one with --version.")


def resolve_default_dataset(
    project_root: Path | None = None,
) -> str:
    """Auto-select the dataset when exactly one train dataset exists.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        The single train dataset name.

    Raises:
        RevolverError: If zero or multiple train datasets exist.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    proj_conn = get_project_db(db_path)
    try:
        all_datasets = db_list_datasets(proj_conn)
    finally:
        proj_conn.close()

    train_datasets = [d for d in all_datasets if d.split == "train"]

    if len(train_datasets) == 0:
        raise RevolverError(
            "No train datasets found. Register one with 'revolver dataset add --split train'."
        )
    if len(train_datasets) == 1:
        return train_datasets[0].name
    # Multiple train datasets: list them in the error message
    names = ", ".join(d.name for d in train_datasets)
    raise RevolverError(f"Multiple train datasets exist ({names}). Specify one with --dataset.")


# ── Post-run failure handler ──────────────────────────────────────────────────


def _handle_post_run_failure(
    proj_conn: Any,
    root: Path,
    run_id: str,
    run_dir: Path,
    generation_time_s: float,
    exc: BaseException | None,
) -> None:
    """Handle a post-processing failure after OE completed successfully.

    Sets the run status to ``completed_with_errors``, writes an error log
    to ``run-error.log`` in the run directory, and removes the lock file.
    All steps are best-effort to avoid masking the original exception.

    Args:
        proj_conn: An open project database connection.
        root: Project root directory.
        run_id: The run ID to update.
        run_dir: The run's output directory.
        generation_time_s: Measured OE generation time in seconds.
        exc: The exception that caused the post-processing failure.
    """
    # 1. Write error log (best-effort)
    error_log_path = run_dir / "run-error.log"
    with contextlib.suppress(Exception):
        error_log_path.write_text(
            f"Post-run processing error at {datetime.now(UTC).isoformat()}:\n"
            f"{type(exc).__name__}: {exc}\n"
        )

    # 2. Update status to completed_with_errors (best-effort)
    try:
        update_run_generation_time(
            proj_conn, run_id, generation_time_s, status="completed_with_errors"
        )
    except Exception:
        with contextlib.suppress(Exception):
            update_run_status(proj_conn, run_id, "completed_with_errors")

    # 3. Remove lock file (best-effort)
    with contextlib.suppress(Exception):
        remove_run_lock(root, run_id)


# ── launch_run (DES-005 §2.1) ────────────────────────────────────────────────


def launch_run(
    config: RunConfig,
    project_root: Path | None = None,
    *,
    quiet: bool = False,
) -> RunResult:
    """Launch a full evolution run on the selected backend.

    Orchestrates the entire run lifecycle per DES-005 section 2.1:
    validate inputs, generate wrapper, build the engine config, launch,
    collect results, create solution, write manifest. Engine-specific
    steps are mediated by the backend selected via ``config.backend``
    (ADR-007, FR-RUN-047).

    Args:
        config: Run configuration with problem version, LLM, dataset,
            backend, etc.
        project_root: Explicit project root, or ``None`` to auto-detect.
        quiet: Suppress informational stderr messages (e.g. in --quiet/--json mode).

    Returns:
        A :class:`RunResult` with run ID, solution, programs, and token usage.

    Raises:
        ValidationError: If ``config.backend`` is not a registered
            backend (exit code 1).
        BackendUnavailableError: If the selected backend is not
            installed (exit code 3).
        RevolverError: On validation failures (unknown LLM, missing version).
        IntegrityError: On dataset integrity mismatch (exit code 2).
        ExternalError: On evolution engine failure (exit code 4).
    """
    # 0. Resolve the evolution backend (ADR-007 D1; unknown name → exit 1)
    backend: EvolutionBackend = get_backend(config.backend)

    # 1. Resolve project root
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"

    proj_conn = get_project_db(db_path)
    global_conn = get_global_db()
    try:
        # 2. Validate problem version exists
        pv = get_problem_version(proj_conn, config.problem_version)
        if pv is None:
            raise RevolverError(f"Problem version '{config.problem_version}' not found.")

        # 3. Resolve LLM or ensemble (global DB) — S11-08
        llm_or_ensemble = resolve_llm_or_ensemble(config.llm_name, global_conn)
        ensemble: EnsembleEntry | None = None
        if isinstance(llm_or_ensemble, EnsembleEntry):
            ensemble = llm_or_ensemble
            if not ensemble.members:
                raise RevolverError(f"Ensemble '{config.llm_name}' has no members.")
            # Use the first member's LLM as the "primary" for shared config
            first_member_llm = get_llm(global_conn, ensemble.members[0].llm_name)
            if first_member_llm is None:
                raise RevolverError(
                    f"Ensemble member LLM '{ensemble.members[0].llm_name}' not found."
                )
            llm: LLMEntry = first_member_llm
        else:
            llm = llm_or_ensemble

        # 4. Validate dataset exists
        ds = get_dataset(proj_conn, config.dataset_name)
        if ds is None:
            raise RevolverError(f"Dataset '{config.dataset_name}' not found.")

        # 5. FR-RUN-002: warn if dataset split != train
        if ds.split and ds.split != "train":
            sys.stderr.write(
                f"Warning: dataset '{ds.name}' has split='{ds.split}' "
                f"(expected 'train'). Proceeding anyway.\n"
            )

        # 6. FR-RUN-003: warn if dataset not compatible with problem version
        compat_versions = get_dataset_compat(proj_conn, config.dataset_name)
        if compat_versions and config.problem_version not in compat_versions:
            sys.stderr.write(
                f"Warning: dataset '{ds.name}' is not marked as compatible "
                f"with problem version '{config.problem_version}'. "
                f"Proceeding anyway.\n"
            )

        # 7. FR-RUN-004: verify dataset integrity
        integrity = verify_dataset_integrity(root, config.dataset_name)
        if not integrity.is_valid:
            raise IntegrityError(
                f"Dataset '{ds.name}' integrity check failed: "
                f"{len(integrity.mismatches)} mismatches, "
                f"{len(integrity.missing)} missing, "
                f"{len(integrity.extra)} extra files."
            )

        # Resolve snapshot dir and dataset path
        snapshot_dir = root / REVOLVER_DIR / PROBLEM_DIR / config.problem_version

        # Resolve dataset path
        dataset_path = resolve_dataset_path(root, config.dataset_name)

        # Read problem.md if present (FR-PRB-015)
        problem_md_path = snapshot_dir / "problem.md"
        problem_description: str | None = None
        if problem_md_path.exists():
            problem_description = problem_md_path.read_text(encoding="utf-8")

        # Build the engine config through the backend (ADR-007 D1).
        # A not-installed stub backend raises BackendUnavailableError
        # here (exit 3), before any side effect.
        spec = BackendRunSpec(
            snapshot_dir=snapshot_dir,
            llm=llm,
            iterations=config.iterations,
            config_overrides=config.config_overrides or None,
            problem_description=problem_description,
            temperature=config.temperature,
            parallel=config.parallel,
            rewrite_mode=config.rewrite_mode,
            ensemble=ensemble,
            conn=global_conn,
        )
        oe_config = backend.build_config(spec)

        # Single-owner iterations resolution (S14-05, ADR-007 D4): the
        # orchestrator owns the canonical value — CLI flag first, then the
        # backend-neutral reading of the built config (max_iterations on
        # OE, num_generations on Shinka), then the Revolver default.
        iterations = (
            config.iterations
            or backend.resolved_config(oe_config).iterations
            or DEFAULT_ITERATIONS
        )
        spec.iterations = iterations

        # Build LLM snapshot for traceability (S11-08)
        llm_type, llm_model_str, llm_snapshot_json = _build_llm_snapshot(
            llm_or_ensemble, global_conn
        )

        # 8. If dry_run: return early with config, no side effects
        if config.dry_run:
            # Convert config_overrides list[str] to dict for display
            overrides_dict: dict[str, Any] | None = None
            if config.config_overrides:
                overrides_dict = {}
                for override in config.config_overrides:
                    if "=" in override:
                        key, val = override.split("=", 1)
                        overrides_dict[key.strip()] = val.strip()
            resolved = backend.resolved_config(oe_config, config_overrides=overrides_dict)
            return RunResult(
                run_id="dry-run",
                solution=SolutionResult(
                    solution_id="dry-run",
                    run_id="dry-run",
                    rank=1,
                    best_score=None,
                ),
                programs_stored=0,
                problem_version=config.problem_version,
                llm=config.llm_name,
                dataset=config.dataset_name,
                iterations=iterations,
                generation_time_s=0.0,
                token_usage=None,
                resolved_config=resolved,
            )

        # 9. Generate run_id, create run dir
        run_id = generate_run_id()
        run_dir = create_run_dir(root, run_id)
        spec.run_dir = run_dir

        # 10. Generate wrapper evaluator (via the backend — ADR-007 D1)
        # Revolver config uses "evaluation:" section; OE uses "evaluator:".
        # Check both keys, preferring "evaluation" (user-facing).
        eval_cfg = oe_config.get("evaluation", oe_config.get("evaluator", {}))
        timeout_per_instance: float | None = (
            eval_cfg.get("timeout_per_instance") if isinstance(eval_cfg, dict) else None
        )
        spec.timeout_per_instance = timeout_per_instance
        wrapper_path = backend.generate_wrapper(spec)
        spec.wrapper_path = wrapper_path

        # Set output dir in config BEFORE the snapshot is persisted:
        # backend.launch() overwrites config['output_dir'] (same value),
        # and the stored snapshot must keep containing it (DES-005 §14.1).
        # The directory name is backend-owned (S14-05, ADR-007 D1).
        engine_output_dir = run_dir / backend.default_output_subdir
        engine_output_dir.mkdir(exist_ok=True)
        oe_config["output_dir"] = str(engine_output_dir)

        # 13. FR-RUN-014/015: check concurrency (lock files for local LLM)
        if llm.source == "local":
            active_locks = get_active_locks(root)
            for lock_data in active_locks:
                if lock_data.get("llm_source") == "local":
                    lock_pid = lock_data.get("pid")
                    if lock_pid and _is_pid_alive(int(lock_pid)):
                        raise RevolverError(
                            f"A local LLM run is already active "
                            f"(run={lock_data.get('run_id')}, PID={lock_pid}). "
                            f"Local LLM runs must execute sequentially (FR-RUN-014)."
                        )

        # 14. Insert run record in DB (status="running")
        # Store the UNRESOLVED config in the snapshot — api_key_env names
        # are safe to persist; resolved secrets are not.
        now = datetime.now(UTC)
        config_snapshot_str = yaml.dump(oe_config, default_flow_style=False)
        insert_run(
            proj_conn,
            run_id=run_id,
            problem_version=config.problem_version,
            llm=config.llm_name,
            dataset=config.dataset_name,
            iterations=iterations,
            problem_hash=pv.hash,
            dataset_hash=ds.global_hash,
            llm_model=llm_model_str,
            created_at=now,
            status="running",
            config_snapshot=config_snapshot_str,
            llm_type=llm_type,
            llm_snapshot=llm_snapshot_json,
            backend=backend.name,
        )

        # Resolve api_key_env → api_key on a deep copy for runtime use only.
        oe_config_resolved = resolve_api_keys(copy.deepcopy(oe_config))

        # 15. Write lock file
        lock_data = {
            "run_id": run_id,
            "pid": os.getpid(),
            "llm_source": llm.source,
            "llm_name": config.llm_name,
            "started_at": now.isoformat(),
        }
        write_run_lock(root, run_id, lock_data)

        # Start token proxy when the backend measures tokens over HTTP
        # (ADR-007 D2) and the LLM has a base_url. The proxy lifecycle
        # stays owned by the orchestrator.
        proxy: TokenCountingProxy | None = None
        if backend.wants_http_proxy() and llm.base_url:
            proxy = TokenCountingProxy(llm.base_url)
            proxy_url = proxy.start()
            # Rewrite config's llm.api_base to proxy
            if "llm" not in oe_config_resolved:
                oe_config_resolved["llm"] = {}
            oe_config_resolved["llm"]["api_base"] = proxy_url

        oe_completed = False
        generation_time_s = 0.0
        run_output: BackendRunResult | None = None

        try:
            # Set env vars via revolver_env()
            env_vars = {
                "REVOLVER_DATASET_DIR": str(dataset_path),
                "REVOLVER_INSTANCE_LOG": str(run_dir / "instance_log.db"),
                "REVOLVER_EVAL_LOG": str(run_dir / "eval_log.db"),
            }

            with revolver_env(env_vars):
                # Record start time
                start_time = time.monotonic()

                # Pre-flight check: evaluate initial program on first instance
                initial_program = snapshot_dir / "initial_program.py"
                preflight_instances = sorted(
                    (
                        p
                        for p in dataset_path.iterdir()
                        if not p.name.startswith(".") and p.is_file()
                    ),
                    key=lambda p: p.name,
                )
                if preflight_instances:
                    first_instance = preflight_instances[0]
                    preflight_result = eval_run_instance(
                        evaluator_path=wrapper_path,
                        program_path=initial_program,
                        instance_path=first_instance,
                        timeout_s=60.0,
                    )
                    if preflight_result.status != "pass":
                        raise RevolverError(
                            f"Pre-flight check failed: initial program evaluation "
                            f"{preflight_result.status} on {first_instance.name}."
                            + (
                                f" Error: {preflight_result.error}"
                                if preflight_result.error
                                else ""
                            )
                            + " Fix the evaluator or initial program before "
                            "running evolution."
                        )
                    # Log success
                    score_info = ""
                    if preflight_result.metrics:
                        cs = preflight_result.metrics.get("combined_score")
                        if cs is not None:
                            score_info = f", score={cs:.4f}"
                        if cs == 0.0:
                            sys.stderr.write(
                                f"Warning: pre-flight check passed but score=0.0 "
                                f"on {first_instance.name}. Evolution may not "
                                f"produce improvements.\n"
                            )
                    sys.stderr.write(
                        f"Pre-flight check passed ({first_instance.name}{score_info}).\n"
                    )

                # Launch the engine with the resolved config (secrets
                # resolved at runtime) through the backend (ADR-007 D1).
                run_output = backend.launch(spec, oe_config_resolved)

                # Record end time
                end_time = time.monotonic()
                generation_time_s = end_time - start_time

            # The engine completed successfully — any exception below is
            # a post-processing failure, not an engine interruption.
            oe_completed = True

            # Token collection (ADR-007 D2): HTTP proxy when the backend
            # wants it, engine-native accounting otherwise.
            token_usage_model: PydanticTokenUsage | None = None
            if proxy is not None:
                proxy_usage = proxy.stop()
                estimated = estimate_cost(
                    proxy_usage.prompt_tokens,
                    proxy_usage.completion_tokens,
                    llm.input_cost_per_mtok,
                    llm.output_cost_per_mtok,
                )
                token_usage_model = PydanticTokenUsage(
                    prompt_tokens=proxy_usage.prompt_tokens,
                    completion_tokens=proxy_usage.completion_tokens,
                    estimated_cost_usd=estimated,
                )
                # Update run with tokens
                update_run_tokens(
                    proj_conn,
                    run_id,
                    proxy_usage.prompt_tokens,
                    proxy_usage.completion_tokens,
                )
            else:
                native_usage = backend.collect_token_usage(run_dir)
                if native_usage is not None:
                    token_usage_model = native_usage
                    update_run_tokens(
                        proj_conn,
                        run_id,
                        native_usage.prompt_tokens,
                        native_usage.completion_tokens,
                    )

            # Collect programs from the engine output dir
            programs = _collect_programs(engine_output_dir, run_dir / "programs")

            # Count valid iterations via the backend (ADR-007 D1, S14-06)
            valid_iters: int | None = backend.count_valid(run_dir)
            if valid_iters is not None:
                update_run_valid_iterations(proj_conn, run_id, valid_iters)

            # Generate solution_id, insert solution (rank=1) in DB
            solution_id = generate_solution_id()
            best_score = run_output.best_score
            insert_solution(
                proj_conn,
                solution_id=solution_id,
                run_id=run_id,
                rank=1,
                best_score=best_score,
                alias=config.alias,
            )

            # Determine final status based on valid iteration ratio, then
            # flag unproductive runs (0 evolved children — backlog #302).
            final_status = _determine_run_status(valid_iters, iterations)
            final_status = _apply_unproductive_override(
                backend, run_dir, iterations, final_status, quiet=quiet
            )

            # Atomically update generation_time_s and status
            update_run_generation_time(proj_conn, run_id, generation_time_s, status=final_status)

            # Run _post_run_evaluation() (warn on failure)
            if not quiet:
                sys.stderr.write("Running post-run evaluation...\n")
            try:
                _post_run_evaluation(
                    proj_conn=proj_conn,
                    run_id=run_id,
                    solution_id=solution_id,
                    snapshot_dir=snapshot_dir,
                    dataset_path=dataset_path,
                    program_path=(
                        run_dir / "programs" / "rank-1.py"
                        if (run_dir / "programs" / "rank-1.py").exists()
                        else initial_program
                    ),
                )
            except Exception as exc:
                sys.stderr.write(f"Warning: post-run evaluation failed: {exc}\n")

            # Build solution result
            solution_result = SolutionResult(
                solution_id=solution_id,
                run_id=run_id,
                alias=config.alias,
                rank=1,
                best_score=best_score,
            )

            # Write run manifest
            manifest_data = RunManifest(
                run_id=run_id,
                created_at=now,
                generation_time_s=generation_time_s,
                iterations=iterations,
                valid_iterations=valid_iters,
                status=final_status,
                problem_version=config.problem_version,
                problem_hash=pv.hash,
                dataset=config.dataset_name,
                dataset_hash=ds.global_hash,
                llm=config.llm_name,
                llm_model=llm_model_str,
                backend=backend.name,
                token_usage=token_usage_model,
                solution=solution_result,
                programs=programs,
            ).model_dump(mode="json")
            write_run_manifest(root, run_id, manifest_data)

            # Remove lock file
            remove_run_lock(root, run_id)

            # Return RunResult
            return RunResult(
                run_id=run_id,
                solution=solution_result,
                programs_stored=len(programs),
                problem_version=config.problem_version,
                llm=config.llm_name,
                dataset=config.dataset_name,
                iterations=iterations,
                valid_iterations=valid_iters,
                generation_time_s=generation_time_s,
                token_usage=token_usage_model,
            )

        except KeyboardInterrupt:
            # Stop proxy on interrupt
            if proxy is not None:
                with contextlib.suppress(Exception):
                    proxy.stop()
            if oe_completed:
                _handle_post_run_failure(
                    proj_conn,
                    root,
                    run_id,
                    run_dir,
                    generation_time_s,
                    KeyboardInterrupt("Interrupted during post-processing"),
                )
            else:
                update_run_status(proj_conn, run_id, "interrupted")
                remove_run_lock(root, run_id)
            raise
        except (RevolverError, ExternalError) as re_exc:
            if proxy is not None:
                with contextlib.suppress(Exception):
                    proxy.stop()
            if oe_completed:
                _handle_post_run_failure(
                    proj_conn,
                    root,
                    run_id,
                    run_dir,
                    generation_time_s,
                    re_exc,
                )
            else:
                crash_status, crash_valid = _determine_crash_status(
                    run_dir, iterations, backend=backend
                )
                update_run_status(proj_conn, run_id, crash_status)
                if crash_valid is not None:
                    update_run_valid_iterations(proj_conn, run_id, crash_valid)
                with contextlib.suppress(Exception):
                    error_log = run_dir / "run-error.log"
                    error_log.write_text(
                        f"Run failed at {datetime.now(UTC).isoformat()}:\n{traceback.format_exc()}"
                    )
                remove_run_lock(root, run_id)
            raise
        except Exception as exc:
            if proxy is not None:
                with contextlib.suppress(Exception):
                    proxy.stop()
            if oe_completed:
                _handle_post_run_failure(
                    proj_conn,
                    root,
                    run_id,
                    run_dir,
                    generation_time_s,
                    exc,
                )
                best = run_output.best_score if run_output else "unknown"
                raise ExternalError(
                    f"Evolution run completed (best_score={best}) "
                    f"but post-run processing failed: {exc}. "
                    f"Run status set to 'completed_with_errors'. "
                    f"Error details in: {run_dir / 'run-error.log'}"
                ) from exc
            else:
                crash_status, crash_valid = _determine_crash_status(
                    run_dir, iterations, backend=backend
                )
                update_run_status(proj_conn, run_id, crash_status)
                if crash_valid is not None:
                    update_run_valid_iterations(proj_conn, run_id, crash_valid)
                with contextlib.suppress(Exception):
                    error_log = run_dir / "run-error.log"
                    error_log.write_text(
                        f"Run failed at {datetime.now(UTC).isoformat()}:\n{traceback.format_exc()}"
                    )
                remove_run_lock(root, run_id)
                raise ExternalError(f"Run failed: {exc}") from exc

    finally:
        proj_conn.close()
        global_conn.close()


# ── _post_run_evaluation (FR-RUN-019/020) ────────────────────────────────────


def _run_post_eval(
    evaluator_path: Path,
    program_path: Path,
    dataset_path: Path,
    run_id: str,
    solution_id: str,
) -> None:
    """Run the inline post-run evaluation on training instances.

    This is the extracted evaluation logic from Sprint 004.
    It iterates over all instances, evaluates each via
    ``evaluator_runner.run_instance()``, and logs results to stderr.

    Args:
        evaluator_path: Path to the evaluator ``.py`` file.
        program_path: Path to the rank-1 program file.
        dataset_path: Path to the dataset directory.
        run_id: ID of the completed run (for logging).
        solution_id: ID of the rank-1 solution (for logging).
    """
    # TODO(S5-08): Replace with core.eval.evaluate_solution() after PR C merge.
    # The signature should become:
    #   core.eval.evaluate_solution(
    #       solution_id_or_alias=solution_id,
    #       dataset_name=<dataset>,
    #       force=True,
    #       on_progress=None,
    #   )
    # This function can then be removed entirely.

    # Enumerate instances
    instances = sorted(
        p for p in dataset_path.iterdir() if not p.name.startswith(".") and p.is_file()
    )
    if not instances:
        sys.stderr.write("Warning: no instances found, skipping post-run evaluation.\n")
        return

    sys.stderr.write(
        f"Post-run evaluation: evaluating {len(instances)} instances "
        f"(run={run_id}, solution={solution_id})...\n"
    )

    passed = 0
    failed = 0
    for inst in instances:
        result = eval_run_instance(
            evaluator_path=evaluator_path,
            program_path=program_path,
            instance_path=inst,
            timeout_s=300.0,
        )
        if result.status == "pass":
            passed += 1
        else:
            failed += 1
            sys.stderr.write(
                f"  Instance {result.instance_id}: {result.status}"
                + (f" — {result.error}" if result.error else "")
                + "\n"
            )

    sys.stderr.write(
        f"Post-run evaluation complete: {passed}/{len(instances)} passed, {failed} failed.\n"
    )


def _post_run_evaluation(
    proj_conn: Any,
    run_id: str,
    solution_id: str,
    snapshot_dir: Path,
    dataset_path: Path,
    program_path: Path,
) -> None:
    """Evaluate the rank-1 program on all training instances.

    Thin wrapper that validates paths and delegates to ``_run_post_eval()``.
    Once ``core.eval`` is available (PR C merge), this will delegate to
    ``core.eval.evaluate_solution()`` instead.

    Args:
        proj_conn: Open project database connection (unused in current impl).
        run_id: ID of the completed run.
        solution_id: ID of the rank-1 solution.
        snapshot_dir: Path to the problem version snapshot.
        dataset_path: Path to the dataset directory.
        program_path: Path to the rank-1 program file.
    """
    evaluator_path = snapshot_dir / EVALUATOR_FILENAME
    if not evaluator_path.exists():
        sys.stderr.write(
            f"Warning: evaluator not found at {evaluator_path}, skipping post-run evaluation.\n"
        )
        return

    if not program_path.exists():
        sys.stderr.write(
            f"Warning: program not found at {program_path}, skipping post-run evaluation.\n"
        )
        return

    _run_post_eval(
        evaluator_path=evaluator_path,
        program_path=program_path,
        dataset_path=dataset_path,
        run_id=run_id,
        solution_id=solution_id,
    )


# ── resume_run (DES-005 §2.3) ────────────────────────────────────────────────


def resume_run(
    run_id: str,
    iterations: int | None = None,
    temperature: float | None = None,
    parallel: int | None = None,
    llm_name: str | None = None,
    config_overrides: list[str] | None = None,
    rewrite_mode: bool = False,
    project_root: Path | None = None,
    *,
    backend_name: str | None = None,
    quiet: bool = False,
) -> RunResult:
    """Resume a run from its checkpoint, creating a new run.

    Creates a new run with ``resumed_from`` pointing to the parent.
    Copies the wrapper evaluator and checkpoint from the parent run.

    The resumed run always uses the **parent run's backend** (FR-RUN-047,
    spec-run §2.3 step 4): resume state formats are backend-specific, so
    cross-backend resume is rejected.

    Args:
        run_id: ID of the parent run to resume from.
        iterations: Override iteration count for the resumed run.
        temperature: LLM temperature override (0.0--2.0).
        parallel: Number of parallel evaluations.
        llm_name: Override LLM for the resumed run (must be registered).
        config_overrides: Engine config overrides (key=value strings).
        rewrite_mode: Full-rewrite mode shortcut. When ``True``, sets
            ``diff_based_evolution=false`` and ``max_code_length=50000``.
        project_root: Explicit project root, or ``None`` to auto-detect.
        backend_name: Optional explicit backend. Must match the parent
            run's backend; a mismatch raises :class:`ValidationError`.
        quiet: Suppress informational stderr messages (e.g. in --quiet/--json mode).

    Returns:
        A :class:`RunResult` for the new resumed run.

    Raises:
        RevolverError: If the parent run is not found or has invalid status.
        ValidationError: If *backend_name* conflicts with the parent
            run's backend (cross-backend resume).
        ExternalError: If the evolution engine fails.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"

    proj_conn = get_project_db(db_path)
    global_conn = get_global_db()
    try:
        # 1. Get parent run from DB
        parent = get_run(proj_conn, run_id)
        if parent is None:
            raise RevolverError(f"Run '{run_id}' not found.")

        # 1b. Inherit the parent run's backend (FR-RUN-047); reject an
        # explicit conflicting backend — cross-backend resume is
        # meaningless (the resume state formats differ).
        parent_backend = str(parent.get("backend") or DEFAULT_BACKEND)
        if backend_name is not None and backend_name != parent_backend:
            raise ValidationError(
                f"Cannot resume run '{run_id}' with backend '{backend_name}': "
                f"the parent run used backend '{parent_backend}'. "
                f"Cross-backend resume is not supported."
            )
        backend: EvolutionBackend = get_backend(parent_backend)

        # 2. Validate status
        parent_status = parent["status"]
        if parent_status not in (
            "completed",
            "interrupted",
            "failed",
            "completed_with_errors",
        ):
            raise RevolverError(
                f"Cannot resume run '{run_id}' with status '{parent_status}'. "
                f"Only 'completed', 'interrupted', 'failed', or "
                f"'completed_with_errors' runs can be resumed."
            )

        # 3. Load parent's problem version, LLM, dataset
        parent_version = str(parent["problem_version"])
        parent_llm_name = str(parent["llm"])
        parent_dataset_name = str(parent["dataset"])
        parent_iterations = int(parent["iterations"])  # type: ignore[call-overload]

        pv = get_problem_version(proj_conn, parent_version)
        if pv is None:
            raise RevolverError(f"Problem version '{parent_version}' not found.")

        # Determine effective LLM/ensemble: use override if provided, otherwise parent's
        effective_llm_name = llm_name if llm_name is not None else parent_llm_name
        llm_or_ensemble = resolve_llm_or_ensemble(effective_llm_name, global_conn)
        ensemble: EnsembleEntry | None = None
        if isinstance(llm_or_ensemble, EnsembleEntry):
            ensemble = llm_or_ensemble
            if not ensemble.members:
                raise RevolverError(f"Ensemble '{effective_llm_name}' has no members.")
            first_member_llm = get_llm(global_conn, ensemble.members[0].llm_name)
            if first_member_llm is None:
                raise RevolverError(
                    f"Ensemble member LLM '{ensemble.members[0].llm_name}' not found."
                )
            llm: LLMEntry = first_member_llm
        else:
            llm = llm_or_ensemble

        ds = get_dataset(proj_conn, parent_dataset_name)
        if ds is None:
            raise RevolverError(f"Dataset '{parent_dataset_name}' not found.")

        # 4. Create new run with resumed_from
        new_run_id = generate_run_id()
        new_run_dir = create_run_dir(root, new_run_id)

        parent_run_dir = get_run_dir(root, run_id)

        # 5. Copy wrapper from parent run dir (FR-RUN-024). The wrapper
        # filename is backend-owned (S14-13: _revolver_evaluator.py on OE,
        # _shinka_evaluator.py on Shinka).
        parent_wrapper = parent_run_dir / backend.wrapper_filename
        if parent_wrapper.exists():
            copy_run_file(parent_wrapper, new_run_dir / backend.wrapper_filename)

        # 6. Backend-aware resume staging precheck (S14-13, ADR-007 D6).
        # The orchestrator owns this fail-fast precheck: it must run BEFORE
        # the run-record insert and lock acquisition so a resume-state-less
        # parent aborts cleanly (DES-005 §14.1). Resume state formats are
        # backend-specific, hence the dispatch.
        if backend.name == "openevolve":
            # Copy checkpoint from parent run dir. The backend's resume()
            # self-staging branch is a fallback only.
            parent_checkpoint = find_latest_checkpoint(parent_run_dir)
            if parent_checkpoint is None:
                raise RevolverError(
                    f"No checkpoint found in parent run '{run_id}'. "
                    "The run may have been too short to produce a checkpoint."
                )
            # oe-checkpoint is the *input* checkpoint fed to OE for resume.
            # OE writes fresh checkpoints to oe-output/checkpoints/checkpoint_N/ instead.
            new_checkpoint: Path = new_run_dir / "oe-checkpoint"
            copy_run_file(parent_checkpoint, new_checkpoint)
        else:
            # ShinkaEvolve auto-resumes from the parent's programs database
            # (reused in place by ShinkaBackend.resume() — no staging copy).
            parent_programs_db = parent_run_dir / backend.default_output_subdir / "programs.sqlite"
            if not parent_programs_db.exists():
                raise RevolverError(
                    f"No programs database found in parent run '{run_id}'. "
                    "The run may have been too short to produce any programs."
                )

        # Resolve paths
        snapshot_dir = root / REVOLVER_DIR / PROBLEM_DIR / parent_version
        dataset_path = resolve_dataset_path(root, parent_dataset_name)

        # Read problem.md if present
        problem_md_path = snapshot_dir / "problem.md"
        problem_description: str | None = None
        if problem_md_path.exists():
            problem_description = problem_md_path.read_text(encoding="utf-8")

        # Determine iterations (FR-RUN-024: parent fallback). The
        # RESOLVED count goes into the spec — backends never see the raw
        # CLI value, whose absence would fall back to the snapshot config.
        actual_iterations = iterations or parent_iterations

        # Build the engine config through the backend (ADR-007 D1)
        spec = BackendRunSpec(
            snapshot_dir=snapshot_dir,
            llm=llm,
            run_dir=new_run_dir,
            iterations=actual_iterations,
            config_overrides=config_overrides,
            problem_description=problem_description,
            temperature=temperature,
            parallel=parallel,
            rewrite_mode=rewrite_mode,
            ensemble=ensemble,
            conn=global_conn,
            wrapper_path=new_run_dir / backend.wrapper_filename,
        )
        oe_config = backend.build_config(spec)

        # Build LLM snapshot for traceability (S11-08)
        llm_type, llm_model_str, llm_snapshot_json = _build_llm_snapshot(
            llm_or_ensemble, global_conn
        )

        # Set output dir in config BEFORE the snapshot is persisted:
        # backend.resume() overwrites config['output_dir'] (same value),
        # and the stored snapshot must keep containing it (DES-005 §14.1).
        # The directory name is backend-owned (S14-05, ADR-007 D1).
        engine_output_dir = new_run_dir / backend.default_output_subdir
        engine_output_dir.mkdir(exist_ok=True)
        oe_config["output_dir"] = str(engine_output_dir)

        # Insert run record — store UNRESOLVED config (no secrets in snapshot)
        now = datetime.now(UTC)
        config_snapshot_str = yaml.dump(oe_config, default_flow_style=False)
        insert_run(
            proj_conn,
            run_id=new_run_id,
            problem_version=parent_version,
            llm=effective_llm_name,
            dataset=parent_dataset_name,
            iterations=actual_iterations,
            problem_hash=pv.hash,
            dataset_hash=ds.global_hash,
            llm_model=llm_model_str,
            created_at=now,
            resumed_from=run_id,
            status="running",
            config_snapshot=config_snapshot_str,
            llm_type=llm_type,
            llm_snapshot=llm_snapshot_json,
            backend=parent_backend,
        )

        # Resolve api_key_env → api_key on a deep copy for runtime use only.
        oe_config_resolved = resolve_api_keys(copy.deepcopy(oe_config))

        # Write lock file
        lock_data_dict = {
            "run_id": new_run_id,
            "pid": os.getpid(),
            "llm_source": llm.source,
            "llm_name": effective_llm_name,
            "started_at": now.isoformat(),
        }
        write_run_lock(root, new_run_id, lock_data_dict)

        # Start token proxy when the backend measures tokens over HTTP
        # (ADR-007 D2) and the LLM has a base_url
        proxy: TokenCountingProxy | None = None
        if backend.wants_http_proxy() and llm.base_url:
            proxy = TokenCountingProxy(llm.base_url)
            proxy_url = proxy.start()
            if "llm" not in oe_config_resolved:
                oe_config_resolved["llm"] = {}
            oe_config_resolved["llm"]["api_base"] = proxy_url

        oe_completed = False
        generation_time_s = 0.0
        run_output_resume: BackendRunResult | None = None

        try:
            env_vars = {
                "REVOLVER_DATASET_DIR": str(dataset_path),
                "REVOLVER_INSTANCE_LOG": str(new_run_dir / "instance_log.db"),
                "REVOLVER_EVAL_LOG": str(new_run_dir / "eval_log.db"),
            }

            with revolver_env(env_vars):
                start_time = time.monotonic()

                # Pre-flight check: evaluate initial program on first instance
                wrapper_path = new_run_dir / backend.wrapper_filename
                initial_program = snapshot_dir / "initial_program.py"
                preflight_instances = sorted(
                    (
                        p
                        for p in dataset_path.iterdir()
                        if not p.name.startswith(".") and p.is_file()
                    ),
                    key=lambda p: p.name,
                )
                if preflight_instances:
                    first_instance = preflight_instances[0]
                    preflight_result = eval_run_instance(
                        evaluator_path=wrapper_path,
                        program_path=initial_program,
                        instance_path=first_instance,
                        timeout_s=60.0,
                    )
                    if preflight_result.status != "pass":
                        raise RevolverError(
                            f"Pre-flight check failed: initial program evaluation "
                            f"{preflight_result.status} on {first_instance.name}."
                            + (
                                f" Error: {preflight_result.error}"
                                if preflight_result.error
                                else ""
                            )
                            + " Fix the evaluator or initial program before "
                            "running evolution."
                        )
                    # Log success
                    score_info = ""
                    if preflight_result.metrics:
                        cs = preflight_result.metrics.get("combined_score")
                        if cs is not None:
                            score_info = f", score={cs:.4f}"
                        if cs == 0.0:
                            sys.stderr.write(
                                f"Warning: pre-flight check passed but score=0.0 "
                                f"on {first_instance.name}. Evolution may not "
                                f"produce improvements.\n"
                            )
                    sys.stderr.write(
                        f"Pre-flight check passed ({first_instance.name}{score_info}).\n"
                    )

                # Resume the engine from the staged checkpoint through
                # the backend (ADR-007 D1; spec.iterations already
                # carries the parent-run fallback per FR-RUN-024).
                run_output_resume = backend.resume(spec, oe_config_resolved, parent_run_dir)

                end_time = time.monotonic()
                generation_time_s = end_time - start_time

            # The engine completed successfully — any exception below is
            # a post-processing failure, not an engine interruption.
            oe_completed = True

            # Token collection (ADR-007 D2): HTTP proxy when the backend
            # wants it, engine-native accounting otherwise.
            token_usage_model: PydanticTokenUsage | None = None
            if proxy is not None:
                proxy_usage = proxy.stop()
                estimated = estimate_cost(
                    proxy_usage.prompt_tokens,
                    proxy_usage.completion_tokens,
                    llm.input_cost_per_mtok,
                    llm.output_cost_per_mtok,
                )
                token_usage_model = PydanticTokenUsage(
                    prompt_tokens=proxy_usage.prompt_tokens,
                    completion_tokens=proxy_usage.completion_tokens,
                    estimated_cost_usd=estimated,
                )
                update_run_tokens(
                    proj_conn,
                    new_run_id,
                    proxy_usage.prompt_tokens,
                    proxy_usage.completion_tokens,
                )
            else:
                native_usage = backend.collect_token_usage(new_run_dir)
                if native_usage is not None:
                    token_usage_model = native_usage
                    update_run_tokens(
                        proj_conn,
                        new_run_id,
                        native_usage.prompt_tokens,
                        native_usage.completion_tokens,
                    )

            # Collect programs
            programs = _collect_programs(engine_output_dir, new_run_dir / "programs")

            # Count valid iterations via the backend (ADR-007 D1, S14-06)
            valid_iters: int | None = backend.count_valid(new_run_dir)
            if valid_iters is not None:
                update_run_valid_iterations(proj_conn, new_run_id, valid_iters)

            # Create solution
            solution_id = generate_solution_id()
            best_score = run_output_resume.best_score
            insert_solution(
                proj_conn,
                solution_id=solution_id,
                run_id=new_run_id,
                rank=1,
                best_score=best_score,
            )

            # Determine final status based on valid iteration ratio, then
            # flag unproductive runs (0 evolved children — backlog #302).
            # NOTE: on Shinka, count_evolved_children reads the cumulative
            # parent-chain DB (ShinkaBackend.resume() reuses the parent
            # results_dir), so a resume that evolves nothing but inherits a
            # productive parent is not flagged — consistent with the cumulative
            # token/valid-iteration accounting on the same DB.
            final_status = _determine_run_status(valid_iters, actual_iterations)
            final_status = _apply_unproductive_override(
                backend, new_run_dir, actual_iterations, final_status, quiet=quiet
            )

            # Atomically update generation_time_s and status
            update_run_generation_time(
                proj_conn, new_run_id, generation_time_s, status=final_status
            )

            # Post-run eval
            if not quiet:
                sys.stderr.write("Running post-run evaluation...\n")
            try:
                _post_run_evaluation(
                    proj_conn=proj_conn,
                    run_id=new_run_id,
                    solution_id=solution_id,
                    snapshot_dir=snapshot_dir,
                    dataset_path=dataset_path,
                    program_path=(
                        new_run_dir / "programs" / "rank-1.py"
                        if (new_run_dir / "programs" / "rank-1.py").exists()
                        else initial_program
                    ),
                )
            except Exception as exc:
                sys.stderr.write(f"Warning: post-run evaluation failed: {exc}\n")

            solution_result = SolutionResult(
                solution_id=solution_id,
                run_id=new_run_id,
                rank=1,
                best_score=best_score,
            )

            # Write manifest
            manifest_data = RunManifest(
                run_id=new_run_id,
                created_at=now,
                generation_time_s=generation_time_s,
                iterations=actual_iterations,
                valid_iterations=valid_iters,
                status=final_status,
                problem_version=parent_version,
                problem_hash=pv.hash,
                dataset=parent_dataset_name,
                dataset_hash=ds.global_hash,
                llm=effective_llm_name,
                llm_model=llm_model_str,
                resumed_from=run_id,
                backend=parent_backend,
                token_usage=token_usage_model,
                solution=solution_result,
                programs=programs,
            ).model_dump(mode="json")
            write_run_manifest(root, new_run_id, manifest_data)

            remove_run_lock(root, new_run_id)

            return RunResult(
                run_id=new_run_id,
                solution=solution_result,
                programs_stored=len(programs),
                problem_version=parent_version,
                llm=effective_llm_name,
                dataset=parent_dataset_name,
                iterations=actual_iterations,
                valid_iterations=valid_iters,
                generation_time_s=generation_time_s,
                token_usage=token_usage_model,
                resumed_from=run_id,
            )

        except KeyboardInterrupt:
            if proxy is not None:
                with contextlib.suppress(Exception):
                    proxy.stop()
            if oe_completed:
                _handle_post_run_failure(
                    proj_conn,
                    root,
                    new_run_id,
                    new_run_dir,
                    generation_time_s,
                    KeyboardInterrupt("Interrupted during post-processing"),
                )
            else:
                update_run_status(proj_conn, new_run_id, "interrupted")
                remove_run_lock(root, new_run_id)
            raise
        except (RevolverError, ExternalError) as re_exc:
            if proxy is not None:
                with contextlib.suppress(Exception):
                    proxy.stop()
            if oe_completed:
                _handle_post_run_failure(
                    proj_conn,
                    root,
                    new_run_id,
                    new_run_dir,
                    generation_time_s,
                    re_exc,
                )
            else:
                crash_status, crash_valid = _determine_crash_status(
                    new_run_dir, actual_iterations, backend=backend
                )
                update_run_status(proj_conn, new_run_id, crash_status)
                if crash_valid is not None:
                    update_run_valid_iterations(proj_conn, new_run_id, crash_valid)
                with contextlib.suppress(Exception):
                    error_log = new_run_dir / "run-error.log"
                    error_log.write_text(
                        f"Run failed at {datetime.now(UTC).isoformat()}:\n{traceback.format_exc()}"
                    )
                remove_run_lock(root, new_run_id)
            raise
        except Exception as exc:
            if proxy is not None:
                with contextlib.suppress(Exception):
                    proxy.stop()
            if oe_completed:
                _handle_post_run_failure(
                    proj_conn,
                    root,
                    new_run_id,
                    new_run_dir,
                    generation_time_s,
                    exc,
                )
                best = run_output_resume.best_score if run_output_resume else "unknown"
                raise ExternalError(
                    f"Evolution run completed (best_score={best}) "
                    f"but post-run processing failed: {exc}. "
                    f"Run status set to 'completed_with_errors'. "
                    f"Error details in: {new_run_dir / 'run-error.log'}"
                ) from exc
            else:
                crash_status, crash_valid = _determine_crash_status(
                    new_run_dir, actual_iterations, backend=backend
                )
                update_run_status(proj_conn, new_run_id, crash_status)
                if crash_valid is not None:
                    update_run_valid_iterations(proj_conn, new_run_id, crash_valid)
                with contextlib.suppress(Exception):
                    error_log = new_run_dir / "run-error.log"
                    error_log.write_text(
                        f"Run failed at {datetime.now(UTC).isoformat()}:\n{traceback.format_exc()}"
                    )
                remove_run_lock(root, new_run_id)
                raise ExternalError(f"Resumed run failed: {exc}") from exc

    finally:
        proj_conn.close()
        global_conn.close()


# ── get_run_status (DES-005 §2.2) ────────────────────────────────────────────


def get_run_status(project_root: Path | None = None) -> RunStatus:
    """Get status of active runs or the most recent run.

    Scans lock files for active runs, validates PIDs, removes stale locks.
    Falls back to the latest run from DB if no active runs.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A :class:`RunStatus` with active run info or latest run info.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"

    # Scan lock files
    active_locks = get_active_locks(root)
    active_run_ids: list[str] = []

    for lock_data in active_locks:
        lock_pid = lock_data.get("pid")
        lock_run_id = lock_data.get("run_id", "")
        if lock_pid and _is_pid_alive(int(lock_pid)):
            active_run_ids.append(lock_run_id)
        else:
            # Stale lock — remove it
            if lock_run_id:
                remove_run_lock(root, lock_run_id)

    if active_run_ids:
        # Return status for active runs
        proj_conn = get_project_db(db_path)
        try:
            # Use first active run for details
            run_data = get_run(proj_conn, active_run_ids[0])
            if run_data:
                started_at_str = str(run_data.get("created_at", ""))
                started_at = datetime.fromisoformat(started_at_str) if started_at_str else None
                elapsed = (datetime.now(UTC) - started_at).total_seconds() if started_at else None

                # Read live progress via the run's backend (read-only,
                # error-tolerant — ADR-007 D1)
                iterations_completed: int | None = None
                best_score: float | None = None
                try:
                    run_dir = root / REVOLVER_DIR / "runs" / active_run_ids[0]
                    run_backend = get_backend(str(run_data.get("backend") or DEFAULT_BACKEND))
                    iterations_completed, best_score = run_backend.read_progress(run_dir)
                except (OSError, ValueError, KeyError, TypeError, RevolverError):
                    logger.debug("Could not read checkpoint progress", exc_info=True)

                return RunStatus(
                    active=True,
                    run_ids=active_run_ids,
                    run_id=active_run_ids[0],
                    problem_version=str(run_data.get("problem_version", "")),
                    llm=str(run_data.get("llm", "")),
                    dataset=str(run_data.get("dataset", "")),
                    iterations_completed=iterations_completed,
                    iterations_total=(
                        int(run_data["iterations"])  # type: ignore[call-overload]
                        if run_data.get("iterations")
                        else None
                    ),
                    best_score=best_score,
                    started_at=started_at,
                    elapsed_s=elapsed,
                )
            return RunStatus(active=True, run_ids=active_run_ids)
        finally:
            proj_conn.close()

    # No active runs — return latest run
    proj_conn = get_project_db(db_path)
    try:
        latest = get_latest_run(proj_conn)
        if latest is None:
            return RunStatus(active=False)

        started_at_str = str(latest.get("created_at", ""))
        started_at = datetime.fromisoformat(started_at_str) if started_at_str else None

        # For completed runs, show valid_iterations from DB
        valid_iters: int | None = None
        if latest.get("valid_iterations") is not None:
            valid_iters = int(latest["valid_iterations"])  # type: ignore[call-overload]

        # Retrieve best_score from rank-1 solution (if any)
        idle_best_score: float | None = None
        run_id_str = str(latest.get("id", ""))
        if run_id_str:
            solutions = get_solutions_for_run(proj_conn, run_id_str)
            if solutions and solutions[0].best_score is not None:
                idle_best_score = solutions[0].best_score

        return RunStatus(
            active=False,
            run_id=run_id_str,
            problem_version=str(latest.get("problem_version", "")),
            llm=str(latest.get("llm", "")),
            dataset=str(latest.get("dataset", "")),
            iterations_completed=valid_iters,
            iterations_total=(
                int(latest["iterations"])  # type: ignore[call-overload]
                if latest.get("iterations")
                else None
            ),
            best_score=idle_best_score,
            started_at=started_at,
        )
    finally:
        proj_conn.close()


# ── list_runs (DES-005 §2.4) ─────────────────────────────────────────────────


def list_runs(
    project_root: Path | None = None,
    version: str | None = None,
    llm: str | None = None,
    status: str | None = None,
) -> list[RunSummary]:
    """List runs with optional filters.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.
        version: Filter by problem version tag.
        llm: Filter by LLM registry name.
        status: Filter by run status.

    Returns:
        A list of :class:`RunSummary` instances ordered by creation time (desc).
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        rows = db_list_runs(conn, version=version, llm=llm, status=status)
        summaries: list[RunSummary] = []
        for row in rows:
            token_usage: PydanticTokenUsage | None = None
            if row.get("prompt_tokens") is not None:
                token_usage = PydanticTokenUsage(
                    prompt_tokens=int(row["prompt_tokens"]),  # type: ignore[call-overload]
                    completion_tokens=int(row.get("completion_tokens") or 0),  # type: ignore[call-overload]
                )
            summaries.append(
                RunSummary(
                    run_id=str(row["id"]),
                    problem_version=str(row["problem_version"]),
                    llm=str(row["llm"]),
                    dataset=str(row["dataset"]),
                    iterations=int(row["iterations"]),  # type: ignore[call-overload]
                    valid_iterations=(
                        int(row["valid_iterations"])  # type: ignore[call-overload]
                        if row.get("valid_iterations") is not None
                        else None
                    ),
                    generation_time_s=(
                        float(row["generation_time_s"])  # type: ignore[arg-type]
                        if row.get("generation_time_s") is not None
                        else 0.0
                    ),
                    token_usage=token_usage,
                    status=str(row["status"]),
                    resumed_from=(str(row["resumed_from"]) if row.get("resumed_from") else None),
                    created_at=datetime.fromisoformat(str(row["created_at"])),
                    best_score=(
                        float(row["best_score"])  # type: ignore[arg-type]
                        if row.get("best_score") is not None
                        else None
                    ),
                    alias=(str(row["alias"]) if row.get("alias") else None),
                    llm_type=str(row.get("llm_type", "single")),
                    backend=str(row.get("backend") or DEFAULT_BACKEND),
                )
            )
        return summaries
    finally:
        conn.close()


# ── detect_zombie_runs (S10-13) ──────────────────────────────────────────────


def detect_zombie_runs(project_root: Path | None = None) -> list[str]:
    """Detect and mark zombie runs as interrupted.

    Scans runs with ``status='running'`` in DB. For each, checks if a lock file
    exists and if the PID is alive. Marks as ``'interrupted'`` if:

    - Lock file exists but PID is dead
    - Lock file is unreadable (corrupt JSON, missing PID)
    - No lock file exists (process gone without cleanup)

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A list of run IDs that were marked as interrupted.
    """
    import json as _json

    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        rows = db_list_runs(conn, status="running")
        locks_dir = root / REVOLVER_DIR / "runs" / "locks"
        zombie_ids: list[str] = []

        for row in rows:
            run_id = str(row["id"])
            lock_file = locks_dir / f"{run_id}.lock"

            is_zombie = False
            if lock_file.exists():
                try:
                    lock_data = _json.loads(lock_file.read_text(encoding="utf-8"))
                    pid = lock_data.get("pid")
                    if pid is not None and not _is_pid_alive(int(pid)):
                        is_zombie = True
                except (ValueError, OSError):
                    # Can't read or parse lock → treat as zombie
                    is_zombie = True
            else:
                # No lock file → process gone without cleanup
                is_zombie = True

            if is_zombie:
                update_run_status(conn, run_id, "interrupted")
                remove_run_lock(root, run_id)
                zombie_ids.append(run_id)

        return zombie_ids
    finally:
        conn.close()


# ── get_run_info (DES-005 §2.5) ──────────────────────────────────────────────


def get_run_info(
    run_id: str,
    project_root: Path | None = None,
) -> RunInfo:
    """Get detailed run information.

    Args:
        run_id: ID of the run to query.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A :class:`RunInfo` with full details, solutions, programs, and resume chain.

    Raises:
        RevolverError: If the run is not found.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # 1. Get run from DB
        run_data = get_run(conn, run_id)
        if run_data is None:
            raise RevolverError(f"Run '{run_id}' not found.")

        # 2. Get solutions for run
        solutions = get_solutions_for_run(conn, run_id)
        solution_results = [
            SolutionResult(
                solution_id=s.id,
                run_id=s.run_id,
                alias=s.alias,
                rank=s.rank,
                best_score=s.best_score,
            )
            for s in solutions
        ]

        # 3. Read programs from manifest (if exists)
        programs: list[ProgramEntry] = []
        try:
            manifest = read_run_manifest(root, run_id)
            if "programs" in manifest:
                for p in manifest["programs"]:
                    programs.append(
                        ProgramEntry(
                            rank=p["rank"],
                            score=p.get("score"),
                            file=p["file"],
                        )
                    )
        except FileNotFoundError:
            pass

        # 4. Get resume chain
        chain = get_resume_chain(conn, run_id)

        # 5. Build token usage
        token_usage: PydanticTokenUsage | None = None
        if run_data.get("prompt_tokens") is not None:
            token_usage = PydanticTokenUsage(
                prompt_tokens=int(run_data["prompt_tokens"]),  # type: ignore[call-overload]
                completion_tokens=int(run_data.get("completion_tokens") or 0),  # type: ignore[call-overload]
            )

        # 6. Detect an unproductive run (0 evolved children — #302). Only
        #    meaningful for a completed_with_errors status on a backend that
        #    distinguishes children from seeds (others return None → False).
        status_str = str(run_data["status"])
        produced_no_children = False
        if status_str == "completed_with_errors":
            try:
                run_backend = get_backend(str(run_data.get("backend") or DEFAULT_BACKEND))
                produced_no_children = (
                    run_backend.count_evolved_children(get_run_dir(root, run_id)) == 0
                )
            except Exception:
                logger.debug("unproductive-run check failed in get_run_info", exc_info=True)

        return RunInfo(
            run_id=str(run_data["id"]),
            problem_version=str(run_data["problem_version"]),
            problem_hash=str(run_data["problem_hash"]),
            llm=str(run_data["llm"]),
            llm_model=str(run_data["llm_model"]),
            dataset=str(run_data["dataset"]),
            dataset_hash=str(run_data["dataset_hash"]),
            iterations=int(run_data["iterations"]),  # type: ignore[call-overload]
            valid_iterations=(
                int(run_data["valid_iterations"])  # type: ignore[call-overload]
                if run_data.get("valid_iterations") is not None
                else None
            ),
            generation_time_s=(
                float(run_data["generation_time_s"])  # type: ignore[arg-type]
                if run_data.get("generation_time_s") is not None
                else 0.0
            ),
            token_usage=token_usage,
            status=str(run_data["status"]),
            resumed_from=(str(run_data["resumed_from"]) if run_data.get("resumed_from") else None),
            created_at=datetime.fromisoformat(str(run_data["created_at"])),
            solutions=solution_results,
            programs=programs,
            resume_chain=chain,
            llm_type=str(run_data.get("llm_type", "single")),
            llm_snapshot=(str(run_data["llm_snapshot"]) if run_data.get("llm_snapshot") else None),
            backend=str(run_data.get("backend") or DEFAULT_BACKEND),
            produced_no_children=produced_no_children,
        )
    finally:
        conn.close()


# ── Population inspection ──────────────────────────────────────────────────────


def get_population(
    run_id: str,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Get the evolved population for a run.

    Delegates population parsing to the run's backend
    (:meth:`EvolutionBackend.parse_population` — ADR-007 D1); for
    OpenEvolve this reads the latest ``checkpoint_N/programs/*.json``
    ranked by score.

    Args:
        run_id: ID of the run to inspect.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A list of dicts with program data, sorted by score descending.

    Raises:
        RevolverError: If the run is not found or has no checkpoint.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"

    proj_conn = get_project_db(db_path)
    try:
        run_data = get_run(proj_conn, run_id)
        if run_data is None:
            raise RevolverError(f"Run '{run_id}' not found.")
        run_backend = get_backend(str(run_data.get("backend") or DEFAULT_BACKEND))
    finally:
        proj_conn.close()

    run_dir = get_run_dir(root, run_id)
    population = run_backend.parse_population(run_dir)
    if population is None:
        raise RevolverError(
            f"No checkpoint found for run '{run_id}'. "
            "The run may not have completed any iterations."
        )

    return population


# ── Internal helpers ──────────────────────────────────────────────────────────


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive.

    Args:
        pid: Process ID to check.

    Returns:
        ``True`` if the process exists, ``False`` otherwise.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _collect_programs(oe_output_dir: Path, programs_dir: Path) -> list[ProgramEntry]:
    """Collect programs from OpenEvolve output directory.

    Looks for Python files in the output directory and copies them
    to the run's ``programs/`` directory as ``rank-1.py``, ``rank-2.py``, etc.

    Args:
        oe_output_dir: OpenEvolve output directory.
        programs_dir: Destination programs directory in the run dir.

    Returns:
        List of :class:`ProgramEntry` for the collected programs.
    """
    programs: list[ProgramEntry] = []
    programs_dir.mkdir(parents=True, exist_ok=True)

    # Look for top_programs/ or best_programs/ or best/; fall back to loose
    # .py files at the output-dir root ONLY when no named dir exists. An
    # existing-but-empty named dir is terminal: engines that keep their
    # programs in a database (ShinkaEvolve) also write their own scripts at
    # the root (init_program.py, evaluate.py) — the root fallback would
    # collect those as solutions of a programless run (review #196 W2).
    named_dirs = [
        oe_output_dir / "top_programs",
        oe_output_dir / "best_programs",
        oe_output_dir / "best",
    ]

    py_files: list[Path] = []
    named_dir_found = False
    for source in named_dirs:
        if source.exists():
            named_dir_found = True
            found = sorted(source.glob("*.py"))
            if found:
                py_files = found
                break
    if not named_dir_found:
        py_files = sorted(oe_output_dir.glob("*.py"))

    for rank, py_file in enumerate(py_files, start=1):
        dest = programs_dir / f"rank-{rank}.py"
        shutil.copy2(py_file, dest)
        programs.append(
            ProgramEntry(
                rank=rank,
                file=f"programs/rank-{rank}.py",
            )
        )

    return programs


# ── Run deletion ─────────────────────────────────────────────────────────────


def delete_run(
    run_id: str,
    *,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Delete a run, its solutions, evals, and on-disk files.

    Confirmation prompts belong in the CLI layer — this is a pure domain
    function.

    Steps:
        1. Resolve project root & open DB.
        2. Verify run exists (raise :class:`RevolverError` if not).
        3. Count solutions and evals for the summary.
        4. Remove the run directory from disk (tolerate missing).
        5. Remove any leftover lock file.
        6. ``DELETE FROM runs`` — CASCADE handles solutions/evals.
        7. Return a summary dict.

    Args:
        run_id: ID of the run to delete.
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A dict with keys ``run_id``, ``solutions_deleted``, ``evals_deleted``.

    Raises:
        RevolverError: If the run is not found.
    """
    root = _resolve_project_root(project_root)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # 1. Verify run exists
        run_data = get_run(conn, run_id)
        if run_data is None:
            raise RevolverError(f"Run '{run_id}' not found.")

        # 2. Guard: refuse to delete an active run
        active_locks = get_active_locks(root)
        for lock in active_locks:
            pid_str = lock.get("pid")
            if lock.get("run_id") == run_id and pid_str and _is_pid_alive(int(pid_str)):
                raise ActiveRunError(
                    f"Run '{run_id}' is currently active (PID={lock['pid']})."
                    " Stop the run before deleting it."
                )

        # 3. Count solutions and evals for summary
        solutions_count = count_solutions_for_run(conn, run_id)
        evals_count = count_evals_for_run(conn, run_id)

        # 4. Delete from DB first (CASCADE handles solutions/evals)
        #    If DB delete fails, files remain intact.
        db_delete_run(conn, run_id)

        # 5. Delete on-disk files (tolerate missing directory)
        delete_run_dir(root, run_id)

        # 6. Remove lock file if present
        remove_run_lock(root, run_id)

        return {
            "run_id": run_id,
            "solutions_deleted": solutions_count,
            "evals_deleted": evals_count,
        }
    finally:
        conn.close()


def delete_all_runs(
    *,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Delete all runs in the project.

    Iterates over every run returned by :func:`list_runs` and calls
    :func:`delete_run` for each.  Active runs are skipped rather than
    aborting the whole operation.

    Args:
        project_root: Explicit project root, or ``None`` to auto-detect.

    Returns:
        A dict with ``deleted`` (int) and ``skipped`` (list of run IDs
        that could not be deleted because they are active).
    """
    # Note: list_runs is called here even though the CLI may have already
    # called it for the confirmation count.  This is acceptable because the
    # query is lightweight and avoids coupling the API to the CLI flow.
    summaries = list_runs(project_root=project_root)
    if not summaries:
        return {"deleted": 0, "skipped": []}

    deleted = 0
    skipped: list[str] = []
    for summary in summaries:
        try:
            delete_run(summary.run_id, project_root=project_root)
            deleted += 1
        except ActiveRunError:
            skipped.append(summary.run_id)
    return {"deleted": deleted, "skipped": skipped}
