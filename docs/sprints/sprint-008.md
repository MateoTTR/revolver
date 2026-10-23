# Sprint 008 — Reliability & Lifecycle Management (v0.8.0)

**Status**: Planning
**Goal**: Fix the two most critical reliability bugs found in the multi-model TSP benchmark (timeout_per_instance not propagated in wrapper, post-"Evolution completed" hang), and add the lifecycle management commands that were blocking scripted benchmarks (`--force` on remove commands, `run delete`, API key pre-flight gate). Target release: v0.8.0.
**Demo**: `revolver llm remove my-llm --force` exits 0 without prompt; `revolver run delete run-20260321-123456 --force` removes run + solutions + files; `revolver run start` aborts with a clear error when `GEMINI_API_KEY` is unset; `problem test` works with evaluators using `evaluate_instance()` signature; wrapper loops with per-instance timeout; no hang after "Evolution completed".

---

## Source

- Demo feedback: `feedback.md` of the TSP multi-model benchmark demo (private demo repository)
- Version tested: v0.7.1
- Date: 2026-03-21
- B1 repro script: `repro-b1-hang.py` (private demo repository)

---

## B1 Investigation — Post-"Evolution completed" Hang

### Root cause (confirmed via code analysis + reproduction)

The hang occurs in OpenEvolve's `ProcessParallelController.stop()` at `executor.shutdown(wait=True)` (file `process_parallel.py:412`). This call blocks **indefinitely** until all worker processes complete.

**Sequence:**
1. OE logs "✅ Evolution completed" (`process_parallel.py:769`) — evolution loop is done
2. `controller.run()` enters `finally` block, calls `parallel_controller.stop()` (`controller.py:376`)
3. `stop()` calls `executor.shutdown(wait=True)` (`process_parallel.py:412`)
4. **Worker processes still running** (in SDK retry loop or evaluating a toxic program) block shutdown

**Why `future.cancel()` doesn't help:** Python's `ProcessPoolExecutor` cannot cancel a future that is already executing — `cancel()` returns `False` for running tasks.

### Evidence from benchmark logs

The Gemini Flash run (`run-20260321-140816`) shows the exact pattern:
- `15:22:59` — "✅ Evolution completed - Shutdown requested"
- `15:23:01..15:23:04` — Worker **continues retrying 429s** via OpenAI SDK backoff loop after shutdown signal
- The SDK retry loop ignores the `shutdown_event` entirely

For the 8 other benchmark runs, `Stopped process pool` arrived 3-5ms after "Evolution completed" — the hang is **not systematic**, it requires a worker to be mid-execution at shutdown time.

### Reproduction (2026-03-21)

Script: `repro-b1-hang.py --scenario retry`

```
19:22:54 — "✅ Evolution completed"
19:22:54 — future.cancel() → "FAILED (already running)" on all 3 workers
19:22:54 — executor.shutdown(wait=True) called → BLOCKS
19:23:21 — Workers still retrying (27s+ after shutdown)
           → killed by external timeout (exit 124)
```

**B1 reproduced.** The `retry` scenario (simulating OpenAI SDK backoff on 429) reproduces the hang deterministically. The `toxic` scenario (subprocess that hangs) also reproduces it.

### Validated mitigation (S8-04)

Wrap the entire `asyncio.run(controller.run())` call in a `ThreadPoolExecutor` with a **computed** timeout:

```python
# Computed from run config
budget_per_iter = evaluator_timeout + llm_timeout + 30  # buffer
watchdog_timeout = int(iterations * budget_per_iter * 1.2)  # 20% margin

watchdog = ThreadPoolExecutor(max_workers=1)
future = watchdog.submit(lambda: asyncio.run(controller.run(...)))
try:
    best = future.result(timeout=watchdog_timeout)
except TimeoutError:
    # Force kill OE + orphan worker processes
    for child in psutil.Process(os.getpid()).children(recursive=True):
        child.kill()
```

Tested: stuck worker killed cleanly in exactly 5s, exit code 0. Run would be marked `interrupted`.

**Why a computed global timeout (not shutdown-only):** We cannot intercept `parallel_controller.stop()` because the `parallel_controller` is created inside `controller.run()`, not in `__init__`. A global timeout is the only reliable way to wrap the opaque `asyncio.run()` call. The computed value (`iterations × per-iter budget × 1.2`) ensures legitimate long runs are not killed, while hangs are caught after the expected max duration.

