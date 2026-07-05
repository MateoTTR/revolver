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
    and runs the engine on a CLONE of the parent's ``shinka-output/`` in
    the new run dir (clone-resume, S16-11).
(c2) ``test_shinka_resume_clone_isolation`` — a clone-resume leaves the
    parent's ``programs.sqlite`` byte-unchanged while the resumed run's DB
    carries the cloned programs plus the new generations (S16-12).
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
from revolver.core.exceptions import ValidationError
from revolver.core.project import init_project
from revolver.core.run import get_run_info
from revolver.infra.backends.base import BackendRunSpec
from revolver.infra.backends.shinka import ShinkaBackend
from revolver.infra.db import get_global_db_at
from revolver.infra.store import REVOLVER_DIR, read_run_manifest
from revolver.models.llm import EnsembleEntry, EnsembleMember, LLMEntry
from tests.fixtures.programs_sqlite import (
    EXPECTED_COMPLETION_TOKENS,
    EXPECTED_LAST_GENERATION,
    EXPECTED_PROMPT_TOKENS,
    EXPECTED_RANKED_IDS,
    EXPECTED_VALID_COUNT,
    FIXTURE_PROGRAM_ROWS,
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


def _register_local_llm(
    global_db_path: Path,
    name: str = "test-llm",
    timeout_s: int | None = None,
) -> None:
    """Register a local (Ollama-shaped) LLM in the global database."""
    conn = get_global_db_at(global_db_path)
    try:
        conn.execute(
            "INSERT INTO llms (name, provider, model, source, base_url, "
            "api_key_env, timeout_s, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                "ollama",
                "test-model",
                "local",
                "http://localhost:11434/v1",
                None,
                timeout_s,
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


def _program_ids(db_path: Path) -> set[str]:
    """Return the set of program ids stored in a shinka programs.sqlite."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT id FROM programs").fetchall()
    finally:
        conn.close()
    return {str(r[0]) for r in rows}


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


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_zero_scored_programs_collects_nothing(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Engine completes with no scored program → no bogus solutions (review #196 W2).

    The mocked engine writes a ``programs.sqlite`` whose rows all have a
    NULL ``combined_score`` AND its own root scripts (``init_program.py``,
    ``evaluate.py``) — the real engine always writes those. The
    orchestrator's collection must NOT fall back to those root files: the
    run is ``failed`` with zero collected programs.
    """
    root = project_with_prereqs["root"]

    null_score_rows = tuple(
        {**row, "combined_score": None, "correct": 0, "public_metrics": {}}
        for row in FIXTURE_PROGRAM_ROWS
    )

    def _factory(**kwargs: Any) -> MagicMock:
        instance = MagicMock()

        def _run() -> None:
            results_dir = Path(kwargs["evo_config"].results_dir)
            build_programs_db(results_dir / "programs.sqlite", rows=null_score_rows)
            # The real engine writes its own scripts at the results root.
            (results_dir / "init_program.py").write_text("def solve(data):\n    return 0\n")
            (results_dir / "evaluate.py").write_text("# engine evaluate script\n")

        instance.run.side_effect = _run
        return instance

    result, _runner_cls, run_id = _invoke_with_mocks(
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
            "--iterations",
            str(_ITERATIONS),
        ],
        project_with_prereqs["root"],
        project_with_prereqs["global_db_path"],
        mock_runner_cls=MagicMock(side_effect=_factory),
    )

    row = _get_run_row(root, run_id)
    assert row["status"] == "failed"

    run_dir = root / REVOLVER_DIR / "runs" / run_id
    programs_dir = run_dir / "programs"
    collected = sorted(programs_dir.glob("*.py")) if programs_dir.exists() else []
    assert collected == [], f"bogus programs collected: {collected}\n{_get_all_output(result)}"


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_unproductive_run_completed_with_errors(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Init-only run (0 evolved children) → completed_with_errors + warning (#302).

    The mocked engine writes a ``programs.sqlite`` holding only the
    file-based init program (no ``llm_result``). The orchestrator must flag
    the run ``completed_with_errors``, set ``RunInfo.produced_no_children``,
    and surface a user-visible warning both at run time and in ``run info``.
    """
    root = project_with_prereqs["root"]
    init_only_rows = (FIXTURE_PROGRAM_ROWS[0],)

    def _factory(**kwargs: Any) -> MagicMock:
        instance = MagicMock()

        def _run() -> None:
            results_dir = Path(kwargs["evo_config"].results_dir)
            build_programs_db(results_dir / "programs.sqlite", rows=init_only_rows)
            (results_dir / "init_program.py").write_text("def solve(data):\n    return 0\n")
            (results_dir / "evaluate.py").write_text("# engine evaluate script\n")

        instance.run.side_effect = _run
        return instance

    result, _runner_cls, run_id = _invoke_with_mocks(
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
            "--iterations",
            str(_ITERATIONS),
        ],
        root,
        project_with_prereqs["global_db_path"],
        mock_runner_cls=MagicMock(side_effect=_factory),
    )

    # Status downgraded to completed_with_errors (not a plain 'completed').
    assert _get_run_row(root, run_id)["status"] == "completed_with_errors"
    # Run-time warning surfaced.
    assert "no evolved child programs" in _get_all_output(result)
    # RunInfo carries the unproductive flag.
    assert get_run_info(run_id, project_root=root).produced_no_children is True

    # `run info` renders the warning line.
    info_result, _cls, _rid = _invoke_with_mocks(
        ["run", "info", run_id],
        root,
        project_with_prereqs["global_db_path"],
        run_id=run_id,
    )
    assert "no evolved child programs" in _get_all_output(info_result)


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


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_evaluation_on_timeout_validation(
    project_with_prereqs: dict[str, Path],
) -> None:
    """evaluation.* is validated on the Shinka launch path too (FR-RUN-054).

    The policy parse happens at the shared launch point AFTER the backend's
    ``build_config``, so this locks two things on the Shinka path: bad
    values exit 1 at dry-run before the engine is constructed, and the
    Shinka ``build_config`` preserves the user's ``evaluation.*`` overrides
    for the parse (valid values dry-run clean).
    """
    base = [
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
    ]

    result, mock_runner_cls, _ = _invoke_with_mocks(
        [*base, "--config-override", "evaluation.on_timeout=bogus"],
        project_with_prereqs["root"],
        project_with_prereqs["global_db_path"],
    )
    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Invalid evaluation.on_timeout 'bogus'" in output
    assert mock_runner_cls.call_count == 0

    result, mock_runner_cls, _ = _invoke_with_mocks(
        [
            *base,
            "--config-override",
            "evaluation.on_timeout=drop",
            "--config-override",
            "evaluation.timeout_score=-1.0",
        ],
        project_with_prereqs["root"],
        project_with_prereqs["global_db_path"],
    )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert mock_runner_cls.call_count == 0


# ── (c) Mocked resume (S14-13, FR-RUN-024/047) ───────────────────────────────


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_resume_mocked(project_with_prereqs: dict[str, Path]) -> None:
    """Resume inherits backend='shinka' and runs on a CLONE of the parent dir."""
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

    # The engine resumed on the NEW run's shinka-output/ (a clone of the
    # parent — S16-11), with an extended generation target derived from the
    # clone's last_iteration (last_iteration + iterations).
    new_run_dir = root / REVOLVER_DIR / "runs" / new_run_id
    new_output = new_run_dir / SHINKA_OUTPUT_SUBDIR
    kwargs = resume_runner_cls.call_args.kwargs
    assert kwargs["evo_config"].results_dir == str(new_output)
    assert kwargs["evo_config"].num_generations == EXPECTED_LAST_GENERATION + _ITERATIONS

    # The clone carries the parent's programs DB and the best program is
    # materialized from it into the new run dir.
    assert (new_output / "programs.sqlite").exists()
    assert (new_run_dir / "programs" / "rank-1.py").exists()

    manifest = read_run_manifest(root, new_run_id)
    assert manifest is not None
    assert manifest["backend"] == "shinka"
    assert manifest["resumed_from"] == parent_run_id


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_resume_clone_isolation(project_with_prereqs: dict[str, Path]) -> None:
    """Clone-resume leaves the parent DB byte-unchanged; clone gains new rows.

    Run A (mocked) writes the fixture programs.sqlite into the parent run's
    shinka-output/. Resume to run B on a CLONE of that dir: the mocked
    engine appends a new-generation row to the clone's DB (simulating fresh
    generations). Asserts (S16-12):

    - the PARENT programs.sqlite is byte-identical before and after B
      (clone-resume isolation — the parent dir is never written to);
    - the resumed run's DB contains the cloned programs PLUS the new row.
    """
    root = project_with_prereqs["root"]

    launch_result, _cls, parent_run_id = _launch_shinka_run(project_with_prereqs)
    assert launch_result.exit_code == 0, _get_all_output(launch_result)

    parent_db = (
        root / REVOLVER_DIR / "runs" / parent_run_id / SHINKA_OUTPUT_SUBDIR / "programs.sqlite"
    )
    assert parent_db.exists()
    parent_bytes_before = parent_db.read_bytes()
    parent_ids_before = _program_ids(parent_db)

    # Mocked resume engine: append one new-generation child to the clone's
    # DB (the engine continues on the clone the backend handed it).
    new_program_id = "prog-gen3-resume"

    def _resume_factory(**kwargs: Any) -> MagicMock:
        instance = MagicMock()

        def _run() -> None:
            clone_db = Path(kwargs["evo_config"].results_dir) / "programs.sqlite"
            conn = sqlite3.connect(clone_db)
            try:
                conn.execute(
                    "INSERT INTO programs (id, code, language, generation, "
                    "timestamp, combined_score, correct, children_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_program_id,
                        "def solve(d):\n    return 1\n",
                        "python",
                        3,
                        0.0,
                        0.99,
                        1,
                        0,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        instance.run.side_effect = _run
        return instance

    resume_runner_cls = MagicMock(side_effect=_resume_factory)
    result, _, new_run_id = _invoke_with_mocks(
        ["run", "resume", "--run", parent_run_id],
        root,
        project_with_prereqs["global_db_path"],
        mock_runner_cls=resume_runner_cls,
    )
    assert result.exit_code == 0, _get_all_output(result)

    # The parent's programs.sqlite is byte-unchanged (clone-resume isolation).
    assert parent_db.read_bytes() == parent_bytes_before
    assert _program_ids(parent_db) == parent_ids_before
    assert new_program_id not in parent_ids_before

    # The resumed run's DB holds the cloned programs PLUS the new generation.
    clone_db = root / REVOLVER_DIR / "runs" / new_run_id / SHINKA_OUTPUT_SUBDIR / "programs.sqlite"
    assert clone_db.exists()
    clone_ids = _program_ids(clone_db)
    assert parent_ids_before <= clone_ids  # cloned programs preserved
    assert new_program_id in clone_ids  # new generation appended


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
    # Cost is not reported (S15 / #300): no cost key in the manifest.
    assert "estimated_cost_usd" not in token_usage


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


# ── (f) Ensemble → bandit mapping (S17-19/20/21, ADR-007 A2/A5) ───────────────
# These drive ``ShinkaBackend.build_config()`` directly with a constructed
# ``BackendRunSpec``: the ensemble→bandit projection lives entirely in the
# backend adapter (PR-W1b); the ``--selection``/``--llm-weight`` CLI flags that
# populate the spec are wired separately in PR-W1c. Building the config directly
# is the tightest unit for the mapping and captures the exact evo_config keys.


def _local_llm_entry(name: str, timeout_s: int | None = None) -> LLMEntry:
    """Build a local (Ollama-shaped) ``LLMEntry`` for spec construction."""
    return LLMEntry(
        name=name,
        provider="ollama",
        model=f"{name}-model",
        source="local",
        base_url="http://localhost:11434/v1",
        timeout_s=timeout_s,
        registered_at=datetime.now(UTC),
    )


def _register_llm_entry(global_db_path: Path, entry: LLMEntry) -> None:
    """Insert an ``LLMEntry`` into the temp global registry (for member lookup)."""
    conn = get_global_db_at(global_db_path)
    try:
        conn.execute(
            "INSERT INTO llms (name, provider, model, source, base_url, "
            "api_key_env, timeout_s, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.name,
                entry.provider,
                entry.model,
                entry.source,
                entry.base_url,
                entry.api_key_env,
                entry.timeout_s,
                entry.registered_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _ensemble_spec(
    snapshot_dir: Path,
    global_db_path: Path,
    members: list[EnsembleMember],
    *,
    selection: str | None = None,
    selection_kwargs: dict[str, Any] | None = None,
    llm_weight_overrides: dict[str, float] | None = None,
    timeouts: dict[str, int] | None = None,
) -> BackendRunSpec:
    """Register the member LLMs and build an ensemble ``BackendRunSpec``."""
    for member in members:
        _register_llm_entry(
            global_db_path,
            _local_llm_entry(member.llm_name, timeout_s=(timeouts or {}).get(member.llm_name)),
        )
    conn = get_global_db_at(global_db_path)
    primary = _local_llm_entry(members[0].llm_name)
    ensemble = EnsembleEntry(name="ens", members=members, created_at=datetime.now(UTC))
    return BackendRunSpec(
        snapshot_dir=snapshot_dir,
        llm=primary,
        ensemble=ensemble,
        conn=conn,
        selection=selection,
        selection_kwargs=selection_kwargs,
        llm_weight_overrides=llm_weight_overrides,
    )


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_single_llm_config_unchanged(tmp_path: Path) -> None:
    """Zero behaviour change: a single-LLM (no-ensemble) spec builds the same
    evo_config LLM projection as before A2 — fixed, one model, and crucially NO
    ``llm_dynamic_selection_kwargs`` / ``prior_probs`` key."""
    llm = _local_llm_entry("solo")
    spec = BackendRunSpec(snapshot_dir=tmp_path, llm=llm)

    evo = ShinkaBackend().build_config(spec)["evo_config"]

    assert evo["llm_models"] == [
        "local/solo-model@http://localhost:11434/v1?api_key_env=OLLAMA_API_KEY"
    ]
    assert evo["llm_dynamic_selection"] == "fixed"
    # The single-LLM path must not gain a sampler-kwargs key (regression pin).
    assert "llm_dynamic_selection_kwargs" not in evo


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_ensemble_projects_all_members(tmp_path: Path, global_db_path: Path) -> None:
    """An N-member ensemble projects N entries into ``llm_models`` in order."""
    members = [EnsembleMember(llm_name="m-a"), EnsembleMember(llm_name="m-b")]
    spec = _ensemble_spec(tmp_path, global_db_path, members)

    evo = ShinkaBackend().build_config(spec)["evo_config"]

    assert len(evo["llm_models"]) == 2
    assert evo["llm_models"][0].startswith("local/m-a-model@")
    assert evo["llm_models"][1].startswith("local/m-b-model@")
    assert evo["llm_dynamic_selection"] == "fixed"


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_selection_fixed_prior_probs(tmp_path: Path, global_db_path: Path) -> None:
    """--selection fixed with 2 members weighted 0.7/0.3 → prior_probs [0.7, 0.3]
    aligned to llm_models order (S17-20)."""
    members = [
        EnsembleMember(llm_name="m-a", weight=0.7),
        EnsembleMember(llm_name="m-b", weight=0.3),
    ]
    spec = _ensemble_spec(tmp_path, global_db_path, members, selection="fixed")

    evo = ShinkaBackend().build_config(spec)["evo_config"]

    assert evo["llm_dynamic_selection"] == "fixed"
    prior = evo["llm_dynamic_selection_kwargs"]["prior_probs"]
    assert prior == pytest.approx([0.7, 0.3])


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_selection_fixed_prior_probs_renormalized(
    tmp_path: Path, global_db_path: Path
) -> None:
    """Non-normalized weights (3/1) renormalize to sum 1 → [0.75, 0.25]."""
    members = [
        EnsembleMember(llm_name="m-a", weight=3.0),
        EnsembleMember(llm_name="m-b", weight=1.0),
    ]
    spec = _ensemble_spec(tmp_path, global_db_path, members, selection="fixed")

    evo = ShinkaBackend().build_config(spec)["evo_config"]
    prior = evo["llm_dynamic_selection_kwargs"]["prior_probs"]
    assert prior == pytest.approx([0.75, 0.25])
    assert sum(prior) == pytest.approx(1.0)


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_fixed_llm_weight_override_wins(tmp_path: Path, global_db_path: Path) -> None:
    """--llm-weight overrides win over registry member weights under fixed."""
    members = [
        EnsembleMember(llm_name="m-a", weight=0.5),
        EnsembleMember(llm_name="m-b", weight=0.5),
    ]
    spec = _ensemble_spec(
        tmp_path,
        global_db_path,
        members,
        selection="fixed",
        llm_weight_overrides={"m-a": 0.9, "m-b": 0.1},
    )

    evo = ShinkaBackend().build_config(spec)["evo_config"]
    prior = evo["llm_dynamic_selection_kwargs"]["prior_probs"]
    assert prior == pytest.approx([0.9, 0.1])


@pytest.mark.integration
@pytest.mark.shinkaevolve
@pytest.mark.parametrize("selection", ["ucb", "ucb1", "thompson"])
def test_shinka_adaptive_ignores_weights_warns(
    tmp_path: Path,
    global_db_path: Path,
    capsys: pytest.CaptureFixture[str],
    selection: str,
) -> None:
    """Adaptive samplers must NOT receive prior_probs (FACT B TypeError) and
    warn that weights are ignored (S17-20)."""
    members = [
        EnsembleMember(llm_name="m-a", weight=0.7),
        EnsembleMember(llm_name="m-b", weight=0.3),
    ]
    spec = _ensemble_spec(tmp_path, global_db_path, members, selection=selection)

    evo = ShinkaBackend().build_config(spec)["evo_config"]

    assert evo["llm_dynamic_selection"] == selection
    kwargs = evo.get("llm_dynamic_selection_kwargs", {})
    assert "prior_probs" not in kwargs
    warning = capsys.readouterr().err
    assert "ignored" in warning and selection in warning
    # U9 doc part (S17a-16): the warning carries the short-run guidance.
    assert "prefer --selection fixed" in warning
    assert "no per-arm prior" in warning


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_ucb_cost_aware_coef_default_zero(tmp_path: Path, global_db_path: Path) -> None:
    """ucb/ucb1 get Revolver's cost_aware_coef default of 0 (not Shinka's 0.5)."""
    members = [EnsembleMember(llm_name="m-a"), EnsembleMember(llm_name="m-b")]
    spec = _ensemble_spec(tmp_path, global_db_path, members, selection="ucb")

    evo = ShinkaBackend().build_config(spec)["evo_config"]
    assert evo["llm_dynamic_selection_kwargs"]["cost_aware_coef"] == 0.0


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_ucb_cost_aware_coef_user_value(tmp_path: Path, global_db_path: Path) -> None:
    """--selection-kwarg cost_aware_coef=0.3 is honored on ucb."""
    members = [EnsembleMember(llm_name="m-a"), EnsembleMember(llm_name="m-b")]
    spec = _ensemble_spec(
        tmp_path,
        global_db_path,
        members,
        selection="ucb",
        selection_kwargs={"cost_aware_coef": 0.3},
    )

    evo = ShinkaBackend().build_config(spec)["evo_config"]
    assert evo["llm_dynamic_selection_kwargs"]["cost_aware_coef"] == 0.3


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_fixed_drops_cost_aware_coef_warns(
    tmp_path: Path, global_db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cost_aware_coef under fixed is dropped-with-warning (FixedSampler would
    silently ignore it — S17-21)."""
    members = [
        EnsembleMember(llm_name="m-a", weight=0.6),
        EnsembleMember(llm_name="m-b", weight=0.4),
    ]
    spec = _ensemble_spec(
        tmp_path,
        global_db_path,
        members,
        selection="fixed",
        selection_kwargs={"cost_aware_coef": 0.3},
    )

    evo = ShinkaBackend().build_config(spec)["evo_config"]
    kwargs = evo["llm_dynamic_selection_kwargs"]
    assert "cost_aware_coef" not in kwargs
    assert "prior_probs" in kwargs  # weights still projected
    assert "cost_aware_coef" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_thompson_drops_cost_aware_coef_warns(
    tmp_path: Path, global_db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cost_aware_coef under thompson is dropped-with-warning (would TypeError if
    spread into ThompsonSampler — S17-21)."""
    members = [EnsembleMember(llm_name="m-a"), EnsembleMember(llm_name="m-b")]
    spec = _ensemble_spec(
        tmp_path,
        global_db_path,
        members,
        selection="thompson",
        selection_kwargs={"cost_aware_coef": 0.3},
    )

    evo = ShinkaBackend().build_config(spec)["evo_config"]
    kwargs = evo.get("llm_dynamic_selection_kwargs", {})
    assert "cost_aware_coef" not in kwargs
    assert "cost_aware_coef" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_ucb_drops_unknown_kwarg_warns(
    tmp_path: Path, global_db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unrecognized selection-kwarg on ucb is dropped-with-warning (never
    spread — it would TypeError in AsymmetricUCB, which has no **kwargs)."""
    members = [EnsembleMember(llm_name="m-a"), EnsembleMember(llm_name="m-b")]
    spec = _ensemble_spec(
        tmp_path,
        global_db_path,
        members,
        selection="ucb",
        selection_kwargs={"epsilon": 0.4, "bogus_key": 1},
    )

    evo = ShinkaBackend().build_config(spec)["evo_config"]
    kwargs = evo["llm_dynamic_selection_kwargs"]
    assert kwargs["epsilon"] == 0.4  # accepted ucb kwarg passes through
    assert "bogus_key" not in kwargs
    assert "bogus_key" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_fixed_uniform_ensemble_prior_probs(tmp_path: Path, global_db_path: Path) -> None:
    """A uniform (default-weight) ensemble under fixed still gets an explicit
    even prior_probs vector (weights are 'present' as an ensemble signal)."""
    members = [EnsembleMember(llm_name="m-a"), EnsembleMember(llm_name="m-b")]
    spec = _ensemble_spec(tmp_path, global_db_path, members, selection="fixed")

    evo = ShinkaBackend().build_config(spec)["evo_config"]
    prior = evo["llm_dynamic_selection_kwargs"]["prior_probs"]
    assert prior == pytest.approx([0.5, 0.5])


# ── (g) S17a PR-C papercuts: U1 fail-fast + U10 dry-run surfacing ─────────────
# Install-gated twins of the unit tests in tests/unit/infra/
# test_shinka_backend.py (which run on the no-shinka env via fake modules).


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_ucb_residual_string_kwarg_fails_fast(tmp_path: Path, global_db_path: Path) -> None:
    """U1 (S17a-08): a residual string on an accepted ucb kwarg raises at
    build_config time — i.e. at --dry-run, before any engine launch."""
    members = [EnsembleMember(llm_name="m-a"), EnsembleMember(llm_name="m-b")]
    spec = _ensemble_spec(
        tmp_path,
        global_db_path,
        members,
        selection="ucb",
        selection_kwargs={"epsilon": "abc"},
    )
    with pytest.raises(ValidationError, match="epsilon=abc"):
        ShinkaBackend().build_config(spec)


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_resolved_config_surfaces_selection_kwargs(
    tmp_path: Path, global_db_path: Path
) -> None:
    """U10 (S17a-14): a build→resolve round trip surfaces prior_probs in
    backend_extras and zips member weights into llm_models entries."""
    members = [
        EnsembleMember(llm_name="m-a", weight=0.7),
        EnsembleMember(llm_name="m-b", weight=0.3),
    ]
    spec = _ensemble_spec(tmp_path, global_db_path, members, selection="fixed")

    backend = ShinkaBackend()
    resolved = backend.resolved_config(backend.build_config(spec))

    kwargs = resolved.backend_extras["llm_dynamic_selection_kwargs"]
    assert kwargs["prior_probs"] == pytest.approx([0.7, 0.3])
    assert resolved.llm_models is not None
    assert [entry["weight"] for entry in resolved.llm_models] == pytest.approx([0.7, 0.3])


# ── (g) LLM request timeout lever (R2 / #320 / #260) ─────────────────────────
# The neutral registry field ``timeout_s`` maps onto shinka's module global
# ``shinka.llm.client.TIMEOUT`` (hard-coded 1200 s in 0.0.7, read at call
# time — the seam the spike's fast-mode repro empirically verified).
# ``_run_engine`` sets it for the duration of the engine run and restores it
# afterwards; ``--dry-run`` surfaces the resolved value as ``llm_timeout``.


def _make_timeout_probe_runner(
    observed: list[Any],
    run_exc: Exception | None = None,
) -> MagicMock:
    """Mock runner class whose run() records shinka.llm.client.TIMEOUT.

    The capture happens inside ``run()`` — i.e. while the engine would be
    issuing LLM requests — so the recorded value is exactly what shinka's
    per-query client construction would read. Writes the fixture DB (clean
    completion) unless *run_exc* is given.
    """

    def _factory(**kwargs: Any) -> MagicMock:
        instance = MagicMock()

        def _run() -> None:
            import shinka.llm.client as shinka_llm_client

            observed.append(shinka_llm_client.TIMEOUT)
            if run_exc is not None:
                raise run_exc
            results_dir = Path(kwargs["evo_config"].results_dir)
            build_programs_db(results_dir / "programs.sqlite")

        instance.run.side_effect = _run
        return instance

    return MagicMock(side_effect=_factory)


def _timeout_run_args(llm_name: str, *extra: str) -> list[str]:
    """CLI args for a Shinka run against *llm_name*."""
    return [
        "run",
        "--version",
        "v1.0",
        "--llm",
        llm_name,
        "--dataset",
        "train-small",
        "--backend",
        "shinka",
        "--iterations",
        str(_ITERATIONS),
        *extra,
    ]


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_llm_timeout_set_and_restored(project_with_prereqs: dict[str, Path]) -> None:
    """An LLM registered with timeout_s=300 → TIMEOUT is 300 during the
    engine run and restored to the previous value afterwards."""
    import shinka.llm.client as shinka_llm_client

    _register_local_llm(project_with_prereqs["global_db_path"], name="slow-llm", timeout_s=300)
    original = shinka_llm_client.TIMEOUT
    observed: list[Any] = []

    result, _cls, _run_id = _invoke_with_mocks(
        _timeout_run_args("slow-llm"),
        project_with_prereqs["root"],
        project_with_prereqs["global_db_path"],
        mock_runner_cls=_make_timeout_probe_runner(observed),
    )

    assert result.exit_code == 0, _get_all_output(result)
    assert observed == [300]
    assert original == shinka_llm_client.TIMEOUT


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_llm_timeout_restored_when_engine_raises(
    project_with_prereqs: dict[str, Path],
) -> None:
    """The previous TIMEOUT is restored even when the engine run crashes."""
    import shinka.llm.client as shinka_llm_client

    _register_local_llm(project_with_prereqs["global_db_path"], name="slow-llm", timeout_s=300)
    original = shinka_llm_client.TIMEOUT
    observed: list[Any] = []

    result, _cls, _run_id = _invoke_with_mocks(
        _timeout_run_args("slow-llm"),
        project_with_prereqs["root"],
        project_with_prereqs["global_db_path"],
        mock_runner_cls=_make_timeout_probe_runner(observed, run_exc=RuntimeError("boom")),
    )

    assert result.exit_code != 0
    assert observed == [300]
    assert original == shinka_llm_client.TIMEOUT


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_no_llm_timeout_global_untouched(project_with_prereqs: dict[str, Path]) -> None:
    """No timeout_s anywhere → the module global is never touched (shinka's
    default stays in force for the run)."""
    import shinka.llm.client as shinka_llm_client

    original = shinka_llm_client.TIMEOUT
    observed: list[Any] = []

    result, _cls, _run_id = _invoke_with_mocks(
        _timeout_run_args("test-llm"),  # project fixture LLM: no timeout_s
        project_with_prereqs["root"],
        project_with_prereqs["global_db_path"],
        mock_runner_cls=_make_timeout_probe_runner(observed),
    )

    assert result.exit_code == 0, _get_all_output(result)
    assert observed == [original]
    assert original == shinka_llm_client.TIMEOUT


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_ensemble_llm_timeout_max_wins(tmp_path: Path, global_db_path: Path) -> None:
    """Mixed member timeouts (120/600/unset) resolve to the max (600) —
    conservative: the slowest member is never truncated."""
    members = [
        EnsembleMember(llm_name="m-a"),
        EnsembleMember(llm_name="m-b"),
        EnsembleMember(llm_name="m-c"),
    ]
    spec = _ensemble_spec(
        tmp_path,
        global_db_path,
        members,
        timeouts={"m-a": 120, "m-b": 600},
    )

    config = ShinkaBackend().build_config(spec)

    assert config["llm_timeout"] == 600


@pytest.mark.integration
@pytest.mark.shinkaevolve
def test_shinka_dry_run_surfaces_llm_timeout(project_with_prereqs: dict[str, Path]) -> None:
    """--dry-run shows the resolved llm_timeout without constructing the
    engine (honest display, R2/#260)."""
    _register_local_llm(project_with_prereqs["global_db_path"], name="slow-llm", timeout_s=300)

    result, mock_runner_cls, _run_id = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "slow-llm",
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
    assert "llm_timeout" in output
    assert "300" in output
    # Dry-run has no side effects: the engine was never constructed.
    assert mock_runner_cls.call_count == 0
