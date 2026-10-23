"""L2 integration tests for ``revolver run`` commands.

Tests the CLI commands end-to-end through Typer's CliRunner with real
SQLite databases (project + global) in ``tmp_path``. OpenEvolveRunner
and TokenCountingProxy are mocked at the infra boundary.

Traceable to: val-integration-tests.md section 2.5 (13 scenarios).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.project import init_project
from revolver.infra.backends.openevolve import RunOutput
from revolver.infra.db import (
    add_ensemble_member,
    get_global_db_at,
    get_project_db,
    insert_ensemble,
)
from revolver.infra.store import REVOLVER_DIR
from revolver.infra.token_proxy import TokenUsage as ProxyTokenUsage

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Counter for unique run/solution IDs in tests
_id_counter = 0


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
    """Extract and parse the first JSON object/array from CLI output.

    CliRunner mixes stdout and stderr, so we find the JSON portion
    by looking for the first '{' or '[' and parsing from there.
    """
    output = getattr(result, "output", "")
    # Find the start of JSON (first { or [)
    for i, ch in enumerate(output):
        if ch in ("{", "["):
            # Try to parse from this position
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(output, i)
            return obj
    msg = f"No JSON found in output: {output[:200]}"
    raise ValueError(msg)


# ── Fixtures ────────────────────────────────────────────────────────────────


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
    """Create a problem version in the project."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    shutil.copy2(fixtures_dir / "evaluator_simple.py", project_root / "evaluator.py")
    shutil.copy2(
        fixtures_dir / "initial_program_simple.py",
        project_root / "initial_program.py",
    )
    shutil.copy2(fixtures_dir / "config_simple.yaml", project_root / "config.yaml")

    from revolver.core.problem import create_version

    create_version(tag=tag, message=f"Version {tag}", project_root=project_root)


def _register_dataset(
    project_root: Path,
    dataset_dir: Path,
    name: str = "train-small",
    split: str | None = "train",
    compatible_with: list[str] | None = None,
) -> None:
    """Register a dataset in the project."""
    from revolver.core.dataset import register_dataset

    register_dataset(
        project_root=project_root,
        name=name,
        path=dataset_dir,
        split=split,
        compatible_with=compatible_with,
    )


def _register_llm(
    global_db_path: Path,
    name: str = "test-llm",
    model: str = "gpt-4",
    source: str = "remote",
    base_url: str | None = "http://localhost:11434/v1",
) -> None:
    """Register an LLM in the global database."""
    conn = get_global_db_at(global_db_path)
    try:
        conn.execute(
            "INSERT INTO llms (name, provider, model, source, base_url, "
            "api_key_env, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                "openai",
                model,
                source,
                base_url,
                None,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _make_mock_runner() -> MagicMock:
    """Create a mock OpenEvolveRunner that returns a successful run."""
    mock_runner_instance = MagicMock()
    mock_runner_instance.run.return_value = RunOutput(
        best_score=0.95,
        best_program="def solve(): pass",
        output_dir=None,
    )
    return mock_runner_instance


def _make_mock_proxy(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> MagicMock:
    """Create a mock TokenCountingProxy."""
    mock_proxy = MagicMock()
    mock_proxy.start.return_value = "http://127.0.0.1:9999"
    mock_proxy.stop.return_value = ProxyTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return mock_proxy


@pytest.fixture()
def project_with_prereqs(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> dict[str, Path]:
    """Set up a project with problem version, LLM, and dataset for run tests."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(tmp_project, dataset_dir, compatible_with=["v1.0"])
    _register_llm(global_db_path, base_url="http://localhost:11434/v1")
    return {
        "root": tmp_project,
        "dataset_dir": dataset_dir,
        "global_db_path": global_db_path,
    }


@pytest.fixture()
def mock_global_db(
    global_db_path: Path,
) -> Generator[Path, None, None]:
    """Patch get_global_db so the CLI opens connections to our temp DB."""
    with patch(
        "revolver.core.run.get_global_db",
        side_effect=lambda: get_global_db_at(global_db_path),
    ):
        yield global_db_path


def _invoke_with_cwd(args: list[str], cwd: Path) -> object:
    """Invoke the CLI with a patched working directory."""
    with patch("pathlib.Path.cwd", return_value=cwd):
        return runner.invoke(app, args, catch_exceptions=False)


def _next_ids() -> tuple[str, str]:
    """Generate unique run and solution IDs for tests."""
    global _id_counter
    _id_counter += 1
    return (
        f"run-20260315-{_id_counter:06d}",
        f"sol-20260315-{_id_counter:06d}",
    )


def _invoke_with_mocks(
    args: list[str],
    cwd: Path,
    global_db_path: Path,
    mock_runner: MagicMock | None = None,
    mock_proxy: MagicMock | None = None,
) -> object:
    """Invoke CLI with mocked OpenEvolveRunner, TokenCountingProxy, and global DB."""
    if mock_runner is None:
        mock_runner = _make_mock_runner()
    if mock_proxy is None:
        mock_proxy = _make_mock_proxy()

    mock_runner_cls = MagicMock(return_value=mock_runner)
    mock_proxy_cls = MagicMock(return_value=mock_proxy)

    run_id, sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=cwd),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=run_id),
        patch("revolver.core.run.generate_solution_id", return_value=sol_id),
        patch("revolver.infra.backends.openevolve.count_valid_programs", return_value=10),
    ):
        return runner.invoke(app, args, catch_exceptions=False)


# ── Test 1: run — valid config, mocked OpenEvolve (FR-RUN-001, 005..010) ───


@pytest.mark.integration
def test_run_valid_config(project_with_prereqs: dict[str, Path]) -> None:
    """Valid config, mocked OpenEvolve: run dir, DB entries, lineage, env vars."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        ["run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small"],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify DB entries: run record exists
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT * FROM runs WHERE status = 'completed'")
        runs = cursor.fetchall()
        assert len(runs) >= 1, "Expected at least 1 completed run in DB"

        # Verify solution record exists
        cursor = conn.execute("SELECT * FROM solutions")
        solutions = cursor.fetchall()
        assert len(solutions) >= 1, "Expected at least 1 solution in DB"
    finally:
        conn.close()

    # Verify run dir was created
    runs_dir = root / REVOLVER_DIR / "runs"
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("run-")]
    assert len(run_dirs) >= 1, "Expected at least 1 run directory"

    # Verify output contains run info
    assert "run-" in output
    assert "v1.0" in output


# ── Test 2: run --alias (FR-RUN-012) ────────────────────────────────────────


@pytest.mark.integration
def test_run_with_alias(project_with_prereqs: dict[str, Path]) -> None:
    """Solution alias set on completion."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--alias",
            "my-best-solution",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify alias in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT alias FROM solutions WHERE alias IS NOT NULL")
        row = cursor.fetchone()
        assert row is not None, "Expected solution with alias"
        assert row[0] == "my-best-solution"
    finally:
        conn.close()

    assert "my-best-solution" in output


# ── Test 3: run --dry-run (FR-RUN-023) ─────────────────────────────────────


@pytest.mark.integration
def test_run_dry_run(project_with_prereqs: dict[str, Path]) -> None:
    """Config displayed, no run launched."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--dry-run",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "dry-run" in output.lower()

    # Verify NO run was created in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM runs")
        count = cursor.fetchone()[0]
        assert count == 0, f"Expected 0 runs in DB, got {count}"
    finally:
        conn.close()


# ── Test 3b: snapshot config re-validation at run entry (U5, S17a-11) ───────


# The U5 re-validation is exercised with the backend's is_available /
# validate_config patched: the CI main test job has NO openevolve install,
# where the availability gate (correctly) skips re-validation — so the real
# validate_oe_config leg lives in tests/integration/test_run_oe.py (the
# OE-installed CI step) and THIS test asserts Revolver's warning plumbing
# (emission at run/--dry-run/resume, warn-only, availability gate)
# deterministically on any env.
_U5_IS_AVAILABLE = "revolver.infra.backends.openevolve.OpenEvolveBackend.is_available"
_U5_VALIDATE = "revolver.infra.backends.openevolve.OpenEvolveBackend.validate_config"
_U5_FINDINGS = [
    "Unknown OE config key 'population_size' at top level. "
    "Did you mean 'database.population_size'?"
]


@pytest.mark.integration
def test_run_revalidates_snapshot_config_warns(
    project_with_prereqs: dict[str, Path],
) -> None:
    """U5 (S17a-11): snapshot config.yaml re-validated warn-only at run entry.

    Backend validation is stubbed (see the module comment above) so every
    leg is deterministic without an openevolve install: findings warn on
    stderr at ``--dry-run``, launch, and resume — and the run proceeds; zero
    findings stay silent; an unavailable backend skips validation entirely.
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # (a) --dry-run warns (re-validation runs before build_config, which is
    # itself before the dry-run early return).
    with (
        patch(_U5_IS_AVAILABLE, return_value=(True, None)),
        patch(_U5_VALIDATE, return_value=_U5_FINDINGS) as mock_validate,
    ):
        result = _invoke_with_mocks(
            [
                "run",
                "--version",
                "v1.0",
                "--llm",
                "test-llm",
                "--dataset",
                "train-small",
                "--dry-run",
            ],
            cwd=root,
            global_db_path=global_db_path,
        )
    assert mock_validate.called  # the warning came from the stub, not a real import
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "snapshot config.yaml" in output
    assert "population_size" in output

    # (b) A real (mocked) launch warns too — and proceeds (warn-only). The
    # --json payload still parses from stdout: the warning is stderr-only.
    with (
        patch(_U5_IS_AVAILABLE, return_value=(True, None)),
        patch(_U5_VALIDATE, return_value=_U5_FINDINGS) as mock_validate,
    ):
        result = _invoke_with_mocks(
            [
                "--json",
                "run",
                "--version",
                "v1.0",
                "--llm",
                "test-llm",
                "--dataset",
                "train-small",
            ],
            cwd=root,
            global_db_path=global_db_path,
        )
    assert mock_validate.called
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "snapshot config.yaml" in output
    parent_run_id = _parse_json_output(result)["run_id"]

    # (c) Resume warns as well (same snapshot dir re-validated).
    checkpoint_dir = (
        root / REVOLVER_DIR / "runs" / parent_run_id / "oe-output" / "checkpoints" / "checkpoint_5"
    )
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    resume_run_id, resume_sol_id = _next_ids()
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch(
            "revolver.infra.backends.openevolve.OpenEvolveRunner",
            MagicMock(return_value=_make_mock_runner()),
        ),
        patch("revolver.core.run.TokenCountingProxy", MagicMock(return_value=_make_mock_proxy())),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=resume_run_id),
        patch("revolver.core.run.generate_solution_id", return_value=resume_sol_id),
        patch(_U5_IS_AVAILABLE, return_value=(True, None)),
        patch(_U5_VALIDATE, return_value=_U5_FINDINGS) as mock_validate,
    ):
        result = runner.invoke(app, ["run", "resume", parent_run_id], catch_exceptions=False)
    assert mock_validate.called
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "snapshot config.yaml" in output

    # (d) A clean snapshot config (zero findings) warns nothing — the
    # availability gate was passed, so silence means "no findings".
    with (
        patch(_U5_IS_AVAILABLE, return_value=(True, None)),
        patch(_U5_VALIDATE, return_value=[]) as mock_validate,
    ):
        result = _invoke_with_mocks(
            [
                "run",
                "--version",
                "v1.0",
                "--llm",
                "test-llm",
                "--dataset",
                "train-small",
                "--dry-run",
            ],
            cwd=root,
            global_db_path=global_db_path,
        )
    assert mock_validate.called
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "snapshot config.yaml" not in output

    # (e) Unavailable backend → re-validation is skipped silently (the CI
    # no-openevolve behaviour, encoded explicitly).
    with (
        patch(_U5_IS_AVAILABLE, return_value=(False, "install hint")),
        patch(_U5_VALIDATE, return_value=_U5_FINDINGS) as mock_validate,
    ):
        result = _invoke_with_mocks(
            [
                "run",
                "--version",
                "v1.0",
                "--llm",
                "test-llm",
                "--dataset",
                "train-small",
                "--dry-run",
            ],
            cwd=root,
            global_db_path=global_db_path,
        )
    assert not mock_validate.called  # gated off before validation
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "snapshot config.yaml" not in output


# ── Selection strategy validation + --llm-weight on OpenEvolve (S17) ────────


def _register_oe_ensemble(global_db_path: Path, weights: tuple[float, float]) -> None:
    """Register a 2-member OE ensemble (``gpt4o`` + ``claude``) with *weights*.

    ``test-llm`` already exists from the fixture (model ``gpt-4``); this adds a
    second distinct-model LLM so the two members map to distinct
    ``llm.models[].name`` entries.
    """
    _register_llm(global_db_path, name="claude", model="claude-3-5-sonnet")
    _register_ensemble(
        global_db_path,
        "oe-ensemble",
        [
            {"llm_name": "test-llm", "weight": weights[0]},
            {"llm_name": "claude", "weight": weights[1]},
        ],
    )


@pytest.mark.integration
def test_run_selection_ucb_rejected_on_oe(
    project_with_prereqs: dict[str, Path],
) -> None:
    """--selection ucb on OpenEvolve exits 1 naming weighted (S17-18/23, A2/A4)."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]
    _register_oe_ensemble(global_db_path, (0.8, 0.2))

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "oe-ensemble",
            "--dataset",
            "train-small",
            "--backend",
            "openevolve",
            "--selection",
            "ucb",
            "--dry-run",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "ucb" in output.lower()
    # The error names the OE-supported strategy (fixed) so the user knows what
    # to use — OE's static weighted sampler under the neutral vocabulary.
    assert "fixed" in output.lower()
    assert "openevolve" in output.lower()


@pytest.mark.integration
def test_run_selection_fixed_accepted_on_oe(
    project_with_prereqs: dict[str, Path],
) -> None:
    """--selection fixed is accepted on OpenEvolve (implicit weighted mode)."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]
    _register_oe_ensemble(global_db_path, (0.8, 0.2))

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "oe-ensemble",
            "--dataset",
            "train-small",
            "--backend",
            "openevolve",
            "--selection",
            "fixed",
            "--dry-run",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"


@pytest.mark.integration
def test_run_llm_weight_overrides_oe_ensemble(
    project_with_prereqs: dict[str, Path],
) -> None:
    """--llm-weight patches llm.models[].weight, not the registry weight (S17-22/23)."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]
    # Registry weights: test-llm=0.5, claude=0.5.
    _register_oe_ensemble(global_db_path, (0.5, 0.5))

    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "oe-ensemble",
            "--dataset",
            "train-small",
            "--backend",
            "openevolve",
            "--llm-weight",
            "test-llm=0.9",
            "--llm-weight",
            "claude=0.1",
            "--dry-run",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert isinstance(data, dict)
    resolved = data["resolved_config"]
    models = resolved["llm_models"]
    by_name = {m["name"]: m["weight"] for m in models}
    # Overrides win over the registry 0.5/0.5. Member LLM models: test-llm →
    # gpt-4 (fixture default), claude → claude-3-5-sonnet.
    assert by_name["gpt-4"] == 0.9
    assert by_name["claude-3-5-sonnet"] == 0.1


@pytest.mark.integration
def test_run_llm_weight_unknown_member_rejected(
    project_with_prereqs: dict[str, Path],
) -> None:
    """--llm-weight naming a non-member exits 1 (not a silent no-op; PR #232)."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]
    _register_oe_ensemble(global_db_path, (0.5, 0.5))  # members: test-llm, claude

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "oe-ensemble",
            "--dataset",
            "train-small",
            "--backend",
            "openevolve",
            "--llm-weight",
            "not-a-member=0.9",
            "--dry-run",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "not-a-member" in output
    # The error lists the valid member names.
    assert "test-llm" in output and "claude" in output


@pytest.mark.integration
def test_run_llm_weight_on_single_llm_rejected(
    project_with_prereqs: dict[str, Path],
) -> None:
    """--llm-weight on a single-LLM run exits 1 (no members to weight)."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--llm-weight",
            "test-llm=0.9",
            "--dry-run",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "--llm-weight" in output and "ensemble" in output.lower()


# ── Test 4: run — unknown LLM name → exit code 1 (FR-RUN-001) ──────────────


@pytest.mark.integration
def test_run_unknown_llm(project_with_prereqs: dict[str, Path]) -> None:
    """Unknown LLM name results in exit code 1."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "nonexistent-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"
    output = _get_all_output(result)
    assert "not found" in output.lower()


# ── Test 5: run — dataset integrity failure → exit code 2 (FR-RUN-004) ─────


@pytest.mark.integration
def test_run_dataset_integrity_failure(project_with_prereqs: dict[str, Path]) -> None:
    """Dataset integrity failure results in exit code 2."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]
    dataset_dir = project_with_prereqs["dataset_dir"]

    # Tamper with an instance file to cause integrity mismatch
    tampered_file = dataset_dir / "instance_001.json"
    tampered_file.write_text(
        json.dumps({"id": 1, "value": 9999, "tampered": True}),
        encoding="utf-8",
    )

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"
    output = _get_all_output(result)
    assert "integrity" in output.lower()


# ── Test 6: run — dataset split=eval → warning on stderr (FR-RUN-002) ──────


@pytest.mark.integration
def test_run_dataset_split_eval_warning(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> None:
    """Dataset split=eval produces a warning on stderr, run proceeds."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(
        tmp_project, dataset_dir, name="eval-ds", split="eval", compatible_with=["v1.0"]
    )
    _register_llm(global_db_path, base_url="http://localhost:11434/v1")

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "eval-ds",
        ],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "warning" in output.lower()
    assert "eval" in output.lower()


# ── Test 7: run — dataset incompatible with version → warning (FR-RUN-003) ──


@pytest.mark.integration
def test_run_dataset_incompatible_warning(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> None:
    """Dataset incompatible with version produces a warning on stderr."""
    _create_problem_version(tmp_project, "v1.0")
    # Insert a v2.0 problem version directly in DB (skip file copy/hash
    # to avoid duplicate hash error from identical fixtures)
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
            ("v2.0", "hash-v2-fake", "Version v2.0", datetime.now(UTC).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    # Register dataset compatible with v2.0 (not v1.0)
    _register_dataset(tmp_project, dataset_dir, name="incompat-ds", compatible_with=["v2.0"])
    _register_llm(global_db_path, base_url="http://localhost:11434/v1")

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "incompat-ds",
        ],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "warning" in output.lower()
    assert "compatible" in output.lower()


# ── Test 8: run — completion with tokens (FR-RUN-028, 029) ─────────────────


@pytest.mark.integration
def test_run_with_token_usage(project_with_prereqs: dict[str, Path]) -> None:
    """Token usage displayed and stored in DB on completion."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy(prompt_tokens=1500, completion_tokens=3000)

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
        mock_runner=mock_runner,
        mock_proxy=mock_proxy,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify tokens displayed
    assert "1500" in output
    assert "3000" in output

    # Verify tokens stored in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT prompt_tokens, completion_tokens FROM runs")
        row = cursor.fetchone()
        assert row is not None, "Expected run with tokens in DB"
        assert row[0] == 1500
        assert row[1] == 3000
    finally:
        conn.close()


# ── Test 9: run — cost is never displayed, even with pricing (S15 / #300) ──


@pytest.mark.integration
def test_run_no_cost_displayed(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> None:
    """Cost is not reported (S15 / #300, pricing removed in S16 / #203):
    tokens are shown, cost never is."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(tmp_project, dataset_dir, compatible_with=["v1.0"])
    _register_llm(
        global_db_path,
        name="test-llm",
        base_url="http://localhost:11434/v1",
    )

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy(prompt_tokens=1000, completion_tokens=2000)

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=tmp_project,
        global_db_path=global_db_path,
        mock_runner=mock_runner,
        mock_proxy=mock_proxy,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Tokens are still shown ...
    assert "1000" in output
    assert "2000" in output
    # ... but cost is never reported (#300).
    assert "cost" not in output.lower()
    assert "$" not in output
    assert "estimated_cost" not in output


# ── Test 10: run — post-run eval on train set (FR-RUN-019, 020) ─────────────


@pytest.mark.integration
def test_run_post_run_evaluation(project_with_prereqs: dict[str, Path]) -> None:
    """Post-run evaluation invoked for rank-1 program."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy()
    mock_runner_cls = MagicMock(return_value=mock_runner)
    mock_proxy_cls = MagicMock(return_value=mock_proxy)
    eval_run_id, eval_sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation") as mock_eval,
        patch("revolver.core.run.generate_run_id", return_value=eval_run_id),
        patch("revolver.core.run.generate_solution_id", return_value=eval_sol_id),
    ):
        result = runner.invoke(
            app,
            [
                "run",
                "--version",
                "v1.0",
                "--llm",
                "test-llm",
                "--dataset",
                "train-small",
            ],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify _post_run_evaluation was called
    mock_eval.assert_called_once()
    call_kwargs = mock_eval.call_args
    # Should be called with proj_conn, run_id, solution_id, etc.
    assert call_kwargs is not None


# ── Test 11: run list — after 2 runs, both listed, filterable (FR-RUN-021) ──


@pytest.mark.integration
def test_run_list_after_two_runs(project_with_prereqs: dict[str, Path]) -> None:
    """After 2 runs, both listed with status, filterable."""
    root = project_with_prereqs["root"]

    # Insert 2 runs directly in DB to avoid timestamp collision
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        for i, rid in enumerate(["run-20260315-100001", "run-20260315-100002"]):
            conn.execute(
                "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
                "problem_hash, dataset_hash, llm_model, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    "v1.0",
                    "test-llm",
                    "train-small",
                    10,
                    f"hash-{i}",
                    f"dhash-{i}",
                    "gpt-4",
                    "completed",
                    f"2026-03-15T10:00:0{i + 1}",
                ),
            )
        conn.commit()
    finally:
        conn.close()

    # List all runs
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(app, ["--json", "run", "list"], catch_exceptions=False)

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert len(data) >= 2, f"Expected at least 2 runs, got {len(data)}"

    # Test filter by version
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "list", "--version", "v1.0"],
            catch_exceptions=False,
        )

    data = _parse_json_output(result)
    assert len(data) >= 2
    for run_item in data:
        assert run_item["problem_version"] == "v1.0"

    # Test filter by status
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "list", "--status", "completed"],
            catch_exceptions=False,
        )

    data = _parse_json_output(result)
    assert len(data) >= 2
    for run_item in data:
        assert run_item["status"] == "completed"


