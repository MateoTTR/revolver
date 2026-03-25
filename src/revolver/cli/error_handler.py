"""CLI error handler — catches RevolverError and maps to exit codes.

Provides a context manager for CLI commands that:
1. Catches any RevolverError subclass
2. Catches workspace-not-found errors with a user-friendly message
3. Renders the error message to stderr
4. Raises typer.Exit with the appropriate exit code
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
import sys

import typer

from revolver.core.exceptions import (
    ProjectNotFoundError as CoreProjectNotFoundError,
    RevolverError,
)
from revolver.infra.store import ProjectNotFoundError as StoreProjectNotFoundError

_WORKSPACE_MSG = "Not in a Revolver workspace. Run `revolver project init` first."


def handle_error(exc: RevolverError) -> int:
    """Map a RevolverError to its exit code.

    Args:
        exc: The exception to map.

    Returns:
        The CLI exit code for this error category.
    """
    return exc.exit_code


@contextmanager
def cli_error_boundary() -> Generator[None, None, None]:
    """Context manager that catches RevolverError and exits with the correct code.

    Also catches ``ProjectNotFoundError`` (from both the infra store and
    core exception layers) and emits a user-friendly workspace message.

    Usage::

        @app.command()
        def my_command() -> None:
            with cli_error_boundary():
                do_something_that_may_raise()

    On RevolverError, the error message is printed to stderr and
    ``typer.Exit`` is raised with the mapped exit code.
    """
    try:
        yield
    except (StoreProjectNotFoundError, CoreProjectNotFoundError) as exc:
        sys.stderr.write(f"Error: {_WORKSPACE_MSG}\n")
        raise typer.Exit(code=1) from exc
    except RevolverError as exc:
        code = handle_error(exc)
        message = str(exc)
        if message:
            sys.stderr.write(f"Error: {message}\n")
        else:
            sys.stderr.write(f"Error: {type(exc).__name__}\n")
        raise typer.Exit(code=code) from exc
