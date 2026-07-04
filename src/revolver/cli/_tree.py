"""CLI command-tree walker — shared doc-lint / help-tooling helper (#354).

Reusable introspection over the ``revolver`` Typer command tree rooted at
:data:`revolver.cli.app`. Consumers:

- the doc command-lint CI test (``tests/unit/test_doc_command_lint.py``,
  S18-21), which asserts that every fenced-block ``revolver`` invocation in
  the documentation corpus resolves against the real CLI;
- the planned CLI help/reference generator (backlog #357, Sprint 019).

Implementation notes
--------------------
- Typer >= 0.16 vendors Click as ``typer._click``: the command/group classes
  produced by :func:`typer.main.get_command` are *distinct* from the public
  ``click`` package's, so ``isinstance`` checks against real Click fail.
  Everything here is duck-typed on attributes (``commands``, ``params``,
  ``opts``, ``param_type_name``, ...) instead.
- ``--json``/``--verbose``/``--quiet``/``--global-db`` are stripped at any
  level by :class:`revolver.cli._global_options.GlobalOptionGroup` *before*
  Click parsing, so they never appear in subcommand ``params``. The walker
  re-injects them as valid at every level (single source of truth: the
  ``_global_options`` constants).
- :data:`DEPRECATED_FLAGS` is the explicit registry of deprecated-but-still-
  accepted flags (currently ``problem version create --tag``). The validator
  unions it into the per-command option table so documentation using a
  deprecated spelling never false-positives while the CLI still accepts it,
  even if a future refactor moves the flag out of the Click ``params`` (as
  happened to the global flags). The #357 help generator should *exclude*
  these flags from generated references.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import typer.main

from revolver.cli import app
from revolver.cli._global_options import _GLOBAL_DB_FLAG, _GLOBAL_FLAGS

# Deprecated flags that must keep resolving: ``path -> {flag: takes_value}``.
# ``path`` is the subcommand path below the root (no leading "revolver").
DEPRECATED_FLAGS: dict[tuple[str, ...], dict[str, bool]] = {
    ("problem", "version", "create"): {"--tag": True},
}

# Options accepted at every level of the tree: the GlobalOptionGroup-stripped
# global flags (value-less), --global-db (takes a path value), and --help.
UNIVERSAL_OPTIONS: dict[str, bool] = {
    **dict.fromkeys(sorted(_GLOBAL_FLAGS), False),
    _GLOBAL_DB_FLAG: True,
    "--help": False,
}

_UNLIMITED = -1


def get_cli_root() -> Any:
    """Return the root (vendored-)Click command for the ``revolver`` app."""
    return typer.main.get_command(app)


def subcommands(command: Any) -> dict[str, Any]:
    """Return the subcommand mapping of *command* (empty for leaf commands).

    Duck-typed on the ``.commands`` dict attribute — works for both real
    Click groups and Typer's vendored-Click groups.
    """
    commands = getattr(command, "commands", None)
    return dict(commands) if isinstance(commands, dict) else {}


def walk_commands(
    root: Any = None, _path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Depth-first walk of the command tree.

    Yields ``(path, command)`` pairs where ``path`` is the subcommand path
    below the root (the root itself is yielded with an empty path). Group
    nodes are yielded too: their ``params`` carry the group-callback options
    (``run``/``eval`` are ``invoke_without_command=True`` groups whose flags
    live on the callback).
    """
    if root is None:
        root = get_cli_root()
    yield _path, root
    for name, sub in sorted(subcommands(root).items()):
        yield from walk_commands(sub, (*_path, name))


def option_table(command: Any, path: tuple[str, ...] = ()) -> dict[str, bool]:
    """Map every option string accepted by *command* to ``takes_value``.

    Includes primary and secondary spellings (``--force``/``-f``,
    ``--no-templates``/``--templates``), the universal options valid at any
    level, and the :data:`DEPRECATED_FLAGS` registered for *path*.
    """
    table: dict[str, bool] = dict(UNIVERSAL_OPTIONS)
    for param in getattr(command, "params", []):
        if getattr(param, "param_type_name", "") != "option":
            continue
        takes_value = not getattr(param, "is_flag", False)
        for opt in (*getattr(param, "opts", []), *getattr(param, "secondary_opts", [])):
            table[opt] = takes_value
    table.update(DEPRECATED_FLAGS.get(path, {}))
    return table


def max_positional_args(command: Any) -> int:
    """Max positional-argument tokens *command* accepts (:data:`_UNLIMITED` = no cap).

    Counts the ``argument`` params (group callbacks included); a variadic
    argument (``nargs=-1``) lifts the cap entirely.
    """
    total = 0
    for param in getattr(command, "params", []):
        if getattr(param, "param_type_name", "") != "argument":
            continue
        nargs = getattr(param, "nargs", 1)
        if nargs == -1:
            return _UNLIMITED
        total += int(nargs)
    return total


def _format_path(path: tuple[str, ...]) -> str:
    return " ".join(("revolver", *path))


def validate_invocation(tokens: list[str], root: Any = None) -> str | None:
    """Validate a tokenized ``revolver`` invocation against the command tree.

    *tokens* is the shell-token list **including** the leading ``revolver``.
    Returns ``None`` when every subcommand resolves, every option is known at
    its level, and positional counts stay within the declared arguments;
    otherwise returns a human-readable error string.

    Grammar notes:

    - option values are skipped (``--llm NAME`` / ``--llm=NAME``), never
      validated;
    - a positional token descends into a matching subcommand while no plain
      positional has been consumed yet; ``a/b/c`` shorthand (README feature
      lists) is accepted when **every** part is a subcommand (descends into
      the first part);
    - positional-count checking only flags *excess* positionals — docs may
      legitimately elide required arguments.
    """
    if root is None:
        root = get_cli_root()
    if not tokens or tokens[0] != "revolver":
        return f"not a revolver invocation: {tokens!r}"

    command = root
    path: tuple[str, ...] = ()
    positionals = 0
    descending = True
    skip_value = False

    for token in tokens[1:]:
        if skip_value:
            skip_value = False
            continue
        if token.startswith("-") and token != "-":
            name = token.split("=", 1)[0]
            options = option_table(command, path)
            if name not in options:
                return f"unknown option '{name}' for '{_format_path(path)}'"
            if options[name] and "=" not in token:
                skip_value = True
            continue

        subs = subcommands(command)
        if descending and subs:
            parts = token.split("/") if "/" in token else [token]
            if parts and all(part in subs for part in parts):
                command = subs[parts[0]]
                path = (*path, parts[0])
                continue
        if subs and max_positional_args(command) == 0:
            return f"unknown command '{token}' under '{_format_path(path)}'"
        descending = False
        positionals += 1
        cap = max_positional_args(command)
        if cap != _UNLIMITED and positionals > cap:
            return (
                f"too many positional arguments for '{_format_path(path)}': "
                f"'{token}' (got {positionals}, max {cap})"
            )

    return None