# ── Test 12: run info — full details (FR-RUN-022) ──────────────────────────


@pytest.mark.integration
def test_run_info_full_details(project_with_prereqs: dict[str, Path]) -> None:
    """Full details: lineage, tokens, solution, stored programs."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy(prompt_tokens=500, completion_tokens=1000)

    # Launch a run first
    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
        mock_runner=mock_runner,
        mock_proxy=mock_proxy,
    )
    assert result.exit_code == 0
    run_data = _parse_json_output(result)
    run_id = run_data["run_id"]

    # Now get info
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
    ):
        result = runner.invoke(
            app,
            ["--json", "run", "info", run_id],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    info = _parse_json_output(result)
    assert info["run_id"] == run_id
    assert info["problem_version"] == "v1.0"
    assert info["llm"] == "test-llm"
    assert info["dataset"] == "train-small"
    assert info["status"] == "completed"

    # Verify lineage hashes present
    assert "problem_hash" in info
    assert "dataset_hash" in info
    assert "llm_model" in info

    # Verify token usage breakdown (prompt/completion/total)
    assert info["token_usage"] is not None
    assert info["token_usage"]["prompt_tokens"] == 500
    assert info["token_usage"]["completion_tokens"] == 1000
    assert info["token_usage"]["total_tokens"] == 1500
    # Cost is not reported (S15 / #300): no cost key in --json output.
    assert "estimated_cost_usd" not in info["token_usage"]

    # Verify solutions
    assert len(info["solutions"]) >= 1
    assert info["solutions"][0]["rank"] == 1


# ── Test 12b: run info — token-honesty caveat in human output (S15-03) ─────


@pytest.mark.integration
def test_run_info_token_caveat(project_with_prereqs: dict[str, Path]) -> None:
    """Human run info shows the token breakdown and the #300 honesty caveat,
    and never a cost figure."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy(prompt_tokens=500, completion_tokens=1000)

    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
        mock_runner=mock_runner,
        mock_proxy=mock_proxy,
    )
    assert result.exit_code == 0
    run_id = _parse_json_output(result)["run_id"]

    # Human (non-JSON) run info
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
    ):
        result = runner.invoke(app, ["run", "info", run_id], catch_exceptions=False)

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # Token breakdown present ...
    assert "500" in output
    assert "1000" in output
    # ... honesty caveat present ...
    assert "not counted" in output
    assert "provider console" in output
    # ... and no cost figure anywhere.
    assert "$" not in output
    assert "estimated_cost" not in output


# ── Test 12c: run info — bridge token under-count caveat (A4 / #316) ────────


@pytest.mark.integration
def test_run_info_local_token_caveat(project_with_prereqs: dict[str, Path]) -> None:
    """`run info` on a `--source local` run appends the bridge token
    under-count caveat after the standard #300 token-honesty note."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # A local-source LLM (e.g. a subscription-backed local OpenAI-compatible shim).
    _register_llm(
        global_db_path,
        name="bridge-local",
        model="claude-via-bridge",
        source="local",
        base_url="http://localhost:11434/v1",
    )

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy(prompt_tokens=2, completion_tokens=4)

    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "bridge-local",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
        mock_runner=mock_runner,
        mock_proxy=mock_proxy,
    )
    assert result.exit_code == 0
    run_id = _parse_json_output(result)["run_id"]

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.cli.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
    ):
        result = runner.invoke(app, ["run", "info", run_id], catch_exceptions=False)

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # The bridge under-count caveat is present ...
    assert "under-report token usage" in output
    assert "Anthropic console" in output
    # ... alongside (after) the existing #300 token-honesty caveat ...
    assert "not counted" in output
    # ... and still no cost figure.
    assert "$" not in output


@pytest.mark.integration
def test_run_info_remote_no_token_caveat(project_with_prereqs: dict[str, Path]) -> None:
    """`run info` on a `--source remote` run shows the standard #300 caveat
    but NOT the bridge token under-count caveat (the default `test-llm`
    fixture is registered as remote)."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy(prompt_tokens=500, completion_tokens=1000)

    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
        mock_runner=mock_runner,
        mock_proxy=mock_proxy,
    )
    assert result.exit_code == 0
    run_id = _parse_json_output(result)["run_id"]

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.cli.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
    ):
        result = runner.invoke(app, ["run", "info", run_id], catch_exceptions=False)

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # The standard #300 token-honesty caveat is still present ...
    assert "not counted" in output
    # ... but the bridge under-count caveat is NOT shown on a remote run.
    assert "under-report token usage" not in output


