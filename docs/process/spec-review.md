# Specification review checklist

Run this review whenever a specification (`docs/specs/`), a design document
(`docs/architecture/design/DES-*.md`) or an architecture decision record
(`docs/architecture/adr/ADR-*.md`) is created or modified, and as the first
step of the pre-release documentation audit ([release.md](release.md), step 0).
The reviewer verifies cross-document consistency and reports findings; the
documents are fixed in a separate pass.

## Inputs

- The changed documents (from the pull-request diff, or
  `git diff origin/develop...HEAD -- docs/` on the branch).
- The document hierarchy:

  ```
  AGENTS.md                              — project entry file; ADR and DES indexes
  docs/conops/conops.md                  — concept of operations, personas, workflows, open questions (OQ-*)
  docs/specs/specifications.md           — NFRs (§3), conventions (§2 numbering and template, §4 CLI conventions), spec index (§5), ConOps traceability (§6)
  docs/specs/spec-*.md                   — one functional specification per command group
  docs/architecture/architecture.md      — architecture overview, layers, data flows, ADR index (§9), DES index (§10), open questions (AQ-*)
  docs/architecture/adr/ADR-NNN-*.md     — architecture decision records
  docs/architecture/design/DES-NNN-*.md  — detailed design documents (expand on ADRs and specs)
  ```

- Discover the documents at run time rather than from memory:
  `ls docs/specs/spec-*.md docs/architecture/adr/ADR-*.md docs/architecture/design/DES-*.md`.
- The traceability chain:

  ```
  ConOps (workflows, OQ-*) → Specs (FR-*, NFR-*) → ADRs (technology decisions, with the POC findings that validated them; a POC finding with no ADR is recorded in the DES that relies on it)
                                                  → DES (detailed design, decision notes DD-*)
  ```

## Steps

Review the most recently changed and highest-impact documents first. If the
scope is large, a complete review of the top items plus an explicit
"Not yet covered: …" line is better than an exhaustive sweep left unfinished.

### For specification files (`docs/specs/spec-*.md`)

1. **Internal consistency** — FR ids are unique, follow `FR-<GROUP>-NNN` ([specifications.md §2.1](../specs/specifications.md)) and have no gaps; deleted requirements are marked `[DELETED]`, never renumbered; a new FR takes the next free number.
2. **NFR references** — every NFR referenced in the spec exists in `specifications.md` §3.
3. **Cross-spec references** — dependencies on other specs resolve.
4. **Architecture alignment** — commands and data flows match `architecture.md`.
5. **ConOps alignment** — functional requirements trace back to ConOps workflows.
6. **ADR alignment** — technology choices match accepted ADRs.
7. **Exit codes** — match the global convention (`specifications.md` §4.2).
8. **Option conventions** — `--json`, `--help`, `--verbose`, `--quiet` presence (`specifications.md` §4.3).
9. **DES alignment** — when a related DES exists, FR coverage is consistent with its design decisions (DD-*).
10. **Commands / FR / Error-cases triad** — a new or changed CLI option appears in the three places the spec template requires (`specifications.md` §2.3): the Commands table, a functional requirement, and the Error Cases table.

### For design documents (`docs/architecture/design/DES-*.md`)

1. **Spec traceability** — design decisions (DD-*) trace back to specific FRs in the related spec.
2. **ADR consistency** — technology choices align with accepted ADRs (e.g. Pydantic models per ADR-005, SQLite per ADR-004, backend abstraction per ADR-007).
3. **DES-001 alignment** — data-model changes (tables, columns, migrations) are consistent with the DES-001 schema.
4. **Architecture alignment** — components, layers and data flows match `architecture.md`.
5. **Cross-DES consistency** — references to other DES documents resolve and do not contradict them.
6. **POC alignment** — when proof-of-concept findings are recorded in the related ADR (ADR-001, ADR-006) or in the DES itself (DES-005 for the hosted-API study), the design follows them.
7. **Open-question resolution** — when the DES resolves an AQ-* or OQ-*, the resolution is reflected in `architecture.md` and `conops.md`.
8. **Headers and numbering** — the `**Version**` / `**Date**` / `**Status**` / `**Traceable to**` header block is present and its version line was bumped for the change; DD numbers are sequential and unique within the document.

### For ADRs (`docs/architecture/adr/ADR-*.md`)

1. **Index consistency** — the ADR is listed, with the same title and status, in `architecture.md` §9 and in `AGENTS.md`.
2. **Status alignment** — the status matches what other documents say about it.
3. **Consequence propagation** — consequences described in the ADR are reflected in `architecture.md` and in the relevant DES / spec files.
4. **Template and amendment style** — the ADR follows [ADR-000](../architecture/adr/ADR-000-template.md) (Context / Decision / Alternatives Considered / Consequences / References). A changed decision is an **in-place, dated amendment** of the existing ADR — an `**Amended**:` header line, an "Amendment — …" section, superseded text struck through and marked "Superseded by …" — as practiced in ADR-007; a **new** ADR is written only for a new decision.

## Severity vocabulary

- **PASS** — the check passed (note briefly what was checked)
- **INFO** — observation, no action required
- **WARN** — inconsistency to fix; suggest the fix
- **FAIL** — broken reference or contradiction, with file paths and line numbers

## Output format

One line per check, grouped by document, then the summary line
`N checks, N warnings, N failures`. Example:

```
spec-run.md
  PASS  FR ids unique and gap-free
  FAIL  §2 Commands lists an option that §4 Error Cases does not cover (spec-run.md:27 vs :384)
DES-005
  WARN  header Version not bumped although §4.6 changed
3 checks, 1 warning, 1 failure
```

## Where to post

- As a review comment on the pull request that changes the documents.
- For the pre-release audit, as a comment on the release or planning issue;
  the fixes are then committed on `develop` and the review is re-run until it
  reports 0 FAIL (WARN items are fixed or explicitly deferred).

## Changes from the former agent definition

- **(changed)** `CLAUDE.md` as the canonical index is replaced by `AGENTS.md`.
- **(changed)** Findings are reported in English (the former prompt said French, the maintainer's conversation language).
- **(changed)** The "run discipline" paragraph about the agent harness is dropped; its portable rule (highest-impact documents first, an explicit "Not yet covered" line) is kept.
- **(changed)** "OK" is written "PASS"; "INFO" is added for symmetry with the documentation review.
- **(added)** Spec check 10 (the Commands / FR / Error-cases triad), DES check 8 (headers, DD numbering) and ADR check 4 (template and amendment style) were not in the prompt; they restate conventions already written in `specifications.md` §2 and practiced in ADR-007 and the DES headers.
