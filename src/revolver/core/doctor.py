"""Domain logic for ``revolver doctor`` — dependency health checks.

Checks Python packages, OpenEvolve, Ollama, nvidia-smi, and Revolver
itself, producing a structured ``DoctorReport``.

Traceable to: spec-setup.md, FR-SET-001..006, FR-SET-012, FR-SET-013.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import importlib.metadata
from typing import Literal

import httpx

from revolver.infra.gpu import get_gpu_info


class CheckStatus(StrEnum):
    """Health check result status."""

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class DependencyStatus:
    """Result of a single dependency health check."""

    name: str
    type: Literal["python", "external", "system"]
    status: CheckStatus
    version: str | None = None
    message: str | None = None
    fixable: bool = False


@dataclass
class DoctorReport:
    """Aggregated result of all dependency checks."""

    checks: list[DependencyStatus] = field(default_factory=list)

    @property
    def overall_status(self) -> CheckStatus:
        """Return the worst status across all checks."""
        if any(c.status == CheckStatus.FAIL for c in self.checks):
            return CheckStatus.FAIL
        if any(c.status == CheckStatus.WARN for c in self.checks):
            return CheckStatus.WARN
        return CheckStatus.OK

    @property
    def error_count(self) -> int:
        """Count checks with FAIL status."""
        return sum(1 for c in self.checks if c.status == CheckStatus.FAIL)

    @property
    def warning_count(self) -> int:
        """Count checks with WARN status."""
        return sum(1 for c in self.checks if c.status == CheckStatus.WARN)


# ── Python package checks ────────────────────────────────────────────────────

# Core Python dependencies from pyproject.toml
_PYTHON_DEPS: list[str] = ["typer", "pydantic", "pyyaml", "rich", "httpx"]


def _check_python_package(name: str) -> DependencyStatus:
    """Check if a Python package is installed and return its version."""
    # importlib.metadata uses distribution names (pyyaml -> PyYAML)
    dist_name = name
    try:
        version = importlib.metadata.version(dist_name)
        return DependencyStatus(
            name=name,
            type="python",
            status=CheckStatus.OK,
            version=version,
            fixable=True,
        )
    except importlib.metadata.PackageNotFoundError:
        return DependencyStatus(
            name=name,
            type="python",
            status=CheckStatus.FAIL,
            message="not installed",
            fixable=True,
        )


def _check_openevolve() -> DependencyStatus:
    """Check if OpenEvolve is importable and report its version."""
    try:
        version = importlib.metadata.version("openevolve")
        return DependencyStatus(
            name="openevolve",
            type="python",
            status=CheckStatus.OK,
            version=version,
            fixable=True,
        )
    except importlib.metadata.PackageNotFoundError:
        return DependencyStatus(
            name="openevolve",
            type="python",
            status=CheckStatus.FAIL,
            message="not installed",
            fixable=True,
        )


# ── External tool checks ─────────────────────────────────────────────────────


def _check_ollama(base_url: str = "http://localhost:11434") -> DependencyStatus:
    """Check Ollama: binary presence, service running, API reachable."""
    try:
        resp = httpx.get(f"{base_url}/api/version", timeout=5.0)
        resp.raise_for_status()
        version = str(resp.json().get("version", "unknown"))
        return DependencyStatus(
            name="ollama",
            type="external",
            status=CheckStatus.OK,
            version=version,
            message=f"running ({base_url})",
            fixable=True,
        )
    except httpx.ConnectError:
        return DependencyStatus(
            name="ollama",
            type="external",
            status=CheckStatus.FAIL,
            message="not found or not running",
            fixable=True,
        )
    except (httpx.HTTPStatusError, httpx.TimeoutException, Exception):
        return DependencyStatus(
            name="ollama",
            type="external",
            status=CheckStatus.WARN,
            message="installed but not responding correctly",
            fixable=False,
        )


# ── System checks ────────────────────────────────────────────────────────────


def _check_nvidia_smi() -> DependencyStatus:
    """Check nvidia-smi availability and GPU info."""
    gpu_info = get_gpu_info()
    if gpu_info is None:
        return DependencyStatus(
            name="nvidia-smi",
            type="system",
            status=CheckStatus.WARN,
            message="not found",
            fixable=False,
        )
    vram_gb = gpu_info.vram_total_mib / 1024
    return DependencyStatus(
        name="nvidia-smi",
        type="system",
        status=CheckStatus.OK,
        version=None,
        message=f"GPU: {gpu_info.name} ({vram_gb:.0f} GB)",
        fixable=False,
    )


def _check_revolver() -> DependencyStatus:
    """Check revolver itself."""
    try:
        version = importlib.metadata.version("revolver")
        return DependencyStatus(
            name="revolver",
            type="python",
            status=CheckStatus.OK,
            version=version,
        )
    except importlib.metadata.PackageNotFoundError:
        # If running from source without install
        from revolver import __version__

        return DependencyStatus(
            name="revolver",
            type="python",
            status=CheckStatus.OK,
            version=__version__,
        )


# ── Main entry point ─────────────────────────────────────────────────────────


def run_doctor() -> DoctorReport:
    """Run all dependency health checks and return a DoctorReport.

    Checks (in order):
    1. Revolver itself
    2. Core Python packages (typer, pydantic, pyyaml, rich, httpx)
    3. OpenEvolve
    4. Ollama (HTTP API)
    5. nvidia-smi / GPU

    Returns:
        A :class:`DoctorReport` with per-check results.
    """
    report = DoctorReport()

    # 1. Revolver itself
    report.checks.append(_check_revolver())

    # 2. Core Python packages
    for pkg in _PYTHON_DEPS:
        report.checks.append(_check_python_package(pkg))

    # 3. OpenEvolve
    report.checks.append(_check_openevolve())

    # 4. Ollama
    report.checks.append(_check_ollama())

    # 5. nvidia-smi / GPU
    report.checks.append(_check_nvidia_smi())

    return report
