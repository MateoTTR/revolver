"""Custom Typer/Click classes for global option propagation.

Allows ``--json``, ``--verbose``, ``--quiet`` and ``--global-db`` to be placed
at any position in the command line:

- ``revolver --json llm list``     (root level -- already worked)
- ``revolver llm --json list``     (group level)
- ``revolver llm list --json``     (command level -- the fix)

The first three are boolean flags. ``--global-db`` takes a *value* — a full
path to the global DB file (``--global-db <path>`` or ``--global-db=<path>``) —
overriding the global DB resolution for power users / CI isolation.

Implements custom ``TyperGroup`` and ``TyperCommand`` subclasses that intercept
these options from the argument list before delegating to the normal
Click/Typer parsing, storing the booleans in ``ctx.obj`` and bridging the
``--global-db`` value into ``$REVOLVER_GLOBAL_DB`` so the zero-argument
``get_global_db()`` factory (called from ~17 sites without ``ctx.obj``) picks it
up without any call-site changes.
"""

from __future__ import annotations

import os
from typing import Any

import click
from typer.core import TyperCommand, TyperGroup

from revolver.infra.db import REVOLVER_GLOBAL_DB_ENV

# The boolean global flags that should be recognised at any level.
_GLOBAL_FLAGS = {"--json", "--verbose", "--quiet"}

# The value-taking global option (full path to the global DB file).
_GLOBAL_DB_FLAG = "--global-db"


def _extract_global_flags(args: list[str]) -> tuple[list[str], set[str], str | None]:
    """Remove global options from *args*.

    Returns ``(cleaned, boolean_flags, global_db_value)`` where *cleaned* is the
    argument list with all global options stripped, *boolean_flags* is the set
    of boolean flags found, and *global_db_value* is the ``--global-db`` path
    (last one wins) or ``None``.
    """
    found: set[str] = set()
    global_db: str | None = None
    cleaned: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in _GLOBAL_FLAGS:
            found.add(arg)
        elif arg == _GLOBAL_DB_FLAG:
            # ``--global-db <path>`` — consume the following token as the value,
            # but only when it looks like a value (not another option). A bare
            # flag, or one immediately followed by another option, is left in
            # ``cleaned`` so Click surfaces its native "option requires an
            # argument" error instead of silently swallowing the next token
            # (``--global-db --json`` would otherwise set the path to "--json").
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                global_db = args[i + 1]
                i += 1
            else:
                cleaned.append(arg)
        elif arg.startswith(_GLOBAL_DB_FLAG + "="):
            # ``--global-db=<path>`` — value is inline.
            global_db = arg[len(_GLOBAL_DB_FLAG) + 1 :]
        else:
            cleaned.append(arg)
        i += 1
    return cleaned, found, global_db


def _apply_flags_to_context(
    ctx: click.Context, flags: set[str], global_db: str | None = None
) -> None:
    """Merge extracted global options into *ctx.obj* and the process env."""
    # An empty ``--global-db=`` value counts as "not provided" — treat it as
    # falsy so it never sets a stray empty env var (matched by the root-callback
    # bridge in cli.__init__).
    if not flags and not global_db:
        return
    ctx.ensure_object(dict)
    if "--json" in flags:
        ctx.obj["json"] = True
    if "--verbose" in flags:
        ctx.obj["verbose"] = True
    if "--quiet" in flags:
        ctx.obj["quiet"] = True
    if global_db:
        # Bridge the value into the env var consulted by ``get_global_db()``.
        # This needs no call-site changes and is isolatable via monkeypatch.
        ctx.obj["global_db"] = global_db
        os.environ[REVOLVER_GLOBAL_DB_ENV] = global_db


# ``ctx`` is typed as ``Any`` on the ``parse_args`` overrides below: the base
# ``TyperGroup``/``TyperCommand`` expect Typer's vendored Click context
# (``typer._click.core.Context`` in recent Typer releases), which is a distinct
# class from the public ``click.Context`` and varies across Typer versions.
# Using ``Any`` keeps the override LSP-compatible without importing a private
# Typer module. At runtime Typer always passes a Click-compatible context.


class GlobalOptionGroup(TyperGroup):
    """TyperGroup subclass that intercepts global options."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        args, flags, global_db = _extract_global_flags(args)
        _apply_flags_to_context(ctx, flags, global_db)
        return super().parse_args(ctx, args)


class GlobalOptionCommand(TyperCommand):
    """TyperCommand subclass that intercepts global options."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        args, flags, global_db = _extract_global_flags(args)
        _apply_flags_to_context(ctx, flags, global_db)
        return super().parse_args(ctx, args)
