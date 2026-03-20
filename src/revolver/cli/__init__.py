"""Revolver CLI — root Typer application.

Provides the ``revolver`` CLI entry point with global options
(``--json``, ``--verbose``, ``--quiet``) and registers all command
group stubs so that ``revolver --help`` displays the full structure.

The ``--json``, ``--verbose``, and ``--quiet`` flags can be placed at
any position in the command line (root, group, or command level) thanks
to the ``GlobalOptionGroup`` custom Click group class.
"""

from __future__ import annotations

import typer

from revolver import __version__
from revolver.cli._global_options import GlobalOptionGroup

# ── Root application ─────────────────────────────────────────────────────────

app = typer.Typer(
    name="revolver",
    cls=GlobalOptionGroup,
    help="MLOps CLI for LLM-guided evolutionary optimization via OpenEvolve.",
    no_args_is_help=True,
)


# ── Version callback ─────────────────────────────────────────────────────────


def _version_callback(value: bool) -> None:
    if value:
        print(f"revolver {__version__}")
        raise typer.Exit()


# ── Global callback (--json, --verbose, --quiet, --version) ──────────────────


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output in JSON format.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Increase output verbosity (show debug info on stderr).",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Suppress non-essential output.",
    ),
) -> None:
    """MLOps CLI for LLM-guided evolutionary optimization via OpenEvolve."""
    ctx.ensure_object(dict)
    # Use ``or`` to preserve values already set by GlobalOptionGroup.parse_args
    # (which strips the flags before Click's normal option parsing).
    ctx.obj["json"] = json_output or ctx.obj.get("json", False)
    ctx.obj["verbose"] = verbose or ctx.obj.get("verbose", False)
    ctx.obj["quiet"] = quiet or ctx.obj.get("quiet", False)


# ── Command group stubs ──────────────────────────────────────────────────────
# Each group is an empty Typer instance registered via app.add_typer().
# Actual commands will be added in their respective modules in later sprints.

project_app = typer.Typer(cls=GlobalOptionGroup, help="Project initialization and management.")
app.add_typer(project_app, name="project")

llm_app = typer.Typer(cls=GlobalOptionGroup, help="LLM registration, lifecycle, and monitoring.")
app.add_typer(llm_app, name="llm")

problem_app = typer.Typer(
    cls=GlobalOptionGroup, help="Problem definition, testing, and versioning."
)
app.add_typer(problem_app, name="problem")

dataset_app = typer.Typer(
    cls=GlobalOptionGroup, help="Dataset registration and integrity management."
)
app.add_typer(dataset_app, name="dataset")

run_app = typer.Typer(cls=GlobalOptionGroup, help="Solution generation via OpenEvolve.")
app.add_typer(run_app, name="run")

solution_app = typer.Typer(
    cls=GlobalOptionGroup, help="Solution browsing, metadata, and aliasing."
)
app.add_typer(solution_app, name="solution")

eval_app = typer.Typer(cls=GlobalOptionGroup, help="Single solution evaluation.")
app.add_typer(eval_app, name="eval")

benchmark_app = typer.Typer(cls=GlobalOptionGroup, help="Multi-solution comparison and export.")
app.add_typer(benchmark_app, name="benchmark")

# ── Command registrations ───────────────────────────────────────────────────
# Import command modules to register their commands on the group apps above.
# These imports MUST come after the Typer instances are created.

import revolver.cli.benchmark as _benchmark_commands  # noqa: F401, E402
import revolver.cli.dataset as _dataset_commands  # noqa: F401, E402
import revolver.cli.doctor as _doctor_commands  # noqa: F401, E402
import revolver.cli.eval as _eval_commands  # noqa: F401, E402
import revolver.cli.llm as _llm_commands  # noqa: F401, E402
import revolver.cli.problem as _problem_commands  # noqa: F401, E402
import revolver.cli.project as _project_commands  # noqa: F401, E402
import revolver.cli.run as _run_commands  # noqa: F401, E402
import revolver.cli.setup as _setup_commands  # noqa: F401, E402
import revolver.cli.solution as _solution_commands  # noqa: F401, E402
