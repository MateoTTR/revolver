"""L1 unit tests for revolver.core.doctor — dependency health checks."""

from __future__ import annotations

import importlib.metadata
from unittest.mock import MagicMock, patch

import httpx
import pytest

from revolver.core.doctor import (
    CheckStatus,
    DependencyStatus,
    DoctorReport,
    _check_backend,
    _check_nvidia_smi,
    _check_ollama,
    _check_python_package,
    _check_revolver,
    run_doctor,
)
from revolver.infra.backends.loongflow import LoongFlowBackend
from revolver.infra.backends.openevolve import OpenEvolveBackend
from revolver.infra.backends.shinka import ShinkaBackend
from revolver.infra.gpu import GpuInfo

# ── DoctorReport dataclass ────────────────────────────────────────────────────


@pytest.mark.unit
def test_doctor_report_all_ok() -> None:
    """DoctorReport with all OK checks has OK overall status."""
    report = DoctorReport(
        checks=[
            DependencyStatus(name="a", type="python", status=CheckStatus.OK),
            DependencyStatus(name="b", type="python", status=CheckStatus.OK),
        ]
    )
    assert report.overall_status == CheckStatus.OK
    assert report.error_count == 0
    assert report.warning_count == 0


@pytest.mark.unit
def test_doctor_report_with_warnings() -> None:
    """DoctorReport with WARN checks has WARN overall status."""
    report = DoctorReport(
        checks=[
            DependencyStatus(name="a", type="python", status=CheckStatus.OK),
            DependencyStatus(name="b", type="system", status=CheckStatus.WARN),
        ]
    )
    assert report.overall_status == CheckStatus.WARN
    assert report.error_count == 0
    assert report.warning_count == 1


@pytest.mark.unit
def test_doctor_report_with_failures() -> None:
    """DoctorReport with FAIL checks has FAIL overall status."""
    report = DoctorReport(
        checks=[
            DependencyStatus(name="a", type="python", status=CheckStatus.OK),
            DependencyStatus(name="b", type="python", status=CheckStatus.FAIL),
            DependencyStatus(name="c", type="system", status=CheckStatus.WARN),
        ]
    )
    assert report.overall_status == CheckStatus.FAIL
    assert report.error_count == 1
    assert report.warning_count == 1


@pytest.mark.unit
def test_doctor_report_empty() -> None:
    """DoctorReport with no checks has OK overall status."""
    report = DoctorReport()
    assert report.overall_status == CheckStatus.OK
    assert report.error_count == 0
    assert report.warning_count == 0


@pytest.mark.unit
def test_doctor_report_info_not_counted() -> None:
    """INFO checks (optional backends) affect neither status nor counts."""
    report = DoctorReport(
        checks=[
            DependencyStatus(name="a", type="python", status=CheckStatus.OK),
            DependencyStatus(name="b", type="python", status=CheckStatus.INFO),
        ]
    )
    assert report.overall_status == CheckStatus.OK
    assert report.error_count == 0
    assert report.warning_count == 0


# ── Python package checks ────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_python_package_installed() -> None:
    """_check_python_package returns OK with version for installed package."""
    with patch("revolver.core.doctor.importlib.metadata.version", return_value="1.2.3"):
        result = _check_python_package("typer")

    assert result.status == CheckStatus.OK
    assert result.version == "1.2.3"
    assert result.type == "python"
    assert result.fixable is True


@pytest.mark.unit
def test_check_python_package_missing() -> None:
    """_check_python_package returns FAIL for missing package."""
    with patch(
        "revolver.core.doctor.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError("pkg"),
    ):
        result = _check_python_package("nonexistent")

    assert result.status == CheckStatus.FAIL
    assert result.message == "not installed"
    assert result.fixable is True


# ── Evolution backend checks (FR-SET-002) ───────────────────────────────────


@pytest.mark.unit
def test_check_openevolve_installed() -> None:
    """_check_backend('openevolve') returns OK when the backend is available."""
    with (
        patch.object(OpenEvolveBackend, "is_available", return_value=(True, None)),
        patch("revolver.core.doctor.importlib.metadata.version", return_value="0.2.0"),
    ):
        result = _check_backend("openevolve")

    assert result.status == CheckStatus.OK
    assert result.version == "0.2.0"
    assert result.name == "openevolve"
    assert result.fixable is True


@pytest.mark.unit
def test_check_openevolve_missing() -> None:
    """_check_backend('openevolve') returns FAIL when the backend is absent."""
    with patch.object(
        OpenEvolveBackend,
        "is_available",
        return_value=(False, "Install with: pip install 'revolver[openevolve]'"),
    ):
        result = _check_backend("openevolve")

    assert result.status == CheckStatus.FAIL
    assert result.message == "not installed"
    assert result.fixable is True


