"""L1 unit tests for revolver.models.run — Run Pydantic models (S4-04)."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest
import yaml

from revolver.models.run import (
    ProgramEntry,
    ProgressInfo,
    ResolvedConfig,
    RunConfig,
    RunInfo,
    RunManifest,
    RunResult,
    RunStatus,
    RunSummary,
    SolutionResult,
    TokenUsage,
)


class TestTokenUsage:
    """Tests for TokenUsage model."""

    @pytest.mark.unit
    def test_total_tokens_computed(self) -> None:
        """total_tokens is the sum of prompt + completion tokens."""
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50)
        assert usage.total_tokens == 150

    @pytest.mark.unit
    def test_total_tokens_defaults(self) -> None:
        """total_tokens defaults to 0 when no tokens provided."""
        usage = TokenUsage()
        assert usage.total_tokens == 0
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0

    @pytest.mark.unit
    def test_no_cost_field(self) -> None:
        """Cost is not reported (S15 / #300): the field is gone from the model."""
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500)
        assert not hasattr(usage, "estimated_cost_usd")
        data = usage.model_dump()
        assert "estimated_cost_usd" not in data
        assert usage.total_tokens == 1500

    @pytest.mark.unit
    def test_serialization_includes_total(self) -> None:
        """model_dump includes the computed total_tokens field."""
        usage = TokenUsage(prompt_tokens=200, completion_tokens=100)
        data = usage.model_dump()
        assert data["total_tokens"] == 300
        assert data["prompt_tokens"] == 200
        assert data["completion_tokens"] == 100


class TestRunConfig:
    """Tests for RunConfig model."""

    @pytest.mark.unit
    def test_valid_config(self) -> None:
        """RunConfig validates with all required fields."""
        config = RunConfig(
            problem_version="v1.0",
            llm_name="codestral-local",
            dataset_name="train-small",
        )
        assert config.problem_version == "v1.0"
        assert config.llm_name == "codestral-local"
        assert config.dataset_name == "train-small"

    @pytest.mark.unit
    def test_defaults(self) -> None:
        """RunConfig applies defaults for optional fields."""
        config = RunConfig(
            problem_version="v1.0",
            llm_name="test-llm",
            dataset_name="train",
        )
        assert config.iterations is None
        assert config.alias is None
        assert config.config_overrides == []
        assert config.dry_run is False
        # New Sprint 017 ensemble levers default to None (zero behavior change).
        assert config.selection is None
        assert config.selection_kwargs is None
        assert config.llm_weight_overrides is None

    @pytest.mark.unit
    def test_selection_levers_round_trip(self) -> None:
        """RunConfig carries the raw --selection / --selection-kwarg / --llm-weight levers."""
        config = RunConfig(
            problem_version="v1.0",
            llm_name="my-ensemble",
            dataset_name="train",
            selection="ucb",
            selection_kwargs=["cost_aware_coef=0.3"],
            llm_weight_overrides=["gpt4o=0.7", "claude=0.3"],
        )
        assert config.selection == "ucb"
        assert config.selection_kwargs == ["cost_aware_coef=0.3"]
        assert config.llm_weight_overrides == ["gpt4o=0.7", "claude=0.3"]
        # Raw strings survive a serialization round-trip unparsed.
        assert RunConfig.model_validate(config.model_dump()).selection == "ucb"

    @pytest.mark.unit
    def test_with_all_fields(self) -> None:
        """RunConfig accepts all optional fields."""
        config = RunConfig(
            problem_version="v2.0",
            llm_name="claude-opus",
            dataset_name="eval-benchmark",
            iterations=500,
            alias="my-run",
            config_overrides=["llm.temperature=0.8", "num_islands=5"],
            dry_run=True,
        )
        assert config.iterations == 500
        assert config.alias == "my-run"
        assert len(config.config_overrides) == 2
        assert config.dry_run is True

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """RunConfig raises ValidationError when required fields are missing."""
        with pytest.raises(ValidationError):
            RunConfig(problem_version="v1.0")  # type: ignore[call-arg]


class TestProgramEntry:
    """Tests for ProgramEntry model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """ProgramEntry can be created with valid data."""
        entry = ProgramEntry(rank=1, score=0.95, file="programs/rank-1.py")
        assert entry.rank == 1
        assert entry.score == 0.95
        assert entry.file == "programs/rank-1.py"

    @pytest.mark.unit
    def test_score_nullable(self) -> None:
        """ProgramEntry accepts None score."""
        entry = ProgramEntry(rank=2, file="programs/rank-2.py")
        assert entry.score is None


class TestSolutionResult:
    """Tests for SolutionResult model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """SolutionResult can be created with valid data."""
        sol = SolutionResult(
            solution_id="sol-20260310-143000",
            run_id="run-20260310-143000",
            rank=1,
            best_score=0.95,
            alias="best-v1",
        )
        assert sol.solution_id == "sol-20260310-143000"
        assert sol.run_id == "run-20260310-143000"
        assert sol.rank == 1
        assert sol.best_score == 0.95
        assert sol.alias == "best-v1"

    @pytest.mark.unit
    def test_defaults(self) -> None:
        """SolutionResult applies defaults for optional fields."""
        sol = SolutionResult(
            solution_id="sol-1",
            run_id="run-1",
            rank=1,
        )
        assert sol.alias is None
        assert sol.best_score is None


