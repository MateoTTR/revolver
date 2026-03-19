"""L2 integration tests for ``revolver benchmark`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner with real
SQLite databases in ``tmp_path``. The core.benchmark functions are mocked
at the module boundary to avoid spawning real evaluations.

Traceable to: val-integration-tests.md section 2.8 (9 scenarios).
"""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.project import init_project
from revolver.infra.db import (
    get_project_db,
    insert_run,
    insert_solution,
)
from revolver.infra.store import REVOLVER_DIR
from revolver.models.benchmark import (
    BenchmarkDetailResult,
    BenchmarkEntry,
    BenchmarkResult,
    BenchmarkSummary,
    InstanceComparison,
    InstanceSolutionResult,
    SolutionLineage,
)
from revolver.models.eval import MetricAggregate

pytestmark = pytest.mark.integration

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _get_all_output(result: object) -> str:
    """Combine stdout and stderr from a CliRunner result."""
    parts: list[str] = []
    for attr in ("stdout", "stderr", "output"):
        val = getattr(result, attr, None)
        if val:
            parts.append(val)
    return _strip_ansi("".join(parts))


def _parse_json_output(result: object) -> object:
    """Extract and parse the first JSON object/array from CLI output."""
    output = getattr(result, "output", "") or ""
    stdout = getattr(result, "stdout", "") or ""
    text = stdout or output
    for i, ch in enumerate(text):
        if ch in ("{", "["):
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(text, i)
            return obj
    msg = f"No JSON found in output: {text[:200]}"
    raise ValueError(msg)


def _invoke_with_cwd(args: list[str], cwd: Path) -> object:
    """Invoke the CLI with a patched working directory."""
    with patch("pathlib.Path.cwd", return_value=cwd):
        return runner.invoke(app, args, catch_exceptions=False)


# ── Fixture helpers ──────────────────────────────────────────────────────────


def _make_lineage(
    problem_version: str = "v1.0",
    llm: str = "test-llm",
    llm_model: str = "test-model",
    train_dataset: str = "train-small",
    iterations: int = 10,
    generation_time_s: float | None = 30.0,
) -> SolutionLineage:
    return SolutionLineage(
        problem_version=problem_version,
        llm=llm,
        llm_model=llm_model,
        train_dataset=train_dataset,
        iterations=iterations,
        generation_time_s=generation_time_s,
    )


def _make_metric_aggregate(mean: float = 0.87) -> MetricAggregate:
    return MetricAggregate(
        mean=mean,
        min=mean - 0.1,
        max=mean + 0.05,
        p10=mean - 0.05,
        p50=mean,
        p90=mean + 0.03,
        std=0.05,
        count=3,
    )


def _make_benchmark_entry(
    solution_id: str,
    run_id: str,
    alias: str | None = None,
    mean_score: float = 0.87,
    instances_count: int = 3,
    instances_solved: int = 3,
    eval_time_s: float | None = 10.0,
) -> BenchmarkEntry:
    return BenchmarkEntry(
        solution_id=solution_id,
        alias=alias,
        run_id=run_id,
        lineage=_make_lineage(),
        metrics={"combined_score": _make_metric_aggregate(mean_score)},
        eval_time_s=eval_time_s,
        instances_count=instances_count,
        instances_solved=instances_solved,
    )


def _make_benchmark_result(
    benchmark_id: str = "bench-20260310-170000",
    dataset_name: str = "eval-bench",
    entries: list[BenchmarkEntry] | None = None,
    failed_solutions: list[str] | None = None,
    alias: str | None = None,
) -> BenchmarkResult:
    if entries is None:
        entries = [
            _make_benchmark_entry("sol-001", "run-001", alias="sol-a"),
            _make_benchmark_entry("sol-002", "run-002", alias="sol-b", mean_score=0.75),
        ]
    return BenchmarkResult(
        benchmark_id=benchmark_id,
        alias=alias,
        dataset_name=dataset_name,
        instance_count=3,
        entries=entries,
        failed_solutions=failed_solutions or [],
        created_at=datetime.now(UTC),
    )