@pytest.mark.unit
def test_check_backend_shinka_informational() -> None:
    """_check_backend('shinka') reports INFO (optional, not a failure).

    Availability is pinned to not-installed via the is_available() seam
    (a real import probe since S14 PR-B) so the test stays deterministic
    on machines where the optional shinka extra happens to be installed.
    """
    with patch.object(
        ShinkaBackend,
        "is_available",
        return_value=(False, "Install with: pip install 'revolver[shinka]'"),
    ):
        result = _check_backend("shinka")

    assert result.status == CheckStatus.INFO
    assert result.name == "shinkaevolve"
    assert result.type == "python"
    assert result.fixable is False
    assert "optional" in (result.message or "")
    assert "revolver[shinka]" in (result.message or "")


@pytest.mark.unit
def test_check_backend_shinka_installed() -> None:
    """_check_backend('shinka') reports OK with version when installed.

    S14-15: with the shinka extra installed, the doctor entry becomes a
    regular OK package check (version from the 'shinka-evolve'
    distribution metadata, no install hint).
    """
    with (
        patch.object(ShinkaBackend, "is_available", return_value=(True, None)),
        patch(
            "revolver.core.doctor.importlib.metadata.version", return_value="0.0.7"
        ) as mock_version,
    ):
        result = _check_backend("shinka")

    assert result.status == CheckStatus.OK
    assert result.name == "shinkaevolve"
    assert result.type == "python"
    assert result.version == "0.0.7"
    assert result.fixable is True
    assert result.message is None
    # Version is looked up under the PyPI distribution name, not the
    # backend or check name (the package ships as 'shinka-evolve').
    mock_version.assert_called_once_with("shinka-evolve")


@pytest.mark.unit
def test_check_backend_shinka_installed_without_metadata() -> None:
    """Importable shinka without package metadata: OK with version=None."""
    with (
        patch.object(ShinkaBackend, "is_available", return_value=(True, None)),
        patch(
            "revolver.core.doctor.importlib.metadata.version",
            side_effect=importlib.metadata.PackageNotFoundError("shinka-evolve"),
        ),
    ):
        result = _check_backend("shinka")

    assert result.status == CheckStatus.OK
    assert result.version is None


