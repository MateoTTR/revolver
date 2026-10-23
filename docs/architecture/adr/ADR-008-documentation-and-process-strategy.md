# ADR-008 — Documentation and Process Strategy

**Date**: 2026-10-23
**Status**: Accepted
**Deciders**: the project maintainer (owner decisions of 2026-10-23, Sprint 019)

---

## Context

Revolver switches from a private to a public repository at v0.19.0 (Sprint 019). Until then it
was developed by one maintainer with a single AI-assisted toolchain, and both the documentation
and the process grew around that situation:

- **Volume.** At v0.18.0 the Markdown under `docs/` weighed ≈ 28.8k lines against ≈ 24.0k lines
  of Python under `src/`. The maintainer's session journal (`docs/sessions/`, 62 files, ≈ 4.9k
  lines) and the sprint files (`docs/sprints/`, ≈ 6.0k lines) together made up ≈ 38 % of it —
  per-session and per-sprint narrative that describes the work, not the product.
- **Redundancy and hand-maintained cross-references.** The same facts (ADR / DES indexes, phase
  status, test counts, release tables, test ids) were repeated across `CLAUDE.md`, `README.md`,
  `architecture.md`, the sprint files, the backlog and the validation documents, and kept in sync
  by hand.
- **Three anti-rot guards as the symptom.** The project had to add a doc command-lint
  (`tests/unit/test_doc_command_lint.py`, #354), freshness stamps
  (`tests/unit/test_doc_freshness.py`, #355) and a reviewer cascade (specification → validation →
  documentation review) to hold the duplicated prose together — treatments for drift rather than
  its removal.
- **Tool-specific process.** The process bible (`CLAUDE.md`, 190 lines) mixed project rules with
  the maintainer's session mechanics: worktree agents, a hook that launched the code reviewer
  after `gh pr create`, "run the reviewers in the foreground", French as the conversation
  language, a session-close ritual writing into `docs/sessions/`. The review checklists existed
  only inside the prompts of five agent definitions under `.claude/agents/`, the traceability
  check inside a skill, the GitHub access inside `.mcp.json`. A contributor without that
  toolchain had no review checklist, no release procedure and no planning procedure to follow;
  the first two external pull requests arrived with no issue, no review and no specification or
  validation edits because nothing in the repository told their authors what was expected.
- **Exposure.** Going public exposes the full history. The pre-publication audit found no
  secrets, but it found local filesystem paths, machine names, private repository names and
  personal timing data in the journal and in several living documents.

The owner principle governing the switch: **"Everything in the GitHub project must be
self-contained and clear for humans and AI agents alike, without assumptions about any
contributor's own development means (with or without AI, Claude Code or other)."**

The as-practiced analysis behind this record — lifecycle, rules catalog, Definition of Done,
gaps for external contributors, ranked recommendations — is committed in sanitized form as
[dev-process-analysis.md](../../analysis/dev-process-analysis.md).

## Decision

### D1 — The maintainer journal lives outside the repository

Session reports and the cumulative time tracker are the maintainer's private working material.
They leave the tree at v0.19.0 (`docs/sessions/` keeps a README pointer only); the journal's
location is configured in a git-ignored local file and is never committed. Contributors are not
expected to keep one: continuity is carried by the GitHub issues, a short **Status** section in
the description of long-running pull requests, `CHANGELOG.md` and the design documents.
Historical "session NNN" references in frozen records are left as they are.

### D2 — Planning is GitHub-native from Sprint 020; the file-based records are frozen

The backlog is the labelled GitHub issue list. A sprint is a **milestone** plus a **planning
issue** whose body carries what a sprint file carried (scope, verified facts, tasks, PR mapping,
waves, conflict map, exit criteria — [sprint-planning.md](../../process/sprint-planning.md)).
The sprint review is the `CHANGELOG.md` release section plus the planning issue's closing
comment. `docs/tasks/backlog.md` and `docs/sprints/*` stay in the repository as **frozen
records** of Sprints 001–019 (freeze banners, nothing moved or renumbered) and are not updated
afterwards.

### D3 — Three documentation tiers

| Tier | Documents | Rule |
|---|---|---|
| **Living / authoritative** | `AGENTS.md`, `README.md`, `CHANGELOG.md`, `docs/architecture/architecture.md`, the ADRs, the DES documents, `docs/guides/`, `docs/process/` | Kept current with every change; the source of truth for what the product and the process are. A fact lives in one of them and is linked from the others. |
| **Requirements & verification** | `docs/specs/` (FR / NFR with stable ids), `docs/validation/` (strategy, L2 matrix, E2E scenarios, traceability matrix) | Normative; updated before or with the code (spec-before-code cascade). To be **slimmed in a later step**: traceability generated from test markers carrying FR ids, the hand-maintained per-test rows dropped (Consequences, follow-ups). |
| **Frozen history** | `docs/tasks/backlog.md`, `docs/sprints/*`, past analyses in `docs/analysis/` | Records. Never edited except for public-file-rule cleanups; never cited as current state. |

### D4 — Framework-agnostic process: `AGENTS.md` canonical, `docs/process/` checklists, one-line tool pointers

`AGENTS.md` is the single entry file for humans and agents: overview, documentation index, key
constraints, conventions, planning model, pull-request workflow, pointers to the procedures. The
procedures themselves — code, specification, validation and documentation review, sprint
planning, release and hotfix, Definition of Done — are tool-neutral checklists under
`docs/process/`, each executable by a human with a terminal and a browser (inputs, steps,
severity vocabulary, output format, where to post). Tool-specific entry files (`CLAUDE.md`,
`GEMINI.md`) are one-line pointers to `AGENTS.md`; no tool name is a requirement anywhere in the
process. The former agent prompts were extracted into these checklists before the tool folders
left git, and every dropped or reworded rule is marked in the checklist that absorbed it.

### D5 — Tooling is private per contributor and not versioned; knowledge lives in neutral documents

Agent definitions, hooks, skills, MCP configurations and similar automation are each
contributor's own means. They are not versioned (`.claude/` and `.mcp.json` are removed from
the index and git-ignored; the maintainer keeps local copies). Whatever project knowledge they
held lives in `docs/process/` and `AGENTS.md`. A contributor may automate any checklist with any
tool, as long as the result is the checklist's output posted where the checklist says.

