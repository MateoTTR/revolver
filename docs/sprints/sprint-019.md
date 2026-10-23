# Sprint 019 — Public Release (v0.19.0)

**Status**: In Progress (S19-01 shipped; PR-A next)
**Target release**: **v0.19.0** (normal sprint release — Release Checklist per CLAUDE.md; `develop` → `main`, tag `v0.19.0`)
**Goal**: Make the repository fit to switch from private to public: move the maintainer session journal out of the tree, give the project a real release-note vehicle (`CHANGELOG.md`), clean the remaining pre-publication hygiene items, publish a contributor process (CONTRIBUTING, templates, CODEOWNERS, SECURITY, Dependabot), harden CI for required checks, release v0.19.0, then flip the visibility and lock the repository down (rulesets, security features, Actions policy).
**Demo**: after the flip, an anonymous user clones the public repository, installs `v0.19.0` from the GitHub URL and gets `revolver --version` → `0.19.0`; `CHANGELOG.md` lists every release from v0.1.0 to v0.19.0; `docs/sessions/` holds only a README pointer; opening an issue offers the feature / new-backend / bug templates; a fork PR waits for maintainer approval, then runs the four required checks on GitHub-hosted runners and cannot be merged until they pass; secret scanning, push protection, Dependabot and private vulnerability reporting are on.
**Source**: Owner decisions of 2026-10-23 (public switch, journal relocation, documentation strategy step 1, LoongFlow re-targeted to Sprint 020). The development-process analysis (`docs/analysis/dev-process-analysis.md`, §4 gaps, §4.6 ranked recommendations, §5 drafts — see S19-27 for its disposition). The pre-publication audit list (kept outside the repository). GitHub issues #272 (done), #275–#278.
**Predecessor**: Sprint 018 (v0.18.0 — eval honesty semantic slice + top-N flagship).

> **No product change this sprint.** Nothing under `src/revolver/` changes behavior; the only source edits are two comment renames (S19-10). v0.19.0 is user-visible through documentation and process only: `CHANGELOG.md`, the journal relocation, and the contributor process. Full-suite regression must stay green at the S18 baseline (1585 passed / 4 skipped, no-shinka env).

> **Public-file rule (applies to every deliverable of this sprint, including this file).** No local filesystem paths, machine or runner hostnames, private repository names, e-mail addresses, personal timing data or business-domain words in any committed file. Use neutral wording ("a local path", "a network Ollama host", "a separate demo repository", "a third-party endpoint shim"). The concrete hit list lives in the maintainer-side audit list (kept outside the repository) and is never copied into the repo.

---

## Scope

### In scope

| Story | GitHub issue | PR | Content |
|---|---|---|---|
| **CI on GitHub-hosted runners + LICENSE** | #272 | #274 (merged 2026-10-23) | `ci.yml` / `doc-lint.yml` on `ubuntu-latest` (`actions/setup-python` v6, `permissions: contents: read`, `REVOLVER_HOME` via `GITHUB_ENV`), `.github/runner/` removed, MIT `LICENSE` (copyright: the maintainer). **Done.** |
| **Documentation restructuring, step 1** | #275 | PR-A | Session journal leaves the repository (`docs/sessions/*`, 62 files incl. `cost-tracker.md`) → a `docs/sessions/README.md` pointer remains; `CHANGELOG.md` (Keep a Changelog) seeded v0.1.0…v0.18.0 + `Unreleased`; `AGENTS.md` pointer; CLAUDE.md index / session checklist / phase line / release checklist adjusted; `CLAUDE.local.md` gitignored; README release table → CHANGELOG pointer, docs section refreshed; doc guards green. |
| **Pre-publication content cleanup** | #276 | PR-B | Mechanical, docs-mostly, driven by the maintainer-side audit list: local paths, hostnames, pointers to private sibling repositories, remaining off-topic paragraphs, editorial markers, third-party endpoint shim wording, a hostname in two source comments. Plus the GitHub-side worklist (issue/PR body edits) executed by the maintainer on switch day — a task, not a PR. |
| **Contributor process** | #277 | PR-C | `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/` (feature, new-backend, bug), `.github/CODEOWNERS`, `SECURITY.md`, `.github/dependabot.yml` (pip + github-actions); fix the process-doc drift of dev-process-analysis §4.5. |
| **Switch to public + settings** | #278 | PR-D (workflow hardening only) + operations | PR-D: resolve the required-check path-filter trap, SHA-pin the actions. Operations (no PR): pre-flip gate, visibility flip, rulesets, security features, Actions policy, repository settings, collaborators, optional GitHub Releases. |
| **Release v0.19.0** | — | release commits | CLAUDE.md Release Checklist (as amended by PR-A): bump both version files, CHANGELOG `Unreleased` → `0.19.0`, README refresh, `verified-against: v0.19.0` stamps, `develop` → `main`, tag, install check from the GitHub URL, post-release doc-reviewer. |

### Explicitly out of scope

