"""CLI error handler — catches RevolverError and maps to exit codes.

Provides a context manager for CLI commands that:
1. Catches any RevolverError subclass
2. Renders the error message to stderr
3. Raises typer.Exit with the appropriate exit code
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
import sys

import typer

from revolver.core.exceptions import RevolverError


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
    except RevolverError as exc:
        code = handle_error(exc)
        message = str(exc)
        if message:
            sys.stderr.write(f"Error: {message}\n")
        else:
            sys.stderr.write(f"Error: {type(exc).__name__}\n")
        raise typer.Exit(code=code) from exc
