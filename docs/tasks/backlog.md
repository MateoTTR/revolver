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
| 24 | DES-005 — `revolver run` design (unblocked by ADR-006) | [ ] | |
| 25 | DES-006 — `revolver eval` design (unblocked by ADR-006) | [ ] | |
| 26 | Implement wrapper evaluator generator (evaluate_instance → evaluate) | [ ] | |

## Phase 3 — POCs

| # | Task | Status | Session |
|---|---|---|---|
| 11 | POC — Local LLM deployment and inference | [x] | 003 |
| 12 | POC — OpenEvolve integration with instance injection | [x] | 007 |
| 13 | POC — OpenEvolve + Claude API | [ ] | |
| 14 | POC — Code generation quality with OpenEvolve + local LLM (quantization impact) | [ ] | |
| 15 | POC — End-to-end OpenEvolve + Ollama endpoint integration | [ ] | |

## Phase 4 — Validation

| # | Task | Status | Session |
|---|---|---|---|
| 16 | Validation strategy and test plan | [ ] | |
| 17 | Traceability matrix (specs → design → tests) | [ ] | |

## Phase 5 — Implementation

_Tasks to be defined after Phase 2-4 completion._
