# Release and hotfix procedure

Releases are cut by the maintainer: version bumps, the `develop` → `main`
merge, tags and repository settings are maintainer-only actions
(`AGENTS.md`, "Irreversible actions"). Contributors prepare their part through
pull requests (CHANGELOG line, documentation, stamps) and never bump or tag.

A release closes a sprint: the `CHANGELOG.md` section it creates is the
sprint's review record ([sprint-planning.md](sprint-planning.md)).

## Inputs

- All sprint pull requests merged into `develop`; CI green on `develop`.
- `CHANGELOG.md` with a populated `[Unreleased]` section.
- The three review checklists for the documentation audit: [spec-review.md](spec-review.md), [validation-review.md](validation-review.md), [doc-review.md](doc-review.md).
- A local clone with `develop` and `main` up to date and push rights on both.

## Release checklist

Before tagging `vX.Y.Z`:

0. **(Optional) Documentation audit cascade** — run before the release to catch spec / doc drift accumulated during the sprint; skip for hotfixes or when the sprint changed no spec.
   - Run the **specification review** checklist → fix all FAIL / WARN findings → commit on `develop`.
   - Run the **validation review** checklist → fix all FAIL / WARN findings → commit on `develop`.
   - *(release steps 1–9 below)*
   - Run the **documentation review** checklist → fix all FAIL / WARN findings → commit + push. It runs post-release because it checks the version numbers in the README and the guides (step 10).
1. **Version bump** — update `version` in **both** `pyproject.toml` and `src/revolver/__init__.py`. The CI `version-check` job fails a tag whose name differs from either file.
2. **README, guides and stamps** (when the release changes user-facing behavior) — refresh `README.md` on `develop` before the merge to `main`: features list, install instructions (extras), CLI examples, test counts, the pointer to the CHANGELOG section. Re-verify the guides (`docs/guides/*.md`) and `docs/specs/user-story-e2e.md` against the release and refresh their `verified-against: vX.Y.Z` front-matter stamps — CI (`tests/unit/test_doc_freshness.py`) fails any stamp more than one minor version behind. The post-release documentation review validates these files but must not be the first time they see the release.
3. **CHANGELOG** — move the `[Unreleased]` entries of `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD` (a one-line sprint summary, then Added / Changed / Fixed / Removed; default-path changes flagged **Behavior change**), leave an empty `[Unreleased]` heading, and update the compare links at the bottom (`[Unreleased]: …/compare/vX.Y.Z...develop` and `[X.Y.Z]: …/compare/vPREVIOUS...vX.Y.Z`).
4. **Merge completeness** — ensure ALL sprint pull requests are merged into `develop`.
5. **Commit + push** — commit the bump, the README / stamps and the CHANGELOG on `develop` (`Bump version to X.Y.Z`), push, wait for CI green.
6. **Merge `develop` → `main`** — `git checkout main && git pull && git merge develop` (a merge commit; `main` receives releases only).
7. **Tag on `main`** — an annotated tag whose message is the CHANGELOG summary: `git tag -a vX.Y.Z -m "vX.Y.Z — <one-line summary>"`, then `git push origin main --tags`. The `version-check` CI job must pass on the tag push.
8. **Verify the install** — from a fresh virtual environment:

   ```bash
   pip install "revolver @ git+https://github.com/MateoTTR/revolver@vX.Y.Z"
   revolver --version
   ```

   The output must be `X.Y.Z`.
9. **Post-release verification** — before declaring the release complete, run these checks and report any failure:
   - `git tag -l vX.Y.Z` → the tag exists;
   - `grep 'version' pyproject.toml` and `grep '__version__' src/revolver/__init__.py` → both read `X.Y.Z`;
   - `git log main --oneline -1` → the tip of `main` is the merge commit;
   - `CHANGELOG.md` has the `## [X.Y.Z]` section and an empty `[Unreleased]`;
   - the sprint's planning issue has its closing comment and is closed with its milestone (GitHub-native planning, ADR-008 D2);
   - optionally, a GitHub Release for the tag with the CHANGELOG section as body.
10. **Post-release documentation review** — the last item of step 0: run [doc-review.md](doc-review.md), fix the findings, commit on `develop`, push.

## Hotfix process

For a critical bug discovered after a release:

1. **Branch** — `git checkout -b hotfix/vX.Y.Z develop` (Z = previous patch + 1).
2. **Fix + tests** — apply the fix with its regression test; run the local gates (`ruff check src/ tests/`, `ruff format --check src/ tests/`, `mypy`, `pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"`); add a `### Fixed` line under `[Unreleased]` in `CHANGELOG.md`.
3. **Draft pull request** — `gh pr create --draft --base develop` with `Closes #N` (open the bug issue first when none exists).
4. **Ready** — `gh pr ready` once the gates are green and the CHANGELOG line is in; the four required checks run.
5. **Code review + merge** — on the green build, apply [code-review.md](code-review.md); address the findings, answer and resolve every thread; the maintainer merges on GitHub with 0 CRITICAL in the latest review and the checks green.
6. **Release** — follow the release checklist above (bump to the patch version, CHANGELOG, `develop` → `main`, tag, install check, post-release checks); step 0 is skipped for a hotfix.

## Output and where to post

The release itself is the output: the tag on `main`, the CHANGELOG section,
the bump commit. Report the post-release verification results as the closing
comment of the sprint's planning issue (or of the hotfix issue), and the
documentation review findings as described in [doc-review.md](doc-review.md).

## Changes from the former `CLAUDE.md` checklist

- **(changed)** Steps 0–7 and the hotfix process are those of the former `CLAUDE.md` "Release Checklist" and "Hotfix Process" sections, renumbered (the old 1b / 1c become steps 2–3) and with the three reviewer *agents* replaced by the three review *checklists* of this directory.
- **(changed)** The post-release checks "journal entry written" and "backlog file updated" are replaced by the CHANGELOG-section check and the planning-issue closing comment: the journal is private and the backlog file left the repository (ADR-008 D1, D2).
- **(changed)** The tag command is written as an annotated tag (`git tag -a … -m …`), which is what the project's release tags are; the former text showed a plain `git tag vX.Y.Z`.
- **(added)** The `version-check` CI job reference, the "wait for CI green" wording in step 5 and the CHANGELOG line in hotfix step 2 restate existing practice (`.github/workflows/ci.yml`, the `CHANGELOG.md` header).
