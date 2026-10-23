# Sprint 019 — Public Release (v0.19.0)

**Status**: In Progress (S19-01 shipped; PR-A next)
**Target release**: **v0.19.0** (normal sprint release; `develop` → `main`, tag `v0.19.0`)
**Goal**: Make the repository fit to switch from private to public and self-contained for any contributor: move the maintainer session journal out of the tree, introduce `CHANGELOG.md` as the release-note vehicle, freeze the file-based planning records, clean the remaining pre-publication hygiene items, make the process framework-agnostic (canonical `AGENTS.md`, tool-neutral checklists under `docs/process/`, ADR-008, tool folders out of git), publish the contributor process (CONTRIBUTING, templates, CODEOWNERS, SECURITY, Dependabot), harden CI for required checks, release v0.19.0, then flip the visibility and lock the repository down.
**Demo**: after the flip, an anonymous user clones the public repository, installs `v0.19.0` from the GitHub URL and gets `revolver --version` → `0.19.0`; `CHANGELOG.md` lists every release from v0.1.0 to v0.19.0; `AGENTS.md` is the single entry file, with `CLAUDE.md` and `GEMINI.md` reduced to one-line pointers; a human with no AI tooling performs a code review and a release from `docs/process/*.md` + `CONTRIBUTING.md` alone; `.claude/` and `.mcp.json` are not in git; opening an issue offers the feature / new-backend / bug / sprint-planning templates; a fork PR waits for maintainer approval, then runs the four required checks and cannot be merged until they pass; secret scanning, push protection, Dependabot and private vulnerability reporting are on.
**Source**: Owner decisions of 2026-10-23 (public switch; journal relocation; documentation strategy step 1; planning GitHub-native from Sprint 020; framework-agnostic process with private tooling; PR-A scope per GH #275; PR-D separate; rulesets bypass for the admin; no history rewrite; LoongFlow re-targeted to Sprint 020). The development-process analysis (§4 gaps, §4.6 ranked recommendations, §5 drafts — disposition in S19-28). The pre-publication audit list (kept outside the repository). GitHub issues #272 (done), #275, #276, #277 (C1), #279, #278.
**Predecessor**: Sprint 018 (v0.18.0 — eval honesty semantic slice + top-N flagship).

> **Owner principle (governs every deliverable of this sprint).** "Everything in the GitHub project must be self-contained and clear for humans and AI agents alike, without assumptions about any contributor's own development means (with or without AI, Claude Code or other)."

> **Public-file rule (applies to every deliverable of this sprint, including this file).** No local filesystem paths, machine or runner hostnames, private repository names, e-mail addresses, personal timing data or business-domain words in any committed file. Use neutral wording ("a local path", "a network Ollama host", "a separate demo repository", "a third-party endpoint shim"). The concrete hit list lives in the maintainer-side audit list (kept outside the repository) and is never copied into the repo.

> **Last file-based sprint.** From Sprint 020 on, planning is GitHub-native: backlog = labelled GitHub issues; a sprint = a milestone + a planning issue whose body carries what a sprint file carries today (scope, waves, conflict map, exit criteria); the sprint review = the CHANGELOG entry + the planning issue's closing comment. `docs/tasks/backlog.md` and `docs/sprints/*` stay in the repository as frozen project records (freeze banners added by PR-A); no file is moved or renumbered.

> **No product change this sprint.** Nothing under `src/revolver/` changes behavior; the only source edits are two comment renames (S19-11). Full-suite regression must stay green at the S18 baseline (1585 passed / 4 skipped, no-shinka env).

---

## Scope

### In scope

| Story | GitHub issue | PR | Content |
|---|---|---|---|
| **CI on GitHub-hosted runners + LICENSE** | #272 | #274 (merged 2026-10-23) | `ci.yml` / `doc-lint.yml` on `ubuntu-latest` (`actions/setup-python` v6, `permissions: contents: read`, `REVOLVER_HOME` via `GITHUB_ENV`), `.github/runner/` removed, MIT `LICENSE` (copyright: the maintainer). **Done.** |
| **Documentation restructuring, step 1** | #275 | PR-A | Journal removal + `docs/sessions/README.md`; `CHANGELOG.md` seeded v0.1.0…v0.18.0 + `Unreleased`; freeze banners (top note in `backlog.md`, new `docs/sprints/README.md`); minimal CLAUDE.md edits (index rows, session checklist via `CLAUDE.local.md`, generic phase line, release checklist CHANGELOG step + GitHub install URL); `.gitignore` `CLAUDE.local.md`; README release table → CHANGELOG pointer; session-close skill aligned with the private journal. |
| **Pre-publication content cleanup** | #276 | PR-B | Mechanical, docs-mostly, driven by the maintainer-side audit list: local paths, hostnames, pointers to private sibling repositories, remaining off-topic paragraphs, editorial markers, third-party endpoint shim wording, a hostname in two source comments. **Does not touch CLAUDE.md or `.claude/`.** Plus the GitHub-side worklist executed by the maintainer on switch day (task, not PR). |
| **Framework-agnostic process** | #277 (re-scoped) | PR-C1 | `AGENTS.md` canonical and tool-neutral (rewrite of the CLAUDE.md content without tool-specific mechanics); `CLAUDE.md` + `GEMINI.md` one-line pointers; knowledge of the five agent definitions + release/hotfix procedures extracted into `docs/process/*.md`; ADR-008 "Documentation and process strategy"; `.claude/` and `.mcp.json` removed from git (kept locally, gitignored); §4.5 drift resolved in the rewrite; disposition of the dev-process analysis. |
| **Contributor process** | #279 | PR-C2 | `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/` (feature, new-backend, bug, sprint-planning), `.github/CODEOWNERS`, `SECURITY.md`, `.github/dependabot.yml`, index lines in README/AGENTS.md, doc-lint corpus adjustment. Depends on C1. |
| **Workflow hardening** | refs #278 | PR-D | Drop the path filters, fold the doc-lint job into `ci.yml`, SHA-pin the actions; required-check names unchanged. |
| **Release v0.19.0** | — | release commits | Release procedure (`docs/process/release.md` from C1): bump both version files, CHANGELOG `Unreleased` → `0.19.0`, README refresh, `verified-against: v0.19.0` stamps, `develop` → `main`, tag, install check from the GitHub URL, post-release doc review. |
| **Switch to public + settings** | #278 | operations (no PR) | Pre-flip gate, visibility flip, rulesets (admin bypass "always"), security features, Actions policy, repository settings, collaborators, GitHub-native planning bootstrap for Sprint 020, optional GitHub Releases. |

### Decided (not open)

| Decision | Content |
|---|---|
| **No git history rewrite** | Files removed from the tree (journal, cleaned lines) stay reachable in history once public. Accepted by the owner: the audit found no secrets. |
| **Rulesets bypass** | Repository admin bypass mode **"always"**, so planning/doc commits directly on `develop` and the local `develop` → `main` release merge keep working. |
| **PR-D separate** | Small workflow-only PR referencing #278, independent of PR-A/B/C1/C2. |
| **Planning GitHub-native from Sprint 020** | See the header box. Sprint 019 is the last file-based sprint. |
| **Tooling private per contributor** | Agent definitions, hooks, skills, MCP config stay out of git; their *knowledge* lives in `docs/process/` and `AGENTS.md`. |

### Explicitly out of scope

| Deferred item | Target | Rationale |
|---|---|---|
| **LoongFlow backend** (external draft PRs #270/#271, catch-up issue #273) | **Sprint 020 / v0.20.0** | First external backend contribution; it needs C1/C2 and PR-D in place, and goes through the backend checklist of `docs/process/code-review.md` / CONTRIBUTING. Issue #273 is retitled by the orchestrator. |
| **Documentation shrink, step 2** — generated traceability from pytest markers carrying FR ids; shrink of the L2 test matrix; Diátaxis reorganisation of the guides | Backlog rows 381–383 (unscheduled, S20+), tied to #357 | Step 1 is structural; step 2 changes how validation docs are produced and is recorded as an ADR-008 follow-up. |
| **#357** executable e2e + generated CLI reference | Unscheduled (S20+) | Displaced by the public-release sprint; grouped with the step-2 rows. |
| **Other S18 carry-overs** — OE top-N (post-#367), L3 E2E Scenario 5, live Shinka smoke through an OpenAI-compatible local endpoint, the "post-extraction training evaluation" doc drift | S20+ | Product work; no product change this sprint. |
| **Remaining dev-process recommendations** — generic backend conformance test (§4.6 rank 6), adding-a-backend guide (rank 7), optional engine CI job (rank 9) | Sprint 020 candidates (LoongFlow) | Useful for the first external backend; scoped in the Sprint 020 planning issue. |

---

## Verified facts driving the plan (checked on `develop` — do not re-derive)

1. **Doc guard corpora.** `tests/unit/test_doc_command_lint.py` lints `README.md` + every `docs/**/*.md`; root-level files (`CHANGELOG.md`, `CONTRIBUTING.md`, `AGENTS.md`, `GEMINI.md`) are **not** linted today. `tests/unit/test_doc_freshness.py` scans `docs/guides/*.md` + `docs/specs/user-story-e2e.md`. New `docs/process/*.md`, `docs/sprints/README.md` and `docs/sessions/README.md` fall into the lint corpus automatically, not into the freshness corpus. No test, workflow or source file reads `docs/sessions/` or `.claude/`.
2. **References to the journal** outside `docs/sessions/`: `CLAUDE.md` (index rows, checklist steps 5–6, release checklist step 7), `.claude/skills/session-close/SKILL.md`, historical "session NNN" mentions in the backlog and sprint files (stay as-is). The only markdown links into `docs/sessions/` are the 4 in `CLAUDE.md`.
3. **CLAUDE.md drift.** Phase 5 line reads "Sprint 009 complete (v0.9.0 released)"; Release Checklist step 6 installs from a local `git+file://` path. The guides table already points to `docs/guides/tuning-evolution.md`.
4. **Tracked tool files**: `.claude/agents/{code-reviewer,spec-reviewer,validation-reviewer,doc-reviewer,scrum-master}/agent.md`, `.claude/skills/{session-close,traceability-check}/SKILL.md`, `.claude/settings.json` (review hook), `.claude/scripts/`, and the root `.mcp.json`. `.claude/worktrees/` is already gitignored.
5. **`tests/unit/test_doc_freshness.py` names "CLAUDE.md Release Checklist step 1b"** in its failure message — must follow the release procedure to `docs/process/release.md` in C1.
6. **There is no `CHANGELOG.md`.** Release notes have so far landed in the README (release table + "Behavior changes (v0.18)") and the annotated tag message.
7. **Required-check names** (exact): `Lint (ruff + mypy)`, `Test (pytest + coverage) (3.12)`, `Test (pytest + coverage) (3.14)` (`ci.yml`), `Doc command-lint (fenced CLI invocations)` (`doc-lint.yml`). `ci.yml` has `paths-ignore: ['**.md', 'docs/**']` and `doc-lint.yml` the complementary `paths:` filter → every PR leaves at least one required check un-triggered ("Expected — waiting for status" forever). A job *skipped* by `if:` satisfies a required check; a never-triggered workflow does not.
8. **Actions are tag-pinned** (`actions/checkout@v5`, `actions/setup-python@v6`), not SHA-pinned.
9. **`pyproject.toml` has no `--strict-markers`**, while `docs/validation/validation.md` §4/§6.2 documents `addopts = "--strict-markers -v"`, ruff `py311`/`line-length 100` and an `e2e_gpu` marker absent from pyproject.
10. **ADR numbering**: ADR-001…007 exist; **ADR-008** is the next free number (#357 had pencilled in an ADR-008 for documentation maintenance — it becomes a follow-up amendment of this ADR-008).
11. **Backlog vs GitHub numbering.** Backlog task numbers and GitHub issue/PR numbers share the same range (backlog rows 272–278 are Sprint 013 tasks). "GH #N" means GitHub; bare numbers in the Backlog column mean backlog rows.

---

## Tasks

### Shipped — CI + LICENSE (GH #272)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-01 | **CI moved to GitHub-hosted runners + MIT LICENSE.** `ci.yml` and `doc-lint.yml` on `ubuntu-latest`, `actions/setup-python` v6, `permissions: contents: read`, `REVOLVER_HOME` via `GITHUB_ENV`; `.github/runner/` removed; `LICENSE` (MIT, copyright: the maintainer). | ci | 372 | #274 | — | [x] | Merged 2026-10-23; Lint + Test 3.12/3.14 + doc-lint green on GitHub-hosted runners |

### PR-A — Documentation restructuring, step 1 (GH #275)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-02 | **Journal out of the tree.** Remove `docs/sessions/*` (62 files, incl. `cost-tracker.md`); add `docs/sessions/README.md` (the session journal is a private maintainer journal kept outside the repository; sprint files and the backlog remain the public planning record; historical "session NNN" references are intentionally left as-is). **Precondition (maintainer action):** export to the private journal first. | doc | 373 | PR-A | maintainer export confirmed | [ ] | `docs/sessions/` contains only `README.md`; the PR description states the export was done; no link into a removed file (fact 2) |
| S19-03 | **`CHANGELOG.md`** (Keep a Changelog): `## [Unreleased]` + one section per existing tag v0.1.0 … v0.18.0 (incl. corrective `a/b/c` releases and the v0.12.1 hotfix), seeded from the README release table and the sprint-review sections; Added / Changed / Fixed / Removed where the source allows; v0.18.0 carries the six "Behavior changes" items (moved from the README); comparison links. No fenced `revolver …` blocks (historical flags). | doc | 373 | PR-A | — | [ ] | Every `v*` tag has exactly one section; `Unreleased` present; no public-file-rule hit |
| S19-04 | **Freeze banners.** Top note in `docs/tasks/backlog.md`: "Frozen at the end of Sprint 019 / v0.19.0 — from Sprint 020 the backlog is tracked as GitHub issues (labels); this file is a project record". New `docs/sprints/README.md`: sprint files 001…019 are frozen records; from Sprint 020 a sprint = milestone + planning issue; review = CHANGELOG entry + planning issue closing comment. No file moved or renumbered. | doc | 373 | PR-A | — | [ ] | Both banners present; `git diff --stat` shows no rename under `docs/sprints/` or `docs/tasks/` |
| S19-05 | **CLAUDE.md — minimal edits.** Index: "Session reports" / "Session cost tracker" rows → one "Session journal" note (private, location in `CLAUDE.local.md`); rows for `CHANGELOG.md` and `docs/sprints/README.md`. Session Checklist steps 5–6 → journal via `CLAUDE.local.md` if configured; contributors write no session reports; long-running PRs keep a "Status" section in the PR description. Phase 5 line → generic. Release Checklist: step 1b gains "move CHANGELOG `Unreleased` → `X.Y.Z`"; step 6 install URL → `git+https://github.com/<owner>/revolver@vX.Y.Z`; step 7 session-report / cost-tracker checks → "CHANGELOG section present" (+ maintainer journal entry). Nothing else (the full rewrite is C1). | doc | 373 | PR-A | S19-03, S19-04 | [ ] | No link into a removed file; no local path; doc-lint green |
| S19-06 | **`.gitignore`**: add `CLAUDE.local.md`. | config | 373 | PR-A | — | [ ] | `git check-ignore CLAUDE.local.md` succeeds |
| S19-07 | **README**: release/sprint table → pointer to `CHANGELOG.md` (optional short "recent releases" table); "Behavior changes (v0.18)" → one-line pointer to the CHANGELOG v0.18.0 section. | doc | 373 | PR-A | S19-03 | [ ] | Links resolve; fenced invocations unchanged; doc-lint green |
| S19-08 | **Session-close skill alignment** (`.claude/skills/session-close/SKILL.md`): write a date-based entry to the journal location configured in `CLAUDE.local.md` (no global counter, no repo cost-tracker); without a configured journal, only the backlog update. Closes the window where the skill would still write into `docs/sessions/`. (The file leaves git in C1; the aligned version is what the maintainer keeps locally.) | doc | 373 | PR-A | S19-05 | [ ] | Skill no longer writes into `docs/sessions/`; consistent with S19-05 |
| S19-09 | **Doc guards + regression.** Run both doc-guard modules, then the full suite. | test | 373 | PR-A | S19-02..08 | [ ] | Doc guards green; full suite at the S18 baseline; CI green |

### PR-B — Pre-publication content cleanup (GH #276)

Scope rule: PR-B **does not touch `CLAUDE.md`** (A then C1 own it) **nor `.claude/`** (leaves git in C1). Audit hits in those files are handled by A (install URL) or absorbed by the C1 rewrite; C1 applies the public-file rule to everything it writes.

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-10 | **Local paths → neutral** in every committed file still carrying one after PR-A (living docs, retained planning records: sprint files, backlog, analysis docs), per the audit list. Repo-relative paths or placeholders; `~/.revolver` stays (product default). | doc | 374 | PR-B | PR-A merged | [ ] | Audit command for local paths returns nothing beyond known test dummies (outside CLAUDE.md / `.claude/`) |
| S19-11 | **Hostnames → neutral** in docs and in the two source comments flagged by the audit list (comment-only). | doc / src (comments) | 374 | PR-B | PR-A merged | [ ] | Audit command for hostnames returns nothing; ruff/mypy clean; full suite green |
| S19-12 | **Pointers to private sibling repositories → neutral wording**, technical content kept. | doc | 374 | PR-B | PR-A merged | [ ] | No private repository name remains |
| S19-13 | **Off-topic paragraphs.** The two flagged paragraphs sat in files removed by PR-A — verify nothing survives elsewhere; remove any residue. | doc | 374 | PR-B | PR-A merged | [ ] | Verification recorded in the PR description in generic terms |
| S19-14 | **Editorial markers + third-party endpoint shim wording** neutralized in living docs (an OpenAI/Ollama-compatible local endpoint — not whose or which subscription); historical rows only where the audit list flags them. | doc | 374 | PR-B | PR-A merged | [ ] | Living docs describe the shim generically; doc-lint green |
| S19-15 | **Re-run the audit commands** on the PR branch; generic result summary in the PR description. | test | 374 | PR-B | S19-10..14 | [ ] | Nothing beyond known test dummies |
| S19-16 | **GitHub-side worklist** (no PR): issue / PR body and comment edits from the audit list, by the maintainer on switch day, before S19-44. | ops | 375 | — | S19-15 | [ ] | Every worklist item ticked in the maintainer-side list |

### PR-C1 — Framework-agnostic process (GH #277, re-scoped)

Internal order: extract the knowledge first (S19-17..25), remove the tool folders last (S19-26), so no knowledge is lost between commits.

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-17 | **`AGENTS.md` canonical entry file.** Rewrite the CLAUDE.md content tool-neutrally: project overview, documentation index (incl. `docs/process/`, CHANGELOG, frozen records), conventions, Git Flow, quality gates, key constraints, irreversible-action rule, planning model (GitHub-native from Sprint 020), the private-journal / `CLAUDE.local.md`-style local-overlay pattern ("tooling and journals stay private per contributor"). No worktree agents, hooks, foreground reviewers, tool names as requirements, or French-language rules. Quotes the owner principle. | doc | 384 | PR-C1 | PR-A merged | [ ] | A reader with no AI tool can follow every instruction; no tool-specific mechanics; public-file rule clean |
| S19-18 | **`CLAUDE.md` and `GEMINI.md` → one-line pointers** to `AGENTS.md`. | doc | 385 | PR-C1 | S19-17 | [ ] | Each file is a single pointer line (plus title at most) |
| S19-19 | **`docs/process/code-review.md`** — checklist extracted from the code-reviewer agent (functionality, layers `cli → core → infra`, exceptions/exit codes, parameterized SQL, ADR-001…008 compliance, docstrings/markers, secrets), severity scale CRITICAL / WARNING / SUGGESTION / GOOD and the "0 CRITICAL before ready" rule, backend sub-checklist (DoD §3b). | doc | 386 | PR-C1 | — | [ ] | Applicable by a human with only the diff and the repo; the ADR-range drift item is moot (ADR list maintained here) |
| S19-20 | **`docs/process/spec-review.md`** — from the spec-reviewer agent (FR/NFR numbering, Commands / FR / Error Cases triad, ADR amendment style, DES headers, cross-reference validity). | doc | 386 | PR-C1 | — | [ ] | Used for the ADR-008 review (S19-25) |
| S19-21 | **`docs/process/validation-review.md`** — from the validation-reviewer agent and the traceability-check skill (FR MUST ≥ 1 test, test IDs in validation docs, traceability rows, DES references resolve). | doc | 386 | PR-C1 | — | [ ] | Covers the traceability-check content |
| S19-22 | **`docs/process/doc-review.md`** — from the doc-reviewer agent (README/guides/user-story vs CLI, version mentions, freshness stamps, command-lint, triggers: release, doc changes, `src/revolver/cli/*.py` changes). | doc | 386 | PR-C1 | — | [ ] | Used for the post-release doc review (S19-42) |
| S19-23 | **`docs/process/sprint-planning.md`** — from the scrum-master agent, re-targeted to GitHub-native planning: milestone + planning issue body (scope, verified facts, tasks, PR mapping, waves, conflict map, exit criteria), labels, review = CHANGELOG entry + closing comment. | doc | 386 | PR-C1 | — | [ ] | A Sprint 020 planning issue can be written from it alone |
| S19-24 | **`docs/process/release.md`** (+ hotfix section or `hotfix.md`) — the Release Checklist and Hotfix Process moved out of CLAUDE.md, tool-neutral (CHANGELOG step, both version files, stamps, `develop` → `main`, annotated tag, GitHub install URL, post-release checks, post-release doc review). Repoint `tests/unit/test_doc_freshness.py`'s failure message (fact 5) and any doc mentioning "CLAUDE.md Release Checklist". | doc / test | 386 | PR-C1 | — | [ ] | `grep -rn "CLAUDE.md Release Checklist"` empty outside frozen records; freshness test green |
| S19-25 | **ADR-008 "Documentation and process strategy"** (template: Context / Decision / Alternatives / Consequences / References): journal out of the repo; planning GitHub-native; three documentation tiers (living/authoritative, requirements & verification, frozen history); tooling private per contributor; the self-contained principle (quoted); follow-ups = step-2 rows 381–383 / #357. ADR index rows in `AGENTS.md` and `docs/architecture/architecture.md` §9. **Spec review per `docs/process/spec-review.md`: 0 FAIL.** | doc | 387 | PR-C1 | S19-20 | [ ] | ADR-008 status Accepted; both ADR indexes in sync; spec review 0 FAIL recorded in the PR |
| S19-26 | **Tool folders out of git.** `git rm -r --cached .claude/ .mcp.json`; add `.claude/` and `.mcp.json` to `.gitignore` (maintainer keeps local copies). | config | 388 | PR-C1 | S19-19..25 | [ ] | `git ls-files .claude .mcp.json` empty; no remaining repo link to a `.claude/` path outside frozen records |
| S19-27 | **Drift resolved in the rewrite**: `validation.md` §4/§6.2 tooling aligned with `pyproject.toml` (fact 9) + **`--strict-markers` decision** (recommended: adopt in `addopts` after verifying all markers are registered; alternative: drop the claim). | doc / config | 377 | PR-C1 | — | [ ] | validation.md quotes only real settings; if adopted, full suite green under `--strict-markers` |
| S19-28 | **Disposition of `docs/analysis/dev-process-analysis.md`** (uncommitted; contains handles, runner hostnames, local paths): sanitize then commit, or keep private (CONTRIBUTING + `docs/process/` are its public distillation). | doc | 377 | PR-C1 | S19-19 | [ ] | Decision recorded; if committed, audit commands return nothing on it |

### PR-C2 — Contributor process (GH #279)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-29 | **`CONTRIBUTING.md`**: roles (maintainer merges, tags, bumps); fork workflow (fork → `feature/<topic>` → PR against `develop`), issue first; local gates (exact ruff / mypy / pytest commands, Python 3.12 + 3.14); tests (levels, directories, markers, `importorskip`); docs touchpoints (spec, DES, ADR amendment, validation rows, README, guides + stamps, command-lint, CHANGELOG `Unreleased` line); RFC-lite (external design issue → maintainer updates the formal docs); draft-first PRs, review per `docs/process/code-review.md`; PR "Status" section convention; owner merges/tags; **how to point each tool at `AGENTS.md`** (generic: any agent or editor reads `AGENTS.md`; tool-specific pointer files exist only as one-liners). | doc | 376 | PR-C2 | PR-C1 merged | [ ] | Commands copy-pasteable; no tool required; public-file rule clean |
| S19-30 | **`.github/PULL_REQUEST_TEMPLATE.md`**: `Closes #N`, Summary, Spec impact, Tests (incl. engine env used), gate + docs checklists, Status section, backend sub-checklist. | doc | 376 | PR-C2 | S19-29 | [ ] | Items match CONTRIBUTING and `docs/process/code-review.md` |
| S19-31 | **`.github/ISSUE_TEMPLATE/`**: `feature.yml`, `new-backend.yml` (paradigm, engine package + version bound, capabilities matrix, real-engine test plan), `bug.yml`, **`sprint-planning.yml`** (body sections per `docs/process/sprint-planning.md`); `config.yml` routes security reports to `SECURITY.md`. | doc | 376 | PR-C2 | S19-29 | [ ] | The four templates render in the issue chooser |
| S19-32 | **`.github/CODEOWNERS`**: maintainer for `*` and the governance paths (`/AGENTS.md`, `/CLAUDE.md`, `/GEMINI.md`, `/.github/`, `/docs/architecture/`, `/docs/specs/`, `/docs/validation/`, `/docs/process/`, backends, `db.py`, `pyproject.toml`). | config | 389 | PR-C2 | — | [ ] | No CODEOWNERS syntax error |
| S19-33 | **`SECURITY.md`**: supported versions, GitHub private vulnerability reporting (enabled in S19-47), no e-mail address. | doc | 389 | PR-C2 | — | [ ] | Linked from `config.yml` and CONTRIBUTING |
| S19-34 | **`.github/dependabot.yml`**: `pip` + `github-actions`, weekly, target `develop`, grouped minor/patch. | config | 389 | PR-C2 | — | [ ] | Validates; keeps the SHA pins of S19-38 current |
| S19-35 | **Index lines**: README "Documentation"/"Contributing" lines (CONTRIBUTING, SECURITY, AGENTS, `docs/process/`); `AGENTS.md` index rows for CONTRIBUTING, SECURITY, templates. | doc | 389 | PR-C2 | S19-29, S19-33 | [ ] | Links resolve; doc-lint green |
| S19-36 | **Doc command-lint corpus**: extend `doc_files()` to root `CONTRIBUTING.md`, `AGENTS.md` (and the pointer files); exclude `CHANGELOG.md` explicitly; unit test pinning the corpus composition. | test | 389 | PR-C2 | S19-29 | [ ] | `test_corpus_includes_contributor_docs` passes |

### PR-D — Workflow hardening (refs GH #278)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-37 | **Path-filter trap** (fact 7): drop `paths-ignore` from `ci.yml`; **fold the doc-lint job into `ci.yml`** (same job name `Doc command-lint (fenced CLI invocations)`, same draft guard) and delete `doc-lint.yml`; update header comments. Four job names byte-identical. | ci | 378 | PR-D | — | [ ] | A docs-only PR and a code-only PR both report all four checks; `doc-lint.yml` gone |
| S19-38 | **SHA-pin every action** to a full commit SHA with a `# vX.Y.Z` comment. | ci | 378 | PR-D | — | [ ] | Every `uses:` is a 40-hex SHA; CI green |

### Release v0.19.0

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-39 | **Bump + release notes** per `docs/process/release.md`: `0.19.0` in `pyproject.toml` and `src/revolver/__init__.py`; CHANGELOG `Unreleased` → `[0.19.0] — <date>`; README refresh; `verified-against: v0.19.0` on the freshness corpus after re-verification; validation review (`docs/process/validation-review.md`) on the S19-27 edit. | release | 380 | release commits on `develop` | A, B, C1, C2, D merged | [ ] | Both version files `0.19.0`; freshness + doc-lint green |
| S19-40 | **`develop` → `main` + annotated tag `v0.19.0`** — owner GO. | release | 380 | — | S19-39 | [ ] | `version-check` green; tip of `main` is the merge commit |
| S19-41 | **Install check + post-release verification**: install from the GitHub URL (authenticated while private), `revolver --version`; tag, version files, CHANGELOG section, backlog. | release | 380 | — | S19-40 | [ ] | All checks pass and are reported |
| S19-42 | **Post-release doc review** per `docs/process/doc-review.md`; fixes on `develop`. | doc | 380 | fix commits | S19-41 | [ ] | 0 FAIL |

### Task-D — operations: switch to public + settings (GH #278, no PR)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-43 | **Pre-flip gate.** (a) release done (S19-39..42); (b) the external contributor's commits re-authored (identity rewrite, coordinated with the contributor) or the contributor's branches removed — **caveat**: a PR keeps its head ref and force-push timeline, so superseded commits stay reachable by SHA through the PR; if the exposure matters, close the affected PRs and request a GitHub Support purge before the flip; (c) audit commands re-run on `main` and `develop`; (d) worklist done (S19-16); (e) history rewrite **not** performed (decided). | ops | 379 | — | S19-16, S19-42 | [ ] | Items ticked in GH #278 |
| S19-44 | **Visibility flip** private → public. | ops | 379 | — | S19-43 | [ ] | Anonymous `git clone` works |
| S19-45 | **Rulesets**: `develop` + `main` — PR required, required checks exactly the four names, block force-push and deletion, **bypass "always" for the repository admin**; tag ruleset `v*` — creation/update/deletion restricted (admin bypass). | ops | 379 | — | S19-44, S19-37 merged | [ ] | Throwaway PR shows the four required checks and is blocked until green; non-bypass push to `main` and tag push rejected; admin direct commit on `develop` still works |
| S19-46 | **Actions policy**: fork-PR approval `all_external_contributors`; `allowed_actions = selected` (GitHub-owned, SHA-pinned); default token read-only. | ops | 379 | — | S19-44, S19-38 merged | [ ] | A fork PR waits for approval |
| S19-47 | **Security features**: secret scanning + push protection; Dependabot alerts + security updates; private vulnerability reporting. | ops | 379 | — | S19-44 | [ ] | All toggles on |
| S19-48 | **Repository settings**: `delete_branch_on_merge = true`; description + topics; stale merged branches deleted; collaborators back to `write` together with the rulesets. | ops | 379 | — | S19-45 | [ ] | No merged branch left; permissions as planned |
| S19-49 | **GitHub-native planning bootstrap** (follows from decision 1): label set (type / area / priority / backend), Sprint 020 milestone + planning issue from the sprint-planning template; open backlog rows (`[ ]` / `[~]`) migrated to issues, each citing its frozen backlog row number. | ops | 390 | — | S19-31 merged | [ ] | Every open backlog row has an issue or an explicit "dropped" note; Sprint 020 milestone exists |
| S19-50 | **Optional — GitHub Releases** for recent tags (body from CHANGELOG) + **anonymous install check** from the public URL. | ops | 379 | — | S19-44 | [ ] | `pip install "revolver @ git+https://github.com/<owner>/revolver@v0.19.0"` works without credentials |

---

## PR Mapping

| PR | GitHub issue | Backlog | Tasks | Files (primary) | Wave |
|---|---|---|---|---|---|
| **#274** (merged) | #272 | 372 | S19-01 | `.github/workflows/*`, `.github/runner/` (removed), `LICENSE` | 0 |
| **PR-A** | #275 | 373 | S19-02..09 | `docs/sessions/*` (removed) + `README.md` there, `CHANGELOG.md`, `docs/tasks/backlog.md` (banner), `docs/sprints/README.md`, `CLAUDE.md`, `.gitignore`, `README.md`, `.claude/skills/session-close/SKILL.md` | 1 |
| **PR-B** | #276 | 374 (+375 ops) | S19-10..15 (+S19-16) | docs per audit list (living docs, `docs/sprints/*`, `docs/tasks/backlog.md`, `docs/analysis/*`, `README.md` if hit), two comments under `src/revolver/` — **not** `CLAUDE.md`, **not** `.claude/` | 2 |
| **PR-C1** | #277 | 377, 384–388 | S19-17..28 | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `docs/process/*.md`, `docs/architecture/adr/ADR-008-*.md`, `docs/architecture/architecture.md` §9, `docs/validation/validation.md`, `pyproject.toml` (`addopts`, if adopted), `tests/unit/test_doc_freshness.py` (message), `.gitignore`, `.claude/` + `.mcp.json` (removed from git) | 2 |
| **PR-C2** | #279 | 376, 389 | S19-29..36 | `CONTRIBUTING.md`, `SECURITY.md`, `.github/{PULL_REQUEST_TEMPLATE.md,ISSUE_TEMPLATE/,CODEOWNERS,dependabot.yml}`, `tests/unit/test_doc_command_lint.py`, `README.md` + `AGENTS.md` (index lines only) | 3 |
| **PR-D** | refs #278 | 378 | S19-37..38 | `.github/workflows/ci.yml`, `.github/workflows/doc-lint.yml` (deleted) | any time |
| release commits | — | 380 | S19-39..42 | `pyproject.toml`, `src/revolver/__init__.py`, `CHANGELOG.md`, `README.md`, guide front-matter | 4 |
| operations | #278 | 375, 379, 390 | S19-16, S19-43..50 | GitHub settings, labels, milestone, issues | 5 |

---

## Integration Tests (L2)

No product behavior change → **no new L2 scenario**. Validated by the doc guards, one new unit test, full-suite regression and GitHub-side checks.

| Area | Scenario | Test ID | Status |
|---|---|---|---|
| Doc command-lint | Corpus (README + `docs/**` incl. `docs/process/` + root contributor docs) resolves | `test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_invocations_resolve` | Planned |
| Doc command-lint corpus | `CONTRIBUTING.md` / `AGENTS.md` included, `CHANGELOG.md` excluded | `test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_includes_contributor_docs` (new, S19-36) | Planned |
| Doc freshness | Freshness corpus stamped `v0.19.0`; failure message points to `docs/process/release.md` | `test_doc_freshness::TestDocFreshnessCorpus::test_corpus_is_stamped_and_fresh` + `TestFreshnessChecker::test_missing_front_matter_fails` | Planned |
| Strict markers (if adopted) | Full suite passes with `--strict-markers` | full-suite run (S19-27) | Planned |
| Non-regression | Full suite at the S18 baseline (1585 passed / 4 skipped); ruff / mypy clean | full-suite regression | Planned |
| CI reachability | Docs-only and code-only PRs both report the four required checks | throwaway PRs (S19-37, S19-45) | Planned |
| Release guard | `version-check` passes on `v0.19.0` | CI job on tag push (S19-40) | Planned |

---

## Parallelization

### Dependency graph

```
S19-01 (CI GitHub-hosted + LICENSE)  [DONE, PR #274]

PR-D  S19-37 (filters + fold doc-lint) ─ S19-38 (SHA pins)     ← independent, any time before release

maintainer journal export
   └──> PR-A  S19-02 → S19-03, S19-04, S19-06 (parallel) → S19-05 → S19-07, S19-08 → S19-09
                     │ merged
          ┌──────────┴────────────────────────────┐
          ▼                                       ▼
   PR-B  S19-10..14 → S19-15              PR-C1  S19-19..24 (parallel checklists) → S19-25 (ADR-008)
          │                                      S19-17 → S19-18 ; S19-27, S19-28
          │                                      → S19-26 (tool folders out, LAST)
          │                                       │ merged
          │                                       ▼
          │                               PR-C2  S19-29 → S19-30, S19-31, S19-35, S19-36
          │                                      S19-32, S19-33, S19-34 (parallel)
          └──────────────┬────────────────────────┘
                         ▼   (+ PR-D merged)
          Release  S19-39 → S19-40 (owner GO) → S19-41 → S19-42
                         ▼
          S19-16 (worklist, switch day) → S19-43 (pre-flip gate) → S19-44 (flip)
                         ├──> S19-45 (rulesets) → S19-48 (settings, collaborators)
                         ├──> S19-46 (Actions policy)
                         ├──> S19-47 (security features)
                         ├──> S19-49 (planning bootstrap — needs C2's template)
                         └──> S19-50 (optional Releases + anonymous install)
```

### Waves

| Wave | Content | Gate to open |
|---|---|---|
| 0 | S19-01 (done) | — |
| 1 | PR-A | maintainer confirms the journal export |
| 2 | PR-B ∥ PR-C1 | PR-A merged |
| 3 | PR-C2 | PR-C1 merged |
| any | PR-D | none (must be merged before wave 4) |
| 4 | Release v0.19.0 | A, B, C1, C2, D merged |
| 5 | Switch to public + settings + planning bootstrap | release done, S19-16 + S19-43 done |

**Release before flip.** The public repository opens on a tagged, CHANGELOG-documented state with hardened workflows on `main`. The S19-41 install check runs authenticated; the anonymous check is repeated after the flip (S19-50). Rulesets come after the flip; the admin "always" bypass keeps the maintainer's direct `develop` commits and the local release merge working for v0.20.0 onward.

### Critical path

```
journal export → PR-A (S19-02..09) → PR-C1 (S19-19..25 → S19-26) → PR-C2 (S19-29..36)
   → S19-39 → S19-40 → S19-41 → S19-42 → S19-16 → S19-43 → S19-44 → S19-45 → S19-48
```

PR-C1 is the largest PR and now sits on the critical path (C2 depends on it); PR-B and PR-D run alongside and are off the critical path.

### Parallel work streams

| Stream | Tasks | Can start after | Assignment |
|---|---|---|---|
| A — Restructuring | S19-02..09 | journal export confirmed | Contributor 1 |
| D — Workflow hardening | S19-37..38 | now | Contributor 2 (small) |
| B — Content cleanup | S19-10..15 | PR-A merged; audit list handed over **outside the repository** | Contributor 1 |
| C1 — Framework-agnostic process | S19-17..28 (checklists S19-19..24 parallelizable) | PR-A merged | Contributor 2 (+ helpers per checklist) |
| C2 — Contributor files | S19-29..36 | PR-C1 merged | Contributor 1 or 2 |
| R — Release | S19-39..42 | A, B, C1, C2, D merged | maintainer (owner GO) |
| O — Operations | S19-16, S19-43..50 | release done | maintainer |

Peak parallelism: **2 contributors** in wave 2 (B ∥ C1), more inside C1 if the six checklists are split.

### Conflict map

| File / area | Touched by | Resolution |
|---|---|---|
| `CLAUDE.md` | PR-A (minimal edits), PR-C1 (reduced to a pointer) | **A then C1 only.** PR-B does not touch it. |
| `AGENTS.md` | PR-C1 (creates), PR-C2 (index lines) | Sequential by construction (C2 depends on C1). |
| `README.md` | PR-A (release table), PR-B (audit hits only), PR-C2 (index lines only), release (test count) | A → B → C2 → release. C1 does not touch README. |
| `.claude/` | PR-A (session-close skill), PR-C1 (removes the folder from git) | A then C1. PR-B does not touch it. |
| `.gitignore` | PR-A (`CLAUDE.local.md`), PR-C1 (`.claude/`, `.mcp.json`) | A then C1; trivial. |
| `docs/validation/validation.md` | PR-B (audit hits, if any), PR-C1 (tooling sections) | Merge B before C1 when both are ready; otherwise C1 rebases. |
| `docs/tasks/backlog.md`, `docs/sprints/*` | PR-A (freeze banner, `docs/sprints/README.md`), PR-B (neutralization), orchestrator progress commits | A first; avoid progress commits while PR-B is open, or rebase PR-B last-minute. |
| `CHANGELOG.md` | PR-A (creates), B / C1 / C2 / D (one `Unreleased` line each), release | Trivial append conflicts. |
| `tests/unit/test_doc_freshness.py` | PR-C1 (message) | — |
| `tests/unit/test_doc_command_lint.py` | PR-C2 | — |
| `.github/` | PR-C2 (new files), PR-D (workflows) | Disjoint files — parallel-safe. |
| `src/revolver/` (two comments) | PR-B | — |
| Required-check names | PR-D keeps them byte-identical; S19-45 depends on them | No rename. |

---

## Exit Criteria

The sprint is complete when ALL of the following hold:

1. **CI + LICENSE** — S19-01 merged (done).
2. **Journal out** — `docs/sessions/` holds only `README.md`; the private-journal pattern is documented in `AGENTS.md`; `CLAUDE.local.md` is gitignored; contributors write no session reports and keep a PR "Status" section instead.
3. **CHANGELOG** — one section per release v0.1.0 … v0.19.0 + `Unreleased`; README points to it; the release procedure names it as the release-note vehicle.
4. **Frozen records** — `docs/tasks/backlog.md` carries the freeze note; `docs/sprints/README.md` exists; no file under either was moved or renumbered.
5. **Clean content** — audit commands return nothing beyond known test dummies on `main` and `develop`; GitHub-side worklist done; no committed file breaks the public-file rule.
6. **Framework-agnostic** — `AGENTS.md` is the canonical entry file; `CLAUDE.md` and `GEMINI.md` are one-line pointers to it; `.claude/` and `.mcp.json` are absent from git (`git ls-files` empty); ADR-008 is Accepted (spec review 0 FAIL) and indexed; the §4.5 drift is resolved (validation.md tooling matches pyproject, `--strict-markers` decided); the dev-process analysis is kept private or committed sanitized.
7. **Human-followable process** — a human without any agent can perform a code review, a spec / validation / doc review, a sprint planning and a release by following `docs/process/*.md` + `CONTRIBUTING.md` alone.
8. **Contributor process** — CONTRIBUTING, PR template, four issue templates (incl. sprint-planning), CODEOWNERS, SECURITY and dependabot on `main`.
9. **CI fit for rulesets** — doc-lint folded into `ci.yml`, no path filters; every PR reports the four required checks; all actions SHA-pinned.
10. **Released** — v0.19.0 tagged on `main`, both version files match, `version-check` green, stamps at `v0.19.0`, install from the GitHub URL works, post-release doc review 0 FAIL.
11. **Public and locked down** — repository public; rulesets on `develop`, `main`, `v*` with the four required checks and admin "always" bypass; secret scanning + push protection, Dependabot alerts/security updates, private vulnerability reporting on; fork-PR approval for all external contributors; `allowed_actions = selected`; `delete_branch_on_merge`; collaborators back to `write`; anonymous install verified; Sprint 020 milestone + planning issue exist and open backlog rows are migrated to issues.
12. **Zero regression** — full suite green at the S18 baseline (+1 new unit test); ruff / mypy clean; CI green.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Knowledge loss when `.claude/` leaves git** (an agent rule not carried into `docs/process/`). | Medium | C1 internal order: checklists first, removal last (S19-26); reviewer diffs each agent definition against its checklist before approving. |
| **PR-C1 is large and on the critical path.** | Medium | Six independent checklist files parallelizable; ADR-008 can be reviewed as soon as `spec-review.md` exists; split into commits per deliverable. |
| **`docs/process/` and `AGENTS.md` duplicate each other** and drift. | Medium | `AGENTS.md` links to `docs/process/` instead of restating procedures; ADR-008 names the authoritative tier of each document. |
| **Superseded commits reachable through PR refs** after an identity rewrite or branch deletion. | Medium | S19-43 (b) caveat; GitHub Support purge if needed, before the flip. |
| **Removed files remain in git history** once public. | Accepted | Owner decision: no rewrite (audit found no secrets). |
| **Path-filter trap** blocks every PR once rulesets are on. | High (if missed) | PR-D merged before S19-45; verified with docs-only and code-only throwaway PRs. |
| **Audit details leak into the repo** through the cleanup PR (commit messages, PR description). | Medium | Audit list handed over out-of-band; generic commit messages and PR descriptions. |
| **Backlog migration to issues is lossy** (S19-49). | Low | Each issue cites its frozen backlog row; the frozen file stays authoritative for history. |
| **CHANGELOG seeding is lossy** for early sprints. | Low | README table as the floor; enrich from sprint reviews. |
| **`--strict-markers` reveals an unregistered marker.** | Low | Verify before adopting; fallback is documentation-only alignment. |

---

## Sprint Review

_Filled at sprint end. Last file-based sprint review; from Sprint 020 the review is the CHANGELOG entry + the planning issue's closing comment._

### Tests passing
- _X passed / Y skipped (no-shinka env); doc guards; CI on GitHub-hosted runners._

### Demo-able features
- [ ] Anonymous clone + install of v0.19.0 from the public GitHub URL
- [ ] `CHANGELOG.md` covering v0.1.0 … v0.19.0
- [ ] `AGENTS.md` canonical; `CLAUDE.md` / `GEMINI.md` pointers; no tool folders in git
- [ ] Code review and release performed from `docs/process/` + CONTRIBUTING without any agent
- [ ] Issue chooser with feature / new-backend / bug / sprint-planning templates; PR template pre-filled
- [ ] Fork PR gated by approval, then by the four required checks
- [ ] Security features on; Sprint 020 milestone + planning issue in place

### Carry-over
- LoongFlow backend (GH #273, external PRs #270/#271) → Sprint 020 / v0.20.0
- Documentation shrink step 2 (backlog 381–383, #357) → unscheduled S20+ (ADR-008 follow-up)
