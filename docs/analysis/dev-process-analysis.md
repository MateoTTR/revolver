# Revolver — Development Process Analysis (as practiced, v0.18.0)

> **Sanitized copy (committed at v0.19.0).** This analysis was written on the maintainer's side at v0.18.0, before Sprint 019 restructured the process; it is the evidence behind [ADR-008](../architecture/adr/ADR-008-documentation-and-process-strategy.md). GitHub handles of third parties, hostnames, local paths and personal data were removed; the analysis itself is unchanged. `file:line` citations refer to the v0.18.0 tree — `CLAUDE.md` has since been replaced by `AGENTS.md` and `docs/process/`, the journal left the repository, and `.claude/` is no longer versioned.

**Repo**: branch `develop` at `9fba2cb` (v0.18.0 plus three documentation commits), analysed 2026-10-23 (read-only; GitHub reads only).
**Purpose**: faithful description of the process, explicit/implicit rules catalog, Definition of Done (feature PR + new evolution backend), gaps for external contributors (Gemini CLI, no Claude agents/hooks). Feeds a future `CONTRIBUTING.md`, PR template and the gap review of PRs #270/#271.
**Citation style**: `file:line` relative to the repo root; `observed in PR #N / sprint-0NN` for practice not written down. Anything not written in a project file is tagged **implicit (observed)**.

---

## 1. Lifecycle as practiced (idea → release)