# ── Test 12e: run info — honest dual-score display (S18 / U11, FR-RUN-055) ──


@pytest.mark.integration
def test_run_info_honest_score_labels(
    project_with_prereqs: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run info` renders the engine best labeled "engine, single eval" NEXT
    TO the post-run training-eval mean labeled with its coverage
    (instances_valid/instances_total — FR-RUN-053); the bare engine number
    never appears without its label; JSON carries both fields (S18-06)."""
    from revolver.infra.db import insert_eval_instance, insert_eval_metadata

    # Keep the pre-flight eval from emitting the once-per-process
    # "[revolver] numeric thread cap..." stderr line: its leading '[' breaks
    # _parse_json_output when this test is the first launch in the process.
    monkeypatch.setenv("REVOLVER_EVAL_NUM_THREADS", "0")

    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Launch a run (engine best_score=0.95; post-run eval patched out).
    result = _invoke_with_mocks(
        ["--json", "run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small"],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0
    run_data = _parse_json_output(result)
    run_id = run_data["run_id"]
    solution_id = run_data["solution"]["solution_id"]

    # Persist a post-run training eval for the rank-1 solution, as the
    # S18-05 evaluate_solution path would: 2 solved instances contribute to
    # the mean (0.5, 0.7 -> 0.6), 1 failed instance does not (coverage 2/3).
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        insert_eval_metadata(
            conn,
            eval_id="eval-20260705-120000",
            solution_id=solution_id,
            dataset_name="train-small",
            instance_count=3,
            instances_solved=2,
            eval_time_s=1.0,
            user_aggregates=None,
            evaluated_at=datetime.now(UTC),
        )
        for instance_id, value, status, error in (
            ("instance_001.json", 0.5, "solved", None),
            ("instance_002.json", 0.7, "solved", None),
            ("instance_003.json", None, "failed", "boom"),
        ):
            insert_eval_instance(
                conn,
                eval_id="eval-20260705-120000",
                instance_id=instance_id,
                metric_name="combined_score" if value is not None else "_status",
                value=value,
                status=status,
                error_message=error,
                compute_time_s=0.1,
            )
        conn.commit()
    finally:
        conn.close()

    # Add a rank-2 program with an engine score to the manifest so the
    # programs detail table renders — its scores must carry the same
    # "engine, single eval" label (the never-bare regex below guards it).
    from revolver.infra.store import read_run_manifest, write_run_manifest

    manifest = read_run_manifest(root, run_id) or {"run_id": run_id}
    manifest["programs"] = [{"rank": 2, "score": 0.95, "file": "programs/rank-2.py"}]
    write_run_manifest(root, run_id, manifest)

    # Human output: both numbers rendered, with distinct labels.
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.cli.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
    ):
        result = runner.invoke(
            app, ["run", "info", run_id], catch_exceptions=False, env={"COLUMNS": "200"}
        )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "0.9500 (engine, single eval)" in output
    assert "0.6000 (mean, 2/3 instances)" in output
    # The inflated engine number NEVER renders bare (FR-RUN-055).
    assert re.search(r"0\.9500(?! \(engine, single eval\))", output) is None

    # JSON output carries both fields.
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(app, ["--json", "run", "info", run_id], catch_exceptions=False)
    assert result.exit_code == 0
    info = _parse_json_output(result)
    assert info["solutions"][0]["best_score"] == 0.95
    assert info["post_eval_score"] == pytest.approx(0.6)
    assert info["post_eval_instances_valid"] == 2
    assert info["post_eval_instances_total"] == 3
    assert "run_best_score" in info


@pytest.mark.integration
def test_run_info_fallback_engine_label(project_with_prereqs: dict[str, Path]) -> None:
    """The #306 display-time fallback (rank-1 score <- engine run best) also
    carries the "engine, single eval" label — the engine number never renders
    bare — and stays display-only (no DB write; JSON keeps best_score null)."""
    from revolver.infra.db import insert_run, insert_solution
    from revolver.infra.store import create_run_dir, write_run_manifest

    root = project_with_prereqs["root"]
    run_id, solution_id = _next_ids()

    create_run_dir(root, run_id)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        insert_run(
            conn,
            run_id=run_id,
            problem_version="v1.0",
            llm="test-llm",
            dataset="train-small",
            iterations=5,
            problem_hash="hash-v1",
            dataset_hash="dataset-hash-1",
            llm_model="gpt-4",
            created_at=datetime.now(UTC),
            status="completed",
        )
        # Rank-1 solution with NO score (post-run eval skipped/failed).
        insert_solution(
            conn,
            solution_id=solution_id,
            run_id=run_id,
            rank=1,
            best_score=None,
            alias=None,
        )
    finally:
        conn.close()
    write_run_manifest(root, run_id, {"run_id": run_id, "programs": []})

    fake_backend = MagicMock()
    fake_backend.count_total.return_value = None
    fake_backend.count_evolved_children.return_value = 1
    fake_backend.read_progress.return_value = (5, 0.87)

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch("revolver.core.run.get_backend", return_value=fake_backend),
    ):
        result = runner.invoke(
            app, ["run", "info", run_id], catch_exceptions=False, env={"COLUMNS": "200"}
        )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # The fallback engine number renders with the label, never bare.
    assert "0.8700 (engine, single eval)" in output
    assert re.search(r"0\.8700(?! \(engine, single eval)", output) is None

    # Display-only (#306): the solution score stays null in JSON; the engine
    # number is carried by the labeled run_best_score field.
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch("revolver.core.run.get_backend", return_value=fake_backend),
    ):
        result = runner.invoke(app, ["--json", "run", "info", run_id], catch_exceptions=False)
    assert result.exit_code == 0
    info = _parse_json_output(result)
    assert info["solutions"][0]["best_score"] is None
    assert info["run_best_score"] == 0.87


# ── Test 13: run resume — existing checkpoint (FR-RUN-013, 024) ─────────────


@pytest.mark.integration
def test_run_resume(project_with_prereqs: dict[str, Path]) -> None:
    """New run from parent, wrapper copied."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Launch initial run
    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0
    parent_data = _parse_json_output(result)
    parent_run_id = parent_data["run_id"]

    # Create the expected checkpoint directory structure
    parent_run_dir = root / REVOLVER_DIR / "runs" / parent_run_id
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Resume the run with unique IDs
    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy()
    mock_runner_cls = MagicMock(return_value=mock_runner)
    mock_proxy_cls = MagicMock(return_value=mock_proxy)
    resume_run_id, resume_sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=resume_run_id),
        patch("revolver.core.run.generate_solution_id", return_value=resume_sol_id),
    ):
        result = runner.invoke(
            app,
            ["--json", "run", "resume", "--run", parent_run_id],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    resume_data = _parse_json_output(result)
    new_run_id = resume_data["run_id"]

    # Verify new run is different from parent
    assert new_run_id != parent_run_id

    # Verify resumed_from field
    assert resume_data.get("resumed_from") == parent_run_id

    # Verify DB has both runs
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM runs")
        count = cursor.fetchone()[0]
        assert count == 2, f"Expected 2 runs in DB, got {count}"

        # Verify resumed_from in DB
        cursor = conn.execute("SELECT resumed_from FROM runs WHERE id = ?", (new_run_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == parent_run_id
    finally:
        conn.close()

    # Verify wrapper was copied to new run dir
    new_run_dir = root / REVOLVER_DIR / "runs" / new_run_id
    assert new_run_dir.exists()


# ── Test 13b: run resume — positional RUN_ID (S16a-12, #319a) ───────────────


def _stage_parent_checkpoint(
    project_with_prereqs: dict[str, Path],
) -> tuple[Path, Path, str]:
    """Launch an initial run and stage a checkpoint so resume can proceed.

    Returns (root, global_db_path, parent_run_id).
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0
    parent_data = _parse_json_output(result)
    parent_run_id = parent_data["run_id"]

    # Create the expected checkpoint directory structure
    checkpoint_dir = (
        root / REVOLVER_DIR / "runs" / parent_run_id / "oe-output" / "checkpoints" / "checkpoint_5"
    )
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    return root, global_db_path, parent_run_id


def _invoke_resume(args: list[str], root: Path, global_db_path: Path) -> object:
    """Invoke ``run resume`` with the standard resume mocks."""
    mock_runner_cls = MagicMock(return_value=_make_mock_runner())
    mock_proxy_cls = MagicMock(return_value=_make_mock_proxy())
    resume_run_id, resume_sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=resume_run_id),
        patch("revolver.core.run.generate_solution_id", return_value=resume_sol_id),
    ):
        return runner.invoke(app, args, catch_exceptions=False)


@pytest.mark.integration
def test_run_resume_positional_run_id(project_with_prereqs: dict[str, Path]) -> None:
    """``run resume <id>`` accepts the run ID as a positional argument."""
    root, global_db_path, parent_run_id = _stage_parent_checkpoint(project_with_prereqs)

    result = _invoke_resume(
        ["--json", "run", "resume", parent_run_id],
        root,
        global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    resume_data = _parse_json_output(result)
    assert resume_data["run_id"] != parent_run_id
    assert resume_data.get("resumed_from") == parent_run_id


@pytest.mark.integration
def test_run_resume_option_compat(project_with_prereqs: dict[str, Path]) -> None:
    """``run resume --run <id>`` still works as a backward-compat alias."""
    root, global_db_path, parent_run_id = _stage_parent_checkpoint(project_with_prereqs)

    result = _invoke_resume(
        ["--json", "run", "resume", "--run", parent_run_id],
        root,
        global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    resume_data = _parse_json_output(result)
    assert resume_data["run_id"] != parent_run_id
    assert resume_data.get("resumed_from") == parent_run_id


@pytest.mark.integration
def test_run_resume_no_id_exits_1(project_with_prereqs: dict[str, Path]) -> None:
    """``run resume`` with no ID prints a clear error and exits 1."""
    root = project_with_prereqs["root"]

    result = _invoke_with_cwd(["run", "resume"], cwd=root)

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "run ID is required" in output


@pytest.mark.integration
def test_run_resume_ensemble_without_selection_warns(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Resuming an ensemble parent without --selection warns the reset is not silent.

    Ensemble selection levers are re-specified per resume, not inherited (DES-005
    §11); the warning makes the fallback-to-default explicit (PR-W1c review WARNING-2).
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]
    _register_oe_ensemble(global_db_path, (0.8, 0.2))  # members: test-llm, claude

    # Launch an ensemble parent (non-json so we can also read stderr later).
    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "oe-ensemble",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0, _get_all_output(result)
    parent_run_id = _parse_json_output(result)["run_id"]

    checkpoint_dir = (
        root / REVOLVER_DIR / "runs" / parent_run_id / "oe-output" / "checkpoints" / "checkpoint_5"
    )
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Resume WITHOUT --json/--quiet (warning is suppressed in quiet mode) and
    # WITHOUT --selection → expect the reset warning.
    result = _invoke_resume(
        ["run", "resume", parent_run_id],
        root,
        global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "without --selection" in output
    assert "re-specified" in output


@pytest.mark.integration
def test_run_resume_positional_wins_over_option(
    project_with_prereqs: dict[str, Path],
) -> None:
    """When both a positional RUN_ID and ``--run`` are given, the positional wins."""
    root, global_db_path, parent_run_id = _stage_parent_checkpoint(project_with_prereqs)

    # ``--run`` points at a non-existent id; if it were honoured the resume
    # would fail to resolve the parent, so a clean resume proves positional wins.
    result = _invoke_resume(
        ["--json", "run", "resume", parent_run_id, "--run", "does-not-exist"],
        root,
        global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    resume_data = _parse_json_output(result)
    assert resume_data.get("resumed_from") == parent_run_id


# ── Test 14: run info shows valid_iterations ─────────────────────────────


@pytest.mark.integration
def test_run_info_shows_valid_iterations(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run info shows valid_iterations when populated in DB."""
    root = project_with_prereqs["root"]

    # Insert a run with valid_iterations directly in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, created_at, "
            "valid_iterations) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-vi-001",
                "v1.0",
                "test-llm",
                "train-small",
                100,
                "hash-vi",
                "dhash-vi",
                "gpt-4",
                "completed",
                "2026-03-20T10:00:00",
                85,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Get info via CLI
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "info", "run-vi-001"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    info = _parse_json_output(result)
    assert info["run_id"] == "run-vi-001"
    assert info["valid_iterations"] == 85
    assert info["iterations"] == 100


# ── Test 15: run list shows valid column ─────────────────────────────────


@pytest.mark.integration
def test_run_list_shows_valid_iterations(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run list includes valid_iterations in JSON output."""
    root = project_with_prereqs["root"]

    # Insert two runs: one with valid_iterations, one without
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, created_at, "
            "valid_iterations) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-vl-001",
                "v1.0",
                "test-llm",
                "train-small",
                50,
                "hash-vl1",
                "dhash-vl1",
                "gpt-4",
                "completed",
                "2026-03-20T11:00:00",
                42,
            ),
        )
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-vl-002",
                "v1.0",
                "test-llm",
                "train-small",
                50,
                "hash-vl2",
                "dhash-vl2",
                "gpt-4",
                "completed",
                "2026-03-20T11:00:01",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # List runs via CLI
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "list"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    by_id = {r["run_id"]: r for r in data}

    assert by_id["run-vl-001"]["valid_iterations"] == 42
    assert by_id["run-vl-002"]["valid_iterations"] is None


# ── run delete --all tests (S8a-04, S8a-05) ────────────────────────────────


def _insert_run_directly(project_root: Path, run_id: str) -> None:
    """Insert a minimal run row directly into the project database."""
    db_path = project_root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                "v1.0",
                "test-llm",
                "train-small",
                10,
                f"hash-{run_id}",
                f"dhash-{run_id}",
                "gpt-4",
                "completed",
                "2026-03-20T10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_run_delete_all(project_with_prereqs: dict[str, Path]) -> None:
    """run delete --all --force removes all runs; run list returns empty."""
    root = project_with_prereqs["root"]

    # Insert 3 runs directly
    for i in range(1, 4):
        _insert_run_directly(root, f"run-del-all-{i:03d}")

    # Delete all with --force
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "delete", "--all", "--force"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert data["runs_deleted"] == 3
    assert data["status"] == "deleted"

    # Verify run list is now empty
    with patch("pathlib.Path.cwd", return_value=root):
        list_result = runner.invoke(
            app,
            ["--json", "run", "list"],
            catch_exceptions=False,
        )

    list_data = _parse_json_output(list_result)
    assert list_data == []


@pytest.mark.integration
def test_run_delete_all_no_force(project_with_prereqs: dict[str, Path]) -> None:
    """run delete --all without --force in JSON mode raises ValidationError."""
    root = project_with_prereqs["root"]

    # Insert a run so there is something to delete
    _insert_run_directly(root, "run-del-nf-001")

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "delete", "--all"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "--force" in output


@pytest.mark.integration
def test_run_delete_all_empty(project_with_prereqs: dict[str, Path]) -> None:
    """run delete --all --force with no runs returns no-op."""
    root = project_with_prereqs["root"]

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "delete", "--all", "--force"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert data["status"] == "no-op"


@pytest.mark.integration
def test_run_delete_all_with_id_error(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run delete --all <run_id> is mutually exclusive — should error."""
    root = project_with_prereqs["root"]

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["run", "delete", "--all", "run-some-id", "--force"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Cannot use --all with a specific run ID" in output


# ── Test: Smart default version — single version auto-selected (S8a-10) ─────


@pytest.mark.integration
def test_run_smart_default_version(project_with_prereqs: dict[str, Path]) -> None:
    """Single version auto-selected with notice when --version omitted."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        ["run", "--llm", "test-llm", "--dataset", "train-small", "--dry-run"],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "Using version v1.0 (only version)" in output
    assert "dry-run" in output.lower()


@pytest.mark.integration
def test_run_smart_default_version_multiple_error(
    tmp_project: Path, dataset_dir: Path, global_db_path: Path
) -> None:
    """Multiple versions → error listing available versions when --version omitted."""
    _create_problem_version(tmp_project, "v1.0")
    db_path = tmp_project / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
            ("v2.0", "fakehash-v2", "Version v2.0", "2026-03-22T10:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    _register_dataset(tmp_project, dataset_dir, compatible_with=["v1.0"])
    _register_llm(global_db_path)

    result = _invoke_with_mocks(
        ["run", "--llm", "test-llm", "--dataset", "train-small", "--dry-run"],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Multiple problem versions exist" in output
    assert "v1.0" in output
    assert "v2.0" in output
    assert "--version" in output


@pytest.mark.integration
def test_run_smart_default_version_no_versions_error(
    tmp_project: Path, dataset_dir: Path, global_db_path: Path
) -> None:
    """No problem versions → error pointing to 'problem version'."""
    _register_dataset(tmp_project, dataset_dir, compatible_with=[])
    _register_llm(global_db_path)

    result = _invoke_with_mocks(
        ["run", "--llm", "test-llm", "--dataset", "train-small", "--dry-run"],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "No problem versions found" in output
    assert "problem version" in output


@pytest.mark.integration
def test_run_smart_default_version_explicit_respected(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Explicit --version is always respected, even with smart defaults available."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--dry-run",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # Should NOT show smart default notice when explicit
    assert "Using version" not in output
    assert "dry-run" in output.lower()


# ── Test: Smart default dataset — single train dataset auto-selected (S8a-11) ─


@pytest.mark.integration
def test_run_smart_default_dataset(project_with_prereqs: dict[str, Path]) -> None:
    """Single train dataset auto-selected with notice when --dataset omitted."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        ["run", "--version", "v1.0", "--llm", "test-llm", "--dry-run"],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "Using dataset train-small (only train dataset)" in output
    assert "dry-run" in output.lower()


@pytest.mark.integration
def test_run_smart_default_dataset_multiple_error(
    tmp_project: Path, dataset_dir: Path, global_db_path: Path
) -> None:
    """Multiple train datasets → error listing them when --dataset omitted."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(tmp_project, dataset_dir, name="train-a", split="train")
    _register_dataset(tmp_project, dataset_dir, name="train-b", split="train")
    _register_llm(global_db_path)

    result = _invoke_with_mocks(
        ["run", "--version", "v1.0", "--llm", "test-llm", "--dry-run"],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Multiple train datasets exist" in output
    assert "train-a" in output
    assert "train-b" in output
    assert "--dataset" in output


@pytest.mark.integration
def test_run_smart_default_dataset_no_train_error(
    tmp_project: Path, dataset_dir: Path, global_db_path: Path
) -> None:
    """No train datasets → error pointing to 'dataset add --split train'."""
    _create_problem_version(tmp_project, "v1.0")
    _register_dataset(tmp_project, dataset_dir, name="eval-set", split="eval")
    _register_llm(global_db_path)

    result = _invoke_with_mocks(
        ["run", "--version", "v1.0", "--llm", "test-llm", "--dry-run"],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "No train datasets found" in output
    assert "dataset add --split train" in output


@pytest.mark.integration
def test_run_smart_default_dataset_explicit_respected(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Explicit --dataset is always respected, even with smart defaults available."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--dry-run",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    # Should NOT show smart default notice when explicit
    assert "Using dataset" not in output
    assert "dry-run" in output.lower()


@pytest.mark.integration
def test_run_smart_default_both(project_with_prereqs: dict[str, Path]) -> None:
    """Both version and dataset auto-selected when both omitted."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        ["run", "--llm", "test-llm", "--dry-run"],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "Using version v1.0 (only version)" in output
    assert "Using dataset train-small (only train dataset)" in output
    assert "dry-run" in output.lower()


# ── Test: run --dry-run --rewrite-mode (S10-09/10/11) ─────────────────────


@pytest.mark.integration
def test_run_dry_run_rewrite_mode(project_with_prereqs: dict[str, Path]) -> None:
    """--rewrite-mode with --dry-run injects rewrite settings into resolved config."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--dry-run",
            "--rewrite-mode",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "dry-run" in output.lower()

    # Verify NO run was created in DB (dry-run does not persist)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM runs")
        count = cursor.fetchone()[0]
        assert count == 0, f"Expected 0 runs in DB, got {count}"
    finally:
        conn.close()


# ── Tests: dry-run resolved config completeness (S12-04/05/06) ─────────────


@pytest.mark.integration
def test_run_dry_run_rewrite_mode_json_fields(
    project_with_prereqs: dict[str, Path],
) -> None:
    """--rewrite-mode --dry-run --json includes diff_based_evolution and max_code_length."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--dry-run",
            "--rewrite-mode",
            "--json",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert isinstance(data, dict)
    rc = data.get("resolved_config")
    assert rc is not None, "resolved_config missing from JSON output"
    # OE-exclusive keys live in backend_extras since S13 PR-C (ADR-007 D4)
    assert rc["backend"] == "openevolve"
    assert rc["backend_extras"]["diff_based_evolution"] is False
    assert rc["backend_extras"]["max_code_length"] == 50000


@pytest.mark.integration
def test_run_dry_run_config_override_json(
    project_with_prereqs: dict[str, Path],
) -> None:
    """--config-override with --dry-run --json includes config_overrides dict."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--dry-run",
            "--config-override",
            "max_code_length=30000",
            "--json",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert isinstance(data, dict)
    rc = data.get("resolved_config")
    assert rc is not None, "resolved_config missing from JSON output"
    assert rc["config_overrides"] == {"max_code_length": "30000"}
    # The override should also be applied to the actual config value
    # (OE-exclusive key → backend_extras since S13 PR-C, ADR-007 D4)
    assert rc["backend_extras"]["max_code_length"] == 30000


@pytest.mark.integration
def test_run_dry_run_ensemble_json(
    project_with_prereqs: dict[str, Path],
) -> None:
    """--dry-run --json with ensemble LLM includes llm_models array."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Register a second LLM for the ensemble
    _register_llm(global_db_path, name="test-llm-2", model="gpt-4-mini")

    # Create ensemble with two members
    _register_ensemble(
        global_db_path,
        "dry-run-ensemble",
        [
            {"llm_name": "test-llm", "weight": 0.7},
            {"llm_name": "test-llm-2", "weight": 0.3},
        ],
    )

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "dry-run-ensemble",
            "--dataset",
            "train-small",
            "--dry-run",
            "--json",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert isinstance(data, dict)
    rc = data.get("resolved_config")
    assert rc is not None, "resolved_config missing from JSON output"
    assert rc["llm_models"] is not None, "llm_models missing from resolved_config"
    assert isinstance(rc["llm_models"], list)
    assert len(rc["llm_models"]) == 2

    # Check member names and weights are present
    names = [m.get("name") for m in rc["llm_models"]]
    assert names == ["gpt-4", "gpt-4-mini"]
    weights = [m.get("weight") for m in rc["llm_models"]]
    assert weights == [0.7, 0.3]


# ── Zombie run detection tests (S10-13/14/15) ────────────────────────────────


def _insert_running_run(
    root: Path,
    run_id: str,
    *,
    pid: int | None = None,
    write_lock: bool = True,
) -> None:
    """Insert a run with status='running' into the DB, optionally create lock file."""
    from revolver.infra.store import write_run_lock

    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                "v1.0",
                "test-llm",
                "train-small",
                10,
                "hash-zombie",
                "dhash-zombie",
                "gpt-4",
                "running",
                "2026-03-28T10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if write_lock and pid is not None:
        write_run_lock(root, run_id, {"run_id": run_id, "pid": pid})


@pytest.mark.integration
def test_detect_zombie_runs_marks_dead_pid(
    project_with_prereqs: dict[str, Path],
) -> None:
    """A run with status=running and a dead PID is marked interrupted."""
    from revolver.core.run import detect_zombie_runs

    root = project_with_prereqs["root"]

    # Use PID 999999999 which should not exist
    _insert_running_run(root, "run-zombie-001", pid=999999999)

    zombies = detect_zombie_runs(project_root=root)

    assert zombies == ["run-zombie-001"]

    # Verify status was updated in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", ("run-zombie-001",)).fetchone()
        assert row is not None
        assert row[0] == "interrupted"
    finally:
        conn.close()

    # Verify lock file was removed
    lock_file = root / REVOLVER_DIR / "runs" / "locks" / "run-zombie-001.lock"
    assert not lock_file.exists()


@pytest.mark.integration
def test_detect_zombie_runs_no_false_positive(
    project_with_prereqs: dict[str, Path],
) -> None:
    """A run with status=running and a live PID is NOT marked interrupted."""
    import os

    from revolver.core.run import detect_zombie_runs

    root = project_with_prereqs["root"]

    # Use the current process PID — guaranteed to be alive
    _insert_running_run(root, "run-alive-001", pid=os.getpid())

    zombies = detect_zombie_runs(project_root=root)

    assert zombies == []

    # Verify status was NOT changed
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", ("run-alive-001",)).fetchone()
        assert row is not None
        assert row[0] == "running"
    finally:
        conn.close()


@pytest.mark.integration
def test_detect_zombie_runs_no_lock_file(
    project_with_prereqs: dict[str, Path],
) -> None:
    """A run with status=running but no lock file is marked interrupted."""
    from revolver.core.run import detect_zombie_runs

    root = project_with_prereqs["root"]

    # Insert run without lock file
    _insert_running_run(root, "run-nolck-001", write_lock=False)

    zombies = detect_zombie_runs(project_root=root)

    assert zombies == ["run-nolck-001"]

    # Verify status was updated
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", ("run-nolck-001",)).fetchone()
        assert row is not None
        assert row[0] == "interrupted"
    finally:
        conn.close()


@pytest.mark.integration
def test_run_list_detects_zombie(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run list auto-detects zombie runs and prints a warning."""
    root = project_with_prereqs["root"]

    # Insert a zombie run (dead PID)
    _insert_running_run(root, "run-zombie-list-001", pid=999999999)

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(app, ["run", "list"], catch_exceptions=False)

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "1 zombie run(s) detected" in output


@pytest.mark.integration
def test_run_cleanup_force(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run cleanup --force marks zombies and reports count."""
    root = project_with_prereqs["root"]

    _insert_running_run(root, "run-zombie-clnp-001", pid=999999999)

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["--json", "run", "cleanup", "--force"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    assert data["zombies_cleaned"] == 1
    assert "run-zombie-clnp-001" in data["run_ids"]


@pytest.mark.integration
def test_run_cleanup_no_zombies(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run cleanup --force with no zombies prints 'No zombie runs found'."""
    root = project_with_prereqs["root"]

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["run", "cleanup", "--force"],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "No zombie runs found" in output


# ── Ensemble helpers ───────────────────────────────────────────────────────────


def _register_ensemble(
    global_db_path: Path,
    ensemble_name: str,
    members: list[dict[str, object]],
) -> None:
    """Register an ensemble with members in the global database."""
    conn = get_global_db_at(global_db_path)
    try:
        insert_ensemble(conn, ensemble_name, datetime.now(UTC))
        for m in members:
            add_ensemble_member(
                conn,
                ensemble_name=ensemble_name,
                llm_name=str(m["llm_name"]),
                weight=float(m.get("weight", 1.0)),  # type: ignore[arg-type]
                temperature_override=m.get("temperature_override"),
                max_tokens_override=m.get("max_tokens_override"),
            )
    finally:
        conn.close()


# ── S11-10: Ensemble integration tests (L2) ──────────────────────────────────


@pytest.mark.integration
def test_run_start_single_llm_no_regression(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run start with single LLM still produces llm_type=single (no ensemble regression).

    Traceable to: sprint-011 L2 test_run_start_single_llm_no_regression.
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    # Verify DB: llm_type should be 'single'
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT llm_type, llm_snapshot FROM runs WHERE status = 'completed'"
        ).fetchone()
        assert row is not None
        assert row["llm_type"] == "single"
        # Single LLM snapshot should contain the model name
        assert row["llm_snapshot"] is not None
        snapshot = json.loads(row["llm_snapshot"])
        assert snapshot["type"] == "single"
        assert snapshot["model"] == "gpt-4"
    finally:
        conn.close()


@pytest.mark.integration
def test_run_start_with_ensemble(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run start with --llm pointing to an ensemble produces llm_type=ensemble.

    Traceable to: sprint-011 L2 test_run_start_with_ensemble.
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Register a second LLM for the ensemble
    _register_llm(global_db_path, name="llm-b", model="gpt-3.5-turbo")

    # Create ensemble with two members
    _register_ensemble(
        global_db_path,
        "test-ensemble",
        [
            {"llm_name": "test-llm", "weight": 0.8},
            {"llm_name": "llm-b", "weight": 0.2, "temperature_override": 0.5},
        ],
    )

    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-ensemble",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    run_id = data["run_id"]

    # Verify DB: llm_type should be 'ensemble'
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT llm, llm_type, llm_snapshot, llm_model FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert row["llm"] == "test-ensemble"
        assert row["llm_type"] == "ensemble"
        # llm_model should contain both model names
        assert "gpt-4" in row["llm_model"]
        assert "gpt-3.5-turbo" in row["llm_model"]
        # Snapshot should contain ensemble details
        snapshot = json.loads(row["llm_snapshot"])
        assert snapshot["type"] == "ensemble"
        assert snapshot["name"] == "test-ensemble"
        assert len(snapshot["members"]) == 2
    finally:
        conn.close()


@pytest.mark.integration
def test_run_info_ensemble_display(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run info for an ensemble run shows llm_type=ensemble and members in snapshot.

    Traceable to: sprint-011 L2 test_run_info_ensemble_display.
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Register a second LLM and an ensemble
    _register_llm(global_db_path, name="llm-b", model="gpt-3.5-turbo")
    _register_ensemble(
        global_db_path,
        "info-ensemble",
        [
            {"llm_name": "test-llm", "weight": 0.7},
            {"llm_name": "llm-b", "weight": 0.3},
        ],
    )

    # Launch ensemble run
    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "info-ensemble",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0, _get_all_output(result)
    run_data = _parse_json_output(result)
    run_id = run_data["run_id"]

    # Query run info via CLI
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
    ):
        result = runner.invoke(
            app,
            ["--json", "run", "info", run_id],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    info = _parse_json_output(result)
    assert info["llm"] == "info-ensemble"
    assert info["llm_type"] == "ensemble"
    assert info["llm_snapshot"] is not None

    # Parse the snapshot to verify member info is preserved
    snapshot = json.loads(info["llm_snapshot"])
    assert snapshot["type"] == "ensemble"
    assert len(snapshot["members"]) == 2
    member_names = {m["name"] for m in snapshot["members"]}
    assert "test-llm" in member_names
    assert "llm-b" in member_names


@pytest.mark.integration
def test_resume_llm_ensemble_override(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run resume --llm can switch from single LLM to ensemble.

    Traceable to: sprint-011 L2 test_resume_llm_ensemble_override.
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Launch initial run with single LLM
    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0, _get_all_output(result)
    parent_data = _parse_json_output(result)
    parent_run_id = parent_data["run_id"]

    # Create checkpoint for parent run
    parent_run_dir = root / REVOLVER_DIR / "runs" / parent_run_id
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Register second LLM and ensemble
    _register_llm(global_db_path, name="llm-b", model="gpt-3.5-turbo")
    _register_ensemble(
        global_db_path,
        "resume-ensemble",
        [
            {"llm_name": "test-llm", "weight": 0.6},
            {"llm_name": "llm-b", "weight": 0.4},
        ],
    )

    # Resume with ensemble override
    mock_runner = _make_mock_runner()
    mock_proxy = _make_mock_proxy()
    mock_runner_cls = MagicMock(return_value=mock_runner)
    mock_proxy_cls = MagicMock(return_value=mock_proxy)
    resume_run_id, resume_sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=resume_run_id),
        patch("revolver.core.run.generate_solution_id", return_value=resume_sol_id),
        patch("revolver.infra.backends.openevolve.count_valid_programs", return_value=3),
    ):
        result = runner.invoke(
            app,
            [
                "--json",
                "run",
                "resume",
                "--run",
                parent_run_id,
                "--llm",
                "resume-ensemble",
            ],
            catch_exceptions=False,
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    resume_data = _parse_json_output(result)
    new_run_id = resume_data["run_id"]

    # Verify the resumed run uses ensemble
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT llm, llm_type, llm_snapshot FROM runs WHERE id = ?",
            (new_run_id,),
        ).fetchone()
        assert row is not None
        assert row["llm"] == "resume-ensemble"
        assert row["llm_type"] == "ensemble"
        snapshot = json.loads(row["llm_snapshot"])
        assert snapshot["type"] == "ensemble"
        assert len(snapshot["members"]) == 2
    finally:
        conn.close()


@pytest.mark.integration
def test_run_start_llm_snapshot_single(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run start with single LLM stores a valid llm_snapshot with model details.

    Traceable to: sprint-011 L2 test_run_start_llm_snapshot_single.
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

    data = _parse_json_output(result)
    run_id = data["run_id"]

    # Verify llm_snapshot in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT llm_snapshot FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row is not None
        assert row["llm_snapshot"] is not None

        snapshot = json.loads(row["llm_snapshot"])
        assert snapshot["type"] == "single"
        assert snapshot["name"] == "test-llm"
        assert snapshot["model"] == "gpt-4"
    finally:
        conn.close()


# ── Test: run list ensemble prefix (F4) ────────────────────────────────────


@pytest.mark.integration
def test_run_list_ensemble_prefix(
    project_with_prereqs: dict[str, Path],
) -> None:
    """run list shows ``(E)`` as prefix for ensemble runs, not suffix.

    Traceable to: F4 (demo feedback), S12-07.
    """
    root = project_with_prereqs["root"]

    # Insert an ensemble run directly in DB
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, llm_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-ensemble-prefix-001",
                "v1.0",
                "flash-mix",
                "train-small",
                5,
                "hash-ep1",
                "dhash-ep1",
                "gemini-2.0-flash",
                "completed",
                "ensemble",
                "2026-04-01T10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Non-JSON output: verify prefix format (Rich may truncate, so check for
    # "(E) fl"). Widen the virtual terminal: the Backend column added in
    # S13 PR-C (FR-RUN-047) squeezes the llm column below 80 cols.
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app, ["run", "list"], catch_exceptions=False, env={"COLUMNS": "200"}
        )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "(E) fl" in output, f"Expected '(E)' prefix in output: {output}"
    assert "flash-mix (E)" not in output, "Suffix format should not appear"

    # JSON output: verify llm_type is exposed
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(app, ["--json", "run", "list"], catch_exceptions=False)

    data = _parse_json_output(result)
    ensemble_runs = [r for r in data if r["run_id"] == "run-ensemble-prefix-001"]
    assert len(ensemble_runs) == 1
    assert ensemble_runs[0]["llm_type"] == "ensemble"


# ── Backend surfacing tests (S13 PR-C, FR-RUN-047/048, ADR-007) ─────────────


@pytest.mark.integration
def test_run_backend_flag_and_default(project_with_prereqs: dict[str, Path]) -> None:
    """Default and explicit ``--backend openevolve`` record the backend.

    The backend must be stored in the run record (DB), written to the
    manifest, and surfaced by ``run info`` / ``run list`` (FR-RUN-047).
    """
    from revolver.infra.store import read_run_manifest

    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Run 1: default backend (no flag)
    result = _invoke_with_mocks(
        ["--json", "run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small"],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0, _get_all_output(result)
    default_run_id = _parse_json_output(result)["run_id"]

    # Run 2: explicit --backend openevolve behaves identically
    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--backend",
            "openevolve",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0, _get_all_output(result)
    explicit_run_id = _parse_json_output(result)["run_id"]

    # DB: both runs record backend='openevolve'
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        for rid in (default_run_id, explicit_run_id):
            cursor = conn.execute("SELECT backend FROM runs WHERE id = ?", (rid,))
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "openevolve", f"run {rid}: backend={row[0]!r}"
    finally:
        conn.close()

    # Manifest: backend key present (FR-RUN-047)
    manifest = read_run_manifest(root, default_run_id)
    assert manifest["backend"] == "openevolve"

    # run info: backend surfaced (JSON and human)
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app, ["--json", "run", "info", default_run_id], catch_exceptions=False
        )
    assert result.exit_code == 0
    info = _parse_json_output(result)
    assert info["backend"] == "openevolve"

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app, ["run", "info", default_run_id], catch_exceptions=False, env={"COLUMNS": "200"}
        )
    output = _get_all_output(result)
    assert result.exit_code == 0
    assert "backend" in output
    assert "openevolve" in output

    # run list: Backend column surfaced (JSON)
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(app, ["--json", "run", "list"], catch_exceptions=False)
    assert result.exit_code == 0
    rows = _parse_json_output(result)
    assert all(r["backend"] == "openevolve" for r in rows)


@pytest.mark.integration
def test_resume_inherits_parent_backend(project_with_prereqs: dict[str, Path]) -> None:
    """A resumed run inherits the parent run's backend (FR-RUN-047, §2.3)."""
    from revolver.infra.store import read_run_manifest

    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Parent run (default backend)
    result = _invoke_with_mocks(
        ["--json", "run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small"],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0, _get_all_output(result)
    parent_run_id = _parse_json_output(result)["run_id"]

    # Stage a parent checkpoint so resume can proceed
    parent_run_dir = root / REVOLVER_DIR / "runs" / parent_run_id
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Resume (no backend flag exists on resume — it takes the parent's)
    mock_runner_cls = MagicMock(return_value=_make_mock_runner())
    mock_proxy_cls = MagicMock(return_value=_make_mock_proxy())
    resume_run_id, resume_sol_id = _next_ids()
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=resume_run_id),
        patch("revolver.core.run.generate_solution_id", return_value=resume_sol_id),
    ):
        result = runner.invoke(
            app,
            ["--json", "run", "resume", "--run", parent_run_id],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, _get_all_output(result)
    new_run_id = _parse_json_output(result)["run_id"]

    # DB: the resumed run records the parent's backend
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT backend FROM runs WHERE id = ?", (new_run_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "openevolve"
    finally:
        conn.close()

    # Manifest: backend inherited
    manifest = read_run_manifest(root, new_run_id)
    assert manifest["backend"] == "openevolve"


@pytest.mark.integration
def test_run_unknown_backend_exit1(project_with_prereqs: dict[str, Path]) -> None:
    """``run --backend nope`` exits 1 and lists the available backends."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--backend",
            "nope",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Unknown backend 'nope'" in output
    assert "openevolve" in output
    assert "shinka" in output

    # No run record was created
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.integration
def test_run_shinka_stub_not_installed_exit3(
    no_shinka: None,
    project_with_prereqs: dict[str, Path],
) -> None:
    """``run --backend shinka`` exits 3 with the install hint (not installed)."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
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
        ],
        cwd=root,
        global_db_path=global_db_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 3, f"Exit {result.exit_code}; output: {output}"
    assert "pip install 'revolver[shinka]'" in output

    # No run record was created (the stub fails before any side effect)
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.integration
def test_run_backend_nondefault_surfaced(
    project_with_prereqs: dict[str, Path],
) -> None:
    """A non-default backend value is faithfully surfaced (review handoff).

    Inserts a run row with ``backend='shinka'`` directly in the DB: if any
    display path forgot to wire ``backend=`` (and silently rode the model
    default), this test catches it — a default-valued run cannot.
    """
    root = project_with_prereqs["root"]

    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (id, problem_version, llm, dataset, iterations, "
            "problem_hash, dataset_hash, llm_model, status, backend, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-shinka-display-001",
                "v1.0",
                "test-llm",
                "train-small",
                5,
                "hash-sd1",
                "dhash-sd1",
                "shinka-model",
                "completed",
                "shinka",
                "2026-04-02T10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # run list (JSON): backend faithfully reported
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(app, ["--json", "run", "list"], catch_exceptions=False)
    assert result.exit_code == 0
    rows = _parse_json_output(result)
    shinka_rows = [r for r in rows if r["run_id"] == "run-shinka-display-001"]
    assert len(shinka_rows) == 1
    assert shinka_rows[0]["backend"] == "shinka"

    # run list (human): Backend column shows the non-default value
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app, ["run", "list"], catch_exceptions=False, env={"COLUMNS": "200"}
        )
    output = _get_all_output(result)
    assert result.exit_code == 0
    assert "shinka" in output

    # run info (JSON + human): backend faithfully reported
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app, ["--json", "run", "info", "run-shinka-display-001"], catch_exceptions=False
        )
    assert result.exit_code == 0
    assert _parse_json_output(result)["backend"] == "shinka"

    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["run", "info", "run-shinka-display-001"],
            catch_exceptions=False,
            env={"COLUMNS": "200"},
        )
    output = _get_all_output(result)
    assert result.exit_code == 0
    assert "shinka" in output


@pytest.mark.integration
def test_run_dry_run_backend_surfaced(project_with_prereqs: dict[str, Path]) -> None:
    """Dry-run output surfaces the backend (FR-RUN-047): human and JSON."""
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # Human output: backend line + backend-aware resolved-config header
    result = _invoke_with_mocks(
        ["run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small", "--dry-run"],
        cwd=root,
        global_db_path=global_db_path,
    )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "backend" in output
    assert "openevolve" in output
    assert "Resolved openevolve config" in output

    # JSON output: resolved_config carries backend + backend_extras
    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--dry-run",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0
    data = _parse_json_output(result)
    rc = data["resolved_config"]
    assert rc["backend"] == "openevolve"
    assert isinstance(rc["backend_extras"], dict)


# ── U4 (S18-09/10): version-stored backend resolution (FR-PRB-016) ──────────


def _make_fake_resolution_backend(name: str) -> MagicMock:
    """Fake EvolutionBackend for resolution-order tests (dry-run path only).

    Substituted at the ``core.run.get_backend`` seam so the resolution
    order is observable without either engine installed (the CI main job
    has neither openevolve nor shinka).
    """
    from revolver.models.run import ResolvedConfig

    fake = MagicMock()
    fake.name = name
    fake.is_available.return_value = (False, None)  # U5 re-validation skips
    fake.build_config.return_value = {}
    fake.resolved_config.return_value = ResolvedConfig(backend=name, iterations=7)
    return fake


@pytest.mark.integration
def test_run_backend_resolution_order_and_mismatch_warn(
    project_with_prereqs: dict[str, Path],
) -> None:
    """U4 resolution order + mismatch warning (S18-09/10, FR-RUN-047 amended).

    - ``version create v2 --backend shinka`` persists ``'shinka'`` on the
      version row (FR-PRB-016, migration v14).
    - ``run v2`` with no ``--backend`` resolves Shinka FROM THE VERSION
      (observed at the ``get_backend`` seam), without any warning.
    - ``run v2 --backend openevolve`` runs OpenEvolve (explicit wins) WITH
      a mismatch warning on stderr.
    - A version row with no stored backend (legacy pre-v14 shape) still
      defaults to ``'openevolve'``.
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]
    db_path = root / REVOLVER_DIR / "revolver.db"

    # ── version create v2 --backend shinka persists 'shinka' ────────────
    # Change the problem content so v2 does not collide with v1.0's hash.
    program = root / "initial_program.py"
    program.write_text(program.read_text() + "\n# v2 tweak\n", encoding="utf-8")
    with patch("pathlib.Path.cwd", return_value=root):
        result = runner.invoke(
            app,
            ["problem", "version", "create", "v2", "--backend", "shinka"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, _get_all_output(result)

    conn = get_project_db(db_path)
    try:
        row = conn.execute(
            "SELECT backend FROM problem_versions WHERE tag = ?", ("v2",)
        ).fetchone()
        assert row is not None
        assert row[0] == "shinka"
    finally:
        conn.close()

    # ── run v2 (no --backend) resolves Shinka from the version ──────────
    fake_shinka = _make_fake_resolution_backend("shinka")
    get_backend_recorder = MagicMock(side_effect=lambda name: fake_shinka)
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.core.run.get_backend", get_backend_recorder),
    ):
        result = runner.invoke(
            app,
            [
                "--json",
                "run",
                "--version",
                "v2",
                "--llm",
                "test-llm",
                "--dataset",
                "train-small",
                "--dry-run",
            ],
            catch_exceptions=False,
        )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    get_backend_recorder.assert_called_once_with("shinka")
    data = _parse_json_output(result)
    assert data["resolved_config"]["backend"] == "shinka"
    # Deferring to the version is not a mismatch — no warning.
    assert "Warning: version" not in output

    # ── run v2 --backend openevolve: explicit wins, mismatch warns ──────
    result = _invoke_with_mocks(
        [
            "run",
            "--version",
            "v2",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--backend",
            "openevolve",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert (
        "Warning: version 'v2' stores backend 'shinka' but --backend "
        "'openevolve' was given. Proceeding with 'openevolve'." in output
    )

    # The explicit choice is what gets persisted on the run record
    # (dry-runs insert nothing, so this is the project's only run row).
    conn = get_project_db(db_path)
    try:
        rows = conn.execute("SELECT backend FROM runs").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "openevolve"
    finally:
        conn.close()

    # ── a version with no stored backend still defaults to openevolve ───
    # Raw insert omitting the backend column = the legacy pre-v14 row shape
    # after migration (the column default backfills 'openevolve').
    conn = get_project_db(db_path)
    try:
        conn.execute(
            "INSERT INTO problem_versions (tag, hash, message, created_at) VALUES (?, ?, ?, ?)",
            ("v0-legacy", "sha256:legacy0", "", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    fake_oe = _make_fake_resolution_backend("openevolve")
    get_backend_recorder = MagicMock(side_effect=lambda name: fake_oe)
    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.core.run.get_backend", get_backend_recorder),
    ):
        result = runner.invoke(
            app,
            [
                "--json",
                "run",
                "--version",
                "v0-legacy",
                "--llm",
                "test-llm",
                "--dataset",
                "train-small",
                "--dry-run",
            ],
            catch_exceptions=False,
        )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    get_backend_recorder.assert_called_once_with("openevolve")
    assert "Warning: version" not in output


# ── S17a-06: "completed" messaging only after teardown (U12 residual, #359) ──


@pytest.mark.integration
def test_launch_run_completed_message_after_teardown(
    project_with_prereqs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Run completed" is emitted only after the finalize backstop reaped a
    child leaked through post-run eval: at lock-removal time the leaked
    child is already terminated, and the CLI message (printed after
    launch_run returns) therefore always follows teardown.
    """
    import signal
    import subprocess
    import sys

    import revolver.core.run as core_run_module
    import revolver.infra.backends.base as backends_base

    # Keep the zombie-wait loop in _reap_run_children fast (the SIGTERMed
    # direct child of pytest stays a zombie until poll()ed).
    monkeypatch.setattr(backends_base, "_CHILD_REAP_GRACE_SECONDS", 0.3)

    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    leaked: dict[str, subprocess.Popen[bytes]] = {}
    order: dict[str, bool] = {}
    probes: dict[str, str] = {}

    def _leaking_post_eval(**kwargs: object) -> None:
        """Simulate post-run eval leaking one direct child (U12)."""
        leaked["proc"] = subprocess.Popen(["sleep", "60"])

    real_remove_run_lock = core_run_module.remove_run_lock

    def _captured_cli_text() -> str:
        """Read the CLI output captured so far by CliRunner's streams."""
        chunks: list[str] = []
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
                buffer = getattr(stream, "buffer", None)
                if buffer is not None and hasattr(buffer, "getvalue"):
                    chunks.append(buffer.getvalue().decode("utf-8", errors="replace"))
            except Exception:  # probe only — never fail the run from here
                continue
        return "".join(chunks)

    def _recording_remove_run_lock(root_arg: Path, run_id_arg: str) -> None:
        order["leaked_dead_at_lock_removal"] = leaked["proc"].poll() is not None
        # Direct ordering probe (PR #245 review): the completed message
        # must NOT have been emitted yet at lock-removal time.
        probes["output_at_lock_removal"] = _captured_cli_text()
        real_remove_run_lock(root_arg, run_id_arg)

    mock_runner_cls = MagicMock(return_value=_make_mock_runner())
    mock_proxy_cls = MagicMock(return_value=_make_mock_proxy())
    run_id, sol_id = _next_ids()

    try:
        with (
            patch("pathlib.Path.cwd", return_value=root),
            patch(
                "revolver.core.run.get_global_db",
                side_effect=lambda: get_global_db_at(global_db_path),
            ),
            patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
            patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
            patch("revolver.core.run._post_run_evaluation", side_effect=_leaking_post_eval),
            patch("revolver.core.run.remove_run_lock", side_effect=_recording_remove_run_lock),
            patch("revolver.core.run.generate_run_id", return_value=run_id),
            patch("revolver.core.run.generate_solution_id", return_value=sol_id),
            patch("revolver.infra.backends.openevolve.count_valid_programs", return_value=10),
        ):
            result = runner.invoke(
                app,
                ["run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small"],
                catch_exceptions=False,
            )

        output = _get_all_output(result)
        assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"

        # The completed message was emitted...
        assert "Run completed" in output
        # ...but only after teardown: at lock-removal time the leaked child
        # was already dead AND the message was not yet in the captured
        # output (direct ordering assertion — PR #245 review). The probe is
        # proven live by a message that does precede lock removal.
        assert order["leaked_dead_at_lock_removal"] is True
        assert "Running post-run evaluation" in probes["output_at_lock_removal"]
        assert "Run completed" not in probes["output_at_lock_removal"]
        assert leaked["proc"].poll() in (-signal.SIGTERM, -signal.SIGKILL)
    finally:
        proc = leaked.get("proc")
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


# ── FR-RUN-053: wrapper coverage keys + timeout side-channel (S18 / U13 ii) ──

_EVALUATOR_TIMEOUT_MIX = '''\
"""Evaluator: one instance times out, the others return metrics.

The reserved "instances_user_key" metric probes the FR-RUN-053 rule that
the "instances_" prefix is never averaged into the aggregate. The timeout
trigger matches the file NAME only — pytest tmp dirs may contain "timeout"
in the test-derived directory name.
"""
import os


def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    if "timeout" in os.path.basename(instance_path):
        raise TimeoutError("simulated per-instance timeout")
    return {"combined_score": 0.5, "quality": 0.4, "instances_user_key": 9.0}
'''

# Driver that imports a generated OE wrapper by path and prints the
# aggregated evaluate() result as JSON (subprocess isolation keeps the
# wrapper's `from evaluator import ...` out of this process's sys.modules).
_OE_WRAPPER_DRIVER = """\
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("_wrapper_under_test", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(json.dumps(mod.evaluate(sys.argv[2])))
"""


def _make_timeout_mix_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Snapshot + dataset (2 valid instances, 1 timing out) + program file."""
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "evaluator.py").write_text(_EVALUATOR_TIMEOUT_MIX, encoding="utf-8")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "inst-01.json").write_text("{}", encoding="utf-8")
    (dataset / "inst-02-timeout.json").write_text("{}", encoding="utf-8")
    (dataset / "inst-03.json").write_text("{}", encoding="utf-8")
    program = tmp_path / "program.py"
    program.write_text("def solve():\n    return 0\n", encoding="utf-8")
    return snapshot, dataset, program


def _assert_coverage_contract(metrics: dict[str, object], log_db: Path) -> None:
    """Shared FR-RUN-053 assertions for both backends' wrapper output."""
    # Coverage keys are emitted as metadata...
    assert metrics["instances_valid"] == pytest.approx(2.0)
    assert metrics["instances_total"] == pytest.approx(3.0)
    # ...and never summed/averaged into the score: combined_score is the
    # FR-RUN-054 default-penalize mean (0.5 + 0.5 + timeout at 0.0) / 3 —
    # NOT inflated by the coverage keys — and the user's reserved-prefix
    # metric is excluded from aggregation entirely.
    assert metrics["combined_score"] == pytest.approx((0.5 + 0.5 + 0.0) / 3)
    assert metrics["quality"] == pytest.approx(0.4)
    assert "instances_user_key" not in metrics
    # The timed-out instance is recorded on the side-channel (timeout marker
    # row), distinguishable from ordinary failures.
    conn = sqlite3.connect(log_db)
    try:
        rows = conn.execute(
            "SELECT instance_id, value FROM instance_log WHERE metric = 'instances_timeout'"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("inst-02-timeout.json", 1.0)]


def _wrapper_env(dataset: Path, log_db: Path | None) -> dict[str, str]:
    """Subprocess env for a generated wrapper run over *dataset*."""
    import os

    env = {k: v for k, v in os.environ.items() if k not in ("REVOLVER_INSTANCE_PATH",)}
    env["REVOLVER_DATASET_DIR"] = str(dataset)
    env.pop("REVOLVER_INSTANCE_LOG", None)
    if log_db is not None:
        env["REVOLVER_INSTANCE_LOG"] = str(log_db)
    return env


def _run_oe_wrapper(
    tmp_path: Path,
    wrapper: Path,
    program: Path,
    dataset: Path,
    log_db: Path | None = None,
) -> tuple[dict[str, float], str]:
    """Exec a generated OE wrapper's evaluate() in a subprocess.

    Returns the aggregated metrics dict and the captured stderr.
    """
    import subprocess
    import sys

    driver = tmp_path / "oe_wrapper_driver.py"
    driver.write_text(_OE_WRAPPER_DRIVER, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(driver), str(wrapper), str(program)],
        env=_wrapper_env(dataset, log_db),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout), proc.stderr


def _generate_shinka_wrapper(
    snapshot: Path,
    run_dir: Path,
    on_timeout: str = "penalize",
    timeout_score: float = 0.0,
) -> Path:
    """Generate the Shinka wrapper for *snapshot* with the given policy."""
    from revolver.infra.backends.base import BackendRunSpec
    from revolver.infra.backends.shinka import ShinkaBackend
    from revolver.models.llm import LLMEntry

    run_dir.mkdir(parents=True, exist_ok=True)
    spec = BackendRunSpec(
        snapshot_dir=snapshot,
        llm=LLMEntry(
            name="test-llm",
            source="local",
            model="test-model",
            base_url="http://localhost:11434/v1",
            api_key_env=None,
            registered_at=datetime.now(UTC),
        ),
        run_dir=run_dir,
        on_timeout=on_timeout,
        timeout_score=timeout_score,
    )
    return ShinkaBackend().generate_wrapper(spec)


def _run_shinka_wrapper(
    wrapper: Path,
    program: Path,
    dataset: Path,
    results_dir: Path,
    log_db: Path | None = None,
) -> dict[str, float]:
    """Run a generated Shinka wrapper (CLI contract) and return metrics.json."""
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            str(wrapper),
            "--program_path",
            str(program),
            "--results_dir",
            str(results_dir),
        ],
        env=_wrapper_env(dataset, log_db),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    metrics = json.loads((results_dir / "metrics.json").read_text(encoding="utf-8"))
    assert isinstance(metrics, dict)
    return metrics


@pytest.mark.integration
def test_wrapper_coverage_keys_not_in_score(tmp_path: Path) -> None:
    """Both wrapper templates emit coverage keys that never inflate the score.

    FR-RUN-053 / FR-EVL-021 (S18 / U13 #367 commit ii): over a mixed
    valid/timed-out dataset, the generated wrapper on BOTH backends emits
    ``instances_valid``/``instances_total`` alongside the aggregated metrics,
    excludes the reserved ``instances_`` prefix from the metric mean, and
    records the timed-out instance on the ``REVOLVER_INSTANCE_LOG``
    side-channel. The Shinka wrapper runs via its standalone fallback here,
    so this covers the no-shinka CI env; the run_shinka_eval path is covered
    by ``test_shinka_wrapper_timeout_branch`` (L2-Shinka).
    """
    from revolver.infra.backends.openevolve import generate_wrapper as oe_generate_wrapper

    snapshot, dataset, program = _make_timeout_mix_project(tmp_path)

    # ── OpenEvolve wrapper (module contract: evaluate(program_path)) ────────
    oe_run_dir = tmp_path / "run-oe"
    oe_run_dir.mkdir()
    oe_wrapper = oe_generate_wrapper(snapshot, oe_run_dir)
    oe_log_db = tmp_path / "instance_log_oe.db"

    oe_metrics, stderr = _run_oe_wrapper(tmp_path, oe_wrapper, program, dataset, oe_log_db)

    _assert_coverage_contract(oe_metrics, oe_log_db)
    assert "timeout for inst-02-timeout.json" in stderr

    # ── ShinkaEvolve wrapper (CLI contract: --program_path/--results_dir) ───
    shinka_wrapper = _generate_shinka_wrapper(snapshot, tmp_path / "run-shinka")
    results_dir = tmp_path / "results"
    shinka_log_db = tmp_path / "instance_log_shinka.db"

    shinka_metrics = _run_shinka_wrapper(
        shinka_wrapper, program, dataset, results_dir, shinka_log_db
    )

    _assert_coverage_contract(shinka_metrics, shinka_log_db)
    correct = json.loads((results_dir / "correct.json").read_text(encoding="utf-8"))
    assert correct["correct"] is True


# ── FR-RUN-054: evaluation.on_timeout policy + validation (S18 / U13 iii) ────


@pytest.mark.integration
def test_on_timeout_penalize_vs_drop(tmp_path: Path) -> None:
    """penalize (default) scores timeouts at timeout_score; drop restores 0.17.

    FR-RUN-054 (S18 / U13 #367 commit iii), on BOTH wrapper templates over
    the same mixed valid/timed-out dataset:

    - default ``penalize`` counts the timed-out instance at ``timeout_score``
      (default 0.0) in the fitness mean — the deliberate v0.18
      fitness-landscape flip;
    - ``on_timeout=drop`` restores the 0.17 survivor-mean;
    - a custom finite ``timeout_score`` is honored;
    - on a zero-timeout dataset the two policies produce identical scores.
    """
    from revolver.infra.backends.openevolve import generate_wrapper as oe_generate_wrapper

    snapshot, dataset, program = _make_timeout_mix_project(tmp_path)
    survivor_mean = 0.5  # mean over the two valid instances (0.17 behavior)
    penalized_mean = (0.5 + 0.5 + 0.0) / 3  # timeout counted at 0.0

    # ── OpenEvolve template ──────────────────────────────────────────────────
    dirs = {name: tmp_path / f"run-oe-{name}" for name in ("pen", "drop", "floor")}
    for d in dirs.values():
        d.mkdir()
    wrapper_pen = oe_generate_wrapper(snapshot, dirs["pen"])  # default: penalize
    wrapper_drop = oe_generate_wrapper(snapshot, dirs["drop"], on_timeout="drop")
    wrapper_floor = oe_generate_wrapper(snapshot, dirs["floor"], timeout_score=-1.0)

    pen_metrics, _ = _run_oe_wrapper(tmp_path, wrapper_pen, program, dataset)
    drop_metrics, _ = _run_oe_wrapper(tmp_path, wrapper_drop, program, dataset)
    floor_metrics, _ = _run_oe_wrapper(tmp_path, wrapper_floor, program, dataset)

    assert pen_metrics["combined_score"] == pytest.approx(penalized_mean)
    assert drop_metrics["combined_score"] == pytest.approx(survivor_mean)
    assert floor_metrics["combined_score"] == pytest.approx((0.5 + 0.5 - 1.0) / 3)
    # Coverage is policy-independent: the timed-out instance is never "valid".
    for m in (pen_metrics, drop_metrics, floor_metrics):
        assert m["instances_valid"] == pytest.approx(2.0)
        assert m["instances_total"] == pytest.approx(3.0)

    # ── ShinkaEvolve template (standalone fallback) ──────────────────────────
    shinka_pen = _generate_shinka_wrapper(snapshot, tmp_path / "run-shinka-pen")
    shinka_drop = _generate_shinka_wrapper(
        snapshot, tmp_path / "run-shinka-drop", on_timeout="drop"
    )

    shinka_pen_metrics = _run_shinka_wrapper(
        shinka_pen, program, dataset, tmp_path / "results-pen"
    )
    shinka_drop_metrics = _run_shinka_wrapper(
        shinka_drop, program, dataset, tmp_path / "results-drop"
    )

    assert shinka_pen_metrics["combined_score"] == pytest.approx(penalized_mean)
    assert shinka_drop_metrics["combined_score"] == pytest.approx(survivor_mean)

    # ── Zero-timeout dataset: penalize ≡ drop (the policy is a no-op) ────────
    clean_dataset = tmp_path / "dataset-clean"
    clean_dataset.mkdir()
    (clean_dataset / "inst-01.json").write_text("{}", encoding="utf-8")
    (clean_dataset / "inst-03.json").write_text("{}", encoding="utf-8")

    clean_pen, _ = _run_oe_wrapper(tmp_path, wrapper_pen, program, clean_dataset)
    clean_drop, _ = _run_oe_wrapper(tmp_path, wrapper_drop, program, clean_dataset)

    assert clean_pen == clean_drop
    assert clean_pen["combined_score"] == pytest.approx(0.5)
    assert clean_pen["instances_valid"] == pytest.approx(2.0)


@pytest.mark.integration
def test_evaluation_on_timeout_validation(project_with_prereqs: dict[str, Path]) -> None:
    """Bad evaluation.* values are rejected at run AND dry-run (FR-RUN-054).

    ``evaluation.*`` is a validated, Revolver-owned config section as of
    S18 (previously popped/uninspected — typos were silent). An unknown
    ``on_timeout`` value or a non-finite ``timeout_score`` exits 1 at the
    shared launch point, before any side effect (no run dir, no DB record);
    valid values are accepted.
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]
    base_args = ["run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small"]

    # (a) Unknown on_timeout value -> exit 1 at --dry-run with a clear message.
    result = _invoke_with_mocks(
        [*base_args, "--dry-run", "--config-override", "evaluation.on_timeout=bogus"],
        cwd=root,
        global_db_path=global_db_path,
    )
    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Invalid evaluation.on_timeout 'bogus'" in output
    assert "penalize, drop" in output

    # (b) Non-finite timeout_score -> exit 1 at --dry-run.
    result = _invoke_with_mocks(
        [*base_args, "--dry-run", "--config-override", "evaluation.timeout_score=.inf"],
        cwd=root,
        global_db_path=global_db_path,
    )
    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "evaluation.timeout_score must be a finite number" in output

    # (c) Rejected at a real run too, with no side effect (no run record).
    result = _invoke_with_mocks(
        [*base_args, "--config-override", "evaluation.on_timeout=bogus"],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 1
    conn = get_project_db(root / REVOLVER_DIR / "revolver.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        conn.close()

    # (d) Valid values pass: drop (the 0.17 escape hatch) dry-runs clean.
    result = _invoke_with_mocks(
        [
            *base_args,
            "--dry-run",
            "--config-override",
            "evaluation.on_timeout=drop",
            "--config-override",
            "evaluation.timeout_score=-1.0",
        ],
        cwd=root,
        global_db_path=global_db_path,
    )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"


# Driver that models run_shinka_eval's ProcessPoolExecutor split: the
# producer module instance runs run_experiment(); a FRESH consumer module
# instance (which never saw run_experiment run — like the parent process
# when run_workers > 1) aggregates. A module-global coverage channel would
# read 0.0/0.0 here; the stamped per-instance entries must not.
_SHINKA_CROSS_PROCESS_DRIVER = """\
import importlib.util
import json
import sys


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


producer = _load(sys.argv[1], "_wrapper_producer")
results = producer.run_experiment(sys.argv[2])
consumer = _load(sys.argv[1], "_wrapper_consumer")
print(json.dumps(consumer.aggregate_metrics([results])))
"""


@pytest.mark.integration
def test_shinka_coverage_survives_process_boundary(tmp_path: Path) -> None:
    """Coverage keys travel with the results, not via a module-global.

    FR-RUN-053 (S18 / U13 #367 commit ii, PR #257 review): shinka's
    ``run_shinka_eval`` executes ``run_experiment()`` in a
    ``ProcessPoolExecutor`` worker when ``run_workers > 1``, so a
    module-global written by the worker's module instance never reaches
    the parent's ``aggregate_metrics()``. The coverage keys are therefore
    stamped onto the per-instance entries and read back from them. This
    driver aggregates in a fresh module instance that never ran
    ``run_experiment()`` — coverage must still be correct.
    """
    import subprocess
    import sys

    snapshot, dataset, program = _make_timeout_mix_project(tmp_path)
    wrapper = _generate_shinka_wrapper(snapshot, tmp_path / "run-shinka")

    driver = tmp_path / "shinka_cross_process_driver.py"
    driver.write_text(_SHINKA_CROSS_PROCESS_DRIVER, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(driver), str(wrapper), str(program)],
        env=_wrapper_env(dataset, None),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    metrics = json.loads(proc.stdout)
    assert metrics["instances_valid"] == pytest.approx(2.0)
    assert metrics["instances_total"] == pytest.approx(3.0)
    # The mean is still the FR-RUN-054 default-penalize mean, uninflated.
    assert metrics["combined_score"] == pytest.approx((0.5 + 0.5 + 0.0) / 3)
    assert "instances_user_key" not in metrics


@pytest.mark.integration
def test_resume_inherits_baked_timeout_policy(
    tmp_project: Path,
    dataset_dir: Path,
    global_db_path: Path,
) -> None:
    """Resume reuses the parent's wrapper, so the baked policy persists.

    FR-RUN-054 (S18 / U13 #367 commit iii): ``evaluation.on_timeout`` /
    ``timeout_score`` are baked into the wrapper at launch; resume copies
    the parent wrapper instead of regenerating it (FR-RUN-024), so a
    non-default policy survives the resume without the overrides being
    re-supplied.
    """
    from revolver.core.problem import create_version

    # Instance-mode evaluator: only the generated (non-legacy) wrapper
    # carries the baked policy constants.
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    shutil.copy2(fixtures_dir / "evaluator_instance.py", tmp_project / "evaluator.py")
    shutil.copy2(
        fixtures_dir / "initial_program_simple.py",
        tmp_project / "initial_program.py",
    )
    shutil.copy2(fixtures_dir / "config_simple.yaml", tmp_project / "config.yaml")
    create_version(tag="v1.0", message="Version v1.0", project_root=tmp_project)
    _register_dataset(tmp_project, dataset_dir, compatible_with=["v1.0"])
    _register_llm(global_db_path, base_url="http://localhost:11434/v1")

    result = _invoke_with_mocks(
        [
            "--json",
            "run",
            "--version",
            "v1.0",
            "--llm",
            "test-llm",
            "--dataset",
            "train-small",
            "--config-override",
            "evaluation.on_timeout=drop",
            "--config-override",
            "evaluation.timeout_score=-0.5",
        ],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0, _get_all_output(result)
    parent_run_id = _parse_json_output(result)["run_id"]

    parent_run_dir = tmp_project / REVOLVER_DIR / "runs" / parent_run_id
    parent_wrapper = (parent_run_dir / "_revolver_evaluator.py").read_text(encoding="utf-8")
    assert "_ON_TIMEOUT = 'drop'" in parent_wrapper
    assert "_TIMEOUT_SCORE = -0.5" in parent_wrapper

    # Stage a checkpoint so resume can proceed (FR-RUN-024).
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    result = _invoke_with_mocks(
        ["--json", "run", "resume", "--run", parent_run_id],
        cwd=tmp_project,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0, _get_all_output(result)
    resumed_run_id = _parse_json_output(result)["run_id"]

    resumed_wrapper = (
        tmp_project / REVOLVER_DIR / "runs" / resumed_run_id / "_revolver_evaluator.py"
    ).read_text(encoding="utf-8")
    # Copied verbatim, not regenerated: the baked policy is inherited.
    assert resumed_wrapper == parent_wrapper


@pytest.mark.integration
def test_resume_post_eval_call_site_wiring(project_with_prereqs: dict[str, Path]) -> None:
    """resume_run wires the post-run eval with the RESUMED run's identifiers.

    S18-05 (PR #261 review): the resume call site threads the parent's
    dataset name, the new run's rank-1 program path, and the project root
    into ``_post_run_evaluation`` — asserted through the same seam the rest
    of the suite patches (the helper's internals are covered by the direct
    ``_post_run_evaluation`` tests).
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    result = _invoke_with_mocks(
        ["--json", "run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small"],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0
    parent_run_id = _parse_json_output(result)["run_id"]

    parent_run_dir = root / REVOLVER_DIR / "runs" / parent_run_id
    checkpoint_dir = parent_run_dir / "oe-output" / "checkpoints" / "checkpoint_5"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    mock_runner_cls = MagicMock(return_value=_make_mock_runner())
    mock_proxy_cls = MagicMock(return_value=_make_mock_proxy())
    resume_run_id, resume_sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation") as mock_post_eval,
        patch("revolver.core.run.generate_run_id", return_value=resume_run_id),
        patch("revolver.core.run.generate_solution_id", return_value=resume_sol_id),
        patch("revolver.infra.backends.openevolve.count_valid_programs", return_value=10),
    ):
        result = runner.invoke(
            app, ["--json", "run", "resume", "--run", parent_run_id], catch_exceptions=False
        )

    assert result.exit_code == 0, _get_all_output(result)

    mock_post_eval.assert_called_once()
    kwargs = mock_post_eval.call_args.kwargs
    assert kwargs["run_id"] == resume_run_id
    assert kwargs["solution_id"] == resume_sol_id
    assert kwargs["dataset_name"] == "train-small"  # inherited from the parent
    assert kwargs["project_root"] == root
    new_run_dir = root / REVOLVER_DIR / "runs" / resume_run_id
    assert kwargs["program_path"] == new_run_dir / "programs" / "rank-1.py"


# ── U8: seed-metric pre-flight validation (FR-RUN-056, S18-11/12/14) ────────


_FEATURE_DIM_CONFIG_SNIPPET = """
database:
  feature_dimensions: {dims}
"""


def _create_version_with_feature_dims(
    project_root: Path,
    tag: str,
    dims: list[str],
) -> None:
    """Create a problem version whose config declares MAP-Elites feature dims."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    shutil.copy2(fixtures_dir / "evaluator_simple.py", project_root / "evaluator.py")
    shutil.copy2(
        fixtures_dir / "initial_program_simple.py",
        project_root / "initial_program.py",
    )
    shutil.copy2(fixtures_dir / "config_simple.yaml", project_root / "config.yaml")
    with open(project_root / "config.yaml", "a", encoding="utf-8") as f:
        f.write(_FEATURE_DIM_CONFIG_SNIPPET.format(dims=json.dumps(dims)))

    from revolver.core.problem import create_version

    create_version(tag=tag, message=f"Version {tag}", project_root=project_root)


def _invoke_run_expecting_no_engine(
    args: list[str],
    root: Path,
    global_db_path: Path,
) -> tuple[object, MagicMock]:
    """Invoke a run/resume CLI command; return (result, mocked runner class).

    Mirrors ``_invoke_with_mocks`` but hands the ``OpenEvolveRunner`` class
    mock back so the caller can assert the engine was never constructed
    (FR-RUN-056: the seed-metric error aborts before iteration 0).
    """
    mock_runner_cls = MagicMock(return_value=_make_mock_runner())
    mock_proxy_cls = MagicMock(return_value=_make_mock_proxy())
    run_id, sol_id = _next_ids()

    with (
        patch("pathlib.Path.cwd", return_value=root),
        patch(
            "revolver.core.run.get_global_db",
            side_effect=lambda: get_global_db_at(global_db_path),
        ),
        patch("revolver.infra.backends.openevolve.OpenEvolveRunner", mock_runner_cls),
        patch("revolver.core.run.TokenCountingProxy", mock_proxy_cls),
        patch("revolver.core.run._post_run_evaluation"),
        patch("revolver.core.run.generate_run_id", return_value=run_id),
        patch("revolver.core.run.generate_solution_id", return_value=sol_id),
    ):
        result = runner.invoke(app, args, catch_exceptions=False)
    return result, mock_runner_cls


@pytest.mark.integration
def test_validate_seed_metrics_missing_dim_fails(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Seed missing a declared non-builtin feature dim fails fast (FR-RUN-056).

    On both launch and resume, the ``validate_seed_metrics`` hook aborts
    right after the pre-flight — before iteration 0, with exit 1 and no
    engine construction — naming the missing dimension and listing the
    available seed metrics (the fixture evaluator only produces
    ``combined_score``).
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    # ── Launch: v2.0 declares a dim the seed's metrics never contain ──
    _create_version_with_feature_dims(root, "v2.0", ["correctness"])

    result, mock_runner_cls = _invoke_run_expecting_no_engine(
        ["run", "--version", "v2.0", "--llm", "test-llm", "--dataset", "train-small"],
        root=root,
        global_db_path=global_db_path,
    )
    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Feature dimension 'correctness' not found in seed metrics" in output
    assert "Available metrics:" in output
    assert "combined_score" in output
    # Pre-flight itself passed — the failure is the 12b hook, one step later.
    assert "Pre-flight check passed" in output
    mock_runner_cls.assert_not_called()  # aborted before iteration 0

    # The inserted run record was finalized as failed, never completed.
    db_path = root / REVOLVER_DIR / "revolver.db"
    conn = get_project_db(db_path)
    try:
        rows = conn.execute("SELECT status FROM runs").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "failed"
    finally:
        conn.close()

    # ── Resume: the hook fires on the resume pre-flight too ──
    # Launch a passing parent on v1.0 (no feature dims), stage a checkpoint,
    # then declare the missing dim in the parent's SNAPSHOT config — the
    # resume rebuilds its engine config from that snapshot.
    result = _invoke_with_mocks(
        ["--json", "run", "--version", "v1.0", "--llm", "test-llm", "--dataset", "train-small"],
        cwd=root,
        global_db_path=global_db_path,
    )
    assert result.exit_code == 0, _get_all_output(result)
    parent_run_id = _parse_json_output(result)["run_id"]
    checkpoint_dir = (
        root / REVOLVER_DIR / "runs" / parent_run_id / "oe-output" / "checkpoints" / "checkpoint_5"
    )
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    snapshot_config = root / REVOLVER_DIR / "problem" / "v1.0" / "config.yaml"
    snapshot_config.chmod(0o644)  # snapshots are stored read-only
    with open(snapshot_config, "a", encoding="utf-8") as f:
        f.write(_FEATURE_DIM_CONFIG_SNIPPET.format(dims=json.dumps(["correctness"])))

    result, mock_runner_cls = _invoke_run_expecting_no_engine(
        ["run", "resume", parent_run_id],
        root=root,
        global_db_path=global_db_path,
    )
    output = _get_all_output(result)
    assert result.exit_code == 1, f"Exit {result.exit_code}; output: {output}"
    assert "Feature dimension 'correctness' not found in seed metrics" in output
    assert "Available metrics:" in output
    mock_runner_cls.assert_not_called()  # resume aborted before iteration 0


@pytest.mark.integration
def test_validate_seed_metrics_builtins_and_shinka_noop(
    project_with_prereqs: dict[str, Path],
) -> None:
    """Builtin feature dims never trip the hook; the Shinka hook is a no-op.

    ``complexity``/``diversity``/``combined_score`` are computed inside
    OpenEvolve and legitimately absent from the seed's metrics (FR-RUN-056
    allowlist), so a run declaring only builtins completes. ShinkaEvolve's
    ``validate_seed_metrics`` never raises regardless of declared dims (its
    only metric contract is ``combined_score``), so a Shinka run is
    unaffected by the hook call site.
    """
    root = project_with_prereqs["root"]
    global_db_path = project_with_prereqs["global_db_path"]

    _create_version_with_feature_dims(root, "v2.0", ["complexity", "diversity", "combined_score"])

    result = _invoke_with_mocks(
        ["run", "--version", "v2.0", "--llm", "test-llm", "--dataset", "train-small"],
        cwd=root,
        global_db_path=global_db_path,
    )
    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit {result.exit_code}; output: {output}"
    assert "Feature dimension" not in output

    # Shinka no-op: even a declared non-builtin dim raises nothing — the
    # backend has no per-dimension metric contract to enforce.
    from revolver.infra.backends.shinka import ShinkaBackend

    shinka = ShinkaBackend()
    config = {"database": {"feature_dimensions": ["correctness"]}}
    assert shinka.validate_seed_metrics(config, {"combined_score": 1.0}) is None
    assert shinka.validate_seed_metrics(config, None) is None


# ── U6 phase 2: default checkpoint cadence (FR-RUN-057, S18-13/14) ──────────


@pytest.mark.integration
def test_checkpoint_cadence_default_when_unset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unset checkpoint_interval defaults to max(1, min(100, iters//10)) (OE).

    A default <=100-iteration run gets a mid-run checkpoint (interval <
    iterations); an explicit ``checkpoint_interval`` is preserved verbatim;
    the S17a-12 phase-1 warn (5c) fires only on EXPLICIT equality; and the
    5b clamp no longer trips on the old default-100-vs-small-iters case.
    """
    from datetime import UTC, datetime as dt

    from revolver.infra.backends.openevolve import build_config
    from revolver.models.llm import LLMEntry

    llm = LLMEntry(
        name="test-llm",
        model="gpt-4",
        source="remote",
        base_url="http://localhost:11434/v1",
        registered_at=dt.now(UTC),
    )

    # Unset interval + 50 iterations -> defaulted mid-run cadence, silent.
    config = build_config(problem_config=None, llm=llm, iterations=50)
    err = capsys.readouterr().err
    assert config["checkpoint_interval"] == 5
    assert config["checkpoint_interval"] < config["max_iterations"]
    assert "no mid-run checkpoint" not in err
    assert "Overriding to checkpoint_interval" not in err

    # Explicit interval -> preserved verbatim, never overridden.
    config = build_config(
        problem_config=None,
        llm=llm,
        iterations=50,
        config_overrides=["checkpoint_interval=40"],
    )
    capsys.readouterr()
    assert config["checkpoint_interval"] == 40

    # EXPLICIT equality -> the 5c warn still fires (S17a-12 unchanged).
    config = build_config(
        problem_config=None,
        llm=llm,
        iterations=50,
        config_overrides=["checkpoint_interval=50"],
    )
    err = capsys.readouterr().err
    assert config["checkpoint_interval"] == 50
    assert "no mid-run checkpoint" in err

    # DEFAULTED equality (iterations=1 -> default interval 1) -> no 5c warn:
    # the user never set the value, so there is nothing to nag about.
    config = build_config(problem_config=None, llm=llm, iterations=1)
    err = capsys.readouterr().err
    assert config["checkpoint_interval"] == 1
    assert "no mid-run checkpoint" not in err

    # Old default-100-vs-small-iters case: the 5a default (1) replaces the
    # 5b clamp -> no clamp warning on the default path anymore.
    config = build_config(problem_config=None, llm=llm, iterations=5)
    err = capsys.readouterr().err
    assert config["checkpoint_interval"] == 1
    assert "Overriding to checkpoint_interval" not in err
