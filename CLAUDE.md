# Revolver — Claude Instructions

## Project Overview

**Revolver** is a MLOps CLI platform that orchestrates a pluggable evolution backend (OpenEvolve by default, ShinkaEvolve optional — ADR-007) to let users define optimization problems, manage LLMs (local or API), version problems and datasets, generate solutions via LLM-guided evolution, and benchmark results with full traceability.

## How to Use This File

At the start of each session, read this file entirely, then follow the "Session Checklist" below before starting any work.

---

## Documentation Index

| Document | Path | Purpose |
|---|---|---|
| ConOps | [docs/conops/conops.md](docs/conops/conops.md) | Concept of operations, personas, workflows |
| Specifications | [docs/specs/specifications.md](docs/specs/specifications.md) | Functional & non-functional requirements |
| Architecture overview | [docs/architecture/architecture.md](docs/architecture/architecture.md) | System design, components, ADR list |
| ADR template | [docs/architecture/adr/ADR-000-template.md](docs/architecture/adr/ADR-000-template.md) | Template for new ADRs |
| Task backlog | [docs/tasks/backlog.md](docs/tasks/backlog.md) | Numbered task list with status |
| Session reports | [docs/sessions/](docs/sessions/) | One file per session, sorted by date |
| Session cost tracker | [docs/sessions/cost-tracker.md](docs/sessions/cost-tracker.md) | Cumulative session duration and token usage |

### Architecture Decision Records (ADRs)

| ADR | Title | Status |
|---|---|---|
| [ADR-001](docs/architecture/adr/ADR-001-ollama-local-llm-backend.md) | Ollama as local LLM backend | Accepted |
| [ADR-002](docs/architecture/adr/ADR-002-python-language.md) | Python as implementation language | Accepted |
| [ADR-003](docs/architecture/adr/ADR-003-cli-framework-typer.md) | Typer as CLI framework | Accepted |
| [ADR-004](docs/architecture/adr/ADR-004-sqlite-structured-storage.md) | SQLite for structured storage | Accepted |
| [ADR-005](docs/architecture/adr/ADR-005-pydantic-data-models.md) | Pydantic for data models | Accepted |
| [ADR-006](docs/architecture/adr/ADR-006-openevolve-instance-injection.md) | Strategy A+B hybrid for OpenEvolve instance injection | Accepted |
| [ADR-007](docs/architecture/adr/ADR-007-pluggable-evolution-backend.md) | Pluggable evolution backend (OpenEvolve default, ShinkaEvolve optional) | Accepted |

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
| Tuning OE config guide | [docs/guides/tuning-oe-config.md](docs/guides/tuning-oe-config.md) | Tuning OpenEvolve parameters (MAP-Elites, islands, parallelism, temperature) |

### Claude Agents

| Agent | Path | Trigger |
|---|---|---|
| code-reviewer | [.claude/agents/code-reviewer/agent.md](.claude/agents/code-reviewer/agent.md) | Auto after `gh pr create` (PostToolUse hook) |
| spec-reviewer | [.claude/agents/spec-reviewer/agent.md](.claude/agents/spec-reviewer/agent.md) | When spec/DES/ADR files are modified |
| validation-reviewer | [.claude/agents/validation-reviewer/agent.md](.claude/agents/validation-reviewer/agent.md) | When validation docs or specs change |
| doc-reviewer | [.claude/agents/doc-reviewer/agent.md](.claude/agents/doc-reviewer/agent.md) | After release, or when README/guides/user-story-e2e change. Run AFTER spec-reviewer and validation-reviewer |
| scrum-master | [.claude/agents/scrum-master/agent.md](.claude/agents/scrum-master/agent.md) | At sprint planning/review boundaries |

### Sprint Planning

| Document | Path | Purpose |
|---|---|---|
| Sprint files | [docs/sprints/](docs/sprints/) | One file per sprint: scope, tasks, parallelization, review |

---

## Session Checklist

Before starting any work in a session:

1. Read this file (`CLAUDE.md`)
2. Read [docs/tasks/backlog.md](docs/tasks/backlog.md) — identify the current in-progress or next task
3. Read the relevant ADRs if the task involves an architectural decision
4. Read [docs/specs/specifications.md](docs/specs/specifications.md) if the task involves a feature
5. Check the latest session report in [docs/sessions/](docs/sessions/) for context from previous session
6. At the end of the session:
   - Create a session report in `docs/sessions/YYYY-MM-DD-session-NNN.md`
   - Include **session duration** (start time → end time) and **token count** (if provided by the user) in the report header
   - Update [docs/sessions/cost-tracker.md](docs/sessions/cost-tracker.md) with the new session row and recalculate totals
   - Update the backlog

---

## Project Phases

