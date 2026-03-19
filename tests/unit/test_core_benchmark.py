"""L1 unit tests for core.benchmark (S6-03/04/05).

Tests cover:
- run_benchmark: reuse path, trigger path, partial failure, all-fail, lineage
- get_benchmark_results: aggregate mode, per-instance mode with wins + ties
- export_benchmark: CSV schema, JSON schema, no secrets
- list_benchmarks: returns BenchmarkSummary list

All DB and eval functions are mocked at the module level:
  - revolver.core.benchmark.db.* (via the db import aliases)
  - revolver.core.benchmark.evaluate_solution
  - revolver.core.benchmark.verify_dataset_integrity
  - revolver.core.benchmark.find_project_root
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from unittest.mock import MagicMock, patch

import pytest

from revolver.core.benchmark import (
    BenchmarkError,
    BenchmarkNotFoundError,
    ExportError,
    _build_comparison_matrix,
    _ensure_evaluated,
    export_benchmark,
    generate_benchmark_id,
    get_benchmark_results,
    list_benchmarks,
    run_benchmark,
)
from revolver.core.eval import generate_eval_id
from revolver.core.exceptions import EvalError
from revolver.models.benchmark import (
    BenchmarkDetailResult,
    BenchmarkEntry,
    BenchmarkResult,
    BenchmarkSummary,
    EvalStatus,
    InstanceComparison,
    InstanceSolutionResult,
    SolutionLineage,
)
from revolver.models.eval import EvalMetadata, InstanceResult, MetricAggregate

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_solution(sol_id: str = "sol-001", alias: str | None = None) -> MagicMock:
    """Create a mock Solution object."""
    sol = MagicMock()
    sol.id = sol_id
    sol.alias = alias
    sol.run_id = "run-001"
    sol.rank = 1
    sol.best_score = 0.95
    return sol


def _make_run(
    run_id: str = "run-001",
    generation_time_s: float | None = 8100.0,
) -> dict[str, object]:
    """Create a mock run dict."""
    return {
        "id": run_id,
        "problem_version": "v1.1",
        "llm": "claude-opus",
        "llm_model": "claude-opus-4-6",
        "dataset": "train-small",
        "iterations": 200,
        "generation_time_s": generation_time_s,
        "status": "completed",
    }


def _make_eval_metadata(
    eval_id: str = "eval-001",
    solution_id: str = "sol-001",
    dataset_name: str = "eval-bench",
    instance_count: int = 10,
    instances_solved: int = 10,
    eval_time_s: float | None = 60.0,
    user_aggregates: dict[str, float] | None = None,
) -> EvalMetadata:
    """Create an EvalMetadata instance."""
    return EvalMetadata(
        eval_id=eval_id,
        solution_id=solution_id,
        dataset_name=dataset_name,
        instance_count=instance_count,
        instances_solved=instances_solved,
        eval_time_s=eval_time_s,
        evaluated_at=datetime(2026, 3, 10, 17, 0, 0, tzinfo=UTC),
        user_aggregates=user_aggregates,
    )


def _make_instance_results(
    n: int = 5,
    metric_name: str = "combined_score",
    value: float = 0.87,
    status: str = "solved",
) -> list[InstanceResult]:
    """Create a list of InstanceResult objects."""
    return [
        InstanceResult(
            instance_id=f"inst-{i:03d}",
            status=status,  # type: ignore[arg-type]
            metrics={metric_name: value} if status == "solved" else {},
            compute_time_s=1.0 + i * 0.1,
        )
        for i in range(n)
    ]


def _make_lineage() -> SolutionLineage:
    """Create a SolutionLineage."""
    return SolutionLineage(
        problem_version="v1.1",
        llm="claude-opus",
        llm_model="claude-opus-4-6",
        train_dataset="train-small",
        iterations=200,
        generation_time_s=8100.0,
    )


def _make_benchmark_entry(
    solution_id: str = "sol-001",
    alias: str | None = "claude-small-v1.1",
    metric_value: float = 0.87,
) -> BenchmarkEntry:
    """Create a BenchmarkEntry."""
    agg = MetricAggregate(
        mean=metric_value,
        min=0.62,
        max=0.95,
        p10=0.71,
        p50=metric_value,
        p90=0.93,
        std=0.08,
        count=10,
    )
    return BenchmarkEntry(
        solution_id=solution_id,
        alias=alias,
        run_id="run-001",
        lineage=_make_lineage(),
        metrics={"combined_score": agg},
        eval_time_s=60.0,
        instances_count=10,
        instances_solved=10,
    )


def _make_benchmark_result(
    benchmark_id: str = "bench-20260310-170000",
    entries: list[BenchmarkEntry] | None = None,
) -> BenchmarkResult:
    """Create a BenchmarkResult."""
    if entries is None:
        entries = [_make_benchmark_entry()]
    return BenchmarkResult(
        benchmark_id=benchmark_id,
        alias=None,
        dataset_name="eval-bench",
        instance_count=10,
        entries=entries,
        created_at=datetime(2026, 3, 10, 17, 0, 0, tzinfo=UTC),
    )


# ── generate_eval_id ───────────────────────────────────────────────────────────


class TestGenerateEvalId:
    """Tests for generate_eval_id() collision avoidance (F1 fix)."""

    @pytest.mark.unit
    def test_format_without_suffix(self) -> None:
        """ID has the eval-YYYYMMDD-HHMMSS format without suffix."""
        eid = generate_eval_id()
        assert eid.startswith("eval-")
        parts = eid.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # HHMMSS

    @pytest.mark.unit
    def test_format_with_suffix(self) -> None:
        """ID includes the suffix when provided."""
        eid = generate_eval_id(suffix=3)
        assert eid.startswith("eval-")
        parts = eid.split("-")
        assert len(parts) == 4
        assert parts[3] == "3"

    @pytest.mark.unit
    def test_no_suffix_when_none(self) -> None:
        """No suffix appended when suffix=None."""
        eid = generate_eval_id(suffix=None)
        parts = eid.split("-")
        assert len(parts) == 3

    @pytest.mark.unit
    def test_suffix_produces_distinct_ids(self) -> None:
        """Different suffixes produce distinct IDs for collision avoidance."""
        base = generate_eval_id(suffix=None)
        suffixed = generate_eval_id(suffix=2)
        assert base != suffixed
        assert suffixed.endswith("-2")


# ── generate_benchmark_id ──────────────────────────────────────────────────────


class TestGenerateBenchmarkId:
    """Tests for generate_benchmark_id()."""

    @pytest.mark.unit
    def test_format(self) -> None:
        """ID has the bench-YYYYMMDD-HHMMSS format."""
        bid = generate_benchmark_id()
        assert bid.startswith("bench-")
        # Format: bench-YYYYMMDD-HHMMSS → 3 parts when split on "-"
        parts = bid.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # HHMMSS


# ── _ensure_evaluated ──────────────────────────────────────────────────────────


class TestEnsureEvaluated:
    """Tests for _ensure_evaluated()."""

    @pytest.mark.unit
    def test_reuses_existing_eval(self, tmp_path: Path) -> None:
        """Returns status='reused' when eval_metadata already exists."""
        existing_meta = _make_eval_metadata(eval_id="eval-existing")

        with (
            patch("revolver.core.benchmark.get_project_db") as mock_db,
            patch("revolver.core.benchmark.get_eval_metadata") as mock_get_meta,
        ):
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            mock_get_meta.return_value = existing_meta

            result = _ensure_evaluated("sol-001", "eval-bench", 300, tmp_path)

        assert result.status == "reused"
        assert result.eval_id == "eval-existing"
        assert result.error is None

    @pytest.mark.unit
    def test_triggers_evaluation_when_missing(self, tmp_path: Path) -> None:
        """Calls evaluate_solution() and returns status='evaluated' when no eval exists."""
        mock_eval_result = MagicMock()
        mock_eval_result.metadata.eval_id = "eval-new"

        with (
            patch("revolver.core.benchmark.get_project_db") as mock_db,
            patch("revolver.core.benchmark.get_eval_metadata") as mock_get_meta,
            patch("revolver.core.benchmark.evaluate_solution") as mock_eval,
        ):
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            mock_get_meta.return_value = None
            mock_eval.return_value = mock_eval_result

            result = _ensure_evaluated("sol-001", "eval-bench", 300, tmp_path)

        assert result.status == "evaluated"
        assert result.eval_id == "eval-new"
        mock_eval.assert_called_once_with(
            solution_id_or_alias="sol-001",
            dataset_name="eval-bench",
            timeout_s=300,
            force=True,
            project_root=tmp_path,
        )

    @pytest.mark.unit
    def test_returns_failed_on_eval_error(self, tmp_path: Path) -> None:
        """Returns status='failed' when evaluate_solution() raises EvalError."""
        with (
            patch("revolver.core.benchmark.get_project_db") as mock_db,
            patch("revolver.core.benchmark.get_eval_metadata") as mock_get_meta,
            patch("revolver.core.benchmark.evaluate_solution") as mock_eval,
        ):
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            mock_get_meta.return_value = None
            mock_eval.side_effect = EvalError("evaluator failed")

            result = _ensure_evaluated("sol-001", "eval-bench", 300, tmp_path)

        assert result.status == "failed"
        assert result.eval_id is None
        assert "evaluator failed" in (result.error or "")


# ── run_benchmark ──────────────────────────────────────────────────────────────


class TestRunBenchmark:
    """Tests for run_benchmark()."""

    def _patch_all(
        self,
        tmp_path: Path,
        sol: MagicMock,
        run: dict[str, object],
        eval_meta: EvalMetadata,
        instances: list[InstanceResult],
        ensure_status: Literal["reused", "evaluated", "failed"] = "reused",
    ) -> dict[str, Any]:
        """Create a dict of patches for run_benchmark."""
        patches: dict[str, Any] = {}

        # Mock find_project_root
        patches["find_project_root"] = patch(
            "revolver.core.benchmark.find_project_root", return_value=tmp_path
        )

        # Mock get_project_db to return a mock connection
        patches["get_project_db"] = patch(
            "revolver.core.benchmark.get_project_db",
            return_value=MagicMock(),
        )

        # Mock DB functions
        patches["get_solution"] = patch("revolver.core.benchmark.get_solution", return_value=sol)
        patches["get_dataset"] = patch(
            "revolver.core.benchmark.get_dataset",
            return_value=MagicMock(split="eval"),
        )
        patches["verify_dataset_integrity"] = patch(
            "revolver.core.benchmark.verify_dataset_integrity",
            return_value=MagicMock(is_valid=True),
        )
        patches["get_eval_metadata"] = patch(
            "revolver.core.benchmark.get_eval_metadata", return_value=eval_meta
        )
        patches["get_eval_instances"] = patch(
            "revolver.core.benchmark.get_eval_instances", return_value=instances
        )
        patches["get_run"] = patch("revolver.core.benchmark.get_run", return_value=run)
        patches["insert_benchmark"] = patch("revolver.core.benchmark.insert_benchmark")
        patches["insert_benchmark_solutions"] = patch(
            "revolver.core.benchmark.insert_benchmark_solutions"
        )

        # Mock _ensure_evaluated at module level
        eval_status = EvalStatus(
            status=ensure_status,
            eval_id="eval-001" if ensure_status != "failed" else None,
            error="error!" if ensure_status == "failed" else None,
        )
        patches["_ensure_evaluated"] = patch(
            "revolver.core.benchmark._ensure_evaluated", return_value=eval_status
        )

        return patches

    @pytest.mark.unit
    def test_reuses_existing_eval(self, tmp_path: Path) -> None:
        """run_benchmark returns a result when eval already exists (reuse path)."""
        sol = _make_solution("sol-001", alias="my-sol")
        run = _make_run()
        meta = _make_eval_metadata()
        instances = _make_instance_results(n=5, value=0.87)
        patches = self._patch_all(tmp_path, sol, run, meta, instances, "reused")

        with (
            patches["find_project_root"],
            patches["get_project_db"],
            patches["get_solution"],
            patches["get_dataset"],
            patches["verify_dataset_integrity"],
            patches["get_eval_metadata"],
            patches["get_eval_instances"],
            patches["get_run"],
            patches["insert_benchmark"],
            patches["insert_benchmark_solutions"],
            patches["_ensure_evaluated"] as mock_ensure,
        ):
            result = run_benchmark(
                solution_ids_or_aliases=["sol-001"],
                dataset_name="eval-bench",
                project_root=tmp_path,
            )

        mock_ensure.assert_called_once_with("sol-001", "eval-bench", 300, tmp_path)
        assert isinstance(result, BenchmarkResult)
        assert len(result.entries) == 1
        assert result.failed_solutions == []
        assert result.entries[0].solution_id == "sol-001"

    @pytest.mark.unit
    def test_triggers_missing_eval(self, tmp_path: Path) -> None:
        """run_benchmark triggers evaluate_solution when eval doesn't exist."""
        sol = _make_solution("sol-002")
        run = _make_run()
        meta = _make_eval_metadata(solution_id="sol-002")
        instances = _make_instance_results(n=3, value=0.90)
        patches = self._patch_all(tmp_path, sol, run, meta, instances, "evaluated")

        with (
            patches["find_project_root"],
            patches["get_project_db"],
            patches["get_solution"],
            patches["get_dataset"],
            patches["verify_dataset_integrity"],
            patches["get_eval_metadata"],
            patches["get_eval_instances"],
            patches["get_run"],
            patches["insert_benchmark"],
            patches["insert_benchmark_solutions"],
            patches["_ensure_evaluated"] as mock_ensure,
        ):
            result = run_benchmark(
                solution_ids_or_aliases=["sol-002"],
                dataset_name="eval-bench",
                project_root=tmp_path,
            )

        mock_ensure.assert_called_once_with("sol-002", "eval-bench", 300, tmp_path)
        assert isinstance(result, BenchmarkResult)
        assert result.failed_solutions == []

    @pytest.mark.unit
    def test_partial_failure_continues(self, tmp_path: Path) -> None:
        """One solution fails eval; others succeed; partial result is returned."""
        sol_good = _make_solution("sol-good", alias="good")
        sol_bad = _make_solution("sol-bad", alias="bad")
        run = _make_run()
        meta_good = _make_eval_metadata(solution_id="sol-good")
        instances = _make_instance_results(n=5)

        statuses = {"sol-good": "reused", "sol-bad": "failed"}

        def _fake_ensure(
            solution_id: str, dataset_name: str, timeout_s: int, root: Path
        ) -> EvalStatus:
            s = statuses[solution_id]
            if s == "failed":
                return EvalStatus(status="failed", error="eval error")
            return EvalStatus(status="reused", eval_id="eval-001")

        def _fake_get_solution(conn: object, id_or_alias: str) -> MagicMock:
            if id_or_alias == "sol-good":
                return sol_good
            return sol_bad

        def _fake_get_eval_meta(
            conn: object, sol_id: str, ds_name: str | None = None
        ) -> EvalMetadata | None:
            if sol_id == "sol-good":
                return meta_good
            return None

        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_solution", side_effect=_fake_get_solution),
            patch("revolver.core.benchmark.get_dataset", return_value=MagicMock(split="eval")),
            patch(
                "revolver.core.benchmark.verify_dataset_integrity",
                return_value=MagicMock(is_valid=True),
            ),
            patch("revolver.core.benchmark._ensure_evaluated", side_effect=_fake_ensure),
            patch("revolver.core.benchmark.get_eval_metadata", side_effect=_fake_get_eval_meta),
            patch("revolver.core.benchmark.get_eval_instances", return_value=instances),
            patch("revolver.core.benchmark.get_run", return_value=run),
            patch("revolver.core.benchmark.insert_benchmark"),
            patch("revolver.core.benchmark.insert_benchmark_solutions"),
        ):
            result = run_benchmark(
                solution_ids_or_aliases=["sol-good", "sol-bad"],
                dataset_name="eval-bench",
                project_root=tmp_path,
            )

        assert isinstance(result, BenchmarkResult)
        assert len(result.entries) == 1
        assert result.entries[0].solution_id == "sol-good"
        assert "sol-bad" in result.failed_solutions

    @pytest.mark.unit
    def test_all_fail_raises_benchmark_error(self, tmp_path: Path) -> None:
        """All solutions fail eval → BenchmarkError is raised (exit code 4)."""
        sol = _make_solution("sol-001")

        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_solution", return_value=sol),
            patch("revolver.core.benchmark.get_dataset", return_value=MagicMock(split="eval")),
            patch(
                "revolver.core.benchmark.verify_dataset_integrity",
                return_value=MagicMock(is_valid=True),
            ),
            patch(
                "revolver.core.benchmark._ensure_evaluated",
                return_value=EvalStatus(status="failed", error="all failed"),
            ),
            pytest.raises(BenchmarkError) as exc_info,
        ):
            run_benchmark(
                solution_ids_or_aliases=["sol-001"],
                dataset_name="eval-bench",
                project_root=tmp_path,
            )

        assert "all solutions" in str(exc_info.value).lower()
        assert BenchmarkError.exit_code == 4

    @pytest.mark.unit
    def test_includes_lineage(self, tmp_path: Path) -> None:
        """run_benchmark enriches each entry with lineage from the parent run."""
        sol = _make_solution("sol-001", alias="my-sol")
        run = _make_run(generation_time_s=9000.0)
        meta = _make_eval_metadata()
        instances = _make_instance_results(n=3)

        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_solution", return_value=sol),
            patch("revolver.core.benchmark.get_dataset", return_value=MagicMock(split="eval")),
            patch(
                "revolver.core.benchmark.verify_dataset_integrity",
                return_value=MagicMock(is_valid=True),
            ),
            patch(
                "revolver.core.benchmark._ensure_evaluated",
                return_value=EvalStatus(status="reused", eval_id="eval-001"),
            ),
            patch("revolver.core.benchmark.get_eval_metadata", return_value=meta),
            patch("revolver.core.benchmark.get_eval_instances", return_value=instances),
            patch("revolver.core.benchmark.get_run", return_value=run),
            patch("revolver.core.benchmark.insert_benchmark"),
            patch("revolver.core.benchmark.insert_benchmark_solutions"),
        ):
            result = run_benchmark(
                solution_ids_or_aliases=["sol-001"],
                dataset_name="eval-bench",
                project_root=tmp_path,
            )

        entry = result.entries[0]
        assert entry.lineage.problem_version == "v1.1"
        assert entry.lineage.llm == "claude-opus"
        assert entry.lineage.llm_model == "claude-opus-4-6"
        assert entry.lineage.train_dataset == "train-small"
        assert entry.lineage.iterations == 200
        assert entry.lineage.generation_time_s == 9000.0

    @pytest.mark.unit
    def test_empty_solution_list_raises(self, tmp_path: Path) -> None:
        """Providing an empty solution list raises BenchmarkError."""
        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            pytest.raises(BenchmarkError),
        ):
            run_benchmark(
                solution_ids_or_aliases=[],
                dataset_name="eval-bench",
                project_root=tmp_path,
            )

    @pytest.mark.unit
    def test_on_progress_callback(self, tmp_path: Path) -> None:
        """on_progress is called with (solution_id, status) for each solution."""
        sol = _make_solution("sol-001")
        run = _make_run()
        meta = _make_eval_metadata()
        instances = _make_instance_results(n=2)
        progress_calls: list[tuple[str, str]] = []

        def record_progress(sol_id: str, status: str) -> None:
            progress_calls.append((sol_id, status))

        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_solution", return_value=sol),
            patch("revolver.core.benchmark.get_dataset", return_value=MagicMock(split="eval")),
            patch(
                "revolver.core.benchmark.verify_dataset_integrity",
                return_value=MagicMock(is_valid=True),
            ),
            patch(
                "revolver.core.benchmark._ensure_evaluated",
                return_value=EvalStatus(status="reused", eval_id="eval-001"),
            ),
            patch("revolver.core.benchmark.get_eval_metadata", return_value=meta),
            patch("revolver.core.benchmark.get_eval_instances", return_value=instances),
            patch("revolver.core.benchmark.get_run", return_value=run),
            patch("revolver.core.benchmark.insert_benchmark"),
            patch("revolver.core.benchmark.insert_benchmark_solutions"),
        ):
            run_benchmark(
                solution_ids_or_aliases=["sol-001"],
                dataset_name="eval-bench",
                on_progress=record_progress,
                project_root=tmp_path,
            )

        assert len(progress_calls) == 1
        assert progress_calls[0] == ("sol-001", "reused")

    @pytest.mark.unit
    def test_instance_count_mismatch_warns(self, tmp_path: Path, caplog: Any) -> None:
        """A warning is logged when solutions have different instance counts."""
        import logging

        sol_good = _make_solution("sol-good", alias="good")
        sol_other = _make_solution("sol-other", alias="other")
        run = _make_run()
        meta_good = _make_eval_metadata(solution_id="sol-good", instance_count=10)
        meta_other = _make_eval_metadata(solution_id="sol-other", instance_count=5)
        instances = _make_instance_results(n=5)

        def _fake_get_solution(conn: object, id_or_alias: str) -> MagicMock:
            return sol_good if id_or_alias == "sol-good" else sol_other

        def _fake_get_eval_meta(
            conn: object, sol_id: str, ds_name: str | None = None
        ) -> EvalMetadata:
            return meta_good if sol_id == "sol-good" else meta_other

        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_solution", side_effect=_fake_get_solution),
            patch("revolver.core.benchmark.get_dataset", return_value=MagicMock(split="eval")),
            patch(
                "revolver.core.benchmark.verify_dataset_integrity",
                return_value=MagicMock(is_valid=True),
            ),
            patch(
                "revolver.core.benchmark._ensure_evaluated",
                return_value=EvalStatus(status="reused", eval_id="eval-001"),
            ),
            patch("revolver.core.benchmark.get_eval_metadata", side_effect=_fake_get_eval_meta),
            patch("revolver.core.benchmark.get_eval_instances", return_value=instances),
            patch("revolver.core.benchmark.get_run", return_value=run),
            patch("revolver.core.benchmark.insert_benchmark"),
            patch("revolver.core.benchmark.insert_benchmark_solutions"),
            caplog.at_level(logging.WARNING, logger="revolver.core.benchmark"),
        ):
            result = run_benchmark(
                solution_ids_or_aliases=["sol-good", "sol-other"],
                dataset_name="eval-bench",
                project_root=tmp_path,
            )

        assert result.instance_count == 10  # max of [10, 5]
        assert any("mismatch" in record.message.lower() for record in caplog.records)


