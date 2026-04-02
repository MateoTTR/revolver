# Sprint 012 — Demo Feedback: UX & Reliability (v0.12.0)

**Status**: Planning
**Goal**: Fix run status classification bugs (B1/B2), make dry-run reflect the complete resolved OE config (F1-F3), improve run observability (F7), add MAP-Elites cell indices to population output (F8), and polish ensemble/solution UX (F4, F6).
**Source**: Demo feedback v0.10/v0.11 (beamforming), 8 findings + 2 bugs.
**Predecessor**: Sprint 011 (v0.11.0)

---

## Source

- Demo feedback: `/home/mathi/revolver-demos/beamforming/demos/demo-v0.11/feedback.md`
- Feedback summary: `/home/mathi/revolver-demos/feedback-summary.md`
- Predecessor: Sprint 011 (v0.11.0) — ~982 tests passing

---

## Scope

### Bugs

| ID | Problem | Root cause |
|---|---|---|
| **B1** | Runs with valid programs (e.g. 24/30) marked `failed` instead of `completed_with_errors` | OE raises an exception when many iterations fail → Revolver's exception handler marks `failed` without checking for valid programs in checkpoint |
| **B2** | Runs with 100% errors marked `completed` (B9 from v0.9.0) | Symmetric issue — `_determine_run_status()` may not be reached, or `count_valid_programs()` counts the initial seed program |

**Fix strategy**: In all exception paths where `oe_completed is False`, count valid programs from checkpoint before deciding status. Simplify `_determine_run_status()`: remove `MIN_VALID_ITERATION_RATIO` (10% threshold), use `valid_iters > 0 → completed_with_errors` when any errors exist, `valid_iters == 0 → failed`.

### UX Findings

| ID | Problem | Approach |
|---|---|---|
| **F1-F3** | `--dry-run` `resolved_config` omits `--rewrite-mode` params, `--config-override` values, and `llm.models` for ensembles | Extend `ResolvedOEConfig` model + `_extract_resolved_config()` to capture these from the merged OE config dict |
| **F4** | `(E)` indicator truncated in narrow terminals (suffix) | Move to prefix: `(E) flash-mix` instead of `flash-mix (E)` |
| **F6** | `solution info` attributes to last run's LLM after resume cross-model, no `resume_chain` | Expose `resume_chain` and `resumed_from` in `solution info` output |
| **F7** | `run status` shows only `elapsed_s` during long runs, no iteration progress | Read OE checkpoint during active run to populate existing `RunStatus.iterations_completed` and `RunStatus.best_score` fields (already in model, never filled) |
| **F8** | `run population --json` doesn't expose MAP-Elites cell indices | Read `metadata.json` `island_feature_maps` in `parse_population()`, join program_id → cell coordinates |

### Explicitly out of scope

- F5 (no DB trace for invalid LLM run) — acceptable behavior
- F8 `complexity`/`diversity` features — requires OE fork changes (tracked in OE fork memory)
- FR2 (per-program model attribution) — requires OE fork changes (tracked in OE fork memory)
- FR3 (`checkpoint_interval` via `--config-override`) — likely already works, to verify during demo

---

## Tasks

