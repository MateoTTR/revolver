"""Domain logic for ``revolver setup`` — assisted installation.

Detects available package managers, computes an install plan from a
DoctorReport, and executes installations with user confirmation.

Traceable to: spec-setup.md, FR-SET-007..011, FR-SET-014..017.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import subprocess

from revolver.core.doctor import CheckStatus, DoctorReport, run_doctor


class InstallMethod(StrEnum):
    """How a dependency can be installed."""

    PIP = "pip"
    CONDA = "conda"
    MANUAL = "manual"


@dataclass
class InstallItem:
    """A single item to install."""

    name: str
    method: InstallMethod
    version: str = "latest"
    command: str = ""


@dataclass
class InstallResult:
    """Result of installing a single item."""

    name: str
    success: bool
    version: str | None = None
    error: str | None = None


@dataclass
class InstallPlan:
    """Plan of items to install and manual instructions."""

    items: list[InstallItem] = field(default_factory=list)
    manual_instructions: list[str] = field(default_factory=list)

    @property
    def has_installable(self) -> bool:
        """True if there are any auto-installable items."""
        return any(item.method != InstallMethod.MANUAL for item in self.items)


# ── Package manager detection ────────────────────────────────────────────────


def detect_package_managers() -> dict[str, bool]:
    """Detect available package managers.

    Returns:
        A dict with keys ``pip``, ``conda``, ``mamba`` and boolean values.
    """
    managers: dict[str, bool] = {"pip": True}

    # Check conda
    try:
        result = subprocess.run(
            ["conda", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        managers["conda"] = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        managers["conda"] = False

    # Check mamba
    try:
        result = subprocess.run(
            ["mamba", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        managers["mamba"] = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        managers["mamba"] = False

    return managers


# ── Install plan computation ─────────────────────────────────────────────────

# Map package names to pip install names
_PIP_INSTALL_NAMES: dict[str, str] = {
    "pyyaml": "pyyaml",
    "typer": "typer",
    "pydantic": "pydantic",
    "rich": "rich",
    "httpx": "httpx",
    "openevolve": "openevolve",
    "revolver": "revolver",
}


def compute_install_plan(report: DoctorReport, managers: dict[str, bool]) -> InstallPlan:
    """Compute an installation plan from a doctor report.

    Args:
        report: The DoctorReport with dependency check results.
        managers: Available package managers from detect_package_managers().

    Returns:
        An InstallPlan with items to install and manual instructions.
    """
    plan = InstallPlan()

    for check in report.checks:
        if check.status == CheckStatus.OK:
            continue

        if check.type == "python" and check.fixable:
            pip_name = _PIP_INSTALL_NAMES.get(check.name, check.name)
            plan.items.append(
                InstallItem(
                    name=check.name,
                    method=InstallMethod.PIP,
                    command=f"pip install {pip_name}",
                )
            )
        elif check.name == "ollama" and check.fixable:
            has_conda = managers.get("conda", False) or managers.get("mamba", False)
            if has_conda:
                conda_cmd = "mamba" if managers.get("mamba", False) else "conda"
                plan.items.append(
                    InstallItem(
                        name="ollama",
                        method=InstallMethod.CONDA,
                        command=f"{conda_cmd} install -y conda-forge::ollama",
                    )
                )
            else:
                plan.items.append(
                    InstallItem(
                        name="ollama",
                        method=InstallMethod.MANUAL,
                    )
                )
                plan.manual_instructions.append(
                    "ollama: Install from https://ollama.com/download"
                    " or activate a conda environment and re-run `revolver setup`"
                )
        elif check.type == "system":
            # System-level deps: instructions only, never auto-install
            if check.name == "nvidia-smi":
                plan.manual_instructions.append(
                    "nvidia-smi: Install NVIDIA drivers for GPU support."
                    " Local LLM inference requires a compatible GPU."
                    " Remote-only workflows will still work without GPU."
                )

    return plan


# ── Plan execution ───────────────────────────────────────────────────────────


def execute_install_plan(
    plan: InstallPlan,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> list[InstallResult]:
    """Execute an installation plan.

    Args:
        plan: The InstallPlan to execute.
        dry_run: If True, return what would be installed without doing it.
        force: If True, reinstall even if present (adds --force-reinstall for pip).

    Returns:
        A list of InstallResult for each attempted installation.
    """
    results: list[InstallResult] = []

    for item in plan.items:
        if item.method == InstallMethod.MANUAL:
            # Manual items are not executed
            continue

        if dry_run:
            results.append(InstallResult(name=item.name, success=True, version="(dry run)"))
            continue

        if item.method == InstallMethod.PIP:
            result = _install_via_pip(item, force=force)
            results.append(result)
        elif item.method == InstallMethod.CONDA:
            result = _install_via_conda(item)
            results.append(result)

    return results


def _install_via_pip(item: InstallItem, *, force: bool = False) -> InstallResult:
    """Install a package via pip."""
    cmd = item.command.split()
    if force:
        cmd.append("--force-reinstall")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if proc.returncode != 0:
            return InstallResult(
                name=item.name,
                success=False,
                error=f"pip install failed: {proc.stderr.strip()}",
            )
        return InstallResult(name=item.name, success=True)
    except subprocess.TimeoutExpired:
        return InstallResult(
            name=item.name,
            success=False,
            error="Installation timed out",
        )
    except FileNotFoundError:
        return InstallResult(
            name=item.name,
            success=False,
            error="pip not found",
        )


def _install_via_conda(item: InstallItem) -> InstallResult:
    """Install a package via conda/mamba."""
    cmd = item.command.split()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if proc.returncode != 0:
            return InstallResult(
                name=item.name,
                success=False,
                error=f"conda install failed: {proc.stderr.strip()}",
            )
        return InstallResult(name=item.name, success=True)
    except subprocess.TimeoutExpired:
        return InstallResult(
            name=item.name,
            success=False,
            error="Installation timed out",
        )
    except FileNotFoundError:
        return InstallResult(
            name=item.name,
            success=False,
            error="conda/mamba not found",
        )


# ── Main entry point ─────────────────────────────────────────────────────────


def run_setup(
    *, dry_run: bool = False, force: bool = False
) -> tuple[InstallPlan, list[InstallResult], DoctorReport]:
    """Run the full setup workflow.

    1. Run doctor to identify issues
    2. Detect package managers
    3. Compute install plan
    4. Execute plan (unless dry_run)
    5. Re-run doctor to verify (unless dry_run)

    Args:
        dry_run: Preview only, no changes.
        force: Skip confirmation, reinstall if present.

    Returns:
        A tuple of (plan, results, post_report).
    """
    # 1. Initial doctor check
    report = run_doctor()

    # 2. Detect package managers
    managers = detect_package_managers()

    # 3. Compute install plan
    plan = compute_install_plan(report, managers)

    # 4. Execute
    results = execute_install_plan(plan, dry_run=dry_run, force=force)

    # 5. Re-run doctor to verify (unless dry_run or nothing to install)
    post_report = report if dry_run or not plan.has_installable else run_doctor()

    return plan, results, post_report