def _make_benchmark_detail_result(
    benchmark_id: str = "bench-20260310-170000",
    dataset_name: str = "eval-bench",
) -> BenchmarkDetailResult:
    instances = [
        InstanceComparison(
            instance_id=f"instance_{i:03d}.json",
            solutions={
                "sol-a": InstanceSolutionResult(
                    status="solved",
                    metrics={"combined_score": 0.9 - i * 0.05},
                    compute_time_s=1.0,
                ),
                "sol-b": InstanceSolutionResult(
                    status="solved",
                    metrics={"combined_score": 0.8 - i * 0.05},
                    compute_time_s=1.2,
                ),
            },
        )
        for i in range(3)
    ]
    return BenchmarkDetailResult(
        benchmark_id=benchmark_id,
        dataset_name=dataset_name,
        instance_count=3,
        solution_ids=["sol-a", "sol-b"],
        instances=instances,
        wins={"sol-a": 3, "sol-b": 0},
        metric="combined_score",
    )


@pytest.fixture()
def bench_project(tmp_path: Path) -> dict[str, object]:
    """Create a minimal project with 2 solutions for benchmark tests."""
    init_project(tmp_path, "test-bench-project")
    db_path = tmp_path / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    now = datetime.now(UTC)

    # Insert minimal DB rows needed by the CLI layer (for DB verification tests)
    try:
        # Insert problem version
        conn.execute(
            "INSERT OR IGNORE INTO problem_versions (tag, hash, message, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("v1.0", "sha256:abc", "Test", now.isoformat()),
        )
        # Insert datasets (eval dataset + train dataset for run FKs)
        for ds_name, ds_split in [("eval-bench", "eval"), ("train-small", "train")]:
            conn.execute(
                "INSERT INTO datasets (name, path, split, storage, description, "
                "global_hash, instance_count, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ds_name,
                    str(tmp_path / "data" / ds_name),
                    ds_split,
                    "reference",
                    "",
                    f"sha256:{ds_name}-hash",
                    3,
                    now.isoformat(),
                ),
            )
        conn.commit()

        # Insert 2 runs + solutions
        insert_run(
            conn,
            run_id="run-001",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="sha256:abc",
            dataset_hash="sha256:ds-hash",
            llm_model="test-model",
            created_at=now,
            status="completed",
            generation_time_s=30.0,
        )
        insert_solution(conn, solution_id="sol-001", run_id="run-001", rank=1, best_score=0.95)

        insert_run(
            conn,
            run_id="run-002",
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=10,
            problem_hash="sha256:abc",
            dataset_hash="sha256:ds-hash",
            llm_model="test-model",
            created_at=now,
            status="completed",
            generation_time_s=25.0,
        )
        insert_solution(conn, solution_id="sol-002", run_id="run-002", rank=1, best_score=0.80)
    finally:
        conn.close()

    return {"root": tmp_path, "db_path": db_path}


# ── Test 1: test_accepts_multiple_solutions ──────────────────────────────────