class TestRunManifest:
    """Tests for RunManifest model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """RunManifest validates with required fields."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        manifest = RunManifest(
            run_id="run-20260310-143000",
            created_at=now,
            iterations=100,
            problem_version="v1.0",
            problem_hash="sha256:abc",
            dataset="train-small",
            dataset_hash="sha256:def",
            llm="codestral-local",
            llm_model="codestral:22b",
        )
        assert manifest.run_id == "run-20260310-143000"
        assert manifest.iterations == 100
        assert manifest.status == "running"

    @pytest.mark.unit
    def test_frozen(self) -> None:
        """RunManifest is frozen and rejects attribute assignment."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        manifest = RunManifest(
            run_id="run-1",
            created_at=now,
            iterations=100,
            problem_version="v1.0",
            problem_hash="sha256:abc",
            dataset="train",
            dataset_hash="sha256:def",
            llm="test-llm",
            llm_model="test-model",
        )
        with pytest.raises(ValidationError):
            manifest.status = "completed"  # type: ignore[misc]

    @pytest.mark.unit
    def test_with_token_usage_and_solution(self) -> None:
        """RunManifest accepts token_usage and solution."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        usage = TokenUsage(prompt_tokens=1000, completion_tokens=500)
        sol = SolutionResult(
            solution_id="sol-1",
            run_id="run-1",
            rank=1,
            best_score=0.95,
        )
        manifest = RunManifest(
            run_id="run-1",
            created_at=now,
            iterations=100,
            status="completed",
            generation_time_s=120.5,
            problem_version="v1.0",
            problem_hash="sha256:abc",
            dataset="train",
            dataset_hash="sha256:def",
            llm="test-llm",
            llm_model="test-model",
            token_usage=usage,
            solution=sol,
            programs=[
                ProgramEntry(rank=1, score=0.95, file="programs/rank-1.py"),
                ProgramEntry(rank=2, score=0.90, file="programs/rank-2.py"),
            ],
        )
        assert manifest.token_usage is not None
        assert manifest.token_usage.total_tokens == 1500
        assert manifest.solution is not None
        assert len(manifest.programs) == 2

    @pytest.mark.unit
    def test_defaults(self) -> None:
        """RunManifest applies defaults for optional fields."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        manifest = RunManifest(
            run_id="run-1",
            created_at=now,
            iterations=50,
            problem_version="v1.0",
            problem_hash="sha256:abc",
            dataset="train",
            dataset_hash="sha256:def",
            llm="test-llm",
            llm_model="test-model",
        )
        assert manifest.generation_time_s is None
        assert manifest.resumed_from is None
        assert manifest.token_usage is None
        assert manifest.solution is None
        assert manifest.programs == []
        assert manifest.checkpoint == "oe-checkpoint/"
        assert manifest.config_file == "config.yaml"


class TestRunResult:
    """Tests for RunResult model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """RunResult validates with valid data."""
        sol = SolutionResult(
            solution_id="sol-1",
            run_id="run-1",
            rank=1,
            best_score=0.95,
        )
        result = RunResult(
            run_id="run-1",
            solution=sol,
            programs_stored=3,
            problem_version="v1.0",
            llm="codestral-local",
            dataset="train-small",
            iterations=100,
            generation_time_s=120.5,
        )
        assert result.run_id == "run-1"
        assert result.solution.solution_id == "sol-1"
        assert result.programs_stored == 3
        assert result.token_usage is None
        assert result.resumed_from is None


