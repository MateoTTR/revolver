# Revolver — Task Backlog

## Phase 1 — Cadrage

| # | Task | Status | Session |
|---|---|---|---|
| 1 | ConOps — Initial brainstorm and draft | [x] | 001 |
| 2 | ConOps — User review and refinements | [x] | 002 |
| 3 | Functional specifications — Draft | [x] | 003 |
| 4 | Functional specifications — Review | [x] | 004 |

## Phase 2 — Architecture

| # | Task | Status | Session |
|---|---|---|---|
| 5 | ADR-001 — Ollama as local LLM backend (decision + tradeoffs from POC) | [x] | 004 |
| 6 | ADR-002 — Programming language (Python >= 3.11) | [x] | 004 |
| 7 | ADR-003 — CLI framework (Typer) | [x] | 005 |
| 8 | Design `revolver llm` subcommands based on Ollama API mapping | [x] | 006 |
| 9 | Architecture overview — Draft | [x] | 005 |
| 10 | Data model — Detailed design | [x] | 005 |
| 18 | ADR-004 — SQLite as structured storage | [x] | 006 |
| 19 | ADR-005 — Pydantic v2 for data models | [x] | 006 |
| 20 | DES-003 — `revolver problem` testing & versioning design | [x] | 006 |
| 21 | DES-004 — `revolver dataset` registration & integrity design | [x] | 006 |
| 22 | Restructure architecture docs (DES-NNN convention) | [x] | 006 |
| 23 | Update spec-dataset with `dataset remove` command | [x] | 006 |
| 24 | DES-005 — `revolver run` design (unblocked by ADR-006) | [x] | 008 |
| 25 | DES-006 — `revolver eval` design (unblocked by ADR-006) | [x] | 008 |
| 26 | ~~Implement wrapper evaluator generator~~ → moved to Phase 5 | — | |
| 27 | Update ConOps §4.1 directory structure for DD-07 (top-N → separate solution dirs) | [x] | 010 |
| 28 | Review remaining spec-reviewer WARNs (ER diagram, benchmark JSON rank/run_id) | [x] | 010 |
| 29 | Refactor: introduce Run entity + Solution as reference (per refactor-run-solution.md) | [x] | 010 |
| 30 | DES-007 — `revolver benchmark` design (after run/solution refactor) | [x] | 011 |
| 31 | Review DES-005/006 decisions (D-005-a..h, D-006-a..f) into updated docs | [x] | 010 |
| 32 | Integrate `problem.md` feature into ConOps, spec-problem, DES-003, DES-005 | [x] | 012 |
| 33 | Refactor top-N → extract on demand (spec-run, DES-005, spec-solution, DES-001, ConOps) | [x] | 013 |
| 34 | Token/cost tracking — lightweight requirement + design integration | [x] | 014 |

## Phase 3 — POCs

| # | Task | Status | Session |
|---|---|---|---|
| 11 | POC — Local LLM deployment and inference | [x] | 003 |
| 12 | POC — OpenEvolve integration with instance injection | [x] | 007 |
| 13 | POC — OpenEvolve + Claude API | [x] | 012 |
| 14 | POC — Code generation quality with OpenEvolve + local LLM (quantization impact) | [~] Covered by POC #11/12/13 | |
| 15 | POC — End-to-end OpenEvolve + Ollama endpoint integration | [~] Covered by POC #11/12/13 | |

## Phase 4 — Validation

| # | Task | Status | Session |
|---|---|---|---|
| 16 | Validation strategy and test plan | [x] | 015 |
| 17 | Traceability matrix (specs → design → tests) | [x] | 015 |

## Phase 5 — Implementation

| # | Task | Status | Session |
|---|---|---|---|
| 26 | Implement wrapper evaluator generator (evaluate_instance → evaluate) | [ ] | |

_Additional tasks to be defined after Phase 2-4 completion._
