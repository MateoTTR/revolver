# Maintainer journal

The working journal that used to live in this directory (one report per
working session plus a cumulative time tracker) was the maintainer's private,
per-session material. It left the public repository at v0.19.0: such a journal
does not compose across contributors, and a global session counter cannot be
kept with parallel pull requests.

- **Historical reports** remain in the git history before v0.19.0 (the files
  were removed, not rewritten, so `git log` on `develop` still shows them).
- **Continuity for contributors** is recorded through GitHub issues, a short
  **Status** section in the description of long-running pull requests
  (updated at each working session), [`CHANGELOG.md`](../../CHANGELOG.md) and
  the design documents under [`docs/architecture/`](../architecture/).
- **The journal itself** is kept outside the repository. Its location is
  configured in the git-ignored `CLAUDE.local.md` and is never committed.
  Contributors are not expected to keep one.

The design note formerly stored here (`refactor-run-solution.md`) was not a
session report and now lives in
[`docs/analysis/refactor-run-solution.md`](../analysis/refactor-run-solution.md).
"Session NNN" references in `docs/sprints/` and `docs/tasks/backlog.md` are
historical and intentionally left as they are.
