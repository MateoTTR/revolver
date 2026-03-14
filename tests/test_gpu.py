"""L1 unit tests for revolver.infra.gpu — GPU information retrieval."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from revolver.infra.gpu import GpuInfo, get_gpu_info


@pytest.mark.unit
def test_get_gpu_info_normal() -> None:
    """get_gpu_info parses nvidia-smi CSV output correctly."""
    fake_result = subprocess.CompletedProcess(
        args=["nvidia-smi"],
        returncode=0,
        stdout="NVIDIA GeForce RTX 5090, 1024, 32768\n",
        stderr="",
    )
    with patch("revolver.infra.gpu.subprocess.run", return_value=fake_result):
        info = get_gpu_info()

    assert info is not None
    assert isinstance(info, GpuInfo)
    assert info.name == "NVIDIA GeForce RTX 5090"
    assert info.vram_used_mib == 1024
    assert info.vram_total_mib == 32768


@pytest.mark.unit
def test_get_gpu_info_no_nvidia_smi() -> None:
    """get_gpu_info returns None when nvidia-smi is not found."""
    with patch(
        "revolver.infra.gpu.subprocess.run",
        side_effect=FileNotFoundError("nvidia-smi not found"),
    ):
        info = get_gpu_info()

    assert info is None


@pytest.mark.unit
def test_get_gpu_info_nonzero_return() -> None:
    """get_gpu_info returns None when nvidia-smi exits with non-zero."""
    fake_result = subprocess.CompletedProcess(
        args=["nvidia-smi"],
        returncode=1,
        stdout="",
        stderr="NVIDIA-SMI has failed",
    )
    with patch("revolver.infra.gpu.subprocess.run", return_value=fake_result):
        info = get_gpu_info()

    assert info is None


@pytest.mark.unit
def test_get_gpu_info_empty_output() -> None:
    """get_gpu_info returns None when nvidia-smi produces empty output."""
    fake_result = subprocess.CompletedProcess(
        args=["nvidia-smi"],
        returncode=0,
        stdout="",
        stderr="",
    )
    with patch("revolver.infra.gpu.subprocess.run", return_value=fake_result):
        info = get_gpu_info()

    assert info is None


@pytest.mark.unit
def test_get_gpu_info_malformed_output() -> None:
    """get_gpu_info returns None on unparsable output."""
    fake_result = subprocess.CompletedProcess(
        args=["nvidia-smi"],
        returncode=0,
        stdout="Some garbage output\n",
        stderr="",
    )
    with patch("revolver.infra.gpu.subprocess.run", return_value=fake_result):
        info = get_gpu_info()

    assert info is None


@pytest.mark.unit
def test_get_gpu_info_timeout() -> None:
    """get_gpu_info returns None when nvidia-smi times out."""
    with patch(
        "revolver.infra.gpu.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10),
    ):
        info = get_gpu_info()

    assert info is None


@pytest.mark.unit
def test_get_gpu_info_multi_gpu() -> None:
    """get_gpu_info returns info for the first GPU when multiple are present."""
    fake_result = subprocess.CompletedProcess(
        args=["nvidia-smi"],
        returncode=0,
        stdout="NVIDIA GeForce RTX 4090, 512, 24576\nNVIDIA GeForce RTX 4090, 256, 24576\n",
        stderr="",
    )
    with patch("revolver.infra.gpu.subprocess.run", return_value=fake_result):
        info = get_gpu_info()

    assert info is not None
    assert info.name == "NVIDIA GeForce RTX 4090"
    assert info.vram_used_mib == 512
    assert info.vram_total_mib == 24576
