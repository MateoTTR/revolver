# Revolver — Claude Instructions

## Project Overview

**Revolver** is a MLOps CLI platform that orchestrates OpenEvolve to let users define optimization problems, manage LLMs (local or API), version problems and datasets, generate solutions via LLM-guided evolution, and benchmark results with full traceability.

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
| Phase 2 | Architecture, tech choices (ADRs), data model | **In progress** |
| Phase 3 | POCs for critical aspects | Not started |
| Phase 4 | Validation strategy, test plan, traceability | Not started |
| Phase 5 | Implementation | Not started |

---

## General Conventions

### Language
- All code, comments, variable names, and documentation must be in **English**.
- Communication with the user is in **French**.

### File Naming
- ADRs: `ADR-NNN-short-title.md` (zero-padded 3-digit number)
- Tasks: `TASK-NNN-short-title.md`
- Sessions: `YYYY-MM-DD-session-NNN.md`
- ConOps: `conops.md` (single living document)

### Git
- Commit message format: English, imperative mood (`Add`, `Fix`, `Update`...)
- Branching strategy: TBD (ADR)

---

## Key Constraints

- **CLI-first**: all functionality exposed as CLI commands, composable in scripts
- **OpenEvolve-based**: solution generation relies on OpenEvolve's evolutionary loop
- **LLM-agnostic**: must support local models and multiple API providers (Anthropic, Google, OpenAI)
- **LLM interface**: all LLMs must expose an OpenAI-compatible API (native or via adapter)
- **Full traceability**: every solution must trace back to problem version, dataset, LLM, and config
- **Reproducibility**: runs must be reproducible given the same config and seed

---

## Open Questions / Decisions Pending

- [x] Primary programming language → **Python >= 3.11** (ADR-002)
- [x] Project/problem versioning strategy → **Internal manifest-based** (DES-003 DD-06)
- [x] Dataset storage format and management → **Reference + optional snapshot** (DES-004)
- [x] Local LLM deployment tool → **Ollama** (ADR-001)
- [x] CLI framework choice → **Typer >= 0.21** (ADR-003)
- [x] OpenEvolve instance injection strategy → **A+B hybrid** (env var + optional SQLite side-channel) (ADR-006)
- [x] Benchmark output format and visualization → **CSV + JSON** (DES-007 DD-03, no Parquet in v1)
