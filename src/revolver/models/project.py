"""Pydantic model for project configuration (``project.yaml``).

Traceable to: FR-PRJ-002, spec-project.md section 5.1.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectConfig(BaseModel):
    """Immutable project configuration stored in ``project.yaml``.

    Attributes:
        name: Project identifier (e.g. ``"scheduling-optimizer"``).
        description: Short human-readable description.
        created_at: Timestamp of project creation (ISO 8601).
        revolver_version: Version of Revolver that created this project.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    created_at: datetime
    revolver_version: str
