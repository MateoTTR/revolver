"""L2 integration tests for ``revolver setup`` command.

Tests the CLI command end-to-end through Typer's CliRunner, mocking
the ``revolver.core.setup`` and ``revolver.core.doctor`` boundary
functions to control install plan computation and execution.

Traceable to: val-integration-tests.md section 2.9 (setup scenarios).
"""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.doctor import CheckStatus, DependencyStatus, DoctorReport
from revolver.core.setup import (
    InstallItem,
    InstallMethod,
    InstallPlan,
    InstallResult,
)

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


# ── Helper: doctor reports for different scenarios ───────────────────────────


def _make_all_ok_report() -> DoctorReport:
    """All dependencies satisfied."""
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


def _make_report_missing_openevolve() -> DoctorReport:
    """OpenEvolve is missing (fixable via pip)."""
    report = _make_all_ok_report()
    for check in report.checks:
        if check.name == "openevolve":
            check.status = CheckStatus.FAIL
            check.version = None
            check.message = "not installed"
            check.fixable = True
            break
    return report


def _make_report_missing_ollama_conda() -> DoctorReport:
    """Ollama missing, with conda available (FAIL, fixable)."""
    report = _make_all_ok_report()
    for check in report.checks:
        if check.name == "ollama":
            check.status = CheckStatus.FAIL
            check.version = None
            check.message = "not found. Run `revolver setup` to install via conda-forge."
            check.fixable = True
            break
    return report


def _make_report_missing_ollama_no_conda() -> DoctorReport:
    """Ollama missing, no conda available (WARN, not fixable)."""
    report = _make_all_ok_report()
    for check in report.checks:
        if check.name == "ollama":
            check.status = CheckStatus.WARN
            check.version = None
            check.message = (
                "not found. Install from https://ollama.com"
                " or activate a conda environment and run `revolver setup`."
            )
            check.fixable = False
            break
    return report


def _make_report_missing_nvidia() -> DoctorReport:
    """nvidia-smi missing (WARN, system, not fixable)."""
    report = _make_all_ok_report()
    for check in report.checks:
        if check.name == "nvidia-smi":
            check.status = CheckStatus.WARN
            check.version = None
            check.message = "not found"
            check.fixable = False
            break
    return report


# ── Test 1: test_setup_dry_run ───────────────────────────────────────────────


