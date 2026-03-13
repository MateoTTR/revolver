---
name: traceability-check
description: Check consistency and traceability across Revolver documentation (ConOps, specs, DES, architecture, backlog)
disable-model-invocation: true
argument-hint: "[scope: all|specs|adrs|des|backlog]"
---

Run a traceability and consistency check across Revolver documentation.
Scope: $ARGUMENTS (default: all)

## Checks to perform

### 1. ADR consistency
- Every ADR listed in `CLAUDE.md` ADR table exists as a file in `docs/architecture/adr/`
- Every ADR file in `docs/architecture/adr/` (except template) is listed in `CLAUDE.md`
- Every ADR referenced in `docs/architecture/architecture.md` matches `CLAUDE.md`
- ADR status (Accepted/Proposed/Deprecated) is consistent across all references

### 2. Spec consistency
- Every spec file listed in `docs/specs/specifications.md` §5 exists
- Every `spec-*.md` file in `docs/specs/` is listed in `specifications.md`
- NFR IDs referenced in spec files exist in `specifications.md` §3
- FR IDs within each spec file are unique and follow the naming convention (FR-XXX-NNN)
- No duplicate FR IDs across all spec files
- FR IDs referenced in DES documents exist in the corresponding spec file

### 3. DES consistency
- Every DES listed in `CLAUDE.md` DES table exists as a file in `docs/architecture/design/`
- Every DES file in `docs/architecture/design/` (matching `DES-*.md`) is listed in `CLAUDE.md`
- Every DES referenced in `docs/architecture/architecture.md` §10 matches `CLAUDE.md`
- DES status (Draft/Final/Deprecated) is consistent across all references
- Design Decisions (DD-NN) within each DES file are sequentially numbered and unique within that DES
- Cross-DES references (e.g., DES-005 referencing DES-003) point to existing DES documents

### 4. ConOps to Specs traceability
- Every ConOps section listed in the traceability matrix (specifications.md §6) has corresponding FRs
- Open questions in ConOps that are marked resolved have corresponding ADRs or decisions

### 5. Architecture to Specs traceability
- Components in architecture.md reference relevant spec files or NFRs
- Technology choices in architecture.md have corresponding ADRs
- DES documents reference the spec files listed in their "Traceable to" header
- DES design decisions don't contradict spec functional requirements

### 6. Backlog consistency
- Task numbers are unique and sequential
- Completed tasks have a session number
- Session numbers in backlog match existing session reports

### 7. CLAUDE.md consistency
- Open questions marked [x] have the decision documented
- Phase statuses match actual progress (check backlog completion)

## Output format

Report findings as:
- OK: (check passed)
- WARN: (minor inconsistency, non-blocking)
- FAIL: (missing reference, broken traceability)

Summarize with counts: N checks passed, N warnings, N failures.
For each WARN/FAIL, provide the specific file, line, and suggested fix.
