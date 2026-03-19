# Sprint 006a — Demo v0.6.0 Feedback Fixes

**Status**: Complete
**Goal**: Fix 4 findings from demo v0.6.0 benchmark session: eval_id collision (BLOCKING), illegible benchmark tables (MAJOR), wrong default metric in per-instance view (MEDIUM), and missing `--all` shortcut (MEDIUM). Target release: v0.6.1.
**Demo**: Run `revolver benchmark --all --dataset tsp-eval` (no workaround needed); view `benchmark results --latest` with readable combined_score table; `benchmark results --latest --metric all` for full detail; `benchmark results --per-instance --latest` showing combined_score by default.

---

## Scope

### Command groups affected
- `revolver eval` — eval_id generation (collision fix)
- `revolver benchmark` — display filtering, new CLI options

### Feedback items addressed

| ID | Finding | Severity | Source |
|---|---|---|---|
| F1 | `generate_eval_id()` collision when benchmark evaluates 2+ solutions in same second | **BLOQUANT** | Demo v0.6.0 |
| F4 | `benchmark results` displays 27 columns — illegible without `--metric` | **MAJEUR** | Demo v0.6.0 |
| F5 | `benchmark` inline output (same as F4 — trop de colonnes) | **MAJEUR** | Demo v0.6.0 |
| F6 | `benchmark results --per-instance` defaults to `baseline_length` instead of `combined_score` | **MOYEN** | Demo v0.6.0 |
| F7 | `--solutions` requires long repetition, no `--all` flag | **MOYEN** | Demo v0.6.0 |

### Explicitly out of scope

| Item | Reason |
|---|---|
| F2 — Soften split='train' warning | Nice-to-have, deferred |
| F3 — Soften version compatibility warning | Nice-to-have, deferred |
| F8 — `benchmark delete` | Nice-to-have, deferred |
| F9/F10 — Alias truncation in list views | Nice-to-have, deferred |

---

## Tasks

| # | Task | PR | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| 141 | **F1-fix** — `generate_eval_id(suffix)` + retry loop on `IntegrityError` (same pattern as `generate_benchmark_id()`) | #68 | — | [x] | 701 tests pass, ruff/mypy clean |
| 142 | **F4/F5-fix** — Default `benchmark` inline + `benchmark results` aggregate to `combined_score` only. Support `--metric all`. | #69 | — | [x] | No breaking change on CSV/JSON export |
| 143 | **F6-fix** — Default `benchmark results --per-instance` to `combined_score` instead of first alphabetical metric. | #69 | — | [x] | Per-instance shows combined_score by default |
| 144 | **F7-fix** — Add `--all` flag (resolve all project solutions). Accept `--solutions A,B,C` (comma-separated). Mutual exclusion guard. | #69 | — | [x] | `--all` + `--solutions` exits code 1 |

---

## Integration Tests (L2)

| Component | Scenario | Test ID | PR |
|---|---|---|---|
| `generate_eval_id` | Format without suffix | `test_format_without_suffix` | #68 |
| `generate_eval_id` | Format with suffix | `test_format_with_suffix` | #68 |
| `generate_eval_id` | No suffix when None | `test_no_suffix_when_none` | #68 |
| `generate_eval_id` | Distinct IDs with different suffixes | `test_suffix_produces_distinct_ids` | #68 |
| `benchmark` CLI | `--all` resolves all solutions | `test_benchmark_all_flag` | #69 |
| `benchmark` CLI | Comma-separated `--solutions` | `test_benchmark_comma_separated_solutions` | #69 |
| `benchmark` CLI | Default to combined_score in results | `test_results_defaults_to_combined_score` | #69 |
| `benchmark` CLI | `--metric all` shows all columns | `test_results_metric_all_shows_everything` | #69 |
| `benchmark` CLI | `--all` with empty project exits 1 | `test_benchmark_all_no_solutions` | #69 |
| `benchmark` CLI | `--all` + `--solutions` mutual exclusion | `test_benchmark_all_and_solutions_exclusive` | #69 |

---

## Parallelization

### Dependency graph

```
Sprint 006 complete (v0.6.0)
  │
  ├──> PR #68: eval_id collision fix (F1)
  │         generate_eval_id(suffix) + retry loop
  │         Files: core/eval.py, tests/unit/test_core_benchmark.py
  │
  └──> PR #69: Benchmark UX fixes (F4-F7)
              Default metric filtering + --all flag + comma-separated
              Files: cli/benchmark.py, tests/integration/test_benchmark.py
```

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — eval_id collision | F1-fix (#141) | Sprint 006 done | Agent 1 (worktree) |
| B — Benchmark UX | F4-F7 (#142-144) | Sprint 006 done | Agent 2 (worktree) |

Peak parallelism: 2 agents simultaneously (no file overlap).

### Conflict risks
- **None** — PR #68 modifies `core/eval.py`, PR #69 modifies `cli/benchmark.py`. No shared files.

### Merge order
- Any order (fully independent).

---

## Sprint Review

### Tests passing
- PR #68: 701 tests (697 existing + 4 new)
- PR #69: 703 tests (697 existing + 6 new)

### PRs merged
| PR | Branch | Scope | Session |
|---|---|---|---|
| #68 | `feature/s6b-eval-id-collision` | F1 | session 031 |
| #69 | `feature/s6b-benchmark-ux` | F4, F5, F6, F7 | session 031 |

### Demo-able features
- [ ] `revolver benchmark --all --dataset <name>` works without listing every solution
- [ ] `revolver benchmark --solutions A,B,C --dataset <name>` accepts comma-separated
- [ ] `revolver benchmark` inline table shows only combined_score (readable)
- [ ] `revolver benchmark results --latest` shows combined_score by default
- [ ] `revolver benchmark results --latest --metric all` shows all metrics
- [ ] `revolver benchmark results --per-instance --latest` defaults to combined_score
- [ ] No more `IntegrityError` when evaluating multiple solutions in same second