# ── get_benchmark_results ──────────────────────────────────────────────────────


class TestGetBenchmarkResults:
    """Tests for get_benchmark_results()."""

    def _bench_row(self) -> dict[str, object]:
        return {
            "id": "bench-20260310-170000",
            "alias": None,
            "dataset_name": "eval-bench",
            "created_at": "2026-03-10T17:00:00+00:00",
        }

    def _sol_rows(self) -> list[dict[str, object]]:
        return [
            {
                "solution_id": "sol-001",
                "alias": "sol-alias-1",
                "run_id": "run-001",
                "eval_id": "eval-001",
                "instance_count": 10,
                "instances_solved": 10,
                "eval_time_s": 60.0,
                "user_aggregates": None,
            }
        ]

    @pytest.mark.unit
    def test_get_results_aggregate(self, tmp_path: Path) -> None:
        """Returns BenchmarkResult with computed aggregates."""
        instances = _make_instance_results(n=5, value=0.87)

        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_benchmark", return_value=self._bench_row()),
            patch(
                "revolver.core.benchmark.get_benchmark_solutions",
                return_value=self._sol_rows(),
            ),
            patch("revolver.core.benchmark.get_eval_instances", return_value=instances),
            patch("revolver.core.benchmark.get_run", return_value=_make_run()),
        ):
            result = get_benchmark_results(
                benchmark_id="bench-20260310-170000",
                project_root=tmp_path,
            )

        assert isinstance(result, BenchmarkResult)
        assert result.benchmark_id == "bench-20260310-170000"
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert "combined_score" in entry.metrics
        assert abs(entry.metrics["combined_score"].mean - 0.87) < 1e-6

    @pytest.mark.unit
    def test_get_results_per_instance(self, tmp_path: Path) -> None:
        """Returns BenchmarkDetailResult with comparison matrix when per_instance=True."""
        instances = [
            InstanceComparison(
                instance_id="inst-000",
                solutions={
                    "sol-alias-1": InstanceSolutionResult(
                        status="solved", metrics={"combined_score": 0.87}
                    ),
                    "sol-alias-2": InstanceSolutionResult(
                        status="solved", metrics={"combined_score": 0.75}
                    ),
                },
            )
        ]
        wins = {"sol-alias-1": 1, "sol-alias-2": 0}

        sol_rows: list[dict[str, object]] = [
            {
                "solution_id": "sol-001",
                "alias": "sol-alias-1",
                "run_id": "run-001",
                "eval_id": "eval-001",
                "instance_count": 10,
                "instances_solved": 10,
                "eval_time_s": 60.0,
                "user_aggregates": None,
            },
            {
                "solution_id": "sol-002",
                "alias": "sol-alias-2",
                "run_id": "run-002",
                "eval_id": "eval-002",
                "instance_count": 10,
                "instances_solved": 10,
                "eval_time_s": 55.0,
                "user_aggregates": None,
            },
        ]

        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_benchmark", return_value=self._bench_row()),
            patch("revolver.core.benchmark.get_benchmark_solutions", return_value=sol_rows),
            patch(
                "revolver.core.benchmark._build_comparison_matrix",
                return_value=(instances, wins),
            ),
        ):
            result = get_benchmark_results(
                benchmark_id="bench-20260310-170000",
                per_instance=True,
                project_root=tmp_path,
            )

        assert isinstance(result, BenchmarkDetailResult)
        assert result.wins == {"sol-alias-1": 1, "sol-alias-2": 0}
        assert len(result.instances) == 1

    @pytest.mark.unit
    def test_benchmark_not_found_raises(self, tmp_path: Path) -> None:
        """Raises BenchmarkNotFoundError when benchmark doesn't exist."""
        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_benchmark", return_value=None),
            pytest.raises(BenchmarkNotFoundError),
        ):
            get_benchmark_results(
                benchmark_id="nonexistent",
                project_root=tmp_path,
            )

    @pytest.mark.unit
    def test_latest_flag(self, tmp_path: Path) -> None:
        """latest=True uses get_latest_benchmark."""
        instances = _make_instance_results(n=2, value=0.75)

        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch(
                "revolver.core.benchmark.get_latest_benchmark",
                return_value=self._bench_row(),
            ) as mock_latest,
            patch(
                "revolver.core.benchmark.get_benchmark_solutions",
                return_value=self._sol_rows(),
            ),
            patch("revolver.core.benchmark.get_eval_instances", return_value=instances),
            patch("revolver.core.benchmark.get_run", return_value=_make_run()),
        ):
            result = get_benchmark_results(latest=True, project_root=tmp_path)

        mock_latest.assert_called_once()
        assert isinstance(result, BenchmarkResult)

    @pytest.mark.unit
    def test_no_id_no_latest_raises(self, tmp_path: Path) -> None:
        """Raises BenchmarkNotFoundError when neither benchmark_id nor latest is provided."""
        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_benchmark", return_value=None),
            patch("revolver.core.benchmark.get_latest_benchmark", return_value=None),
            pytest.raises(BenchmarkNotFoundError) as exc_info,
        ):
            get_benchmark_results(project_root=tmp_path)

        assert "No benchmark found" in str(exc_info.value)


