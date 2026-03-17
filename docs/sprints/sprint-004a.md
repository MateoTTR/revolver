# Sprint 004a — Demo Feedback Fixes (v0.4.1 → v0.4.4)

**Status**: Complete
**Goal**: Stabilize the `revolver run` pipeline for real-world usage. Fix all blocking, major, and important findings discovered during demo sessions (v0.4.0 → v0.4.3). Ensure the full pipeline works end-to-end with real LLMs (Claude Sonnet, codestral:22b, qwen:7b).
**Trigger**: Demo v0.4.0 revealed a CRITICAL crash; subsequent demos (v0.4.2, v0.4.3) uncovered 11+ additional issues across config building, evaluation, program collection, and documentation.
**Sessions**: 025, 025b, 026
**Releases**: v0.4.1, v0.4.2, v0.4.3, v0.4.4

---

## Context

Sprint 004 delivered the `revolver run` command group with mocked OpenEvolve tests. When tested with real LLMs during demo sessions, multiple issues surfaced:

1. **Config building** — field name mismatches, missing keys, Revolver-specific keys leaking to OpenEvolve
2. **Evaluation** — post-run eval crashed with `evaluate_instance()` only evaluators, wrapper swallowed errors
3. **Result collection** — best_score null, programs not collected from `oe-output/best/`
4. **Missing safety** — no pre-flight check, cascade_evaluation default incompatible
5. **Template** — evaluator template generated with wrong signature

This sprint was executed reactively (hotfix-driven) across 3 sessions, with 4 releases and 3 demo validation cycles.

---

## Tasks

| # | Task | PR | Release | Findings | Status |
|---|---|---|---|---|---|
| S4a-01 | Fix dict→Config conversion in `OpenEvolveRunner._init_controller()` (CRITICAL crash) | #25 | v0.4.1 | Demo v0.4.0 | [x] |
| S4a-02 | Fix `dry-run iterations=0` fallback + `generation_time_s` null default | #25 | v0.4.1 | Demo v0.4.0 | [x] |
| S4a-03 | Add L2-OE integration tests (real OpenEvolve, no LLM) + fix config field mapping (`api_base`, `primary_model`, `max_iterations`) | #26 | v0.4.2 | Silent bugs | [x] |
| S4a-04 | Strip Revolver-specific keys (`evaluator`, `initial_program`) in `build_config()` + map `num_generations`→`max_iterations` | #27 | v0.4.3 | Demo v0.4.2 | [x] |
| S4a-05 | Inject `api_key="ollama"` for local LLMs, force `cascade_evaluation: false`, extract `best_score` from `Program.metrics` | #31 | v0.4.4 | F3, F5, F8 | [x] |
| S4a-06 | Fix program collection (`oe-output/best/`), post-run eval `evaluate_instance()` mode, wrapper error logging | #32 | v0.4.4 | F9, F6, F7 | [x] |
| S4a-07 | Add pre-flight evaluation check (evaluate initial program on first instance before OE launch) | #33 | v0.4.4 | F4 | [x] |
| S4a-08 | Fix evaluator template: correct `evaluate_instance(program_path, instance_path)` signature | #35 | v0.4.4 | F2/F7 template | [x] |
| S4a-09 | Update DES-005 (pre-flight, cascade_evaluation, api_key, collect_programs, best_score) + fix 5 stale items | #36 | v0.4.4 | Doc debt | [x] |
| S4a-10 | Update specs and validation docs (FR-PRJ-004, 13 new test scenarios, 13 traceability mappings) | #37 | v0.4.4 | Doc debt | [x] |

---

## PRs

| PR | Branch | Scope | Session | Release |
|---|---|---|---|---|
| #25 | `hotfix/v0.4.1` | S4a-01, S4a-02 | 025 | v0.4.1 |
| #26 | `feature/l2-oe-tests` | S4a-03 | 025, 025b | v0.4.2 |
| #27 | `hotfix/v0.4.3` | S4a-04 | 025b | v0.4.3 |
| #31 | `hotfix/v0.4.4-build-config` | S4a-05 | 026 | v0.4.4 |
| #32 | `hotfix/v0.4.4-eval-collection` | S4a-06 | 026 | v0.4.4 |
| #33 | `hotfix/v0.4.4-preflight` | S4a-07 | 026 | v0.4.4 |
| #35 | `hotfix/v0.4.4-template` | S4a-08 | 026 | v0.4.4 |
| #36 | `docs/s044-des005-update` | S4a-09 | 026 | v0.4.4 |
| #37 | `docs/s044-spec-validation-update` | S4a-10 | 026 | v0.4.4 |

---

## Demo validation cycles

| Demo | Version | Outcome | Findings |
|---|---|---|---|
| Demo v0.4.0 | v0.4.0 | CRITICAL crash on run launch | 1 critical + 2 minor |
| Demo v0.4.2 | v0.4.2 | Crash on Revolver-specific keys | 1 blocking |
| Demo v0.4.3 (Claude Sonnet) | v0.4.3 | First successful run; 11 findings (F1-F11) | 2 blocking, 2 major, 4 important, 3 minor |
| Demo v0.4.4 (validation) | v0.4.4 | 8/8 findings fixed; pipeline E2E OK | 0 regressions |
| Demo v0.4.4 (codestral) | v0.4.4 | Local LLM pipeline validated | NF1-NF4 (new) |
| Demo v0.4.4 (Gemini) | v0.4.4 | Google provider blocked by proxy | NF5-NF9 (new) |

---

## Sprint Review

**Completed: 2026-03-17** — All 10/10 tasks done across 3 sessions.

### Tests

- 24 new tests added (440 total, up from 410 at Sprint 004 end)
- 3 L2-OE integration tests (real OpenEvolve, no LLM)
- All 52 existing L2 integration tests still passing

### Key outcomes

- **Pipeline validated E2E** with 3 real LLMs (Claude Sonnet, codestral:22b, qwen:7b)
- **First successful optimization**: TSP tour reduced 8.3% with Claude Sonnet (3 iterations)
- **Local LLM validated**: codestral:22b achieves 100% valid diffs with structured initial program
- **4 releases** in 2 days (rapid iteration cycle proven)
- **Draft PR workflow** adopted (create draft → fix review → ready → merge)
- **L2-OE test strategy** established (real OpenEvolve, `importorskip`, CI non-blocking)

### Carry-over (not addressed)

| Item | Severity | Reason deferred |
|---|---|---|
| NF5 — Proxy masks Google URL → seed rejected | BLOQUANT | Discovered at end of session 026; requires design decision |
| NF7 — Proxy 502 for all upstream errors | MOYEN | Proxy architecture change |
| NF6 — `_parse_value()` no null/none support | MOYEN | Trivial but out of scope for F3-F9 fix cycle |
| NF8 — No Retry-After header respect | MOYEN | Requires proxy + possibly OpenEvolve changes |
| NF1 — False positive wrapper warning | MINEUR | UX only |
| NF2 — Alias absent from `run list --json` | MINEUR | UX only |
| NF4 — Initial program structure best practices | DOC | Documentation only |

These items are scheduled for Sprint 004b.