| Phase | Focus | Status |
|---|---|---|
| Phase 1 | Cadrage: ConOps + Functional Specifications | **Done** |
| Phase 2 | Architecture, tech choices (ADRs), data model | **Done** |
| Phase 3 | POCs for critical aspects | **Done** (covered by POC #11/12/13) |
| Phase 4 | Validation strategy, test plan, traceability | **Done** |
| Phase 5 | Implementation | **In progress** — Sprint 009 complete (v0.9.0 released) |

---

## General Conventions

### Language
- All code, comments, variable names, and documentation must be in **English**.
- Communication with the user is in **French**.

### File Naming
- ADRs: `ADR-NNN-short-title.md` (zero-padded 3-digit number)
- Tasks: `TASK-NNN-short-title.md`
- Sessions: `YYYY-MM-DD-session-NNN.md`
- Sprints: `sprint-NNN.md` (zero-padded 3-digit number)
- ConOps: `conops.md` (single living document)

### Git
- Commit message format: English, imperative mood (`Add`, `Fix`, `Update`...)
- Branching strategy: **Git Flow**
  - `main` — production-ready, tagged at sprint end (e.g. `v0.1.0`)
  - `develop` — integration branch, PRs target here
  - `feature/*` — one branch per PR (e.g. `feature/s1-scaffold-ci`)
  - `release/*`, `hotfix/*` — as needed
- CI pipeline: `.github/workflows/ci.yml` — ruff, mypy, pytest + coverage (≥80%), runs on push/PR to main/develop
- **Irreversible actions require explicit user approval**: never execute `gh pr merge`, `git merge` into main, `git tag`, or version bumps without the user's go-ahead. Always create the PR or propose the action, then wait for confirmation.

### Release Checklist

Before tagging a release (`vX.Y.Z`):

0. **(Optional) Documentation audit cascade** — Run before the release to catch spec/doc drift accumulated during the sprint. Skip for hotfixes or when the sprint had no spec changes.
   - **spec-reviewer** → fix all FAIL/WARN findings → commit on `develop`
   - **validation-reviewer** → fix all FAIL/WARN findings → commit on `develop`
   - *(release steps 1–6 below)*
   - **doc-reviewer** → fix all FAIL/WARN findings → commit + push (runs post-release because it checks version numbers in README/guides)
1. **Version bump** — Update `version` in **both** `pyproject.toml` and `src/revolver/__init__.py`
1b. **README update (when the release changes user-facing behavior)** — Refresh `README.md` on `develop` before the merge to `main`: features list, release/sprint table, install instructions (extras), CLI examples, test counts. The post-release doc-reviewer validates it but must not be the first time the README sees the release.
2. **Merge completeness** — Ensure ALL sprint PRs are merged into `develop`
3. **Commit + push** — Commit the version bump on `develop`, push
4. **Merge `develop` → `main`** — `git checkout main && git merge develop`
5. **Tag on `main`** — `git tag vX.Y.Z && git push origin main --tags`
6. **Verify install** — `pip install "revolver @ git+file:///home/mathi/revolver@vX.Y.Z"` then `revolver --version`
7. **Post-release verification** — Before declaring the release complete, run these checks and report any failures:
   - `git tag -l vX.Y.Z` → tag exists
   - `grep 'version' pyproject.toml` and `grep '__version__' src/revolver/__init__.py` → both match `X.Y.Z`
   - `git log main --oneline -1` → tip of main is the merge commit
   - Session report exists in `docs/sessions/`
   - `docs/sessions/cost-tracker.md` updated
   - `docs/tasks/backlog.md` updated

### Hotfix Process

For critical bugs discovered after a release:

1. **Branch** — `git checkout -b hotfix/vX.Y.Z develop`
2. **Fix + tests** — Apply fix, run full test suite, lint
3. **Draft PR** — `gh pr create --draft --base develop`
4. **Code review** — Run code-review agent, address findings
5. **Ready + merge** — `gh pr ready`, user merges on GitHub
6. **Release** — Follow the Release Checklist above (bump, merge to main, tag)

### PR Development Workflow

Each PR follows a standardized 5-step process:

1. **GitHub Issue** — `gh issue create` with: scope (sprint tasks), files to create/modify, acceptance criteria, test scenarios, DES/spec references. The issue is the single source of truth for the feature.
2. **Dev Agent (worktree)** — Launch a worktree-isolated agent. The agent reads the issue via `gh issue view <number>`, plus project docs (DES, specs, existing code). It implements, tests, commits, and **pushes the branch** — then stops and reports. It does **NOT** run `gh pr create`: a PR created inside a background subagent does not trigger the code-review hook in a session that acts on it, so such PRs ship unreviewed.
3. **Draft PR (from the main / orchestrator session)** — The orchestrator (main session), **not** the worktree agent, runs `gh pr create --draft` linking the issue (`Closes #N`). Creating the PR from the main session is what lets the `gh pr create` PostToolUse hook fire in the main loop and auto-launch the code-reviewer (step 4). Draft prevents CI from running prematurely.
4. **Code Review Agent** — Auto-triggered by the hook once the main session creates the PR. Run it **foreground** (these reviewer agents tend to hit the harness idle-timeout when backgrounded). Reviews the diff, posts structured findings as a PR review (CRITICAL/WARNING/SUGGESTION/GOOD).
5. **Fix & Ready** — Address review findings, push fixes, then `gh pr ready` to mark as ready (triggers CI).
6. **Merge** — User merges on GitHub after CI passes.

Independent PRs are developed in parallel using separate worktree agents. Dependent PRs wait for their prerequisites to be merged into `develop`.

---

## Key Constraints

- **CLI-first**: all functionality exposed as CLI commands, composable in scripts
- **Backend-based**: solution generation relies on a pluggable evolution backend — OpenEvolve by default, ShinkaEvolve optional (ADR-007)
- **LLM-agnostic**: must support local models and multiple API providers (Anthropic, Google, OpenAI)
- **LLM interface**: all LLMs must expose an OpenAI-compatible API (native or via adapter)
- **Full traceability**: every solution must trace back to problem version, dataset, LLM, and config
- **Reproducibility**: a backend capability — guaranteed on OpenEvolve given the same config and seed; not guaranteed on ShinkaEvolve (no global search seed — ADR-007)

