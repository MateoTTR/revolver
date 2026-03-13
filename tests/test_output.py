"""L1 unit tests for revolver.infra.output — rendering utilities."""

from __future__ import annotations

import json

import pytest

from revolver.infra.output import create_progress, render, render_error


@pytest.mark.unit
def test_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """render(json_mode=True) must output valid JSON to stdout."""
    data = {"name": "test", "value": 42}
    render(data, json_mode=True)

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["name"] == "test"
    assert parsed["value"] == 42
    assert captured.err == ""


@pytest.mark.unit
def test_human_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """render(json_mode=False) must produce non-empty human-readable output."""
    data = {"name": "test-project", "status": "ok"}
    render(data, json_mode=False)

    captured = capsys.readouterr()
    assert "test-project" in captured.out
    assert "ok" in captured.out


@pytest.mark.unit
def test_error_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """render_error must write to stderr, not stdout (NFR-004)."""
    render_error("something went wrong")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "something went wrong" in captured.err


@pytest.mark.unit
def test_create_progress() -> None:
    """create_progress must return a Progress instance."""
    from rich.progress import Progress

    p = create_progress()
    assert isinstance(p, Progress)
