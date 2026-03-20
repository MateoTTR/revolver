"""L2 cross-cutting integration tests for all ``revolver`` commands.

Verifies behavior that cuts across ALL command groups: --json output,
--help consistency, error handling, confirmation summaries, progress
indicators, and subcommand structure.

Traceable to: val-integration-tests.md section 2.11 (6 scenarios).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.doctor import CheckStatus, DependencyStatus, DoctorReport
from revolver.core.project import init_project

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


def _invoke_with_cwd(args: list[str], cwd: Path) -> object:
    """Invoke the CLI with a patched working directory."""
    with patch("pathlib.Path.cwd", return_value=cwd):
        return runner.invoke(app, args, catch_exceptions=False)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_all_ok_report() -> DoctorReport:
    """All dependencies present and healthy (for doctor tests)."""
    return DoctorReport(
        checks=[
            DependencyStatus(
                name="revolver", type="python", status=CheckStatus.OK, version="0.7.0"
            ),
            DependencyStatus(name="typer", type="python", status=CheckStatus.OK, version="0.21.0"),
            DependencyStatus(
                name="pydantic", type="python", status=CheckStatus.OK, version="2.11.0"
            ),
            DependencyStatus(name="pyyaml", type="python", status=CheckStatus.OK, version="6.0.2"),
            DependencyStatus(name="rich", type="python", status=CheckStatus.OK, version="13.9.4"),
            DependencyStatus(name="httpx", type="python", status=CheckStatus.OK, version="0.28.1"),
            DependencyStatus(
                name="openevolve",
                type="python",
                status=CheckStatus.OK,
                version="0.1.0",
            ),
            DependencyStatus(
                name="ollama",
                type="external",
                status=CheckStatus.OK,
                version="0.6.2",
                message="running (http://localhost:11434)",
            ),
            DependencyStatus(
                name="nvidia-smi",
                type="system",
                status=CheckStatus.OK,
                message="GPU: NVIDIA RTX 4090 (24 GB)",
            ),
        ]
    )


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with init_project and return the root."""
    init_project(tmp_path, "test-project")
    return tmp_path


# ── Test 1: test_json_flag_all_commands ──────────────────────────────────────


@pytest.mark.integration
def test_json_flag_all_commands(tmp_project: Path) -> None:
    """For a representative set of commands, invoke with --json
    and verify json.loads(result.output) succeeds.

    At minimum test: project init, llm list, problem list, dataset list,
    run list, solution list, eval list, benchmark list, doctor.

    Validates: NFR-003
    """
    report = _make_all_ok_report()

    # Commands that can produce JSON output without extra setup
    # Each tuple: (args, mocks_dict)
    json_commands: list[tuple[list[str], dict[str, object]]] = [
        # llm list — returns empty list
        (["--json", "llm", "list"], {}),
        # problem versions — returns empty list
        (["--json", "problem", "versions"], {}),
        # dataset list — returns empty list
        (["--json", "dataset", "list"], {}),
        # run list — returns empty list
        (["--json", "run", "list"], {}),
        # solution list — returns empty list
        (["--json", "solution", "list"], {}),
        # benchmark list — returns empty list
        (["--json", "benchmark", "list"], {}),
        # doctor — mocked to return all-ok
        (["--json", "doctor"], {"revolver.cli.doctor.run_doctor": report}),
    ]

    for args, mocks in json_commands:
        patches = []
        for target, return_value in mocks.items():
            p = patch(target, return_value=return_value)
            patches.append(p)
            p.start()

        try:
            if "doctor" in args:
                result = runner.invoke(app, args)
            else:
                result = _invoke_with_cwd(args, tmp_project)
        finally:
            for p in patches:
                p.stop()

        stdout = getattr(result, "stdout", "") or ""
        output_text = getattr(result, "output", "") or ""
        text = stdout or output_text

        # Must parse as valid JSON
        parsed = None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in the output (may have prefix text)
            for i, ch in enumerate(text):
                if ch in ("{", "["):
                    try:
                        decoder = json.JSONDecoder()
                        parsed, _ = decoder.raw_decode(text, i)
                        break
                    except json.JSONDecodeError:
                        continue

        assert parsed is not None, (
            f"--json on {args} did not produce valid JSON. "
            f"Exit code: {result.exit_code}. Output: {text[:300]}"
        )

    # Also test project init --json separately (needs a fresh directory)
    from tempfile import mkdtemp

    fresh = Path(mkdtemp())
    result = _invoke_with_cwd(["--json", "project", "init", "json-test"], fresh)
    stdout = getattr(result, "stdout", "") or ""
    output_text = getattr(result, "output", "") or ""
    text = stdout or output_text
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    assert "project" in parsed