# ── Ollama check ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_ollama_running() -> None:
    """_check_ollama returns OK when Ollama API responds."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"version": "0.6.2"}
    mock_resp.raise_for_status = MagicMock()

    with patch("revolver.core.doctor.httpx.get", return_value=mock_resp):
        result = _check_ollama()

    assert result.status == CheckStatus.OK
    assert result.version == "0.6.2"
    assert result.type == "external"


@pytest.mark.unit
def test_check_ollama_not_running_with_conda() -> None:
    """_check_ollama returns FAIL when conda available (fixable)."""
    with patch("revolver.core.doctor.httpx.get", side_effect=httpx.ConnectError("refused")):
        result = _check_ollama(has_conda=True)

    assert result.status == CheckStatus.FAIL
    assert "not found" in (result.message or "")
    assert result.fixable is True


@pytest.mark.unit
def test_check_ollama_not_running_without_conda() -> None:
    """_check_ollama returns WARN when no conda (not fixable)."""
    with patch("revolver.core.doctor.httpx.get", side_effect=httpx.ConnectError("refused")):
        result = _check_ollama(has_conda=False)

    assert result.status == CheckStatus.WARN
    assert "not found" in (result.message or "")
    assert result.fixable is False


@pytest.mark.unit
def test_check_ollama_timeout() -> None:
    """_check_ollama returns WARN on timeout."""
    with patch(
        "revolver.core.doctor.httpx.get",
        side_effect=httpx.TimeoutException("timed out"),
    ):
        result = _check_ollama()

    assert result.status == CheckStatus.WARN


# ── nvidia-smi check ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_nvidia_smi_available() -> None:
    """_check_nvidia_smi returns OK with GPU info when nvidia-smi works."""
    gpu = GpuInfo(name="NVIDIA GeForce RTX 5090", vram_used_mib=1024, vram_total_mib=32768)
    with patch("revolver.core.doctor.get_gpu_info", return_value=gpu):
        result = _check_nvidia_smi()

    assert result.status == CheckStatus.OK
    assert "RTX 5090" in (result.message or "")
    assert "32 GB" in (result.message or "")
    assert result.type == "system"
    assert result.fixable is False


@pytest.mark.unit
def test_check_nvidia_smi_not_found() -> None:
    """_check_nvidia_smi returns WARN when nvidia-smi is not available."""
    with patch("revolver.core.doctor.get_gpu_info", return_value=None):
        result = _check_nvidia_smi()

    assert result.status == CheckStatus.WARN
    assert result.message == "not found"
    assert result.fixable is False


# ── Revolver check ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_revolver_installed() -> None:
    """_check_revolver returns OK with version."""
    with patch("revolver.core.doctor.importlib.metadata.version", return_value="0.6.3"):
        result = _check_revolver()

    assert result.status == CheckStatus.OK
    assert result.version == "0.6.3"
    assert result.name == "revolver"


@pytest.mark.unit
def test_check_revolver_from_source() -> None:
    """_check_revolver falls back to __version__ when not pip-installed."""
    with patch(
        "revolver.core.doctor.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError("revolver"),
    ):
        result = _check_revolver()

    assert result.status == CheckStatus.OK
    assert result.version is not None  # Falls back to __version__


# ── Fixable vs system ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_fixable_vs_system() -> None:
    """Python and external deps are fixable; system deps are not."""
    with patch("revolver.core.doctor.importlib.metadata.version", return_value="1.0"):
        py = _check_python_package("typer")

    with patch("revolver.core.doctor.get_gpu_info", return_value=None):
        gpu = _check_nvidia_smi()

    assert py.fixable is True
    assert gpu.fixable is False


# ── Full run_doctor ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_run_doctor_all_pass() -> None:
    """run_doctor with all deps present returns all-OK report."""
    gpu = GpuInfo(name="RTX 5090", vram_used_mib=0, vram_total_mib=32768)

    with (
        patch("revolver.core.doctor.importlib.metadata.version", return_value="1.0.0"),
        patch.object(OpenEvolveBackend, "is_available", return_value=(True, None)),
        # Pin "shinka and loongflow absent" so the INFO assertion below holds identically
        # in real environments.
        patch.object(
            ShinkaBackend,
            "is_available",
            return_value=(False, "Install with: pip install 'revolver[shinka]'"),
        ),
        patch.object(
            LoongFlowBackend,
            "is_available",
            return_value=(False, "Install with: pip install 'revolver[loongflow]'"),
        ),
        patch("revolver.core.doctor.httpx.get") as mock_get,
        patch("revolver.core.doctor.get_gpu_info", return_value=gpu),
        patch("revolver.core.doctor._detect_conda", return_value=True),
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"version": "0.6.2"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        report = run_doctor()

    # ShinkaEvolve and LoongFlow absent are informational only — overall stays OK
    assert report.overall_status == CheckStatus.OK
    assert report.error_count == 0
    assert report.warning_count == 0
    # revolver + 5 python deps + openevolve + shinkaevolve + loongflow + ollama + nvidia-smi = 11
    assert len(report.checks) == 11
    shinka_check = next(c for c in report.checks if c.name == "shinkaevolve")
    assert shinka_check.status == CheckStatus.INFO
    loongflow_check = next(c for c in report.checks if c.name == "loongflow")
    assert loongflow_check.status == CheckStatus.INFO


@pytest.mark.unit
def test_run_doctor_missing_dep() -> None:
    """run_doctor with a missing required backend returns FAIL report."""
    gpu = GpuInfo(name="RTX 5090", vram_used_mib=0, vram_total_mib=32768)

    with (
        patch("revolver.core.doctor.importlib.metadata.version", return_value="1.0.0"),
        patch.object(
            OpenEvolveBackend,
            "is_available",
            return_value=(False, "Install with: pip install 'revolver[openevolve]'"),
        ),
        patch("revolver.core.doctor.httpx.get") as mock_get,
        patch("revolver.core.doctor.get_gpu_info", return_value=gpu),
        patch("revolver.core.doctor._detect_conda", return_value=True),
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"version": "0.6.2"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        report = run_doctor()

    assert report.overall_status == CheckStatus.FAIL
    assert report.error_count == 1
    # Find the openevolve check
    oe_check = next(c for c in report.checks if c.name == "openevolve")
    assert oe_check.status == CheckStatus.FAIL
    assert oe_check.message == "not installed"


@pytest.mark.unit
def test_run_doctor_ollama_warn_without_conda() -> None:
    """run_doctor without conda: missing Ollama is WARN (not FAIL)."""
    gpu = GpuInfo(name="RTX 5090", vram_used_mib=0, vram_total_mib=32768)

    with (
        patch("revolver.core.doctor.importlib.metadata.version", return_value="1.0.0"),
        patch.object(OpenEvolveBackend, "is_available", return_value=(True, None)),
        patch(
            "revolver.core.doctor.httpx.get",
            side_effect=httpx.ConnectError("refused"),
        ),
        patch("revolver.core.doctor.get_gpu_info", return_value=gpu),
        patch("revolver.core.doctor._detect_conda", return_value=False),
    ):
        report = run_doctor()

    ollama_check = next(c for c in report.checks if c.name == "ollama")
    assert ollama_check.status == CheckStatus.WARN
    assert ollama_check.fixable is False
    # Overall should be WARN (not FAIL) since Ollama is the only issue
    # (ShinkaEvolve absent is informational, not a warning)
    assert report.overall_status == CheckStatus.WARN
