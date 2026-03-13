"""Five-level configuration hierarchy resolution.

Resolution order (last wins):
    1. Built-in defaults
    2. Global config  (``~/.revolver/config.yaml``)
    3. Project config (``project.yaml`` in project root)
    4. CLI arguments   (passed as keyword arguments)
    5. Environment variables (``REVOLVER_*``)

Traceable to: specifications.md section 4.4.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# ── Built-in defaults ────────────────────────────────────────────────────────

_DEFAULTS: dict[str, Any] = {
    "verbose": False,
    "quiet": False,
    "json": False,
}


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file if it exists, returning empty dict otherwise."""
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            return data
    return {}


def _load_env_overrides() -> dict[str, Any]:
    """Collect ``REVOLVER_*`` environment variables as config entries.

    The prefix ``REVOLVER_`` is stripped and the remainder is lower-cased.
    For example, ``REVOLVER_VERBOSE=1`` becomes ``{"verbose": "1"}``.
    """
    prefix = "REVOLVER_"
    result: dict[str, Any] = {}
    for key, value in os.environ.items():
        if key.startswith(prefix):
            config_key = key[len(prefix) :].lower()
            result[config_key] = value
    return result


def load_config(**cli_overrides: Any) -> dict[str, Any]:
    """Build a merged configuration dictionary using the 5-level hierarchy.

    Args:
        **cli_overrides: Key-value pairs from CLI arguments (level 4).

    Returns:
        Merged configuration dictionary where later levels override earlier ones.
    """
    # Level 1: defaults
    merged: dict[str, Any] = dict(_DEFAULTS)

    # Level 2: global config
    global_config_path = Path.home() / ".revolver" / "config.yaml"
    merged.update(_load_yaml_file(global_config_path))

    # Level 3: project config (look in cwd)
    project_config_path = Path.cwd() / "project.yaml"
    merged.update(_load_yaml_file(project_config_path))

    # Level 4: CLI arguments (filter out None values)
    for k, v in cli_overrides.items():
        if v is not None:
            merged[k] = v

    # Level 5: environment variables
    merged.update(_load_env_overrides())

    return merged
