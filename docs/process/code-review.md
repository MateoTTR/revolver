# Code review checklist

Review every pull request against this checklist before it is marked ready.
The author runs it first (self-review); a second reviewer runs it again. The
review is posted on the pull request as a GitHub review with inline comments.

## Inputs

- The pull request number (or branch name) and the issue it closes
  (`Closes #N` in the description). The issue is the single source of truth
  for the intended behavior.
- [`AGENTS.md`](../../AGENTS.md) for the project conventions and the
  architecture overview; `docs/specs/` for the FR/NFR being implemented.
- The diff and the **complete** changed files, not only the hunks:

  ```bash
  gh pr checkout <N>              # or: git fetch origin && git switch <branch>
  gh pr diff <N> --name-only      # files to read in full
  gh pr diff <N>                  # the hunks
  ```

  Without the GitHub CLI: `git diff origin/develop...HEAD` on the checked-out
  branch, and the "Files changed" tab of the pull request.

## Steps

### 1. Gather context

1. Read `AGENTS.md` and the issue the pull request closes.
2. List the changed files; read each changed file in full to understand the
   complete context of every hunk.
3. Order the work by risk: migrations, security-sensitive code, data
   integrity and the diff's core logic first, lower-risk files afterwards.
   If the review must stop early, post what was reviewed with an explicit
   "Not yet reviewed: …" line rather than nothing.

### 2. Check every changed file

Functionality

- [ ] Logic correctness — does the code do what the issue says?
- [ ] Edge cases — empty inputs, `None` values, boundary conditions
- [ ] Error handling — exceptions caught at the right level, correct exit codes (1–4, [specifications.md §4.2](../specs/specifications.md))
- [ ] Return types match signatures and Pydantic models
- [ ] FR/NFR compliance — cross-reference with `docs/specs/` when applicable

Architecture & design

- [ ] Layer separation respected: `cli/` calls `core/`, `core/` calls `infra/`, never reversed
- [ ] No circular imports between modules
- [ ] New exceptions inherit from the `RevolverError` hierarchy (`src/revolver/core/exceptions.py`)
- [ ] Pydantic models use `ConfigDict(frozen=True)` where required
- [ ] SQLite queries use parameterized statements (no f-strings / `format`)
- [ ] ADR compliance (ADR-001 … ADR-008) — e.g. Ollama for local LLMs, Typer for the CLI, backend capabilities drive validation (ADR-007)

Code quality

- [ ] Clear, descriptive names (English, no abbreviations)
- [ ] No code duplication — reuse existing `infra` utilities
- [ ] Type hints on all function signatures
- [ ] Docstrings on public functions (existing style: Args / Returns / Raises)
- [ ] No commented-out code or `TODO` without an issue reference
- [ ] `from __future__ import annotations` at the top of each module

Performance

- [ ] No N+1 query patterns in DB functions
- [ ] No unnecessary file I/O in loops
- [ ] Subprocess / `ProcessPoolExecutor` properly cleaned up
- [ ] `httpx` client not recreated per request

Security

- [ ] API keys never stored in code or DB (only environment-variable **names**)
- [ ] No `eval()`, `exec()` or unsafe deserialization on user input
- [ ] SQL injection prevented (parameterized queries only)
- [ ] Subprocess calls do not pass unsanitized user input to a shell

Testing

- [ ] All new public functions have corresponding tests
- [ ] Tests follow Arrange-Act-Assert
- [ ] Mocks sit at the right boundary (the `infra` layer for integration tests)
- [ ] Edge cases tested (empty, `None`, duplicates, timeouts)
- [ ] Test names are descriptive: `test_<function>_<scenario>`
- [ ] `@pytest.mark.integration` on L2 tests, `@pytest.mark.unit` on L1 tests; markers are strict (`--strict-markers`), so a new marker must be registered in `pyproject.toml`

Public-file rule

- [ ] No local path, hostname, private repository name, e-mail address, personal timing data or third-party handle in the diff ([README.md](README.md#public-file-rule))

### 3. Backend pull requests

When the pull request adds or changes an evolution backend
(`src/revolver/infra/backends/`), also walk the backend section of the
[Definition of Done](definition-of-done.md#2-new-evolution-backend): registry
and protocol members, the capability axes, doctor / setup entries, the opt-in
extra with an upper bound, the wrapper contract tests gated by
`pytest.importorskip` and the engine marker, the spec / DES / ADR / validation
touchpoints, and the real-engine evidence in the pull-request description
(CI does not run engine tests).

### 4. Classify each finding

- **CRITICAL** — must fix before merge (bugs, security, data-loss risks)
- **WARNING** — should fix (code quality, missing edge cases, architecture violations)
- **SUGGESTION** — nice to have (style improvements, minor optimizations)
- **GOOD** — noteworthy positive pattern worth highlighting

### 5. Post the review

Post one **pull-request review** (not a plain comment) so that findings are
anchored to lines:

1. In the pull request's "Files changed" tab, add one inline comment per
   CRITICAL / WARNING / SUGGESTION finding on the exact line of the new
   version of the file. Start the comment with its severity tag
   (`**CRITICAL**:`, `**WARNING**:`, `**SUGGESTION**:`), quote the
   problematic snippet and suggest a fix.
2. Submit the review with the summary below as its body: **Request changes**
   when any finding is CRITICAL, **Comment** otherwise. (**Approve** is the
   maintainer's call at merge time.)

From a terminal, the summary alone can be posted with:

```bash
gh pr review <N> --request-changes --body-file review.md   # any CRITICAL
gh pr review <N> --comment --body-file review.md           # otherwise
```

and the inline comments added in the web interface.

Summary body template:

```markdown
## Code Review — PR #<number>

### Summary
<1–2 sentence overview of the changes and the overall assessment>

**Verdict**: REQUEST CHANGES / COMMENT

### Stats
- Files reviewed: N
- Critical: N | Warnings: N | Suggestions: N
- Test coverage: adequate / needs improvement

#### GOOD
> <positive patterns worth noting>
```

## Notes

- Write in English.
- Be precise with line numbers (new side of the diff) and specific: show the snippet, propose the fix.
- Do not flag what `ruff` and `mypy` already catch — CI handles those; focus on logic, design and what a linter cannot see.
- If no issue is found, still post a positive review confirming the code looks good. GOOD findings go in the summary body, never inline.

## Exit rule

The pull request may be marked ready (`gh pr ready <N>`, or the button in
the web interface) only when the latest review carries **0 CRITICAL**
findings and every WARNING is either fixed in the pull request or explicitly
listed as carried over in the pull-request description. The four required CI
checks must then be green before the maintainer merges (see `AGENTS.md`,
"Pull request workflow").

## Changes from the former agent definition

- **(changed)** The former prompt read "ADR compliance (ADR-001..006)"; the range is now ADR-001 … ADR-008 (ADR-007 governs backend pull requests and was missing).
- **(changed)** Posting through a GitHub MCP tool with a `gh pr comment` fallback is replaced by the "Files changed" flow and `gh pr review`; the "Automated review by Claude Code" footer and the hard-coded owner / repository constants are dropped.
- **(changed)** The "run discipline" paragraph about the agent harness idle timeout is dropped; its one portable rule (highest-risk files first, a partial review rather than none) is kept in step 1.
- **(changed)** "Report in English" is kept; the French communication rule applied to the maintainer's own sessions and is not part of the project process.
- **(added)** Step 3 (backend pull requests), the public-file-rule item and the exit rule were implicit practice (every sprint review reported "0 CRITICAL before ready"); they are now written down. The strict-marker note reflects `pyproject.toml` at v0.19.0.
