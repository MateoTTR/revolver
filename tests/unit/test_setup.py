"""L1 unit tests for revolver.core.setup — assisted installation."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from revolver.core.doctor import CheckStatus, DependencyStatus, DoctorReport
from revolver.core.setup import (
    InstallItem,
    InstallMethod,
    InstallPlan,
    compute_install_plan,
    detect_package_managers,
    execute_install_plan,
    run_setup,
)

# ── detect_package_managers ───────────────────────────────────────────────────


@pytest.mark.unit
def test_detects_pip_always() -> None:
    """detect_package_managers always reports pip as available."""
    with (
        patch("revolver.core.setup.subprocess.run", side_effect=FileNotFoundError),
    ):
        managers = detect_package_managers()

    assert managers["pip"] is True


@pytest.mark.unit
def test_detects_conda() -> None:
    """detect_package_managers detects conda when available."""
    fake_conda = subprocess.CompletedProcess(
        args=["conda", "--version"],
        returncode=0,
        stdout="conda 24.1.0\n",
        stderr="",
    )
    fake_mamba_fail = FileNotFoundError("mamba")

    def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "conda":
            return fake_conda
        raise fake_mamba_fail

    with patch("revolver.core.setup.subprocess.run", side_effect=mock_run):
        managers = detect_package_managers()

    assert managers["conda"] is True
    assert managers["mamba"] is False


@pytest.mark.unit
def test_detects_mamba() -> None:
    """detect_package_managers detects mamba when available."""
    fake_conda = subprocess.CompletedProcess(
        args=["conda", "--version"],
        returncode=0,
        stdout="conda 24.1.0\n",
        stderr="",
    )
    fake_mamba = subprocess.CompletedProcess(
        args=["mamba", "--version"],
        returncode=0,
        stdout="mamba 1.5.0\n",
        stderr="",
    )

    def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "conda":
            return fake_conda
        if cmd[0] == "mamba":
            return fake_mamba
        raise FileNotFoundError(cmd[0])

    with patch("revolver.core.setup.subprocess.run", side_effect=mock_run):
        managers = detect_package_managers()

    assert managers["conda"] is True
    assert managers["mamba"] is True


@pytest.mark.unit
def test_no_conda_no_mamba() -> None:
    """detect_package_managers reports False when neither conda nor mamba available."""
    with patch("revolver.core.setup.subprocess.run", side_effect=FileNotFoundError):
        managers = detect_package_managers()

    assert managers["conda"] is False
    assert managers["mamba"] is False


# ── compute_install_plan ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_plan_for_missing_python_dep() -> None:
    """compute_install_plan includes pip install for missing Python deps."""
    report = DoctorReport(
        checks=[
            DependencyStatus(
                name="openevolve",
                type="python",
                status=CheckStatus.FAIL,
                message="not installed",
                fixable=True,
            ),
        ]
    )
    managers = {"pip": True, "conda": False, "mamba": False}
    plan = compute_install_plan(report, managers)

    assert len(plan.items) == 1
    assert plan.items[0].name == "openevolve"
    assert plan.items[0].method == InstallMethod.PIP
    assert "pip install" in plan.items[0].command


@pytest.mark.unit
def test_plan_ollama_with_conda() -> None:
    """compute_install_plan proposes conda install for Ollama when conda detected."""
    report = DoctorReport(
        checks=[
            DependencyStatus(
                name="ollama",
                type="external",
                status=CheckStatus.FAIL,
                message="not found",
                fixable=True,
            ),
        ]
    )
    managers = {"pip": True, "conda": True, "mamba": False}
    plan = compute_install_plan(report, managers)

    assert len(plan.items) == 1
    assert plan.items[0].name == "ollama"
    assert plan.items[0].method == InstallMethod.CONDA
    assert "conda install" in plan.items[0].command
    assert "conda-forge::ollama" in plan.items[0].command


@pytest.mark.unit
def test_plan_ollama_with_mamba() -> None:
    """compute_install_plan prefers mamba over conda when both available."""
    report = DoctorReport(
        checks=[
            DependencyStatus(
                name="ollama",
                type="external",
                status=CheckStatus.FAIL,
                message="not found",
                fixable=True,
            ),
        ]
    )
    managers = {"pip": True, "conda": True, "mamba": True}
    plan = compute_install_plan(report, managers)

    assert plan.items[0].method == InstallMethod.CONDA
    assert "mamba install" in plan.items[0].command


@pytest.mark.unit
def test_plan_ollama_no_conda() -> None:
    """compute_install_plan provides manual instructions when no conda."""
    report = DoctorReport(
        checks=[
            DependencyStatus(
                name="ollama",
                type="external",
                status=CheckStatus.FAIL,
                message="not found",
                fixable=True,
            ),
        ]
    )
    managers = {"pip": True, "conda": False, "mamba": False}
    plan = compute_install_plan(report, managers)

    assert plan.items[0].method == InstallMethod.MANUAL
    assert len(plan.manual_instructions) == 1
    assert "https://ollama.com/download" in plan.manual_instructions[0]


@pytest.mark.unit
def test_plan_never_installs_system_pkg() -> None:
    """compute_install_plan never auto-installs system-level deps."""
    report = DoctorReport(
        checks=[
            DependencyStatus(
                name="nvidia-smi",
                type="system",
                status=CheckStatus.WARN,
                message="not found",
                fixable=False,
            ),
        ]
    )
    managers = {"pip": True, "conda": True, "mamba": False}
    plan = compute_install_plan(report, managers)

    # No auto-installable items
    assert not any(item.method in (InstallMethod.PIP, InstallMethod.CONDA) for item in plan.items)
    # But manual instructions should mention drivers
    assert len(plan.manual_instructions) == 1
    assert "NVIDIA drivers" in plan.manual_instructions[0]


@pytest.mark.unit
def test_plan_reports_install_method() -> None:
    """compute_install_plan reports install method for each dependency."""
    report = DoctorReport(
        checks=[
            DependencyStatus(
                name="openevolve",
                type="python",
                status=CheckStatus.FAIL,
                message="not installed",
                fixable=True,
            ),
            DependencyStatus(
                name="ollama",
                type="external",
                status=CheckStatus.FAIL,
                message="not found",
                fixable=True,
            ),
        ]
    )
    managers = {"pip": True, "conda": True, "mamba": False}
    plan = compute_install_plan(report, managers)

    oe_item = next(i for i in plan.items if i.name == "openevolve")
    ollama_item = next(i for i in plan.items if i.name == "ollama")

    assert oe_item.method == InstallMethod.PIP
    assert ollama_item.method == InstallMethod.CONDA


@pytest.mark.unit
def test_plan_optional_backend_never_auto_installed() -> None:
    """compute_install_plan reports optional backends (INFO) as manual-only.

    Validates: FR-SET-002 — an absent optional evolution backend
    (ShinkaEvolve) is never auto-installed; its install instruction is
    surfaced separately and does not count as an installable issue.
    """
    report = DoctorReport(
        checks=[
            DependencyStatus(
                name="shinkaevolve",
                type="python",
                status=CheckStatus.INFO,
                message="not installed (optional). Install with: pip install 'revolver[shinka]'",
                fixable=False,
            ),
        ]
    )
    managers = {"pip": True, "conda": True, "mamba": False}
    plan = compute_install_plan(report, managers)

    assert plan.items == []
    assert plan.has_installable is False
    assert plan.manual_instructions == []
    assert len(plan.optional_instructions) == 1
    assert plan.optional_instructions[0].startswith("shinkaevolve:")
    assert "revolver[shinka]" in plan.optional_instructions[0]


@pytest.mark.unit
def test_plan_installed_optional_backend_not_listed() -> None:
    """compute_install_plan drops the shinka entry once installed (S14-15).

    Validates: FR-SET-002 — with the shinka extra installed the doctor
    entry is a plain OK check, so setup must list neither an install
    item nor an optional instruction for it.
    """
    report = DoctorReport(
        checks=[
            DependencyStatus(
                name="shinkaevolve",
                type="python",
                status=CheckStatus.OK,
                version="0.0.7",
                fixable=True,
            ),
        ]
    )
    managers = {"pip": True, "conda": True, "mamba": False}
    plan = compute_install_plan(report, managers)

    assert plan.items == []
    assert plan.has_installable is False
    assert plan.manual_instructions == []
    assert plan.optional_instructions == []


@pytest.mark.unit
def test_plan_ok_deps_skipped() -> None:
    """compute_install_plan skips deps with OK status."""
    report = DoctorReport(
        checks=[
            DependencyStatus(
                name="typer",
                type="python",
                status=CheckStatus.OK,
                version="0.21.0",
                fixable=True,
            ),
        ]
    )
    managers = {"pip": True, "conda": False, "mamba": False}
    plan = compute_install_plan(report, managers)

    assert len(plan.items) == 0


# ── execute_install_plan ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_dry_run_no_side_effects() -> None:
    """execute_install_plan with dry_run does not call subprocess."""
    plan = InstallPlan(
        items=[
            InstallItem(
                name="openevolve",
                method=InstallMethod.PIP,
                command="pip install openevolve",
            ),
        ]
    )

    with patch("revolver.core.setup.subprocess.run") as mock_run:
        results = execute_install_plan(plan, dry_run=True)

    mock_run.assert_not_called()
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].version == "(dry run)"


@pytest.mark.unit
def test_execute_pip_success() -> None:
    """execute_install_plan installs via pip successfully."""
    plan = InstallPlan(
        items=[
            InstallItem(
                name="openevolve",
                method=InstallMethod.PIP,
                command="pip install openevolve",
            ),
        ]
    )

    fake_result = subprocess.CompletedProcess(
        args=["pip", "install", "openevolve"],
        returncode=0,
        stdout="Successfully installed openevolve-0.2.0\n",
        stderr="",
    )
    with patch("revolver.core.setup.subprocess.run", return_value=fake_result):
        results = execute_install_plan(plan, dry_run=False)

    assert len(results) == 1
    assert results[0].success is True


@pytest.mark.unit
def test_execute_pip_failure() -> None:
    """execute_install_plan reports failure when pip install fails."""
    plan = InstallPlan(
        items=[
            InstallItem(
                name="openevolve",
                method=InstallMethod.PIP,
                command="pip install openevolve",
            ),
        ]
    )

    fake_result = subprocess.CompletedProcess(
        args=["pip", "install", "openevolve"],
        returncode=1,
        stdout="",
        stderr="ERROR: No matching distribution found",
    )
    with patch("revolver.core.setup.subprocess.run", return_value=fake_result):
        results = execute_install_plan(plan, dry_run=False)

    assert len(results) == 1
    assert results[0].success is False
    assert "pip install failed" in (results[0].error or "")


@pytest.mark.unit
def test_execute_conda_success() -> None:
    """execute_install_plan installs via conda successfully."""
    plan = InstallPlan(
        items=[
            InstallItem(
                name="ollama",
                method=InstallMethod.CONDA,
                command="conda install -y conda-forge::ollama",
            ),
        ]
    )

    fake_result = subprocess.CompletedProcess(
        args=["conda", "install", "-y", "conda-forge::ollama"],
        returncode=0,
        stdout="",
        stderr="",
    )
    with patch("revolver.core.setup.subprocess.run", return_value=fake_result):
        results = execute_install_plan(plan, dry_run=False)

    assert len(results) == 1
    assert results[0].success is True


@pytest.mark.unit
def test_execute_manual_items_skipped() -> None:
    """execute_install_plan does not execute manual items."""
    plan = InstallPlan(
        items=[
            InstallItem(
                name="ollama",
                method=InstallMethod.MANUAL,
            ),
        ]
    )

    with patch("revolver.core.setup.subprocess.run") as mock_run:
        results = execute_install_plan(plan, dry_run=False)

    mock_run.assert_not_called()
    assert len(results) == 0


@pytest.mark.unit
def test_execute_pip_force_reinstall() -> None:
    """execute_install_plan adds --force-reinstall when force=True."""
    plan = InstallPlan(
        items=[
            InstallItem(
                name="openevolve",
                method=InstallMethod.PIP,
                command="pip install openevolve",
            ),
        ]
    )

    fake_result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="",
        stderr="",
    )
    with patch("revolver.core.setup.subprocess.run", return_value=fake_result) as mock_run:
        execute_install_plan(plan, dry_run=False, force=True)

    # Verify --force-reinstall was added
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert "--force-reinstall" in cmd


@pytest.mark.unit
def test_install_plan_has_installable() -> None:
    """InstallPlan.has_installable returns True when auto-installable items exist."""
    plan_auto = InstallPlan(
        items=[InstallItem(name="x", method=InstallMethod.PIP, command="pip install x")]
    )
    plan_manual = InstallPlan(items=[InstallItem(name="y", method=InstallMethod.MANUAL)])
    plan_empty = InstallPlan()

    assert plan_auto.has_installable is True
    assert plan_manual.has_installable is False
    assert plan_empty.has_installable is False


# ── run_setup integration ────────────────────────────────────────────────────


@pytest.mark.unit
def test_run_setup_dry_run() -> None:
    """run_setup with dry_run does not execute installations."""
    mock_report = DoctorReport(
        checks=[
            DependencyStatus(
                name="openevolve",
                type="python",
                status=CheckStatus.FAIL,
                message="not installed",
                fixable=True,
            ),
        ]
    )

    no_conda = {"pip": True, "conda": False, "mamba": False}
    with (
        patch("revolver.core.setup.run_doctor", return_value=mock_report),
        patch("revolver.core.setup.detect_package_managers", return_value=no_conda),
        patch("revolver.core.setup.subprocess.run") as mock_subprocess,
    ):
        _plan, results, post_report = run_setup(dry_run=True)

    # subprocess should not be called (only for detect, which is mocked)
    mock_subprocess.assert_not_called()
    assert len(results) == 1
    assert results[0].version == "(dry run)"
    # post_report should be same as initial (no re-run)
    assert post_report is mock_report


@pytest.mark.unit
def test_run_setup_executes_and_re_checks() -> None:
    """run_setup executes installations and re-runs doctor."""
    initial_report = DoctorReport(
        checks=[
            DependencyStatus(
                name="openevolve",
                type="python",
                status=CheckStatus.FAIL,
                message="not installed",
                fixable=True,
            ),
        ]
    )
    post_report = DoctorReport(
        checks=[
            DependencyStatus(
                name="openevolve",
                type="python",
                status=CheckStatus.OK,
                version="0.2.0",
                fixable=True,
            ),
        ]
    )

    fake_pip_result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="",
        stderr="",
    )

    call_count = 0

    def mock_run_doctor() -> DoctorReport:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return initial_report
        return post_report

    no_conda = {"pip": True, "conda": False, "mamba": False}
    with (
        patch("revolver.core.setup.run_doctor", side_effect=mock_run_doctor),
        patch("revolver.core.setup.detect_package_managers", return_value=no_conda),
        patch("revolver.core.setup.subprocess.run", return_value=fake_pip_result),
    ):
        _plan, _results, final_report = run_setup(dry_run=False, force=True)

    assert final_report.overall_status == CheckStatus.OK
    assert call_count == 2  # Initial + post-install verification