# ── _build_comparison_matrix ──────────────────────────────────────────────────


class TestBuildComparisonMatrix:
    """Tests for _build_comparison_matrix()."""

    def _make_raw_instances(
        self,
        sol_id: str,
        metric_val: float,
        n: int = 3,
    ) -> list[InstanceResult]:
        return [
            InstanceResult(
                instance_id=f"inst-{i:03d}",
                status="solved",
                metrics={"combined_score": metric_val},
                compute_time_s=1.0,
            )
            for i in range(n)
        ]

    @pytest.mark.unit
    def test_win_counting(self, tmp_path: Path) -> None:
        """The solution with higher combined_score wins each instance."""
        sol_rows: list[dict[str, object]] = [
            {
                "solution_id": "sol-001",
                "alias": "high-sol",
                "eval_id": "eval-001",
            },
            {
                "solution_id": "sol-002",
                "alias": "low-sol",
                "eval_id": "eval-002",
            },
        ]

        def _fake_get_instances(conn: object, eval_id: str) -> list[InstanceResult]:
            if eval_id == "eval-001":
                return self._make_raw_instances("sol-001", 0.9, n=3)
            return self._make_raw_instances("sol-002", 0.5, n=3)

        with (
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_benchmark_solutions", return_value=sol_rows),
            patch("revolver.core.benchmark.get_eval_instances", side_effect=_fake_get_instances),
        ):
            _instances, wins = _build_comparison_matrix(
                "bench-001", "eval-bench", None, None, tmp_path
            )

        assert wins["high-sol"] == 3  # wins all 3 instances
        assert wins["low-sol"] == 0

    @pytest.mark.unit
    def test_tie_breaking_both_win(self, tmp_path: Path) -> None:
        """Tied instances are counted as wins for both solutions (FR-BEN-015)."""
        sol_rows: list[dict[str, object]] = [
            {"solution_id": "sol-a", "alias": "sol-a", "eval_id": "eval-a"},
            {"solution_id": "sol-b", "alias": "sol-b", "eval_id": "eval-b"},
        ]

        def _fake_get_instances(conn: object, eval_id: str) -> list[InstanceResult]:
            # Both solutions get the same score on all instances
            return [
                InstanceResult(
                    instance_id="inst-000",
                    status="solved",
                    metrics={"combined_score": 0.80},
                    compute_time_s=1.0,
                )
            ]

        with (
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_benchmark_solutions", return_value=sol_rows),
            patch("revolver.core.benchmark.get_eval_instances", side_effect=_fake_get_instances),
        ):
            _instances2, wins = _build_comparison_matrix(
                "bench-001", "eval-bench", None, None, tmp_path
            )

        # Both should win the tied instance
        assert wins["sol-a"] == 1
        assert wins["sol-b"] == 1

    @pytest.mark.unit
    def test_failed_instances_not_counted(self, tmp_path: Path) -> None:
        """Failed/timeout instances are not counted in wins."""
        sol_rows: list[dict[str, object]] = [
            {"solution_id": "sol-a", "alias": "sol-a", "eval_id": "eval-a"},
            {"solution_id": "sol-b", "alias": "sol-b", "eval_id": "eval-b"},
        ]

        def _fake_get_instances(conn: object, eval_id: str) -> list[InstanceResult]:
            if eval_id == "eval-a":
                return [
                    InstanceResult(
                        instance_id="inst-000",
                        status="solved",
                        metrics={"combined_score": 0.9},
                        compute_time_s=1.0,
                    )
                ]
            # sol-b failed on this instance
            return [
                InstanceResult(
                    instance_id="inst-000",
                    status="failed",
                    metrics={},
                    compute_time_s=0.5,
                )
            ]

        with (
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.get_benchmark_solutions", return_value=sol_rows),
            patch("revolver.core.benchmark.get_eval_instances", side_effect=_fake_get_instances),
        ):
            _instances3, wins = _build_comparison_matrix(
                "bench-001", "eval-bench", None, None, tmp_path
            )

        assert wins["sol-a"] == 1
        assert wins["sol-b"] == 0


