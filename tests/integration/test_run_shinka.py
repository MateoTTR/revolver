"""L2-Shinka integration tests for ``revolver run --backend shinka`` (S14-14).

Exercises the CLI end-to-end through Typer's CliRunner with real SQLite
databases (project + global) in ``tmp_path``. The engine is mocked at the
``shinka.core.ShinkaEvolveRunner`` boundary; the engine's on-disk output
is simulated with the shared fixture ``programs.sqlite`` factory
(``tests/fixtures/programs_sqlite.py`` — verified 0.0.7 schema).

Scenarios (val-integration-tests.md §L2-Shinka):

(a) ``test_shinka_launch_mocked`` — mocked launch completes; run record
    and manifest carry ``backend='shinka'``; ``programs/rank-1.py`` is the
    DB's best program, NOT the initial program (R4 trap pin).
(b) ``test_shinka_dry_run`` — ``--dry-run`` shows Shinka ``backend_extras``.
(c) ``test_shinka_resume_mocked`` — resume inherits ``backend='shinka'``
    and reuses the parent's ``shinka-output/`` as the engine results dir.
(d) ``test_shinka_token_collection`` — engine-native token accounting from
    the fixture DB lands in the run record (ADR-007 D2).
(e) ``test_shinka_population_no_cell_indices`` — ``run population`` exits 0
    with no ``cell_indices`` field.

Skipped automatically when shinka-evolve is not installed (mirrors L2-OE).

Traceable to: sprint-014 S14-10..14, issue #194, ADR-007 D1/D2/D6,
FR-RUN-047/048, DES-005 §14.1.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

pytest.importorskip("shinka.database", reason="shinka-evolve not installed")

from revolver.cli import app
from revolver.core.project import init_project
from revolver.infra.db import get_global_db_at
from revolver.infra.store import REVOLVER_DIR, read_run_manifest
from tests.fixtures.programs_sqlite import (
    EXPECTED_COMPLETION_TOKENS,
    EXPECTED_COST_USD,
    EXPECTED_LAST_GENERATION,
    EXPECTED_PROMPT_TOKENS,
    EXPECTED_RANKED_IDS,
    EXPECTED_VALID_COUNT,
    SHINKA_OUTPUT_SUBDIR,
    build_programs_db,
)

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Counter for unique run/solution IDs in tests.
_id_counter = 0

# Fixture has 3 correct programs: with --iterations 3 a run completes clean.
_ITERATIONS = EXPECTED_VALID_COUNT

# Shinka-shaped problem config (the OE config_simple.yaml fixture would
# inject OE-only top-level keys into the projected config).
_SHINKA_CONFIG_YAML = """\
evo_config:
  num_generations: 2
  patch_types:
    - diff
    - full
  patch_type_probs:
    - 0.6
    - 0.4
db_config:
  num_islands: 2
job_config: {}
evaluation:
  timeout_per_instance: 30
"""


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


def _parse_json_output(result: object) -> Any:
    """Extract and parse the first JSON object/array from CLI output."""
    output = getattr(result, "output", "")
    for i, ch in enumerate(output):
        if ch in ("{", "["):
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(output, i)
            return obj
    msg = f"No JSON found in output: {output[:200]}"
    raise ValueError(msg)


def _next_ids() -> tuple[str, str]:
    """Generate unique run and solution IDs for tests."""
    global _id_counter
    _id_counter += 1
    return (
        f"run-20260612-{_id_counter:06d}",
        f"sol-20260612-{_id_counter:06d}",
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with init_project and return the root."""
    init_project(tmp_path, "test-project")
    return tmp_path


@pytest.fixture()
def dataset_dir(tmp_path: Path) -> Path:
    """Create a directory with 3 JSON instance files for dataset tests."""
    data_dir = tmp_path / "data" / "instances"
    data_dir.mkdir(parents=True)
    for i in range(1, 4):
        (data_dir / f"instance_{i:03d}.json").write_text(
            json.dumps({"id": i, "value": i * 10}),
            encoding="utf-8",
        )
    return data_dir


