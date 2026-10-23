# Documentation review checklist

This review keeps the **user-facing documentation** aligned with both the
specifications and the actual CLI implementation. It runs **last** in the
review cascade — after the [specification review](spec-review.md) and the
[validation review](validation-review.md) — so the specs can be assumed
consistent. The reviewer reports; fixes come in a separate pass.

## When to run

- **After a release** — version numbers, install instructions, the release pointers in the README.
- **When user-facing docs change** — `README.md`, `docs/guides/*.md`, `docs/specs/user-story-e2e.md`.
- **When CLI source changes** (`src/revolver/cli/*.py`) — the inverted trigger: a renamed command, flag or changed default silently strands docs that the change never touched. Review the docs against the **new** CLI surface, focusing on the commands and flags the diff modified.

Line-initial `revolver` invocations inside fenced blocks of `README.md` and
`docs/**` are machine-checked by the doc command-lint test
(`tests/unit/test_doc_command_lint.py`, walker in `src/revolver/cli/_tree.py`),
and the `verified-against` stamps of the guides by
`tests/unit/test_doc_freshness.py`. Prioritize what those tests cannot see:
inline-prose command mentions, transcript output blocks, flag semantics and
defaults, narrative accuracy.

## Inputs

| File | What it should reflect |
|---|---|
| `README.md` | Current version, feature list, CLI examples, test count, install instructions, pointer to `CHANGELOG.md` |
| `docs/guides/initial-program-structure.md` | Valid CLI syntax, correct flag names, accurate workflow descriptions |
| `docs/guides/tuning-evolution.md` | Valid CLI flags, correct config key names, accurate parameter descriptions for both backends |
| `docs/specs/user-story-e2e.md` | Accurate CLI syntax matching the actual Typer command signatures |

Discover at run time: `README.md`; `docs/guides/*.md`;
`docs/specs/user-story-e2e.md`; `src/revolver/cli/*.py` (Typer command
definitions); `src/revolver/__init__.py` (canonical version string);
`pyproject.toml` (package version, `requires-python`). On an installed
checkout, `revolver --help` and the `--help` of each command give the live
surface.

## Steps

### 1. Version consistency (`README.md`)

Extract the version from `pyproject.toml` (`version = "X.Y.Z"`) and from
`src/revolver/__init__.py` (`__version__`); verify the README states the
correct version wherever it names one (badges, text, install examples).
Mismatches are **FAIL**.

### 2. Feature-list accuracy (`README.md`)

Extract the CLI command groups from `src/revolver/cli/*.py` (`typer.Typer()`
apps and command decorators). Each implemented group is listed in the README
feature section (**WARN** when missing); a group listed but not implemented
is **FAIL**.

### 3. CLI syntax in examples (README, guides, E2E walkthrough)

For each CLI example (lines starting with `revolver ` or `$ revolver `), find
the corresponding Typer command in `src/revolver/cli/*.py` and verify: the
subcommand exists; flag names match (e.g. `--temperature`, not `--temp`);
positional-argument order matches; removed flags are not referenced. Invalid
syntax is **FAIL**; a deprecated flag still referenced is **WARN**.

### 4. Flag / option inventory (guides)

For each `--flag` mentioned in a guide: the flag exists on the corresponding
command (**FAIL** otherwise) and its type / range description matches the
Typer definition (e.g. a `float` in 0.0–2.0 for temperature; **WARN**
otherwise).

### 5. Config-key accuracy (guides)

For config keys mentioned in the guides (e.g. `llm.temperature`,
`evaluator.parallel_evaluations`), verify the key exists in the backend's
`build_config()` (`src/revolver/infra/backends/openevolve.py`,
`src/revolver/infra/backends/shinka.py`). Non-existent keys are **FAIL**.

### 6. Test count (`README.md`)

If the README states a test count, note it as **INFO**: it is a snapshot and
drifts every sprint. Never **FAIL** on a test-count mismatch.

### 7. Install instructions (`README.md`)

Install commands reference valid URLs, extras and package names; the Python
requirement matches `requires-python` in `pyproject.toml`. Mismatches are
**WARN**.

### 8. Cross-reference with the specs

Feature descriptions in the README and guides are consistent with the
corresponding `docs/specs/spec-*.md` (the specs are the source of truth).
Contradictions are **WARN**.

### 9. Freshness stamps (guides and E2E walkthrough)

Every `docs/guides/*.md` file and `docs/specs/user-story-e2e.md` opens with a
`verified-against: vX.Y.Z` front-matter stamp at the current release (the
test tolerates one minor version of lag; the release procedure refreshes the
stamps). A stale stamp after a release is **WARN**; a missing stamp is **FAIL**.

## Severity vocabulary

- **PASS** — check passed (note briefly what was checked)
- **INFO** — notable observation, no action required
- **WARN** — inconsistency to fix; suggest the correction
- **FAIL** — broken reference or factual error, with file paths and line numbers

## Output format

One line per check with its severity, grouped by document, then the summary
line `N checks, N PASS, N warnings, N failures`.

## Where to post

- After a release: as a comment on the release or planning issue, followed by
  a fix commit on `develop`; the review must reach 0 FAIL.
- Otherwise: as a review comment on the pull request that changes the docs or
  the CLI source.

## Changes from the former agent definition

- **(changed)** The config-key check pointed to `src/revolver/infra/openevolve.py`; the module moved to `src/revolver/infra/backends/openevolve.py` with ADR-007, and the ShinkaEvolve backend is checked alike.
- **(changed)** The example of a removed flag ("`--rank` was removed in Sprint 009") is dropped: `solution extract --rank` was re-introduced in v0.18.0. The CLI tree (`src/revolver/cli/_tree.py`, including its `DEPRECATED_FLAGS` registry) is the reference for the current surface.
- **(changed)** "README release table" becomes the README's pointer to `CHANGELOG.md` (the release table moved there at v0.19.0).
- **(changed)** Findings are reported in English; the agent-harness "run discipline" paragraph is dropped; "OK" is written "PASS".
- **(added)** Check 9 restates the freshness-stamp rule enforced by `tests/unit/test_doc_freshness.py`; it was not in the prompt.