# ── export_benchmark ──────────────────────────────────────────────────────────


class TestExportBenchmark:
    """Tests for export_benchmark()."""

    @pytest.mark.unit
    def test_export_csv_schema(self, tmp_path: Path) -> None:
        """CSV aggregate export has the correct column headers (ConOps §8.1)."""
        bench_result = _make_benchmark_result()
        output = tmp_path / "results.csv"

        with patch(
            "revolver.core.benchmark.get_benchmark_results",
            return_value=bench_result,
        ):
            path = export_benchmark(
                benchmark_id="bench-001",
                output_format="csv",
                output_path=output,
                per_instance=False,
                project_root=tmp_path,
            )

        assert path == output
        assert output.exists()

        with output.open() as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames is not None
            headers = set(reader.fieldnames)

        expected_headers = {
            "benchmark_id",
            "solution_id",
            "solution_alias",
            "run_id",
            "problem_version",
            "llm",
            "llm_model",
            "train_dataset",
            "eval_dataset",
            "metric_name",
            "mean",
            "min",
            "max",
            "p10",
            "p50",
            "p90",
            "std",
            "gen_time_s",
            "eval_time_s",
            "instances_count",
            "instances_solved",
        }
        assert expected_headers == headers

    @pytest.mark.unit
    def test_export_json_schema(self, tmp_path: Path) -> None:
        """JSON aggregate export has the expected top-level structure (ConOps §8.2)."""
        bench_result = _make_benchmark_result()
        output = tmp_path / "results.json"

        with patch(
            "revolver.core.benchmark.get_benchmark_results",
            return_value=bench_result,
        ):
            path = export_benchmark(
                benchmark_id="bench-001",
                output_format="json",
                output_path=output,
                per_instance=False,
                project_root=tmp_path,
            )

        assert path == output
        data = json.loads(output.read_text())

        assert "benchmark_id" in data
        assert "eval_dataset" in data
        assert "instance_count" in data
        assert "created_at" in data
        assert "results" in data
        assert isinstance(data["results"], list)
        assert len(data["results"]) == 1

        entry_data = data["results"][0]
        assert "solution_id" in entry_data
        assert "lineage" in entry_data
        assert "metrics" in entry_data

        # Lineage fields
        lineage = entry_data["lineage"]
        assert "problem_version" in lineage
        assert "llm" in lineage
        assert "llm_model" in lineage
        assert "train_dataset" in lineage
        assert "iterations" in lineage
        assert "generation_time_s" in lineage

    @pytest.mark.unit
    def test_no_secrets_in_csv_export(self, tmp_path: Path) -> None:
        """CSV export contains no file system paths or API keys (FR-BEN-013)."""
        output = tmp_path / "results.csv"

        # Build entry with symbolic names only (no paths)
        secret_lineage = SolutionLineage(
            problem_version="v1.1",
            llm="claude-opus",
            llm_model="claude-opus-4-6",
            train_dataset="train-small",
            iterations=200,
            generation_time_s=8100.0,
        )
        # BenchmarkEntry with symbolic names only
        agg = MetricAggregate(
            mean=0.87,
            min=0.62,
            max=0.95,
            p10=0.71,
            p50=0.87,
            p90=0.93,
            std=0.08,
            count=10,
        )
        entry = BenchmarkEntry(
            solution_id="sol-001",
            alias=None,
            run_id="run-001",
            lineage=secret_lineage,
            metrics={"combined_score": agg},
            eval_time_s=60.0,
            instances_count=10,
            instances_solved=10,
        )
        result_with_entry = _make_benchmark_result(entries=[entry])

        with patch(
            "revolver.core.benchmark.get_benchmark_results",
            return_value=result_with_entry,
        ):
            export_benchmark(
                benchmark_id="bench-001",
                output_format="csv",
                output_path=output,
                project_root=tmp_path,
            )

        csv_text = output.read_text()

        # No absolute paths in the CSV
        assert "/home/" not in csv_text
        assert "/data/" not in csv_text
        assert ".revolver/" not in csv_text
        # API keys / env var names not present
        assert "ANTHROPIC_API_KEY" not in csv_text
        assert "sk-" not in csv_text

    @pytest.mark.unit
    def test_no_secrets_in_json_export(self, tmp_path: Path) -> None:
        """JSON export contains no file system paths or API keys (FR-BEN-013)."""
        bench_result = _make_benchmark_result()
        output = tmp_path / "results.json"

        with patch(
            "revolver.core.benchmark.get_benchmark_results",
            return_value=bench_result,
        ):
            export_benchmark(
                benchmark_id="bench-001",
                output_format="json",
                output_path=output,
                project_root=tmp_path,
            )

        json_text = output.read_text()

        assert "/home/" not in json_text
        assert "/data/" not in json_text
        assert ".revolver/" not in json_text
        assert "ANTHROPIC_API_KEY" not in json_text

    @pytest.mark.unit
    def test_invalid_format_raises_export_error(self, tmp_path: Path) -> None:
        """An invalid format raises ExportError."""
        with pytest.raises(ExportError):
            export_benchmark(
                benchmark_id="bench-001",
                output_format="parquet",
                output_path=tmp_path / "out.parquet",
                project_root=tmp_path,
            )

    @pytest.mark.unit
    def test_export_per_instance_csv_schema(self, tmp_path: Path) -> None:
        """Per-instance CSV export has the correct column headers."""
        detail_result = BenchmarkDetailResult(
            benchmark_id="bench-001",
            alias=None,
            dataset_name="eval-bench",
            instance_count=2,
            solution_ids=["sol-a", "sol-b"],
            instances=[
                InstanceComparison(
                    instance_id="inst-000",
                    solutions={
                        "sol-a": InstanceSolutionResult(
                            status="solved",
                            metrics={"combined_score": 0.9},
                            compute_time_s=1.0,
                        ),
                        "sol-b": InstanceSolutionResult(
                            status="failed",
                            metrics={},
                        ),
                    },
                )
            ],
            wins={"sol-a": 1, "sol-b": 0},
            metric="combined_score",
        )
        output = tmp_path / "per-instance.csv"

        with patch(
            "revolver.core.benchmark.get_benchmark_results",
            return_value=detail_result,
        ):
            export_benchmark(
                benchmark_id="bench-001",
                output_format="csv",
                output_path=output,
                per_instance=True,
                project_root=tmp_path,
            )

        with output.open() as fh:
            reader = csv.DictReader(fh)
            headers = set(reader.fieldnames or [])

        expected = {
            "benchmark_id",
            "solution_id",
            "solution_alias",
            "instance_id",
            "metric_name",
            "value",
            "status",
            "compute_time_s",
        }
        assert expected == headers


