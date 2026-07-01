"""Tests for ``revolver run population`` command (S10-16).

L1 unit tests for ``parse_population()`` and ``get_population()``,
plus L2 integration tests for the CLI command.

Traceable to: issue #156, val-integration-tests.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.exceptions import CheckpointRecoveryError
from revolver.core.run import get_population
from revolver.infra.backends.openevolve import (
    parse_population,
    read_checkpoint_best_score,
    recover_best_from_checkpoint,
)
from revolver.infra.db import get_project_db, insert_run
from revolver.infra.store import REVOLVER_DIR, init_project_store

runner = CliRunner()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_program_json(
    prog_id: str,
    metrics: dict[str, object],
    generation: int = 1,
    iteration_found: int = 1,
    parent_id: str | None = None,
) -> str:
    """Build a minimal OE program JSON string."""
    data: dict[str, object] = {
        "id": prog_id,
        "code": "def solve(): pass",
        "metrics": metrics,
        "generation": generation,
        "parent_id": parent_id,
        "complexity": 1.0,
        "diversity": 0.5,
        "changes_description": "test change",
        "iteration_found": iteration_found,
        "timestamp": "2026-03-28T10:00:00",
    }
    return json.dumps(data)


def _create_checkpoint_with_programs(
    run_dir: Path,
    checkpoint_num: int,
    programs: list[dict[str, object]],
    metadata: dict[str, object] | None = None,
) -> Path:
    """Create a fake OE checkpoint with program JSON files.

    Args:
        run_dir: The run directory (e.g. .revolver/runs/<id>).
        checkpoint_num: Checkpoint number (e.g. 5 for checkpoint_5).
        programs: List of dicts with keys: id, metrics, generation, iteration_found.
        metadata: Optional metadata dict to write as ``metadata.json``.

    Returns:
        Path to the created checkpoint directory.
    """
    checkpoint_dir = run_dir / "oe-output" / "checkpoints" / f"checkpoint_{checkpoint_num}"
    programs_dir = checkpoint_dir / "programs"
    programs_dir.mkdir(parents=True)

    for prog in programs:
        prog_id = str(prog["id"])
        prog_json = _make_program_json(
            prog_id=prog_id,
            metrics=prog.get("metrics", {}),  # type: ignore[arg-type]
            generation=int(prog.get("generation", 1)),  # type: ignore[arg-type]
            iteration_found=int(prog.get("iteration_found", 1)),  # type: ignore[arg-type]
            parent_id=prog.get("parent_id"),  # type: ignore[arg-type]
        )
        (programs_dir / f"{prog_id}.json").write_text(prog_json, encoding="utf-8")

    if metadata is not None:
        (checkpoint_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    return checkpoint_dir


def _create_run_in_db(project_root: Path, run_id: str) -> None:
    """Insert a minimal run record into the project database.

    Also inserts the required FK references (problem_version, dataset).
    """
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        # Insert FK prerequisites (ignore if already exist)
        conn.execute(
            "INSERT OR IGNORE INTO problem_versions (tag, hash, message, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("v1.0", "abc123", "test version", datetime.now(UTC).isoformat()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO datasets "
            "(name, path, split, storage, description, global_hash, "
            "instance_count, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "train",
                "/tmp/data",
                "train",
                "reference",
                "test",
                "def456",
                1,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()

        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            problem_hash="abc123",
            llm="test-llm",
            llm_model="test-model",
            dataset="train",
            dataset_hash="def456",
            iterations=10,
            status="completed",
            config_snapshot="{}",
            created_at=datetime.now(UTC),
        )
    finally:
        conn.close()


def _setup_project_with_run(
    tmp_path: Path,
    run_id: str,
    programs: list[dict[str, object]] | None = None,
    checkpoint_num: int = 5,
    create_checkpoint: bool = True,
    metadata: dict[str, object] | None = None,
) -> Path:
    """Create a project with a run and optional checkpoint."""
    init_project_store(tmp_path)
    _create_run_in_db(tmp_path, run_id)

    run_dir = tmp_path / REVOLVER_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if create_checkpoint and programs is not None:
        _create_checkpoint_with_programs(run_dir, checkpoint_num, programs, metadata)

    return tmp_path


# ── L1: parse_population() unit tests ───────────────────────────────────────


class TestParsePopulation:
    """Unit tests for ``infra.openevolve.parse_population()``."""

    def test_empty_programs_dir(self, tmp_path: Path) -> None:
        """Returns empty list when programs/ directory exists but is empty."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        result = parse_population(tmp_path)
        assert result == []

    def test_no_programs_dir(self, tmp_path: Path) -> None:
        """Returns empty list when programs/ directory does not exist."""
        result = parse_population(tmp_path)
        assert result == []

    def test_single_program(self, tmp_path: Path) -> None:
        """Parses a single program correctly."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_json = _make_program_json(
            "prog1",
            metrics={"combined_score": 0.95, "accuracy": 0.8},
            generation=3,
            iteration_found=5,
        )
        (programs_dir / "prog1.json").write_text(prog_json, encoding="utf-8")

        result = parse_population(tmp_path)

        assert len(result) == 1
        prog = result[0]
        assert prog["id"] == "prog1"
        assert prog["score"] == pytest.approx(1.75)  # 0.95 + 0.8
        assert prog["generation"] == 3
        assert prog["iteration_found"] == 5
        assert prog["rank"] == 1
        assert prog["metrics"] == {"combined_score": 0.95, "accuracy": 0.8}
        # No metadata.json → cell_indices and island should be None
        assert prog["cell_indices"] is None
        assert prog["island"] is None

    def test_multiple_programs_sorted_by_score(self, tmp_path: Path) -> None:
        """Programs are sorted by combined score descending."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()

        for pid, score in [("a", 0.5), ("b", 0.9), ("c", 0.3)]:
            prog_json = _make_program_json(pid, metrics={"score": score})
            (programs_dir / f"{pid}.json").write_text(prog_json, encoding="utf-8")

        result = parse_population(tmp_path)

        assert len(result) == 3
        assert result[0]["id"] == "b"
        assert result[0]["rank"] == 1
        assert result[1]["id"] == "a"
        assert result[1]["rank"] == 2
        assert result[2]["id"] == "c"
        assert result[2]["rank"] == 3

    def test_program_with_no_metrics(self, tmp_path: Path) -> None:
        """Program with empty metrics gets score 0.0."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_json = _make_program_json("prog1", metrics={})
        (programs_dir / "prog1.json").write_text(prog_json, encoding="utf-8")

        result = parse_population(tmp_path)
        assert result[0]["score"] == 0.0

    def test_skips_invalid_json(self, tmp_path: Path) -> None:
        """Skips files that cannot be parsed as JSON."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        (programs_dir / "bad.json").write_text("not json", encoding="utf-8")
        prog_json = _make_program_json("good", metrics={"score": 1.0})
        (programs_dir / "good.json").write_text(prog_json, encoding="utf-8")

        result = parse_population(tmp_path)
        assert len(result) == 1
        assert result[0]["id"] == "good"

    def test_boolean_metrics_excluded_from_score(self, tmp_path: Path) -> None:
        """Boolean values in metrics are not summed into the score."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_json = _make_program_json(
            "prog1",
            metrics={"score": 0.5, "valid": True, "converged": False},
        )
        (programs_dir / "prog1.json").write_text(prog_json, encoding="utf-8")

        result = parse_population(tmp_path)
        assert result[0]["score"] == pytest.approx(0.5)

    def test_id_fallback_to_filename(self, tmp_path: Path) -> None:
        """Uses filename stem as ID when 'id' field is missing."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        data = {"metrics": {"score": 1.0}, "generation": 1, "iteration_found": 1}
        (programs_dir / "prog_x.json").write_text(json.dumps(data), encoding="utf-8")

        result = parse_population(tmp_path)
        assert result[0]["id"] == "prog_x"


