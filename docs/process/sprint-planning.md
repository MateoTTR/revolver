# Sprint planning procedure

From Sprint 020 on, planning is GitHub-native (ADR-008 D2): the backlog is the
labelled issue list, a sprint is a **milestone** plus a **planning issue**, and
the sprint review is the release entry in `CHANGELOG.md` plus the closing
comment of the planning issue. `docs/tasks/backlog.md` and `docs/sprints/*`
are frozen records of Sprints 001–019 and are no longer updated.

Use this procedure at sprint boundaries: to plan a sprint, to review it, and
to groom the backlog between sprints.

## Inputs

- The specifications (`docs/specs/spec-*.md`, `docs/specs/specifications.md`) for the FR scope.
- `docs/validation/val-integration-tests.md` (which L2 scenarios validate each command) and `docs/validation/traceability-matrix.md`.
- `docs/architecture/architecture.md`, the ADRs and the DES documents for dependencies.
- The open issues (the backlog) and the previous sprint's planning issue — its closing comment carries the carry-over.
- The `[Unreleased]` section of `CHANGELOG.md` (what already landed since the last release).

## Scoping principles

Sprints are scoped by **functional increment**, not by time. Each sprint
delivers a **vertically integrated slice** that is independently testable
and demo-able: CLI layer (Typer commands) → domain layer (`revolver.core`) →
infrastructure layer (SQLite stores, file operations, external calls) →
tests (L1 unit + L2 integration for the delivered commands).

Ordering guidelines:

1. **Foundation first** — infrastructure that other features depend on (DB schema, project structure, Pydantic models) comes early.
2. **Dependencies respected** — a sprint's inputs are delivered by a previous sprint or inside the same sprint.
3. **Incremental value** — each sprint adds user-visible functionality that can be demonstrated.
4. **Test coverage grows monotonically** — each sprint adds passing integration tests and never breaks existing ones.

Command-group dependency order for product work:

```
project (foundation — DB, project structure)
    ↓
llm, problem, dataset (each needed by run)
    ↓
run (orchestrates the evolution backend — needs llm + problem + dataset)
    ↓
solution, eval (read run output)
    ↓
benchmark (compares across runs)
```

`setup` and `doctor` are cross-cutting and fit any sprint.

Constraints: each sprint is independently testable and never leaves the
project in a broken state; tasks are sized for roughly one working session
(a guideline, not a rule); every task references specific FR ids and L2
scenarios from the existing documentation; no new requirement is invented —
work from the specs; infrastructure and cross-cutting concerns belong to the
earliest sprint that needs them.

## Steps — planning a sprint

1. **Read** the specs, the validation documents, the architecture and DES files and the open issues; identify the candidate functional increment and the carry-over from the previous planning issue.
2. **Verify facts in the code** before writing the plan (file-level reconnaissance, cited as `path::symbol`), and record them in the planning issue so that nobody re-derives them.
3. **Create the milestone** `Sprint NNN — <functional scope>` with the target version `vX.Y.0` in its description.
4. **Open the planning issue** from the sprint-planning issue template added by the contributor-process pull request (or with the outline below); assign it to the milestone; label it `sprint-planning`.
5. **Create or link one issue per pull request** (feature, bug or new-backend template as fits); each carries scope, files, acceptance criteria, test scenarios and spec / DES / ADR references, belongs to the milestone and is linked from the planning issue's task table.
6. **Analyze parallelization** (below); record the waves, the critical path, the streams and the conflict map in the planning issue.
7. **Spec-before-code cascade** — when the sprint changes behavior, update the specs / DES / ADR / validation rows first (test ids declared `Planned`), review them with [spec-review.md](spec-review.md) and [validation-review.md](validation-review.md), and commit on `develop` before the implementation pull requests start.

### Planning issue outline

What a sprint file used to carry, as the body of the planning issue:

