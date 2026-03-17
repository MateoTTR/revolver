"""Pydantic models for run orchestration and result reporting.

Models cover the full lifecycle of an OpenEvolve run: configuration,
execution status, result collection, and detailed info queries.

Traceable to: DES-005 (Run Orchestration) §8, FR-RUN-001..030.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


class TokenUsage(BaseModel):
    """Token usage accumulated during a run.

    Attributes:
        prompt_tokens: Total input tokens consumed (0 if unavailable).
        completion_tokens: Total output tokens consumed (0 if unavailable).
        total_tokens: Sum of prompt + completion tokens (computed).
        estimated_cost_usd: Estimated cost in USD, computed at read time
            from LLM pricing. ``None`` if pricing is unavailable.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float | None = None

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
    """

    problem_version: str
    llm_name: str
    dataset_name: str
    iterations: int | None = None
    alias: str | None = None
    config_overrides: list[str] = Field(default_factory=list)
    dry_run: bool = False


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
        status: Run status (``"running"``, ``"completed"``, ``"interrupted"``).
        problem_version: Problem version tag used.
        problem_hash: Hash of the problem snapshot used.
        dataset: Dataset name used.
        dataset_hash: Hash of the dataset at registration time.
        llm: LLM registry name used.
        llm_model: Full model identifier (e.g. ``"claude-opus-4-6"``).
        resumed_from: Parent run ID if this is a resumed run.
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
    status: str = "running"

    # Lineage
    problem_version: str
    problem_hash: str
    dataset: str
    dataset_hash: str
    llm: str
    llm_model: str
    resumed_from: str | None = None

    # Token usage (FR-RUN-028/029/030)
    token_usage: TokenUsage | None = None

    # Solution
    solution: SolutionResult | None = None

    # Files
    programs: list[ProgramEntry] = []
    checkpoint: str = "oe-checkpoint/"
    config_file: str = "config.yaml"


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
        generation_time_s: Wall-clock generation time in seconds.
        token_usage: Token counts from the proxy (``None`` if unavailable).
        resumed_from: Parent run ID if this is a resumed run.
    """

    run_id: str
    solution: SolutionResult
    programs_stored: int
    problem_version: str
    llm: str
    dataset: str
    iterations: int
    generation_time_s: float
    token_usage: TokenUsage | None = None
    resumed_from: str | None = None


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
        generation_time_s: Wall-clock generation time in seconds.
        token_usage: Token counts for display in list view.
        status: Run status (``"running"``, ``"completed"``, ``"interrupted"``).
        resumed_from: Parent run ID if this is a resumed run.
        created_at: Timestamp of run creation.
        best_score: Best score achieved (from rank-1 solution).
        alias: Alias of the rank-1 solution (if set).
    """

    run_id: str
    problem_version: str
    llm: str
    dataset: str
    iterations: int
    generation_time_s: float = 0.0
    token_usage: TokenUsage | None = None
    status: str
    resumed_from: str | None = None
    created_at: datetime
    best_score: float | None = None
    alias: str | None = None


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
        generation_time_s: Wall-clock generation time in seconds.
        token_usage: Token counts and cost estimate.
        status: Run status.
        resumed_from: Parent run ID if resumed.
        created_at: Timestamp of run creation.
        solutions: All solutions (auto-created + extracted) for this run.
        programs: All stored programs from OpenEvolve output.
        resume_chain: Ordered list of ancestor run IDs.
    """

    run_id: str
    problem_version: str
    problem_hash: str
    llm: str
    llm_model: str
    dataset: str
    dataset_hash: str
    iterations: int
    generation_time_s: float = 0.0
    token_usage: TokenUsage | None = None
    status: str
    resumed_from: str | None = None
    created_at: datetime
    solutions: list[SolutionResult] = []
    programs: list[ProgramEntry] = []
    resume_chain: list[str] = []


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
