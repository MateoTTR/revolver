# Process checklists

This directory holds the project's development-process procedures in a
tool-neutral form. Each file is a checklist that a human can execute with a
terminal, a browser and the repository alone; no AI agent, editor plug-in or
automation is assumed. Agents of any kind may follow the same files.

The entry point for the whole project is [`AGENTS.md`](../../AGENTS.md); the
rationale for this layout is
[ADR-008](../architecture/adr/ADR-008-documentation-and-process-strategy.md).

## Index

| Procedure | File | When |
|---|---|---|
| Code review | [code-review.md](code-review.md) | Every pull request, before it is marked ready; also the author's self-review |
| Specification review | [spec-review.md](spec-review.md) | A spec, DES or ADR file changed; before a release |
| Validation review | [validation-review.md](validation-review.md) | A validation document or a spec changed; before a release (includes the cross-document traceability sweep) |
| Documentation review | [doc-review.md](doc-review.md) | After a release; README / guides / E2E walkthrough changed; CLI source changed |
| Sprint planning | [sprint-planning.md](sprint-planning.md) | Sprint boundaries: planning issue, milestone, sprint review |
| Release and hotfix | [release.md](release.md) | Tagging a version; shipping a critical fix |
| Definition of Done | [definition-of-done.md](definition-of-done.md) | Any feature pull request; a new evolution backend |

## Common conventions

Every checklist states what to have open (**inputs**), the **steps** to run, its
**severity vocabulary**, the **output format** and **where to post** the result;
headings vary slightly from file to file.

Two severity vocabularies are used, one per kind of review:

| Review | Vocabulary | Meaning |
|---|---|---|
| Code review | **CRITICAL** / **WARNING** / **SUGGESTION** / **GOOD** | Must fix before merge / should fix / nice to have / positive pattern worth noting |
| Document reviews (spec, validation, doc) | **FAIL** / **WARN** / **INFO** / **PASS** | Broken reference or factual error / inconsistency to fix / observation, no action / check passed |

A pull request is marked ready only with **0 CRITICAL** findings; every
WARNING is fixed in the pull request or carried over explicitly in its
description. Document reviews end with a count line
("N checks, N warnings, N failures"); a release requires 0 FAIL.

Reviews are written in **English** and posted where the reviewed change
lives: a pull-request review with inline comments for code; a comment on the
pull request, or on the planning issue when the review runs outside a pull
request, for documents.

## Public-file rule

Everything committed to this repository is public. No committed file may
contain a local filesystem path, a machine or runner hostname, a private
repository name, an e-mail address, personal timing data, GitHub handles of
third parties, or business-domain vocabulary. Use neutral wording ("a local
path", "a network Ollama host", "a separate demo repository", "a third-party
endpoint shim"). The rule applies to pull-request descriptions, issue bodies
and review comments as well, since they are part of the public record.

## Provenance

These checklists were extracted at v0.19.0 from the maintainer's former
agent definitions (code, spec, validation and doc reviewers, sprint planner)
and from the release and hotfix sections of the former `CLAUDE.md`, as
decided in ADR-008 (D4, D5). Each file keeps the original checks. Every point
that was dropped, reworded or added during the extraction is listed at the
end of the file under "Changes from the former agent definition", so the
extraction can be audited. One systematic rename: the former prompts wrote
`OK` for a passed check; these files write `PASS`.