```markdown
# Sprint NNN — <functional scope title>

**Status**: Planning | In Progress | Review | Done
**Target release**: vX.Y.0
**Goal**: <1–2 sentences — what this sprint delivers>
**Demo**: <what can be demonstrated at sprint end>
**Source**: <owner decisions, analyses, carry-over from Sprint NNN-1 (link its planning issue)>

## Scope
### In scope — stories / pull requests
| Story | Issue | PR | Content |
### Decided (not open)
### Explicitly out of scope — deferred item, target, rationale

## Verified facts driving the plan (checked in the code — do not re-derive)
1. …

## Tasks
| # | Task | Layer (infra / domain / cli / test / doc / ci / ops) | Issue | PR | Depends | Acceptance criteria |

## Integration tests (L2)
| Area | Scenario | Test ID | Status (Planned / Implemented / Passing) |

## PR mapping
| PR | Issue | Tasks | Files (primary) | Wave |

## Parallelization
### Dependency graph (ASCII)
### Waves — wave, content, gate to open
### Critical path
### Parallel work streams — stream, tasks, can start after, assignment
### Conflict map — file or area, touched by, resolution (merge order)

## Exit criteria
1. …

## Risks
| Risk | Severity | Mitigation |

## Release note
<the CHANGELOG lines this sprint must produce; default-path changes flagged "Behavior change">
```

### Parallelization analysis

Principles: independent layers run in parallel (two tasks touching different
modules with no shared state); two CLI commands of the same sprint can be
implemented in parallel when they share no domain logic; within a dependency
chain infra → domain → CLI is sequential, across chains it is parallel; a test
task is sequential with its implementation and parallel with other test tasks.

For each sprint identify: the **critical path** (longest sequential chain);
the **parallel streams** (task groups independent once their shared
prerequisites are met); the **merge points** where streams converge and
integration testing is needed; the **degree of parallelism** (how many
contributors can work concurrently at peak); the **conflict risks** (tasks
touching shared files such as the DB schema or shared models, where
concurrent edits would cause merge conflicts) and the resulting
**merge order**.

Dependency-graph example:

```
S1-01 (infra: DB schema) ──┬──> S1-02 (domain: project service) → S1-04 (cli) → S1-07 (test)
                            └──> S1-03 (domain: llm service)     → S1-05 (cli) → S1-08 (test)   ← parallel with S1-02
```

## Steps — during the sprint

- Progress lives on the issues and pull requests (task checkboxes, the pull request's **Status** section updated at each working session); the planning issue's task table is updated at each merge.
- Every pull request adds its line under `[Unreleased]` in `CHANGELOG.md`.
- Scope changes are recorded as a comment on the planning issue, never silently.

## Steps — sprint review

1. Check the sprint's expected L2 scenarios against the test files and the CI result; count passing versus planned.
2. Walk the exit criteria; list the demo-able features and the carry-over.
3. **Release** per [release.md](release.md). The `CHANGELOG.md` section for the version **is** the record of what shipped.
4. Post the **closing comment** on the planning issue: tests passing versus planned (counts, coverage, review tallies — CRITICAL / WARNING findings addressed), demo-able features checklist, carry-over items (each turned into, or linked to, an issue for the next sprint), deviations from the plan. Close the planning issue and the milestone.

## Steps — backlog grooming (between sprints)

1. Review the open issues: completed, in progress, blocked; a merged pull request closes its issue through `Closes #N`.
2. Re-prioritize with labels (type / area / priority / backend) and milestones; split or merge issues whose scope moved.
3. Record decisions on the issues themselves.

## Output and where to post

Planning produces the milestone and the planning issue (body and task table);
the review produces the closing comment and the CHANGELOG section. Everything
is posted on GitHub; nothing is written under `docs/sprints/` or `docs/tasks/`
any more.

## Changes from the former agent definition

- **(changed)** The former scrum-master agent wrote `docs/sprints/sprint-NNN.md` and updated `docs/tasks/backlog.md`; both are frozen (ADR-008 D2). Its sprint-file format becomes the planning-issue outline above, extended with the sections the later sprint files had grown (Verified facts, PR mapping, Waves, Conflict map, Exit criteria, Risks, Release note — the Sprint 018/019 shape).
- **(changed)** "Agent assignment" in the work-stream table becomes "assignment" (a contributor or an agent, indifferently).
- **(changed)** The sprint-review section of the sprint file becomes the CHANGELOG entry plus the planning issue's closing comment.
- **(changed)** The French communication rule is dropped (English only).
- **(dropped)** The former sprint-file sections "Command groups included" and "Key FRs covered" have no counterpart in the planning-issue outline: the milestone's issue list (labels) and each pull request's Spec-impact section carry that information.
- **(added)** Step 7 (spec-before-code cascade) and the "during the sprint" rules (one CHANGELOG line per pull request, the Status section) restate practice from Sprints 017–019 that was not in the agent prompt.
