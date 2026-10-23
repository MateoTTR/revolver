# Revolver — Project Guide for Humans and Agents

**Revolver** is a MLOps CLI platform that orchestrates a pluggable evolution
backend (OpenEvolve by default, ShinkaEvolve optional —
[ADR-007](docs/architecture/adr/ADR-007-pluggable-evolution-backend.md)) to
let users define optimization problems, manage LLMs (local or API), version
problems and datasets, generate solutions via LLM-guided evolution, and
benchmark results with full traceability.

> **Principle.** "Everything in the GitHub project must be self-contained
> and clear for humans and AI agents alike, without assumptions about any
> contributor's own development means (with or without AI, Claude Code or
> other)." —
> [ADR-008](docs/architecture/adr/ADR-008-documentation-and-process-strategy.md)

## How to use this file

- **Read this file first**, whether you are a person or an agent. It is the
  canonical entry point; everything else is reached from the index below.
  `CLAUDE.md` and `GEMINI.md` are one-line pointers to this file for tools
  that look for those names.
- Then read the issue you work on, the relevant specification
  (`docs/specs/`), design document (DES) and ADR, and the checklist under
  `docs/process/` for what you are about to do.
- **Local, personal instructions** — journal location, local environment
  paths, tool settings, automation — live in git-ignored per-tool files such
  as `CLAUDE.local.md` and are never committed. The repository carries project
  knowledge only; tooling stays private per contributor (ADR-008 D5).
- Nothing here assumes a particular editor, assistant or automation. Every
  command shown is a plain shell or `gh` command.

## Documentation index

| Document | Path | Purpose |
|---|---|---|
| ConOps | [docs/conops/conops.md](docs/conops/conops.md) | Concept of operations, personas, workflows |
| Specifications | [docs/specs/specifications.md](docs/specs/specifications.md) | Functional & non-functional requirements; index of the `spec-*.md` files |
| Architecture overview | [docs/architecture/architecture.md](docs/architecture/architecture.md) | System design, components, ADR and DES indexes |
| ADR template | [docs/architecture/adr/ADR-000-template.md](docs/architecture/adr/ADR-000-template.md) | Template for new ADRs |
| Changelog | [CHANGELOG.md](CHANGELOG.md) | Release history (Keep a Changelog), one section per tag; `[Unreleased]` collects the current sprint |
| Process checklists | [docs/process/README.md](docs/process/README.md) | Tool-neutral procedures: code / spec / validation / doc review, sprint planning, release & hotfix, Definition of Done |

### Architecture Decision Records (ADRs)

| ADR | Title | Status |
|---|---|---|
| [ADR-001](docs/architecture/adr/ADR-001-ollama-local-llm-backend.md) | Ollama as local LLM backend | Accepted |
| [ADR-002](docs/architecture/adr/ADR-002-python-language.md) | Python as implementation language | Accepted |
| [ADR-003](docs/architecture/adr/ADR-003-cli-framework-typer.md) | Typer as CLI framework | Accepted |
| [ADR-004](docs/architecture/adr/ADR-004-sqlite-structured-storage.md) | SQLite for structured storage | Accepted |
| [ADR-005](docs/architecture/adr/ADR-005-pydantic-data-models.md) | Pydantic for data models | Accepted |
| [ADR-006](docs/architecture/adr/ADR-006-openevolve-instance-injection.md) | Strategy A+B hybrid for OpenEvolve instance injection | Accepted |
| [ADR-007](docs/architecture/adr/ADR-007-pluggable-evolution-backend.md) | Pluggable evolution backend (OpenEvolve default, ShinkaEvolve optional) | Accepted (amended 2026-07-01, 2026-07-05) |
| [ADR-008](docs/architecture/adr/ADR-008-documentation-and-process-strategy.md) | Documentation and process strategy | Accepted (amended 2026-10-23) |

### Design Documents (DES)