# ── list_benchmarks ───────────────────────────────────────────────────────────


class TestListBenchmarks:
    """Tests for list_benchmarks()."""

    @pytest.mark.unit
    def test_returns_benchmark_summary_list(self, tmp_path: Path) -> None:
        """Returns a list of BenchmarkSummary objects from the DB."""
        db_rows: list[dict[str, object]] = [
            {
                "id": "bench-20260310-170000",
                "alias": "baseline",
                "dataset_name": "eval-bench",
                "solution_count": 3,
                "created_at": "2026-03-10T17:00:00+00:00",
            },
            {
                "id": "bench-20260311-100000",
                "alias": None,
                "dataset_name": "eval-bench-2",
                "solution_count": 2,
                "created_at": "2026-03-11T10:00:00+00:00",
            },
        ]

        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.list_benchmarks_with_count", return_value=db_rows),
        ):
            result = list_benchmarks(project_root=tmp_path)

        assert len(result) == 2
        assert all(isinstance(s, BenchmarkSummary) for s in result)
        assert result[0].benchmark_id == "bench-20260310-170000"
        assert result[0].alias == "baseline"
        assert result[0].solution_count == 3
        assert result[1].alias is None
        assert result[1].solution_count == 2

    @pytest.mark.unit
    def test_returns_empty_list_when_no_benchmarks(self, tmp_path: Path) -> None:
        """Returns an empty list when no benchmarks exist."""
        with (
            patch("revolver.core.benchmark.find_project_root", return_value=tmp_path),
            patch("revolver.core.benchmark.get_project_db", return_value=MagicMock()),
            patch("revolver.core.benchmark.list_benchmarks_with_count", return_value=[]),
        ):
            result = list_benchmarks(project_root=tmp_path)

        assert result == []