| # | Step | Who / what performs it | Artifacts produced | Automated guards | Source |
|---|---|---|---|---|---|
| 1 | **Idea intake → backlog entry.** Every piece of work gets a numbered row in the backlog (global counter, never reused; `[ ]`/`[x]`/`[~]` status; Sprint/PR/session reference column). Demo feedback arrives as "Demo-surfaced" sections and triage docs in `docs/analysis/`; investigations are sequenced *spike → analysis → ADR → specs → sprint* ("do NOT write ADRs/specs before the spike"). | The maintainer + the maintainer's AI-assistant session | `docs/tasks/backlog.md` rows; `docs/analysis/*.md` (spikes `shinka-spike-266.md`, `spike-320-*`, triage `triage-feedback-v017.md`) | none | backlog.md:393-407 (tasks 266-268), :482-491, :576-603; CLAUDE.md:21 |
| 2 | **Sprint planning.** Scrum-master agent drafts `docs/sprints/sprint-NNN.md`: Status/Target release/Goal/Demo/Source/Predecessor header, Scope in/out, "Verified facts" (code recon with file:line), Tasks table `SNN-xx` (Layer, Backlog #, PR, Depends, Acceptance criteria), Integration Tests (L2) with **Test IDs declared up front**, PR Grouping, Parallelization (dependency graph, critical path, parallel streams, conflict risks, recommended merge order), Exit criteria, Release note, Risks, empty Sprint Review. S18 planning used 10 agents: 5 recon briefs → scrum-master → 3 adversarial plan reviewers. | scrum-master agent + owner arbitration ("Scope arbitrated by the maintainer") | `docs/sprints/sprint-NNN.md`; backlog rows re-pointed to the sprint | none (review by agents, not CI) | scrum-master/agent.md:85-166, :168-217; sprint-018.md:1-8, :62-70, :74-115, :138-162, :166-178, :182-254, :258-272; session-058.md:10-20 |
| 3 | **Spec-before-code cascade** (since S17/session 055). Before implementation PRs: allocate next free FR numbers, edit specs/DES/ADR/validation docs (parallel per-document editor agents), run **spec-reviewer** then **validation-reviewer**, fix all FAIL/WARN, commit directly on `develop`. Test IDs for the sprint are added to `val-integration-tests.md` and the traceability matrix as `Planned` rows. | Main session + spec-reviewer + validation-reviewer agents | `docs/specs/*.md` (new FRs, amendments), `docs/architecture/design/DES-*.md`, ADR amendments, `docs/validation/*.md` (rows `Planned`), one commit on `develop` (e.g. `71b85f9`) | none in CI (docs are `paths-ignore` in ci.yml) — only the two reviewer agents | sprint-018.md:118-134; sprint-017.md:132-137; session-055.md:21,37-38; session-058.md:22-29; CLAUDE.md:139-143 (same cascade as release step 0) |
| 4 | **GitHub issue per PR = single source of truth.** Body shape observed: Context (sprint, ADR phase, task range) · "Read first" (sprint file sections, ADR decisions, analysis §, source files) · Scope per task · Out of scope · Acceptance criteria (full suite unmodified, ruff/format/mypy, coverage ≥80, counts) · Dev env (owner's conda envs) · References (ADR/FR/DES/sprint) · Claude footer. | Main session (`gh issue create`) | GitHub issue #N | none | CLAUDE.md:174; observed in issues #190, #191 |
| 5 | **Worktree dev agent.** Reads the issue + docs, implements on `feature/sNN-<topic>`, runs tests, commits (imperative English), **pushes**, stops. It must **not** run `gh pr create` (PRs created in a subagent miss the review hook). "Commit before pausing" discipline saved work twice when agents died. | Claude worktree agent | branch `feature/s18-pr1-u13-timeout-semantics` style; commits | none | CLAUDE.md:175, :130; session-058.md:55-59,63; session-059.md:93-95 |
| 6 | **Draft PR from the orchestrator.** `gh pr create --draft`, title `S18 PR-1: <topic> (#backlog)`, body: `Closes #issue` first line, Summary/Commits/What it does, Tests (counts, ruff/format/mypy clean, coverage), Deviations, Merge order, Claude footer. Draft prevents CI (jobs skip drafts). | Main session (owner's `gh` identity) | PR (draft) | ci.yml draft guard :30-32,:126-128; doc-lint.yml:34-35 | CLAUDE.md:176; observed in PRs #184/#185/#188/#192/#193/#197/#257/#264/#268; 38/40 last merged PRs carry `Closes #N` |
| 7 | **Code review agent.** PostToolUse hook on any Bash command containing `gh pr create` injects "Launch the code-reviewer agent…"; the agent (run foreground) reads CLAUDE.md, the diff and whole files, applies a checklist (functionality, layer separation `cli→core→infra`, exceptions, parameterized SQL, ADR compliance, docstrings, markers), classifies CRITICAL/WARNING/SUGGESTION/GOOD and posts a PR review (`REQUEST_CHANGES` if any CRITICAL) via MCP or `gh pr comment` fallback. | code-reviewer agent (Opus), under the owner's GitHub token | PR review/comment "Code Review — PR #N" | hook only fires in the owner's Claude Code session | .claude/settings.json:7-18; CLAUDE.md:177; code-reviewer/agent.md:19-28,:30-75,:77-84,:86-103,:126-134 |
| 8 | **Fix & ready.** Findings addressed in-PR ("Address PR #N review findings" commits), pushed, then `gh pr ready` → CI runs. **Implicit rule: 0 CRITICAL before ready; every WARNING fixed or explicitly carried over** (consistently reported in every sprint review). | Main session / dev agent | fix commits; PR marked ready | ci.yml `ready_for_review` trigger :14 | CLAUDE.md:178; sprint-013.md:150; sprint-014.md:282; sprint-017a.md:307; sprint-018.md:308 — **implicit (observed)** |
| 9 | **CI.** `ci.yml`: Lint (ruff check, ruff format --check, mypy strict) + Test matrix Python 3.12/3.14 (`pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"`) + non-blocking L2-OE step (3.12) + version/tag job on `v*` tags. `doc-lint.yml` covers the paths ci.yml ignores (`**.md`, `docs/**`): doc command-lint + freshness stamps. All jobs `runs-on: [self-hosted, linux, x64]`; concurrency cancels superseded runs. | GitHub Actions on the owner's 3 ephemeral Docker runners | check runs | the gates themselves | ci.yml:3-23,:26-73,:75-120,:122-181; doc-lint.yml:1-35,:68-71; .github/runner/Dockerfile, docker-compose.yml |
| 10 | **Merge.** The owner merges on GitHub after CI is green (merge commits `Merge pull request #N from <owner>/feature/...`). Never `gh pr merge`/`git merge` to main/tag/bump without the owner's go-ahead. Backlog rows then get the PR number ("Mark S14 PR-A tasks done"). | Owner | merge commit on `develop`; backlog update commit | none technical (no branch protection — see §4) | CLAUDE.md:133,:179; `git log --merges`; commits `12d7840`, `ea0548d` |
| 11 | **Sprint review.** Fill `## Sprint Review` in the sprint file: tests passing (counts, coverage, review tallies), demo-able features checklist, carry-over → next sprint's "Source". | scrum-master or main session | sprint file §Sprint Review | none | scrum-master/agent.md:153-166,:234-238; sprint-013.md:142-165; sprint-018.md:301-332 |
| 12 | **Release checklist.** (0) optional doc cascade spec-reviewer → validation-reviewer; (1) bump `version` in **both** `pyproject.toml` and `src/revolver/__init__.py`; (1b) README refresh (features, release table, extras, test counts, "Behavior changes" subsection) + re-verify guides and `user-story-e2e.md` and refresh `verified-against: vX.Y.Z` stamps; (2) all sprint PRs merged; (3) commit+push on develop; (4) merge develop→main; (5) annotated tag on main; (6) install from tag + `revolver --version`; (7) post-release checks; then **doc-reviewer** (post-release, checks versions). CI version-check job fails a tag whose version differs from both files. | Owner GO + main session + doc-reviewer | bump commit, merge commit on main, tag `vX.Y.Z`, README/guides edits | ci.yml:75-120 (tag ↔ versions); tests/unit/test_doc_freshness.py:57-118 (stamp ≤ 1 minor behind) | CLAUDE.md:135-157; session-059.md:68-84,:109-115; sprint-018.md:276-282 (release-note landing artifacts) |
| 13 | **Session close.** Session report `docs/sessions/YYYY-MM-DD-session-NNN.md` (Duration, Tokens, Phase, Focus; What was done; Incidents & lessons; Carry-over), cost-tracker row + totals, backlog update; commit `Close session NNN: …` after user validation. | Main session (`/session-close` skill) | session report, cost-tracker row, backlog | none | CLAUDE.md:92-96; .claude/skills/session-close/SKILL.md:12-77; session-059.md:1-7; cost-tracker.md:1-8 |
| 14 | **Hotfix variant.** `hotfix/vX.Y.Z` off `develop`, fix + tests, draft PR, code review, ready, owner merges, release checklist. Sprint "017a" shows a corrective sprint run under the hotfix process with a full sprint file. | same actors | `docs/sprints/sprint-0NNa.md` | same CI | CLAUDE.md:159-168; sprint-017a.md:4,:289-297 |

**Backend precedent (S13/S14, v0.12.1→v0.14.0)** — the "adding a backend" path was: spike #266 + top-down analysis #267 → ADR-007 (D1-D6) → spec/DES/validation cascade with both reviewers (`528f5c1..f26069a`) → sprint-013 (abstraction, zero behavior change, 4 PRs, waves A+B ∥, then C+D) → sprint-014 (Shinka MVP, 4 PRs: fixtures+extra+contract tests first, then config tier, engine tier, shims+E2E) → doc-reviewer post-release. 75 files changed (`git diff --stat v0.12.1..v0.14.0`): `src/revolver/infra/backends/{__init__,base,openevolve,shinka}.py`, `core/{run,doctor,setup,project,problem}.py`, `cli/{run,doctor,setup,project,problem}.py`, `infra/db.py` (v9), `models/run.py`, `pyproject.toml`, `tests/unit/infra/test_backends.py`, `tests/unit/infra/test_shinka_backend.py`, `tests/unit/test_db_migration_v9.py`, `tests/integration/{test_run,test_run_shinka,test_shinka_db,test_shinka_wrapper,test_doctor,test_setup,test_problem}.py`, `tests/e2e/test_shinka_backend.py`, `tests/fixtures/{programs_sqlite,shinka_evaluate_py,fake_llm_server}.py`, `tests/conftest.py` (`no_shinka`), plus ADR-006/007, architecture.md, DES-001/005/006, conops, spec-{run,llm,problem,project,setup}, specifications.md, user-story-e2e, validation.md, val-integration/val-e2e, traceability, README, CLAUDE.md, backlog, sprint-013/014, 3 session reports. Sources: backlog.md:393-451; sprint-013.md:1-165; sprint-014.md:1-310; session-048.md:26-27.

---

## 2. Rules catalog

E = explicit (written in a project file); I = implicit (observed in practice, not written as a rule).

| # | Rule | E/I | Source | How to check |
|---|---|---|---|---|
| R1 | Git Flow: `main` (tagged releases), `develop` (PR target), `feature/*`, `release/*`, `hotfix/*` | E | CLAUDE.md:127-131 | `gh pr view N --json baseRefName` == `develop`; branch name matches `^(feature\|hotfix\|release)/` |
| R2 | Feature branch naming `feature/s<NN>-<pr-or-topic>` tied to the sprint (`feature/s13-backends-package`, `feature/s18-pr1-u13-timeout-semantics`); hotfix `hotfix/vX.Y.Z` | I | observed in all 40 last PRs; CLAUDE.md:130 gives only `feature/s1-scaffold-ci` as example; CLAUDE.md:163 | regex `^feature/s[0-9]+[a-z]?-` |
| R3 | Commit messages: English, imperative mood (`Add`, `Fix`, `Address`, `Bump`, `Close`, `Plan`, `Mark`); review fixes as `Address PR #N review findings` | E (+I for verbs) | CLAUDE.md:126; `git log` histogram (Add 34, Address 23, Fix 13, Close 7, Bump 7) | `git log --format=%s origin/develop..HEAD` first word is an imperative verb |
| R4 | PR title `S<NN> PR-<X>: <summary> (#<backlog>)`; sprint-free PRs still prefixed (`S18 R2:`) | I | observed in PRs #184-#269 | title regex `^S[0-9]+[a-z]? (PR-[A-Z0-9]+\|R[0-9]+\|W[0-9]+[a-z]?):` |
| R5 | PR body starts with `Closes #<issue>`; sections Summary / Tests (counts, ruff+format+mypy clean, coverage) / Deviations / Merge order | I | observed in PRs #184,#185,#188,#192,#193,#197,#257,#264,#268; 38/40 merged PRs | `gh pr view N --json body --jq .body \| grep -E '^Closes #[0-9]+'` |
| R6 | One GitHub issue per PR, created before dev, holding scope/files/acceptance/test scenarios/DES-spec refs | E | CLAUDE.md:174 | `Closes #N` resolves to an issue with Scope + Acceptance criteria sections |
| R7 | PR is created **draft-first** by the orchestrator, not by the dev agent; `gh pr ready` only after review fixes | E | CLAUDE.md:175-178 | PR timeline shows `convert_to_draft`/ready events; checks start only after `ready_for_review` |
| R8 | **0 CRITICAL** in code review before ready; WARNINGs fixed in-PR or carried over explicitly in the sprint review | I | sprint-013.md:150; sprint-014.md:282; sprint-017a.md:307; sprint-018.md:308; code-reviewer/agent.md:81,:98 | last review on the PR has no `**CRITICAL**` finding; verdict ≠ REQUEST CHANGES |
| R9 | Owner merges; `gh pr merge`, merge to `main`, `git tag`, version bumps need explicit owner approval | E | CLAUDE.md:133,:179 | merge commit author is the owner; no tags/bumps in contributor PRs |
| R10 | CI gates: `ruff check src/ tests/`, `ruff format --check src/ tests/`, `mypy` (strict), pytest `-m "unit or integration"` with `--cov-fail-under=80`, on Python 3.12 **and** 3.14 | E | ci.yml:63-69,:132,:170; pyproject.toml:62-68,:86-92 | run the four commands locally; `mypy` has no path arg (uses `packages = ["revolver"]`) |
| R11 | Coverage targets per layer: overall ≥80 %, core ≥90 %, infra ≥75 %, models ≥95 % (only the 80 % is enforced) | E | validation.md:154-164; pyproject.toml:92 | `pytest --cov=revolver --cov-report=term-missing` |
| R12 | Layer rule: `cli/` → `core/` → `infra/`, never reversed; CLI never touches SQLite; core never formats output | E | architecture.md:102; code-reviewer/agent.md:42 | Reverse direction must stay empty: `grep -rn "from revolver.cli" src/revolver/core src/revolver/infra src/revolver/models`; review question for new CLI code: no SQL, no business logic. Tolerated existing `cli → infra` imports: `infra.output` (rendering), `infra.backends.base.AVAILABLE_BACKENDS` (help text), `infra.db` connection helpers, `infra.ollama.OllamaClient` (cli/llm.py:20-22) |
| R13 | Exceptions inherit `RevolverError` hierarchy; exit codes 0-4 (1 general, 2 integrity, 3 resource, 4 external) | E | specifications.md:149-157; code-reviewer/agent.md:37,:44 | new error paths map to the table; `BackendUnavailableError.exit_code == 3` (base.py:304) |
| R14 | Test markers: `unit` (L1), `integration` (L2), `openevolve`, `shinkaevolve` (engine contract tests, importorskip + non-blocking), `e2e` + `slow` (L3, deselected by default via `addopts = "-m 'not e2e'"`) | E | pyproject.toml:71-84; val-integration-tests.md:480-484; val-e2e-tests.md:224-228 | every new test module has `pytestmark`/decorators; engine modules start with `pytest.importorskip(...)` |
| R15 | Test layout: new L2 suites in `tests/integration/test_<command>.py`; L1 under `tests/unit/{core,infra,models}`; historic top-level `tests/test_*.py` tolerated; a new top-level file only when marker must diverge | E | validation.md:168,:290-316; val-integration-tests.md:460-478 | new test files live in the right directory |
| R16 | **Test IDs are declared in the validation docs** (`val-integration-tests.md` rows + traceability `Planned` rows) **before** implementation, then flipped to `Implemented` at release; ID form `integration/test_x::test_y` | E (pattern) / I (timing) | validation.md:290-316; traceability-matrix.md:22-23; sprint-018.md:138-162; session-059.md:70-79 | `grep -n "<test_name>" docs/validation/*.md` returns a row; status column consistent |
| R17 | Every FR MUST has ≥1 test; SHOULD should; MAY may not; DES refs in the matrix must point to existing headings | E | validation-reviewer/agent.md:60-72 | run the validation-reviewer or grep the matrix for the new FR |
| R18 | FR/NFR numbering: `FR-<GROUP>-NNN`, stable IDs, deleted ones marked `[DELETED]` never renumbered; new FRs take the next free number; amendments are in-place edits of the FR row referencing the sprint/backlog (`(S18 / U4 #369)`) | E (+I for amendment style) | specifications.md:24-47; spec-run.md:346-357 | new FR id not already used (`grep -rn "FR-RUN-058" docs/specs`); row cites ADR/DES |
| R19 | Spec files follow Scope / Commands / Functional Requirements / Error Cases / Dependencies; a new CLI option gets a row in the Commands table + an FR + an Error Cases row | E | specifications.md:49-56; spec-run.md:27,:346,:384-386 | the option appears in all three places |
| R20 | ADR changes are **in-place amendments** (dated "Amendment — vX.Y" section, `**Amended**:` header lines, superseded text struck through and marked "Superseded by…"); a new ADR only for a new decision; ADR template: Context / Decision / Alternatives / Consequences (Positive/Negative/Risks) / References; status table in CLAUDE.md **and** architecture.md §9 kept in sync | E (template, index) / I (amendment style) | ADR-000-template.md; ADR-007:4-7,:128-133,:155-248,:280-283; session-055.md:19; spec-reviewer/agent.md:79-83 | `grep -n ADR- CLAUDE.md architecture.md` statuses equal |
| R21 | DES documents carry `**Version**`/`**Date**`/`**Status**`/`**Traceable to**` headers bumped per sprint; design decisions `DD-NN` sequential; cross-DES references valid | E | DES-005:3-6; DES-001:3-6; traceability-check/SKILL.md:28-33 | header version line mentions the sprint; DD numbering unique |
| R22 | DB migrations: sequential `vN`, forward-only, **one column per migration**, table-presence guard so the global DB no-ops-and-bumps, `CURRENT_SCHEMA_VERSION` bumped, DES-001 §5.N narrative + §8 dict entry, dedicated `tests/unit/test_db_migration_vN.py` (fresh + upgrade + global no-op) | E | DES-001:724-756,:576-593; db.py:32,:803-812; test_db_migration_v14.py:1-18; sprint-018.md:18 | new migration has all five artifacts |
| R23 | Doc freshness: every `docs/guides/*.md` and `docs/specs/user-story-e2e.md` starts with YAML front-matter `verified-against: vX.Y.Z` ≤ 1 minor behind `revolver.__version__` (fresh-major grace); refreshed at release step 1b | E | test_doc_freshness.py:1-32,:57-67,:88-118; CLAUDE.md:145 | `pytest tests/unit/test_doc_freshness.py` |
| R24 | Doc command-lint: every line-initial `revolver …` invocation inside **any** fenced block of `README.md` + `docs/**` must resolve in the Typer tree (subcommands, flags, positional caps); deprecated flags denylisted | E | test_doc_command_lint.py:1-32; doc-lint.yml:1-9 | `pytest tests/unit/test_doc_command_lint.py` |
| R25 | README must be refreshed on `develop` **before** merge to main for user-facing changes: Features block, release/sprint table row, install extras, test counts, "Behavior changes" subsection for default-path changes (no CHANGELOG exists) | E | CLAUDE.md:145; sprint-018.md:276-282; README.md:22-43,:65-75,:209-259,:261-295 | diff README on the release PR |
| R26 | Version lives in **two** files and must equal the tag | E | CLAUDE.md:144,:153; ci.yml:83-120 | `grep version pyproject.toml; grep __version__ src/revolver/__init__.py` |
| R27 | English-only code, comments, identifiers, docs; communication with the owner in French (reviewer agents report in French) | E | CLAUDE.md:114-116; spec-reviewer:87; validation-reviewer:103; doc-reviewer:122 | grep for French in `src/`/`docs/` |
| R28 | File naming: `ADR-NNN-…`, `DES-NNN-…`, `sprint-NNN.md` (+`a/b/c` suffix for corrective sprints), `YYYY-MM-DD-session-NNN.md` | E (+I for `a/b/c`) | CLAUDE.md:118-123; `ls docs/sprints` | filename regex |
| R29 | Backlog task rows: `\| # \| Task \| Status \| Sprint \|`, status `[x]`/`[ ]`/`[~]`, Sprint column `S13 — session 048, PR #184`; completed tasks cite session or PR; numbers unique and sequential | E | traceability-check/SKILL.md:45-48; backlog.md:413-428 | new work has a row; closed rows cite a PR |
| R30 | Sprint file sections (see §1 step 2) incl. Parallelization and Sprint Review | E | scrum-master/agent.md:85-166 | section headings present |
| R31 | Session report + cost-tracker row + backlog update at every session end | E | CLAUDE.md:92-96; session-close/SKILL.md | files exist for the date |
| R32 | Optional backends are **opt-in extras** (`pip install revolver[<name>]`), never pulled by `dev`/test extras; engine version pinned with an upper bound (`>=0.0.7,<0.1`) | E | pyproject.toml:23-33; ADR-007:135-141,:295; NFR-061 specifications.md:129 | `dev` extra list contains no engine package |
| R33 | Backend capabilities are declared in `capabilities()` and **drive validation** (reject unsupported `--selection`, warn map-with-warn, gate `--rank`) — never `if backend == "x"` branches | E | ADR-007:55-58,:204-212; FR-RUN-048 spec-run.md:347; DES-005:788-803; specifications.md:179-183 | grep `backend.name ==` in `core/` (one known seam: sprint-014.md:300) |
| R34 | Neutral run levers get first-class flags mapped per backend; `--config-override` is the escape hatch for backend-exclusive structural keys; `evaluation.*` is Revolver-owned and validated | E | specifications.md:179-183; ADR-007:163-172 | new lever has a flag, not only an override key |
| R35 | Reproducibility is a backend capability (`global_seed`); CLI warns when a seed is requested on a non-capable backend | E | ADR-007:89-95; NFR-024 specifications.md:96 | capability set honestly; `test_seed_warning_on_shinka` row (traceability:386) |
| R36 | Token accounting token-primary; backend chooses proxy (`wants_http_proxy()`) or native (`collect_token_usage()`); no USD | E | ADR-007:65-87 | run record `tokens` populated after a mocked run |
| R37 | Pydantic models frozen where required; SQL parameterized; `from __future__ import annotations`; docstrings Args/Returns/Raises; test names `test_<function>_<scenario>` | E | code-reviewer/agent.md:45-55,:74 | code review checklist |
| R38 | Secrets: API keys only via env-var **names**, never in config snapshots/DB/lineage | E | NFR-050/052 specifications.md:120-122; code-reviewer:64 | grep for literal keys; snapshots carry `api_key_env` |
| R39 | Engine-coupled commands (`run` launch/resume/status/population + doctor/setup/project init/version create shims) get a per-backend test variant; engine-neutral commands tested once | E | validation.md:56-62 | new backend has L2 rows for the coupled commands |
| R40 | Backend engine tests are **not** run in CI; they run manually in an engine-enabled env before release and the PR body states the evidence ("58 shinkaevolve-marked green on real shinka 0.0.7") | E (CI fact) / I (evidence in PR) | validation.md:244; session-059.md:88-89; PR #257 body | PR body cites a real-engine run |
| R41 | Doc-reviewer runs after spec-reviewer and validation-reviewer, post-release, and whenever `src/revolver/cli/*.py` changes | E | doc-reviewer/agent.md:23-38; CLAUDE.md:72 | release report mentions the pass |
| R42 | Commit trailers `Co-Authored-By: Claude …` and PR footer `🤖 Generated with Claude Code` | I (tooling attribution) | `git log -12 --format=%B`; PR bodies | not a rule for humans |
| R43 | "Commit before pausing" — dev agents commit and push partial work; worktrees cleaned after merge | I | session-058.md:63; session-059.md:93-101 | — |
| R44 | Release note for fitness-landscape/default-path changes is mandatory and lands in README + annotated tag | E | sprint-018.md:276-282,:258-271 | README "Behavior changes" subsection present |

---

## 3. Definition of Done

### 3a. Feature PR (any)

1. Backlog row exists (R29) and a GitHub issue exists with scope/acceptance/test scenarios; PR body `Closes #N` (R5, R6).
2. Spec surface updated **before/with** the code: Commands-table row + FR (next free id, MUST/SHOULD) + Error Cases row (R18, R19); affected DES sections amended with header version bump (R21); ADR amended in place if a decision changes (R20).
3. Validation docs: `val-integration-tests.md` rows with Test IDs, traceability rows (`Planned` → `Implemented`), `validation.md`/`val-e2e-tests.md` if levels/CI change (R16, R17).
4. Code respects layers, exceptions/exit codes, typing, docstrings, secrets rules (R12, R13, R37, R38).
5. Tests: L1 + L2 for every new public function/command path, correct markers and directories, engine tests gated by `importorskip` + marker (R14, R15); DB change → migration vN + DES-001 + `test_db_migration_vN.py` (R22).
6. Local gates green: `ruff check src/ tests/`, `ruff format --check src/ tests/`, `mypy`, `pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"`; **no pre-existing test modified** except traced mechanical categories (sprint-013.md:76,:148) (R10, R11).
7. Docs: README features/install/behavior-changes if user-facing (R25); guides/user-story examples lint-clean (R24); any new/changed guide stamped `verified-against` (R23).
8. Draft PR → code review → 0 CRITICAL, WARNINGs fixed or carried over → `gh pr ready` → CI green on 3.12 and 3.14 → owner merge (R7, R8, R9).
9. Post-merge: backlog row closed with PR #, sprint file task `[x]`, carry-over noted (R29, R30).

### 3b. New evolution backend (derived from ADR-007 D1-D6/A1-A5 and what S13/S14 touched)

| Area | Done when | Source |
|---|---|---|
| **Registry & interface** | `infra/backends/<name>.py` implements every `EvolutionBackend` protocol member (`capabilities`, `is_available`, `config_template`, `validate_config`, `build_config`, `resolved_config`, `generate_wrapper`, `validate_seed_metrics`, `launch`, `resume_precheck`, `resume`, `recover_best_from_checkpoint`, `extract_ranked_program`, `read_progress`, `parse_population`, `count_valid`, `count_total`, `count_evolved_children`, `wants_http_proxy`, `collect_token_usage`) plus class attrs `name`, `default_output_subdir`, `wrapper_filename`; inherits `ChildProcessReaperMixin` (or documents why not); added to `AVAILABLE_BACKENDS` **and** the `get_backend()` registry (assert at base.py:818); exported in `backends/__init__.py`; `test_backends.py` conformance tests updated (`AVAILABLE_BACKENDS == (...)` at :120, protocol isinstance at :113-116) | base.py:28,:165,:510-823 (class attrs :534-536); openevolve.py:1746-1751; shinka.py:814-819; DES-005:526-552; ADR-007:46-63 |
| **Capabilities matrix** | `capabilities()` returns honest values for all 8 axes (`global_seed`, `map_elites_cells`, `native_cost_tracking`, `multi_language`, `ensemble_model`, `top_n_extraction`, `selection_strategies`, `per_member_reasoning_effort`); DES-005 §4.6 table gains a column; ADR-007 D1 wording "two implementations" amended | base.py:307-349; DES-005:788-803; ADR-007:48-50 |
| **Config templates / validation** | `config_template()` scaffold parses as YAML and passes `validate_config()`; `project init --backend <name>` and `problem version create --backend <name>` work (help text auto-lists `AVAILABLE_BACKENDS`); `validate_config()` degrades gracefully when the engine is absent; FR-PRJ-005 / spec-problem option row cite the new name | cli/project.py:48-54; cli/problem.py:174-180; spec-project.md:34,:63; spec-problem.md:93 |
| **Doctor / setup** | `doctor` reports the backend via `is_available()`; absent optional backend = INFO with install hint (FR-SET-002); entries in `_BACKEND_CHECK_NAMES` / `_BACKEND_DIST_NAMES`; `setup` lists the extra; L1 `test_doctor.py` + L2 `integration/test_doctor.py` rows; `user-story-e2e.md` doctor transcript updated | core/doctor.py:105-160,:320-323; spec-setup.md:173; sprint-014.md S14-15 |
| **DB / traceability** | `runs.backend` and `problem_versions.backend` are free TEXT (no CHECK) → no migration unless a constraint is added; `run info`/`run list`/dry-run/manifest show the new value (FR-RUN-047); DES-001 §3.1/§3.5 value list and spec-run §5 manifest comment mention it | db.py:46,:94; spec-run.md:346,:397; DES-001 §3.5 |
| **Token accounting (D2)** | Either `wants_http_proxy()=True` (OpenAI-compatible HTTP engine) or `False` + `collect_token_usage()` reading engine-native counts; token-primary, no USD; L2 test asserts tokens stored after a mocked run | ADR-007:65-87; sprint-014.md S14-11/S14-14 |
| **Reproducibility (D3)** | `global_seed` truthful; seed warning when unsupported (NFR-024 row in traceability) | ADR-007:89-95; traceability:386 |
| **Neutral config (D4)** | `build_config()` maps neutral levers (`--iterations`, `--temperature`, `--parallel`, `--rewrite-mode`, `--selection`, `--llm-weight`, `--reasoning-effort`) or map-with-warn via capabilities; `resolved_config()` returns `ResolvedConfig` with engine-only keys in `backend_extras`; `--config-override` unknown-key warning (B9); `evaluation.on_timeout`/`timeout_score` honored in the wrapper (FR-RUN-054 says "on both backends" → amend to "all backends") | ADR-007:97-115,:163-172; spec-run.md:352-354; specifications.md:179-183 |
| **LLM registry projection (D5)** | Projects `LLMEntry`/`EnsembleEntry` (local Ollama + remote) into the engine's model syntax; exports provider env var **names** only; ensembles accepted or rejected per `selection_strategies`; spec-llm projection note extended | ADR-007:117-133; NFR-050; sprint-014.md S14-08 |
| **Dependency extra (D6)** | `[project.optional-dependencies] <name> = ["<pkg>>=x,<y"]` with upper bound; never in `dev`; `is_available()` import probe + `_INSTALL_HINT`; exit 3 when selected but absent; README install block + NFR-061 example | pyproject.toml:23-33; shinka.py:88,:834-840; README.md:73-74; ADR-007:135-141,:295 |
| **CLI** | `run --backend <name>` works with the `None` sentinel resolution (explicit > version > default) and mismatch warning; `solution extract --rank/--program-id` gated on `top_n_extraction`; help wording lists the backend | cli/run.py:44-54; core/solution.py:438; spec-run.md:27,:346 |
| **Wrapper evaluator + L2 contract track** | `generate_wrapper()` bridges `evaluate_instance()` to the engine contract, emits `instances_valid`/`instances_total`, distinct timeout branch; contract tests (`tests/integration/test_<name>_wrapper.py`, `test_run_<name>.py`, `test_<name>_db.py` or equivalent) with module-level `pytest.importorskip` + `@pytest.mark.integration` + `@pytest.mark.<name>` (marker registered in pyproject); a `no_<name>` conftest fixture for "not installed" tests; fixtures under `tests/fixtures/`; L1 suite runnable **without** the engine; L3 scenario in `tests/e2e/` (`e2e`+`slow`) against the fake LLM server | FR-RUN-053 spec-run.md:352; val-integration-tests.md:24-48,:480-484; val-e2e-tests.md:129-147; tests/conftest.py:14-23; pyproject.toml:77-84 |
| **Specs / DES / ADR** | FR-RUN-047/048, FR-SET-002, FR-PRJ-005, FR-PRB-016, FR-SOL-021, NFR-024/061 wording widened to the new backend; DES-005 §4.1-§4.6, §14.1 (selection row), DES-006 §1.3 wrapper table row; architecture.md §1 external deps table + §3 package tree + §8 stack; ADR-007 amendment (same paradigm) **or a new ADR** when the paradigm differs (e.g. non-evolutionary REPL/agentic loop) — ADR-007's "Decision" is scoped to evolution engines sharing the AlphaEvolve `EVOLVE-BLOCK`/`combined_score` conventions (ADR-007:13-21) | DES-005:1684-1702; DES-006:46-63; architecture.md:42-47,:149-153,:406; ADR-007:4-7 (amendment header style) |
| **Validation docs** | validation.md §3 level table gets a `2-<Name>` row and the "Backend matrix axis" text; val-integration §1 scope paragraph + §2 rows + §4 conventions bullet; val-e2e scenario; traceability rows (FR-RUN-047/048, FR-SET-002, NFR-024/061) with the new Test IDs; §13 note | validation.md:47-62; val-integration-tests.md:24-48,:458-484; traceability:386-394,:426 |
| **Guides / README** | New/updated guide stamped `verified-against`; tuning guide gains a per-backend knob section (its structure is backend-neutral + per-backend reference); README features block, install extras, release table, "Why Revolver" narrative, test-count line | test_doc_freshness.py:57-67; docs/guides/tuning-evolution.md:1-9; README.md:22-43,:65-75,:209-259 |
| **Process artifacts** | Backlog rows (investigation/spike → sprint tasks), sprint file (or sprint section) with waves/conflict map/exit criteria, issue per PR, session report; evidence of a **real-engine** run in the PR body (CI does not run engine tests) | backlog.md:393-451; sprint-014.md:67-91; validation.md:244 |

---

## 4. Gaps for external contributors

### 4.1 What depends on the owner's Claude Code tooling

- **Review hook is session-local**: the PostToolUse hook fires only on a `gh pr create` executed inside the owner's Claude Code session (settings.json:14). PRs #270/#271 (opened 2026-10-22 by an external contributor) have **no review** (`reviews: []`). Reviewers (code/spec/validation/doc) are Claude agents (`model: opus`) whose output goes to the owner's terminal in **French** (spec-reviewer:87, validation-reviewer:103, doc-reviewer:122); only the code-reviewer leaves a trace on GitHub.
- **Worktree dev agents, scrum-master, `/session-close`, `/traceability-check`** are Claude-only; issue bodies reference the owner's conda envs (a local conda environment, issue #190 "Dev env"); CLAUDE.md:150 hardcodes a local filesystem path.
- **Spec-before-code cascade** is documented only inside sprint files and session reports (sprint-018.md:118-134; sprint-017.md:132) and as release step 0 (CLAUDE.md:139-143) — nothing tells a PR author which docs to touch.
- **DoD is implicit**: 0 CRITICAL, test IDs in validation docs, `Closes #N`, draft-first, release-note landing — none is written as a contributor rule.

### 4.2 Repository governance (verified via `gh`)

- Repo is **private on GitHub Free**: branch protection returns HTTP 403 ("Upgrade to GitHub Pro or make this repository public"); rulesets are likewise unavailable. Five collaborators: the maintainer as admin, four others with **write** → anyone can push to `develop`/`main`, merge their own PR, or tag.
- Missing files: `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/`, `CODEOWNERS`, `CODE_OF_CONDUCT.md`, and **`LICENSE`** although `pyproject.toml:10` declares `license = "MIT"`.
- No open issues: external PRs were not preceded by an issue (R6 not followed; no `Closes #N` in #270/#271).

### 4.3 CI reachability

- Every job is `runs-on: [self-hosted, linux, x64]` (ci.yml:28,:77,:124; doc-lint.yml:32). The three self-hosted runners were **offline** at analysis time; #270/#271 checks are `QUEUED` since 2026-10-22. An outsider cannot obtain L0/L1/L2 feedback unless the owner's machine is up; nothing in the repo says so.
- Engine-specific tests never run in CI (validation.md:244) — a backend PR's core promise is unverified unless the author reports a manual run (R40, implicit).
- Draft-skip means an external non-draft PR immediately consumes runner time without the review gate having happened.

### 4.4 Rules that would silently bite an outsider

- New `docs/guides/<x>.md` **without** `verified-against:` front-matter fails `test_doc_freshness` (scans `docs/guides/*.md`, :59) → red CI on an otherwise fine PR.
- Any fenced `revolver …` example whose flag does not exist in the Typer tree fails `test_doc_command_lint` (R24).
- `test_backends.py:120` hard-codes `AVAILABLE_BACKENDS == ("openevolve", "shinka")` and `get_backend()` asserts registry == constant (base.py:818) — a new backend must touch both or the suite fails.
- `pytest` does **not** use `--strict-markers` (pyproject.toml:76 vs validation.md:202) → an unregistered marker only warns; the documented conventions (R14) are unenforced.
- Conventional-commit titles (`feat(backends): …`) and `feat/*` branches (PR #270/#271) do not match R2/R4; harmless technically, but they break the sprint-centric traceability (backlog → sprint → PR).
- Branch/sprint coupling: outsiders have no sprint task number, so R2/R4/R29 have no defined form for non-sprint work.

### 4.5 Drift inside the process documents (fix before pointing contributors at them)

- CLAUDE.md:108 says "Sprint 009 complete (v0.9.0)"; actual v0.18.0.
- validation.md §4.1/§4.2/§6.2 quote ruff `py311`/`line-length 100`/rule `N`, a mypy override, `--strict-markers -v`, `e2e_gpu` marker — none in pyproject.toml (:39-84).
- code-reviewer checklist says "ADR compliance (ADR-001..006)" (:47) — omits ADR-007, the one most relevant to backend PRs.
- `/session-close` template (SKILL.md:28-56) differs from the actual report format (session-059.md:1-7).

### 4.6 Ranked recommendations

| Rank | Recommendation | Effort | Rules enforced |
|---|---|---|---|
| 1 | **`CONTRIBUTING.md`** (English) with the lifecycle for outsiders: issue first, branch naming for non-sprint work, local gate commands, spec/DES/validation touchpoints, DoD §3a/§3b, "owner merges/tags", review severity semantics, CI runner caveat | M | R1-R11, R16-R25, R32-R35 |
| 2 | **`.github/PULL_REQUEST_TEMPLATE.md`** with the §5 checklist (incl. backend sub-checklist) | S | R5, R8, R10, R16, R23-R25, R40 |
| 3 | **Issue templates** (`feature.yml`, `new-backend.yml`) mirroring issue #190's shape (Context/Read first/Scope/Out of scope/Acceptance/References) | S | R6 |
| 4 | **GitHub-hosted CI fallback**: add an `ubuntu-latest` variant of lint + test (3.12) for `pull_request` from non-owner branches, or a `workflow_dispatch`/label trigger; document that self-hosted runners may be offline | M | R10, R11 (reachability) |
| 5 | **Portable review**: owner runs the code-reviewer manually on external PRs (`Review PR #N`) **and** publish the checklist (code-reviewer/agent.md:30-75) in CONTRIBUTING so Gemini CLI users can self-review; switch reviewer-agent output to English when the PR author is external | S | R8, R12, R13, R37 |
| 6 | **Generic backend conformance test** parameterized over `AVAILABLE_BACKENDS` (protocol isinstance, 8 capability axes typed, `is_available()` tuple, doctor name maps present, marker registered) replacing the hard-coded tuple at test_backends.py:120 | S | R33, DoD §3b |
| 7 | **`docs/guides/adding-a-backend.md`** (or DES-005 §4.9) = DoD §3b as prose, stamped `verified-against` | M | DoD §3b |
| 8 | Add `--strict-markers` to `addopts`; register per-backend markers; make validation.md §4/§6.2 match pyproject | S | R14 |
| 9 | **Optional CI job** that installs `.[<backend>]` and runs `-m <backend>` for PRs touching `src/revolver/infra/backends/<name>.py` (continue-on-error like L2-OE) | M | R39, R40 |
| 10 | **`LICENSE`** (MIT, matching pyproject) + `CODEOWNERS` (informational now; enforced once public/Pro) | S | governance |
| 11 | Fix process-doc drift (CLAUDE.md:108, validation.md tooling, code-reviewer ADR range → ADR-001..007) | S | credibility of sources |
| 12 | **Branch protection / rulesets** on `develop` and `main` (require PR + 1 review + CI) as soon as the repo goes public or Pro; meanwhile state in CONTRIBUTING that only the owner merges | S (blocked) | R9 |
| 13 | Add a `## Scope / Spec impact` section to the PR template asking which FR/DES/ADR/validation rows were touched, so the cascade becomes visible per PR instead of per sprint | S | R16-R21 |

---

## 5. Draft outlines

### 5.1 `CONTRIBUTING.md` — sections

1. Scope & roles (owner merges/releases; collaborators propose via PR; language English).
2. Before you start: open an issue (template), get a backlog number from the owner, read ADR-007 + DES-005 §4 for backend work.
3. Branching & commits (Git Flow; `feature/<topic>` or `feature/s<NN>-…` when attached to a sprint; imperative English commits).
4. Local quality gates (exact commands) and Python 3.12/3.14.
5. Tests: levels, directories, markers, importorskip for optional engines, fixtures, "no pre-existing test modified".
6. Docs you must touch (spec FR + Commands/Error rows, DES, ADR amendment, validation rows + Test IDs, README, guides + stamp, command-lint).
7. Pull requests: draft first, `Closes #N`, body sections, review severities, 0 CRITICAL, `ready`, CI (self-hosted caveat), owner merges.
8. Adding an evolution backend (link to DoD §3b / guide).
9. Releases & versioning (owner-only; two version files; tags).
10. Definition of Done checklists (feature / backend).

**Contributor rules (bullet list for the file):**
- Open or reference a GitHub issue before coding; the PR body starts with `Closes #N`.
- Target `develop`; branch `feature/<short-topic>`; never push to `develop`/`main` directly; never tag or bump versions.
- Commits: English, imperative mood, one logical change each.
- Run `ruff check src/ tests/`, `ruff format --check src/ tests/`, `mypy`, `pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"` on Python 3.12 before opening the PR.
- Add L1 + L2 tests for every new public function/command path; L2 suites go in `tests/integration/test_<command>.py` with `@pytest.mark.integration`; engine tests use `pytest.importorskip` + their engine marker.
- Do not modify existing tests except for mechanical relocation; call out every such change in the PR body.
- Every CLI option/behavior change updates `docs/specs/spec-<group>.md` (Commands table, FR with next free id, Error Cases) and the relevant `DES-*` section (bump its Version header).
- Every new FR gets rows in `docs/validation/val-integration-tests.md` and `traceability-matrix.md` naming the real test IDs.
- Changing an architectural decision = in-place dated amendment of the ADR (or a new ADR for a new decision), reflected in CLAUDE.md and architecture.md §9.
- DB schema changes: one column per migration, new `vN`, DES-001 §5.N + §8, `tests/unit/test_db_migration_vN.py`.
- User-facing changes update README (features, install, behavior changes); guides carry `verified-against: vX.Y.Z`; every fenced `revolver …` example must be a valid command.
- Optional engines are opt-in extras with pinned upper bounds; never add them to the `dev` extra; code must work when the engine is not installed.
- Open PRs as **draft**; mark ready only after review findings are fixed; a PR with an open CRITICAL finding is not mergeable.
- English only in code and docs; secrets only as env-var names.
- State in the PR how engine-specific tests were run (CI does not run them).

### 5.2 `.github/PULL_REQUEST_TEMPLATE.md` — checklist items

```
Closes #<issue>   (backlog #<n>, sprint task S<NN>-xx if any)
## Summary / Commits
## Spec impact   FR added/amended: … · DES: … · ADR: … · validation rows: …
## Tests          counts before/after · markers · engine env used (real <engine> x.y.z or "none")
- [ ] ruff check + ruff format --check + mypy clean
- [ ] pytest -m "unit or integration" ≥ 80 % coverage, Python 3.12 (and 3.14 if available)
- [ ] No pre-existing test modified (or each change listed above)
- [ ] L1 + L2 tests added; engine tests importorskip + marker
- [ ] spec-*.md Commands row + FR + Error Cases updated
- [ ] DES-* section(s) amended, Version header bumped
- [ ] ADR amended / new ADR (or "no decision change")
- [ ] val-integration-tests.md + traceability-matrix.md rows with real test IDs
- [ ] DB migration vN + DES-001 + test_db_migration_vN.py (or "no schema change")
- [ ] README features/install/behavior changes; guides stamped verified-against; doc command-lint passes
- [ ] Opened as draft; review findings addressed; 0 CRITICAL
- [ ] Backend PR only: AVAILABLE_BACKENDS + registry + capabilities() 8 axes + doctor maps + extra with upper bound + wrapper contract tests + DES-005 §4.6 column + ADR-007 amendment or new ADR
```

### 5.3 `CODEOWNERS` (suggested)

```
*                               @<maintainer>
/CLAUDE.md                      @<maintainer>
/.claude/                       @<maintainer>
/.github/                       @<maintainer>
/docs/architecture/             @<maintainer>
/docs/specs/                    @<maintainer>
/docs/validation/               @<maintainer>
/docs/sprints/                  @<maintainer>
/src/revolver/infra/backends/   @<maintainer>
/src/revolver/infra/db.py       @<maintainer>
/pyproject.toml                 @<maintainer>
```
(Informational until branch protection/rulesets become available; review-request routing still works on Free.)

---

## 6. Observed shape of the two external PRs (facts only, for the later gap review)

- **#270** `feat(backends): integrate LoongFlow evolution backend (PR 1)` — branch `feat/loongflow-backend`, not draft, 11 files (+706/−13): `.gitignore`, `README.md`, `docs/guides/loongflow.md`, `pyproject.toml`, `core/doctor.py`, `infra/backends/{__init__,base,loongflow}.py`, `tests/unit/infra/{test_backends,test_loongflow_backend}.py`, `tests/unit/test_doctor.py`. No issue / `Closes`, no spec/DES/ADR/validation edits, unit tests only, body cites "Traceable to ADR-007", checks QUEUED.
- **#271** `Feat/agentic backend` — branch `feat/agentic-backend`, not draft, 15 files (+1471/−14) **including the #270 files** (stacked), adds `infra/backends/agentic.py`, `docs/guides/agentic.md`, edits `docs/guides/tuning-evolution.md`, a real-Gemini-API e2e test; same gaps as #270; "conversational REPL refinement" is a different paradigm from ADR-007's evolution-engine scope (ADR-007:13-21).