| DES | Title | Status |
|---|---|---|
| [DES-001](docs/architecture/design/DES-001-sqlite-data-model.md) | SQLite Data Model | Draft |
| [DES-002](docs/architecture/design/DES-002-llm-subcommands.md) | `revolver llm` Subcommands — Ollama API Mapping | Draft |
| [DES-003](docs/architecture/design/DES-003-problem-versioning.md) | `revolver problem` — Testing & Versioning | Draft |
| [DES-004](docs/architecture/design/DES-004-dataset-registration.md) | `revolver dataset` — Registration & Integrity | Draft |
| [DES-005](docs/architecture/design/DES-005-run-orchestration.md) | `revolver run` — OpenEvolve Orchestration | Draft |
| [DES-006](docs/architecture/design/DES-006-eval-loop.md) | `revolver eval` — Evaluation Loop | Draft |
| [DES-007](docs/architecture/design/DES-007-benchmark-design.md) | `revolver benchmark` — Benchmark Design | Draft |

### Validation Documents

| Document | Path | Purpose |
|---|---|---|
| Validation overview | [docs/validation/validation.md](docs/validation/validation.md) | Strategy, levels, tools, CI pipeline, coverage targets |
| Integration tests | [docs/validation/val-integration-tests.md](docs/validation/val-integration-tests.md) | L2 command test matrix, fixtures, scenarios |
| E2E tests | [docs/validation/val-e2e-tests.md](docs/validation/val-e2e-tests.md) | L3 scenarios, LLM mocking, fake server |
| Traceability matrix | [docs/validation/traceability-matrix.md](docs/validation/traceability-matrix.md) | FR/NFR → DES → test mapping |

### Guides

| Document | Path | Purpose |
|---|---|---|
| Initial program guide | [docs/guides/initial-program-structure.md](docs/guides/initial-program-structure.md) | Best practices for OpenEvolve initial programs |
| Tuning guide | [docs/guides/tuning-evolution.md](docs/guides/tuning-evolution.md) | Tuning evolution runs — backend-neutral concepts, cross-engine ensembles, OpenEvolve/ShinkaEvolve knob references |

### Process checklists

| Procedure | Path | When |
|---|---|---|
| Code review | [docs/process/code-review.md](docs/process/code-review.md) | Every pull request before it is marked ready (self-review, then reviewer) |
| Specification review | [docs/process/spec-review.md](docs/process/spec-review.md) | A spec, DES or ADR changed; pre-release audit |
| Validation review | [docs/process/validation-review.md](docs/process/validation-review.md) | A validation document or spec changed; pre-release audit; traceability sweep |
| Documentation review | [docs/process/doc-review.md](docs/process/doc-review.md) | After a release; README / guides / E2E walkthrough or `src/revolver/cli/*.py` changed |
| Sprint planning | [docs/process/sprint-planning.md](docs/process/sprint-planning.md) | Sprint boundaries |
| Release and hotfix | [docs/process/release.md](docs/process/release.md) | Tagging a version; shipping a critical fix |
| Definition of Done | [docs/process/definition-of-done.md](docs/process/definition-of-done.md) | Any feature pull request; a new evolution backend |

## Key constraints

- **CLI-first**: all functionality exposed as CLI commands, composable in scripts
- **Backend-based**: solution generation relies on a pluggable evolution backend — OpenEvolve by default, ShinkaEvolve optional (ADR-007)
- **LLM-agnostic**: must support local models and multiple API providers (Anthropic, Google, OpenAI)
- **LLM interface**: all LLMs must expose an OpenAI-compatible API (native or via adapter)
- **Full traceability**: every solution must trace back to problem version, dataset, LLM, and config
- **Reproducibility**: a backend capability — guaranteed on OpenEvolve given the same config and seed; not guaranteed on ShinkaEvolve (no global search seed — ADR-007)

## Project phases

| Phase | Focus | Status |
|---|---|---|
| Phase 1 | Framing: ConOps + functional specifications | **Done** |
| Phase 2 | Architecture, technology choices (ADRs), data model | **Done** |
| Phase 3 | POCs for critical aspects | **Done** (three proof-of-concept studies; findings recorded in ADR-001 and ADR-006) |
| Phase 4 | Validation strategy, test plan, traceability | **Done** |
| Phase 5 | Implementation | **In progress** — see [CHANGELOG.md](CHANGELOG.md) for the release history and the open milestones for the current sprint |

## Conventions

### Language

All code, comments, identifiers, documentation, issues, pull requests and
reviews are in **English**.

### Public-file rule