### D6 — Public-file rule

No committed file, issue, pull request or review may contain a local filesystem path, a machine
or runner hostname, a private repository name, an e-mail address, personal timing data, GitHub
handles of third parties, or business-domain vocabulary. Neutral wording replaces them. The
concrete audit list stays outside the repository.

### D7 — `CHANGELOG.md` is the release-note vehicle

Keep a Changelog format, one section per tag, seeded back to v0.1.0. Each pull request adds its
line under `[Unreleased]`; the release moves the block under a dated version heading and updates
the compare links ([release.md](../../process/release.md)). Default-path changes are flagged
**Behavior change**. The README points to it instead of carrying a release table.

### D8 — No git-history rewrite

Files removed from the tree (the journal, cleaned lines) remain reachable in the history once the
repository is public. This exposure is accepted: the audit found no secrets, and a rewrite would
invalidate every pull-request, issue and sprint reference the records rely on.

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| **Keep everything as is** (journal, sprint files, `CLAUDE.md` as process bible, `.claude/` in git) and only clean the content | No restructuring effort | The process stays executable by one toolchain only; the journal and planning narrative keep growing in the public tree; the anti-rot guards keep compensating for duplication; personal data keeps leaking into living documents |
| **New public repository from a filtered clone** | Guarantees that removed files never appear in the public history | Breaks every pull-request, issue and commit reference used by the backlog, the sprint records and the CHANGELOG; loses the review history that is part of the project's value; the residual exposure of the existing repository is a commit reachable only by SHA |
| **Keep `.claude/` in git as shared, optional tooling** | Contributors with the same tool get the automation for free | Makes one vendor's format the de-facto process definition; the checklists would stay buried in prompts; every other tool's users remain second-class; tooling churn lands in the project history |
| **One complete instruction file per tool** (`CLAUDE.md`, `GEMINI.md`, … all full) | Each tool finds its native file | N copies of the same rules to keep in sync — the duplication problem again |
| **Planning stays file-based** (`docs/sprints/`, `docs/tasks/backlog.md`) in the public repository | Familiar; one place for history and plan | Global task counter and session numbers do not compose across parallel contributors; every PR touches the same two files; the records keep swelling the tree; GitHub already provides issues, labels and milestones with cross-references |