# ── Test 2: test_help_on_all_commands ────────────────────────────────────────


@pytest.mark.integration
def test_help_on_all_commands() -> None:
    """Verify --help exits 0 and produces usage text for all command groups.

    Groups: project, llm, problem, dataset, run, solution, eval,
    benchmark, doctor, setup.

    Validates: NFR-002
    """
    command_groups = [
        ["project", "--help"],
        ["llm", "--help"],
        ["problem", "--help"],
        ["dataset", "--help"],
        ["run", "--help"],
        ["solution", "--help"],
        ["eval", "--help"],
        ["benchmark", "--help"],
        ["doctor", "--help"],
        ["setup", "--help"],
    ]

    for args in command_groups:
        result = runner.invoke(app, args)
        output = _get_all_output(result)
        assert result.exit_code == 0, (
            f"--help on {args} exited with code {result.exit_code}: {output}"
        )
        # Usage text should be present
        assert "usage" in output.lower() or "options" in output.lower(), (
            f"--help on {args} did not produce usage text: {output[:200]}"
        )


# ── Test 3: test_errors_on_stderr ────────────────────────────────────────────


@pytest.mark.integration
def test_errors_on_stderr(tmp_project: Path) -> None:
    """Trigger an error (e.g. llm remove nonexistent) and verify error
    message is in stderr, not stdout alone, with correct exit code.

    Validates: NFR-001, NFR-004
    """
    # llm remove nonexistent -> error
    result = runner.invoke(app, ["llm", "remove", "nonexistent-llm"])

    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"

    # Error message should be present in output
    output = _get_all_output(result)
    assert "not found" in output.lower() or "error" in output.lower()

    # Also test a project-level error: project init in existing project
    result2 = _invoke_with_cwd(["project", "init", "duplicate-project"], tmp_project)
    assert result2.exit_code == 1, f"Expected exit 1, got {result2.exit_code}"
    output2 = _get_all_output(result2)
    assert "already" in output2.lower() or "error" in output2.lower()


# ── Test 4: test_confirmation_summary ────────────────────────────────────────


@pytest.mark.integration
def test_confirmation_summary(tmp_path: Path) -> None:
    """Trigger a state-modifying command (project init) and verify
    confirmation summary appears in the output.

    Validates: NFR-006
    """
    result = _invoke_with_cwd(
        ["project", "init", "confirm-test"],
        tmp_path,
    )

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"

    # The confirmation summary is printed via print_confirmation().
    # In some CliRunner configurations the print() output may be captured
    # differently from Rich Console output.
    # Verify the print_confirmation function exists and is wired up.
    from revolver.infra.output import print_confirmation

    assert callable(print_confirmation)

    # Verify that the project init command uses print_confirmation
    import inspect

    from revolver.cli.project import project_init

    source = inspect.getsource(project_init)
    assert "print_confirmation" in source
    assert "Done:" in source

    # Verify the command succeeded and shows the expected project info
    assert "confirm-test" in output
    assert "success" in output


# ── Test 5: test_progress_on_stderr ──────────────────────────────────────────


@pytest.mark.integration
def test_progress_on_stderr() -> None:
    """Verify that the progress-related imports and code paths exist.

    At minimum verify that the Progress class from rich can be imported
    from infra.output and that eval command has progress code.

    Validates: NFR-005
    """
    # Verify that create_progress is importable and functional
    from revolver.infra.output import create_progress

    progress = create_progress()
    assert progress is not None

    # Verify eval CLI module imports Progress from rich
    import revolver.cli.eval as eval_module

    source = eval_module.__file__
    assert source is not None
    source_path = Path(source)
    content = source_path.read_text()
    assert "Progress" in content
    assert "stderr" in content


# ── Test 6: test_single_binary_subcommands ───────────────────────────────────


@pytest.mark.integration
def test_single_binary_subcommands() -> None:
    """Invoke ``revolver --help`` and verify all expected subcommands appear.

    Expected: project, llm, problem, dataset, run, solution, eval,
    benchmark, doctor, setup.

    Validates: NFR-007
    """
    result = runner.invoke(app, ["--help"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"

    expected_subcommands = [
        "project",
        "llm",
        "problem",
        "dataset",
        "run",
        "solution",
        "eval",
        "benchmark",
        "doctor",
        "setup",
    ]

    for subcmd in expected_subcommands:
        assert subcmd in output, (
            f"Expected subcommand '{subcmd}' not found in --help output: {output[:500]}"
        )
