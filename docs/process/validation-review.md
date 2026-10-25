# Validation review checklist

Run this review whenever a validation document (`docs/validation/`) or a
specification (`docs/specs/`) changes, and as the second step of the
pre-release documentation audit ([release.md](release.md), step 0), after the
[specification review](spec-review.md). Part A checks that the test strategy
and the traceability matrix stay consistent with the specifications and the
design documents; Part B is the cross-document traceability sweep over the
whole documentation set. The reviewer reports; fixes come in a separate pass.

## Inputs

```
docs/validation/validation.md              — overview: strategy, levels, tools, CI pipeline, test-id conventions (§8.1)
docs/validation/val-integration-tests.md   — L2 command test matrix (§2), test data, conventions
docs/validation/val-e2e-tests.md           — L3 scenarios, LLM mocking, fake server
docs/validation/traceability-matrix.md     — FR/NFR → DES → test mapping, coverage summary (§13)
docs/specs/specifications.md               — NFRs (§3), conventions, spec index (§5), ConOps traceability (§6)
docs/specs/spec-*.md                       — functional specifications per command group
docs/architecture/design/DES-*.md          — detailed design documents
docs/architecture/architecture.md          — architecture overview, ADR index (§9), DES index (§10)
docs/architecture/adr/ADR-*.md             — architecture decision records
docs/conops/conops.md                      — concept of operations
AGENTS.md                                  — project entry file; ADR and DES indexes
tests/**/*.py                              — the test files
```

Discover files at run time (`ls`, `grep`), never from memory. Useful one-liners:

```bash
grep -rhoE 'FR-[A-Z]+-[0-9]+' docs/specs/spec-*.md | sort -u                 # FR ids in the specs
grep -rhoE 'FR-[A-Z]+-[0-9]+' docs/validation/traceability-matrix.md | sort -u
grep -rhoE 'NFR-[0-9]+' docs/specs/specifications.md | sort -u
```

## Part A — Validation documents against specs and design

### 1. FR coverage (traceability matrix vs specs)

For each `spec-*.md`: extract the FR ids (`FR-[A-Z]+-\d+`) and verify every id
appears in `traceability-matrix.md`. An FR present in a spec but missing from
the matrix is **FAIL**; an FR present in the matrix but absent from the specs
is **WARN** (orphan).

### 2. NFR coverage (traceability matrix vs `specifications.md`)

Extract the NFR ids (`NFR-\d+`) from `specifications.md` §3. Testable NFRs
(CLI, storage, reproducibility, security) must appear in the matrix (**WARN**
when missing). Performance NFRs (NFR-030/031/032) and deployment NFRs
(NFR-060/061) may be marked manual or packaging — acceptable.

### 3. Priority coverage

Every `MUST` FR has at least one test (L1 or L2) — missing is **FAIL**. A
`MUST` FR whose only rows are `Planned` but carry a dated justification and an
open tracking issue (an acknowledged requirement that is not implemented yet) is
**WARN**, not FAIL; the review names it and the issue. A `SHOULD` FR should have a
test — missing is **WARN**. A `MAY` FR may have none.

### 4. DES reference validity

For each DES reference in the matrix (e.g. "DES-005 §4.2"): the file
`docs/architecture/design/DES-NNN-*.md` exists and, when a section is given,
a heading containing that section number exists in it. Invalid references
are **FAIL**.

### 5. Test-level consistency (matrix vs `validation.md`)

Test levels used in the matrix (L0, L1, L2, L3) match the strategy. Test ids
follow `validation.md` §8.1: L1 `unit/{layer}/test_{module}::{test_name}`,
L2 `integration/test_{command}::{test_name}` (historic top-level suites are
referenced without a prefix), L3 `e2e/test_{scenario}::{test_name}`.
Non-conforming ids are **WARN**.

### 6. Test-file existence

For each matrix row with status `Implemented` or `Passing`, the test file
exists under `tests/` — missing is **FAIL**. `Planned` rows need no file.

### 7. Command coverage (command test matrix vs specs)

Extract the CLI commands from the spec files (headings and Commands tables)
and verify each has at least one scenario in the command test matrix,
`val-integration-tests.md` §2. Missing commands are **WARN**.

### 8. Coverage-summary accuracy

