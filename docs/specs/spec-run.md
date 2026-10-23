# Spec: revolver run

**Traceable to**: ConOps §4.6 (Solution), §5.5 (Workflow: Generate a Solution), §3.3 (Concurrency Model), §4.4 (Instance Injection), DES-005 v0.6.0, ADR-007
**Status**: Draft

---

## 1. Scope

This spec covers solution generation via a pluggable evolution backend (OpenEvolve by default, ShinkaEvolve optional — ADR-007). `revolver run` is the core command that ties together a problem version, a dataset, and an LLM to produce evolved solutions.

---

## 2. Commands

### 2.1 `revolver run`

Launch an evolution run on the selected backend.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--version <tag>` | string | Yes | Problem version to use |
| `--llm <name>` | string | Yes | Registered LLM or ensemble name |
| `--dataset <name>` | string | Yes | Registered training dataset |
| `--backend <name>` | string | No | Evolution backend: `openevolve` or `shinka`. When omitted, the problem version's stored backend is used, falling back to `openevolve` (resolution order: explicit flag > version backend > default — FR-RUN-047, FR-PRB-016). An explicit value that differs from the version's stored backend warns on stderr. Stored in the run record (FR-RUN-047) |
| `--iterations <n>` | int | No | Number of evolution iterations. Overrides config.yaml value. Mapped to the backend's native parameter (OE: `max_iterations`; Shinka: `num_generations`) |
| `--alias <name>` | string | No | User-friendly name for the generated solution |
| `--config-override <key=value>` | string[] | No | Override specific backend config values (validated against the selected backend's schema). `evaluation.*` keys (e.g. `evaluation.on_timeout`, `evaluation.timeout_score`) are a Revolver-owned section and value-validated at run/dry-run (FR-RUN-054) |
| `--dry-run` | flag | No | Validate all inputs and display the resolved config (neutral fields + backend extras) without launching the run |
| `--temperature <float>` | float | No | Override the LLM sampling temperature (range: 0.0–2.0). Mapped per backend (OE: `llm.temperature`; Shinka: per-model `llm_kwargs`) |
| `--parallel <int>` | int | No | Override evaluation parallelism (positive integer). Mapped per backend (OE: `evaluator.parallel_evaluations`; Shinka: evaluation job pool, with a warning) |
| `--selection <strategy>` | string | No | Ensemble member-selection strategy: `fixed`, `ucb`, `ucb1`, or `thompson`. Capability-driven per backend (OE supports only weighted/`fixed`; Shinka maps it to `evo_config.llm_dynamic_selection`). See FR-RUN-049 |
| `--selection-kwarg <k=v>` | string[] | No | Sampler constructor kwarg (repeatable), routed to the **selected** strategy's sampler only (e.g. `cost_aware_coef` applies to `ucb`/`ucb1`). Shinka only. See FR-RUN-049 |
| `--llm-weight <model=w>` | string[] | No | Per-run override of an ensemble member's weight (repeatable). Honored on OE (weighted) and Shinka `fixed`; ignored with a warning under Shinka adaptive modes. See FR-RUN-050 |

**Behavior**:
1. **Validate inputs**:
   - Problem version exists
   - LLM is registered and reachable (loaded for local, API key set for remote)
   - Dataset is registered and compatible with the problem version (warn if not)
   - If dataset split is not `train`, display a warning (do not block)
2. **Verify dataset integrity**: recompute hashes, warn on mismatch
3. **Prepare environment**:
   - Set `REVOLVER_DATASET_DIR` to the dataset path
   - Set `REVOLVER_INSTANCE_LOG` to the side-channel SQLite DB path (optional, for per-instance visibility — ADR-006)
   - Set `REVOLVER_EVAL_LOG` to the evaluator log file path (optional — ADR-006)
   - Configure the backend to use the registered LLM (base URL/model for OpenAI-compatible access; per-provider projection for ShinkaEvolve — ADR-007 D5)
4. **Launch the selected backend** with the problem version's files (initial_program, evaluator, config)
5. **Monitor progress**: display iteration count, best score, elapsed time
6. **On completion**:
   - Store all top-ranked programs as `rank-1.py`, `rank-2.py`, etc. in `.revolver/runs/<run-id>/programs/` (backend output, preserved for later extraction)
   - Create **one** solution DB row for the best program (rank-1) with `(run_id, rank=1)`
   - Record full lineage in `RunManifest` stored in the run directory
   - Store metrics in SQLite
   - Store the backend resume state in the run directory for potential resume (OpenEvolve: checkpoint dir; ShinkaEvolve: results dir with `programs.sqlite`)

**Output** (human, during run):
```
Run started: v1.1 + claude-opus + train-small
  Iteration 42/200 | Best score: 0.87 | Elapsed: 1h15m | ETA: 2h05m
