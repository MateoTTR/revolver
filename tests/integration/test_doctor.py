"""L2 integration tests for ``revolver doctor`` command.

Tests the CLI command end-to-end through Typer's CliRunner, mocking
the ``revolver.core.doctor`` boundary functions to control dependency
check results.

Traceable to: val-integration-tests.md section 2.9 (doctor scenarios).
"""

from __future__ import annotations

import contextlib
import json
import re
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from revolver.cli import app
from revolver.core.doctor import CheckStatus, DependencyStatus, DoctorReport
from revolver.infra.backends.openevolve import OpenEvolveBackend
from revolver.infra.backends.shinka import ShinkaBackend
from revolver.infra.gpu import GpuInfo

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


# ── Helper: build a full DoctorReport ────────────────────────────────────────


def _make_all_ok_report() -> DoctorReport:
    """All dependencies present and healthy."""
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


# ── Test 1: test_doctor_all_ok ───────────────────────────────────────────────


@pytest.mark.integration
def test_doctor_all_ok() -> None:
    """All deps present: exit 0, all check marks in output.

    Validates: FR-SET-001..005
    """
    report = _make_all_ok_report()

    with patch("revolver.cli.doctor.run_doctor", return_value=report):
        result = runner.invoke(app, ["doctor"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Check mark (unicode \u2713) should appear for all OK checks
    assert "\u2713" in output
    assert "All checks passed" in output


# ── Test 2: test_doctor_missing_dep_fail ─────────────────────────────────────


@pytest.mark.integration
def test_doctor_missing_dep_fail() -> None:
    """OpenEvolve missing: exit 1, FAIL in output.

    Validates: FR-SET-002, FR-SET-005
    """
    report = _make_all_ok_report()
    # Make openevolve FAIL
    for check in report.checks:
        if check.name == "openevolve":
            check.status = CheckStatus.FAIL
            check.version = None
            check.message = "not installed"
            break

    with patch("revolver.cli.doctor.run_doctor", return_value=report):
        result = runner.invoke(app, ["doctor"])

    output = _get_all_output(result)
    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}: {output}"
    # Cross mark (unicode \u2717) should appear for FAIL
    assert "\u2717" in output
    assert "1 error" in output


# ── Test 3: test_doctor_warn_only ────────────────────────────────────────────


@pytest.mark.integration
def test_doctor_warn_only() -> None:
    """nvidia-smi missing (WARN): exit 0 (WARN doesn't cause exit 1).

    Validates: FR-SET-004, FR-SET-005
    """
    report = _make_all_ok_report()
    # Make nvidia-smi WARN
    for check in report.checks:
        if check.name == "nvidia-smi":
            check.status = CheckStatus.WARN
            check.version = None
            check.message = "not found"
            break

    with patch("revolver.cli.doctor.run_doctor", return_value=report):
        result = runner.invoke(app, ["doctor"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {output}"
    # Warning sign should appear
    assert "\u26a0" in output
    assert "1 warning" in output


# ── Test 4: test_doctor_json ─────────────────────────────────────────────────


@pytest.mark.integration
def test_doctor_json() -> None:
    """--json mode: valid JSON, has 'checks', 'status', 'errors', 'warnings' keys.

    Validates: NFR-003, FR-SET-013
    """
    report = _make_all_ok_report()

    with patch("revolver.cli.doctor.run_doctor", return_value=report):
        result = runner.invoke(app, ["--json", "doctor"])

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {_get_all_output(result)}"
    data = _parse_json_output(result)
    assert isinstance(data, dict)
    assert "checks" in data
    assert "status" in data
    assert "errors" in data
    assert "warnings" in data
    assert data["status"] == "ok"
    assert data["errors"] == 0
    assert data["warnings"] == 0
    assert isinstance(data["checks"], list)
    assert len(data["checks"]) >= 5


# ── Test 5: test_doctor_works_outside_project ────────────────────────────────


@pytest.mark.integration
def test_doctor_works_outside_project(tmp_path: object) -> None:
    """Run from tmp_path without .revolver/: still works.

    Validates: FR-SET-012
    """
    report = _make_all_ok_report()

    with (
        patch("revolver.cli.doctor.run_doctor", return_value=report),
        patch("pathlib.Path.cwd", return_value=tmp_path),
    ):
        result = runner.invoke(app, ["doctor"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "All checks passed" in output


# ── Test 6: test_doctor_reports_versions ─────────────────────────────────────


@pytest.mark.integration
def test_doctor_reports_versions() -> None:
    """Version strings appear in human output.

    Validates: FR-SET-013
    """
    report = _make_all_ok_report()

    with patch("revolver.cli.doctor.run_doctor", return_value=report):
        result = runner.invoke(app, ["doctor"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Version strings from the report should be visible
    assert "0.7.0" in output  # revolver
    assert "0.21.0" in output  # typer
    assert "0.6.2" in output  # ollama


# ── Test 7: test_doctor_ollama_missing ───────────────────────────────────────


@pytest.mark.integration
def test_doctor_ollama_missing() -> None:
    """Ollama missing: shows actionable message.

    Validates: FR-SET-003, FR-SET-005, FR-SET-006
    """
    report = _make_all_ok_report()
    # Make ollama WARN (no conda available case)
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

    with patch("revolver.cli.doctor.run_doctor", return_value=report):
        result = runner.invoke(app, ["doctor"])

    output = _get_all_output(result)
    # WARN-only so exit 0
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    # Should show actionable advice
    assert "ollama" in output.lower()
    assert "setup" in output.lower() or "install" in output.lower()


# ── Tests 8-9: ShinkaEvolve informational entry (FR-SET-002, S13-12) ─────────


def _healthy_env_patches(*, shinka_available: bool = False) -> list[object]:
    """Patches simulating a healthy environment for the REAL run_doctor.

    OpenEvolve availability is pinned (env-independent), Ollama/GPU/conda
    boundaries are mocked. ShinkaEvolve availability is pinned via
    *shinka_available* so these tests stay deterministic regardless of
    whether the optional shinka extra happens to be installed (the
    is_available() seam is the real import probe since S14 PR-B).
    """
    gpu = GpuInfo(name="NVIDIA RTX 4090", vram_used_mib=0, vram_total_mib=24576)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"version": "0.6.2"}
    mock_resp.raise_for_status = MagicMock()
    shinka_availability: tuple[bool, str | None] = (
        (True, None)
        if shinka_available
        else (False, "Install with: pip install 'revolver[shinka]'")
    )
    return [
        patch("revolver.core.doctor.importlib.metadata.version", return_value="1.0.0"),
        patch.object(OpenEvolveBackend, "is_available", return_value=(True, None)),
        patch.object(ShinkaBackend, "is_available", return_value=shinka_availability),
        patch("revolver.core.doctor.httpx.get", return_value=mock_resp),
        patch("revolver.core.doctor.get_gpu_info", return_value=gpu),
        patch("revolver.core.doctor._detect_conda", return_value=True),
    ]


@pytest.mark.integration
def test_doctor_shinka_informational() -> None:
    """ShinkaEvolve absent: informational entry, exit 0, overall OK.

    Validates: FR-SET-002, spec-setup error case "ShinkaEvolve not
    installed (optional backend)" — INFO, exit 0 (info only).
    """
    with contextlib.ExitStack() as stack:
        for p in _healthy_env_patches():
            stack.enter_context(p)
        result = runner.invoke(app, ["doctor"])

    output = _get_all_output(result)
    # Informational only — never a failure, exit 0
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "shinkaevolve" in output
    assert "optional" in output
    assert "revolver[shinka]" in output
    # No error/warning attributed to the optional backend
    assert "All checks passed" in output


@pytest.mark.integration
def test_doctor_json_includes_shinka_entry() -> None:
    """--json: additive shinkaevolve entry; openevolve entry unchanged.

    Validates: FR-SET-002 (additive entry, backward-compatible report shape).
    """
    with contextlib.ExitStack() as stack:
        for p in _healthy_env_patches():
            stack.enter_context(p)
        result = runner.invoke(app, ["--json", "doctor"])

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {_get_all_output(result)}"
    data = _parse_json_output(result)
    assert isinstance(data, dict)
    checks = {c["name"]: c for c in data["checks"]}

    # OpenEvolve entry keeps its pre-S13 name/status semantics
    assert checks["openevolve"]["status"] == "ok"
    assert checks["openevolve"]["type"] == "python"
    assert checks["openevolve"]["fixable"] is True

    # Additive ShinkaEvolve entry: informational, not fixable, no "error" key
    shinka = checks["shinkaevolve"]
    assert shinka["status"] == "info"
    assert shinka["type"] == "python"
    assert shinka["fixable"] is False
    assert "error" not in shinka
    assert "optional" in shinka["message"]
    assert "revolver[shinka]" in shinka["message"]

    # Informational entry does not degrade the overall report
    assert data["status"] == "ok"
    assert data["errors"] == 0
    assert data["warnings"] == 0


# ── Tests 10-11: ShinkaEvolve installed entry (FR-SET-002, S14-15) ───────────


@pytest.mark.integration
def test_doctor_shinka_installed() -> None:
    """ShinkaEvolve installed: regular OK entry with version, no hint.

    S14-15: ``ShinkaBackend.is_available()`` is a real import probe since
    PR-B. Availability is pinned via the backend seam (no shinka install
    needed) so this test passes on both shinka-less CI and dev machines
    with the extra; the doctor must report the backend like any other
    installed package check.

    Validates: FR-SET-002 (doctor reflects real Shinka availability).
    """
    with contextlib.ExitStack() as stack:
        for p in _healthy_env_patches(shinka_available=True):
            stack.enter_context(p)
        result = runner.invoke(app, ["doctor"])

    output = _get_all_output(result)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {output}"
    assert "shinkaevolve" in output
    # Version resolved via importlib.metadata (patched to 1.0.0)
    assert "1.0.0" in output
    # No informational not-installed message, no install hint
    assert "not installed (optional)" not in output
    assert "revolver[shinka]" not in output
    assert "All checks passed" in output


@pytest.mark.integration
def test_doctor_json_shinka_installed() -> None:
    """--json with shinka installed: OK entry, version, fixable, no message.

    Validates: FR-SET-002 (doctor reflects real Shinka availability).
    """
    with contextlib.ExitStack() as stack:
        for p in _healthy_env_patches(shinka_available=True):
            stack.enter_context(p)
        result = runner.invoke(app, ["--json", "doctor"])

    assert result.exit_code == 0, f"Exit code {result.exit_code}: {_get_all_output(result)}"
    data = _parse_json_output(result)
    assert isinstance(data, dict)
    checks = {c["name"]: c for c in data["checks"]}

    shinka = checks["shinkaevolve"]
    assert shinka["status"] == "ok"
    assert shinka["type"] == "python"
    assert shinka["version"] == "1.0.0"
    assert shinka["fixable"] is True
    assert "message" not in shinka
    assert "error" not in shinka

    assert data["status"] == "ok"
    assert data["errors"] == 0
    assert data["warnings"] == 0
