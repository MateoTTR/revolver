"""L1 unit tests for revolver.infra.config — 5-level config hierarchy."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from revolver.infra.config import load_config


@pytest.mark.unit
def test_defaults() -> None:
    """load_config with no overrides must return built-in defaults."""
    config = load_config()
    assert config["verbose"] is False
    assert config["quiet"] is False
    assert config["json"] is False


@pytest.mark.unit
def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """REVOLVER_* environment variables must override all other levels."""
    monkeypatch.setenv("REVOLVER_VERBOSE", "true")
    monkeypatch.setenv("REVOLVER_CUSTOM_KEY", "from-env")

    config = load_config(verbose="from-cli")
    # Env vars (level 5) override CLI args (level 4)
    assert config["verbose"] == "true"
    assert config["custom_key"] == "from-env"


@pytest.mark.unit
def test_hierarchy_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config hierarchy: defaults < global < project < CLI < env."""
    # Level 2: global config
    global_dir = tmp_path / "home" / ".revolver"
    global_dir.mkdir(parents=True)
    global_config = global_dir / "config.yaml"
    with open(global_config, "w") as f:
        yaml.dump({"verbose": True, "from_global": "global-val"}, f)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))  # type: ignore[arg-type]

    # Level 3: project config in cwd
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_config = project_dir / "project.yaml"
    with open(project_config, "w") as f:
        yaml.dump({"from_global": "project-overrides-global", "from_project": "proj-val"}, f)

    monkeypatch.chdir(project_dir)

    # Level 4: CLI arg
    # Level 5: env
    monkeypatch.setenv("REVOLVER_FROM_PROJECT", "env-overrides-project")

    config = load_config(from_project="cli-overrides-project")

    # Global sets verbose=True, default was False
    assert config["verbose"] is True
    # Project overrides global
    assert config["from_global"] == "project-overrides-global"
    # Env (level 5) overrides CLI (level 4) which overrides project (level 3)
    assert config["from_project"] == "env-overrides-project"
