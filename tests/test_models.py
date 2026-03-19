"""L1 unit tests for revolver.models.project — ProjectConfig Pydantic model."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from revolver.models.project import ProjectConfig


@pytest.mark.unit
def test_project_config_validate() -> None:
    """ProjectConfig must validate from a dict (simulating YAML load)."""
    data = {
        "name": "test-project",
        "description": "A test project",
        "created_at": "2026-03-10T14:30:00Z",
        "revolver_version": "0.1.0",
    }
    config = ProjectConfig.model_validate(data)
    assert config.name == "test-project"
    assert config.description == "A test project"
    assert config.revolver_version == "0.1.0"


@pytest.mark.unit
def test_project_config_dump() -> None:
    """ProjectConfig.model_dump() must serialize cleanly."""
    config = ProjectConfig(
        name="my-project",
        description="",
        created_at=datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC),
        revolver_version="0.1.0",
    )
    dumped = config.model_dump()
    assert dumped["name"] == "my-project"
    assert "created_at" in dumped
    assert dumped["revolver_version"] == "0.1.0"


@pytest.mark.unit
def test_project_config_frozen() -> None:
    """ProjectConfig must be frozen (immutable)."""
    config = ProjectConfig(
        name="my-project",
        description="",
        created_at=datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC),
        revolver_version="0.1.0",
    )
    with pytest.raises(ValidationError):
        config.name = "changed"  # type: ignore[misc]


@pytest.mark.unit
def test_project_config_defaults() -> None:
    """ProjectConfig.description must default to empty string."""
    config = ProjectConfig(
        name="minimal",
        created_at=datetime.now(UTC),
        revolver_version="0.1.0",
    )
    assert config.description == ""
