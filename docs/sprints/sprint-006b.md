# Sprint 006b — Demo v0.6.1 Feedback Fixes

**Status**: Complete
**Goal**: Fix 4 residual findings from demo v0.6.1 feedback: wide table tip (MINOR), benchmark delete (MINOR), alias column width (MINOR), and pull timeout (MINOR). Single PR, single release.
**Demo**: `revolver benchmark delete <id>` works; `benchmark list` and `solution list` show full aliases; `llm add --pull` succeeds on large models.

---

## Scope

### Feedback items addressed

| ID | Finding | Severity | Source |
|---|---|---|---|
| F4b | `--metric all` output is unreadable in standard terminals — add tip | **MINOR** | Demo v0.6.1 |
| F8 | No `benchmark delete` command — benchmarks accumulate without cleanup | **MINOR** | Demo v0.6.0 |
| F9/F10 | Alias columns truncated in `benchmark list` and `solution list` | **MINOR** | Demo v0.6.0 |
| NEW | `llm add --pull` crashes with ReadTimeout on large models (>10 GB) | **MINOR** | Demo v0.6.1 |

### Explicitly out of scope

| Item | Reason |
|---|---|
| F2 — Soften split='train' warning | Nice-to-have, deferred |
| F3 — Soften version compatibility warning | Message is fine as-is |
| OpenEvolve version pinning | User prefers unpinned |

---

## Tasks

| # | Task | PR | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| 145 | **F4b-fix** — Add tip in `--metric all` help text for wide table handling | #71 | — | [x] | Help text mentions `--format csv` or `less -S` |
| 146 | **F8-fix** — `benchmark delete`: DB cascade (`benchmark_solutions`), core function, CLI command with `--force` | #71 | — | [x] | Delete removes benchmark + junction rows, confirmation prompt |
| 147 | **F9/F10-fix** — Dynamic alias column width in `infra.output` render (rich Table `no_wrap`) | #71 | — | [x] | Alias columns not truncated in list views |
| 148 | **Pull-timeout-fix** — Override httpx timeout to `None` for `pull_model()` stream | #71 | — | [x] | `llm add --pull` does not timeout on large models |

---

## Integration Tests (L2)

| Component | Scenario | Test ID | PR |
|---|---|---|---|
| `benchmark delete` | Delete with confirmation prompt (user accepts) | `test_benchmark_delete_confirm_prompt` | #71 |
| `benchmark delete` | Delete non-existent benchmark exits with error | `test_benchmark_delete_nonexistent` | #71 |
| `benchmark delete` | Delete with `--force` skips confirmation, cleans junction table | `test_benchmark_delete_force` | #71 |

---

## Parallelization

Single PR — no parallelization needed. All 4 fixes in one branch.

### Files modified

| Fix | Files |
|---|---|
| F4b | `src/revolver/cli/benchmark.py` |
| F8 | `src/revolver/infra/db.py`, `src/revolver/core/benchmark.py`, `src/revolver/cli/benchmark.py` |
| F9/F10 | `src/revolver/infra/output.py` |
| Pull timeout | `src/revolver/infra/ollama.py` |

---

## Sprint Review

### Tests passing
- PR #71: 710 tests (703 existing + 7 new)

### PRs merged
| PR | Branch | Scope | Session |
|---|---|---|---|
| #71 | `feature/s6b-feedback-fixes` | F4b, F8, F9/F10, pull timeout | session 032 |

### Demo-able features
- [x] `revolver benchmark delete <id>` deletes benchmark and junction rows
- [x] `revolver benchmark delete <id>` prompts for confirmation (unless `--force`)
- [x] `benchmark list` and `solution list` show full aliases
- [x] `--metric all` help text includes tip for wide output
- [x] `llm add --pull` does not timeout on large models
