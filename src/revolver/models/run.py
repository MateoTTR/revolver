"""Pydantic models for run orchestration and result reporting.

Models cover the full lifecycle of an OpenEvolve run: configuration,
execution status, result collection, and detailed info queries.

Traceable to: DES-005 (Run Orchestration) §8, FR-RUN-001..030.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class TokenUsage(BaseModel):
    """Token usage accumulated during a run.

    Cost is intentionally not reported (S15 / backlog #300): no realistic
    figure is reachable — the engines do not persist per-attempt or
    reasoning/thinking tokens, so any cost estimate would be misleading.
    Token counts cover stored programs only; watch the provider console
    for thinking-model spend.

    Attributes:
        prompt_tokens: Total input tokens consumed (0 if unavailable).
        completion_tokens: Total output tokens consumed (0 if unavailable).
        total_tokens: Sum of prompt + completion tokens (computed).
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int:
        """Return the sum of prompt and completion tokens.

        Note: DES-005 §8 specifies ``total_tokens`` as a stored field.
        We use a computed property instead to avoid data inconsistency
        and eliminate a redundant column.
        """
        return self.prompt_tokens + self.completion_tokens


class RunConfig(BaseModel):
    """Configuration for launching an OpenEvolve run.

    Attributes:
        problem_version: Problem version tag (e.g. ``"v1.0"``).
        llm_name: LLM registry name (e.g. ``"codestral-local"``).
        dataset_name: Dataset name (e.g. ``"train-small"``).
        iterations: Number of OpenEvolve iterations (``None`` for default).
        alias: Optional alias for the auto-created rank-1 solution.
        config_overrides: OpenEvolve config override strings
            (e.g. ``["llm.temperature=0.8"]``).
        dry_run: If ``True``, validate inputs and display config without launching.
        temperature: Sampling temperature for LLM (overrides LLM registry value).
        parallel: Number of parallel evaluations for OpenEvolve.
        rewrite_mode: Full-rewrite mode shortcut. When ``True``, sets
            ``diff_based_evolution=false`` and ``max_code_length=50000``.
        backend: Evolution backend name (ADR-007). ``None`` sentinel =
            "not specified" (U4 / S18): the effective backend resolves
            ``explicit --backend > version-stored backend (FR-PRB-016) >
            default 'openevolve'`` in ``launch_run`` — the sentinel keeps
            an explicit ``"openevolve"`` distinguishable from flag absence
            (FR-RUN-047 as amended).
        selection: Ensemble selection strategy (``--selection``; ADR-007
            Amendment A2). ``None`` = backend default. Accepted values are
            capability-gated per backend (OpenEvolve: ``weighted`` only;
            ShinkaEvolve: ``fixed``/``ucb``/``ucb1``/``thompson``).
        selection_kwargs: Raw ``--selection-kwarg k=v`` strings (repeatable),
            parsed and routed per-sampler downstream (ADR-007 Amendment A5).
        llm_weight_overrides: Raw ``--llm-weight model=w`` strings (repeatable),
            per-run weight overrides parsed downstream (ADR-007 Amendment
            A1/M3).
    """

    problem_version: str
    llm_name: str
    dataset_name: str
    iterations: int | None = None
    alias: str | None = None
    config_overrides: list[str] = Field(default_factory=list)
    dry_run: bool = False
    temperature: float | None = None
    parallel: int | None = None
    rewrite_mode: bool = False
    backend: str | None = None
    selection: str | None = None
    selection_kwargs: list[str] | None = None
    llm_weight_overrides: list[str] | None = None


class ProgramEntry(BaseModel):
    """A stored program from OpenEvolve output.

    Attributes:
        rank: Program rank (1 = best).
        score: Best score achieved by this program (``None`` if unavailable).
        file: Relative path within the run directory (e.g. ``"programs/rank-1.py"``).
    """

    rank: int
    score: float | None = None
    file: str


class SolutionResult(BaseModel):
    """A solution reference returned after run completion.

    Attributes:
        solution_id: Unique solution identifier (e.g. ``"sol-20260310-143000"``).
        run_id: ID of the run that produced this solution.
        alias: Optional user-given alias.
        rank: Rank within the run (1 = best, auto-created).
        best_score: Best score achieved (``None`` if unavailable).
    """

    solution_id: str
    run_id: str
    alias: str | None = None
    rank: int
    best_score: float | None = None


class RunManifest(BaseModel):
    """Manifest stored in ``.revolver/runs/<id>/manifest.yaml``.

    Contains full run metadata, lineage information, token usage,
    solution reference, and program file list. Frozen once written.

    Attributes:
        run_id: Unique run identifier.
        created_at: Timestamp of run creation.
        generation_time_s: Wall-clock generation time in seconds.
        iterations: Number of OpenEvolve iterations executed.
        valid_iterations: Number of iterations that produced valid programs.
        status: Run status (``"running"``, ``"completed"``, ``"interrupted"``).
        problem_version: Problem version tag used.
        problem_hash: Hash of the problem snapshot used.
        dataset: Dataset name used.
        dataset_hash: Hash of the dataset at registration time.
        llm: LLM registry name used.
        llm_model: Full model identifier (e.g. ``"claude-opus-4-6"``).
        resumed_from: Parent run ID if this is a resumed run.
        backend: Evolution backend name (ADR-007). Defaults to
            ``"openevolve"`` so manifests written before Sprint 013
            keep loading.
        token_usage: Token counts from the run (``None`` while running).
        solution: Auto-created rank-1 solution (``None`` while running).
        programs: All stored programs from OpenEvolve output.
        checkpoint: Relative path to checkpoint directory.
        config_file: Relative path to config file in run directory.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    created_at: datetime
    generation_time_s: float | None = None
    iterations: int
    valid_iterations: int | None = None
    status: str = "running"

    # Lineage
    problem_version: str
    problem_hash: str
    dataset: str
    dataset_hash: str
    llm: str
    llm_model: str
    resumed_from: str | None = None
    backend: str = "openevolve"

    # Token usage (FR-RUN-028/029/030)
    token_usage: TokenUsage | None = None

    # Solution
    solution: SolutionResult | None = None

    # Files
    programs: list[ProgramEntry] = []
    checkpoint: str = "oe-checkpoint/"
    config_file: str = "config.yaml"


class ResolvedConfig(BaseModel):
    """Backend-neutral resolved configuration for dry-run display.

    Holds the parameters shared by all evolution backends (ADR-007 D4),
    plus a ``backend_extras`` escape hatch for backend-exclusive keys
    (e.g. OpenEvolve's ``checkpoint_interval`` or ``feature_dimensions``).

    Attributes:
        backend: Evolution backend name (``"openevolve"`` or ``"shinka"``).
        iterations: Maximum evolution iterations/generations.
        num_islands: Number of evolutionary islands.
        temperature: LLM sampling temperature.
        language: Programming language of the evolved program.
        llm_models: Ensemble LLM model entries with names and weights.
        config_overrides: Raw config override key=value pairs from CLI.
        backend_extras: Backend-exclusive parameters as a free-form dict.
    """

    backend: str
    iterations: int | None = None
    num_islands: int | None = None
    temperature: float | None = None
    language: str | None = None
    llm_models: list[dict[str, Any]] | None = None
    config_overrides: dict[str, Any] | None = None
    backend_extras: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    """Result returned to the CLI after a run completes.

    Attributes:
        run_id: This run's own identifier.
        solution: Auto-created rank-1 solution reference.
        programs_stored: Total number of programs stored from OpenEvolve output.
        problem_version: Problem version tag used.
        llm: LLM registry name used.
        dataset: Dataset name used.
        iterations: Number of iterations executed.
        valid_iterations: Number of iterations that produced valid programs.
        generation_time_s: Wall-clock generation time in seconds.
        token_usage: Token counts from the proxy (``None`` if unavailable).
        resumed_from: Parent run ID if this is a resumed run.
        resolved_config: Backend-neutral resolved configuration
            (populated in dry-run mode — ADR-007 D4).
    """

    run_id: str
    solution: SolutionResult
    programs_stored: int
    problem_version: str
    llm: str
    dataset: str
    iterations: int
    valid_iterations: int | None = None
    generation_time_s: float
    token_usage: TokenUsage | None = None
    resumed_from: str | None = None
    resolved_config: ResolvedConfig | None = None


class RunStatus(BaseModel):
    """Status of active runs or the most recent run.

    Attributes:
        active: ``True`` if at least one run is currently in progress.
        run_ids: IDs of all active runs (may be multiple).
        run_id: Most recent run ID (if no active runs).
        problem_version: Problem version of the active/recent run.
        llm: LLM name of the active/recent run.
        dataset: Dataset name of the active/recent run.
        iterations_completed: Number of iterations completed so far.
        iterations_total: Total planned iterations.
        best_score: Best score achieved so far.
        started_at: Timestamp when the run started.
        elapsed_s: Elapsed wall-clock time in seconds.
    """

    active: bool
    run_ids: list[str] = []
    run_id: str | None = None
    problem_version: str | None = None
    llm: str | None = None
    dataset: str | None = None
    iterations_completed: int | None = None
    iterations_total: int | None = None
    best_score: float | None = None
    started_at: datetime | None = None
    elapsed_s: float | None = None


class RunSummary(BaseModel):
    """Summary for run list output.

    Attributes:
        run_id: Unique run identifier.
        problem_version: Problem version tag used.
        llm: LLM registry name used.
        dataset: Dataset name used.
        iterations: Number of iterations executed.
        valid_iterations: Number of iterations that produced valid programs.
        generation_time_s: Wall-clock generation time in seconds.
        token_usage: Token counts for display in list view.
        status: Run status (``"running"``, ``"completed"``, ``"interrupted"``).
        resumed_from: Parent run ID if this is a resumed run.
        created_at: Timestamp of run creation.
        best_score: Best score achieved (from rank-1 solution).
        alias: Alias of the rank-1 solution (if set).
        llm_type: ``"single"`` or ``"ensemble"``.
        backend: Evolution backend name (ADR-007). Defaults to ``"openevolve"``.
    """

    run_id: str
    problem_version: str
    llm: str
    dataset: str
    iterations: int
    valid_iterations: int | None = None
    generation_time_s: float = 0.0
    token_usage: TokenUsage | None = None
    status: str
    resumed_from: str | None = None
    created_at: datetime
    best_score: float | None = None
    alias: str | None = None
    llm_type: str = "single"
    backend: str = "openevolve"


class RunInfo(BaseModel):
    """Detailed run information for ``revolver run info`` output.

    Attributes:
        run_id: Unique run identifier.
        problem_version: Problem version tag used.
        problem_hash: Hash of the problem snapshot used.
        llm: LLM registry name used.
        llm_model: Full model identifier.
        dataset: Dataset name used.
        dataset_hash: Hash of the dataset at registration time.
        iterations: Number of iterations executed.
        valid_iterations: Number of iterations that produced valid programs.
        generation_time_s: Wall-clock generation time in seconds.
        token_usage: Token counts and cost estimate.
        status: Run status.
        resumed_from: Parent run ID if resumed.
        created_at: Timestamp of run creation.
        solutions: All solutions (auto-created + extracted) for this run.
        programs: All stored programs from OpenEvolve output.
        programs_extracted: Number of programs materialized to the run's
            ``programs/`` directory (equals ``len(programs)``).
        total_programs: Total programs in the backend's store (all rows in
            ShinkaEvolve's ``programs.sqlite``; ``None`` on OpenEvolve, where
            a full total needs checkpoint parsing — UX-4 / S16-19).
        run_best_score: Best score recorded by the engine at run completion,
            used as a display-time fallback for the rank-1 solution score
            when its own score is missing (UX-4 / S16-20, #306 — never a DB
            write). A max over single, survivorship-prone evaluations: it is
            rendered ONLY under the "engine, single eval" label
            (S18 / U11 — FR-RUN-055), never bare.
        post_eval_score: Post-run training-eval mean of ``combined_score``
            over solved instances (honest, multi-instance — S18 / U11,
            FR-RUN-055). Read back from the persisted post-run eval
            (FR-RUN-019 via ``core.eval``). ``None`` when no post-run eval
            exists or no instance produced a score.
        post_eval_instances_valid: Coverage label numerator (FR-RUN-053):
            number of instances contributing to ``post_eval_score``.
        post_eval_instances_total: Coverage label denominator (FR-RUN-053):
            total training instances in the post-run eval.
        resume_chain: Ordered list of ancestor run IDs.
        llm_type: ``"single"`` or ``"ensemble"``.
        llm_snapshot: JSON string with LLM/ensemble configuration snapshot.
        backend: Evolution backend name (ADR-007). Defaults to ``"openevolve"``.
    """

    run_id: str
    problem_version: str
    problem_hash: str
    llm: str
    llm_model: str
    dataset: str
    dataset_hash: str
    iterations: int
    valid_iterations: int | None = None
    generation_time_s: float = 0.0
    token_usage: TokenUsage | None = None
    status: str
    resumed_from: str | None = None
    created_at: datetime
    solutions: list[SolutionResult] = []
    programs: list[ProgramEntry] = []
    programs_extracted: int = 0
    total_programs: int | None = None
    run_best_score: float | None = None
    post_eval_score: float | None = None
    post_eval_instances_valid: int | None = None
    post_eval_instances_total: int | None = None
    resume_chain: list[str] = []
    llm_type: str = "single"
    llm_snapshot: str | None = None
    backend: str = "openevolve"
    produced_no_children: bool = False
    """True when the run completed but produced no evolved child programs —
    only the initial seed(s) remain (the unproductive-run case, backlog
    #302). Computed at read time; only meaningful on backends that can
    distinguish children from seeds."""


class ProgressInfo(BaseModel):
    """Progress callback data from OpenEvolve during a run.

    Attributes:
        iteration: Current iteration number.
        total_iterations: Total planned iterations.
        best_score: Best score achieved so far.
        elapsed_s: Elapsed wall-clock time in seconds.
    """

    iteration: int
    total_iterations: int
    best_score: float
    elapsed_s: float