### Conclusion

The bug is in OpenEvolve (`ProcessPoolExecutor.shutdown(wait=True)` with no timeout). Revolver mitigates via watchdog (S8-04) + per-instance timeout in wrapper (S8-03). An upstream OE fix (e.g., `shutdown(wait=False)` + explicit worker kill) would be the proper solution.

---

## Findings from benchmark demo

| ID | Severity | Area | Description | Sprint action |
|---|---|---|---|---|
| B3 | CRITICAL | infra | `timeout_per_instance` not propagated into `_revolver_evaluator.py` | Fix wrapper template |
| B1 | CRITICAL | infra | Post-"Evolution completed" hang — OE worker doesn't join after toxic program | **Upstream issue** (not a Revolver fix) |
| B4 | MAJOR | infra | `problem test` rejects `evaluate_instance()` evaluators (`evaluator_loader.py` line 47) | Fix loader check |
| F1 | MAJOR | core | Missing API key → warning instead of fatal error | Convert to fatal error |
| FR4 | MEDIUM | cli | `llm remove` / `dataset remove` have no `--force`/`--yes` for scripting | Add `--force` flag |
| FR5 | MEDIUM | infra | FK constraints and CASCADE not enforced in SQLite | Enable FK + migration v5 |
| FR1 | MEDIUM | cli | `run delete <id>` command missing | Implement command |
| P3 | LOW | cli | Silent post-run eval phase gives no feedback | Add progress message |

---

## Scope

### Command groups included
- `revolver llm remove` — add `--force`/`--yes` flag
- `revolver dataset remove` — add `--force`/`--yes` flag
- `revolver run` — new `delete` subcommand
- `revolver problem test` — fix `evaluate_instance()` support
- `revolver run` (launch) — fatal error on missing API key

### Key FRs covered
- FR-LLM-006 — `llm remove` (extended: scripting support)
- FR-DAT-010 — `dataset remove` (extended: scripting support)
- FR-RUN-027 — run cleanup / delete
- FR-PRB-007 — `problem test` evaluate_instance support
- NFR-001 — exit codes and error reporting
- NFR-016 — data integrity (FK constraints)

---

## Tasks