@pytest.fixture()
def global_db_path(tmp_path: Path) -> Path:
    """Return the path for a temporary global database."""
    db_path = tmp_path / "global.db"
    conn = get_global_db_at(db_path)
    conn.close()
    return db_path


def _create_problem_version(project_root: Path, tag: str) -> None:
    """Create a problem version with a Shinka-shaped config.yaml.

    Uses the ``evaluate_instance()`` evaluator fixture: the shinka
    backend rejects the legacy ``evaluate()``-only contract (DES-006 §1.3).
    """
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    shutil.copy2(fixtures_dir / "evaluator_instance.py", project_root / "evaluator.py")
    shutil.copy2(
        fixtures_dir / "initial_program_simple.py",
        project_root / "initial_program.py",
    )
    (project_root / "config.yaml").write_text(_SHINKA_CONFIG_YAML, encoding="utf-8")

    from revolver.core.problem import create_version

    create_version(tag=tag, message=f"Version {tag}", project_root=project_root)


def _register_local_llm(global_db_path: Path, name: str = "test-llm") -> None:
    """Register a local (Ollama-shaped) LLM in the global database."""
    conn = get_global_db_at(global_db_path)
    try:
        conn.execute(
            "INSERT INTO llms (name, provider, model, source, base_url, "
            "api_key_env, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                "ollama",
                "test-model",
                "local",
                "http://localhost:11434/v1",
                None,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def project_with_prereqs(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> dict[str, Path]:
    """Set up a project with problem version, local LLM, and dataset."""
    from revolver.core.dataset import register_dataset

    _create_problem_version(tmp_project, "v1.0")
    register_dataset(
        project_root=tmp_project,
        name="train-small",
        path=dataset_dir,
        split="train",
        compatible_with=["v1.0"],
    )
    _register_local_llm(global_db_path)
    return {
        "root": tmp_project,
        "dataset_dir": dataset_dir,
        "global_db_path": global_db_path,
    }


def _make_mock_runner_cls(write_fixture_db: bool = True) -> MagicMock:
    """Build a mocked ShinkaEvolveRunner class.

    Construction kwargs are recorded on the returned class mock
    (``.call_args_list``). When *write_fixture_db* is true, ``run()``
    simulates the engine by writing the fixture ``programs.sqlite`` into
    the ``results_dir`` the backend configured.
    """

    def _factory(**kwargs: Any) -> MagicMock:
        instance = MagicMock()

        def _run() -> None:
            if write_fixture_db:
                results_dir = Path(kwargs["evo_config"].results_dir)
                build_programs_db(results_dir / "programs.sqlite")

        instance.run.side_effect = _run
        return instance

    return MagicMock(side_effect=_factory)


def _invoke_with_mocks(
    args: list[str],
    cwd: Path,
    global_db_path: Path,
    mock_runner_cls: MagicMock | None = None,
    run_id: str | None = None,
) -> tuple[Any, MagicMock, str]:
    """Invoke the CLI with a mocked ShinkaEvolveRunner and temp global DB."""
    if mock_runner_cls is None:
        mock_runner_cls = _make_mock_runner_cls()

    auto_run_id, sol_id = _next_ids()
    run_id = run_id or auto_run_id

    with (
        patch("pathlib.Path.cwd", return_value=cwd),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("shinka.core.ShinkaEvolveRunner", mock_runner_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=run_id),
        patch("revolver.core.run.generate_solution_id", return_value=sol_id),
    ):
        result = runner.invoke(app, args, catch_exceptions=False)
    return result, mock_runner_cls, run_id


def _launch_shinka_run(
    project: dict[str, Path],
    extra_args: list[str] | None = None,
) -> tuple[Any, MagicMock, str]:
    """Launch a mocked Shinka run and return (result, runner_cls, run_id)."""
    args = [
        "run",
        "--version",
        "v1.0",
        "--llm",
        "test-llm",
        "--dataset",
        "train-small",
        "--backend",
        "shinka",
        "--iterations",
        str(_ITERATIONS),
        *(extra_args or []),
    ]
    return _invoke_with_mocks(args, project["root"], project["global_db_path"])


def _get_run_row(root: Path, run_id: str) -> dict[str, Any]:
    """Read a run row from the project database as a dict."""
    conn = sqlite3.connect(root / REVOLVER_DIR / "revolver.db")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None, f"run record {run_id} not found"
    return dict(row)


# ── (a) Mocked launch (S14-10, FR-RUN-047) ───────────────────────────────────


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_launch_mocked(project_with_prereqs: dict[str, Path]) -> None:
    """Mocked launch completes; record + manifest carry backend='shinka'."""
    root = project_with_prereqs["root"]

    result, mock_runner_cls, run_id = _launch_shinka_run(project_with_prereqs)

    assert result.exit_code == 0, _get_all_output(result)

    # Run record: backend + clean completion (3 valid / 3 iterations).
    row = _get_run_row(root, run_id)
    assert row["backend"] == "shinka"
    assert row["status"] == "completed"
    assert row["valid_iterations"] == EXPECTED_VALID_COUNT

    # Manifest: backend recorded for full traceability.
    manifest = read_run_manifest(root, run_id)
    assert manifest is not None
    assert manifest["backend"] == "shinka"
    assert manifest["status"] == "completed"

    # Engine boundary: the runner was constructed once with the projected
    # config and string contents, and run() was called.
    assert mock_runner_cls.call_count == 1
    kwargs = mock_runner_cls.call_args.kwargs
    run_dir = root / REVOLVER_DIR / "runs" / run_id
    assert kwargs["evo_config"].results_dir == str(run_dir / SHINKA_OUTPUT_SUBDIR)
    assert kwargs["evo_config"].num_generations == _ITERATIONS
    assert kwargs["evo_config"].llm_dynamic_selection == "fixed"
    assert kwargs["init_program_str"]
    assert "--program_path" in kwargs["evaluate_str"]

    # R4 trap pin: rank-1 is the DB's best program, NOT the engine's own
    # root init_program.py (and not Revolver's initial program either).
    rank1 = run_dir / "programs" / "rank-1.py"
    assert rank1.exists()
    initial_program = (root / REVOLVER_DIR / "problem" / "v1.0" / "initial_program.py").read_text()
    assert rank1.read_text() != initial_program
    assert "def solve(data)" in rank1.read_text()  # fixture best-program code
    assert not (run_dir / "programs" / "rank-2.py").exists()


# ── (b) Dry-run (S14-08, ADR-007 D4) ─────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_dry_run(project_with_prereqs: dict[str, Path]) -> None:
    """--dry-run exits 0 and shows the Shinka backend_extras fields."""
    result, mock_runner_cls, _run_id = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--backend",
            "shinka",
            "--dry-run",
        ],
        project_with_prereqs["root"],
        project_with_prereqs["global_db_path"],
    )

    assert result.exit_code == 0, _get_all_output(result)
    output = _get_all_output(result)
    assert "Resolved shinka config" in output
    # Shinka-exclusive extras (never part of the neutral section).
    assert "patch_types" in output
    assert "llm_dynamic_selection" in output
    assert "fixed" in output
    # Dry-run has no side effects: the engine was never constructed.
    assert mock_runner_cls.call_count == 0


