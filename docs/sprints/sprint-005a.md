# Sprint 005a — Demo v0.5.0 Feedback Fixes

**Status**: Complete
**Goal**: Fix 4 findings from demo v0.5.0: API key leak in config_snapshot (SECURITY), incomplete Google seed fix (BLOCKING), interrupted status on post-processing crash (MAJOR), missing solution delete command (MEDIUM). Target release: v0.5.1.
**Demo**: Verify `solution info --json` no longer exposes API keys; launch a Gemini run without `--config-override random_seed=null`; trigger a post-processing failure and verify `completed_with_errors` status; delete a solution via CLI.

---

## Scope

### Command groups affected
- `revolver run` — config building (`build_config()`), post-run processing, status management
- `revolver solution` — new `delete` subcommand, `extract` relaxed status check

### Key FRs covered
- FR-RUN-006 — Configure OpenEvolve LLM endpoint from registry (api_key handling)
- FR-RUN-006 — Google provider detection (top-level `random_seed`)
- FR-RUN-017/018 — Run completion status and error handling
- FR-SOL-011..013 — Solution extraction (relaxed for `completed_with_errors`)
- NEW — `solution delete` command

### Feedback items addressed

| ID | Finding | Severity | Source |
|---|---|---|---|
| F1 | API keys stored in cleartext in `config_snapshot` (SQLite + JSON) | **SÉCURITÉ** | Demo v0.5.0 |
| F2 | Fix v0.4.5 seed Google targets `llm.random_seed` instead of top-level `random_seed` | **BLOQUANT** | Demo v0.5.0 |
| F3 | Run marked `interrupted` when post-processing crashes (OE completed) | **MAJEUR** | Demo v0.5.0 |
| F4 | No `solution delete` command | **MOYEN** | Demo v0.5.0 |

### Explicitly out of scope

