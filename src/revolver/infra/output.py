"""Output rendering utilities.

Provides human-friendly (rich.Table) and machine-readable (JSON) output,
with error messages directed to stderr (NFR-004).

Traceable to: NFR-003, NFR-004, NFR-005.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.progress import Progress
from rich.table import Table

# Stderr console for errors and progress indicators.
_stderr_console = Console(stderr=True)


def render(data: dict[str, Any] | list[dict[str, Any]], *, json_mode: bool = False) -> None:
    """Render data to stdout as a rich table (human) or JSON (machine).

    Args:
        data: A dictionary or list of dictionaries to display.
        json_mode: If ``True``, output JSON; otherwise render a rich table.
    """
    if json_mode:
        print(json.dumps(data, indent=2, default=str))
        return

    # Human mode: build a rich.Table from dict keys.
    stdout_console = Console()
    if isinstance(data, dict):
        table = Table(show_header=True, header_style="bold")
        table.add_column("Key")
        table.add_column("Value")
        for key, value in data.items():
            table.add_row(str(key), str(value))
        stdout_console.print(table)
    elif isinstance(data, list) and data:
        table = Table(show_header=True, header_style="bold")
        for col in data[0]:
            table.add_column(str(col), no_wrap=True)
        for row in data:
            table.add_row(*(str(v) for v in row.values()))
        stdout_console.print(table, overflow="ellipsis")
    else:
        stdout_console.print(str(data))


def render_error(msg: str) -> None:
    """Print an error message to stderr using rich formatting.

    Args:
        msg: The error message to display.
    """
    _stderr_console.print(f"[bold red]Error:[/bold red] {msg}", highlight=False)


def create_progress() -> Progress:
    """Create a rich Progress bar that renders on stderr.

    Returns:
        A ``rich.progress.Progress`` instance attached to stderr.
    """
    return Progress(console=Console(file=sys.stderr))


def print_confirmation(message: str, *, json_mode: bool = False, quiet: bool = False) -> None:
    """Print a one-line confirmation summary to stdout.

    Summaries are suppressed in ``--json`` and ``--quiet`` modes (NFR-006).

    Args:
        message: The confirmation message (e.g. "Done: Project 'foo' initialized at /tmp").
        json_mode: If ``True``, suppress the message.
        quiet: If ``True``, suppress the message.
    """
    if json_mode or quiet:
        return
    print(message)
