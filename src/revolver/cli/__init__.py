"""Revolver CLI — root Typer application (placeholder for S1-02)."""

import typer

from revolver import __version__

app = typer.Typer(
    name="revolver",
    help="MLOps CLI for LLM-guided evolutionary optimization via OpenEvolve.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"revolver {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", help="Show version and exit.", callback=_version_callback
    ),
) -> None:
    """MLOps CLI for LLM-guided evolutionary optimization via OpenEvolve."""