## Consequences

### Positive

- A contributor with no AI tooling can run the pull-request workflow, a code review, a sprint
  planning and a release from `AGENTS.md` and `docs/process/` alone; agents of any kind read the
  same files.
- The repository tree shrinks by the journal and stops growing with per-session narrative; the
  planning records stop duplicating GitHub.
- Every process fact has one home (`AGENTS.md` or one checklist) and is linked, not copied.
- Personal data and tool-specific mechanics are kept out of the public record by rule (D5, D6).
- Release notes are a first-class artifact (`CHANGELOG.md`) instead of a README table plus tag
  messages.

### Negative

- The maintainer loses the in-tree journal and the in-tree sprint files as a working surface;
  continuity moves to GitHub issues and a private journal.
- Two documents (`AGENTS.md` and `docs/process/`) can still drift from each other;
  `AGENTS.md` links to the procedures instead of restating them, and the validation review's
  entry-file check guards the indexes.
- The step-2 shrink (generated traceability, slimmer L2 matrix) is deferred: until it lands the
  requirements-and-verification tier remains hand-maintained.
- Removed files stay visible in the history (D8).

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Knowledge lost when the tool folders leave git (an agent rule not carried into `docs/process/`) | Medium | Checklists written first, folders removed last; each checklist lists every dropped or reworded rule |
| Checklists rot once nobody runs them by hand | Medium | They are the release gate (step 0 of `release.md`) and the review gate of every pull request; the pull-request template mirrors the Definition of Done |
| The planning issue becomes a wall of text nobody updates | Low | Progress lives on the per-PR issues and the PR Status sections; the planning issue is updated at merges and closed at release |
| External contributors skip the specification cascade | Medium | Issue-first rule with the RFC-lite design issue; the maintainer owns the formal documents |

### Follow-ups (documentation shrink, step 2)

Recorded as backlog rows 381–383 and #357 before the freeze, to be migrated to GitHub issues;
they become an amendment of this ADR once a concrete mechanism is chosen:

- **Generated traceability** (row 381): pytest markers carrying FR ids and a generator producing
  the FR → test mapping, replacing the hand-maintained test-id columns of
  `traceability-matrix.md`; CI fails on an FR `MUST` without a test.
- **Shrink the L2 test matrix** (row 382): once the mapping is generated, keep the strategy,
  fixtures and conventions of `val-integration-tests.md` and drop the per-test rows.
- **Diátaxis reorganisation of the guides** (row 383): tutorial = tested, how-to = tested,
  reference = generated, explanation = reviewed; keeps the `verified-against` stamps.
- **Executable E2E walkthrough and generated CLI reference** (#357): replay the fenced command
  blocks of `user-story-e2e.md` against the fake LLM server; generate the flag reference from
  the CLI tree so that guides link to it instead of hand-maintaining flag tables.

## References

- [dev-process-analysis.md](../../analysis/dev-process-analysis.md) — the as-practiced process analysis at v0.18.0 (lifecycle, rules catalog, Definition of Done, gaps, recommendations)
- [AGENTS.md](../../../AGENTS.md) — the canonical entry file (D4)
- [docs/process/README.md](../../process/README.md) — the checklists and the public-file rule (D4, D6)
- [docs/sessions/README.md](../../sessions/README.md), [docs/sprints/README.md](../../sprints/README.md) — the journal pointer and the sprint-records freeze banner (D1, D2)
- [CHANGELOG.md](../../../CHANGELOG.md) — the release-note vehicle (D7)
- [ADR-007](ADR-007-pluggable-evolution-backend.md) — the amendment style this ADR follows and the source of the backend Definition of Done
- Sprint 019 record (`docs/sprints/sprint-019.md`) — the owner decisions, the verified facts and the task breakdown that implemented this ADR
