"""Domain logic for ``revolver doctor`` — dependency health checks.

Checks Python packages, evolution backends (OpenEvolve required,
ShinkaEvolve optional — ADR-007), Ollama, nvidia-smi, and Revolver
itself, producing a structured ``DoctorReport``.

Traceable to: spec-setup.md, FR-SET-001..006, FR-SET-012, FR-SET-013.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import importlib.metadata
import subprocess
from typing import Literal

import httpx

from revolver.infra.backends.base import AVAILABLE_BACKENDS, get_backend
from revolver.infra.gpu import get_gpu_info


class CheckStatus(StrEnum):
    """Health check result status.

    ``INFO`` marks informational entries (e.g. an optional evolution
    backend that is not installed — FR-SET-002): they never affect the
    overall status, error count, or warning count.
    """

    OK = "ok"
    INFO = "info"
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


# ── Evolution backend checks (FR-SET-002, ADR-007) ──────────────────────────

# Backends required for core workflows; absence is a FAIL (today's
# OpenEvolve semantics). All other registered backends are optional:
# absence is reported as informational, never a failure.
_REQUIRED_BACKENDS: frozenset[str] = frozenset({"openevolve"})

# Doctor check names per backend name (package-style, e.g. the doctor
# entry for the "shinka" backend is "shinkaevolve", matching "openevolve").
_BACKEND_CHECK_NAMES: dict[str, str] = {"openevolve": "openevolve", "shinka": "shinkaevolve"}


def _check_backend(backend_name: str) -> DependencyStatus:
    """Check an evolution backend's availability (FR-SET-002).

    Required backends (OpenEvolve) report FAIL when absent, with the
    same message and fixable-via-``revolver setup`` behavior as before.
    Optional backends (ShinkaEvolve) report INFO when absent — not a
    failure, not auto-fixable (ADR-007, spec-setup error cases).
    """
    backend = get_backend(backend_name)
    available, hint = backend.is_available()
    check_name = _BACKEND_CHECK_NAMES.get(backend_name, backend_name)

    if available:
        try:
            version: str | None = importlib.metadata.version(check_name)
        except importlib.metadata.PackageNotFoundError:
            version = None
        return DependencyStatus(
            name=check_name,
            type="python",
            status=CheckStatus.OK,
            version=version,
            fixable=True,
        )

    if backend_name in _REQUIRED_BACKENDS:
        return DependencyStatus(
            name=check_name,
            type="python",
            status=CheckStatus.FAIL,
            message="not installed",
            fixable=True,
        )

    message = "not installed (optional)."
    if hint:
        message = f"{message} {hint}"
    return DependencyStatus(
        name=check_name,
        type="python",
        status=CheckStatus.INFO,
        message=message,
        fixable=False,
    )


# ── External tool checks ─────────────────────────────────────────────────────


def _check_ollama(
    base_url: str = "http://localhost:11434", *, has_conda: bool = False
) -> DependencyStatus:
    """Check Ollama: binary presence, service running, API reachable.

    Per spec-setup.md §4:
    - Ollama missing + conda available → FAIL (fixable via conda)
    - Ollama missing + no conda → WARN (manual install only)
    - Ollama installed but not responding → WARN
    """
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
        if has_conda:
            return DependencyStatus(
                name="ollama",
                type="external",
                status=CheckStatus.FAIL,
                message="not found. Run `revolver setup` to install via conda-forge.",
                fixable=True,
            )
        else:
            return DependencyStatus(
                name="ollama",
                type="external",
                status=CheckStatus.WARN,
                message=(
                    "not found. Install from https://ollama.com"
                    " or activate a conda environment and run `revolver setup`."
                ),
                fixable=False,
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


def _detect_conda() -> bool:
    """Check if conda or mamba is available."""
    for cmd in ("conda", "mamba"):
        try:
            result = subprocess.run(
                [cmd, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


def run_doctor() -> DoctorReport:
    """Run all dependency health checks and return a DoctorReport.

    Checks (in order):
    1. Revolver itself
    2. Core Python packages (typer, pydantic, pyyaml, rich, httpx)
    3. Evolution backends (OpenEvolve required, ShinkaEvolve informational)
    4. Ollama (HTTP API) — status depends on conda availability
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

    # 3. Evolution backends (FR-SET-002): OpenEvolve required; optional
    #    backends (ShinkaEvolve) are informational when absent (ADR-007).
    for backend_name in AVAILABLE_BACKENDS:
        report.checks.append(_check_backend(backend_name))

    # 4. Ollama — per spec, status depends on conda availability
    has_conda = _detect_conda()
    report.checks.append(_check_ollama(has_conda=has_conda))

    # 5. nvidia-smi / GPU
    report.checks.append(_check_nvidia_smi())

    return report