class TestRunStatus:
    """Tests for RunStatus model."""

    @pytest.mark.unit
    def test_active_status(self) -> None:
        """RunStatus with active runs."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        status = RunStatus(
            active=True,
            run_ids=["run-1", "run-2"],
            problem_version="v1.0",
            llm="test-llm",
            dataset="train",
            iterations_completed=50,
            iterations_total=100,
            best_score=0.85,
            started_at=now,
            elapsed_s=60.0,
        )
        assert status.active is True
        assert len(status.run_ids) == 2

    @pytest.mark.unit
    def test_inactive_status(self) -> None:
        """RunStatus with no active runs."""
        status = RunStatus(
            active=False,
            run_id="run-last",
        )
        assert status.active is False
        assert status.run_ids == []
        assert status.run_id == "run-last"


class TestRunSummary:
    """Tests for RunSummary model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """RunSummary validates with valid data."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        summary = RunSummary(
            run_id="run-1",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train",
            iterations=100,
            status="completed",
            created_at=now,
            best_score=0.95,
        )
        assert summary.run_id == "run-1"
        assert summary.status == "completed"
        assert summary.best_score == 0.95


class TestRunInfo:
    """Tests for RunInfo model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """RunInfo validates with valid data."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        info = RunInfo(
            run_id="run-1",
            problem_version="v1.0",
            problem_hash="sha256:abc",
            llm="test-llm",
            llm_model="test-model",
            dataset="train",
            dataset_hash="sha256:def",
            iterations=100,
            generation_time_s=120.5,
            status="completed",
            created_at=now,
            solutions=[
                SolutionResult(
                    solution_id="sol-1",
                    run_id="run-1",
                    rank=1,
                    best_score=0.95,
                ),
            ],
            programs=[
                ProgramEntry(rank=1, score=0.95, file="programs/rank-1.py"),
            ],
            resume_chain=["run-0", "run-1"],
        )
        assert info.run_id == "run-1"
        assert len(info.solutions) == 1
        assert len(info.programs) == 1
        assert info.resume_chain == ["run-0", "run-1"]

    @pytest.mark.unit
    def test_defaults(self) -> None:
        """RunInfo applies defaults for optional fields."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        info = RunInfo(
            run_id="run-1",
            problem_version="v1.0",
            problem_hash="sha256:abc",
            llm="test-llm",
            llm_model="test-model",
            dataset="train",
            dataset_hash="sha256:def",
            iterations=100,
            status="running",
            created_at=now,
        )
        assert info.solutions == []
        assert info.programs == []
        assert info.resume_chain == []
        assert info.token_usage is None
        assert info.resumed_from is None


class TestProgressInfo:
    """Tests for ProgressInfo model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """ProgressInfo validates with valid data."""
        progress = ProgressInfo(
            iteration=50,
            total_iterations=100,
            best_score=0.85,
            elapsed_s=30.0,
        )
        assert progress.iteration == 50
        assert progress.total_iterations == 100
        assert progress.best_score == 0.85
        assert progress.elapsed_s == 30.0

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """ProgressInfo raises ValidationError when required fields are missing."""
        with pytest.raises(ValidationError):
            ProgressInfo(iteration=10)  # type: ignore[call-arg]


class TestDatetimeSerialization:
    """Tests for datetime serialization across run models."""

    @pytest.mark.unit
    def test_run_manifest_datetime_round_trip(self) -> None:
        """RunManifest datetime serialises to ISO 8601 and back."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        manifest = RunManifest(
            run_id="run-1",
            created_at=now,
            iterations=100,
            problem_version="v1.0",
            problem_hash="sha256:abc",
            dataset="train",
            dataset_hash="sha256:def",
            llm="test-llm",
            llm_model="test-model",
        )
        data = manifest.model_dump()
        restored = RunManifest.model_validate(data)
        assert restored.created_at == now

    @pytest.mark.unit
    def test_run_summary_datetime_round_trip(self) -> None:
        """RunSummary datetime serialises and deserialises correctly."""
        now = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        summary = RunSummary(
            run_id="run-1",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train",
            iterations=100,
            status="completed",
            created_at=now,
        )
        data = summary.model_dump()
        restored = RunSummary.model_validate(data)
        assert restored.created_at == now


class TestResolvedConfig:
    """Tests for the backend-neutral ResolvedConfig model (ADR-007 D4)."""

    @pytest.mark.unit
    def test_defaults(self) -> None:
        """ResolvedConfig instantiates with only backend; extras default to {}."""
        config = ResolvedConfig(backend="openevolve")
        assert config.backend == "openevolve"
        assert config.iterations is None
        assert config.num_islands is None
        assert config.temperature is None
        assert config.language is None
        assert config.llm_models is None
        assert config.config_overrides is None
        assert config.backend_extras == {}

    @pytest.mark.unit
    def test_backend_required(self) -> None:
        """ResolvedConfig requires the backend field."""
        with pytest.raises(ValidationError):
            ResolvedConfig()  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_backend_extras_not_shared(self) -> None:
        """backend_extras default dict is not shared between instances."""
        a = ResolvedConfig(backend="openevolve")
        b = ResolvedConfig(backend="shinka")
        a.backend_extras["checkpoint_interval"] = 10
        assert b.backend_extras == {}

    @pytest.mark.unit
    def test_with_all_fields(self) -> None:
        """ResolvedConfig accepts all neutral fields and backend extras."""
        config = ResolvedConfig(
            backend="openevolve",
            iterations=100,
            num_islands=4,
            temperature=0.8,
            language="python",
            llm_models=[{"name": "test-model", "weight": 1.0}],
            config_overrides={"llm.temperature": "0.8"},
            backend_extras={"checkpoint_interval": 10, "max_code_length": 50000},
        )
        assert config.iterations == 100
        assert config.num_islands == 4
        assert config.temperature == 0.8
        assert config.language == "python"
        assert config.llm_models == [{"name": "test-model", "weight": 1.0}]
        assert config.config_overrides == {"llm.temperature": "0.8"}
        assert config.backend_extras["checkpoint_interval"] == 10


