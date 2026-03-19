"""GPU information retrieval via nvidia-smi.

Provides a simple interface to query NVIDIA GPU status (name, VRAM usage).
Returns ``None`` gracefully when no GPU or nvidia-smi is unavailable.

Traceable to: DES-002 (LLM subcommands — GPU awareness).
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess


@dataclass
class GpuInfo:
    """Basic GPU information from nvidia-smi."""

    name: str
    vram_used_mib: int
    vram_total_mib: int


def get_gpu_info() -> GpuInfo | None:
    """Query nvidia-smi for GPU name and VRAM usage.

    Returns:
        A :class:`GpuInfo` instance, or ``None`` if nvidia-smi is not
        available or fails to produce parsable output.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0:
        return None

    line = result.stdout.strip()
    if not line:
        return None

    # Parse the first GPU line: "NVIDIA GeForce RTX 5090, 1024, 32768"
    parts = [p.strip() for p in line.split("\n")[0].split(",")]
    if len(parts) < 3:
        return None

    try:
        return GpuInfo(
            name=parts[0],
            vram_used_mib=int(parts[1]),
            vram_total_mib=int(parts[2]),
        )
    except (ValueError, IndexError):
        return None