@pytest.mark.integration
def test_setup_dry_run() -> None:
    """--dry-run: shows plan, no installations, exit 0.

    Validates: FR-SET-011
    """
    report = _make_report_missing_openevolve()
    managers = {"pip": True, "conda": False, "mamba": False}
    plan = InstallPlan(
        items=[
            InstallItem(
                name="openevolve",
                method=InstallMethod.PIP,
                command="pip install openevolve",
            ),
        ]
    )

    with (
        patch("revolver.cli.setup.run_doctor", return_value=report),
        patch("revolver.cli.setup.detect_package_managers", return_value=managers),
        patch("revolver.cli.setup.compute_install_plan", return_value=plan),
        patch("revolver.cli.setup.execute_install_plan") as mock_execute,
    ):
        result = runner.invoke(app, ["setup", "--dry-run"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Plan should be displayed
    assert "openevolve" in output.lower()
    # "dry run" message should appear
    assert "dry run" in output.lower() or "no changes" in output.lower()
    # execute_install_plan should NOT have been called (dry_run bypasses it)
    mock_execute.assert_not_called()


# ── Test 2: test_setup_installs_missing_pip ──────────────────────────────────


@pytest.mark.integration
def test_setup_installs_missing_pip() -> None:
    """Missing pip package: mocked pip install succeeds.

    Validates: FR-SET-007
    """
    report = _make_report_missing_openevolve()
    post_report = _make_all_ok_report()
    managers = {"pip": True, "conda": False, "mamba": False}
    plan = InstallPlan(
        items=[
            InstallItem(
                name="openevolve",
                method=InstallMethod.PIP,
                command="pip install openevolve",
            ),
        ]
    )
    results = [InstallResult(name="openevolve", success=True)]

    with (
        patch("revolver.cli.setup.run_doctor", side_effect=[report, post_report]),
        patch("revolver.cli.setup.detect_package_managers", return_value=managers),
        patch("revolver.cli.setup.compute_install_plan", return_value=plan),
        patch("revolver.cli.setup.execute_install_plan", return_value=results),
    ):
        result = runner.invoke(app, ["setup", "--force"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "openevolve" in output.lower()
    assert "done" in output.lower() or "satisfied" in output.lower()


# ── Test 3: test_setup_asks_confirmation ─────────────────────────────────────


@pytest.mark.integration
def test_setup_asks_confirmation() -> None:
    """Without --force: confirmation prompt appears.

    Validates: FR-SET-008
    """
    report = _make_report_missing_openevolve()
    post_report = _make_all_ok_report()
    managers = {"pip": True, "conda": False, "mamba": False}
    plan = InstallPlan(
        items=[
            InstallItem(
                name="openevolve",
                method=InstallMethod.PIP,
                command="pip install openevolve",
            ),
        ]
    )
    results = [InstallResult(name="openevolve", success=True)]

    interactive_runner = CliRunner()
    with (
        patch("revolver.cli.setup.run_doctor", side_effect=[report, post_report]),
        patch("revolver.cli.setup.detect_package_managers", return_value=managers),
        patch("revolver.cli.setup.compute_install_plan", return_value=plan),
        patch("revolver.cli.setup.execute_install_plan", return_value=results),
    ):
        result = interactive_runner.invoke(app, ["setup"], input="y\n")

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Prompt text should have appeared
    assert "proceed" in output.lower() or "confirm" in output.lower()


# ── Test 4: test_setup_force_skips_confirmation ──────────────────────────────


@pytest.mark.integration
def test_setup_force_skips_confirmation() -> None:
    """--force: no confirmation prompt.

    Validates: FR-SET-008 (--force bypass)
    """
    report = _make_report_missing_openevolve()
    post_report = _make_all_ok_report()
    managers = {"pip": True, "conda": False, "mamba": False}
    plan = InstallPlan(
        items=[
            InstallItem(
                name="openevolve",
                method=InstallMethod.PIP,
                command="pip install openevolve",
            ),
        ]
    )
    results = [InstallResult(name="openevolve", success=True)]

    with (
        patch("revolver.cli.setup.run_doctor", side_effect=[report, post_report]),
        patch("revolver.cli.setup.detect_package_managers", return_value=managers),
        patch("revolver.cli.setup.compute_install_plan", return_value=plan),
        patch("revolver.cli.setup.execute_install_plan", return_value=results),
    ):
        # No input needed — --force skips the prompt
        result = runner.invoke(app, ["setup", "--force"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # "Proceed?" prompt should NOT appear with --force
    assert "proceed?" not in output.lower()


# ── Test 5: test_setup_instructions_for_non_fixable ──────────────────────────


@pytest.mark.integration
def test_setup_instructions_for_non_fixable() -> None:
    """System dep missing: shows instructions only.

    Validates: FR-SET-009, FR-SET-010
    """
    report = _make_report_missing_nvidia()
    managers = {"pip": True, "conda": False, "mamba": False}
    plan = InstallPlan(
        items=[],
        manual_instructions=[
            "nvidia-smi: Install NVIDIA drivers for GPU support."
            " Local LLM inference requires a compatible GPU."
            " Remote-only workflows will still work without GPU."
        ],
    )

    with (
        patch("revolver.cli.setup.run_doctor", return_value=report),
        patch("revolver.cli.setup.detect_package_managers", return_value=managers),
        patch("revolver.cli.setup.compute_install_plan", return_value=plan),
    ):
        result = runner.invoke(app, ["setup"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "nvidia" in output.lower()
    assert "driver" in output.lower() or "gpu" in output.lower()


# ── Test 6: test_setup_ollama_via_conda ──────────────────────────────────────


@pytest.mark.integration
def test_setup_ollama_via_conda() -> None:
    """Conda detected + ollama missing: proposes conda install.

    Validates: FR-SET-015, FR-SET-016
    """
    report = _make_report_missing_ollama_conda()
    post_report = _make_all_ok_report()
    managers = {"pip": True, "conda": True, "mamba": False}
    plan = InstallPlan(
        items=[
            InstallItem(
                name="ollama",
                method=InstallMethod.CONDA,
                command="conda install -y conda-forge::ollama",
            ),
        ]
    )
    results = [InstallResult(name="ollama", success=True)]

    with (
        patch("revolver.cli.setup.run_doctor", side_effect=[report, post_report]),
        patch("revolver.cli.setup.detect_package_managers", return_value=managers),
        patch("revolver.cli.setup.compute_install_plan", return_value=plan),
        patch("revolver.cli.setup.execute_install_plan", return_value=results),
    ):
        result = runner.invoke(app, ["setup", "--force"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "ollama" in output.lower()


# ── Test 7: test_setup_manual_instructions_no_conda ──────────────────────────


@pytest.mark.integration
def test_setup_manual_instructions_no_conda() -> None:
    """No conda + ollama missing: manual instructions.

    Validates: FR-SET-017
    """
    report = _make_report_missing_ollama_no_conda()
    managers = {"pip": True, "conda": False, "mamba": False}
    plan = InstallPlan(
        items=[
            InstallItem(
                name="ollama",
                method=InstallMethod.MANUAL,
            ),
        ],
        manual_instructions=[
            "ollama: Install from https://ollama.com/download"
            " or activate a conda environment and re-run `revolver setup`"
        ],
    )

    with (
        patch("revolver.cli.setup.run_doctor", return_value=report),
        patch("revolver.cli.setup.detect_package_managers", return_value=managers),
        patch("revolver.cli.setup.compute_install_plan", return_value=plan),
    ):
        result = runner.invoke(app, ["setup"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Should show manual installation guidance
    assert "ollama" in output.lower()
    assert (
        "no conda" in output.lower() or "manual" in output.lower() or "install" in output.lower()
    )
