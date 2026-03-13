"""Domain logic for project initialization.

Implements ``revolver project init`` — creates the project directory
structure, SQLite database, manifest, and template files.

Traceable to: FR-PRJ-001..008, spec-project.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import revolver
from revolver.core.exceptions import DuplicateNameError
from revolver.infra.db import get_project_db
from revolver.infra.store import REVOLVER_DIR, init_project_store, write_manifest
from revolver.models.project import ProjectConfig

# ── Template content ─────────────────────────────────────────────────────────

_INITIAL_PROGRAM_TEMPLATE = '''\
"""Initial program template — edit the EVOLVE-BLOCK to define your solution.

OpenEvolve will evolve the code between the EVOLVE-BLOCK markers.
Keep the function signature and return type unchanged.
"""

from __future__ import annotations


def solve(data: list[int]) -> int:
    """Solve the optimization problem.

    Args:
        data: Input data for the problem instance.

    Returns:
        The computed result.
    """
    # --- EVOLVE-BLOCK-START ---
    # OpenEvolve will replace this block with evolved code.
    # Write your initial (baseline) solution here.
    result = sum(data)
    # --- EVOLVE-BLOCK-END ---
    return result
'''

_EVALUATOR_TEMPLATE = '''\
"""Evaluator template — dual-mode pattern (single-instance + aggregated).

Revolver supports two evaluation modes:

1. **Per-instance** (preferred): implement ``evaluate_instance(program_path)``
   - Revolver sets ``REVOLVER_INSTANCE_PATH`` to the current instance file
   - Returns ``dict[str, float]`` with metric names and values
   - Revolver handles aggregation (mean, min, max, percentiles)

2. **Aggregated** (legacy): implement ``evaluate(program_path)``
   - Revolver sets ``REVOLVER_DATASET_DIR`` to the dataset directory
   - You iterate over instances and compute aggregate metrics yourself
   - Returns ``dict[str, float]`` with your custom aggregation

Environment variables set by Revolver:
    REVOLVER_INSTANCE_PATH — path to the current instance (per-instance mode)
    REVOLVER_DATASET_DIR   — path to the dataset directory (aggregated mode)
"""

from __future__ import annotations

import os


def evaluate_instance(program_path: str) -> dict[str, float]:
    """Evaluate the program on a single instance.

    Args:
        program_path: Path to the evolved program file.

    Returns:
        Dictionary of metric names to float values.
        Must include ``combined_score`` as the primary metric.
    """
    instance_path = os.environ.get("REVOLVER_INSTANCE_PATH", "")

    # TODO: Load the instance data from instance_path
    # TODO: Run the program on the instance
    # TODO: Compute metrics

    return {"combined_score": 0.0}


def evaluate(program_path: str) -> dict[str, float]:
    """Evaluate the program on the full dataset (legacy aggregated mode).

    Args:
        program_path: Path to the evolved program file.

    Returns:
        Dictionary of aggregated metric names to float values.
    """
    dataset_dir = os.environ.get("REVOLVER_DATASET_DIR", "")

    # TODO: Iterate over instances in dataset_dir
    # TODO: Run the program on each instance
    # TODO: Aggregate results

    return {"combined_score": 0.0}
'''

_CONFIG_TEMPLATE = """\
# OpenEvolve configuration — edit to match your problem.
#
# See OpenEvolve documentation for all available options.
# Revolver passes this file to OpenEvolve via --config.

# Number of evolutionary iterations (generations).
num_iterations: 10

# Population size — number of candidate programs per generation.
population_size: 10

# LLM sampling settings.
llm:
  temperature: 0.8
  max_tokens: 4096

# Evaluation settings.
evaluation:
  timeout_per_instance: 30  # seconds
"""


def init_project(
    path: Path,
    name: str,
    description: str = "",
) -> ProjectConfig:
    """Initialize a new Revolver project.

    Creates the ``.revolver/`` directory structure, SQLite database,
    ``project.yaml`` manifest, and template files.

    Args:
        path: Project root directory. Created if it does not exist (FR-PRJ-007).
        name: Project name.
        description: Short project description.

    Returns:
        The created ``ProjectConfig``.

    Raises:
        DuplicateNameError: If ``.revolver/`` already exists in *path* (FR-PRJ-006).
    """
    path = path.resolve()

    # FR-PRJ-007: create target directory if it does not exist
    path.mkdir(parents=True, exist_ok=True)

    # FR-PRJ-006: refuse if already initialized
    revolver_path = path / REVOLVER_DIR
    if revolver_path.exists():
        raise DuplicateNameError(
            f"Project already initialized in {path}. Use a different directory."
        )

    # FR-PRJ-001, FR-PRJ-008: create .revolver/ with subdirs and mode 700
    init_project_store(path)

    # FR-PRJ-001: initialize SQLite database
    db_path = revolver_path / "revolver.db"
    conn = get_project_db(db_path)
    conn.close()

    # Build ProjectConfig
    config = ProjectConfig(
        name=name,
        description=description,
        created_at=datetime.now(UTC),
        revolver_version=revolver.__version__,
    )

    # FR-PRJ-002: write project.yaml
    manifest_path = path / "project.yaml"
    write_manifest(
        manifest_path,
        {
            "name": config.name,
            "description": config.description,
            "created_at": config.created_at.isoformat(),
            "revolver_version": config.revolver_version,
        },
    )

    # FR-PRJ-003: generate template initial_program.py
    (path / "initial_program.py").write_text(_INITIAL_PROGRAM_TEMPLATE, encoding="utf-8")

    # FR-PRJ-004: generate template evaluator.py
    (path / "evaluator.py").write_text(_EVALUATOR_TEMPLATE, encoding="utf-8")

    # FR-PRJ-005: generate template config.yaml
    (path / "config.yaml").write_text(_CONFIG_TEMPLATE, encoding="utf-8")

    return config
