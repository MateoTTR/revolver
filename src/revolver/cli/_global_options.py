"""Custom Typer/Click classes for global option propagation.

Allows ``--json``, ``--verbose``, and ``--quiet`` to be placed at any
position in the command line:

- ``revolver --json llm list``     (root level -- already worked)
- ``revolver llm --json list``     (group level)
- ``revolver llm list --json``     (command level -- the fix)

Implements custom ``TyperGroup`` and ``TyperCommand`` subclasses that
intercept these three flags from the argument list before delegating to
the normal Click/Typer parsing, storing them in ``ctx.obj``.
"""

from __future__ import annotations

import click
from typer.core import TyperCommand, TyperGroup

# The global flags that should be recognised at any level
_GLOBAL_FLAGS = {"--json", "--verbose", "--quiet"}


def _extract_global_flags(args: list[str]) -> tuple[list[str], set[str]]:
    """Remove global flags from *args* and return (cleaned, found)."""
    found: set[str] = set()
    cleaned: list[str] = []
    for arg in args:
        if arg in _GLOBAL_FLAGS:
            found.add(arg)
        else:
            cleaned.append(arg)
    return cleaned, found


def _apply_flags_to_context(ctx: click.Context, flags: set[str]) -> None:
    """Merge extracted flags into *ctx.obj*."""
    if not flags:
        return
    ctx.ensure_object(dict)
    if "--json" in flags:
        ctx.obj["json"] = True
    if "--verbose" in flags:
        ctx.obj["verbose"] = True
    if "--quiet" in flags:
        ctx.obj["quiet"] = True


class GlobalOptionGroup(TyperGroup):
    """TyperGroup subclass that intercepts global flags."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        args, flags = _extract_global_flags(args)
        _apply_flags_to_context(ctx, flags)
        return super().parse_args(ctx, args)


class GlobalOptionCommand(TyperCommand):
    """TyperCommand subclass that intercepts global flags."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        args, flags = _extract_global_flags(args)
        _apply_flags_to_context(ctx, flags)
        return super().parse_args(ctx, args)