# ── L1: parse_population() cell-index tests ───────────────────────────────────


class TestParsePopulationCellIndices:
    """Unit tests for MAP-Elites cell indices in ``parse_population()``."""

    def test_single_island_cell_indices(self, tmp_path: Path) -> None:
        """Programs found in metadata get correct cell_indices and island."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_json = _make_program_json("p1", metrics={"score": 1.0})
        (programs_dir / "p1.json").write_text(prog_json, encoding="utf-8")

        metadata = {"island_feature_maps": [{"0-5": "p1"}]}
        (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        result = parse_population(tmp_path)
        assert len(result) == 1
        assert result[0]["cell_indices"] == [0, 5]
        assert result[0]["island"] == 0

    def test_multi_island(self, tmp_path: Path) -> None:
        """Programs from different islands get correct island index."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        for pid in ["p1", "p2", "p3"]:
            prog_json = _make_program_json(pid, metrics={"score": 1.0})
            (programs_dir / f"{pid}.json").write_text(prog_json, encoding="utf-8")

        metadata = {
            "island_feature_maps": [
                {"0-5": "p1", "2-3": "p2"},
                {"1-1": "p3"},
            ]
        }
        (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        result = parse_population(tmp_path)
        by_id = {p["id"]: p for p in result}
        assert by_id["p1"]["cell_indices"] == [0, 5]
        assert by_id["p1"]["island"] == 0
        assert by_id["p2"]["cell_indices"] == [2, 3]
        assert by_id["p2"]["island"] == 0
        assert by_id["p3"]["cell_indices"] == [1, 1]
        assert by_id["p3"]["island"] == 1

    def test_program_not_in_feature_map(self, tmp_path: Path) -> None:
        """Programs not in any feature map get cell_indices=None."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        for pid in ["p1", "p2"]:
            prog_json = _make_program_json(pid, metrics={"score": 1.0})
            (programs_dir / f"{pid}.json").write_text(prog_json, encoding="utf-8")

        # Only p1 is in the feature map
        metadata = {"island_feature_maps": [{"0-5": "p1"}]}
        (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        result = parse_population(tmp_path)
        by_id = {p["id"]: p for p in result}
        assert by_id["p1"]["cell_indices"] == [0, 5]
        assert by_id["p1"]["island"] == 0
        assert by_id["p2"]["cell_indices"] is None
        assert by_id["p2"]["island"] is None

    def test_missing_metadata_json(self, tmp_path: Path) -> None:
        """All programs get null cell data when metadata.json is absent."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_json = _make_program_json("p1", metrics={"score": 1.0})
        (programs_dir / "p1.json").write_text(prog_json, encoding="utf-8")

        result = parse_population(tmp_path)
        assert result[0]["cell_indices"] is None
        assert result[0]["island"] is None

    def test_metadata_missing_island_feature_maps(self, tmp_path: Path) -> None:
        """Graceful fallback when island_feature_maps key is absent."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_json = _make_program_json("p1", metrics={"score": 1.0})
        (programs_dir / "p1.json").write_text(prog_json, encoding="utf-8")

        metadata = {"best_program_id": "p1"}
        (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        result = parse_population(tmp_path)
        assert result[0]["cell_indices"] is None
        assert result[0]["island"] is None

    def test_corrupt_metadata_json(self, tmp_path: Path) -> None:
        """Graceful fallback when metadata.json is not valid JSON."""
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_json = _make_program_json("p1", metrics={"score": 1.0})
        (programs_dir / "p1.json").write_text(prog_json, encoding="utf-8")

        (tmp_path / "metadata.json").write_text("not valid json", encoding="utf-8")

        result = parse_population(tmp_path)
        assert len(result) == 1
        assert result[0]["cell_indices"] is None
        assert result[0]["island"] is None


# ── L1: get_population() unit tests ─────────────────────────────────────────


class TestGetPopulation:
    """Unit tests for ``core.run.get_population()``."""

    def test_run_not_found(self, tmp_path: Path) -> None:
        """Raises RevolverError when run does not exist in DB."""
        init_project_store(tmp_path)
        db_path = tmp_path / REVOLVER_DIR / "revolver.db"
        get_project_db(db_path).close()

        with pytest.raises(Exception, match="not found"):
            get_population("nonexistent-run", project_root=tmp_path)

    def test_no_checkpoint(self, tmp_path: Path) -> None:
        """Raises RevolverError when run has no checkpoint directory."""
        root = _setup_project_with_run(tmp_path, "run-001", programs=None, create_checkpoint=False)
        # Create the run dir without any checkpoints
        run_dir = root / REVOLVER_DIR / "runs" / "run-001"
        run_dir.mkdir(parents=True, exist_ok=True)

        with pytest.raises(Exception, match="No checkpoint found"):
            get_population("run-001", project_root=root)

    def test_returns_population(self, tmp_path: Path) -> None:
        """Returns parsed population from checkpoint."""
        programs = [
            {"id": "p1", "metrics": {"score": 0.9}, "generation": 2, "iteration_found": 4},
            {"id": "p2", "metrics": {"score": 0.7}, "generation": 1, "iteration_found": 2},
        ]
        root = _setup_project_with_run(tmp_path, "run-002", programs=programs)

        result = get_population("run-002", project_root=root)

        assert len(result) == 2
        assert result[0]["id"] == "p1"
        assert result[0]["rank"] == 1
        assert result[1]["id"] == "p2"
        assert result[1]["rank"] == 2

    def test_empty_population(self, tmp_path: Path) -> None:
        """Returns empty list when checkpoint has no programs."""
        root = _setup_project_with_run(tmp_path, "run-003", programs=[])

        result = get_population("run-003", project_root=root)

        assert result == []


# ── L2: CLI integration tests ───────────────────────────────────────────────


class TestRunPopulationCLI:
    """L2 integration tests for ``revolver run population`` CLI command."""

    def test_run_population_shows_table(self, tmp_path: Path) -> None:
        """Displays a table with program entries, scores, and metrics."""
        programs = [
            {
                "id": "p1",
                "metrics": {"combined_score": 0.95},
                "generation": 3,
                "iteration_found": 5,
            },
            {
                "id": "p2",
                "metrics": {"combined_score": 0.80},
                "generation": 2,
                "iteration_found": 3,
            },
        ]
        _setup_project_with_run(tmp_path, "run-pop-1", programs=programs)

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["run", "population", "run-pop-1"])

        assert result.exit_code == 0
        output = result.output
        # Table should contain program IDs
        assert "p1" in output
        assert "p2" in output
        # Table should contain scores
        assert "0.9500" in output
        assert "0.8000" in output

    def test_run_population_json_output(self, tmp_path: Path) -> None:
        """With --json, outputs a JSON array of programs including cell data."""
        programs = [
            {
                "id": "p1",
                "metrics": {"combined_score": 0.95},
                "generation": 3,
                "iteration_found": 5,
            },
        ]
        metadata = {"island_feature_maps": [{"2-7": "p1"}]}
        _setup_project_with_run(tmp_path, "run-pop-2", programs=programs, metadata=metadata)

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["--json", "run", "population", "run-pop-2"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "p1"
        assert data[0]["score"] == pytest.approx(0.95)
        assert data[0]["rank"] == 1
        assert data[0]["cell_indices"] == [2, 7]
        assert data[0]["island"] == 0

    def test_run_population_run_not_found(self, tmp_path: Path) -> None:
        """Non-existent run ID produces an error."""
        init_project_store(tmp_path)
        db_path = tmp_path / REVOLVER_DIR / "revolver.db"
        get_project_db(db_path).close()

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["run", "population", "nonexistent"])

        assert result.exit_code != 0

    def test_run_population_no_checkpoint(self, tmp_path: Path) -> None:
        """Run with no checkpoint produces an error."""
        _setup_project_with_run(tmp_path, "run-pop-4", programs=None, create_checkpoint=False)
        run_dir = tmp_path / REVOLVER_DIR / "runs" / "run-pop-4"
        run_dir.mkdir(parents=True, exist_ok=True)

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["run", "population", "run-pop-4"])

        assert result.exit_code != 0

    def test_run_population_empty_no_crash(self, tmp_path: Path) -> None:
        """Empty population shows message without crashing."""
        _setup_project_with_run(tmp_path, "run-pop-5", programs=[])

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["run", "population", "run-pop-5"])

        assert result.exit_code == 0

    def test_run_population_shows_cell_column(self, tmp_path: Path) -> None:
        """Table output includes a Cell column with cell indices."""
        programs = [
            {
                "id": "p1",
                "metrics": {"score": 0.9},
                "generation": 1,
                "iteration_found": 1,
            },
        ]
        metadata = {"island_feature_maps": [{"3-8": "p1"}]}
        _setup_project_with_run(tmp_path, "run-pop-cell", programs=programs, metadata=metadata)

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["run", "population", "run-pop-cell"])

        assert result.exit_code == 0
        assert "[3, 8]" in result.output

    def test_run_population_no_island_column_single_island(self, tmp_path: Path) -> None:
        """Island column is hidden when all programs share the same island."""
        programs = [
            {"id": "p1", "metrics": {"score": 0.9}, "generation": 1, "iteration_found": 1},
            {"id": "p2", "metrics": {"score": 0.8}, "generation": 1, "iteration_found": 1},
        ]
        metadata = {"island_feature_maps": [{"0-1": "p1", "0-2": "p2"}]}
        _setup_project_with_run(tmp_path, "run-pop-noisland", programs=programs, metadata=metadata)

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["run", "population", "run-pop-noisland"])

        assert result.exit_code == 0
        # Island column header should NOT appear anywhere in output.
        # Rich may truncate headers (e.g. "isla…"), so check the short prefix.
        assert "isla" not in result.output.lower()

    def test_run_population_multi_island_shows_island_column(self, tmp_path: Path) -> None:
        """Island column appears when programs span multiple islands."""
        programs = [
            {"id": "p1", "metrics": {"score": 0.9}, "generation": 1, "iteration_found": 1},
            {"id": "p2", "metrics": {"score": 0.8}, "generation": 1, "iteration_found": 1},
        ]
        metadata = {"island_feature_maps": [{"0-1": "p1"}, {"0-2": "p2"}]}
        _setup_project_with_run(
            tmp_path, "run-pop-multiisland", programs=programs, metadata=metadata
        )

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(app, ["run", "population", "run-pop-multiisland"])

        assert result.exit_code == 0
        # Rich may truncate headers (e.g. "isla…"), so check the short prefix.
        assert "isla" in result.output.lower()


# ── L1: read_checkpoint_best_score() unit tests ──────────────────────────────


class TestReadCheckpointBestScore:
    """Unit tests for ``infra.openevolve.read_checkpoint_best_score()``."""

    def test_no_metadata_file(self, tmp_path: Path) -> None:
        """Returns None when metadata.json does not exist."""
        assert read_checkpoint_best_score(tmp_path) is None

    def test_no_best_program_id(self, tmp_path: Path) -> None:
        """Returns None when metadata.json has no best_program_id."""
        (tmp_path / "metadata.json").write_text(json.dumps({"version": 1}))
        assert read_checkpoint_best_score(tmp_path) is None

    def test_missing_program_file(self, tmp_path: Path) -> None:
        """Returns None when program file referenced by metadata is missing."""
        (tmp_path / "metadata.json").write_text(json.dumps({"best_program_id": "prog-999"}))
        (tmp_path / "programs").mkdir()
        assert read_checkpoint_best_score(tmp_path) is None

    def test_sums_all_numeric_metrics(self, tmp_path: Path) -> None:
        """Sums all numeric metrics including combined_score (consistent with parse_population)."""
        (tmp_path / "metadata.json").write_text(json.dumps({"best_program_id": "prog-001"}))
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_data = {
            "id": "prog-001",
            "metrics": {"combined_score": 42.5, "accuracy": 0.95},
        }
        (programs_dir / "prog-001.json").write_text(json.dumps(prog_data))

        result = read_checkpoint_best_score(tmp_path)

        assert result == pytest.approx(43.45)

    def test_sum_of_numeric_metrics_no_combined(self, tmp_path: Path) -> None:
        """Sums numeric metrics when no combined_score key is present."""
        (tmp_path / "metadata.json").write_text(json.dumps({"best_program_id": "prog-002"}))
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_data = {
            "id": "prog-002",
            "metrics": {"accuracy": 0.8, "throughput": 1.2},
        }
        (programs_dir / "prog-002.json").write_text(json.dumps(prog_data))

        result = read_checkpoint_best_score(tmp_path)

        assert result == pytest.approx(2.0)

    def test_empty_metrics(self, tmp_path: Path) -> None:
        """Returns None when program has no numeric metrics."""
        (tmp_path / "metadata.json").write_text(json.dumps({"best_program_id": "prog-003"}))
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        prog_data = {
            "id": "prog-003",
            "metrics": {},
        }
        (programs_dir / "prog-003.json").write_text(json.dumps(prog_data))

        assert read_checkpoint_best_score(tmp_path) is None

    def test_corrupt_metadata_json(self, tmp_path: Path) -> None:
        """Returns None when metadata.json is corrupt."""
        (tmp_path / "metadata.json").write_text("not valid json{{{")
        assert read_checkpoint_best_score(tmp_path) is None

    def test_corrupt_program_json(self, tmp_path: Path) -> None:
        """Returns None when program JSON is corrupt."""
        (tmp_path / "metadata.json").write_text(json.dumps({"best_program_id": "prog-bad"}))
        programs_dir = tmp_path / "programs"
        programs_dir.mkdir()
        (programs_dir / "prog-bad.json").write_text("invalid json")

        assert read_checkpoint_best_score(tmp_path) is None


# ── L1: recover_best_from_checkpoint() unit tests (B7) ───────────────────────


def _write_recovery_checkpoint(
    run_dir: Path,
    *,
    best_id: str = "prog-001",
    code: str = "def solve():\n    return 0\n",
    metrics: dict[str, float] | None = None,
) -> Path:
    """Write a checkpoint_5 under run_dir/oe-output/checkpoints and return it."""
    checkpoint = run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    programs_dir = checkpoint / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint / "metadata.json").write_text(json.dumps({"best_program_id": best_id}))
    (programs_dir / f"{best_id}.json").write_text(
        json.dumps(
            {
                "id": best_id,
                "code": code,
                "language": "python",
                "metrics": metrics if metrics is not None else {"combined_score": 1.0},
            }
        )
    )
    return checkpoint


class TestRecoverBestFromCheckpoint:
    """Unit tests for ``infra.openevolve.recover_best_from_checkpoint()`` (B7)."""

    def test_score_is_combined_score_not_sum(self, tmp_path: Path) -> None:
        """The recovered score is combined_score alone, NOT the sum of metrics.

        A program with combined_score plus other numeric metrics must not be
        over-counted (finding #1): 0.87 recovered, not 0.87 + 0.5 + 12.0.
        """
        _write_recovery_checkpoint(
            tmp_path,
            metrics={"combined_score": 0.87, "accuracy": 0.5, "latency_ms": 12.0},
        )

        recovered = recover_best_from_checkpoint(tmp_path)

        assert recovered.score == pytest.approx(0.87)
        assert recovered.program_id == "prog-001"
        assert recovered.language == "python"

    def test_score_none_when_no_combined_score(self, tmp_path: Path) -> None:
        """Falls back to None (not a summed value) when combined_score is absent."""
        _write_recovery_checkpoint(
            tmp_path, metrics={"accuracy": 0.8, "throughput": 1.2}
        )

        recovered = recover_best_from_checkpoint(tmp_path)

        assert recovered.score is None
        assert recovered.code.startswith("def solve():")

    def test_no_checkpoint_raises(self, tmp_path: Path) -> None:
        """Raises CheckpointRecoveryError when no checkpoint exists yet."""
        with pytest.raises(CheckpointRecoveryError, match="No checkpoint"):
            recover_best_from_checkpoint(tmp_path)

    def test_no_code_raises(self, tmp_path: Path) -> None:
        """Raises CheckpointRecoveryError when the best program has no code."""
        _write_recovery_checkpoint(tmp_path, code="")
        with pytest.raises(CheckpointRecoveryError, match="no usable code"):
            recover_best_from_checkpoint(tmp_path)