| Deferred item | Target | Rationale |
|---|---|---|
| **LoongFlow backend** (external draft PRs #270/#271, catch-up issue #273) | **Sprint 020 / v0.20.0** | First external backend contribution; it needs the contributor process (PR-C) and the hardened CI (PR-D) in place first, and goes through the DoD §3b backend checklist of the dev-process analysis. Issue #273 is retitled by the orchestrator. |
| **Documentation shrink, step 2** — generated traceability from pytest markers carrying FR ids; shrink of the L2 test matrix in the validation docs; Diátaxis reorganisation of the guides | Backlog (unscheduled, S20+), rows 381–383, tied to #357 | Step 1 (this sprint) is structural only (journal out, CHANGELOG in). Step 2 changes how validation docs are produced and deserves its own design (possibly ADR-008, as #357 already suggests). |
| **#357** executable e2e + generated CLI reference | Backlog (unscheduled, S20+) | Was "S19" in the S18 carry-over; displaced by the public-release sprint. Grouped with the step-2 rows. |
| **Other S18 carry-overs** — OE top-N (post-#367), L3 E2E Scenario 5 (penalize-vs-drop on the fake server), live Shinka smoke on ≥0.17.1 through an OpenAI-compatible local endpoint, the "post-extraction training evaluation" doc drift | S20+ | Product work; this sprint carries no product change. |
| **Remaining dev-process recommendations** not chosen by the owner for S19 — generic backend conformance test (§4.6 rank 6), adding-a-backend guide (rank 7), optional engine CI job (rank 9), English reviewer-agent output for external PRs (rank 5) | Sprint 020 candidates (LoongFlow) | Directly useful for the first external backend; scoping them belongs to the Sprint 020 planning. |
| **Git history rewrite** | Decision only (S19-34) | Files removed from the tree stay reachable in history once public. The audit found no secrets; the default recommendation is to accept the history as is. Recorded as an explicit decision, not silently assumed. |

---

## Verified facts driving the plan (checked on `develop` @ `bdfb02f` — do not re-derive)

1. **Doc guard corpora.** `tests/unit/test_doc_command_lint.py` lints `README.md` + every `docs/**/*.md` (`doc_files()`); root-level files such as a new `CHANGELOG.md`, `CONTRIBUTING.md` or `AGENTS.md` are **not** linted today. `tests/unit/test_doc_freshness.py` scans `docs/guides/*.md` + `docs/specs/user-story-e2e.md` (stamp ≤ 1 minor behind). Removing `docs/sessions/*` only shrinks the lint corpus; no test, workflow or source file reads `docs/sessions/`.
2. **References to the journal outside `docs/sessions/`** are limited to `CLAUDE.md` (index rows, checklist steps 5–6, release checklist step 7), `.claude/skills/session-close/SKILL.md`, `docs/tasks/backlog.md` (historical "session NNN" mentions — stay as-is) and the uncommitted dev-process analysis. The only **markdown links** into `docs/sessions/` are the 4 in `CLAUDE.md` → no dead links elsewhere after removal (plain-text mentions in sprint files stay as historical references).
3. **CLAUDE.md drift.** Phase 5 line still reads "Sprint 009 complete (v0.9.0 released)"; Release Checklist step 6 installs from a local `git+file://` path (must become the GitHub URL). The Guides table already points to `docs/guides/tuning-evolution.md` on `bdfb02f` — S19-05 only re-verifies it (the old `tuning-oe-config.md` name survives only in historical sprint files and backlog rows, which stay).
4. **There is no `CHANGELOG.md`.** Release notes have so far landed in the README (release/sprint table + "Behavior changes (v0.18)" subsection) and in the annotated tag message (sprint-018 §Release note).
5. **Required-check names** (exact, as rendered by GitHub): `Lint (ruff + mypy)`, `Test (pytest + coverage) (3.12)`, `Test (pytest + coverage) (3.14)` (from `ci.yml`), `Doc command-lint (fenced CLI invocations)` (from `doc-lint.yml`). `ci.yml` has `paths-ignore: ['**.md', 'docs/**']` and `doc-lint.yml` has the complementary `paths:` filter → **every PR leaves at least one required check un-triggered**, which a ruleset reports as "Expected — waiting for status" forever (the path-filter trap). Draft PRs skip jobs through `if:` — a *skipped* job does satisfy a required check, a *never-triggered* workflow does not.
6. **Actions are tag-pinned** (`actions/checkout@v5`, `actions/setup-python@v6`), not SHA-pinned.
7. **`pyproject.toml` has no `--strict-markers`** while `docs/validation/validation.md` §4/§6.2 documents `addopts = "--strict-markers -v"`, ruff `py311`/`line-length 100` and an `e2e_gpu` marker that pyproject does not define.
8. **Backlog vs GitHub numbering.** Backlog task numbers and GitHub issue/PR numbers share the same range (backlog rows 272–278 are Sprint 013 tasks). In this sprint, "GH #N" means GitHub; bare numbers in the backlog column mean backlog rows.

---

## Tasks

### Shipped — CI + LICENSE (GH #272)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-01 | **CI moved to GitHub-hosted runners + MIT LICENSE.** `ci.yml` and `doc-lint.yml` on `ubuntu-latest`, `actions/setup-python` v6, `permissions: contents: read`, `REVOLVER_HOME` set through `GITHUB_ENV`; `.github/runner/` removed; `LICENSE` (MIT, copyright: the maintainer). | ci | 372 | #274 | — | [x] | Merged 2026-10-23; Lint + Test 3.12/3.14 + doc-lint green on GitHub-hosted runners; `pyproject.toml` `license = "MIT"` now backed by a `LICENSE` file |

### PR-A — Documentation restructuring, step 1 (GH #275)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-02 | **Journal out of the tree.** Remove `docs/sessions/*` (62 files, incl. `cost-tracker.md` and the non-session note in that directory); add `docs/sessions/README.md` (short: the session journal is a private maintainer journal kept outside the repository; sprint files in `docs/sprints/` and the backlog remain the public planning record; historical "session NNN" references in sprint files and the backlog are intentionally left as they are). **Precondition (maintainer action, not in the PR):** the files are exported to the private journal first. | doc | 373 | PR-A | maintainer export confirmed | [ ] | `docs/sessions/` contains only `README.md`; the PR description states the export was done; no file outside `docs/sessions/` links to a removed file (fact 2) |
| S19-03 | **`CHANGELOG.md`** at the repo root, Keep a Changelog style: `## [Unreleased]` + one `## [X.Y.Z] — YYYY-MM-DD` section per existing tag (v0.1.0 … v0.18.0, including the corrective `a/b/c` releases and the v0.12.1 hotfix), seeded from the README release/sprint table and the sprint-review sections; group entries under Added / Changed / Fixed / Removed where the source allows; v0.18.0 carries the six "Behavior changes" items (moved from the README); comparison links at the bottom. **No fenced `revolver …` blocks** (historical flags would fail the lint if the file is ever added to the corpus — see S19-26). Dates from the tag dates. | doc | 373 | PR-A | — | [ ] | Every `v*` tag has exactly one section; `Unreleased` exists; the v0.18.0 behavior changes are present; no public-file-rule hit |
| S19-04 | **`AGENTS.md`** at the repo root: a short pointer for non-Claude coding agents → read `CLAUDE.md` (conventions, Git Flow, quality gates, documentation index) and `CONTRIBUTING.md` (once PR-C lands; until then, CLAUDE.md alone). No duplicated rules. | doc | 373 | PR-A | — | [ ] | ≤ ~20 lines; points to CLAUDE.md; contains no rule that is not in CLAUDE.md |
| S19-05 | **CLAUDE.md adjustments.** (a) Documentation index: replace the "Session reports" / "Session cost tracker" rows by one "Session journal" note (private, outside the repository, location configured in `CLAUDE.local.md`); add rows for `CHANGELOG.md` and `AGENTS.md`. (b) Session Checklist step 5 → read the latest journal entry *if a journal is configured in `CLAUDE.local.md`*; step 6 → write a date-based journal entry there (no global session counter), update the backlog; state that **contributors are not expected to write session reports** and that **long-running PRs keep a short "Status" section in the PR description**, updated at each working session. (c) Phase 5 line → generic ("In progress — see `CHANGELOG.md` for the latest release"). (d) Guides table: re-verify the tuning-guide link (fact 3; no-op if still correct). (e) Release Checklist: step 1b gains "move CHANGELOG `Unreleased` → `X.Y.Z`" (CHANGELOG becomes the release-note vehicle; README keeps features/install/test counts); step 6 install URL → `pip install "revolver @ git+https://github.com/<owner>/revolver@vX.Y.Z"`; step 7 replaces the session-report / cost-tracker checks with "journal entry written (maintainer)" + "CHANGELOG section present". | doc | 373 | PR-A | S19-03, S19-04 | [ ] | No link into a removed file; no local path; checklist steps consistent with the new journal model; doc-lint green |
| S19-06 | **`.gitignore`**: add `CLAUDE.local.md`. | config | 373 | PR-A | — | [ ] | `git check-ignore CLAUDE.local.md` succeeds |
| S19-07 | **README refresh.** Replace the "Project Status" release/sprint table by a pointer to `CHANGELOG.md` (optionally keep a 3–4-row "recent releases" table); move "Behavior changes (v0.18)" into the CHANGELOG v0.18.0 section (keep a one-line pointer); refresh the "Documentation" section (guides, CHANGELOG, link to `LICENSE`). Leave the CONTRIBUTING/SECURITY links to PR-C (S19-25). | doc | 373 | PR-A | S19-03 | [ ] | README has no release table longer than the optional short one; every link resolves; doc-lint green (fenced invocations unchanged) |
| S19-08 | **Doc guards + regression.** Run `tests/unit/test_doc_command_lint.py` and `tests/unit/test_doc_freshness.py`, then the full suite; confirm no tooling reads `docs/sessions/` (fact 2). | test | 373 | PR-A | S19-02..07 | [ ] | Both doc-guard modules green; full suite at the S18 baseline; CI green (the PR is docs-only → doc-lint runs; see the path-filter note under PR-D) |

### PR-B — Pre-publication content cleanup (GH #276)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-09 | **Local paths → neutral** in every committed file still carrying one after PR-A (living docs, `.claude/` agents and skills, retained planning records: sprint files, backlog, analysis docs), per the audit list. Use repo-relative paths or placeholders (`<project-dir>`, `~/.revolver` stays — it is a product default, not a personal path). | doc | 374 | PR-B | PR-A merged | [ ] | Audit command for local paths returns nothing beyond known test dummies |
| S19-10 | **Hostnames → neutral** in docs (e.g. "a network Ollama host") **and** in the two source comments flagged by the audit list (comment-only rename; no behavior change). | doc / src (comments) | 374 | PR-B | PR-A merged | [ ] | Audit command for hostnames returns nothing; `ruff`/`mypy` clean; full suite green (the source edit triggers the full CI) |
| S19-11 | **Pointers to private sibling repositories → neutral wording** ("a separate demo repository", "an external bridge project"); keep the technical content of each item. | doc | 374 | PR-B | PR-A merged | [ ] | No private repository name remains in any committed file |
| S19-12 | **Off-topic paragraphs.** The two paragraphs flagged by the audit list sit in files removed by PR-A — **verify** that nothing of them survives elsewhere (quotes in sprint files, backlog, analysis docs); remove any residue. | doc | 374 | PR-B | PR-A merged | [ ] | Verification result recorded in the PR description (not in the repo) |
| S19-13 | **Editorial markers + third-party endpoint shim wording.** Remove editorial markers listed by the audit; make the wording about the third-party endpoint shim neutral in the living docs (what it is technically — an OpenAI/Ollama-compatible local endpoint — not whose or which subscription). Historical sprint/backlog rows: neutralize only what the audit list flags. | doc | 374 | PR-B | PR-A merged | [ ] | Living docs describe the shim generically; command-lint green |
| S19-14 | **Re-run the audit commands** on the PR branch; attach the (empty) result summary to the PR description. | test | 374 | PR-B | S19-09..13 | [ ] | Nothing reported beyond the known test dummies (fake API keys / placeholder hosts in tests) |
| S19-15 | **GitHub-side worklist** (no PR): edit the issue / PR bodies and comments flagged by the audit list (same categories as above), executed by the maintainer **on the day of the switch**, before S19-35. | ops | 375 | — | S19-14 | [ ] | Every worklist item ticked in the maintainer-side list |

### PR-C — Contributor process (GH #277)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-16 | **`CONTRIBUTING.md`** (from dev-process-analysis §5.1): roles (maintainer merges, tags, bumps versions); **fork workflow** for externals (fork → `feature/<topic>` → PR against `develop`), issue first; local gates (exact `ruff check` / `ruff format --check` / `mypy` / `pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"` commands, Python 3.12 + 3.14); tests (levels, directories, markers, `importorskip` for optional engines); **docs touchpoints** (spec FR + Commands/Error rows, DES, ADR amendment, validation rows with test IDs, README, guides + `verified-against`, command-lint, CHANGELOG `Unreleased` line); **RFC-lite**: an external contributor opens a design issue (new-backend / feature template) and the **maintainer** updates the formal docs (specs/DES/ADR/validation) — contributors are not required to edit them; draft-first PRs, review severities (0 CRITICAL before ready), **PR "Status" section** convention for long-running PRs; owner merges and tags; Definition of Done (feature / backend). English only. | doc | 376 | PR-C | PR-A merged (cites the new paths) | [ ] | Covers every §5.1 section; commands copy-pasteable; no public-file-rule hit; no Claude-only tooling required of contributors |
| S19-17 | **`.github/PULL_REQUEST_TEMPLATE.md`** (from §5.2): `Closes #N`, Summary, Spec impact, Tests (incl. engine env used), gate checklist, docs checklist, Status section, **backend sub-checklist**. | doc | 376 | PR-C | S19-16 | [ ] | Opening a PR pre-fills the template; items match CONTRIBUTING |
| S19-18 | **`.github/ISSUE_TEMPLATE/`**: `feature.yml`, `new-backend.yml` (Context / Read first / Scope / Out of scope / Acceptance / References — the shape of the existing sprint issues; new-backend adds paradigm, engine package + version bound, capabilities matrix, real-engine test plan), `bug.yml` (version, command, expected/actual, logs); `config.yml` points security reports to `SECURITY.md`. | doc | 376 | PR-C | S19-16 | [ ] | The three templates render in the "New issue" chooser (verifiable once public / on the PR preview) |
| S19-19 | **`.github/CODEOWNERS`** (from §5.3): maintainer as owner of `*` and of the governance paths (`/CLAUDE.md`, `/.claude/`, `/.github/`, `/docs/architecture/`, `/docs/specs/`, `/docs/validation/`, `/docs/sprints/`, backends, `db.py`, `pyproject.toml`). | config | 376 | PR-C | — | [ ] | GitHub shows no CODEOWNERS syntax error; review requests route to the maintainer |
| S19-20 | **`SECURITY.md`**: supported versions (latest minor), report through GitHub **private vulnerability reporting** (enabled in S19-37), no e-mail address, expected response. | doc | 376 | PR-C | — | [ ] | Linked from the issue-template `config.yml` and CONTRIBUTING |
| S19-21 | **`.github/dependabot.yml`**: `pip` (root `pyproject.toml`) + `github-actions` ecosystems, weekly, target `develop`, grouped minor/patch updates, small open-PR limit. | config | 376 | PR-C | — | [ ] | File validates (Dependabot "Check for updates" on the PR / after merge); github-actions updates keep the SHA pins of S19-29 current |
| S19-22 | **Drift: code-reviewer ADR range** → `ADR-001..007` in `.claude/agents/code-reviewer/agent.md`. | doc | 377 | PR-C | — | [ ] | Checklist names ADR-007 |
| S19-23 | **Drift: `validation.md` tooling sections vs `pyproject.toml`** (fact 7) + **`--strict-markers` decision**. Recommended: adopt `--strict-markers` in `pyproject.toml` `addopts` (all markers already registered — verify) and align validation.md §4/§6.2 with the real ruff/mypy/pytest config (drop `py311`, `line-length 100`, the undefined `e2e_gpu` marker or register it). Alternative: drop the claim from validation.md. Record the choice in the PR. | doc / config | 377 | PR-C | — | [ ] | validation.md quotes only settings present in pyproject; if adopted, the full suite passes under `--strict-markers` |
| S19-24 | **Drift: `/session-close` skill vs the journal decision.** Update `.claude/skills/session-close/SKILL.md`: write a date-based entry to the journal location configured in `CLAUDE.local.md` (no global counter, no repo cost-tracker); if no journal is configured, do nothing but the backlog update. | doc | 377 | PR-C | PR-A merged | [ ] | Skill no longer writes into `docs/sessions/`; consistent with CLAUDE.md steps 5–6 (S19-05) |
| S19-25 | **Indexes.** CLAUDE.md documentation index: rows for `CONTRIBUTING.md`, `SECURITY.md`, PR/issue templates; README "Documentation" / new "Contributing" lines linking CONTRIBUTING and SECURITY; `AGENTS.md` pointer to CONTRIBUTING activated. | doc | 376 | PR-C | S19-16, S19-20 | [ ] | All links resolve; command-lint green |
| S19-26 | **Doc command-lint corpus.** Extend `doc_files()` in `tests/unit/test_doc_command_lint.py` to the root contributor docs (`CONTRIBUTING.md`, `AGENTS.md`); **exclude `CHANGELOG.md` explicitly** (historical record — removed flags must stay quotable); add a unit test pinning the corpus composition. | test | 376 | PR-C | S19-16 | [ ] | New test `test_corpus_includes_contributor_docs` passes; any fenced `revolver …` in CONTRIBUTING resolves |
| S19-27 | **Disposition of the dev-process analysis** (`docs/analysis/dev-process-analysis.md`, uncommitted). In its current form it contains items the public-file rule forbids (handles, runner hostnames, local paths). Either keep it maintainer-side (CONTRIBUTING is its public distillation), or commit a sanitized copy; do not commit it as-is. | doc | 377 | PR-C | S19-16 | [ ] | Decision recorded in the PR; if committed, the audit commands return nothing on it |

### PR-D — Workflow hardening for rulesets (part of Task-D, refs GH #278)

PR-D is the only repository change of Task-D (workflow files); everything else in Task-D is GitHub configuration executed by the maintainer (section "Task-D — operations" below). It is independent of PR-A/B/C and may start immediately; it must be merged before the release so the public repository opens on hardened workflows.

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-28 | **Path-filter trap** (fact 5). Recommended: **drop the `paths-ignore` filter of `ci.yml` and the `paths` filter of `doc-lint.yml`** so all four required checks report on every PR and push (on a public repository, GitHub-hosted standard runners are free; doc-lint takes about a minute). Alternative: one always-triggered workflow with a change-detection job and `if:`-skipped jobs (a skipped job satisfies a required check). Keep the four job names **byte-identical**; update the header comments of both workflows. | ci | 378 | PR-D | — | [ ] | A docs-only PR and a code-only PR both report all four checks; job names unchanged |
| S19-29 | **SHA-pin every action** (`actions/checkout`, `actions/setup-python`) to a full commit SHA with a `# vX.Y.Z` comment, in both workflows. | ci | 378 | PR-D | — | [ ] | `grep -n 'uses:'` shows only 40-hex SHAs; CI green |

### Release v0.19.0

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-30 | **Bump + release notes.** `version = "0.19.0"` in `pyproject.toml` **and** `__version__` in `src/revolver/__init__.py`; CHANGELOG `Unreleased` → `[0.19.0] — <date>` (CHANGELOG introduced, journal relocated, contributor process, CI on GitHub-hosted runners, LICENSE, SHA-pinned workflows); README refresh (test count line, docs section); `verified-against: v0.19.0` on `docs/guides/*.md` and `docs/specs/user-story-e2e.md` after re-verification. Optional step 0 cascade: validation-reviewer on the validation.md edit of S19-23 only (no spec change this sprint). | release | 380 | release commits on `develop` | PR-A, PR-B, PR-C, PR-D merged | [ ] | Both version files = `0.19.0`; freshness test green; doc-lint green |
| S19-31 | **`develop` → `main` + tag** `v0.19.0` (annotated; message summarises the CHANGELOG section) — **owner GO**. | release | 380 | — | S19-30 | [ ] | `version-check` job green on the tag push; tip of `main` is the merge commit |
| S19-32 | **Install check + post-release verification** (Release Checklist steps 6–7 as amended by PR-A): install from the GitHub URL (authenticated if still private), `revolver --version`; tag exists; both version files match; CHANGELOG section present; backlog updated; journal entry written (maintainer). | release | 380 | — | S19-31 | [ ] | All step-7 checks pass and are reported |
| S19-33 | **Post-release doc-reviewer** (README, guides, CHANGELOG, CONTRIBUTING version mentions); fix FAIL/WARN on `develop`. | doc | 380 | fix commits | S19-32 | [ ] | doc-reviewer 0 FAIL |

### Task-D — operations: switch to public + settings (GH #278, no PR)

| # | Task | Layer | Backlog | PR | Depends | Status | Acceptance criteria |
|---|---|---|---|---|---|---|---|
| S19-34 | **Pre-flip gate.** (a) PR-A/B/C/D merged and v0.19.0 released (S19-30..33); (b) the external contributor's commits re-authored (identity rewrite, coordinated with the contributor) **or** the contributor's branches removed — **caveat**: a PR keeps its head ref and its force-push timeline, so superseded commits stay reachable by SHA through the PR even after a force-push or branch deletion; if the identity exposure matters, close the affected PRs and request a GitHub Support purge before the flip; (c) audit commands re-run on `main` and `develop`; (d) GitHub-side worklist done (S19-15); (e) **history-exposure decision** recorded: files removed from the tree (journal, cleaned lines) remain in git history once public — recommended: accept (the audit found no secrets); alternative: history rewrite before the flip (invalidates SHAs and tags, forces a re-tag). | ops | 379 | — | S19-15, S19-33 | [ ] | All five items ticked in issue #278 |
| S19-35 | **Visibility flip** private → public. | ops | 379 | — | S19-34 | [ ] | Anonymous `git clone` works |
| S19-36 | **Rulesets.** Branch ruleset on `develop` and `main`: PR required, required status checks = exactly `Lint (ruff + mypy)`, `Test (pytest + coverage) (3.12)`, `Test (pytest + coverage) (3.14)`, `Doc command-lint (fenced CLI invocations)` (set by name; verify on a throwaway PR), block force-push and deletion. Tag ruleset on `v*`: creation/update/deletion restricted. **Bypass decision**: the maintainer's current practice commits doc cascades and backlog updates directly on `develop` and merges `develop` → `main` locally (Release Checklist step 4) — either grant the maintainer an "always" bypass, or switch those to PRs and amend the Release Checklist (release PR `develop` → `main`) in a follow-up commit. | ops | 379 | — | S19-35, S19-28 merged | [ ] | A throwaway PR shows the four required checks and is blocked until they pass; direct push to `main` rejected for non-bypass actors; tag push by a non-bypass actor rejected |
| S19-37 | **Security features**: secret scanning + push protection; Dependabot alerts + Dependabot security updates; private vulnerability reporting (target of `SECURITY.md`). | ops | 379 | — | S19-35 | [ ] | All five toggles on in the repository security settings |
| S19-38 | **Actions policy**: fork-PR workflow approval = `all_external_contributors`; `allowed_actions = selected` (GitHub-owned actions + any explicitly listed ones, SHA-pinned per S19-29); default `GITHUB_TOKEN` permission read-only. | ops | 379 | — | S19-35, S19-29 merged | [ ] | A fork PR waits for approval; a non-allowed action would fail |
| S19-39 | **Repository settings**: `delete_branch_on_merge = true`; description + topics; stale merged branches deleted; collaborators restored to `write` **only together with** the rulesets (S19-36). | ops | 379 | — | S19-36 | [ ] | No merged branch left; collaborator permissions match the plan |
| S19-40 | **Optional — GitHub Releases** for recent tags (at least v0.19.0, optionally v0.17.0…v0.18.0), body copied from the CHANGELOG section; **anonymous install check** from the public GitHub URL. | ops | 379 | — | S19-35 | [ ] | `pip install "revolver @ git+https://github.com/<owner>/revolver@v0.19.0"` works without credentials; `revolver --version` → `0.19.0` |

---

## PR Mapping

| PR | GitHub issue | Backlog | Tasks | Files (primary) | Wave |
|---|---|---|---|---|---|
| **#274** (merged) | #272 | 372 | S19-01 | `.github/workflows/{ci,doc-lint}.yml`, `.github/runner/` (removed), `LICENSE` | 0 |
| **PR-A** | #275 | 373 | S19-02..08 | `docs/sessions/*` (removed) + `docs/sessions/README.md`, `CHANGELOG.md`, `AGENTS.md`, `CLAUDE.md`, `.gitignore`, `README.md` | 1 |
| **PR-B** | #276 | 374 (+375 ops) | S19-09..14 (+S19-15 ops) | docs per audit list (living docs, `.claude/`, `docs/sprints/*`, `docs/tasks/backlog.md`, `docs/analysis/*`), two comments under `src/revolver/` | 2 |
| **PR-C** | #277 | 376, 377 | S19-16..27 | `CONTRIBUTING.md`, `SECURITY.md`, `.github/{PULL_REQUEST_TEMPLATE.md,ISSUE_TEMPLATE/,CODEOWNERS,dependabot.yml}`, `.claude/agents/code-reviewer/agent.md`, `.claude/skills/session-close/SKILL.md`, `docs/validation/validation.md`, `pyproject.toml` (`addopts`, if adopted), `tests/unit/test_doc_command_lint.py`, `CLAUDE.md` + `README.md` + `AGENTS.md` (index lines only) | 2 |
| **PR-D** | #278 (refs) | 378 | S19-28..29 | `.github/workflows/ci.yml`, `.github/workflows/doc-lint.yml` | 1–2 (independent) |
| release commits | — | 380 | S19-30..33 | `pyproject.toml`, `src/revolver/__init__.py`, `CHANGELOG.md`, `README.md`, guide front-matter | 3 |
| operations | #278 | 375, 379 | S19-15, S19-34..40 | GitHub settings only | 4 |

---

## Integration Tests (L2)

No new product behavior → **no new L2 scenario** in `val-integration-tests.md`. The sprint is validated by the doc guards, one new unit test and full-suite regression, plus GitHub-side checks.

| Area | Scenario | Test ID | Status |
|---|---|---|---|
| Doc command-lint | Corpus (README + `docs/**` + root contributor docs) resolves after the journal removal and the new files | `test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_invocations_resolve` | Planned |
| Doc command-lint corpus | `CONTRIBUTING.md` / `AGENTS.md` included, `CHANGELOG.md` excluded | `test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_includes_contributor_docs` (new, S19-26) | Planned |
| Doc freshness | Guides + `user-story-e2e.md` stamped `v0.19.0` | `test_doc_freshness::TestDocFreshnessCorpus::test_corpus_is_stamped_and_fresh` | Planned |
| Strict markers (if adopted) | Full suite passes with `--strict-markers` | full-suite run (S19-23) | Planned |
| Non-regression | Full suite at the S18 baseline (1585 passed / 4 skipped, no-shinka env); ruff / mypy clean | full-suite regression | Planned |
| CI reachability | Docs-only PR and code-only PR both report all four required checks | manual check on throwaway PRs (S19-28, S19-36) | Planned |
| Release guard | `version-check` passes on the `v0.19.0` tag | CI job on tag push (S19-31) | Planned |

---

## Parallelization

### Dependency graph

```
S19-01 (CI GitHub-hosted + LICENSE)  [DONE, PR #274]
   │
   ├──> PR-D  S19-28 (path-filter trap) ─┬─ S19-29 (SHA pins)      ← independent, may start now
   │                                     │
   │   maintainer export of the journal  │
   │          │                          │
   └──> PR-A  S19-02 → S19-03 → S19-04 → S19-05 → S19-06 → S19-07 → S19-08
              (S19-03/04/06 parallel inside the PR; S19-05 after 03+04; S19-07 after 03)
                     │ merged
          ┌──────────┴───────────────────────────┐
          ▼                                      ▼
   PR-B  S19-09..13 → S19-14             PR-C  S19-16 → S19-17, S19-18, S19-25, S19-26, S19-27
          │ (merge FIRST)                        S19-19, S19-20, S19-21, S19-22, S19-23, S19-24 (parallel)
          │                                      │ (rebase on PR-B, merge SECOND)
          └──────────────┬───────────────────────┘
                         ▼
          Release  S19-30 → S19-31 (owner GO) → S19-32 → S19-33       (needs PR-D merged too)
                         │
                         ▼
          S19-15 (GitHub-side worklist, switch day) → S19-34 (pre-flip gate)
                         │
                         ▼
          S19-35 (flip) ──┬──> S19-36 (rulesets) → S19-39 (settings, collaborators)
                          ├──> S19-37 (security features)
                          ├──> S19-38 (Actions policy)
                          └──> S19-40 (optional Releases + anonymous install)
```

### Waves

| Wave | Content | Gate to open |
|---|---|---|
| 0 | S19-01 (done) | — |
| 1 | PR-A; PR-D in parallel | PR-A: maintainer confirms the journal export. PR-D: none |
| 2 | PR-B ∥ PR-C (developed in parallel, **merged B then C**) | PR-A merged |
| 3 | Release v0.19.0 | PR-A, PR-B, PR-C, PR-D merged |
| 4 | Switch to public + settings | release done (recommended order), S19-15 + S19-34 done |

**Release before flip (recommended).** The public repository then opens on a tagged, CHANGELOG-documented state with the hardened workflows already on `main`. Consequence: the S19-32 install check runs authenticated; the anonymous install check is repeated after the flip (S19-40). Rulesets are configured after the flip (they need a public repository on the current plan), so v0.19.0 is not affected by the S19-36 bypass decision; v0.20.0 is.

### Critical path

```
maintainer journal export → PR-A (S19-02..08) → PR-B (S19-09..14) → PR-C rebase + merge
   → S19-30 → S19-31 → S19-32 → S19-15 → S19-34 → S19-35 → S19-36 → S19-39
```

PR-C is usually the largest PR; it overlaps PR-B in time and only its merge sits on the critical path.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Restructuring | S19-02..08 | journal export confirmed | Agent 1 |
| D — Workflow hardening | S19-28..29 | now | Agent 2 (small) |
| B — Content cleanup | S19-09..14 | PR-A merged; audit list handed to the agent **outside the repository** (prompt only, never committed) | Agent 1 |
| C — Contributor process | S19-16..27 | PR-A merged | Agent 2 or 3 |
| R — Release | S19-30..33 | A, B, C, D merged | main session (owner GO) |
| O — Operations | S19-15, S19-34..40 | release done | maintainer |

Peak parallelism: **2 agents** (wave 2: B ∥ C, with D finished earlier or alongside).

### Conflict map

| File / area | Touched by | Resolution |
|---|---|---|
| `CLAUDE.md` | PR-A (index, checklist, phase, release checklist), PR-B (only if the audit list still hits it after PR-A), PR-C (index rows for contributor files) | Merge order **A → B → C**. PR-C limits itself to adding index rows; PR-B touches CLAUDE.md only for audit hits. |
| `README.md` | PR-A (release table, docs section), PR-B (audit hits only), PR-C (contributing/security links), release (test count, docs) | Same order **A → B → C → release**; PR-C edits only the docs/contributing lines. |
| `AGENTS.md` | PR-A (creates), PR-C (activates the CONTRIBUTING pointer) | Sequential by construction. |
| `CHANGELOG.md` | PR-A (creates), PR-B / PR-C / PR-D (one `Unreleased` line each), release (promotes `Unreleased`) | Trivial append conflicts; resolve at rebase. |
| `docs/validation/validation.md` | PR-B (audit hits, if any), PR-C (tooling sections, S19-23) | B first; C rebases. |
| `.claude/agents/*`, `.claude/skills/session-close/SKILL.md` | PR-B (audit hits), PR-C (S19-22, S19-24) | B first; C rebases. **Window**: between PR-A and PR-C merges the skill still targets `docs/sessions/` — do not run `/session-close` in that window (or fold S19-24 into PR-A if PR-C slips). |
| `docs/tasks/backlog.md`, `docs/sprints/*` | PR-B (neutralization), orchestrator progress commits | Avoid backlog/sprint progress commits on `develop` while PR-B is open, or have PR-B rebase last-minute. |
| `.github/` | PR-C (new files: templates, CODEOWNERS, dependabot), PR-D (workflows) | Disjoint files — parallel-safe. |
| `tests/unit/test_doc_command_lint.py` | PR-C only | — |
| `src/revolver/` (two comments) | PR-B only | — |
| Required-check names | PR-D must keep them byte-identical; S19-36 depends on them | Any rename forces a ruleset update — avoid. |

---

## Exit Criteria

The sprint is complete when ALL of the following hold:

1. **CI + LICENSE** — S19-01 merged (done).
2. **Journal out** — `docs/sessions/` holds only `README.md`; CLAUDE.md checklist and the `/session-close` skill reference the private journal through `CLAUDE.local.md`; `CLAUDE.local.md` is gitignored; contributors are told they write no session reports and keep a PR "Status" section instead.
3. **CHANGELOG** — `CHANGELOG.md` has `Unreleased` (empty after release) and one section per release v0.1.0 … v0.19.0; README points to it; the Release Checklist names it as the release-note vehicle.
4. **Clean content** — the audit commands return nothing beyond the known test dummies on `main` and `develop`; the GitHub-side worklist is done; no committed file (including this sprint file and the backlog) breaks the public-file rule.
5. **Contributor process** — CONTRIBUTING, PR template, three issue templates, CODEOWNERS, SECURITY and dependabot are on `main`; the §4.5 drift is fixed (code-reviewer ADR range, validation.md tooling vs pyproject, `--strict-markers` decided, `/session-close` aligned); the dev-process analysis is either kept out of the repository or committed sanitized.
6. **CI fit for rulesets** — every PR reports the four required checks (path-filter trap resolved); all actions SHA-pinned.
7. **Released** — v0.19.0 tagged on `main`, both version files match, `version-check` green, stamps at `v0.19.0`, install from the GitHub URL works, post-release doc-reviewer 0 FAIL.
8. **Public and locked down** — repository public; rulesets on `develop`, `main` and `v*` tags active with the four required checks and a recorded bypass decision; secret scanning + push protection, Dependabot alerts/security updates and private vulnerability reporting on; fork-PR approval for all external contributors; `allowed_actions = selected`; `delete_branch_on_merge`; collaborators back to `write`; anonymous install of v0.19.0 verified.
9. **Zero regression** — full suite green at the S18 baseline (1585 passed / 4 skipped, no-shinka env; +1 new unit test); ruff / mypy clean; CI green on GitHub-hosted runners.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Superseded commits stay reachable through PR refs** after an identity rewrite or branch deletion. | Medium | S19-34 (b) caveat: close the affected PRs and request a GitHub Support purge if the exposure matters; decide before the flip. |
| **Removed files remain in git history** once public. | Medium | S19-34 (e) explicit decision; the audit found no secrets; a history rewrite remains possible only before the flip. |
| **Path-filter trap** blocks every PR once rulesets are on. | High (if missed) | S19-28 merged before S19-36; verify with a docs-only and a code-only throwaway PR. |
| **Rulesets block the maintainer's direct-to-`develop` and local `develop` → `main` habits.** | Medium | S19-36 bypass decision; amend the Release Checklist if PR-only is chosen. |
| **Audit details leak into the repo** through the cleanup PR itself (commit messages, PR description, a "list of what was removed"). | Medium | The audit list is passed to the agent out-of-band; commit messages stay generic ("Neutralize local paths in living docs"); verification results go in the PR description in generic terms. |
| **CHANGELOG seeding is lossy** (early sprints have thin reviews). | Low | Seed from the README table as the floor; enrich from sprint reviews where available; accuracy over completeness. |
| **`--strict-markers` reveals an unregistered marker** and reddens the suite. | Low | S19-23 verifies before adopting; fallback is the documentation-only alignment. |

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- _X passed / Y skipped (no-shinka env); doc guards; CI on GitHub-hosted runners._

### Demo-able features
- [ ] Anonymous clone + install of v0.19.0 from the public GitHub URL
- [ ] `CHANGELOG.md` covering v0.1.0 … v0.19.0
- [ ] `docs/sessions/` reduced to a README pointer
- [ ] Issue chooser with feature / new-backend / bug templates; PR template pre-filled
- [ ] Fork PR gated by approval, then by the four required checks
- [ ] Security features on (secret scanning, push protection, Dependabot, private vulnerability reporting)

### Carry-over
- LoongFlow backend (GH #273, external PRs #270/#271) → Sprint 020 / v0.20.0
- Documentation shrink step 2 (backlog 381–383, #357) → unscheduled S20+
