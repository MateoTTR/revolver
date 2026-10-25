"""L1 unit tests for ``core.eval`` (``evaluate_solution``, ``compute_aggregates``).

Covers the MUST requirements of the evaluation loop that the
traceability matrix carried as Planned until Sprint 020 (#297):

- FR-EVL-001: every instance of the dataset is evaluated;
- FR-EVL-003: the evaluator is taken from the problem-version snapshot, never
  from the mutable working copy;
- FR-EVL-004: the full ``dict[str, float]`` return value and the wall-clock
  time are stored per instance;
- FR-EVL-006: aggregates (mean, min, max, p10, p50, p90, std) are computed at
  read time from the stored raw rows and are never persisted.

``evaluator_runner.run_instance`` is patched at the ``core.eval`` boundary:
no subprocess is spawned.

Traceable to: DES-006 § 1 (evaluator resolution), § 4 (collect), § 5 (aggregate).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import json
from pathlib import Path
import statistics
from unittest.mock import patch

import pytest

import revolver.core.eval as core_eval
from revolver.core.eval import compute_aggregates, evaluate_solution, get_eval_results
from revolver.core.project import init_project
from revolver.infra.db import (
    get_eval_instances,
    get_project_db,
    insert_dataset,
    insert_dataset_compat,
    insert_dataset_instances,
    insert_problem_version,
    insert_run,
    insert_solution,
)
from revolver.infra.store import PROBLEM_DIR, REVOLVER_DIR, RUNS_DIR
from revolver.models.dataset import DatasetInstance, DatasetRegistration
from revolver.models.eval import EvalResult, InstanceResult
from revolver.models.problem import InstanceTestResult, ProblemVersion

pytestmark = [pytest.mark.unit]

_SNAPSHOT_EVALUATOR = (
    "def evaluate_instance(program_path, instance_path):\n    return {'combined_score': 1.0}\n"
)
_WORKING_COPY_EVALUATOR = (
    "def evaluate_instance(program_path, instance_path):\n"
    "    raise RuntimeError('the working copy must never be called')\n"
)
_INSTANCE_IDS = ["instance_001.json", "instance_002.json", "instance_003.json"]


def _setup_project(tmp_path: Path) -> dict[str, Path]:
    """Project with a v1.0 snapshot, a diverging working-copy evaluator, a
    3-instance eval dataset, a completed run and its rank-1 solution ``best``."""
    init_project(tmp_path, "eval-unit")
    now = datetime.now(UTC)

    snapshot_dir = tmp_path / REVOLVER_DIR / PROBLEM_DIR / "v1.0"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "evaluator.py").write_text(_SNAPSHOT_EVALUATOR)
    (tmp_path / "evaluator.py").write_text(_WORKING_COPY_EVALUATOR)

    data_dir = tmp_path / "data" / "eval"
    data_dir.mkdir(parents=True)
    for i, instance_id in enumerate(_INSTANCE_IDS, start=1):
        (data_dir / instance_id).write_text(json.dumps({"id": i}))

    conn = get_project_db(tmp_path / REVOLVER_DIR / "revolver.db")
    try:
        insert_problem_version(
            conn,
            ProblemVersion(tag="v1.0", hash="sha256:v1", message="v1", created_at=now),
        )
        insert_dataset(
            conn,
            DatasetRegistration(
                name="eval-bench",
                path=str(data_dir),
                split="eval",
                storage="reference",
                instance_count=3,
                global_hash="sha256:ds",
                created_at=now,
            ),
        )
        insert_dataset_instances(
            conn,
            "eval-bench",
            [
                DatasetInstance(
                    filename=instance_id,
                    relative_path=instance_id,
                    hash=f"sha256:i{i}",
                    size_bytes=10,
                )
                for i, instance_id in enumerate(_INSTANCE_IDS, start=1)
            ],
        )
        insert_dataset_compat(conn, "eval-bench", "v1.0")
        insert_run(
            conn,
            run_id="run-eval-unit",
            problem_version="v1.0",
            llm="test-llm",
            dataset="eval-bench",
            iterations=5,
            problem_hash="sha256:v1",
            dataset_hash="sha256:ds",
            llm_model="test-model",
            created_at=now,
            status="completed",
        )
        insert_solution(
            conn,
            solution_id="sol-eval-unit",
            run_id="run-eval-unit",
            rank=1,
            best_score=0.9,
            alias="best",
        )
    finally:
        conn.close()

    programs_dir = tmp_path / REVOLVER_DIR / RUNS_DIR / "run-eval-unit" / "programs"
    programs_dir.mkdir(parents=True)
    (programs_dir / "rank-1.py").write_text("print('solution')\n")

    return {
        "root": tmp_path,
        "snapshot_evaluator": snapshot_dir / "evaluator.py",
        "working_copy_evaluator": tmp_path / "evaluator.py",
    }


def _passing(metrics: dict[str, float], time_s: float) -> Callable[..., InstanceTestResult]:
    """A ``run_instance`` stand-in that passes every instance with ``metrics``."""

    def _run_instance(
        evaluator_path: Path,
        program_path: Path,
        instance_path: Path,
        timeout_s: float = 300.0,
    ) -> InstanceTestResult:
        return InstanceTestResult(
            instance_id=instance_path.name,
            status="pass",
            metrics=dict(metrics),
            time_s=time_s,
        )

    return _run_instance


# ── FR-EVL-001 ───────────────────────────────────────────────────────────────


def test_iterates_all_instances(tmp_path: Path) -> None:
    """Every top-level entry of the evaluation dataset is evaluated exactly once."""
    paths = _setup_project(tmp_path)

    with patch.object(
        core_eval, "run_instance", side_effect=_passing({"combined_score": 1.0}, 0.01)
    ) as mock_run:
        result = evaluate_solution("best", "eval-bench", project_root=paths["root"])

    evaluated = sorted(call.kwargs["instance_path"].name for call in mock_run.call_args_list)
    assert evaluated == _INSTANCE_IDS
    assert result.metadata.instance_count == 3
    assert result.metadata.instances_solved == 3


# ── FR-EVL-003 ───────────────────────────────────────────────────────────────


def test_uses_version_evaluator_not_working_copy(tmp_path: Path) -> None:
    """Every instance is evaluated with the snapshot evaluator of the solution's
    problem version, never with the working copy at the project root."""
    paths = _setup_project(tmp_path)

    with patch.object(
        core_eval, "run_instance", side_effect=_passing({"combined_score": 1.0}, 0.01)
    ) as mock_run:
        evaluate_solution("best", "eval-bench", project_root=paths["root"])

    assert mock_run.call_count == 3
    for call in mock_run.call_args_list:
        assert call.kwargs["evaluator_path"] == paths["snapshot_evaluator"]
        assert call.kwargs["evaluator_path"] != paths["working_copy_evaluator"]


# ── FR-EVL-004 ───────────────────────────────────────────────────────────────


def test_collects_metrics_and_time(tmp_path: Path) -> None:
    """The full metrics dict and the per-instance compute time are stored, and
    the evaluation wall-clock time is recorded on the metadata."""
    paths = _setup_project(tmp_path)
    metrics = {"combined_score": 0.5, "makespan": 120.0}

    with patch.object(core_eval, "run_instance", side_effect=_passing(metrics, 0.25)):
        result = evaluate_solution("best", "eval-bench", project_root=paths["root"])

    conn = get_project_db(paths["root"] / REVOLVER_DIR / "revolver.db")
    try:
        rows = get_eval_instances(conn, result.metadata.eval_id)
    finally:
        conn.close()

    assert sorted(r.instance_id for r in rows) == _INSTANCE_IDS
    for row in rows:
        assert row.status == "solved"
        assert row.metrics == metrics
        assert row.compute_time_s == pytest.approx(0.25)
    assert result.metadata.eval_time_s is not None
    assert result.metadata.eval_time_s >= 0.0
    assert result.compute_time is not None
    assert result.compute_time.total_s == pytest.approx(0.75)


# ── FR-EVL-006 ───────────────────────────────────────────────────────────────


def test_compute_aggregates_statistics() -> None:
    """mean, min, max, p10, p50, p90 (linear interpolation) and sample std over
    the solved instances only; a single value has std 0.0; no solved -> {}."""
    solved = [
        InstanceResult(
            instance_id=f"i{v}", status="solved", metrics={"score": float(v)}, compute_time_s=0.1
        )
        for v in (1, 2, 3, 4, 5)
    ]
    failed = InstanceResult(
        instance_id="bad", status="failed", metrics={}, error="boom", compute_time_s=0.1
    )

    agg = compute_aggregates([*solved, failed])

    assert set(agg) == {"score"}
    score = agg["score"]
    assert score.count == 5
    assert score.mean == pytest.approx(3.0)
    assert score.min == pytest.approx(1.0)
    assert score.max == pytest.approx(5.0)
    assert score.p10 == pytest.approx(1.4)
    assert score.p50 == pytest.approx(3.0)
    assert score.p90 == pytest.approx(4.6)
    assert score.std == pytest.approx(statistics.stdev([1.0, 2.0, 3.0, 4.0, 5.0]))

    single = compute_aggregates([solved[0]])["score"]
    assert single.std == 0.0
    assert single.p10 == single.p50 == single.p90 == pytest.approx(1.0)

    assert compute_aggregates([failed]) == {}


def test_aggregates_computed_at_read_time_not_stored(tmp_path: Path) -> None:
    """No aggregate column exists in the eval tables, and a read after a raw-row
    change returns aggregates recomputed from the stored raw data."""
    paths = _setup_project(tmp_path)

    with patch.object(
        core_eval, "run_instance", side_effect=_passing({"combined_score": 0.5}, 0.01)
    ):
        result = evaluate_solution("best", "eval-bench", project_root=paths["root"])
    assert result.aggregates["combined_score"].max == pytest.approx(0.5)

    conn = get_project_db(paths["root"] / REVOLVER_DIR / "revolver.db")
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(eval_metadata)")}
        columns |= {row[1] for row in conn.execute("PRAGMA table_info(eval_instances)")}
        assert not columns & {"mean", "min", "max", "p10", "p50", "p90", "std"}

        conn.execute(
            "UPDATE eval_instances SET value = 10.0 "
            "WHERE eval_id = ? AND instance_id = ? AND metric_name = ?",
            (result.metadata.eval_id, "instance_003.json", "combined_score"),
        )
        conn.commit()
    finally:
        conn.close()

    reread = get_eval_results("best", "eval-bench", project_root=paths["root"])

    assert isinstance(reread, EvalResult)
    score = reread.aggregates["combined_score"]
    assert score.max == pytest.approx(10.0)
    assert score.mean == pytest.approx((0.5 + 0.5 + 10.0) / 3)