The counts in the traceability matrix summary (§13) match the actual rows of
the matrix. Mismatches are **WARN**.

## Part B — Cross-document traceability sweep

### 9. ADR consistency

- Every ADR listed in the `AGENTS.md` ADR table exists as a file in `docs/architecture/adr/`.
- Every ADR file (except the template) is listed in `AGENTS.md`.
- The ADR table in `architecture.md` §9 matches `AGENTS.md` (titles, statuses).
- ADR statuses (Proposed / Accepted / Deprecated / Superseded) agree across every reference.

### 10. Spec consistency

- Every spec file listed in `specifications.md` §5 exists; every `spec-*.md` in `docs/specs/` is listed there.
- NFR ids referenced in spec files exist in `specifications.md` §3.
- FR ids within each spec file are unique and follow `FR-<GROUP>-NNN`; no duplicate FR id across spec files.
- FR ids referenced in DES documents exist in the corresponding spec file.

### 11. DES consistency

- Every DES listed in the `AGENTS.md` DES table exists in `docs/architecture/design/`; every `DES-*.md` file is listed there.
- The DES table in `architecture.md` §10 matches `AGENTS.md`; DES statuses (Draft / Final / Deprecated) agree across references.
- Design decisions (DD-NN) are sequentially numbered and unique within each DES.
- Cross-DES references point to existing documents.

### 12. ConOps-to-specs traceability

- Every ConOps section listed in the traceability table of `specifications.md` §6 has corresponding FRs.
- ConOps open questions marked resolved have a corresponding ADR or decision.

### 13. Architecture-to-specs traceability

- Components in `architecture.md` reference relevant spec files or NFRs.
- Technology choices in `architecture.md` have corresponding ADRs.
- Each DES references the spec files listed in its "Traceable to" header, and its design decisions do not contradict the spec's functional requirements.

### 14. Entry-file consistency

- The phase table in `AGENTS.md` matches the actual state (latest release in `CHANGELOG.md`, open milestones).
- Every index row in `AGENTS.md` resolves to an existing file.
- Open questions or decision placeholders in `AGENTS.md` are closed with a documented decision (an ADR or a CHANGELOG entry), and the phase statuses match the actual progress.

## Severity vocabulary

- **PASS** — check passed (note briefly what was checked and the result)
- **INFO** — observation, no action required
- **WARN** — minor inconsistency, non-blocking; suggest the fix
- **FAIL** — missing reference or broken traceability, with file paths and line numbers

## Output format

One line per check with its severity, grouped Part A / Part B, then the
summary line `N checks, N warnings, N failures`. For each WARN / FAIL give
the file, the line and the suggested fix.

## Where to post

- As a review comment on the pull request that changes the documents.
- For the pre-release audit, as a comment on the release or planning issue;
  fixes are committed on `develop` and the review is re-run until it reports
  0 FAIL.

## Changes from the former agent definition and skill

- **(changed)** Part A reproduces the former validation-reviewer checks 1–8. Check 7 pointed to "the strategy's command test matrix (§5.2)"; the matrix lives in `val-integration-tests.md` §2, which is what the text now says.
- **(changed)** Check 6 used the statuses "Written or Passing"; the matrix legend defines `Planned` → `Implemented` → `Passing`, so `Implemented` is used.
- **(changed)** Part B folds in the former `/traceability-check` skill (its checks 1–5 and 7). `CLAUDE.md` is replaced by `AGENTS.md` throughout. The skill's "Backlog consistency" check (task numbers unique and sequential, completed tasks cite a session number, session numbers match session reports) is **dropped**: neither the backlog file nor the session journal is in the repository any more (ADR-008 D1, D2). Its "CLAUDE.md consistency" check (open questions ticked with a documented decision, phase statuses matching progress) becomes check 14.
- **(changed)** Findings are reported in English; the agent-harness "run discipline" paragraph is dropped; "OK" is written "PASS" and "INFO" is added.
- **(changed, 2026-10-25, #297)** Check 3 grades a `MUST` FR that is acknowledged as not implemented — `Planned` rows only, with a dated justification and an open tracking issue — as **WARN** instead of FAIL, the grading the Sprint 020 traceability-debt resolution applied to FR-LLM-005 (#315).