| # | Task | Layer | PR | Status |
|---|---|---|---|---|
| S12-01 | Simplify `_determine_run_status()`: remove `MIN_VALID_ITERATION_RATIO`, `valid > 0 && errors → completed_with_errors`, `valid == 0 → failed`, `no errors → completed` | domain | PR-A | [ ] |
| S12-02 | In `launch_run()` + `resume_run()` exception handlers (when `oe_completed is False`): count valid programs from checkpoint before marking status; use `_determine_run_status()` instead of hardcoding `"failed"` | domain | PR-A | [ ] |
| S12-03 | Verify B2 scenario (100% errors → must be `failed`): add explicit test with zero valid programs | test | PR-A | [ ] |
| S12-04 | Add fields to `ResolvedOEConfig`: `diff_based_evolution: bool | None`, `max_code_length: int | None`, `config_overrides: dict[str, Any] | None`, `llm_models: list[dict] | None` | domain | PR-B | [ ] |
| S12-05 | Update `_extract_resolved_config()` to read `diff_based_evolution`, `max_code_length` from merged config, pass-through `config_overrides` dict, and extract `llm.models` array when present | domain | PR-B | [ ] |
| S12-06 | Update dry-run CLI display to render new `ResolvedOEConfig` fields (overrides as key=value, ensemble models as name×weight) | cli | PR-B | [ ] |
| S12-07 | Change ensemble indicator in `run list` from suffix `llm (E)` to prefix `(E) llm` | cli | PR-C | [ ] |
| S12-08 | `core.solution.get_solution_info()` — fetch `resumed_from` and `resume_chain` from the parent run record, include in output dict | domain | PR-C | [ ] |
| S12-09 | `cli.solution.solution_info` — display `resumed_from` and `resume_chain` when present | cli | PR-C | [ ] |
| S12-10 | `get_run_status()` — when run is active, find latest checkpoint, call `count_valid_programs()` for `iterations_completed` and read best score from checkpoint `metadata.json` | domain | PR-D | [ ] |
| S12-11 | `cli.run.run_status` — display `iterations_completed` (e.g. `12/50`) and `best_score` when available | cli | PR-D | [ ] |
| S12-12 | `infra.openevolve.parse_population()` — read `metadata.json` `island_feature_maps`, build reverse map `program_id → cell_indices`; add `cell_indices: list[int] | None` to each program dict | infra | PR-E | [ ] |
| S12-13 | `cli.run.run_population` — display cell indices column in table, include in `--json` output | cli | PR-E | [ ] |
| S12-14 | L2 integration tests for Sprint 012 features | test | all PRs | [ ] |

---

## Key implementation details

### B1/B2 — Status logic (PR-A)

**Current code** (`core/run.py:117-139`):
```python
MIN_VALID_ITERATION_RATIO = 0.1

def _determine_run_status(valid_iters, total_iters):
    if valid_iters is None or valid_iters == 0:
        return "failed"
    if total_iters > 0 and valid_iters / total_iters < MIN_VALID_ITERATION_RATIO:
        return "completed_with_errors"
    return "completed"
```

**Proposed replacement**:
```python
def _determine_run_status(valid_iters, total_iters):
    if valid_iters is None or valid_iters == 0:
        return "failed"
    if valid_iters < total_iters:
        return "completed_with_errors"
    return "completed"
```

**Exception handler change** (`core/run.py:967-968`):
Currently: `update_run_status(proj_conn, run_id, "failed")`
Proposed: count valid programs from checkpoint first, then use `_determine_run_status()`. Same pattern already used in the happy path (lines 844-866).

### F1-F3 — Dry-run completeness (PR-B)

**Current `_extract_resolved_config()`** reads 7 hardcoded fields from the merged OE config dict.

The merged OE config dict already contains all the values we need — `build_config()` applies `--rewrite-mode` (sets `diff_based_evolution`, `max_code_length`), `--config-override` values, and `llm.models` (ensemble) before returning. The dry-run calls `_extract_resolved_config(oe_config)` at line 638 — so the data is there, just not extracted.

**Config overrides**: pass the raw overrides dict alongside the resolved values so the user can see both "what was overridden" and "what the final value is".

### F7 — Run progression (PR-D)

The `RunStatus` model already has `iterations_completed: int | None` and `best_score: float | None` fields (lines 242-244 of `models/run.py`). They are never populated in `get_run_status()`.

For active runs, we can:
1. Find latest checkpoint in the run dir (reuse `find_latest_checkpoint()`)
2. Count programs via `count_valid_programs()` → `iterations_completed`
3. Read `metadata.json` → `best_program_id` → read that program's score → `best_score`

This reads checkpoint files written by OE without interfering with the running process (read-only).

### F8 — MAP-Elites cell indices (PR-E)