| Item | Reason |
|---|---|
| F5 — Gemini free tier quota | Observation only, no code change needed |
| Proxy-level `seed` filtering | Addressed at config level (F2); proxy filtering is defense-in-depth for later |
| `_post_run_evaluation` → `core.eval` wiring (S5-08 carry-over) | Sprint 006 |
| `--json` on subcommands | Sprint 007 (S7-05, task #102) |

---

## Tasks

| # | Task | PR | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| 136 | **F1-fix** — Store `api_key_env` name instead of resolved value in `build_config()`. Add `resolve_api_keys()` helper. | A (#56) | — | [x] | PR #56 merged, 8 tests |
| 137 | **F2-fix** — Set `config["random_seed"] = None` (top-level) for Google providers. | A (#56) | — | [x] | PR #56 merged, tests updated |
| 138 | **F3-fix** — Add `completed_with_errors` status, schema migration v2, `_handle_post_run_failure()`, `run-error.log`. | B (#57) | — | [x] | PR #57 merged, 7 tests |
| 139 | **F3-extract** — Relax `extract_solution()` to accept `completed_with_errors` runs. | B (#57) | 138 | [x] | PR #57 merged, 2 integration tests |
| 140 | **F4-delete** — `solution delete` with confirmation, `--force`, cascade eval deletion. | C (#55) | — | [x] | PR #55 merged, 8 tests |

---

## Integration Tests (L2)

| Component | Scenario | Test ID | Status |
|---|---|---|---|
| `build_config` | API key env name stored, not resolved value | `test_build_config_stores_api_key_env_not_value` | Planned |
| `build_config` | `_resolve_api_keys()` resolves env var from config | `test_resolve_api_keys_from_env` | Planned |
| `build_config` | Google LLM → top-level `random_seed=None` | `test_build_config_google_disables_toplevel_seed` | Planned |
| `launch_run` | config_snapshot in DB contains no cleartext API key | `test_run_config_snapshot_no_api_key` | Planned |
| `core.run` | Post-processing failure → `completed_with_errors` + error log | `test_run_postprocessing_failure_status` | Planned |
| `core.run` | Normal completion → `completed` (regression) | `test_run_normal_completion_status` | Planned |
| `solution extract` | `completed_with_errors` run with program → succeeds | `test_extract_solution_completed_with_errors` | Planned |
| `solution extract` | `completed_with_errors` run without program → fails | `test_extract_solution_no_program_fails` | Planned |
| `solution delete` | Delete by alias → removed from DB | `test_solution_delete_by_alias` | Planned |
| `solution delete` | Delete cascade-removes eval results | `test_solution_delete_cascades_eval` | Planned |
| `solution delete` | Non-existent alias → error | `test_solution_delete_nonexistent_error` | Planned |

---

## Parallelization

### Dependency graph

```
Sprint 005 complete (v0.5.0)
  │
  ├──> PR A: Security + Google seed fix (F1, F2)
  │         F1 (api_key_env in build_config + resolve helper)
  │         F2 (top-level random_seed=None for Google)
  │         Files: infra/openevolve.py, core/run.py
  │
  ├──> PR B: Post-run error handling (F3)
  │         F3-fix (completed_with_errors status + error logging)
  │           ↓
  │         F3-extract (relaxed extract_solution)
  │         Files: infra/db.py (schema migration), core/run.py, core/solution.py, models/run.py
  │
  └──> PR C: Solution delete (F4)
              F4-delete (core + db + cli)
              Files: infra/db.py (new query), core/solution.py, cli/solution.py
```

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Security + seed fix | F1-fix (#136), F2-fix (#137) | Sprint 005 done | Agent 1 (worktree) |
| B — Error handling | F3-fix (#138), F3-extract (#139) | Sprint 005 done | Agent 2 (worktree) |
| C — Solution delete | F4-delete (#140) | Sprint 005 done | Agent 3 (worktree) |

Peak parallelism: 3 agents simultaneously (all streams independent).

### Conflict risks
- **`infra/openevolve.py`** — PR A only (F1 + F2 in `build_config()`). No conflict with PR B or C.
- **`core/run.py`** — PR A (F1: `_resolve_api_keys()` call in `launch_run()`) and PR B (F3: try/except in post-processing). Different sections of `launch_run()` — low conflict risk. Merge PR A first (smaller, targeted changes), then PR B.
- **`infra/db.py`** — PR B (F3: schema migration, `update_run_status` type hint) and PR C (F4: `delete_solution` query). Different functions — low conflict risk. Merge PR B first (schema change).
- **`core/solution.py`** — PR B (F3-extract: relaxed status check) and PR C (F4: `delete_solution()`). Independent functions — no conflict.

### Merge order
1. **PR A** (F1 + F2) — no dependencies
2. **PR B** (F3) — after PR A (core/run.py overlap)
3. **PR C** (F4) — after PR B (infra/db.py overlap)

---

## Sprint Review

### Tests passing
- 567 tests passing (all PRs merged into develop)
- 17 new tests added (5 integration + 7 unit for F3, 5 integration for F4)

### PRs merged
| PR | Branch | Scope | Sessions |
|---|---|---|---|
| #56 | `feature/s5a-security-seed-fix` | F1, F2 | session 029 |
| #55 | `feature/s5a-solution-delete` | F4 | session 029 |
| #57 | `feature/s5a-error-handling` | F3 | session 029 |

### Demo-able features
- [x] `build_config()` stores `api_key_env: ANTHROPIC_API_KEY` (no cleartext key in config_snapshot)
- [x] Google provider: top-level `random_seed=None` set in addition to `llm.random_seed`
- [x] Post-processing failure → `completed_with_errors` + `run-error.log`
- [x] `solution extract` works on `completed_with_errors` runs
- [x] `revolver solution delete <alias>` with confirmation + `--force`
- [x] Warning emitted when `api_key_env` is set but env var is missing

### Carry-over
- Gemini run without `--config-override random_seed=null` not yet tested in demo (needs v0.5.1 release + demo)
- Schema migration v2 not tested on real v1 database (unit tests cover fresh DBs only)
