# ADR-003 — Typer as CLI Framework

**Date**: 2026-03-10
**Status**: Accepted
**Deciders**: the project maintainer

---

## Context

Revolver is a CLI-first tool (NFR-007) with ~30 subcommands across 9 command groups, nested two levels deep (e.g., `revolver llm start`, `revolver benchmark export`). The CLI must support:

- Two-level nested subcommands (8 groups + 2 top-level commands)
- Global options on all commands: `--json`, `--verbose`, `--quiet`, `--help` (NFR-002, NFR-003)
- Tab completion for bash and zsh (NFR-008)
- Custom exit codes: 0, 1, 2, 3, 4 (§4.2 of specifications)
- Progress indicators for long-running commands (NFR-005)
- In-process test runner (no subprocess needed)
- Python >= 3.12 (ADR-002), pip-installable (NFR-060)

Three candidates were evaluated: **Typer**, **Click**, and **argparse** (stdlib).

## Decision

**Typer** (>= 0.21) is the CLI framework for Revolver.

Typer is built on top of Click, using Python type hints to define CLI interfaces with minimal boilerplate. Each command group (llm, problem, dataset, etc.) is a separate `typer.Typer()` instance composed into the root app via `app.add_typer()`.

### Key patterns

- **Global options**: defined in `@app.callback()`, stored in `ctx.obj`, accessed via `typer.Context` in subcommands. Global options appear before the subcommand: `revolver --json llm list`.
- **Tab completion**: built-in via Click 8.x. Users run `revolver --install-completion` to configure their shell.
- **Testing**: `typer.testing.CliRunner` enables in-process CLI testing without subprocess.
- **Rich output**: native `rich` integration for tables, progress bars, and colored output.

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| **Typer** (selected) | Type-hint-driven: function signature = CLI definition. ~50% less boilerplate than Click. Built-in completion install (`--install-completion`). Native `rich` integration. Strong testing support. Active development (FastAPI ecosystem). | Pre-1.0 (v0.21.x), API could theoretically change. Adds transitive Click dependency. Help text grouping requires workarounds. |
| **Click** | Battle-tested (Flask, Celery, etc.). Largest plugin ecosystem (`click-contrib`, `rich-click`). Stable API (v8.2.x). Excellent nested command support — Click invented this pattern. | More verbose: every option is a decorator line (~50% more boilerplate). No type-hint inference. Tab completion requires manual shell script setup. |
| **argparse** (stdlib) | Zero dependencies. Universally known. Ships with Python. | Two-level nesting is painful and error-prone. No built-in test runner. Tab completion requires `argcomplete` (extra dependency). Global options require workarounds (parent parsers, two-pass parsing). No standard pattern for splitting CLI across files. ~70% more boilerplate than Typer. |

### Evaluation Matrix

| Criterion | Weight | Typer | Click | argparse |
|---|---|---|---|---|
| Nested subcommands | High | ++ | ++ | − |
| Global options (`--json`) | High | + | + | −− |
| Tab completion | Medium | ++ | + | − |
| Type annotations | Medium | ++ | 0 | −− |
| Testing support | High | ++ | ++ | − |
| Boilerplate reduction | Medium | ++ | + | −− |
| Maturity / stability | Medium | + | ++ | ++ |
| Community / ecosystem | Low | + | ++ | + |

## Consequences

### Positive

- **Minimal boilerplate**: for ~30 commands, type-hint-driven definitions save significant code. A typical command is 5-8 lines vs 10-15 (Click) or 15-25 (argparse).
- **Modern Python style**: type hints align with Python >= 3.12 and the project's mypy/pyright linting approach (ADR-002).
- **Click underneath**: Typer delegates to Click for the heavy lifting — battle-tested command parsing, shell completion, and context management.
- **One-command completion setup**: `revolver --install-completion` satisfies NFR-008 with zero user friction.
- **Rich integration**: progress bars (NFR-005), formatted tables, colored output come built-in.
- **Testable CLI**: `CliRunner` enables fast, in-process tests without mocking `sys.argv`.

### Negative

- **Pre-1.0 API**: Typer has not reached 1.0 yet. In practice the API has been stable, but breaking changes are theoretically possible on minor version bumps.
- **Transitive dependency**: Typer depends on Click and `rich`. This adds two dependencies beyond the framework itself (though both are widely used and well-maintained).
- **Global option placement**: `--json` must appear before the subcommand (`revolver --json llm list`, not `revolver llm list --json`). This is standard POSIX convention but may surprise some users.

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Typer breaking change before 1.0 | Low | Pin version in `pyproject.toml` (e.g., `typer>=0.21,<1.0`). Typer's API has been stable since 0.9+. |
| Help text grouping not natively supported | Low | Use `rich_help_panel` parameter (available since Typer 0.7) or custom `rich-click` integration. |
| `--json` before subcommand confuses users | Low | Document in `--help` output. Standard convention used by `docker`, `kubectl`, etc. |
| Typer abandoned / unmaintained | Very Low | Falls back to raw Click with moderate refactoring (Typer is a thin wrapper). |

## References

- [ADR-002](ADR-002-python-language.md) — Python >= 3.12 as implementation language
- [specifications.md](../../specs/specifications.md) — NFR-002, NFR-003, NFR-005, NFR-007, NFR-008
- [Typer documentation](https://typer.tiangolo.com/)
- [Click documentation](https://click.palletsprojects.com/)
- [Typer GitHub — nested subcommands](https://typer.tiangolo.com/tutorial/subcommands/nested-subcommands/)
- [Typer testing](https://typer.tiangolo.com/tutorial/testing/)
