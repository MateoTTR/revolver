# Contributing to Revolver

Thank you for considering a contribution. This file is the **lifecycle of a
change** seen from a contributor's chair, from the issue to the merged pull
request. It links to the rules; it does not restate them. The canonical
project guide is [AGENTS.md](AGENTS.md) and the procedures live under
[docs/process/](docs/process/README.md): when this file and those disagree,
they win and this file has a bug.

Everything here works with a terminal, a browser and the repository alone; no
editor, assistant or automation is assumed
([ADR-008](docs/architecture/adr/ADR-008-documentation-and-process-strategy.md)).

## Before you start

- Read [AGENTS.md](AGENTS.md): overview, documentation index, conventions,
  pull-request workflow.
- This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
  Vulnerabilities go through the [security policy](SECURITY.md), never through
  a public issue.
- Everything committed, posted or reviewed here is public: see the
  [public-file rule](docs/process/README.md#public-file-rule). It applies to
  issues, pull-request descriptions and review comments as well.
- All code, comments, documentation, issues, pull requests and reviews are in
  English.

## Roles

| Role | Who | Does |
|---|---|---|
| **Maintainer** | The repository owner | Merges, tags, version bumps, releases and repository settings; owns the formal documents (specifications, DES, ADRs, validation); plans sprints; is the code owner of the governance paths (`.github/CODEOWNERS`) |
| **Contributor** | Anyone — collaborators have read access and contribute the same way | Opens issues and pull requests from a fork, runs the local gates and the self-review, keeps the pull request's **Status** section current |
| **Reviewer** | Any contributor; the maintainer at merge time | Applies [docs/process/code-review.md](docs/process/code-review.md) and posts a pull-request review with inline comments |
| **Agents** | Any AI coding tool a contributor chooses to use | Follow the same files as humans ([Working with AI tools](#working-with-ai-tools-pointer-file-rule)); the contributor remains the author and the accountable party |

## 1. Start from an issue

Every pull request closes a GitHub issue
([AGENTS.md § Pull request workflow](AGENTS.md#pull-request-workflow), step 1).
Pick one of the issue forms — **Bug report**, **Feature**, **New evolution
backend** (the **Sprint planning** form is for the maintainer) — or comment on
an existing issue to claim it. The issue carries the scope, the files to touch,
the acceptance criteria, the test scenarios and the specification / DES / ADR
references: it is the single source of truth for the change, and the reviewer
checks the pull request against it.

**Design changes from external contributors (RFC-lite).** When your change
alters behavior, a CLI surface, a data model or an architectural decision —
anything that would touch `docs/specs/`, a DES, an ADR or `docs/validation/` —
open the issue first as a **design issue** (the Feature form with the RFC-lite
box ticked, or the New evolution backend form) and wait for the maintainer's
go-ahead. The maintainer then updates the formal documents, or reviews your
edits to them, before or with your implementation pull request
(spec-before-code: [sprint-planning.md](docs/process/sprint-planning.md),
step 7). Bug fixes and documentation fixes that change no behavior need no
design issue.

Issues labelled `good first issue` are sized for a first contribution.

## 2. Fork and branch

Every pull request comes from a **fork**, targets `develop` and lives on a
`feature/<topic>` branch; branch and commit conventions are in
[AGENTS.md § Git](AGENTS.md#git).

```bash
# once: fork the repository on GitHub, then
git clone https://github.com/<your-account>/revolver.git
cd revolver
git remote add upstream https://github.com/MateoTTR/revolver.git

# per change
git fetch upstream
git switch -c feature/<topic> upstream/develop
# ... commit: English, imperative mood, one logical change per commit ...
git push -u origin feature/<topic>
```

Keep the branch current with `git fetch upstream && git rebase
upstream/develop` (force-push to your own fork only). A pull request that
depends on another waits for it to be merged into `develop`.

## 3. Set up and run the local gates

CI runs on Python **3.12 and 3.14**: run the gates on 3.12 at least, and on
3.14 when you have it. Install the package in development mode and run exactly
what CI runs ([AGENTS.md § Pull request workflow](AGENTS.md#pull-request-workflow),
step 4; the jobs are in `.github/workflows/ci.yml`):

```bash
python -m venv .venv && source .venv/bin/activate   # any Python >= 3.12 environment
pip install -e ".[dev]"

ruff check src/ tests/
ruff format --check src/ tests/
mypy
pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"
```

Two documentation guards run in CI as well (the `Doc command-lint` job); run
them whenever you touch Markdown:

```bash
pytest tests/unit/test_doc_command_lint.py tests/unit/test_doc_freshness.py
```

**Engine-specific tests are not run by CI.** Install the engine extra, run its
marker, and state in the pull request which environment you ran them in
(engine package and version, Python version):

```bash
pip install -e ".[openevolve]" && pytest -m openevolve
pip install -e ".[shinka]"     && pytest -m shinkaevolve
```

CI runs `tests/integration/test_run_oe.py` on Python 3.12 as a non-blocking
step; nothing in CI runs ShinkaEvolve.

`pytest` runs the L1 and L2 suites by default; the L3 end-to-end tests are
deselected (`-m 'not e2e'` in `pyproject.toml`) and run with `pytest -m e2e`.
The tests isolate Revolver's global store through `REVOLVER_HOME` (see the
README); point it at a scratch directory when your own `~/.revolver` must stay
untouched.

## 4. Test levels, directories and markers

| Level | What | Where | Markers | In CI |
|---|---|---|---|---|
| 0 — Static | ruff, mypy | — | — | `Lint (ruff + mypy)` |
| 1 — Unit | functions and classes of `core/` and `infra/`, everything external mocked | `tests/unit/` (mirrors `src/revolver/`) | `unit` | `Test (pytest + coverage)` |
| 2 — Integration | CLI commands through `CliRunner`, real SQLite in a temporary project | `tests/integration/test_<command>.py` (a few historic suites sit at `tests/test_*.py`) | `integration` | `Test (pytest + coverage)` |
| 2-OE — OpenEvolve contract | config round-trip, controller init; no LLM | `tests/integration/test_run_oe.py` | `integration` + `openevolve`, module-level `pytest.importorskip` | non-blocking step, Python 3.12 |
| 2-Shinka — ShinkaEvolve contract | config projection, wrapper and database contracts; no LLM | `tests/integration/test_run_shinka.py`, `tests/integration/test_shinka_*.py` | `integration` + `shinkaevolve`, module-level `pytest.importorskip` | not run — manual |
| 3 — E2E | full workflows against the fake LLM server | `tests/e2e/` | `e2e` + `slow` (`e2e_gpu` reserved for the manual GPU track) | not run — manual, `-m e2e` |

Markers are **strict** (`--strict-markers`): a new marker must be registered
in `pyproject.toml` under `[tool.pytest.ini_options]`, or collection fails.
Shared fixtures live in `tests/conftest.py` (`tmp_project`, `cli_runner`, the
HTTP mocks, the `no_<backend>` fixtures) and test data under `tests/fixtures/`.
The validation documents cite tests as `<path-under-tests/>::<test_name>`
([validation.md § 8.1](docs/validation/validation.md#81-test-id-conventions)).
Strategy, coverage targets and conventions:
[docs/validation/validation.md](docs/validation/validation.md) and
[val-integration-tests.md § 4](docs/validation/val-integration-tests.md#4-conventions).

## 5. Documentation touchpoints

Documentation is updated **before or with** the code, in the same pull
request. The [Definition of Done](docs/process/definition-of-done.md) (items 2,
3 and 7) is the checklist; a change may have to touch:

| Touchpoint | When | Where |
|---|---|---|
| Specification | a new or changed CLI option or behavior | `docs/specs/spec-<group>.md`: the Commands-table row, a functional requirement (next free id, `MUST` / `SHOULD` / `MAY`) and an Error Cases row |
| Design document | a design section no longer matches | the DES section, with its header version bumped |
| ADR | a decision changes, or a new decision is taken | an in-place dated amendment of the existing ADR, or a new ADR, indexed in `architecture.md` § 9 and `AGENTS.md` |
| Validation rows | tests added or changed | `docs/validation/val-integration-tests.md` and `traceability-matrix.md`, naming the real test ids (`Planned` while in flight, `Implemented` once merged) |
| README | a user-facing feature, install step or behavior | `README.md` |
| Guides and the E2E walkthrough | their content changed, or a release | `docs/guides/*.md` and `docs/specs/user-story-e2e.md`, each with a current `verified-against: vX.Y.Z` front-matter stamp |
| Doc command-lint | any fenced `revolver …` example | it must resolve against the CLI tree; the `Doc command-lint` CI job tells you which line does not |
| Changelog | every pull request | **one line** under `[Unreleased]` in `CHANGELOG.md`, flagged **Behavior change** when a default path changes |

The review procedures for the documents are
[spec-review.md](docs/process/spec-review.md),
[validation-review.md](docs/process/validation-review.md) and
[doc-review.md](docs/process/doc-review.md).

## 6. Open a draft pull request

Open the pull request **as a draft, as soon as the branch exists**, against
`develop`. The pull-request template pre-fills the description: its first line
is `Closes #N`, followed by Summary, Spec impact, Tests, the Definition-of-Done
checklist and a **Status** section. Update **Status** (done / next / blocked)
at the end of each working session: it is how continuity is carried between
sessions and between contributors, since no journal or planning file is kept in
the repository. Drafts do not run CI.

```bash
gh pr create --draft --base develop --title "<imperative summary>"   # or the web interface
```

## 7. Review, ready, merge

1. **Self-review** your diff against
   [docs/process/code-review.md](docs/process/code-review.md) and the
   [Definition of Done](docs/process/definition-of-done.md); fix what you find.
2. **Ask for a review** on the draft. A reviewer applies the same checklist and
   posts a GitHub review with inline findings classified **CRITICAL** /
   **WARNING** / **SUGGESTION** / **GOOD**; address them and push.
3. **Mark the pull request ready** (`gh pr ready <N>`, or the button) only when
   the latest review carries **0 CRITICAL** findings, every WARNING is fixed or
   explicitly carried over in the description, and the `[Unreleased]` line is
   in `CHANGELOG.md` ([code-review.md § Exit rule](docs/process/code-review.md#exit-rule)).
   The four required checks then run and must be green.
4. **The maintainer merges.** Merging into `develop` or `main`, tags, version
   bumps and repository settings are maintainer-only actions
   ([AGENTS.md § Git](AGENTS.md#git)); releases follow
   [docs/process/release.md](docs/process/release.md).

## Working with AI tools (pointer-file rule)

You may use any assistant, or none; nothing in the process depends on one.

- **`AGENTS.md` is the only instruction file.** Project knowledge for agents
  lives there and in the files it links; it is never duplicated into
  tool-specific files.
- **A tool-specific pointer file is added only when both conditions hold**:
  the tool cannot read `AGENTS.md` natively, **and** the tool is used by an
  active contributor. Such a file contains nothing but an import of
  `AGENTS.md`, plus the one-line reminder that personal notes go to a
  git-ignored `*.local.md`. Today there are two: `CLAUDE.md` (Claude Code
  import syntax, `@AGENTS.md`) and `GEMINI.md` (Gemini CLI import syntax,
  `@./AGENTS.md`).
- **Tools that read `AGENTS.md` natively get no file**: Codex, Cursor,
  Copilot, Jules, Windsurf, Amp, Zed, Aider and the like find it at the
  repository root.
- **Tooling stays private.** Agent definitions, hooks, skills, MCP
  configurations and personal instruction files (`CLAUDE.local.md`,
  `GEMINI.local.md`) are git-ignored and never committed
  ([ADR-008 D5](docs/architecture/adr/ADR-008-documentation-and-process-strategy.md)).
  A tool may automate any checklist of `docs/process/` as long as its output
  is posted where the checklist says.

To point your tool at the project guide:

| Tool | What to do |
|---|---|
| Claude Code | Nothing: it reads `CLAUDE.md`, which imports `AGENTS.md` (recent versions also read `AGENTS.md` directly) |
| Gemini CLI | Nothing: it reads `GEMINI.md`, which imports `AGENTS.md` (alternatively, list `AGENTS.md` in its `context.fileName` setting) |
| Codex, Cursor, Copilot, Jules, Windsurf, Amp, Zed, Aider, … | Nothing: they read `AGENTS.md` natively |
| Another tool that cannot read `AGENTS.md` | Open an issue proposing the pointer file under the rule above; until then, give it `AGENTS.md` as context by hand |
| No tool | Read `AGENTS.md`; every command in it and in `docs/process/` is a plain shell or `gh` command |

Whatever produced your change, you are its author: run the gates, do the
self-review and answer the review yourself.

## Security and conduct

- Vulnerabilities: [SECURITY.md](SECURITY.md) — private reporting only.
- Behavior: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) (Contributor Covenant
  2.1), enforced by the maintainer through GitHub's private channels.

## License

Revolver is released under the [MIT License](LICENSE). By contributing you
agree that your contribution is licensed under the same terms.