```

**Output** (human, on completion):
```
Run completed: run-20260310-143000
  200 iterations in 3h45m
  Solution: sol-20260310-143000 (rank #1, alias: claude-small-v1.1)
  Best combined_score: 0.91
  Programs stored: 1 (rank-1 auto-promoted to solution; use `run population` to inspect the full population)
  Tokens: 1,245,000 prompt + 328,000 completion = 1,573,000 total
  Stored in: .revolver/runs/run-20260310-143000/
```

Cost is not reported (S15 / #300): no realistic figure is reachable since
the engines do not persist per-attempt or reasoning/thinking tokens. Token
counts cover stored programs only.

**Output** (JSON, on completion):
```json
{
  "run_id": "run-20260310-143000",
  "status": "completed",
  "problem_version": "v1.1",
  "llm": "claude-opus",
  "dataset": "train-small",
  "iterations": 200,
  "generation_time_s": 13500,
  "token_usage": {
    "prompt_tokens": 1245000,
    "completion_tokens": 328000,
    "total_tokens": 1573000
  },
  "solution": {
    "solution_id": "sol-20260310-143000",
    "alias": "claude-small-v1.1",
    "rank": 1,
    "best_score": 0.91
  },
  "programs_stored": 5
}
```

**Exit codes**: 0 success, 1 invalid inputs, 2 dataset integrity failure, 3 LLM or backend unavailable, 4 backend failure

### 2.2 `revolver run status`

Show the status of active or most recent runs. Scans `.revolver/runs/locks/` for active runs and can show multiple concurrent runs.

**Output** (human):
```
Run in progress: run-20260310-143000
  Problem: v1.1 | LLM: claude-opus | Dataset: train-small
  Iteration: 42/200 | Best score: 0.87
  Started: 2026-03-10 14:30 | Elapsed: 1h15m
```

**Exit codes**: 0 always

### 2.3 `revolver run resume`

Resume an interrupted run from its checkpoint. Creates a NEW run from the parent run's checkpoint.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `RUN_ID` | Yes | Run whose checkpoint to resume from (primary positional argument) |

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--run <run-id>` | string | No | **Deprecated** fallback alias for the positional `RUN_ID`, kept for backward compatibility. The positional argument wins when both are supplied. |
| `--llm <name>` | string | No | Override the LLM or ensemble used for the resumed run. Accepts both single LLM and ensemble names, allowing switching between single and ensemble mode. |
| `--iterations <n>` | int | No | Number of additional iterations on top of the parent chain (the parent run's iteration count is reused when omitted). |
| `--temperature <t>` | float | No | LLM temperature override (0.0–2.0). |
| `--parallel <n>` | int | No | Number of parallel evaluations. |
| `--config-override <k=v>` | string[] | No | Backend config override (key=value, repeatable). Not persisted or auto-carried across resumes. |
| `--rewrite-mode` | flag | No | Full-rewrite mode (same semantics as `run start`). |
| `--selection <strategy>` | string | No | Ensemble member-selection strategy for the resumed run. **Not inherited** on resume — it must be re-specified each time; when omitted for an *ensemble* parent, the run falls back to the backend default and `resume_run()` emits a warning so the reset is not silent (cf. DES-005 §2.3). |
| `--selection-kwarg <k=v>` | string[] | No | Per-sampler constructor kwarg (key=value, repeatable), routed to the selected strategy's sampler. ShinkaEvolve only. |
| `--llm-weight <model=w>` | string[] | No | Per-run ensemble member weight override (model=weight, repeatable). |

**Behavior**:
1. Locate the parent run's backend resume state (OpenEvolve: checkpoint dir; ShinkaEvolve: results dir with `programs.sqlite`)
2. Verify the resume state is valid and resumable via the backend's `resume_precheck` hook (fail fast, exit 1, before any record is created). ShinkaEvolve's precheck requires the parent's `programs.sqlite` to exist and to record `last_iteration > 0`; otherwise the run is rejected as non-resumable.
3. Create a new run (`resumed_from: <parent-run-id>`). On **both backends the parent's resume state is READ but never mutated**: OpenEvolve copies the checkpoint into the new run dir, and **ShinkaEvolve clones the parent's `shinka-output/`** (`copytree` of `programs.sqlite` + sidecars, every `gen_*/` dir, and any `bandit_state.pkl`/`prompts.sqlite`) into the new run dir and continues the DB-driven search **on the clone**. The parent's `shinka-output/` stays byte-unchanged (clone-resume isolation), and because the clone is itself the new run's artifact tree, no post-run snapshot copy is needed. The resumed run's token/valid counts are cumulative over the parent chain, while the parent's `run population`/`run status` continue to reflect only the parent's own (untouched) database.
4. The resumed run uses the **parent run's backend** (cross-backend resume is not supported)
5. If `--llm` is provided, use the specified LLM or ensemble instead of the parent run's LLM
6. Reuse the parent run's wrapper evaluator (no regeneration) — including the parent wrapper's baked `evaluation.on_timeout`/`timeout_score` policy (FR-RUN-054)
7. Re-launch the backend from the parent's resume state with the (optionally overridden) configuration. `--iterations N` means **N more iterations on top of the parent chain** on both backends (when omitted, the parent run's iteration count is reused)
8. On completion: the new run gets its own ID, directory, programs, and a single solution DB row (rank-1)

**Exit codes**: 0 success, 1 if run or resume state not found, 4 if the backend fails

### 2.4 `revolver run list`

List all runs in the current project.

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--version <tag>` | string | — | Filter by problem version |
| `--llm <name>` | string | — | Filter by LLM used |
| `--status <status>` | string | — | Filter by status: `running`, `completed`, `completed_with_errors`, `failed`, `interrupted` |

**Output** (human):
```
ID                    Version  LLM              Dataset      Backend     Iter  Score   Status      Date
run-20260310-143000   v1.0     codestral-local  train-small  openevolve  100   0.74    completed   2026-03-10
run-20260310-173000   v1.0     claude-opus      train-small  openevolve  100   0.82    completed   2026-03-10
run-20260310-190000   v1.0     (E) multi-model-v1  train-small  shinka   200   0.91    completed   2026-03-10
```

Note: Ensemble names are marked with a `(E) ` prefix in the LLM column. The `Backend` column surfaces the evolution backend (FR-RUN-047).

**Exit codes**: 0 always

### 2.5 `revolver run info <run-id>`

Show detailed information about a run.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `run-id` | Yes | Run ID |

**Output** (human, single LLM):
```
Run: run-20260310-143000
  Status: completed
  Backend: openevolve
  Problem version: v1.1 (sha256:e5f6g7h8...)
  LLM: claude-opus (claude-opus-4-6)
  Dataset: train-small (sha256:f1e2d3c4...)
  Iterations: 200
  Generation time: 3h45m
  Tokens: 1,245,000 prompt + 328,000 completion = 1,573,000 total
  Note: token counts cover stored programs only; retry/failed-attempt and
  reasoning/thinking tokens are not counted — watch the provider console.
  Programs extracted: 3 (files in programs/)
  Programs in DB: 18 (total in backend store)
  Resumed from: —
  Directory: .revolver/runs/run-20260310-143000/

Solution (auto-created):
  sol-20260310-143000  rank=#1  claude-small-v1.1
  Best score: 0.91 (engine, single eval)
  Post-eval mean: 0.87 (48/50 instances valid)

Programs (from backend output):
  #1  score=0.91  → sol-20260310-143000 (extracted)
  #2  score=0.85
  #3  score=0.79
  Use `revolver solution extract --run run-20260310-143000 --rank <N>` to promote
  (ranks > 1 require a top-N-capable backend — FR-SOL-021).

Resume chain: (none)
```

> **Program counters (UX-4 / S16).** `run info` reports two counts: **Programs
> extracted** (`programs_extracted`) is the number of `rank-N.py` files
> materialized into the run's `programs/` directory; **Programs in DB**
> (`programs_in_db`) is the total program count in the backend's own store
> (every row in ShinkaEvolve's `programs.sqlite`). The DB total is only shown
> on backends that report it — it is omitted on OpenEvolve, where a full total
> would require parsing the checkpoint. When a rank-1 solution has no post-run
> eval score of its own, its score falls back to the engine's run best, labeled
> `(engine, single eval)` — the former bare `(from run)` indicator — so the
> single-eval engine number never renders unlabeled (FR-RUN-055). When a
> post-run eval mean exists, it is displayed next to the engine best with its
> FR-RUN-053 coverage (`instances_valid/instances_total`).

**Output** (human, ensemble):
```
Run: run-20260310-190000
  Status: completed
  Problem version: v1.1 (sha256:e5f6g7h8...)
  LLM: multi-model-v1 (ensemble: 2 members)
    claude-opus (weight: 0.7)
    gemini-pro (weight: 0.3)
  Dataset: train-small (sha256:f1e2d3c4...)
  Iterations: 200
  ...
```

**Exit codes**: 0 success, 1 if not found

### 2.6 `revolver run delete <run-id>`

Delete a run and all its associated data (solutions, evaluations, files).

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `run-id` | Yes | Run ID to delete |

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--force` / `-f` | flag | false | Skip interactive confirmation prompt |

**Behavior**:
1. Resolve the run by ID
2. If `--json` is active and `--force` is not set, return an error (no interactive prompt possible in JSON mode)
3. If `--force` is not set, display run details and ask for confirmation
4. Delete associated solutions and their evaluation data within a transaction
5. Delete the run row from SQLite and the run directory from the filesystem

**Output** (human):
```
Deleted run "run-20260310-143000"
  Solutions deleted: 1
  Evaluations deleted: 2
```

**Output** (JSON):
```json
{
  "run_id": "run-20260310-143000",
  "solutions_deleted": 1,
  "evals_deleted": 2,
  "status": "deleted"
}
```

**Exit codes**: 0 success, 1 if not found or confirmation declined

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-RUN-001 | MUST | Validate that problem version, LLM, and dataset exist before starting | — |
| FR-RUN-002 | MUST | Warn (do not block) if the dataset's split is not `train` | §4.3 |
| FR-RUN-003 | MUST | Warn (do not block) if the dataset is not declared compatible with the problem version | §7.4 |
| FR-RUN-004 | MUST | Verify dataset integrity (hash check) before starting; warn on mismatch | §7.2 |
| FR-RUN-005 | MUST | Set `REVOLVER_DATASET_DIR` environment variable for the evaluator | §4.4 |
| FR-RUN-026 | SHOULD | Set `REVOLVER_INSTANCE_LOG` for optional per-instance SQLite side-channel logging | §4.4, ADR-006 |
| FR-RUN-027 | SHOULD | Set `REVOLVER_EVAL_LOG` for optional evaluator log file | §4.4, ADR-006 |
| FR-RUN-006 | MUST | Configure the backend to use the registered LLM: base URL and model ID for OpenAI-compatible backends (OpenEvolve); per-provider projection of the same registry fields for ShinkaEvolve (ADR-007 D5) | §3.2 |
| FR-RUN-007 | MUST | Generate a unique run ID: `run-{YYYYMMDD}-{HHMMSS}`. Generate solution IDs: `sol-{YYYYMMDD}-{HHMMSS}` | §4.6 |
| FR-RUN-008 | MUST | Store all top-ranked programs as `rank-N.py` files in the run directory (from backend output). Create **one** solution DB row for the best program (rank-1), referencing (`run_id`, `rank=1`). Additional programs can be promoted to solutions via `revolver solution extract`. | §4.6 |
| FR-RUN-009 | MUST | Record full lineage in `RunManifest` in the run directory: problem version, dataset, LLM, config, timestamp, iterations, generation time | §4.6 |
| FR-RUN-010 | MUST | Store metrics (best scores per iteration) in SQLite | §4.6 |
| FR-RUN-019 | MUST | On completion, evaluate the rank-1 program on all training instances **through `core.eval.evaluate_solution`**, persisting raw per-instance results into `eval_metadata`/`eval_instances` (same storage path as `revolver eval` — no longer a stderr-only report; task-86 residue, U11/#368). The per-instance timeout comes from the eval path (the hardcoded 300 s is removed); a failed post-run eval still only **warns** (never fails the run); the write is guarded against DB contention with the still-open launch connection (commit/WAL/busy_timeout before the call). Each per-instance eval subprocess is killed at its timeout (no leaked workers) and runs under the `REVOLVER_EVAL_NUM_THREADS` thread cap (DES-005 §7, v0.17.1). | §4.6 |
| FR-RUN-020 | MUST | Training results are accessible via `revolver eval results --solution <id> --dataset <train-dataset>` (persisted through the FR-RUN-019 eval path — U11/#368) | — |
| FR-RUN-011 | MUST | Store the backend resume state in the run directory for resume capability (OpenEvolve: checkpoint dir; ShinkaEvolve: results dir) | §4.6, §5.5 |
| FR-RUN-012 | MUST | Support `--alias` for user-friendly solution naming | §4.6 |
| FR-RUN-013 | MUST | `resume` creates a new run from parent checkpoint. The parent run is immutable. | §5.5 |
| FR-RUN-014 | MUST | Local LLM runs execute sequentially (one at a time) | §3.3 |
| FR-RUN-015 | MUST | Remote LLM runs can execute in parallel | §3.3 |
| FR-RUN-016 | SHOULD | Display progress during the run (iteration count, best score, elapsed time) | — |
| FR-RUN-017 | SHOULD | Store the backend config used (verbatim copy) in the run directory | NFR-023 |
| FR-RUN-018 | SHOULD | Record generation wall-clock time in solution lineage | §4.6 |
| FR-RUN-021 | MUST | `run list` shows all runs with filtering by version, LLM, status | — |
| FR-RUN-022 | MUST | `run info` displays full run details including the auto-created solution, all stored programs with scores, and resume chain | — |
| FR-RUN-023 | MUST | `--dry-run` validates all inputs and displays the resolved config (neutral fields + backend extras) without launching | ADR-007 D4 |
| FR-RUN-024 | MUST | Resume reuses the parent run's wrapper evaluator (no regeneration) and backend resume state; the resume mechanism is backend-defined and never mutates the parent (OpenEvolve: copy checkpoint into the new run dir; ShinkaEvolve: clone the parent's `shinka-output/` and continue the DB-driven search on the clone — clone-resume parity, S16 / TD-3). A `resume_precheck` backend hook fails fast on a non-resumable parent before any record is created. | ADR-007 |
| FR-RUN-025 | SHOULD | Per-run lock files in `.revolver/runs/locks/` enable concurrent run tracking | §3.3 |
| FR-RUN-028 | SHOULD | Track total `prompt_tokens` and `completion_tokens` consumed during the run. The accounting source is backend-defined: HTTP response interception (OpenEvolve) or the engine's native per-program accounting (ShinkaEvolve) — token-primary on all backends (ADR-007 D2). Counts cover **stored programs only**: retry/failed-attempt and reasoning/thinking tokens are not counted (the engines do not persist them — S15 / #300) | §4.6, POC #13 |
| FR-RUN-029 | SHOULD | Display token usage (prompt/completion/total breakdown) in run completion output and `run info`, with a caveat that retry and reasoning/thinking tokens are not counted | §4.6 |
| FR-RUN-030 | ~~SHOULD~~ | **Removed (S15 / #300, completed in S16).** Cost estimation was dropped from reported output: no realistic figure is reachable since the engines never persist per-attempt or reasoning/thinking tokens (verified by the #300 token-accounting spike). The `estimate_cost()` helper and the LLM `--input-cost`/`--output-cost` pricing flags/columns have been removed (schema migration v10 drops the columns). Revolver reports **tokens only**. | §4.6, POC #13 |
| FR-RUN-031 | MUST | If the evolution backend throws an exception during execution, run status is set to `failed` in DB, `run-error.log` is written to the run directory, and the lock file is removed | — |
| FR-RUN-032 | MUST | Post-processing errors are logged to `run-error.log` in the run directory | — |
| FR-RUN-033 | MUST | `solution extract` accepts runs with status `completed_with_errors` if the program file exists | — |
| FR-RUN-034 | MUST | `resume` accepts `completed_with_errors` as a valid parent run status | — |
| FR-RUN-035 | MUST | `delete` removes a run by ID with interactive confirmation prompt | — |
| FR-RUN-036 | MUST | `delete --force` bypasses the interactive confirmation prompt | — |
| FR-RUN-037 | MUST | Deleting a run cascade-deletes associated solutions and their evaluation data | — |
| FR-RUN-038 | MUST | Deleting a run removes the run directory from the filesystem | — |
| FR-RUN-039 | MUST | `delete` in JSON mode (`--json`) without `--force` returns an error | NFR-003 |
| FR-RUN-040 | SHOULD | `--temperature` overrides the LLM sampling temperature in the resolved config (range: 0.0–2.0), mapped to the backend's native parameter (OE: `llm.temperature`; Shinka: per-model `llm_kwargs`) | — |
| FR-RUN-041 | SHOULD | `--parallel` overrides evaluation parallelism in the resolved config (positive integer), mapped to the backend's native parameter (OE: `evaluator.parallel_evaluations`; Shinka: evaluation job pool, with a warning) | — |
| FR-RUN-043 | MUST | If the backend completes but post-processing fails, run status is set to `completed_with_errors` (not `interrupted`) | — |
| FR-RUN-044 | MUST | Run metadata stores `llm_type` (`single` or `ensemble`) indicating whether a single LLM or an ensemble was used | — |
| FR-RUN-045 | MUST | Run metadata stores `llm_snapshot` (JSON) capturing the full LLM or ensemble configuration at run time for traceability | NFR-020 |
| FR-RUN-046 | MUST | `--llm` accepts ensemble names; when an ensemble is used, the backend is configured with multiple models, mapped first-class per backend (ADR-007 A2/A3). OpenEvolve uses a weighted `llm.models` array (member weights honored; per-member `reasoning_effort` honored). ShinkaEvolve maps all members to `evo_config.llm_models[]` with `--selection` driving `llm_dynamic_selection`; under `fixed`, member weights seed `FixedSampler.prior_probs` (apples-to-apples with the OE weighted ensemble). Weights carry across **OE-weighted** and **Shinka-`fixed`** only — under Shinka adaptive modes (`ucb`/`ucb1`/`thompson`) weights are ignored **by design** (bandit starts uniform) and per-member `reasoning_effort` is OpenEvolve-only. Both asymmetries are verified ShinkaEvolve 0.0.7 constraints surfaced via `capabilities()` (map-with-warn), **not** a silent drop. | — |
| FR-RUN-047 | MUST | `--backend {openevolve,shinka}` selects the evolution backend. Resolution order: **explicit `--backend` > the problem version's stored backend (FR-PRB-016) > default `openevolve`** — omitting the flag defers to the version, so flag absence MUST be distinguishable from an explicit `openevolve` (`None` sentinel, not a hard CLI default — U4/#369). An explicit `--backend` that differs from the version's stored backend **warns on stderr** (never errors). `--dry-run` resolves the backend identically. The resolved backend is stored in the run record and manifest, and surfaced in `run info`, `run list`, and dry-run output. `resume` inherits the parent run's backend. | ADR-007 |
| FR-RUN-048 | MUST | Backend capability differences are reported honestly: an option not supported by the selected backend produces a warning (map-with-warn), never a silent no-op or an error that breaks scripts | ADR-007 D3/D4 |
| FR-RUN-049 | MUST | `--selection {fixed,ucb,ucb1,thompson}` is a neutral run lever selecting the ensemble member-selection strategy, validated against the resolved backend's `capabilities().selection_strategies` (ADR-007 A1/A4). OpenEvolve supports only weighted (`fixed`) selection and **rejects** any non-`fixed` value with a clear error naming the supported strategy (exit 1). ShinkaEvolve maps it to `evo_config.llm_dynamic_selection` (`fixed`/`ucb`/`ucb1` [alias of `AsymmetricUCB`]/`thompson`). `--selection-kwarg k=v` (repeatable) is routed only to the **selected** sampler's constructor (never a union); `cost_aware_coef` applies to `ucb`/`ucb1` and defaults to 0 (ADR-007 A5). | ADR-007 A1/A4/A5 |
| FR-RUN-050 | MUST | `--llm-weight model=w` (repeatable) overrides an ensemble member's weight for this run only, taking precedence over the registry weight. Honored on OpenEvolve (patches the weighted sampler's per-member `weight`) and on ShinkaEvolve **only under `--selection fixed`** (folded into the `FixedSampler.prior_probs` vector). Under Shinka adaptive modes it is **ignored with a warning** (the bandit starts uniform — ADR-007 A3). Per-member weight/effort is reachable only via this dedicated flag, not `--config-override` (which cannot address list members). | ADR-007 A1/A3 |
| FR-RUN-051 | MUST | `revolver solution extract --from-checkpoint` recovers the best program of an `interrupted`/`failed` OpenEvolve run from its latest checkpoint (`best_program_id` in the checkpoint `metadata.json` + `programs/{id}.json`), routed via a backend-neutral `EvolutionBackend` recovery method (B7). The **default** `solution extract` behavior is unchanged — it still rejects `interrupted` runs. A run too short to have produced a checkpoint yields a clear error. | — |
| FR-RUN-052 | MUST | Score display and population ranking (`run status` live progress, `run population`, and the checkpoint best-score fallback) **prefer a numeric `combined_score`** over the sum-of-numeric-metrics; the sum is the fallback only when no numeric `combined_score` exists in the metrics dict, and a metrics dict lacking `combined_score` never crashes display. Display/fallback-only change — the solution-DB `best_score` is already `combined_score`-based (DES-005 §4.5; U13/#367) | — |
| FR-RUN-053 | MUST | The generated wrapper evaluator on **both backends** emits the coverage keys `instances_valid`/`instances_total` alongside the aggregated metrics and records each timed-out instance on a side-channel; the `instances_` metric prefix is **reserved** for coverage metadata and excluded from the wrapper's metric mean (read-path counterpart: FR-EVL-021 as amended — coverage is metadata, never averaged into a score); the ShinkaEvolve wrapper gains a **distinct `TimeoutError` branch** (today it catches all exceptions in one branch) so timeouts are distinguishable from failures (DES-005 §3.2; U13/#367) | — |
| FR-RUN-054 | MUST | `evaluation.on_timeout: penalize\|drop` controls how the generated wrapper scores a timed-out instance: **`penalize` (default) counts the instance at `evaluation.timeout_score` (finite, default `0.0`) in the metric mean; `drop` excludes it, restoring the 0.17 survivor-mean**. The default flip to `penalize` is a **deliberate v0.18 fitness-landscape change** (release-noted; `evaluation.on_timeout=drop` is the escape hatch). Both keys are parsed at the shared launch point on both backends and their values are **validated at run/dry-run** (unknown `on_timeout` value or non-finite `timeout_score` → exit 1): `evaluation.*` is a validated, **Revolver-owned** config section (previously popped/uninspected). Resume inherits the parent wrapper's baked policy; on a run with zero timeouts, `penalize` and `drop` produce identical scores (DES-005 §3.2; U13/#367) | — |
| FR-RUN-055 | MUST | `run info` shows the engine best score labeled **"engine, single eval"** next to the post-run eval mean labeled with the FR-RUN-053 coverage (`instances_valid/instances_total`); the #306 display-time score fallback (rank-1 solution with no post-eval score of its own) is labeled "engine, single eval" so the single-eval engine number **never renders bare**; JSON output carries both fields. The residual two-timeout semantics (engine fitness penalizes, post-eval reports coverage-labeled means) is **by design** — labels carry the burden (triage v0.17 §3; U11/#368) | — |
| FR-RUN-056 | MUST | After the existing pre-flight evaluation — on **both launch and resume** — a backend `validate_seed_metrics` hook fails fast (**before iteration 0**) when a metric named in `database.feature_dimensions` is absent or non-numeric in the seed's pre-flight metrics; the error names the missing dimension and the available metrics. The builtins `complexity`/`diversity`/`combined_score` are **allowlisted** (computed inside OpenEvolve); ShinkaEvolve's hook is a no-op (its only metric contract is `combined_score`); the hook is skipped whenever pre-flight itself is skipped (empty dataset) (U8/#370) | — |
| FR-RUN-057 | SHOULD | OpenEvolve-only: when `checkpoint_interval` is **unset** (absent from both config.yaml and `--config-override`), the effective interval defaults to `max(1, min(100, iterations//10))` so a killed ≤100-iteration run has a mid-run checkpoint to resume from; an explicit `checkpoint_interval` is **never overridden**, and the S17a-12 phase-1 warning keeps firing only on explicit equality. Release-noted v0.18 default-path change (U6 phase 2/#364) | — |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Problem version not found | Error: "Problem version '<tag>' not found" | 1 |
| LLM not registered | Error: "LLM '<name>' not found" | 1 |
| Local LLM not loaded | Error: "LLM '<name>' is not loaded. Run `revolver llm start <name>` first." | 3 |
| Remote LLM API key not set | Error: "API key not configured. Set <ENV_VAR> environment variable." | 3 |
| Dataset not found | Error: "Dataset '<name>' not found" | 1 |
| Dataset split is neither `train` nor `both` | Warning: "dataset '<name>' has split='eval' (expected 'train'). Proceeding anyway." A `both` dataset is a valid training split and triggers **no** warning. | 0 (continue) |
| Dataset hash mismatch | Warning: "Dataset '<name>' has been modified since registration. Results may not be reproducible." | 0 (continue) |
| Dataset incompatible with problem version | Warning: "Dataset '<name>' is not declared compatible with version '<tag>'." | 0 (continue) |
| Backend crashes during run | Error: "<Backend> failed: <error>". Run status set to `failed`, `run-error.log` written, lock removed. Preserve partial results if any. | 4 |
| Resume with no resume state | Error: "No checkpoint found for run '<run-id>'" (OE) / "No results database found for run '<run-id>'" (Shinka) | 1 |
| `--backend shinka` but ShinkaEvolve not installed | Error: "Backend 'shinka' is not installed. Install with `pip install revolver[shinka]`." | 3 |
| `--backend` with unknown name | Error: "Unknown backend '<name>'. Available: openevolve, shinka." | 1 |
| `--selection` value not supported by the selected backend (e.g. `--selection ucb` on `--backend openevolve`) | Error: "Selection strategy '<value>' is not supported by backend 'openevolve'. Supported: fixed." | 1 |
| `--from-checkpoint` on a run with no checkpoint yet (too short to checkpoint) | Error: "No checkpoint found for run '<run-id>' — the run stopped before its first checkpoint." | 1 |
| Another local run already in progress | Error: "A local LLM run is already in progress (see `.revolver/runs/locks/`). Wait for it to complete or cancel it." | 3 |
| `--dry-run` with missing or invalid inputs | Error reported as normal (exit 1), no run launched | 1 |
| Not in a Revolver project | Error: "Not a Revolver project" | 1 |
| `delete` with non-existent run | Error: "Run '<run-id>' not found" | 1 |
| `delete` in JSON mode without `--force` | Error: "Use --force to delete in JSON mode (no interactive prompt)" | 1 |
| `delete` confirmation declined by user | No deletion, exit silently | 1 |
| `evaluation.on_timeout` set to a value other than `penalize`/`drop`, or `evaluation.timeout_score` non-finite | Error: "Invalid evaluation.on_timeout '<value>'. Supported: penalize, drop." / "evaluation.timeout_score must be a finite number." Rejected at run **and** `--dry-run` (FR-RUN-054). | 1 |
| Seed program's pre-flight metrics lack a metric named in `database.feature_dimensions` (or its value is non-numeric) | Error: "Feature dimension '<name>' not found in seed metrics. Available metrics: <list>." Fails **before iteration 0** on both launch and resume (FR-RUN-056); the builtins `complexity`/`diversity`/`combined_score` never trigger this error. | 1 |
| Explicit `--backend` differs from the problem version's stored backend | Warning on stderr: "Warning: version '<tag>' stores backend '<stored>' but --backend '<explicit>' was given. Proceeding with '<explicit>'." Proceeds with the explicit backend (FR-RUN-047). | 0 (continue) |

---

## 5. Run Manifest Format

`.revolver/runs/<id>/manifest.yaml`:

```yaml
run_id: "run-20260310-143000"
status: "completed"
backend: "openevolve"             # evolution backend used (FR-RUN-047, ADR-007)
created_at: "2026-03-10T14:30:00Z"
generation_time_s: 13500
iterations: 200

token_usage:
  prompt_tokens: 1245000
  completion_tokens: 328000
  total_tokens: 1573000          # cost not reported (S15 / #300)

lineage:
  problem_version: "v1.1"
  problem_hash: "sha256:e5f6g7h8..."
  dataset: "train-small"
  dataset_hash: "sha256:f1e2d3c4..."
  llm: "claude-opus"
  llm_model: "claude-opus-4-6"

resumed_from: null
config_file: "config.yaml"        # relative path to config in run dir (verbatim content stored in SQLite as config_snapshot)

solution:                          # auto-created rank-1 solution
  id: "sol-20260310-143000"
  rank: 1
  best_score: 0.91
  alias: "claude-small-v1.1"
  program: "programs/rank-1.py"

programs:                          # all programs stored from backend output
  - rank: 1
    score: 0.91
    file: "programs/rank-1.py"
  - rank: 2
    score: 0.85
    file: "programs/rank-2.py"
  - rank: 3
    score: 0.79
    file: "programs/rank-3.py"
```

---

## 6. Dependencies

- Requires an initialized project ([spec-project.md](spec-project.md))
- Requires a problem version ([spec-problem.md](spec-problem.md))
- Requires a registered LLM ([spec-llm.md](spec-llm.md))
- Requires a registered dataset ([spec-dataset.md](spec-dataset.md))
- Solutions produced here are consumed by `revolver eval` ([spec-eval.md](spec-eval.md)) and `revolver benchmark` ([spec-benchmark.md](spec-benchmark.md))