# ── (c) Mocked resume (S14-13, FR-RUN-024/047) ───────────────────────────────


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_resume_mocked(project_with_prereqs: dict[str, Path]) -> None:
    """Resume inherits backend='shinka' and reuses the parent shinka-output/."""
    root = project_with_prereqs["root"]

    launch_result, _cls, parent_run_id = _launch_shinka_run(project_with_prereqs)
    assert launch_result.exit_code == 0, _get_all_output(launch_result)

    resume_runner_cls = _make_mock_runner_cls(write_fixture_db=False)
    result, _, new_run_id = _invoke_with_mocks(
        ["run", "resume", "--run", parent_run_id],
        root,
        project_with_prereqs["global_db_path"],
        mock_runner_cls=resume_runner_cls,
    )

    assert result.exit_code == 0, _get_all_output(result)

    # The resumed run inherits the parent's backend (no --backend given).
    row = _get_run_row(root, new_run_id)
    assert row["backend"] == "shinka"
    assert row["resumed_from"] == parent_run_id
    assert row["status"] == "completed"

    # The engine resumed IN the parent's shinka-output/ (DB-driven resume)
    # with an extended generation target (last_iteration + iterations).
    parent_output = root / REVOLVER_DIR / "runs" / parent_run_id / SHINKA_OUTPUT_SUBDIR
    kwargs = resume_runner_cls.call_args.kwargs
    assert kwargs["evo_config"].results_dir == str(parent_output)
    assert kwargs["evo_config"].num_generations == EXPECTED_LAST_GENERATION + _ITERATIONS

    # Results were materialized into the NEW run dir (DB snapshot + best/).
    new_run_dir = root / REVOLVER_DIR / "runs" / new_run_id
    assert (new_run_dir / SHINKA_OUTPUT_SUBDIR / "programs.sqlite").exists()
    assert (new_run_dir / "programs" / "rank-1.py").exists()

    manifest = read_run_manifest(root, new_run_id)
    assert manifest is not None
    assert manifest["backend"] == "shinka"
    assert manifest["resumed_from"] == parent_run_id