| # | Task | Layer | Depends on | PR | Status | Acceptance criteria |
|---|---|---|---|---|---|---|
| S8-01 | Fix `evaluator_loader.py`: accept `evaluate_instance(program_path, instance_path)` as a valid evaluator signature (in addition to `evaluate(program_path)`). Update docstring. | infra | — | PR-A | [ ] | `problem test --instance inst.json` works with an evaluator that only defines `evaluate_instance()`; `EvaluatorLoadError` raised only when neither function is present |
| S8-02 | Fix `resolve_api_keys()` in `infra/openevolve.py`: convert missing-key warning to `ValidationError` (fatal). Check is performed before OpenEvolve is launched. | infra | — | PR-B | [ ] | `revolver run` with unset `GEMINI_API_KEY` exits with code 2 and a clear Revolver error message before any OE process starts |
| S8-03 | Propagate `timeout_per_instance` into `_WRAPPER_TEMPLATE` in `core/run.py`. Read value from `config["evaluator"]["timeout_per_instance"]` at wrapper generation time; default to `None` (no timeout) if absent. Wrap each `evaluate_instance()` call in the loop with `signal.alarm()` or `multiprocessing.Process` with timeout. | infra | — | PR-C | [ ] | Wrapper generated with a per-instance timeout guard; instance that hangs is killed after N seconds; `_revolver_evaluator.py` includes the injected timeout value; unit test confirms value is rendered |
| ~~S8-04~~ | ~~OE watchdog timeout~~ — **Removed**: B1 is an OpenEvolve bug (`ProcessPoolExecutor.shutdown(wait=True)` with no timeout). Root cause confirmed and reproduced (see B1 Investigation above). Filed as upstream issue on OpenEvolve. Any Revolver-side workaround would have poor UX regardless of timeout strategy. | — | — | — | [~] | N/A — tracked upstream |
| S8-05 | Add `--force` / `--yes` flag to `revolver llm remove`. Skip interactive confirmation when set. Existing behaviour (no flag) is unchanged. | cli | — | PR-D | [ ] | `revolver llm remove my-llm --force` exits 0 without any prompt; `revolver llm remove my-llm` still shows confirmation (if confirmation exists) or removes silently as today |
| S8-06 | Add `--force` / `--yes` flag to `revolver dataset remove`. Same pattern as S8-05. | cli | — | PR-D | [ ] | `revolver dataset remove my-ds --force` exits 0 without prompt; existing behaviour unchanged |
| S8-07 | DB migration v5: add `ON DELETE CASCADE` to FK constraints on `solutions`, `eval_metadata`, `eval_instances`, `benchmark_solutions`. SQLite requires table recreation. Also add `ON DELETE CASCADE` to `dataset_instances` and `dataset_compat`. Update `CURRENT_SCHEMA_VERSION` to 5. | infra | — | PR-E | [ ] | Deleting a run row cascades to `solutions`, `eval_metadata`, `eval_instances`; deleting a dataset cascades to `dataset_instances`, `dataset_compat`; migration runs cleanly on existing v4 DBs; new tests confirm cascades |
| S8-08 | Implement `core.run.delete_run(run_id, force, project_root)` — domain function that: (1) verifies run exists; (2) collects associated solution IDs and eval IDs; (3) deletes run directory from disk (`infra.store`); (4) deletes DB rows (runs cascade will clean solutions/evals). | domain | S8-07 | PR-F | [ ] | `delete_run()` removes DB row + run directory; cascade deletes solutions and evals; `RevolverError` if run_id not found; works correctly when run directory is missing (partial state) |
| S8-09 | Add `infra.db` helpers: `delete_run()`, `get_solutions_for_run()` (if not already exported). | infra | S8-07 | PR-F | [ ] | SQL `DELETE FROM runs WHERE id=?` triggers cascade; `get_solutions_for_run()` returns list of solution IDs before deletion |
| S8-10 | Implement `cli.run.run_delete` command: `revolver run delete <id> [--force]`. Confirmation prompt unless `--force`. Show summary of what will be deleted (run + N solutions + N evals). | cli | S8-08 | PR-F | [ ] | `revolver run delete run-XXXXX --force` exits 0; shows "Deleted run + 3 solutions + 6 evals"; `revolver run delete run-XXXXX` prompts for confirmation; `--json` outputs structured result |
| S8-11 | Add "Running post-run evaluation..." message to `cli/run.py` after OE completes and before post-run eval starts. Print to stderr (not stdout) to preserve `--json` compatibility. | cli | — | PR-B | [ ] | Message appears in human mode between "Evolution completed" and the final run summary; absent in `--quiet` and `--json` modes |
| S8-12 | Write L2 integration tests for Sprint 008 features. | test | S8-01..S8-11 | PR-G | [ ] | `test_problem_test_evaluate_instance`, `test_llm_remove_force`, `test_dataset_remove_force`, `test_run_delete_by_id`, `test_run_delete_force_skips_prompt`, `test_run_delete_not_found`, `test_api_key_missing_fatal`, `test_wrapper_has_timeout`, `test_migration_v4_to_v5` all pass |

---

## Integration Tests (L2)

Tests that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `problem test` | Evaluator with only `evaluate_instance()` — accepted and runs | `test_problem_test_evaluate_instance` | Planned |
| `problem test` | Evaluator with neither function — `EvaluatorLoadError` | `test_problem_test_no_evaluate_fn` | Planned |
| `llm remove` | `--force` skips confirmation prompt | `test_llm_remove_force` | Planned |
| `dataset remove` | `--force` skips confirmation prompt | `test_dataset_remove_force` | Planned |
| `run delete` | Delete existing run → removes DB row + files | `test_run_delete_by_id` | Planned |
| `run delete` | `--force` flag skips prompt | `test_run_delete_force_skips_prompt` | Planned |
| `run delete` | Unknown run ID → exit 1, clear error | `test_run_delete_not_found` | Planned |
| `run` (start) | Missing API key env var → fatal error before launch | `test_api_key_missing_fatal` | Planned |
| wrapper generation | `timeout_per_instance` rendered into wrapper code | `test_wrapper_has_timeout` | Planned |
| DB migration | v4→v5 adds CASCADE, existing data preserved | `test_migration_v4_to_v5` | Planned |

**Cumulative L2 tests at sprint end: ~148 total (138 previous + ~10 new)**

