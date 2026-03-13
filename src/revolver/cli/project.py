"""CLI commands for ``revolver project``.

Registers commands on the ``project_app`` Typer instance from
``revolver.cli``.

Traceable to: spec-project.md, FR-PRJ-001..008.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from revolver.cli import project_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core.project import init_project
from revolver.infra.output import render


@project_app.command("init")
def project_init(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Project name.")],
    path: Annotated[
        Path | None,
        typer.Option(
            "--path",
            help="Directory to initialize. Created if it does not exist.",
        ),
    ] = None,
    description: Annotated[
        str,
        typer.Option(
            "--description",
            help="Short project description.",
        ),
    ] = "",
) -> None:
    """Initialize a new Revolver project."""
    with cli_error_boundary():
        target = path if path is not None else Path.cwd()

        config = init_project(
            path=target,
            name=name,
            description=description,
        )

        resolved = target.resolve()

        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        files = ".revolver/, initial_program.py, evaluator.py, config.yaml, project.yaml"

        if json_mode:
            render(
                {
                    "project": config.name,
                    "path": str(resolved),
                    "files_created": [
                        ".revolver/",
                        "initial_program.py",
                        "evaluator.py",
                        "config.yaml",
                        "project.yaml",
                    ],
                },
                json_mode=True,
            )
        else:
            render(
                {
                    "status": "success",
                    "project": config.name,
                    "path": str(resolved),
                    "created": files,
                },
                json_mode=False,
            )