class TestBackendField:
    """Tests for the backend field on run models (ADR-007, FR-RUN-047)."""

    @pytest.mark.unit
    def test_run_config_backend_default(self) -> None:
        """RunConfig defaults backend to 'openevolve'."""
        config = RunConfig(
            problem_version="v1.0",
            llm_name="test-llm",
            dataset_name="train",
        )
        assert config.backend == "openevolve"

    @pytest.mark.unit
    def test_run_manifest_backend_default(self) -> None:
        """RunManifest defaults backend to 'openevolve'."""
        manifest = RunManifest(
            run_id="run-1",
            created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
            iterations=100,
            problem_version="v1.0",
            problem_hash="sha256:abc",
            dataset="train",
            dataset_hash="sha256:def",
            llm="test-llm",
            llm_model="test-model",
        )
        assert manifest.backend == "openevolve"

    @pytest.mark.unit
    def test_run_manifest_yaml_without_backend_loads(self) -> None:
        """A pre-v9 manifest YAML without a backend key loads with the default."""
        manifest_yaml = """\
run_id: run-20260310-143000
created_at: 2026-03-10T14:30:00+00:00
iterations: 100
status: completed
problem_version: v1.0
problem_hash: sha256:abc
dataset: train-small
dataset_hash: sha256:def
llm: codestral-local
llm_model: codestral:22b
"""
        data = yaml.safe_load(manifest_yaml)
        assert "backend" not in data
        manifest = RunManifest.model_validate(data)
        assert manifest.backend == "openevolve"
        assert manifest.run_id == "run-20260310-143000"

    @pytest.mark.unit
    def test_run_summary_backend_default(self) -> None:
        """RunSummary defaults backend to 'openevolve'."""
        summary = RunSummary(
            run_id="run-1",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train",
            iterations=100,
            status="completed",
            created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        )
        assert summary.backend == "openevolve"

    @pytest.mark.unit
    def test_run_info_backend_default(self) -> None:
        """RunInfo defaults backend to 'openevolve'."""
        info = RunInfo(
            run_id="run-1",
            problem_version="v1.0",
            problem_hash="sha256:abc",
            llm="test-llm",
            llm_model="test-model",
            dataset="train",
            dataset_hash="sha256:def",
            iterations=100,
            status="completed",
            created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        )
        assert info.backend == "openevolve"

    @pytest.mark.unit
    def test_backend_explicit_value(self) -> None:
        """The backend field accepts an explicit non-default value."""
        config = RunConfig(
            problem_version="v1.0",
            llm_name="test-llm",
            dataset_name="train",
            backend="shinka",
        )
        assert config.backend == "shinka"


class TestRunResultResolvedConfig:
    """RunResult.resolved_config holds the neutral model (S13 PR-C).

    The legacy ``ResolvedOEConfig`` was removed with the union narrowing
    (ADR-007 D4, Sprint 013 PR-C).
    """

    @staticmethod
    def _make_result(resolved: ResolvedConfig | None) -> RunResult:
        sol = SolutionResult(solution_id="sol-1", run_id="run-1", rank=1)
        return RunResult(
            run_id="run-1",
            solution=sol,
            programs_stored=1,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train",
            iterations=100,
            generation_time_s=10.0,
            resolved_config=resolved,
        )

    @pytest.mark.unit
    def test_accepts_neutral_resolved_config(self) -> None:
        """RunResult accepts the neutral ResolvedConfig."""
        neutral = ResolvedConfig(backend="openevolve", iterations=100)
        result = self._make_result(neutral)
        assert isinstance(result.resolved_config, ResolvedConfig)
        assert result.resolved_config.backend == "openevolve"

    @pytest.mark.unit
    def test_accepts_none(self) -> None:
        """RunResult resolved_config remains optional."""
        result = self._make_result(None)
        assert result.resolved_config is None

    @pytest.mark.unit
    def test_backend_extras_round_trip(self) -> None:
        """OE-exclusive keys live in backend_extras (ADR-007 D4)."""
        neutral = ResolvedConfig(
            backend="openevolve",
            iterations=100,
            backend_extras={"checkpoint_interval": 10, "diff_based_evolution": False},
        )
        result = self._make_result(neutral)
        assert result.resolved_config is not None
        assert result.resolved_config.backend_extras["checkpoint_interval"] == 10
        assert result.resolved_config.backend_extras["diff_based_evolution"] is False