---

## PR Decomposition

| PR | Scope | Files modified | Can parallelize |
|---|---|---|---|
| PR-A | Fix `evaluator_loader` + `problem test` | `infra/evaluator_loader.py`, `tests/` | Independent |
| PR-B | Fatal API key + post-run message | `infra/openevolve.py`, `cli/run.py`, `tests/` | Independent |
| PR-C | Wrapper per-instance timeout | `core/run.py` (`_WRAPPER_TEMPLATE`), `tests/` | Independent |
| PR-D | `--force` on `llm remove` + `dataset remove` | `cli/llm.py`, `cli/dataset.py`, `tests/` | Independent |
| PR-E | DB migration v5 (CASCADE FKs) | `infra/db.py`, `tests/` | Must merge before PR-F |
| PR-F | `run delete` command | `infra/db.py`, `core/run.py`, `cli/run.py`, `infra/store.py`, `tests/` | Depends on PR-E |
| PR-G | Full regression + sprint L2 tests | `tests/` | Depends on all PRs merged |

---

## Parallelization

### Dependency graph

```
S8-01 (infra: evaluator_loader fix) ─────────────────────────────────────────> S8-12 (tests)
                                                                                      ↑
S8-02 (infra: API key fatal) ──> S8-11 (cli: post-run message) ──────────────────────┤
                                                                                      │
S8-03 (infra: wrapper timeout) ─────────────────────────────────────────────────────┤
                                                                                      │
S8-05 (cli: llm remove --force) ─────────────────────────────────────────────────────┤
S8-06 (cli: dataset remove --force) ─────────────────────────────────────────────────┤
                                                                                      │
S8-07 (infra: DB migration v5) ──> S8-09 (infra: db helpers)                         │
                                         ↓                                            │
                                   S8-08 (domain: delete_run)                         │
                                         ↓                                            │
                                   S8-10 (cli: run delete) ───────────────────────────┘
```

### Critical path
S8-07 → S8-09 → S8-08 → S8-10 → S8-12
Estimated sequential depth: 4 steps (DB migration must land before delete command).

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Evaluator & problem test fix | S8-01 | — | Agent 1 |
| B — API key + UX message | S8-02, S8-11 | — | Agent 2 |
| C — Wrapper per-instance timeout | S8-03 | — | Agent 3 |
| D — Force flags on remove | S8-05, S8-06 | — | Agent 1 (after S8-01) |
| E — DB migration v5 | S8-07 | — | Agent 4 |
| F — run delete command | S8-09, S8-08, S8-10 | S8-07 merged | Agent 4 |
| G — Integration tests + regression | S8-12 | All PRs merged | Any agent |

Peak parallelism: 4 agents (Streams A, B, C, E simultaneously).

### Conflict risks
- **`infra/db.py`** — PR-E (migration v5 adds `CURRENT_SCHEMA_VERSION = 5`) and PR-F (new `delete_run` helpers) both modify this file. Merge PR-E first; PR-F branch should rebase onto PR-E.
- **`core/run.py`** — PR-C modifies `_WRAPPER_TEMPLATE`; PR-F adds `delete_run()`. Separate functions, but same file. Low conflict risk if PRs are well-scoped.

---

## Sprint Review

**Completed**: Session 037 (2026-03-21)
**Release**: v0.8.0

### Tests passing
- 13 / 10 new tests passing (exceeded target)
- 749 / ~148 total tests passing (cumulative)

### Demo-able features
- [x] `revolver problem test` works with `evaluate_instance()` evaluators (PR #86)
- [x] `revolver llm remove <name> --force` exits without prompt (scriptable) (PR #89)
- [x] `revolver dataset remove <name> --force` exits without prompt (scriptable) (PR #89)
- [x] `revolver run delete <id> --force` removes run + solutions + eval data + files (PR #93)
- [x] `revolver run` aborts with fatal error when API key env var is unset (PR #88)
- [x] Post-run eval phase shows "Running post-run evaluation..." message (PR #88)
- [x] Wrapper `_revolver_evaluator.py` contains per-instance timeout guard (PR #87)
- [x] DB v5 migration runs cleanly on existing projects (PR #91)
- [~] B1 upstream issue: root cause confirmed and reproduced (not filed yet)

### Carry-over
- B1 upstream OE issue: file on OpenEvolve GitHub