# ── (d) Engine-native token collection (S14-11, ADR-007 D2) ──────────────────


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_token_collection(project_with_prereqs: dict[str, Path]) -> None:
    """Token usage read from the fixture programs.sqlite lands in the record."""
    root = project_with_prereqs["root"]

    result, _cls, run_id = _launch_shinka_run(project_with_prereqs)
    assert result.exit_code == 0, _get_all_output(result)

    row = _get_run_row(root, run_id)
    assert row["prompt_tokens"] == EXPECTED_PROMPT_TOKENS
    assert row["completion_tokens"] == EXPECTED_COMPLETION_TOKENS

    manifest = read_run_manifest(root, run_id)
    assert manifest is not None
    token_usage = manifest["token_usage"]
    assert token_usage["prompt_tokens"] == EXPECTED_PROMPT_TOKENS
    assert token_usage["completion_tokens"] == EXPECTED_COMPLETION_TOKENS
    assert token_usage["estimated_cost_usd"] == pytest.approx(EXPECTED_COST_USD)


# ── (e) run population (S14-12) ───────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_population_no_cell_indices(project_with_prereqs: dict[str, Path]) -> None:
    """run population renders a Shinka run without cell_indices, exit 0."""
    root = project_with_prereqs["root"]

    result, _cls, run_id = _launch_shinka_run(project_with_prereqs)
    assert result.exit_code == 0, _get_all_output(result)

    # Table mode: the renderer must cope with the cell-less entries.
    with patch("pathlib.Path.cwd", return_value=root):
        table_result = runner.invoke(app, ["run", "population", run_id], catch_exceptions=False)
    assert table_result.exit_code == 0, _get_all_output(table_result)

    # JSON mode: pin the field contract.
    with patch("pathlib.Path.cwd", return_value=root):
        json_result = runner.invoke(
            app, ["--json", "run", "population", run_id], catch_exceptions=False
        )
    assert json_result.exit_code == 0, _get_all_output(json_result)
    population = _parse_json_output(json_result)
    assert isinstance(population, list)
    assert len(population) > 0
    for entry in population:
        assert "cell_indices" not in entry
        assert "island" not in entry
        for key in ("id", "generation", "combined_score", "correct", "public_metrics"):
            assert key in entry
    scored = [e for e in population if e["combined_score"] is not None]
    assert [e["id"] for e in scored] == list(EXPECTED_RANKED_IDS)