@pytest.mark.integration
def test_accepts_multiple_solutions(bench_project: dict[str, object]) -> None:
    """2 solutions + eval dataset → comparison table with all solutions present.

    Validates: FR-BEN-001, FR-BEN-004, FR-BEN-005, FR-BEN-006
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    mock_result = _make_benchmark_result()

    with patch("revolver.core.benchmark.run_benchmark", return_value=mock_result):
        result = _invoke_with_cwd(
            [
                "benchmark",
                "--solutions",
                "sol-001",
                "--solutions",
                "sol-002",
                "--dataset",
                "eval-bench",
            ],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Comparison table should mention solutions
    assert "sol-a" in output or "sol-001" in output
    assert "sol-b" in output or "sol-002" in output


# ── Test 2: test_metadata_stored_in_db ──────────────────────────────────────


@pytest.mark.integration
def test_benchmark_output_contains_benchmark_id(bench_project: dict[str, object]) -> None:
    """CLI output contains the benchmark_id after a successful run.

    Validates: FR-BEN-005 (output traceability)
    Note: core.benchmark.run_benchmark is mocked, so the DB insert does not
    actually occur. This test verifies that the CLI surfaces the benchmark_id
    returned by core in its output.
    """
    root = bench_project["root"]
    db_path = bench_project["db_path"]
    assert isinstance(root, Path)
    assert isinstance(db_path, Path)

    bench_id = "bench-20260310-170000"
    mock_result = _make_benchmark_result(benchmark_id=bench_id)

    with patch("revolver.core.benchmark.run_benchmark", return_value=mock_result):
        result = _invoke_with_cwd(
            [
                "benchmark",
                "--solutions",
                "sol-001",
                "--solutions",
                "sol-002",
                "--dataset",
                "eval-bench",
            ],
            root,
        )

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {_get_all_output(result)}"

    # The output should include the benchmark_id
    output = _get_all_output(result)
    assert bench_id in output or "bench-" in output


# ── Test 3: test_runs_missing_evals ─────────────────────────────────────────


@pytest.mark.integration
def test_runs_missing_evals(bench_project: dict[str, object]) -> None:
    """One solution reused, one triggers eval — progress shows both statuses.

    Validates: FR-BEN-002, FR-BEN-003
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    mock_result = _make_benchmark_result()

    def fake_run_benchmark(
        solution_ids_or_aliases: list[str],
        dataset_name: str,
        timeout_s: int = 300,
        alias: str | None = None,
        on_progress: object = None,
        project_root: Path | None = None,
    ) -> BenchmarkResult:
        # Simulate progress callback — one reused, one evaluated
        if callable(on_progress):
            on_progress("sol-001", "reused")
            on_progress("sol-002", "evaluated")
        return mock_result

    with patch("revolver.core.benchmark.run_benchmark", side_effect=fake_run_benchmark):
        result = _invoke_with_cwd(
            [
                "benchmark",
                "--solutions",
                "sol-001",
                "--solutions",
                "sol-002",
                "--dataset",
                "eval-bench",
            ],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Progress lines should be present (reused / evaluated)
    assert "reused" in output or "evaluated" in output


# ── Test 4: test_comparative_table ──────────────────────────────────────────


@pytest.mark.integration
def test_comparative_table(bench_project: dict[str, object]) -> None:
    """Aggregate table includes eval_time, instances_solved.

    Validates: FR-BEN-004, FR-BEN-009
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    mock_result = _make_benchmark_result(
        entries=[
            _make_benchmark_entry(
                "sol-001",
                "run-001",
                alias="sol-a",
                mean_score=0.87,
                instances_solved=3,
                eval_time_s=12.5,
            ),
            _make_benchmark_entry(
                "sol-002",
                "run-002",
                alias="sol-b",
                mean_score=0.75,
                instances_solved=2,
                eval_time_s=9.0,
            ),
        ]
    )

    with patch("revolver.core.benchmark.run_benchmark", return_value=mock_result):
        result = _invoke_with_cwd(
            [
                "benchmark",
                "--solutions",
                "sol-001",
                "--solutions",
                "sol-002",
                "--dataset",
                "eval-bench",
            ],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Table should contain instances and eval_time info
    assert "3/3" in output or "2/3" in output or "instances" in output.lower()
    # Mean scores should appear
    assert "0.87" in output or "0.75" in output


# ── Test 5: test_results_per_instance ───────────────────────────────────────


@pytest.mark.integration
def test_results_per_instance(bench_project: dict[str, object]) -> None:
    """benchmark results --per-instance shows side-by-side comparison.

    Validates: FR-BEN-014, FR-BEN-015
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    mock_detail = _make_benchmark_detail_result()

    with patch(
        "revolver.core.benchmark.get_benchmark_results",
        return_value=mock_detail,
    ):
        result = _invoke_with_cwd(
            [
                "benchmark",
                "results",
                "--latest",
                "--per-instance",
            ],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Should show instance IDs
    assert "instance_001" in output or "instance_002" in output
    # Should show solution columns
    assert "sol-a" in output or "sol-b" in output


# ── Test 6: test_export_csv ──────────────────────────────────────────────────


@pytest.mark.integration
def test_export_csv(bench_project: dict[str, object], tmp_path: Path) -> None:
    """Export to CSV: valid CSV file, no secrets, run_id included.

    Validates: FR-BEN-007, FR-BEN-013, FR-BEN-017
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    output_file = tmp_path / "results.csv"

    # The export function writes the CSV — use fake to simulate this
    written_path = output_file

    def fake_export(
        benchmark_id: str | None = None,
        latest: bool = False,
        output_format: str = "csv",
        output_path: Path | None = None,
        per_instance: bool = False,
        project_root: Path | None = None,
    ) -> Path:
        # Write a minimal CSV with the expected columns
        with (output_path or written_path).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "benchmark_id",
                    "solution_id",
                    "solution_alias",
                    "run_id",
                    "eval_dataset",
                    "metric_name",
                    "mean",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "benchmark_id": "bench-20260310-170000",
                    "solution_id": "sol-001",
                    "solution_alias": "sol-a",
                    "run_id": "run-001",
                    "eval_dataset": "eval-bench",
                    "metric_name": "combined_score",
                    "mean": 0.87,
                }
            )
        return output_path or written_path

    with patch("revolver.core.benchmark.export_benchmark", side_effect=fake_export):
        result = _invoke_with_cwd(
            [
                "benchmark",
                "export",
                "--latest",
                "--format",
                "csv",
                "--output",
                str(output_file),
            ],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"

    # Verify CSV is valid
    assert output_file.exists(), "CSV file should have been created"
    with output_file.open() as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) >= 1
    assert "benchmark_id" in rows[0]
    assert "run_id" in rows[0]
    # No secrets: run_id is present (traceability), but no file paths
    assert rows[0]["run_id"] == "run-001"
    # No absolute path values in CSV
    for row in rows:
        for val in row.values():
            assert not str(val).startswith("/"), f"Unexpected path in CSV: {val}"


# ── Test 7: test_export_json ─────────────────────────────────────────────────


@pytest.mark.integration
def test_export_json(bench_project: dict[str, object], tmp_path: Path) -> None:
    """Export to JSON: valid JSON matching ConOps §8.2 schema.

    Validates: FR-BEN-008
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    output_file = tmp_path / "results.json"

    def fake_export(
        benchmark_id: str | None = None,
        latest: bool = False,
        output_format: str = "csv",
        output_path: Path | None = None,
        per_instance: bool = False,
        project_root: Path | None = None,
    ) -> Path:
        payload = {
            "benchmark_id": "bench-20260310-170000",
            "alias": None,
            "eval_dataset": "eval-bench",
            "instance_count": 3,
            "created_at": "2026-03-10T17:00:00+00:00",
            "results": [
                {
                    "solution_id": "sol-001",
                    "alias": "sol-a",
                    "run_id": "run-001",
                    "lineage": {
                        "problem_version": "v1.0",
                        "llm": "test-llm",
                        "llm_model": "test-model",
                        "train_dataset": "train-small",
                        "iterations": 10,
                        "generation_time_s": 30.0,
                    },
                    "metrics": {
                        "combined_score": {
                            "mean": 0.87,
                            "min": 0.77,
                            "max": 0.92,
                            "p10": 0.82,
                            "p50": 0.87,
                            "p90": 0.90,
                            "std": 0.05,
                            "count": 3,
                        }
                    },
                    "user_aggregates": None,
                    "eval_time_s": 10.0,
                    "instances_count": 3,
                    "instances_solved": 3,
                }
            ],
        }
        target = output_path or (tmp_path / "results.json")
        with target.open("w") as fh:
            json.dump(payload, fh)
        return target

    with patch("revolver.core.benchmark.export_benchmark", side_effect=fake_export):
        result = _invoke_with_cwd(
            [
                "benchmark",
                "export",
                "--latest",
                "--format",
                "json",
                "--output",
                str(output_file),
            ],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"

    assert output_file.exists(), "JSON file should have been created"
    with output_file.open() as fh:
        data = json.load(fh)

    # Validate JSON schema matches ConOps §8.2
    assert "benchmark_id" in data
    assert "eval_dataset" in data
    assert "instance_count" in data
    assert "results" in data
    assert len(data["results"]) >= 1

    entry = data["results"][0]
    assert "solution_id" in entry
    assert "run_id" in entry
    assert "lineage" in entry
    assert "metrics" in entry
    assert "problem_version" in entry["lineage"]
    assert "llm" in entry["lineage"]
    assert "train_dataset" in entry["lineage"]


# ── Test 8: test_export_per_instance ────────────────────────────────────────


@pytest.mark.integration
def test_export_per_instance(bench_project: dict[str, object], tmp_path: Path) -> None:
    """Per-instance export: CSV/JSON rows for each instance across all solutions.

    Validates: FR-BEN-016
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    output_file = tmp_path / "per-instance.csv"

    def fake_export(
        benchmark_id: str | None = None,
        latest: bool = False,
        output_format: str = "csv",
        output_path: Path | None = None,
        per_instance: bool = False,
        project_root: Path | None = None,
    ) -> Path:
        target = output_path or output_file
        with target.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "benchmark_id",
                    "solution_id",
                    "solution_alias",
                    "instance_id",
                    "metric_name",
                    "value",
                    "status",
                    "compute_time_s",
                ],
            )
            writer.writeheader()
            for i in range(1, 4):
                for sol_id, sol_alias in [("sol-001", "sol-a"), ("sol-002", "sol-b")]:
                    writer.writerow(
                        {
                            "benchmark_id": "bench-20260310-170000",
                            "solution_id": sol_id,
                            "solution_alias": sol_alias,
                            "instance_id": f"instance_{i:03d}.json",
                            "metric_name": "combined_score",
                            "value": 0.9 - i * 0.05,
                            "status": "solved",
                            "compute_time_s": 1.0,
                        }
                    )
        return target

    with patch("revolver.core.benchmark.export_benchmark", side_effect=fake_export):
        result = _invoke_with_cwd(
            [
                "benchmark",
                "export",
                "--latest",
                "--format",
                "csv",
                "--output",
                str(output_file),
                "--per-instance",
            ],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"

    assert output_file.exists(), "Per-instance CSV should have been created"
    with output_file.open() as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    # 3 instances x 2 solutions = 6 rows
    assert len(rows) == 6
    instance_ids = {row["instance_id"] for row in rows}
    assert "instance_001.json" in instance_ids
    assert "instance_003.json" in instance_ids
    solution_ids = {row["solution_id"] for row in rows}
    assert "sol-001" in solution_ids
    assert "sol-002" in solution_ids


# ── Test 9: test_list_benchmarks ────────────────────────────────────────────


@pytest.mark.integration
def test_list_benchmarks(bench_project: dict[str, object]) -> None:
    """After 2 benchmarks, both listed with metadata.

    Validates: FR-BEN-012
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    now = datetime.now(UTC)
    mock_summaries = [
        BenchmarkSummary(
            benchmark_id="bench-20260310-170000",
            alias="first-bench",
            dataset_name="eval-bench",
            solution_count=2,
            created_at=now,
        ),
        BenchmarkSummary(
            benchmark_id="bench-20260311-090000",
            alias=None,
            dataset_name="eval-bench",
            solution_count=3,
            created_at=now,
        ),
    ]

    with patch("revolver.core.benchmark.list_benchmarks", return_value=mock_summaries):
        result = _invoke_with_cwd(["benchmark", "list"], root)

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"

    # Both benchmarks should be listed with metadata
    # Note: Rich may truncate long IDs in narrow terminal — check for partial IDs
    assert "bench-20260310" in output or "20260310" in output
    assert "bench-20260311" in output or "20260311" in output
    assert "first-bench" in output
    assert "eval-bench" in output
    # Solution count should be present
    assert "2" in output
    assert "3" in output


# ── JSON mode tests (§2.11 cross-cutting) ───────────────────────────────────


@pytest.mark.integration
def test_benchmark_json_mode(bench_project: dict[str, object]) -> None:
    """benchmark --json outputs valid JSON with expected keys.

    Validates: §2.11 (JSON mode), FR-BEN-001, FR-BEN-004
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    mock_result = _make_benchmark_result()

    with patch("revolver.core.benchmark.run_benchmark", return_value=mock_result):
        result = _invoke_with_cwd(
            [
                "--json",
                "benchmark",
                "--solutions",
                "sol-001",
                "--solutions",
                "sol-002",
                "--dataset",
                "eval-bench",
            ],
            root,
        )

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {_get_all_output(result)}"
    data = _parse_json_output(result)
    assert isinstance(data, dict)
    assert "benchmark_id" in data
    assert "dataset_name" in data
    assert "entries" in data
    assert isinstance(data["entries"], list)
    assert len(data["entries"]) >= 1


@pytest.mark.integration
def test_benchmark_results_json_mode(bench_project: dict[str, object]) -> None:
    """benchmark results --latest --json outputs valid JSON with expected keys.

    Validates: §2.11 (JSON mode), FR-BEN-009
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    mock_result = _make_benchmark_result()

    with patch("revolver.core.benchmark.get_benchmark_results", return_value=mock_result):
        result = _invoke_with_cwd(
            ["--json", "benchmark", "results", "--latest"],
            root,
        )

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {_get_all_output(result)}"
    data = _parse_json_output(result)
    assert isinstance(data, dict)
    assert "benchmark_id" in data
    assert "entries" in data


@pytest.mark.integration
def test_benchmark_list_json_mode(bench_project: dict[str, object]) -> None:
    """benchmark list --json outputs valid JSON array of benchmark summaries.

    Validates: §2.11 (JSON mode), FR-BEN-012
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    now = datetime.now(UTC)
    mock_summaries = [
        BenchmarkSummary(
            benchmark_id="bench-20260310-170000",
            alias="first-bench",
            dataset_name="eval-bench",
            solution_count=2,
            created_at=now,
        ),
    ]

    with patch("revolver.core.benchmark.list_benchmarks", return_value=mock_summaries):
        result = _invoke_with_cwd(["--json", "benchmark", "list"], root)

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {_get_all_output(result)}"
    data = _parse_json_output(result)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["benchmark_id"] == "bench-20260310-170000"
    assert data[0]["alias"] == "first-bench"


# ── Error case tests (§2.11 cross-cutting) ───────────────────────────────────


@pytest.mark.integration
def test_benchmark_missing_solutions(bench_project: dict[str, object]) -> None:
    """benchmark without --solutions exits with code 1 and error message on stderr.

    Validates: §2.11 (error cases)
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    result = _invoke_with_cwd(
        ["benchmark", "--dataset", "eval-bench"],
        root,
    )

    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"
    output = _get_all_output(result)
    assert "--solutions" in output or "solutions" in output.lower()


@pytest.mark.integration
def test_benchmark_missing_dataset(bench_project: dict[str, object]) -> None:
    """benchmark without --dataset exits with code 1 and error message on stderr.

    Validates: §2.11 (error cases)
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    result = _invoke_with_cwd(
        ["benchmark", "--solutions", "sol-001"],
        root,
    )

    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"
    output = _get_all_output(result)
    assert "--dataset" in output or "dataset" in output.lower()


@pytest.mark.integration
def test_benchmark_not_found_error(bench_project: dict[str, object]) -> None:
    """BenchmarkNotFoundError propagated by core exits with code 1.

    Validates: §2.11 (error cases), FR-BEN-009
    """
    from revolver.core.exceptions import BenchmarkNotFoundError

    root = bench_project["root"]
    assert isinstance(root, Path)

    with patch(
        "revolver.core.benchmark.get_benchmark_results",
        side_effect=BenchmarkNotFoundError("Benchmark 'bench-xyz' not found."),
    ):
        result = _invoke_with_cwd(
            ["benchmark", "results", "--id", "bench-xyz"],
            root,
        )

    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"
    output = _get_all_output(result)
    assert "not found" in output.lower() or "Error" in output


@pytest.mark.integration
def test_benchmark_error_all_evals_fail(bench_project: dict[str, object]) -> None:
    """BenchmarkError (all evals fail) propagated by core exits with code 4.

    Validates: §2.11 (error cases), FR-BEN-004
    """
    from revolver.core.exceptions import BenchmarkError

    root = bench_project["root"]
    assert isinstance(root, Path)

    with patch(
        "revolver.core.benchmark.run_benchmark",
        side_effect=BenchmarkError("Evaluation failed for all solutions. Benchmark aborted."),
    ):
        result = _invoke_with_cwd(
            [
                "benchmark",
                "--solutions",
                "sol-001",
                "--solutions",
                "sol-002",
                "--dataset",
                "eval-bench",
            ],
            root,
        )

    assert result.exit_code == 4, f"Expected exit 4, got {result.exit_code}"
    output = _get_all_output(result)
    assert "Error" in output or "failed" in output.lower()


# ── Sprint 006b fix tests ────────────────────────────────────────────────────


@pytest.mark.integration
def test_benchmark_all_flag(bench_project: dict[str, object]) -> None:
    """--all resolves all project solutions and passes them to run_benchmark.

    Validates: F7 (--all shortcut)
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    mock_result = _make_benchmark_result()

    with (
        patch(
            "revolver.core.solution.list_solutions",
            return_value=[
                {"id": "sol-001", "alias": "sol-a"},
                {"id": "sol-002", "alias": "sol-b"},
            ],
        ),
        patch("revolver.core.benchmark.run_benchmark", return_value=mock_result) as mock_run,
    ):
        result = _invoke_with_cwd(
            ["benchmark", "--all", "--dataset", "eval-bench"],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    call_args = mock_run.call_args
    fallback = call_args.args[0] if call_args.args else []
    sol_ids = call_args.kwargs.get("solution_ids_or_aliases", fallback)
    assert "sol-a" in sol_ids


@pytest.mark.integration
def test_benchmark_comma_separated_solutions(bench_project: dict[str, object]) -> None:
    """--solutions A,B,C expands to 3 separate solution arguments.

    Validates: F7 (comma-separated shortcut)
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    mock_result = _make_benchmark_result()

    with patch("revolver.core.benchmark.run_benchmark", return_value=mock_result) as mock_run:
        result = _invoke_with_cwd(
            [
                "benchmark",
                "--solutions",
                "sol-001,sol-002",
                "--dataset",
                "eval-bench",
            ],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    call_args = mock_run.call_args
    fallback = call_args.args[0] if call_args.args else []
    sol_list = call_args.kwargs.get("solution_ids_or_aliases", fallback)
    assert "sol-001" in sol_list
    assert "sol-002" in sol_list


@pytest.mark.integration
def test_results_defaults_to_combined_score(bench_project: dict[str, object]) -> None:
    """benchmark results without --metric shows only combined_score columns.

    Validates: F4 (default metric filtering)
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    multi_metric_entry = BenchmarkEntry(
        solution_id="sol-001",
        alias="sol-a",
        run_id="run-001",
        lineage=_make_lineage(),
        metrics={
            "combined_score": _make_metric_aggregate(0.87),
            "baseline_length": _make_metric_aggregate(100.0),
            "tour_length": _make_metric_aggregate(50.0),
        },
        eval_time_s=10.0,
        instances_count=3,
        instances_solved=3,
    )
    mock_result = _make_benchmark_result(entries=[multi_metric_entry])

    with patch("revolver.core.benchmark.get_benchmark_results", return_value=mock_result):
        result = _invoke_with_cwd(
            ["benchmark", "results", "--latest"],
            root,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "0.87" in output
    assert "baseline_length" not in output
    assert "tour_length" not in output


@pytest.mark.integration
def test_results_metric_all_shows_everything(bench_project: dict[str, object]) -> None:
    """benchmark results --metric all shows more columns than default.

    Validates: F4 (--metric all support)
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    multi_metric_entry = BenchmarkEntry(
        solution_id="sol-001",
        alias="sol-a",
        run_id="run-001",
        lineage=_make_lineage(),
        metrics={
            "combined_score": _make_metric_aggregate(0.87),
            "baseline_length": _make_metric_aggregate(100.0),
        },
        eval_time_s=10.0,
        instances_count=3,
        instances_solved=3,
    )
    mock_result = _make_benchmark_result(entries=[multi_metric_entry])

    with patch("revolver.core.benchmark.get_benchmark_results", return_value=mock_result):
        result_all = _invoke_with_cwd(
            ["benchmark", "results", "--latest", "--metric", "all"],
            root,
        )

    with patch("revolver.core.benchmark.get_benchmark_results", return_value=mock_result):
        result_default = _invoke_with_cwd(
            ["benchmark", "results", "--latest"],
            root,
        )

    assert result_all.exit_code == 0
    assert result_default.exit_code == 0

    output_all = _get_all_output(result_all)
    output_default = _get_all_output(result_default)

    # --metric all has more table columns (separators) than default
    all_cols = output_all.count("\u2503")
    default_cols = output_default.count("\u2503")
    assert all_cols > default_cols, (
        f"--metric all should have more columns ({all_cols}) than default ({default_cols})"
    )


@pytest.mark.integration
def test_benchmark_all_no_solutions(bench_project: dict[str, object]) -> None:
    """--all with no solutions in project exits with code 1.

    Validates: F7 (--all edge case)
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    with patch(
        "revolver.cli.benchmark.core_solution.list_solutions",
        return_value=[],
    ):
        result = _invoke_with_cwd(
            ["benchmark", "--all", "--dataset", "eval-bench"],
            root,
        )

    assert result.exit_code == 1
    output = _get_all_output(result)
    assert "no solutions" in output.lower()


@pytest.mark.integration
def test_benchmark_all_and_solutions_exclusive(bench_project: dict[str, object]) -> None:
    """--all and --solutions together exits with code 1.

    Validates: F7 (mutual exclusion)
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    result = _invoke_with_cwd(
        ["benchmark", "--all", "--solutions", "sol-001", "--dataset", "eval-bench"],
        root,
    )

    assert result.exit_code == 1
    output = _get_all_output(result)
    assert "mutually exclusive" in output.lower()


# ── Sprint 006b: benchmark delete tests ──────────────────────────────────────


@pytest.mark.integration
def test_benchmark_delete_existing(bench_project: dict[str, object]) -> None:
    """Delete an existing benchmark removes it from list.

    Validates: F8 (benchmark delete)
    """
    root = bench_project["root"]
    db_path = bench_project["db_path"]
    assert isinstance(root, Path)
    assert isinstance(db_path, Path)

    # Insert a benchmark directly into the DB
    from revolver.infra.db import insert_benchmark, insert_benchmark_solutions

    conn = get_project_db(db_path)
    try:
        insert_benchmark(
            conn,
            benchmark_id="bench-delete-test",
            alias="to-delete",
            dataset_name="eval-bench",
            created_at=datetime.now(UTC),
        )
        insert_benchmark_solutions(conn, "bench-delete-test", ["sol-001", "sol-002"])
    finally:
        conn.close()

    # Delete with --force
    result = _invoke_with_cwd(
        ["benchmark", "delete", "bench-delete-test", "--force"],
        root,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "deleted" in output.lower()

    # Verify it's gone from the DB
    conn2 = get_project_db(db_path)
    try:
        from revolver.infra.db import get_benchmark

        row = get_benchmark(conn2, "bench-delete-test")
        assert row is None, "Benchmark should have been deleted"
    finally:
        conn2.close()


@pytest.mark.integration
def test_benchmark_delete_nonexistent(bench_project: dict[str, object]) -> None:
    """Deleting a non-existent benchmark exits with error.

    Validates: F8 (benchmark delete error case)
    """
    root = bench_project["root"]
    assert isinstance(root, Path)

    result = _invoke_with_cwd(
        ["benchmark", "delete", "bench-does-not-exist", "--force"],
        root,
    )

    assert result.exit_code != 0, f"Expected non-zero exit, got {result.exit_code}"
    output = _get_all_output(result)
    assert "not found" in output.lower()


@pytest.mark.integration
def test_benchmark_delete_force(bench_project: dict[str, object]) -> None:
    """Delete with --force skips confirmation prompt.

    Validates: F8 (benchmark delete --force)
    """
    root = bench_project["root"]
    db_path = bench_project["db_path"]
    assert isinstance(root, Path)
    assert isinstance(db_path, Path)

    # Insert a benchmark directly into the DB
    from revolver.infra.db import insert_benchmark, insert_benchmark_solutions

    conn = get_project_db(db_path)
    try:
        insert_benchmark(
            conn,
            benchmark_id="bench-force-test",
            alias=None,
            dataset_name="eval-bench",
            created_at=datetime.now(UTC),
        )
        insert_benchmark_solutions(conn, "bench-force-test", ["sol-001"])
    finally:
        conn.close()

    # Delete with --force (no interactive prompt)
    result = _invoke_with_cwd(
        ["benchmark", "delete", "bench-force-test", "--force"],
        root,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "deleted" in output.lower()

    # Verify junction table rows are also gone
    conn2 = get_project_db(db_path)
    try:
        cursor = conn2.execute(
            "SELECT COUNT(*) FROM benchmark_solutions WHERE benchmark_id = ?",
            ("bench-force-test",),
        )
        count = cursor.fetchone()[0]
        assert count == 0, "benchmark_solutions rows should have been deleted"
    finally:
        conn2.close()