Everything committed here is public. No file, issue, pull request or review
may contain a local filesystem path, a machine or runner hostname, a private
repository name, an e-mail address, personal timing data, GitHub handles of
third parties, or business-domain vocabulary. Use neutral wording ("a local
path", "a network Ollama host", "a separate demo repository"). See
[docs/process/README.md](docs/process/README.md#public-file-rule).

### File naming

- ADRs: `ADR-NNN-short-title.md`; design documents: `DES-NNN-short-title.md` (zero-padded 3-digit numbers); specifications: `spec-<group>.md`; ConOps: `conops.md` (single living document).

### Git

- **Git Flow**: `main` is production-ready and tagged at each release; `develop` is the integration branch and the target of every pull request; `feature/<topic>` is one branch per pull request (sprint work uses `feature/s<NN>-<topic>`); `hotfix/vX.Y.Z` and `release/*` as needed.
- Commit messages: English, imperative mood (`Add`, `Fix`, `Update`…), one logical change per commit.
- CI (`.github/workflows/ci.yml`) runs on pushes and non-draft pull requests to `main` and `develop`. The four required checks are `Lint (ruff + mypy)`, `Test (pytest + coverage) (3.12)`, `Test (pytest + coverage) (3.14)` and `Doc command-lint (fenced CLI invocations)`; a `version-check` job runs on `v*` tags only. Coverage must stay ≥ 80 %.
- **Irreversible actions are maintainer-only**: merging into `main`, tags, version bumps, repository visibility and settings. Contributors never run `gh pr merge`, `git merge` into `main`, `git tag` or bump versions; they open the pull request or propose the action and wait for the maintainer.

## Planning model (GitHub-native)

- The **backlog** is the GitHub issue list, organised with labels (type / area / priority / backend).
- A **sprint** is a **milestone** plus a **planning issue** whose body carries the scope, the verified facts, the task table, the PR mapping, the waves, the conflict map and the exit criteria ([docs/process/sprint-planning.md](docs/process/sprint-planning.md)).
- The **sprint review** is the release section in `CHANGELOG.md` plus the closing comment of the planning issue.
- Planning lives on GitHub only; no planning file is kept in the repository (ADR-008 D2, amended 2026-10-23 by A2).
- In documents written before v0.19.0, a number written `#N` that names a task, a spike or a carry-over is a former backlog row, not a GitHub issue or pull request (the two numberings overlap); new text writes "backlog row N" and keeps `#N` for GitHub items (ADR-008 A3 scope note).

## Pull request workflow

1. **Issue first.** Every pull request closes a GitHub issue that states the scope, the files to touch, the acceptance criteria, the test scenarios and the spec / DES / ADR references. The issue is the single source of truth for the change. External contributors proposing a design change open a **design issue** first (RFC-lite): the maintainer then updates — or reviews the contributor's edits to — the formal specification, DES, ADR and validation documents.
2. **Branch** from `develop`: `feature/<topic>`.
3. **Draft pull request** against `develop`, as soon as the branch exists: the first line of the description is `Closes #N`; a short **Status** section is kept up to date at each working session (what is done, what is next, what blocks). Drafts do not run CI.
4. **Local gates** before asking for review, on Python 3.12 (and 3.14 when available), after `pip install -e ".[dev]"`:
   `ruff check src/ tests/` · `ruff format --check src/ tests/` · `mypy` · `pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"`.
   Engine-specific tests (`-m openevolve`, `-m shinkaevolve`) are not run by CI: state in the pull request how they were run.
5. **Self-review** against [docs/process/code-review.md](docs/process/code-review.md) and the [Definition of Done](docs/process/definition-of-done.md); then a reviewer applies the same checklist and posts a pull-request review.
6. **Ready** (`gh pr ready <N>`) only with **0 CRITICAL** findings, every WARNING fixed or explicitly carried over, and one line added under `[Unreleased]` in `CHANGELOG.md`. The four required checks must be green.
7. **The maintainer merges** on GitHub.

Independent pull requests proceed in parallel; a pull request that depends on
another waits for it to be merged into `develop` (the planning issue's
conflict map says which order).

## Release, hotfix, Definition of Done, reviews

- Release and hotfix: [docs/process/release.md](docs/process/release.md).
- Definition of Done (feature; new evolution backend): [docs/process/definition-of-done.md](docs/process/definition-of-done.md).
- Review procedures (code, specification, validation, documentation) and sprint planning: the other files of [docs/process/](docs/process/README.md).