**Checkpoint `metadata.json`** contains:
```json
{
  "island_feature_maps": [{"0-5": "prog_id_1", "0-9": "prog_id_2"}],
  "feature_stats": {"time_s": {"min": 0, "max": 2.4}, "diversity": {...}}
}
```

Cell keys are `"dim0_bin-dim1_bin"` strings mapping to program IDs. We build a reverse map `program_id → [dim0_bin, dim1_bin]` and attach to each program in the population output.

---

## Integration Tests (L2)

| Command | Scenario | Test ID |
|---|---|---|
| `core _determine_run_status` | Valid > 0, some errors → `completed_with_errors` | `test_status_valid_with_errors` |
| `core _determine_run_status` | Valid == 0 → `failed` | `test_status_zero_valid` |
| `core _determine_run_status` | Valid == total → `completed` | `test_status_all_valid` |
| `core launch_run` exception | OE crash with valid checkpoint → `completed_with_errors` | `test_launch_run_crash_with_valid_programs` |
| `run --dry-run --rewrite-mode` | `resolved_config` contains `diff_based_evolution: false` | `test_dry_run_rewrite_mode` |
| `run --dry-run --config-override` | `resolved_config` contains override values | `test_dry_run_config_override` |
| `run --dry-run --llm <ensemble>` | `resolved_config` contains `llm_models` array | `test_dry_run_ensemble_models` |
| `run list` | Ensemble indicator shows `(E) name` prefix | `test_run_list_ensemble_prefix` |
| `solution info` (resumed run) | Output includes `resume_chain` | `test_solution_info_resume_chain` |
| `run status` (active) | Shows `iterations_completed` and `best_score` from checkpoint | `test_run_status_active_progress` |
| `run population` | Programs include `cell_indices` from metadata | `test_population_cell_indices` |

---

## Parallelization

### Dependency graph

```
Sprint 011 complete ──────────────────────────────────────────────────
          |
          ├──> PR-A (B1/B2: status fix)         ← independent
          |
          ├──> PR-B (F1-F3: dry-run)            ← independent
          |
          ├──> PR-C (F4+F6: display + solution) ← independent
          |
          ├──> PR-D (F7: run progression)        ← independent
          |
          └──> PR-E (F8: population cells)       ← independent
```

**All 5 PRs are independent** — they touch different areas:
- PR-A: `_determine_run_status()` + exception handlers in `launch_run()`/`resume_run()`
- PR-B: `ResolvedOEConfig` model + `_extract_resolved_config()` + dry-run CLI display
- PR-C: `run list` display (1 line) + `solution info` output
- PR-D: `get_run_status()` + `run status` CLI display
- PR-E: `parse_population()` + `run population` CLI display

Peak parallelism: **5 agents** (all PRs can run concurrently).

### Conflict risks

- **`core/run.py`** — PR-A (status logic), PR-B (dry-run), PR-D (run status) all touch this file but different sections. Merge order: PR-A first (smallest, highest priority), then PR-B, then PR-D.
- **`models/run.py`** — PR-B adds fields to `ResolvedOEConfig`. PR-D doesn't modify models (fields already exist). Low risk.
- **`cli/run.py`** — PR-B (dry-run display), PR-C (run list), PR-D (run status), PR-E (population). All touch different functions. Low risk.

**Recommended merge order**: PR-A → PR-C → {PR-B, PR-D, PR-E} in any order.

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / ~11 new integration tests passing

### Demo-able features
- [ ] Run with errors correctly classified `completed_with_errors` (B1 fix)
- [ ] `--dry-run --rewrite-mode` shows `diff_based_evolution`, `max_code_length` (F1)
- [ ] `--dry-run --config-override` shows override values (F2)
- [ ] `--dry-run --llm <ensemble>` shows `llm_models` with members and weights (F3)
- [ ] `run list` shows `(E) flash-mix` prefix (F4)
- [ ] `solution info` on resumed run shows `resume_chain` (F6)
- [ ] `run status` during active run shows iterations and best score (F7)
- [ ] `run population` includes cell indices from MAP-Elites grid (F8)

### Carry-over
_TBD at sprint end._
