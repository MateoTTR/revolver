# DES-005 — `revolver run` — Run Orchestration

**Version**: 0.9.0 — v0.18 eval-honesty semantic slice + top-N promotion (U13/U11/U4/U8/U6p2 + reap hardening: §2.1/§2.3/§2.5/§3.2/§4.1–4.6/§4.8/§7/§7.3/§8/§10/§11/§14.1; FR-RUN-052..057, FR-PRB-016, FR-SOL-021, FR-EVL-021 amended)
**Date**: 2026-07-05
**Status**: Draft
**Traceable to**: [spec-run.md](../../specs/spec-run.md), [Architecture](../architecture.md) §4/§6.1, [ADR-006](../adr/ADR-006-openevolve-instance-injection.md), [ADR-007](../adr/ADR-007-pluggable-evolution-backend.md), [DES-001 Data Model](DES-001-sqlite-data-model.md) §3.5–3.6 (runs, solutions), [POC #12](../../pocs/poc-openevolve-integration.md)

---

## 1. Overview

This document details the design of the `revolver run` commands: `run` (launch an evolution run), `status`, `resume`, `list`, and `info`. The **run** is the first-class physical entity that owns all artifacts (resume state, config, wrapper evaluator, programs). Solutions are lightweight DB references pointing to (run_id, rank). These commands orchestrate the selected evolution backend to generate solutions from a problem version + LLM + dataset combination.

> **Backend mediation (ADR-007)**: since [ADR-007](../adr/ADR-007-pluggable-evolution-backend.md),
> orchestration is mediated by the `EvolutionBackend` abstraction (`infra/backends/`) rather than
> calling OpenEvolve directly. OpenEvolve remains the default backend; ShinkaEvolve is an opt-in
> second backend (`revolver[shinka]`). [§4 Backend Integration](#4-backend-integration) describes
> the abstraction and how both backends implement each tier. §3 (wrapper generation) is still
> written from the OpenEvolve in-process `evaluate()` perspective; the per-backend evaluator
> contract (ShinkaEvolve's subprocess CLI wrapper) is owned by [DES-006 §1.3](DES-006-eval-loop.md).
> The DD-14 token proxy is an OpenEvolve-only mechanism ([§4.7](#47-openevolve-token-proxy-dd-14)).
> See §14.1 for the mediation summary.

### 1.1 Key Responsibilities

| Responsibility | Description |
|---|---|
| **Input validation** | Problem version, LLM, dataset exist and are usable |
| **Wrapper evaluator generation** | Transform user's `evaluate_instance()` into OpenEvolve-compatible `evaluate()` |
| **Environment setup** | Set `REVOLVER_*` env vars per ADR-006 |
| **OpenEvolve configuration** | Programmatically configure LLM endpoint, iterations, output dir |
| **Execution** | Launch OpenEvolve via controller class (not `run_evolution()`) |
| **Progress monitoring** | Display iteration count, best score, elapsed time |
| **Result collection** | Materialize the best program as `rank-1.py` in the run directory and auto-promote it (rank-1 solution reference in DB); the rest of the population stays in the backend store, materialized on demand by `solution extract` (DD-07, §7.3) |
| **Post-run evaluation** | Evaluate rank-1 program on training instances (FR-RUN-019) |
| **Concurrency control** | Per-run lock files in `.revolver/runs/locks/` |

---

## 2. Command → Layer Flow

### 2.1 `revolver run`

Launch an OpenEvolve evolution run.

```
CLI (cli/run.py)
  │ Parse: --version, --llm, --dataset, --iterations, --alias,
  │        --config-override, --temperature, --parallel, --rewrite-mode,
  │        --selection, --selection-kwarg, --llm-weight, --backend,
  │        --dry-run
  │        (--backend defaults to a None sentinel, NOT "openevolve" —
  │         absence must stay distinguishable from an explicit value; U4)
  │ Validate: all required options provided
  │        (--selection/--selection-kwarg/--llm-weight are neutral ensemble
  │         levers mapped per backend, §4.2; capability-checked at build time —
  │         --selection non-supported → reject, ADR-007 A2/A4)
  ▼
Core (core/run.py) → launch_run()
  │ 1. Resolve project root                        ──► Infra: store.find_project_root()
  │ 2. Load problem version                        ──► Infra: db.get_problem_version(tag)
  │    Verify snapshot integrity                    ──► Infra: hashing.verify_snapshot()
  │ 2b. Resolve backend (U4 — FR-RUN-047 as amended)
  │     Order: explicit --backend > the version's stored backend
  │     (FR-PRB-016, problem_versions.backend — DES-003 / DES-001 v14)
  │     > default "openevolve". The version row is loaded BEFORE
  │     get_backend() so its stored backend is available; an explicit
  │     --backend that differs from the version's stored backend WARNS
  │     on stderr (never errors). --dry-run resolves identically;
  │     resume still inherits the parent run's backend.
  │ 3. Resolve LLM                                 ──► Infra: db.get_llm(name) [global DB]
  │    If local: check loaded                       ──► Infra: ollama.is_loaded(model)
  │    If remote: check API key env var is set
  │ 4. Load dataset registration                   ──► Infra: db.get_dataset(name)
  │    Quick integrity check                        ──► Core: dataset.verify_dataset_integrity()
  │    Warn if split != 'train'                    (FR-RUN-002)
  │    Warn if not compatible with version          (FR-RUN-003)
  │ 5. Check concurrency constraints                ──► Infra: store.get_active_runs()
  │    Scan .revolver/runs/locks/ for active locks
  │    If local LLM and another local run active → error (FR-RUN-014)
  │ 6. If --dry-run: display resolved config and exit (DD-08)
  │ 7. Generate run ID                              ──► generate_run_id()
  │ 8. Create run directory                         ──► Infra: store.create_run_dir(id)
  │    .revolver/runs/<id>/
  │    .revolver/runs/<id>/programs/
  │ 9. Generate wrapper evaluator (into run dir)    ──► Core: run.generate_wrapper()
  │    The evaluation.on_timeout / evaluation.timeout_score policy
  │    (FR-RUN-054) is parsed + VALIDATED at this shared launch point on
  │    BOTH backends (bad value → exit 1, also at --dry-run) and baked
  │    into the wrapper via BackendRunSpec (§3.2)
  │ 10. Prepare environment variables               (ADR-006)
  │     REVOLVER_DATASET_DIR, REVOLVER_INSTANCE_LOG, REVOLVER_EVAL_LOG
  │     (paths point to .revolver/runs/<id>/)
  │ 11. Configure OpenEvolve programmatically       ──► Infra: openevolve.build_config()
  │     Includes: problem.md injection if present   (§4.2, DD-13)
  │ 12. Pre-flight evaluation check (implementation quality safeguard)
  │     Before launching OpenEvolve, evaluate the initial program on the
  │     first dataset instance using the generated wrapper. This catches
  │     evaluator errors (crashes, timeouts, misconfigured arguments) before
  │     wasting LLM tokens on a full evolution run.
  │     - Calls evaluator_runner.run_instance(wrapper_path, initial_program,
  │       first_instance, timeout_s=60)
  │     - If evaluation fails (crash or timeout) → abort with clear error,
  │       set run status to "interrupted"
  │     - If evaluation passes with combined_score == 0.0 → warning on stderr,
  │       proceed (some programs legitimately score zero initially)
  │     - If evaluation passes with score > 0 → log score on stderr, proceed
  │ 12b. Seed-metric validation (U8 — FR-RUN-056)   ──► Backend: validate_seed_metrics()
  │     Right after the pre-flight (both launch and resume): fail fast —
  │     before iteration 0 — when a metric named in
  │     database.feature_dimensions is absent or non-numeric in the seed's
  │     pre-flight metrics; the error names the missing dimension and the
  │     available metrics. Builtins complexity/diversity/combined_score are
  │     allowlisted (computed inside OpenEvolve). Shinka: no-op. Skipped
  │     when pre-flight itself is skipped (empty dataset). See §4.4.
  │ 13. Start token-counting proxy (§4.7, DD-14)   ──► Infra: token_proxy.start()
  │     (OpenEvolve backend only — Shinka has no proxy)
  │     Rewrite llm.base_url → proxy local URL
  │ 14. Write run lock file                         ──► Infra: store.write_run_lock(id)
  │     .revolver/runs/locks/<id>.lock
  │ 15. Launch OpenEvolve                           ──► Infra: openevolve.run()
  │ 16. Monitor progress                            ──► callback to CLI for display
  │ 17. On completion:
  │     a. Stop token proxy, read token counts      ──► Infra: token_proxy.stop()
  │     b. Materialize the best program              ──► Infra: openevolve.collect_results()
  │        as rank-1.py in .revolver/runs/<id>/programs/
  │        (the rest of the population stays in the backend store,
  │         materialized on demand by solution extract — DD-07, §7.3)
  │     c. Copy checkpoint, config, evaluator       ──► Infra: store
  │        into run directory
  │     d. Generate solution ID for rank-1          ──► generate_solution_id()
  │        Insert solution row (run_id, rank=1)     ──► Infra: db.insert_solution()
  │        Set alias (if provided)
  │     e. Post-run training evaluation             ──► Core: eval.evaluate_solution()
  │        on rank-1 solution only (FR-RUN-019)
  │     f. Store token usage in run row             ──► Infra: db.update_run_tokens()
  │     g. Update run status to 'completed'         ──► Infra: db.update_run_status()
  │     h. Write run manifest (incl. token_usage)   ──► Infra: store.write_run_manifest()
  │     i. Remove run lock                          ──► Infra: store.remove_run_lock(id)
  │ 18. Return RunResult (containing 1 SolutionResult + programs_stored + token_usage)
  ▼
Infra
  ├── store: run dirs, manifests, lock files
  ├── db: read problem/LLM/dataset, insert run + solutions, update run status + tokens
  ├── hashing: snapshot integrity verification
  ├── ollama: check model loaded (local LLMs)
  ├── openevolve: configure, launch, monitor, collect results
  ├── token_proxy: transparent HTTP proxy for token counting (DD-14)
  └── dataset (core): integrity verification
```

### 2.2 `revolver run status`

Show the status of current active runs or the most recent run.

```
CLI (cli/run.py)
  │ Parse: (no options)
  ▼
Core (core/run.py) → get_run_status()
  │ 1. Scan .revolver/runs/locks/ for active locks  ──► Infra: store.get_active_runs()
  │ 2. For each lock file: validate PID still alive
  │    Remove stale locks (PID dead)
  │ 3. If active runs found: read progress from each lock file
  │ 4. If no active: query most recent run           ──► Infra: db.get_latest_run()
  │ 5. Return RunStatus (with list of active run_ids)
  ▼
Infra
  ├── store: scan locks/ directory, read lock files
  └── db: query latest run
```

### 2.3 `revolver run resume`

Resume a run from its checkpoint. Creates a **new run** with `resumed_from` pointing to the parent run. The parent run and its solutions/eval results remain immutable.

```
CLI (cli/run.py)
  │ Parse: --run <run_id>
  ▼
Core (core/run.py) → resume_run()
  │ 1. Resolve run                                  ──► Infra: db.get_run(run_id)
  │ 2. Load run metadata                            (problem_version, llm, dataset, config)
  │ 3. Locate checkpoint dir                        ──► store: .revolver/runs/<run_id>/oe-checkpoint/
  │ 4. Validate checkpoint exists and is non-empty
  │ 5. Validate run status is 'completed', 'interrupted', or 'completed_with_errors'
  │    (cannot resume a 'running' run)
  │ 6. Load original problem version                ──► Infra: db.get_problem_version(tag)
  │ 7. Load original LLM config                     ──► Infra: db.get_llm(name)
  │ 8. Load original dataset                        ──► Infra: db.get_dataset(name)
  │ 9. Create NEW run with resumed_from: <run_id>   ──► generate_run_id()
  │ 10. Create new run directory                    ──► Infra: store.create_run_dir(new_id)
  │ 11. Copy wrapper from parent run (DD-09)        ──► Infra: store
  │     (wrapper reused, not regenerated — the resumed run inherits the
  │      parent wrapper's baked evaluation.on_timeout policy, FR-RUN-054)
  │ 12. Copy parent checkpoint into new run dir     ──► Infra: store
  │ 13. Reconstruct environment and OpenEvolve config
  │     (same as original run, from parent metadata)
  │ 13b. Pre-flight evaluation + seed-metric validation (as §2.1 steps 12/12b)
  │     validate_seed_metrics() fires on resume too (FR-RUN-056); skipped
  │     when pre-flight is skipped (empty dataset)
  │ 14. Write run lock file                         ──► Infra: store.write_run_lock(new_id)
  │ 15. Launch OpenEvolve with checkpoint           ──► Infra: openevolve.run(checkpoint=...)
  │ 16. Monitor progress                            ──► callback to CLI for display
  │ 17. On completion (same as fresh run):
  │     a. Materialize the best program as rank-1.py
  │        in .revolver/runs/<new_id>/programs/
  │        (the rest of the population stays in the backend store,
  │         materialized on demand by solution extract — DD-07, §7.3)
  │     b. Copy checkpoint, config into new run directory
  │     c. Generate solution ID for rank-1
  │        Insert solution row (run_id, rank=1) in DB
  │     d. Post-run training evaluation on rank-1 solution
  │     e. Update run status to 'completed'
  │     f. Write run manifest
  │     g. Remove run lock
  │ 18. Return RunResult
  ▼
Infra
  ├── db: read run metadata, insert new run + solutions, update run status
  ├── openevolve: launch with checkpoint
  └── store: read parent checkpoint/wrapper, create new run dir, write manifest
```

### 2.4 `revolver run list`

List runs with optional filters.

```
CLI (cli/run.py)
  │ Parse: --version, --llm, --status, --sort
  ▼
Core (core/run.py) → list_runs()
  │ 1. Query runs with optional filters             ──► Infra: db.list_runs()
  │ 2. Return list of RunSummary
  ▼
Infra
  └── db: query runs table with filters
```

### 2.5 `revolver run info`

Show detailed information about a specific run, including its solutions and resume chain.

```
CLI (cli/run.py)
  │ Parse: <run_id>
  ▼
Core (core/run.py) → get_run_info()
  │ 1. Query run metadata                           ──► Infra: db.get_run(run_id)
  │ 2. Query associated solutions                   ──► Infra: db.get_solutions_for_run(run_id)
  │ 3. Read programs list from run manifest          ──► Infra: store.read_run_manifest(run_id)
  │    (programs with ranks and scores for display;
  │     programs_extracted = len(programs))
  │ 3b. Read backend store total + run best          ──► Backend: total_programs (None on OE),
  │    (programs_in_db + rank-1 score fallback)            run_best_score for the labeled fallback
  │ 3c. Read post-run training-eval aggregate        ──► Infra: db (eval_metadata/eval_instances,
  │    (mean + instances_valid/instances_total             written via core.eval — FR-RUN-019, §7)
  │     coverage — FR-RUN-053)
  │ 4. Query resume chain (CTE recursive)           ──► Infra: db.get_resume_chain(run_id)
  │ 5. Return RunInfo (solutions + programs + programs_extracted + total_programs + run_best_score
  │    + post_eval_score / post_eval_instances_valid / post_eval_instances_total — FR-RUN-055)
  ▼
Infra
  └── db: query runs + solutions tables
```

> **Honest dual-score display (S18 / U11 — FR-RUN-055).** `run info` renders the engine best
> labeled **"engine, single eval"** (a max over single, survivorship-prone evaluations) NEXT TO
> the post-run training-eval mean labeled with its **coverage**
> (`instances_valid/instances_total`, FR-RUN-053). The #306 display-time fallback (rank-1
> solution score ← `run_best_score`, display-only — not a DB write) carries the same
> "engine, single eval" label, so the inflated engine number never renders bare. JSON output
> carries both fields (§8 `RunInfo`). The residual **two timeout semantics** — engine fitness
> *penalizes* timeouts (FR-RUN-054, evolution pressure) while post-eval reports honest
> coverage-labeled means (reporting) — is **by design**: the labels carry the burden
> (triage-feedback-v017 §3).

---

## 3. Wrapper Evaluator Generation

A central mechanism of `revolver run` is generating a wrapper evaluator that bridges the user's `evaluate_instance()` function with OpenEvolve's `evaluate(program_path)` interface (ADR-006).

### 3.1 User-Provided Code

The user writes **only** the single-instance evaluation logic in `evaluator.py`:

```python
def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    """Evaluate one program against one instance. Return metrics dict."""
    # User's domain logic here
    ...
    return {"combined_score": 0.85, "makespan": 142.5}
```

### 3.2 Generated Wrapper

Revolver generates a `_revolver_evaluator.py` file in the run's directory that wraps the user's function:

```python
"""Auto-generated by Revolver. Do not edit."""
import os
import sys
import sqlite3
import statistics
from pathlib import Path

# Import user's evaluator from the problem version snapshot
sys.path.insert(0, "{snapshot_dir}")
from evaluator import evaluate_instance

# Baked at generation time from evaluation.on_timeout / evaluation.timeout_score
# (FR-RUN-054; validated at the launch point, inherited on resume via DD-09)
ON_TIMEOUT = "{on_timeout}"        # "penalize" (default) | "drop"
TIMEOUT_SCORE = {timeout_score}    # finite float, default 0.0


def evaluate(program_path: str) -> dict[str, float]:
    instance_path = os.environ.get("REVOLVER_INSTANCE_PATH")

    if instance_path:
        # Single-instance mode (revolver eval / revolver benchmark)
        return evaluate_instance(program_path, instance_path)

    # Aggregated mode (OpenEvolve training)
    dataset_dir = os.environ["REVOLVER_DATASET_DIR"]
    instances = sorted(
        p for p in Path(dataset_dir).iterdir()
        if not p.name.startswith(".")
    )

    all_metrics = []       # entries feeding the mean (incl. penalty entries)
    valid = 0              # instances that genuinely returned metrics
    for inst in instances:
        try:
            # Per-instance timeout enforced by the template's runner
            metrics = evaluate_instance(program_path, str(inst))
            all_metrics.append(metrics)
            valid += 1
            _log_instance(inst.name, metrics)
        except TimeoutError:
            # Distinct timeout branch on BOTH backends (FR-RUN-053):
            # record the timed-out instance on the side-channel, then
            # apply the baked policy (FR-RUN-054).
            _log_timeout(inst.name)
            if ON_TIMEOUT == "penalize":     # default — v0.18 flip
                all_metrics.append({"combined_score": TIMEOUT_SCORE})
            # "drop": fall through — survivor-mean (0.17 behavior)
        except Exception:
            pass  # Skip failed instances during training

    if not all_metrics:
        return {
            "combined_score": 0.0,
            "instances_valid": 0.0,
            "instances_total": float(len(instances)),
        }

    combined = statistics.mean(m["combined_score"] for m in all_metrics)
    result = {"combined_score": combined}

    # Include other metrics as aggregated means. The reserved `instances_`
    # coverage prefix is NEVER averaged (FR-RUN-053; read-path counterpart:
    # FR-EVL-021 as amended, DES-006 §4.3).
    all_keys = set()
    for m in all_metrics:
        all_keys.update(m.keys())
    for key in sorted(all_keys):
        if key != "combined_score" and not key.startswith("instances_"):
            vals = [m[key] for m in all_metrics if key in m]
            if vals:
                result[key] = statistics.mean(vals)

    # Coverage keys: metadata, not fitness (FR-RUN-053)
    result["instances_valid"] = float(valid)
    result["instances_total"] = float(len(instances))
    return result


def _log_instance(instance_id: str, metrics: dict[str, float]) -> None:
    """Optional: log per-instance results to SQLite side-channel."""
    log_path = os.environ.get("REVOLVER_INSTANCE_LOG")
    if not log_path:
        return
    try:
        conn = sqlite3.connect(log_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS instance_log "
            "(instance_id TEXT, metric TEXT, value REAL, pid INTEGER)"
        )
        for metric, value in metrics.items():
            conn.execute(
                "INSERT INTO instance_log VALUES (?, ?, ?, ?)",
                (instance_id, metric, value, os.getpid()),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Side-channel is best-effort


def _log_timeout(instance_id: str) -> None:
    """Record a timed-out instance on the side-channel (FR-RUN-053).

    Same best-effort SQLite channel as _log_instance, with a timeout
    status marker — timed-out instances stay visible even under
    on_timeout=drop.
    """
    ...
```

**Timeout policy and coverage keys (S18 / U13 — FR-RUN-053/054):**

- **`evaluation.on_timeout: penalize | drop` + `evaluation.timeout_score` (FR-RUN-054).** Parsed
  and **validated** at the shared launch point in `core/run.py` on BOTH backends (an invalid
  `on_timeout` value or a non-finite `timeout_score` → exit 1 at run *and* `--dry-run`), carried
  on `BackendRunSpec` (`on_timeout`, `timeout_score` — §4.1) and baked as constants into the
  generated wrapper. `evaluation.*` is a **validated, Revolver-owned config section** (previously
  the OE backend popped the whole section uninspected and Shinka never inspected its keys — typos
  were silent). **Default `penalize`** — a deliberate fitness-landscape change, release-noted: a
  timed-out instance contributes `timeout_score` (finite, default `0.0`) to the mean instead of
  being silently dropped. `drop` restores the 0.17 survivor-mean. On a run with **zero timeouts**
  the two policies produce identical scores. `resume` inherits the parent wrapper's **baked**
  policy (DD-09, §2.3 step 11).
- **Coverage keys (FR-RUN-053).** Both wrapper templates emit `instances_valid` /
  `instances_total`; the `instances_` metric prefix is **reserved** and excluded from the wrapper
  mean here and from read-time aggregation (FR-EVL-021 as amended — DES-006 §4.3 owns the
  read/eval-path aggregation; DES-006's "Numeric-only aggregation guard (B1)" blockquote delegates
  the wrapper mean loop to this section). Timed-out instances are additionally recorded on the
  side-channel, so coverage is auditable per instance.
- **Shinka wrapper parity.** The ShinkaEvolve subprocess wrapper (`_shinka_evaluator.py`,
  DES-006 §1.3) mirrors the same aggregation contract: it gains a **distinct `TimeoutError`
  branch** (previously a single catch-all exception branch — sprint-018 fact 6), the same
  coverage keys, and the same baked timeout policy.

### 3.3 Generation Logic

```python
def generate_wrapper(
    snapshot_dir: Path,
    output_dir: Path,
) -> Path:
    """
    Generate the wrapper evaluator file.

    Args:
        snapshot_dir: Path to .revolver/problem/<tag>/ (immutable snapshot)
        output_dir: Path to run directory (.revolver/runs/<id>/)

    Returns:
        Path to the generated _revolver_evaluator.py

    Detection order (D-005-a):
        1. If evaluate() exists → use as-is (priority, legacy mode)
        2. Else if evaluate_instance() exists → generate wrapper
        3. Else → raise EvaluatorError
    """
```

### 3.4 Legacy Mode

> See [DES-006 §3.3](DES-006-eval-loop.md#33-evaluator-resolution) for detailed dual-mode detection logic used by `revolver eval`.

If the user's evaluator already defines `evaluate(program_path)`, Revolver uses it directly without generating a wrapper. This supports advanced users who want full control over the aggregation strategy and maintains backward compatibility with standard OpenEvolve evaluators. The user may also define both `evaluate()` and `evaluate_instance()` in the same file; Revolver only checks for `evaluate()` first.

Detection order (D-005-a):
1. `evaluate(program_path)` → use as-is (legacy mode, priority)
2. `evaluate_instance(program_path, instance_path)` → generate wrapper
3. Neither → error

**Trade-offs of legacy mode**:

| Capability | `evaluate_instance()` (wrapper) | `evaluate()` (legacy) |
|---|---|---|
| User writes | Single-instance logic only | Full dual-mode evaluator (both aggregated and single-instance) |
| Aggregation strategy | Fixed: `mean(combined_score)` under the `evaluation.on_timeout` policy (FR-RUN-054); `instances_*` coverage keys excluded (FR-RUN-053) | User-controlled (min, max, weighted, etc.); no baked timeout policy or coverage keys |
| Training per-instance side-channel | Supported (wrapper logs each instance) | Not available (evaluator is a black box to Revolver) |
| Post-run eval (FR-RUN-019) | Full per-instance results | Full per-instance results (same as wrapper) |
| `revolver eval` / `benchmark` | Full per-instance results | Full per-instance results (same as wrapper) |
| Final traceability | Complete | Complete |

The key insight: **legacy mode does not affect final traceability**. The post-run eval (§7) always evaluates the best program per-instance regardless of the evaluator mode. The only difference is per-instance visibility *during* the evolution run (side-channel), which is an observability convenience (FR-RUN-026, SHOULD), not a traceability requirement.

The recommended approach is `evaluate_instance()` for simplicity. Legacy mode is for users who need custom aggregation (e.g., worst-case optimization using `min` instead of `mean`).

### 3.5 Scope of the Generated Wrapper

The generated `_revolver_evaluator.py` is stored in the run directory (`.revolver/runs/<id>/`) and is used **exclusively by OpenEvolve** during the evolution run (aggregated mode). It is **not** used by `revolver eval` or `revolver benchmark`.

When `revolver eval` evaluates a solution ([DES-006](DES-006-eval-loop.md) §3.3), it loads the evaluator directly from the problem version snapshot and calls either `evaluate_instance()` (preferred) or `evaluate()` with `REVOLVER_INSTANCE_PATH` set. The wrapper is not involved because `revolver eval` always operates in single-instance mode.

```
OpenEvolve training:  _revolver_evaluator.py → evaluate() (aggregated mode)
                      └── calls evaluate_instance() per instance
                      └── returns mean(combined_score)

revolver eval:        .revolver/problem/<tag>/evaluator.py → evaluate_instance() (direct)
                      └── returns per-instance metrics
```

---

## 4. Backend Integration

`revolver run` does not call any evolution engine directly. Since [ADR-007](../adr/ADR-007-pluggable-evolution-backend.md),
`core/run.py` resolves a backend by name (`get_backend(name)`) and drives the whole engine-coupled
surface — config build, wrapper generation, launch, resume, live progress, population parsing, token
collection — through the `EvolutionBackend` protocol (`infra/backends/base.py`). Two adapters
implement that protocol: `OpenEvolveBackend` (`infra/backends/openevolve.py`, default) and
`ShinkaBackend` (`infra/backends/shinka.py`, opt-in `revolver[shinka]`). The `--backend
{openevolve,shinka}` flag selects one per run; since S18 (U4) the effective backend resolves
**explicit `--backend` > the problem version's stored backend (FR-PRB-016) > default
`openevolve`** — the CLI flag and `RunConfig.backend` default to a **`None` sentinel** so absence
stays distinguishable from an explicit `openevolve`, and an explicit flag that differs from the
version's stored backend warns on stderr (never errors). The choice is persisted on the
run and inherited by `resume` (**FR-RUN-047** as amended).

This section describes the protocol tiers and how each adapter implements them. The unit shared
across both backends is **tokens** ([ADR-007 D2](../adr/ADR-007-pluggable-evolution-backend.md#d2--tokencost-tracking-token-primary-on-both-backends)):
no USD cost is reported (S15 / #300). Everything *downstream* of the engine (program collection into
`programs/rank-N.py`, solution creation, eval, benchmark) stays backend-agnostic by construction
(#267 §1.4); the abstraction is confined to this section.

### 4.1 The `EvolutionBackend` Protocol

`EvolutionBackend` (`infra/backends/base.py`, `@runtime_checkable Protocol`) is the contract every
adapter satisfies. Each adapter also declares three class attributes the orchestrator reads without a
method call: `name` (`"openevolve"` / `"shinka"`), `default_output_subdir` (the engine output
directory inside a run dir — `"oe-output"` / `"shinka-output"`), and `wrapper_filename` (the
generated wrapper's name — `_revolver_evaluator.py` / `_shinka_evaluator.py`).

The methods group into tiers. Two engine-neutral data carriers cross the boundary:
`BackendRunSpec` (the run to launch/resume — snapshot dir, LLM, run dir, resolved iterations, CLI
overrides, ensemble, timeout policy `on_timeout`/`timeout_score` (FR-RUN-054), …) and
`BackendRunResult` (`best_score`, `best_program`, `output_dir`).

| Tier | Protocol method(s) | Purpose |
|---|---|---|
| **Availability / capabilities** | `is_available()`, `capabilities()` | Install probe (`doctor`/`setup`) and the honest capability matrix (§4.6) |
| **Config build** | `config_template()`, `validate_config()`, `build_config()`, `resolved_config()` | Scaffold (`project init`), warn on unknown keys (`problem version create`), merge the runtime config, project it to the neutral dry-run view |
| **Wrapper generation** | `generate_wrapper()` | Emit the per-backend evaluator bridging the user's `evaluate_instance()` to the engine's evaluator contract |
| **Seed-metric validation** | `validate_seed_metrics()` | Post-pre-flight fail-fast: metrics declared in `database.feature_dimensions` must be present and numeric in the seed's pre-flight metrics (§4.4, FR-RUN-056; OE-enforced, Shinka no-op) |
| **Launch / resume** | `launch()`, `resume()` | Run a fresh evolution, or continue from a parent run (backend-defined resume semantics) |
| **Live progress** | `read_progress()` | Cheap `(iterations_done, best_score)` poll for `run status` (active path) |
| **Population / counts** | `parse_population()`, `count_valid()`, `count_evolved_children()` | Ranked population for `run population`; valid-program and evolved-children counts |
| **Token collection** | `wants_http_proxy()`, `collect_token_usage()` | Declare the token strategy and read engine-native accounting when available |

Each tier is detailed below, naming the real method signatures (`infra/backends/base.py`) and how
`OpenEvolveBackend` and `ShinkaBackend` implement it.

### 4.2 Config Build Tier

`build_config(spec: BackendRunSpec) -> dict[str, Any]` merges the problem version's `config.yaml`
with the LLM registry projection and CLI overrides into the engine's native config shape. The merge
order is **last-wins** and identical in spirit across backends (base config → LLM projection → CLI
`--temperature`/`--parallel` → problem-description injection → `--iterations` → `--rewrite-mode` →
**ensemble neutral levers** (`--selection` → sampler/selection strategy, `--llm-weight` → per-member
weight patch, `--selection-kwarg` → per-sampler kwargs) → `--config-override` dotted `key=value`). Per-LLM
`reasoning_effort` is **not** a `run` flag — it rides on the LLM/ensemble-member registry entry and is
projected at the *LLM projection* step above (per-member on OE, a single global pool on Shinka; FR-LLM-026).
The ensemble levers land in the
last-wins order **before** `--config-override`, so a raw `--config-override` still wins as the final
escape hatch. **The neutral levers are first-class** — common ensemble/selection knobs get neutral
names mapped per backend (ADR-007 A1); **`--config-override` is the reserved escape hatch** for
backend-exclusive structural keys, not the normal path for these levers (it also cannot address
array members — `_set_nested` has no `[i]` indexing — so per-member weight/effort is *only*
reachable via the dedicated flags). `resolved_config(config, overrides)` projects the merged
config to the engine-neutral `ResolvedConfig` for `--dry-run` display, routing backend-exclusive
parameters into a `backend_extras` dict ([ADR-007 D4](../adr/ADR-007-pluggable-evolution-backend.md#d4--neutral-config-surface-resolvedconfig--backend_extras)).
`validate_config()` returns human-readable warnings (never raises) and degrades gracefully to `[]`
when the engine is not installed; `config_template()` returns the per-backend `config.yaml` scaffold
served by `project init`.

**`OpenEvolveBackend`** (`build_config` → module-level `build_config()`):

- Single-LLM injection maps the registry entry to OpenEvolve keys: `base_url` → `llm.api_base`,
  `model` → `llm.primary_model`, `api_key_env` → `llm.api_key_env` (the env var **name**, not the
  secret — DD-15). Local (`source == "local"`) entries with no key get an `api_key: "ollama"`
  placeholder (the OpenAI SDK requires a non-empty key).
- Ensemble mode (`--llm <ensemble>`) emits an `llm.models` array instead of `llm.primary_model`,
  mapping each member to `name`/`api_base`/`api_key`/`weight`/`temperature`/`max_tokens`/
  `reasoning_effort` (the `${ENV}` syntax for keys). OpenEvolve's ensemble sampler is
  **weighted** (`ensemble_model="weighted"`, static weighted-random), exposed under the neutral
  selection vocabulary `capabilities().selection_strategies == ("fixed",)`.
- **Selection strategy (ADR-007 A2/A4).** `--selection` non-`fixed` (`ucb`/`ucb1`/
  `thompson`) → **rejected** with a clear error naming `fixed` as the only accepted OE value (the
  orchestrator-level capability check in `core/run.py` gates this before `build_config()` via a plain
  `selection in selection_strategies` membership test; a defensive belt-and-braces error also lives
  here). `fixed`/unset is the implicit weighted mode.
- **`--llm-weight model=w` (ADR-007 A1/M3)** is **honored**: it patches the resolved member's
  `weight` (CLI override wins over the registry `weight`) before the `llm.models` array is built.
- **Per-member `reasoning_effort` (ADR-007 A3.2, FACT A) is honored per member**
  (`LLMModelConfig.reasoning_effort`): the effective value is `member.reasoning_effort` if set, else
  the member LLM's registry-level `reasoning_effort`; written onto `llm.models[].reasoning_effort`
  when non-`None`. The single-LLM path maps `spec.llm.reasoning_effort` directly.
- `cascade_evaluation` is forced to `false` unless the problem config sets it (Revolver evaluators
  do not define `evaluate_stage1/2/3`). Google's `generativelanguage.googleapis.com` endpoint is
  detected by `base_url` and `random_seed` is nulled at both the top level and under `llm` (DD-17),
  because that API rejects `seed` with HTTP 400.
- **Slow local-endpoint timeout (#307, v0.15.0).** When the registered LLM has no explicit
  `timeout_s` and is `source == "local"`, `build_config()` sets `llm.timeout = 600` s
  (`DEFAULT_LOCAL_LLM_TIMEOUT_S`). OpenEvolve's OpenAI client defaults to 60 s, which aborts slow
  local endpoints (e.g. a subscription-backed local OpenAI-compatible shim at 50–530 s/call) into
  a retry storm and a proxy
  `BrokenPipeError`. Remote APIs keep OpenEvolve's default. A `config.yaml` `llm.timeout` or
  `--config-override llm.timeout=…` still wins (`setdefault` + overrides applied last).
- **Default checkpoint cadence (U6 phase 2, S18 — FR-RUN-057).** When `checkpoint_interval` is
  **unset** (absent from both the problem `config.yaml` and `--config-override`), `build_config()`
  sets the effective interval to `max(1, min(100, iterations // 10))` so a killed ≤100-iteration
  run has a mid-run checkpoint to resume from (previously the engine default of 100 meant zero
  mid-run checkpoints for the whole default regime). An **explicit** value is never overridden,
  and the S17a-12 phase-1 warning (`interval ≥ iterations` → "a killed run cannot be resumed")
  keeps firing only on an explicit equality. OpenEvolve-only — Shinka has no
  `checkpoint_interval`. Release-noted default-path change (sprint-018 exit criterion 10).
- `resolved_config()` maps `max_iterations` → iterations, `database.num_islands` → num_islands,
  `llm.temperature` → temperature, and pushes OE-exclusive keys (`checkpoint_interval`,
  `feature_dimensions`, `feature_bins`, `parallel_evaluations`, `diff_based_evolution`,
  `max_code_length`) into `backend_extras` only when set. `validate_config()` strict-parses against
  the OpenEvolve `Config` dataclass (`dacite`), stripping Revolver-injected keys first.

**`ShinkaBackend`** (`build_config` builds the nested `evo_config`/`db_config`/`job_config` shape):

- The LLM is projected to a Shinka model string ([ADR-007 D5](../adr/ADR-007-pluggable-evolution-backend.md#d5--llm-registry-no-schema-change-per-backend-projection)):
  local entries become `local/<model>@<base_url>?api_key_env=<env>` (synthesizing
  `OLLAMA_API_KEY` when none is registered); remote entries use the model id as-is and map the
  provider-standard env var (`ANTHROPIC_API_KEY`, …) to the registered key var via an `llm_env`
  export map consumed by `launch()`. For a single LLM, `evo_config.llm_models` is a single-element
  list and `llm_dynamic_selection = "fixed"`.
- **Multi-LLM ensemble → bandit selection (ADR-007 A2/A3, supersedes the earlier "ensembles raise
  ValidationError" text).** Ensembles are now **first-class**: each member is projected to a Shinka
  model string and appended to `evo_config.llm_models[]` (order-preserving). `evo_config.
  llm_dynamic_selection` is set from `--selection` (`fixed`/`ucb`/`ucb1` [alias of `AsymmetricUCB`,
  same class]/`thompson`; default `fixed` when unset — the S14 single-LLM path is the one-member,
  `fixed` case of this same code, zero behavior change).
  - **Weights → `prior_probs`, fixed-only (FACT B).** Under `--selection` `fixed` (or unset), member
    weights (registry weights with `--llm-weight model=w` overrides applied on top) build the
    `FixedSampler.prior_probs` positional vector, aligned to `llm_models` order and renormalized to
    sum 1 (**apples-to-apples with the OE weighted ensemble**). Under `ucb`/`ucb1`/`thompson` the
    arms start **uniform** and weights are **ignored**; `prior_probs` exists only on `FixedSampler`,
    so it is **not** sent to the adaptive samplers (passing it raises `TypeError`). Revolver **warns**
    when non-uniform weights or `--llm-weight` are supplied under an adaptive mode.
  - **`--selection-kwarg k=v` branched per sampler (ADR-007 A5).** Shinka spreads
    `llm_dynamic_selection_kwargs` **verbatim** into the *selected* sampler's constructor, so a wrong
    key raises `TypeError`. Revolver routes kwargs per sampler and never sends a union:
    `cost_aware_coef` is valid **only for `ucb`/`ucb1`** (Revolver default **0** — the flat-rate/
    bridge case, M4 — not Shinka's own `0.5`; inert anyway when per-model cost is undifferentiated);
    a kwarg not accepted by the selected sampler is dropped with a warning (would be silently ignored
    by `FixedSampler`, or `TypeError` under `ThompsonSampler`).
  - **`reasoning_efforts` is a single global pool (FACT A).** Per-member effort is **OE-only**;
    Shinka's `reasoning_efforts` (like `temperatures`/`max_tokens`) is one global pool sampled
    independently of the chosen model. Revolver collects each member's effective effort; if all
    agree it writes `llm_kwargs.reasoning_efforts = [<value>]`; if members **disagree** it applies
    the **highest-effort-wins** disagreement policy (total order `min < low < medium < high < max`,
    a conservative default that never under-thinks) **and warns** that Shinka cannot honor per-member
    effort. It additionally warns (once) that effort is **inert for `local`/bridge-sourced members**
    (Shinka classes them `is_reasoning_model=False` → effort forced to `"disabled"`).
- Revolver injects safer defaults than Shinka's own: `llm_kwargs.max_tokens` defaults to 16384
  (Shinka's 4096 starves thinking-capable models, which return empty content) and
  `max_patch_attempts` defaults to 10 (Shinka's 1 loses a whole generation on a single malformed
  patch). Both respect an explicit `config.yaml` value and `--config-override`.
- **LLM request timeout (R2 / #260, S18).** The registered `--timeout` is projected as the
  engine's LLM-request timeout: `max(timeout_s over ensemble members that set it)` →
  sets/restores `shinka.llm.client.TIMEOUT` around the engine run; surfaced as `llm_timeout` in
  `resolved_config.backend_extras`. `--config-override llm_timeout=N` is the escape hatch and
  `llm_timeout=null` opts out; when unset, shinka's default (1200 s) is left untouched.
- Unsupported options are reported honestly (**FR-RUN-048**, map-with-warn): `--parallel` has no
  neutral Shinka mapping and warns on stderr instead of silently no-opping. **Ensembles are now
  supported via the bandit mapping above** (the earlier "ensembles raise `ValidationError` /
  weighted→bandit is a later phase" behavior is superseded by v0.17 — ADR-007 A2). `build_config()`
  raises `BackendUnavailableError` (exit 3) when shinka is not installed, before any side effect.
- `resolved_config()` maps `evo_config.num_generations` → iterations, `db_config.num_islands` →
  num_islands, a single-valued `llm_kwargs.temperatures` → temperature, and pushes Shinka-exclusive
  keys (`patch_types`, `max_patch_attempts`, `max_tokens`, `reasoning_efforts`, `max_api_costs`,
  `llm_timeout`, `archive_size`, …) into `backend_extras`.

> **`--source local` concurrency on Shinka (UX-5, planned S16).** `ShinkaBackend.build_config()`
> additionally pins `job_config.max_proposal_jobs = 1` for a `source == "local"` LLM unless the user
> overrides it — a serialized subscription/single-GPU endpoint cannot honor Shinka's default
> fan-out. The OpenEvolve equivalent is `--parallel 1`. See [tuning-evolution.md](../../guides/tuning-evolution.md).

### 4.3 Wrapper Generation Tier

`generate_wrapper(spec: BackendRunSpec) -> Path` writes the per-backend evaluator into the run dir
and returns its path. Both backends adapt the user's single-instance `evaluate_instance()` over the
dataset in `$REVOLVER_DATASET_DIR` (ADR-006 env-var inputs), but the *output contract* differs and
is owned by [DES-006 §1.3](DES-006-eval-loop.md):

- **`OpenEvolveBackend`** emits `_revolver_evaluator.py` exposing an in-process
  `evaluate(program_path) -> dict[str, float]` (§3). It supports legacy `evaluate()`-only evaluators
  (copied as-is) and the per-instance side-channel log. Detection order: `evaluate()` >
  `evaluate_instance()` (DD-10).
- **`ShinkaBackend`** emits `_shinka_evaluator.py`, a **subprocess CLI** evaluator honoring Shinka's
  job-scheduler argv contract (`--program_path <evolved.py> --results_dir <dir>`) that writes
  `metrics.json` + `correct.json`. It **requires** `evaluate_instance()` — the legacy
  `evaluate()`-only contract is OpenEvolve-specific and unsupported here.

On `resume`, the orchestrator copies the parent run's wrapper by its backend-owned
`wrapper_filename` rather than regenerating it (DD-09), so the exact evaluator code is preserved
across the resume chain.

### 4.4 Launch / Resume Tier

`launch(spec, config, on_progress=None) -> BackendRunResult` runs a fresh evolution;
`resume(spec, config, parent_run_dir, on_progress=None) -> BackendRunResult` continues from a parent
run with backend-defined semantics ([ADR-007 D1](../adr/ADR-007-pluggable-evolution-backend.md#d1--backend-abstraction-infrabackends)).
Both overwrite `config["output_dir"]` for their own layout, so the orchestrator persists any config
snapshot *before* calling. `spec.iterations` must already carry the parent-run fallback (FR-RUN-024)
— `core/run.py` is the single owner of iteration resolution (S14-05); the adapters guard the
contract rather than silently defaulting. `on_progress` may be ignored (live progress is served by
`read_progress()` polling).

| | `OpenEvolveBackend` | `ShinkaBackend` |
|---|---|---|
| **Engine entry** | `OpenEvolveRunner` wraps the `OpenEvolve` controller (`asyncio.run(controller.run(...))`); programmatic config, resume support (DD-04, POC #12 S7) | `ShinkaEvolveRunner` constructed in-process from `evo_config`/`db_config`/`job_config` (ADR-007 D6); `llm_env` exported via `revolver_env` before construction |
| **Launch output** | OpenEvolve writes `oe-output/` (checkpoints, `best/best_program.py`) | Engine writes `shinka-output/` (`programs.sqlite` + per-gen dirs); `launch()` then materializes the top program into `<results_dir>/best/best_program.py` so the orchestrator's `best/`-first collection does not fall through to the engine's root `init_program.py` |
| **Resume state** | Latest `checkpoint_N/` copied to `<run_dir>/oe-checkpoint` and passed as `checkpoint_path`; OpenEvolve writes fresh checkpoints under `oe-output/checkpoints/` | DB-driven: the engine auto-resumes when `results_dir` holds a `programs.sqlite` with `last_iteration > 0`. The resumed run runs on a **clone** of the parent's `shinka-output/` (`copytree` of `programs.sqlite` + sidecars, every `gen_*/` dir, and any `bandit_state.pkl`/`prompts.sqlite`) placed in the new run dir; the new generation target is `clone.last_iteration + spec.iterations`. A `resume_precheck` hook fails fast when the parent's `programs.sqlite` is missing or `last_iteration == 0` |
| **Resume artifact isolation** | New run dir is self-contained (own checkpoint copy) | **Clone-resume parity (S16 / TD-3)**: the engine runs on the **clone** in the new run dir, so the parent's `shinka-output/` is never opened for writing and stays byte-unchanged. The resumed run's token/valid/population counts are cumulative over the parent chain (the clone carries the parent's history), while `run population`/`run status` on the parent reflect only its own untouched DB. The clone IS the resumed run's artifact tree, so no post-run snapshot copy is needed |
| **Failure mapping** | `ExternalError` ("OpenEvolve run failed: …") | `ExternalError` ("ShinkaEvolve run failed: …"); the orchestrator maps engine failure to run status `failed` (FR-RUN-031) |

The orchestrator owns the fail-fast resume precheck *before* inserting the run record; the adapters'
parent-state checks are a defensive fallback, not a parallel implementation.

**Seed-metric validation hook (U8, S18 — FR-RUN-056).** `validate_seed_metrics()` is a new
protocol method the orchestrator calls **right after the existing pre-flight evaluation, on both
launch and resume** (§2.1 step 12b / §2.3 step 13b). **OpenEvolve**: fails fast — before
iteration 0 — when a metric named in `database.feature_dimensions` (read from the resolved
config) is **absent or non-numeric** in the seed's pre-flight `InstanceTestResult.metrics`; the
error names the missing dimension and the available metrics. The builtins
`complexity`/`diversity`/`combined_score` are **allowlisted** — they are computed inside
OpenEvolve and legitimately absent from evaluator output. **ShinkaEvolve**: no-op (its only
metric contract is `combined_score`). The hook is skipped whenever the pre-flight itself is
skipped (empty dataset). Rationale: without it, a missing feature metric only crashes at the
engine's seed-add — after config build, run insert, and wrapper generation (triage U8: the
friction is lateness, not opacity).

**Post-run teardown, both backends (B2 — symmetric to #224).** `launch()`/`resume()` wrap the engine
call in `try/finally` so the runner always tears down its child processes and executors, even when
the engine raises — preventing the post-run busy-loop/hang. The two child-reaping helpers
(`_current_child_pids()` snapshotting live PIDs before launch, `_reap_run_children()` reaping the
diff after) are **hoisted to `infra/backends/base.py`** and shared by both adapters (previously
Shinka-only). Each adapter adds a backend-specific `_shutdown_runner()`: `getattr`-guarded access to
the controller's executor(s), `shutdown(wait=False)` wrapped in `contextlib.suppress(Exception)` —
**never `wait=True`** (that reintroduces the #159 `ProcessPoolExecutor.shutdown(wait=True)` hang).
The run result is persisted **before** teardown runs, so reaping/shutdown cannot truncate it.

**Reap hardening (S18, carry-over #359 — recursive descendants + `killpg`).** The base-mixin reap
previously enumerated **direct** children only and killed per-PID — a grandchild spawned by an
evaluator (or surviving Shinka's single-PID wrapper kill) could outlive teardown. S18 hardens
`ChildProcessReaperMixin` in `infra/backends/base.py`: `_current_child_pids()` enumerates
descendants **recursively** (walking `/proc/<pid>/task/*/children`), and `_reap_run_children()`
reaps each survivor's whole **process group** via `os.getpgid` — the pgid logic (SIGTERM → 3 s
grace → SIGKILL, single-PID fallback when `getpgid`/`killpg` fails) is reimplemented locally in
`base.py` in PID form (`evaluator_runner` is not imported), which also guards PID reuse.
This backstop closes the Shinka single-PID wrapper-kill
grandchildren caveat (triage §1). The run-level reap lives **here**; §7's teardown note covers
the separate per-instance eval primitive (0.17.1).

### 4.5 Live Progress, Population, and Counts Tier

These read-only methods serve `run status` (active path), `run population`, and the
unproductive-run guard. All are error-tolerant — the engine may be mid-write.

- `read_progress(run_dir) -> (iterations_done, best_score)` — **OE** reads the latest checkpoint
  (`count_valid_programs` + `read_checkpoint_best_score`); **Shinka** runs cheap queries on
  `programs.sqlite` (`last_iteration` from `metadata_store`, `MAX(combined_score)`).
- `parse_population(run_dir) -> list[dict] | None` (ranked by score descending, `None` when no
  population state yet) — **OE** parses `checkpoint_N/programs/*.json` and resolves MAP-Elites
  `cell_indices` + `island` from `metadata.json`; **Shinka** reads `programs.sqlite` rows and carries
  **no** `cell_indices`/`island` (no MAP-Elites grid — callers must not assume them), aliasing
  `iteration_found` to `generation`.
  - **Score preference (S18 / U13 i — FR-RUN-052).** The OE display/ranking readers
    (`parse_population`, `read_checkpoint_best_score`) prefer a numeric `combined_score` over the
    previous sum-of-numeric-metrics; the sum remains only as the fallback when no
    `combined_score` exists, and a metrics dict lacking it never crashes the reader.
    Display/fallback-only: the solution-DB `best_score` written at run end was already
    `combined_score`-based (`recover_best_from_checkpoint` / `_extract_best_score`) — the sum
    leaked only via `run status` / `run population` display and the #306 fallback. Landing this
    **before** the FR-RUN-053 coverage keys guarantees `instances_*` are never summed into a
    displayed score.
- `count_valid(run_dir) -> int | None` — **OE** counts entries in the checkpoint `database.json`;
  **Shinka** counts `programs` rows with `correct = 1`.
- `count_evolved_children(run_dir) -> int | None` — **OE** returns `None` (the checkpoint does not
  distinguish the seed from children, so the unproductive-run check, #302, is skipped); **Shinka**
  counts programs carrying a `metadata.llm_result` (a `0` after completion means an unproductive
  run).

### 4.6 Capabilities Matrix

`capabilities() -> BackendCapabilities` returns the static, honest declaration of what a backend can
do (frozen dataclass). It drives map-with-warn behavior (**FR-RUN-048**) and the per-backend
reproducibility caveat (NFR-024, [ADR-007 D3](../adr/ADR-007-pluggable-evolution-backend.md#d3--reproducibility-scoped-per-backend)).

| Capability | `OpenEvolveBackend` | `ShinkaBackend` | Meaning |
|---|---|---|---|
| `global_seed` | `True` | `False` | Search-level reproducibility via a global seed |
| `map_elites_cells` | `True` | `False` | MAP-Elites feature-grid cells in the population (Shinka: island index only) |
| `native_cost_tracking` | `False` | `True` | Engine persists token accounting itself (OE relies on the HTTP proxy) |
| `multi_language` | `False` | `True` | Evolution of non-Python programs |
| `ensemble_model` | `"weighted"` | `"bandit"` | Multi-LLM selection semantics |
| `selection_strategies` | `("fixed",)` | `("fixed","ucb","ucb1","thompson")` | Accepted `--selection` values (ADR-007 A4); OE's static weighted sampler is exposed under the neutral `fixed` value — `ensemble_model` above is the separate sampler-semantics axis. `--selection` outside this tuple is rejected |
| `per_member_reasoning_effort` | `True` | `False` | Whether `--reasoning-effort` is honored per ensemble member (OE) or collapses to a single global pool with map-with-warn (Shinka — FACT A) |
| `top_n_extraction` | `False` | `True` | Arbitrary-rank/program promotion via `solution extract --rank N` / `--program-id` (FR-SOL-021 — the capability existed since ADR-007 with zero consumers; S18 adds the consumer, §7.3). OE stays `False` (consciously deferred): checkpoint-granularity-limited (full population only at checkpoint boundaries — ties to FR-RUN-057) and an S18 implementation would have baked the pre-FR-RUN-052 sum ordering. A non-capable backend exits 1 with a clear "not supported on `<backend>`" error |

### 4.7 OpenEvolve Token Proxy (DD-14)

Token strategy is a backend decision: `wants_http_proxy()` declares it and
`collect_token_usage(run_dir) -> TokenUsage | None` reads engine-native accounting when the engine
keeps it ([ADR-007 D2](../adr/ADR-007-pluggable-evolution-backend.md#d2--tokencost-tracking-token-primary-on-both-backends)).
The two backends sit at opposite ends:

- **`ShinkaBackend`** — `wants_http_proxy() == False`. ShinkaEvolve persists token counts per
  program, so `collect_token_usage()` sums them directly from `programs.sqlite`: prompt tokens from
  `metadata.llm_result.input_tokens`, completion tokens from `output_tokens + thinking_tokens`
  (the sum is the total completion-side count across all 0.0.7 providers). No proxy is started; the
  real LLM endpoint is stored in the config snapshot. Token counts cover stored programs only and
  slightly undercount retried generations (`llm_result` holds the last response only).
- **`OpenEvolveBackend`** — `wants_http_proxy() == True`. OpenEvolve exposes no token usage (POC #13
  finding: no per-request hooks, no token logging), so `collect_token_usage()` returns `None` and
  Revolver measures tokens out-of-band with the **`TokenCountingProxy`** (`infra/token_proxy.py`),
  whose lifecycle is owned by `core/run.py`.

**`TokenCountingProxy` mechanism (OpenEvolve only — DD-14):**

1. Before launching OpenEvolve, `core/run.py` starts a local proxy on a random free port; its
   `base_url` rewrite points OpenEvolve at the proxy instead of the real endpoint.
2. The proxy forwards every request to the real endpoint and accumulates `usage.prompt_tokens` /
   `usage.completion_tokens` from the OpenAI-compatible response. It forwards upstream HTTP errors
   verbatim (FB-01) and can optionally back off on `429` (FB-04).
3. After the run, `core/run.py` calls `proxy.stop()`, which returns the accumulated `TokenUsage`,
   and persists it on the run.

**Key properties:**

- **Transparent**: OpenEvolve sees a normal OpenAI-compatible endpoint; no engine modification.
- **Protocol-compatible**: works with any provider (Anthropic, OpenAI, Ollama) exposing `usage`.
- **Best-effort**: a response without `usage` (e.g. streaming without a final usage frame) is not
  counted; the DB token columns are NULLable for this reason.
- **Negligible overhead** (< 1 ms/request vs seconds of LLM inference); one local port allocation.
- **Per-run**: a fresh proxy is started for each run, including on `resume`.

> **No cost reported (S15 / #300, removal completed S16 / TD-1).** Revolver reports **tokens only**, on both
> backends. The #300 token-accounting spike confirmed that neither engine persists per-attempt or
> reasoning/thinking tokens, so no realistic USD figure is reachable; the `TokenUsage` model carries
> `prompt_tokens` / `completion_tokens` / `total_tokens` and no cost field. The `estimate_cost()`
> helper and the LLM `--input-cost`/`--output-cost` pricing flags/columns have been **removed**
> (schema migration v10 drops the `llms` pricing columns).

### 4.8 FR Coverage

The backend integration described in this section covers the following requirements
([spec-run.md §3](../../specs/spec-run.md)). The S13-era doc debt on FR-RUN-036..039 and the
FR-RUN-042 numbering gap is cleared here.

| Requirement | Status | Where covered |
|---|---|---|
| FR-RUN-036 | **Covered** | `run delete --force` bypasses confirmation — orchestration command, run-record + run-dir teardown. Not engine-coupled (post-engine boundary, #267 §1.4); independent of the selected backend. |
| FR-RUN-037 | **Covered** | Deleting a run cascade-deletes its solutions and eval data (DB cascade on `runs` → `solutions` → `eval_*`, DES-001 §3.5–3.8). Backend-agnostic. |
| FR-RUN-038 | **Covered** | Deleting a run removes its run directory (`.revolver/runs/<id>/`, incl. the backend's `default_output_subdir`). Backend-agnostic. |
| FR-RUN-039 | **Covered** | `run delete --json` without `--force` errors (NFR-003 non-interactive safety). Backend-agnostic. |
| FR-RUN-042 | **N/A (numbering gap)** | No requirement is defined at FR-RUN-042 — the spec list jumps FR-RUN-041 → FR-RUN-043 (a known gap carried since S13, see sprint-013 §Carry-over). Recorded here so the cross-reference resolves; no behavior is owed, so coverage is not applicable. |
| FR-RUN-047 | **Covered** | `--backend {openevolve,shinka}` selection, persisted on the run and inherited by `resume`; S18 (U4) resolution order **explicit `--backend` > version-stored backend (FR-PRB-016) > default `openevolve`** via the `None` sentinel, mismatch warn on stderr (§2.1 step 2b, §4 intro, §8, §14.1). |
| FR-RUN-048 | **Covered** | Backend capability map-with-warn (§4.2 Shinka `--parallel`/ensemble warnings, §4.6 `capabilities()`). |
| FR-RUN-049 | **Covered** | `--selection {fixed,ucb,ucb1,thompson}` neutral ensemble lever, mapped per backend; OE rejects non-`fixed` `--selection` via `capabilities().selection_strategies == ("fixed",)` (§2.1, §4.2, §4.6, §14.1; ADR-007 A2/A4). |
| FR-RUN-050 | **Covered** | `--llm-weight model=w` per-run weight override; honored on OE and Shinka-`fixed`, warned+ignored under Shinka adaptive modes (§4.2; ADR-007 A1/M3). |
| FR-RUN-051 | **Covered** | `solution extract --from-checkpoint` recovers the best program of an interrupted/failed OE run from the latest checkpoint via `recover_best_from_checkpoint()` (§7.2, B7). |
| FR-RUN-052 | **Covered** | Score display/ranking prefers a numeric `combined_score` over the sum-of-numeric-metrics in `parse_population` / `read_checkpoint_best_score` (`run status` / `run population` / checkpoint best-score fallback); sum only as fallback; no crash on a metrics dict lacking it. Display/fallback-only (§4.5, U13 i). |
| FR-RUN-053 | **Covered** | Wrapper coverage keys `instances_valid`/`instances_total` + timeout side-channel on both backends; reserved `instances_` prefix excluded from every mean (read-path counterpart FR-EVL-021 as amended, DES-006 §4.3); distinct Shinka `TimeoutError` branch (§3.2, U13 ii). |
| FR-RUN-054 | **Covered** | `evaluation.on_timeout: penalize\|drop` (default `penalize`) + finite `evaluation.timeout_score` (default 0.0), parsed + validated at the shared launch point on both backends (bad value → exit 1 at run/dry-run), baked into the wrapper, inherited on resume (§2.1 step 9, §3.2, U13 iii). |
| FR-RUN-055 | **Covered** | `run info` dual-score display: engine best labeled "engine, single eval" next to the coverage-labeled post-eval mean; #306 fallback labeled the same way, never bare; JSON carries both fields (§2.5, §7, §8 `RunInfo`, U11 B). |
| FR-RUN-056 | **Covered** | `validate_seed_metrics()` post-pre-flight fail-fast on launch and resume; builtins `complexity`/`diversity`/`combined_score` allowlisted; Shinka no-op; skipped with pre-flight on empty dataset (§2.1 step 12b, §2.3 step 13b, §4.1, §4.4, U8). |
| FR-RUN-057 | **Covered** | Default checkpoint cadence `max(1, min(100, iterations//10))` when `checkpoint_interval` is unset; explicit values never overridden; S17a-12 warn fires only on explicit equality (§4.2, U6 phase 2). |

---

## 5. Environment Variables

Set before launching OpenEvolve, per ADR-006:

| Variable | Value | Required |
|---|---|---|
| `REVOLVER_DATASET_DIR` | `resolve_dataset_path(dataset_name)` | Yes (FR-RUN-005) |
| `REVOLVER_INSTANCE_LOG` | `.revolver/runs/<id>/instance_log.db` | Optional (FR-RUN-026) |
| `REVOLVER_EVAL_LOG` | `.revolver/runs/<id>/eval_log.db` | Optional (FR-RUN-027) |

These are set in the current process environment before calling `openevolve.run()`. OpenEvolve's worker processes inherit them via standard `os.environ` propagation (validated in POC #12 S2).

**Note (D-005-d)**: `REVOLVER_INSTANCE_LOG` and `REVOLVER_EVAL_LOG` are used only by the generated wrapper evaluator. Legacy evaluators (`evaluate()` mode) do not benefit from these unless the user implements them manually.

**Cleanup**: After the run completes (success or failure), the env vars are unset to avoid polluting subsequent operations in the same process.

```python
@contextmanager
def revolver_env(env_vars: dict[str, str]):
    """Context manager to set and clean up REVOLVER_* env vars."""
    old = {}
    for key, value in env_vars.items():
        old[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key in env_vars:
            if old[key] is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old[key]
```

---

## 6. Concurrency Control

### 6.1 Per-Run Lock Files (FR-RUN-014)

Each active run has its own lock file in `.revolver/runs/locks/`. This replaces the single `.revolver/run.lock` file (DD-11).

**Mechanism**: A lock file `.revolver/runs/locks/<run_id>.lock` is created when a run starts:

```yaml
# .revolver/runs/locks/run-20260310-143000.lock
run_id: "run-20260310-143000"
llm: "codestral-local"
llm_source: "local"
started_at: "2026-03-10T14:30:00Z"
pid: 12345
```

Before starting a local-LLM run, Revolver checks:
1. Scan `.revolver/runs/locks/` for `*.lock` files
2. For each lock file: is the PID still alive? (`os.kill(pid, 0)`)
3. If PID dead → stale lock, remove it
4. If any live lock has `llm_source == "local"` → error: "A local LLM run is already in progress"
5. If no conflict → proceed

### 6.2 Remote LLM — Parallel Execution (FR-RUN-015)

Remote LLM runs have no local resource conflict. A lock file is still created (for status tracking via `run status`) but does not block other runs. The concurrency check only blocks when `llm_source == "local"` and another local-LLM lock is alive.

### 6.3 Lock File Lifecycle

```
launch_run()  → write .revolver/runs/locks/<run_id>.lock
               → launch OpenEvolve
               → on completion/failure: remove .revolver/runs/locks/<run_id>.lock
               → on crash: stale lock detected by PID check on next run/status
```

---

## 7. Post-Run Training Evaluation (FR-RUN-019/020)

After the engine completes, Revolver evaluates the **rank-1 program** (the auto-created solution) on all training instances to produce per-instance results accessible via `revolver eval results` (DD-12).

```python
def _post_run_evaluation(
    proj_conn: Any,
    run_id: str,
    solution_id: str,
    snapshot_dir: Path,
    dataset_name: str,
    dataset_path: Path,
    program_path: Path,
    project_root: Path | None = None,
) -> None:
    """
    Evaluate the rank-1 program on training instances.
    Calls core.eval.evaluate_solution() for the auto-created solution.
    Results are stored in eval_metadata/eval_instances with the training
    dataset, making them accessible via:
      revolver eval results --solution <id> --dataset <train-dataset>
    Warn-only: a failed post-run eval never fails the run.
    """
```

> **S18 / U11 commit A — the docstring becomes true (Task-86 residue, FR-RUN-019/020).** Until
> v0.17 the implementation diverged from this design: an interim `_run_post_eval` shortcut ran
> the instances with a **hardcoded `timeout_s=300`** and **stored nothing** (stderr-only output),
> so the FR-RUN-020 promise ("accessible via `revolver eval results`") was not literally met.
> S18 replaces it with the real `core.eval.evaluate_solution()` path on **both** call sites
> (`launch_run` and `resume_run`):
>
> - Results are **persisted** to `eval_metadata`/`eval_instances` (DES-001 §3.7–3.8) — no longer
>   a stderr-only path; `run info` reads the aggregate back for the dual-score display
>   (FR-RUN-055, §2.5), including the FR-RUN-053 coverage (`instances_valid`/`instances_total`).
> - `config.dataset_name` is **threaded through** (previously only `dataset_path` reached the
>   helper), so the eval rows reference the registered training dataset.
> - The per-instance timeout comes from the **eval path** (the hardcoded 300 s is gone).
> - Failure remains **warn-only** — a failed or missing post-run eval never fails the run.
> - **DB-contention guard**: `launch_run` still holds its open project connection when the eval
>   path opens its own — the orchestrator commits `proj_conn` before the call (plus WAL /
>   `busy_timeout`) so the write cannot contend with the still-open launch connection.
> - `evaluate_solution()` raises when an eval already exists for `(solution, dataset)` — the
>   post-run call passes `force=True` / performs the has-existing-eval check.

This step is **synchronous** — it runs after the engine completes but before the run is marked as finished.

**Eval subprocess teardown (v0.17.1, task 358 / U12+U14).** Each per-instance
evaluation funnels through `infra/evaluator_runner.run_instance()`, which runs
the evaluator in a **spawn-context** `multiprocessing.Process` in its own
session (`os.setsid()`):

- **Kill-on-timeout**: at the per-instance deadline the parent sends SIGTERM
  to the child's process group, waits a 3 s grace, then SIGKILL (single-PID
  `terminate()`/`kill()` fallback when `getpgid`/`killpg` fails). No eval
  worker survives the call — this replaces the previous
  `ProcessPoolExecutor` timeout, which *abandoned* a still-running worker
  (one leaked grinder per timed-out instance).
- **Thread caps**: the child receives the BLAS/OpenMP thread-cap env family
  before importing the evaluator, controlled by `REVOLVER_EVAL_NUM_THREADS`
  (`0` = uncapped; default `max(1, cpu_count // 2)`; nothing injected when
  the user already set any cap variable). This prevents the core
  oversubscription that produced false per-instance timeouts.
- The legacy global `evaluate()` aggregation (DES-006 §"legacy mode") runs
  through the same killable primitive.

The `InstanceTestResult` contract (statuses `pass`/`fail`/`timeout`, the
timeout message, error strings) is unchanged.

### 7.1 Error Handling: `oe_completed` Flag and `completed_with_errors` (F3)

Post-processing (program collection, solution creation, training eval) can fail even after OpenEvolve completes successfully. To distinguish this from an OpenEvolve failure, `launch_run()` uses an `oe_completed` flag:

1. `oe_completed = False` before calling `openevolve.run()`
2. After `openevolve.run()` returns successfully, set `oe_completed = True`
3. If an exception occurs during post-processing:
   - If `oe_completed is True` → call `_handle_post_run_failure()`:
     - Write error details to `run-error.log` in the run directory (best-effort)
     - Set run status to `completed_with_errors` (not `interrupted`)
     - Remove lock file
     - Raise `RunError` with a message pointing to the error log
   - If `oe_completed is False` → set status to `interrupted` (OpenEvolve itself failed)

This ensures the run directory and its checkpoint are preserved for recovery. The user can:
- Inspect the error via `run-error.log`
- Use `solution extract` on the run if programs were already collected (FR-RUN-033)
- Use `run resume` to retry from the checkpoint (FR-RUN-034)
- Recover the best program of an **interrupted/failed** run from its latest checkpoint via
  `solution extract --from-checkpoint` (B7, below)

**On-demand extraction**: When a user later calls `revolver solution extract --run <id> --rank N`, the same evaluation is performed on the newly extracted solution. This ensures every solution has training eval results, whether auto-created or extracted. `extract` accepts runs with status `completed` or `completed_with_errors` (FR-RUN-033).

### 7.2 Best-of-interrupt recovery: `solution extract --from-checkpoint` (B7, FR-RUN-051)

An `interrupted`/`failed` OpenEvolve run never materializes `programs/rank-N.py` (post-processing
did not run), so the default `solution extract` correctly **rejects** it. What survives is the
latest `oe-output/checkpoints/checkpoint_N/`: `best_program_id` in `metadata.json` plus the code in
`programs/{id}.json`. The new `--from-checkpoint` flag recovers the best program from that checkpoint
for `interrupted`/`failed` runs, dispatched through a **backend-neutral** protocol method
`recover_best_from_checkpoint(run_dir) -> (code, score)` on `EvolutionBackend`:

- **`OpenEvolveBackend`** locates the latest `checkpoint_N/`, reads `best_program_id`, loads the
  program code and score. It raises a clear, typed `RevolverError` subclass — distinguishable from
  "backend does not support checkpoint recovery" — when **no checkpoint exists yet** (run too short
  to checkpoint).
- **`ShinkaBackend`** does not need this path (its `programs.sqlite` already survives an interrupted
  run and the DB-driven collection recovers the best directly); the method may no-op / raise
  "not needed".

**Default behavior is unchanged**: without `--from-checkpoint`, `solution extract` still rejects an
interrupted run (the pre-v0.17 contract). Only the explicit flag path recovers from the checkpoint.

### 7.3 Top-N / arbitrary-rank promotion: `solution extract --rank N` / `--program-id` (S18, FR-SOL-021)

`solution extract` regains an arbitrary-rank path (removed in tasks 197/198; the extract-on-demand
model of DD-07 kept the DB shape ready throughout — `core.extract_solution` accepts an arbitrary
rank and the `UNIQUE(run_id, rank)` constraint was never dropped). The CLI resolves the run's
persisted backend and gates on `capabilities().top_n_extraction` (§4.6) — the capability has
existed since ADR-007 with **zero consumers**; S18 adds the consumer (FR-SOL-021 in
spec-solution.md; FR-SOL-011/012 generalized from rank-1-only):

- **ShinkaEvolve (`top_n_extraction = True`)** — a new `ShinkaBackend.extract_ranked_program(
  run_dir, rank | program_id)` reads the full population from `programs.sqlite` (the existing
  best-program `ORDER BY combined_score DESC` query, without `LIMIT 1`) and materializes the
  requested program to `programs/rank-<N>.py` through the same recovery flow `extract_solution`
  already uses (§7.2 pattern). Works **retroactively** on old runs — the population DB is the run
  artifact; no run-dir layout change. `--program-id <id>` promotes an arbitrary population
  program by engine ID.
- **OpenEvolve (`top_n_extraction = False`, consciously deferred)** — exits 1 with a clear
  "not supported on openevolve" error. Deferral rationale: the checkpoint exposes the full
  population only at checkpoint boundaries (a granularity limit — mitigated but not removed by
  the FR-RUN-057 cadence default), and an S18 implementation would have baked the
  pre-FR-RUN-052 sum-of-metrics ordering. Revisit post-U13 (sprint-018 carry-over).
- `--rank 1` behaves exactly as today (the auto-created rank-1 solution is unchanged);
  `(run_id, rank)` uniqueness is enforced; extraction-time training eval applies as for any
  extracted solution (DD-07/DD-12, §7.1 on-demand extraction).

---

## 8. Pydantic Data Models

```python
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from pathlib import Path

class RunConfig(BaseModel):
    """Configuration for an evolution run."""
    problem_version: str
    llm_name: str
    dataset_name: str
    backend: str | None = None         # None sentinel = "not specified" (U4, S18): resolution
                                       # order explicit --backend > version-stored backend
                                       # (FR-PRB-016) > default "openevolve" (FR-RUN-047 as
                                       # amended). A hard "openevolve" default would make
                                       # explicit-vs-default indistinguishable (sprint-018 fact 5)
    iterations: int | None = None
    alias: str | None = None
    config_overrides: list[str] = []
    # Ensemble neutral levers (ADR-007 A1). None/empty on single-LLM runs.
    selection: str | None = None            # fixed | ucb | ucb1 | thompson (capability-checked per backend)
    selection_kwargs: list[str] = []        # raw "k=v" strings, branched per selected sampler (A5)
    llm_weight_overrides: list[str] = []     # raw "model=w" strings, per-run weight override (M3)
    dry_run: bool = False

class TokenUsage(BaseModel):
    """Token usage accumulated during a run."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0              # prompt + completion (computed, NOT persisted in DB)
    # estimated_cost_usd removed in S15 (#300): no realistic cost figure is
    # reachable; tokens cover stored programs only.

class RunManifest(BaseModel):
    """Manifest stored in .revolver/runs/<id>/manifest.yaml."""
    model_config = ConfigDict(frozen=True)

    run_id: str
    created_at: datetime
    generation_time_s: float | None = None
    iterations: int
    status: str = "running"  # running | completed | interrupted | completed_with_errors | failed

    # Lineage
    problem_version: str
    problem_hash: str
    dataset: str
    dataset_hash: str
    llm: str
    llm_model: str
    resumed_from: str | None = None

    # Token usage (FR-RUN-028/029/030)
    token_usage: TokenUsage | None = None  # None while running or if tracking unavailable

    # Solution
    solution: "SolutionResult | None" = None  # Auto-created rank-1 solution (None while running)

    # Files
    programs: list["ProgramEntry"] = []  # All stored programs from OpenEvolve output
    checkpoint: str = "oe-checkpoint/"
    config_file: str = "config.yaml"    # Relative path to config in run dir (NB: SQLite stores verbatim content as config_snapshot)

class ProgramEntry(BaseModel):
    """A stored program from OpenEvolve output."""
    rank: int
    score: float | None = None
    file: str                          # e.g. "programs/rank-1.py"

class RunResult(BaseModel):
    """Returned to CLI after a run completes."""
    run_id: str                        # This run's own ID
    solution: "SolutionResult"         # Auto-created rank-1 solution
    programs_stored: int               # Total programs stored from OpenEvolve output
    problem_version: str
    llm: str
    dataset: str
    iterations: int
    generation_time_s: float
    token_usage: TokenUsage | None = None  # Token counts from proxy (FR-RUN-028)
    resumed_from: str | None = None

class SolutionResult(BaseModel):
    """One solution reference."""
    solution_id: str
    run_id: str                        # Run that produced this solution
    alias: str | None = None
    rank: int                          # 1 = best (auto-created), or extracted rank
    best_score: float | None = None

class RunStatus(BaseModel):
    """Status of active runs or the most recent run."""
    active: bool
    run_ids: list[str] = []            # Active run IDs (may be multiple)
    run_id: str | None = None          # Most recent run (if no active)
    problem_version: str | None = None
    llm: str | None = None
    dataset: str | None = None
    iterations_completed: int | None = None
    iterations_total: int | None = None
    best_score: float | None = None
    started_at: datetime | None = None
    elapsed_s: float | None = None

class RunSummary(BaseModel):
    """Summary for run list output."""
    run_id: str
    problem_version: str
    llm: str
    dataset: str
    iterations: int
    generation_time_s: float | None = None
    token_usage: TokenUsage | None = None  # Token counts for run list display
    status: str
    resumed_from: str | None = None
    created_at: datetime
    best_score: float | None = None

class RunInfo(BaseModel):
    """Detailed run information for run info output."""
    run_id: str
    problem_version: str
    problem_hash: str
    llm: str
    llm_model: str
    dataset: str
    dataset_hash: str
    iterations: int
    generation_time_s: float | None = None
    token_usage: TokenUsage | None = None  # Token counts (no cost — S15 / #300)
    status: str
    resumed_from: str | None = None
    created_at: datetime
    solutions: list["SolutionResult"] = []  # Auto-created + extracted solutions
    programs: list["ProgramEntry"] = []     # All stored programs (for run info display)
    programs_extracted: int = 0             # Files materialized to programs/ (== len(programs)) — UX-4 / S16
    total_programs: int | None = None       # Total in backend store (all rows in Shinka's programs.sqlite; None on OE) — surfaced as programs_in_db
    run_best_score: float | None = None     # Engine's run best; fallback for the rank-1 solution score when its own is missing — UX-4 / S16, #306. Rendered ONLY under the "engine, single eval" label (FR-RUN-055): a max over single, survivorship-prone evals, never shown bare
    # Honest dual-score display (S18 / U11 — FR-RUN-055): populated from the persisted post-run
    # training eval (FR-RUN-019 via core.eval, §7) and rendered next to run_best_score
    post_eval_score: float | None = None            # Post-run training-eval mean (honest, multi-instance)
    post_eval_instances_valid: int | None = None    # FR-RUN-053 coverage label: instances in the mean
    post_eval_instances_total: int | None = None    # FR-RUN-053 coverage label: total training instances
    resume_chain: list[str] = []            # Ordered list of ancestor run IDs

class ProgressInfo(BaseModel):
    """Progress callback data from OpenEvolve."""
    iteration: int
    total_iterations: int
    best_score: float
    elapsed_s: float
```

---

## 9. Storage Layout

Each run has its own directory under `.revolver/runs/`. Solutions do not have their own directories — they are DB references to programs stored in the run directory. A completed run materializes the **best** program as `programs/rank-1.py` (both backends — single best, since S9-B2) and auto-promotes it to a solution. On a top-N-capable backend (ShinkaEvolve), `solution extract --rank N` / `--program-id` materializes additional `rank-<N>.py` files on demand from the backend program store — retroactively on old runs, no layout change (FR-SOL-021, §7.3).

```
.revolver/
├── runs/
│   ├── run-20260310-143000/
│   │   ├── manifest.yaml              # Run metadata + lineage
│   │   ├── config.yaml                # Verbatim OpenEvolve config used (FR-RUN-017)
│   │   ├── _revolver_evaluator.py     # Generated wrapper (or copied evaluator)
│   │   ├── oe-checkpoint/             # OpenEvolve checkpoint for resume
│   │   │   └── ...                    # OpenEvolve internal files
│   │   ├── run-error.log              # Post-processing error details (only if completed_with_errors, FR-RUN-032)
│   │   ├── instance_log.db            # SQLite side-channel (optional, FR-RUN-026)
│   │   ├── eval_log.db                # Evaluator log (optional, FR-RUN-027)
│   │   └── programs/
│   │       ├── rank-1.py
│   │       └── rank-2.py  (materialized on demand by solution extract)
│   ├── run-20260310-160000/
│   │   └── ...
│   └── locks/
│       └── run-20260310-143000.lock
├── problem/
├── datasets/
└── revolver.db
```

### 9.1 SQLite

Uses tables from [DES-001](DES-001-sqlite-data-model.md):
- `runs` (§3.5): run metadata, lineage, resume chain
- `solutions` (§3.6): lightweight references (run_id, rank, alias, best_score)
- `eval_metadata` + `eval_instances` (§3.7–3.8): post-run training evaluation

---

## 10. Core Layer: Function Signatures

```python
# --- Run ---
def launch_run(config: RunConfig) -> RunResult:
    """
    Launch an OpenEvolve evolution run.
    Validates inputs, generates wrapper, launches OE, stores results.
    Creates a run directory, stores all programs, creates 1 solution row (rank-1).
    Post-run evaluation runs on rank-1 solution only.
    If config.dry_run is True, validates everything and returns without launching.
    """

def resume_run(run_id: str) -> RunResult:
    """
    Resume a run from its checkpoint.
    Creates a NEW run with resumed_from pointing to the parent run.
    Copies wrapper and checkpoint from parent, launches OE with checkpoint.
    On completion: creates 1 solution (rank-1), runs post-run eval.
    """

def get_run_status() -> RunStatus:
    """
    Get status of active runs or the most recent run.
    Scans .revolver/runs/locks/ for active locks, falls back to latest run in DB.
    """

def list_runs(
    version: str | None = None,
    llm: str | None = None,
    status: str | None = None,
    sort: str = "created_at",
) -> list[RunSummary]:
    """List runs with optional filters."""

def get_run_info(run_id: str) -> RunInfo:
    """
    Get detailed info for a run, including its solutions and resume chain.
    Uses a recursive CTE to resolve the full resume ancestry.
    """

# --- Internal ---
def generate_wrapper(
    snapshot_dir: Path,
    output_dir: Path,
) -> Path:
    """Generate wrapper evaluator or copy legacy evaluator."""

def _post_run_evaluation(
    proj_conn: Any,
    run_id: str,
    solution_id: str,
    snapshot_dir: Path,
    dataset_name: str,
    dataset_path: Path,
    program_path: Path,
    project_root: Path | None = None,
) -> None:
    """Evaluate rank-1 program on training instances after run.
    S18 / U11: routes through core.eval.evaluate_solution() — persists
    eval_metadata/eval_instances, uses the eval path's timeout, stays
    warn-only, and guards DB contention (commit proj_conn before the
    call). See §7."""

def generate_run_id() -> str:
    """Generate run-YYYYMMDD-HHMMSS from current timestamp."""

def generate_solution_id() -> str:
    """Generate sol-YYYYMMDD-HHMMSS from current timestamp."""
```

---

## 11. CLI Layer: Typer Commands

```python
import typer

app = typer.Typer(name="run", help="Generate solutions via OpenEvolve")

@app.callback(invoke_without_command=True)
def run_default(
    ctx: typer.Context,
    version: str = typer.Option(..., "--version", help="Problem version tag"),
    llm: str = typer.Option(..., "--llm", help="Registered LLM name"),
    dataset: str = typer.Option(..., "--dataset", help="Training dataset name"),
    iterations: int | None = typer.Option(None, "--iterations", help="Override iteration count"),
    alias: str | None = typer.Option(None, "--alias", help="Solution alias"),
    config_override: list[str] | None = typer.Option(None, "--config-override", help="key=value overrides (escape hatch for backend-exclusive structural keys)"),
    temperature: float | None = typer.Option(None, "--temperature", help="Override LLM sampling temperature"),
    parallel: int | None = typer.Option(None, "--parallel", help="Override number of parallel evaluations"),
    selection: str | None = typer.Option(None, "--selection", help="Ensemble selection strategy: fixed | ucb | ucb1 | thompson (capability-checked per backend; OE accepts weighted/fixed only, ADR-007 A2/A4)"),
    selection_kwarg: list[str] | None = typer.Option(None, "--selection-kwarg", help="Repeatable k=v routed to the selected sampler (e.g. cost_aware_coef=0.3 for ucb/ucb1; A5)"),
    llm_weight: list[str] | None = typer.Option(None, "--llm-weight", help="Repeatable model=w per-run weight override (OE + Shinka-fixed; warned/ignored under Shinka adaptive modes; M3)"),
    backend: str | None = typer.Option(None, "--backend", help="Evolution backend: openevolve | shinka. None sentinel — resolves explicit > version-stored backend (FR-PRB-016) > openevolve; a mismatch with the version's stored backend warns on stderr (U4, FR-RUN-047 as amended)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate inputs and show config without launching"),
): ...

@app.command()
def status(): ...

@app.command()
def resume(
    run: str = typer.Option(..., "--run", help="Run ID to resume from"),
    # Ensemble neutral levers are RE-SPECIFIED per resume, not inherited from the parent run —
    # consistent with `--config-override` (neither is persisted or auto-carried; §14.1). When a
    # resume of an *ensemble* parent omits `--selection`, the run falls back to the backend default
    # and `resume_run()` emits a warning so the reset is not silent.
    selection: str | None = typer.Option(None, "--selection", help="Ensemble selection strategy for the resumed run (re-specify; not inherited)"),
    selection_kwarg: list[str] | None = typer.Option(None, "--selection-kwarg", help="Repeatable k=v for the selected sampler"),
    llm_weight: list[str] | None = typer.Option(None, "--llm-weight", help="Repeatable model=w per-run weight override"),
): ...

@app.command()
def list(
    version: str | None = typer.Option(None, "--version", help="Filter by problem version"),
    llm: str | None = typer.Option(None, "--llm", help="Filter by LLM name"),
    status: str | None = typer.Option(None, "--status", help="Filter by status (running, completed, completed_with_errors, interrupted)"),
    sort: str = typer.Option("created_at", "--sort", help="Sort by field (created_at, score, iterations)"),
): ...

@app.command()
def info(
    run_id: str = typer.Argument(..., help="Run ID to inspect"),
): ...
```

---

## 12. Sequence Diagrams

### 12.1 `revolver run --version v1.1 --llm claude --dataset train-small`

```
User      CLI         Core            OpenEvolve    Store    DB       Hashing
 │         │           │                │            │        │         │
 │─ run ──►│           │                │            │        │         │
 │         │─ start() ►│                │            │        │         │
 │         │           │── get version ────────────────────►│         │
 │         │           │── verify snapshot ────────────────────────────►│
 │         │           │── get LLM ────────────────────────►│         │
 │         │           │── get dataset ────────────────────►│         │
 │         │           │── check integrity ──────────────────────────►│
 │         │           │── scan locks/ ─────►│            │        │
 │         │           │                     │            │        │
 │         │           │── gen run ID         │            │        │
 │         │           │── insert run ───────────────────►│         │
 │         │           │── create run dir ───►│            │        │
 │         │           │── generate wrapper   │            │        │
 │         │           │── set env vars       │            │        │
 │         │           │── build OE config    │            │        │
 │         │           │── write run lock ───►│            │        │
 │         │           │                     │            │        │
 │         │           │── run() ────────────►│            │        │
 │         │           │                     │ (evolution) │        │
 │◄progress│◄─progress─│◄── on_progress ────│            │        │
 │         │           │                     │            │        │
 │         │           │◄── results ─────────│            │        │
 │         │           │── save programs ────►│ (rank-1.py)│        │
 │         │           │── copy checkpoint ──►│            │        │
 │         │           │── gen solution ID (rank-1)         │        │
 │         │           │── insert solution ──────────────►│         │
 │         │           │── post-run eval (rank-1)│            │        │
 │         │           │── update run status ─────────────►│         │
 │         │           │── write manifest ───►│            │        │
 │         │           │── remove run lock ──►│            │        │
 │◄─result─│◄─RunResult│                     │            │        │
```

### 12.2 `revolver run resume --run run-20260310-143000`

```
User      CLI         Core            OpenEvolve    Store    DB
 │         │           │                │            │        │
 │─resume─►│           │                │            │        │
 │         │─resume() ►│                │            │        │
 │         │           │── get run ──────────────────────────►│
 │         │           │── locate checkpoint ►│            │
 │         │           │── validate checkpoint│            │
 │         │           │── validate status    │            │
 │         │           │── get version ──────────────────────►│
 │         │           │── get LLM ──────────────────────────►│
 │         │           │── get dataset ──────────────────────►│
 │         │           │── gen NEW run ID      │            │
 │         │           │── insert run (resumed)──────────────►│
 │         │           │── create new run dir ►│            │
 │         │           │── copy wrapper ──────►│ (from parent)
 │         │           │── copy checkpoint ───►│ (from parent)
 │         │           │── reconstruct config  │            │
 │         │           │── write run lock ────►│            │
 │         │           │                      │            │
 │         │           │── run(checkpoint) ───►│            │
 │         │           │                      │ (resume)   │
 │◄progress│◄─progress─│◄── on_progress ─────│            │
 │         │           │◄── results ──────────│            │
 │         │           │── save programs ─────►│ (rank-1.py)│
 │         │           │── gen solution ID (rank-1)          │
 │         │           │── insert solution ─────────────────►│
 │         │           │── post-run eval (rank-1) │            │
 │         │           │── update run status ──────────────►│
 │         │           │── write manifest ────►│            │
 │         │           │── remove run lock ───►│            │
 │◄─result─│◄─RunResult│                      │            │
```

---

## 13. Design Decisions

### DD-01: Wrapper evaluator generation vs requiring dual-mode code

Revolver generates the wrapper evaluator rather than requiring the user to write dual-mode code. This:
- **Reduces boilerplate**: the user writes only `evaluate_instance()`, the simplest possible interface
- **Eliminates mistakes**: the dual-mode pattern, env var reading, side-channel logging are all handled correctly by the generated code
- **Supports legacy mode**: users who already have an `evaluate()` function can use it directly

Trade-off: code generation adds complexity to `revolver run`. Mitigated by the fact that the generated code is deterministic and stored alongside the solution for inspection.

### DD-02: Lock file with PID check for concurrency control

A lock file with PID is simpler than alternatives (SQLite advisory lock, OS-level flock):
- **Self-healing**: stale locks are detected via PID check, no manual cleanup needed
- **Portable**: works on Linux, macOS, WSL2
- **Inspectable**: the lock file is human-readable YAML, easy to debug

Trade-off: PID reuse could theoretically cause a false positive (a different process reuses the PID). In practice, PIDs are not reused quickly enough for this to matter with runs that take minutes to hours.

### DD-03: Post-run evaluation uses the same eval machinery

FR-RUN-019 requires evaluating the best program on all training instances after the run. Rather than implementing a separate evaluation loop, this reuses `core.eval.evaluate_solution()` with the training dataset. This ensures:
- **Consistency**: training and evaluation results use the same format and storage
- **Queryability**: results are accessible via `revolver eval results --solution <id> --dataset <train>`
- **No code duplication**: the evaluation loop is implemented once

> **S18 / U11 note**: this DD was aspirational until v0.18 — the shipped code used an interim
> `_run_post_eval` shortcut (hardcoded 300 s timeout, results not persisted). S18 closes the
> Task-86 residue and makes the reuse real (§7, FR-RUN-019/020).

### DD-04: OpenEvolve controller class, not `run_evolution()`

Per POC #12 S7, the high-level `run_evolution()` function does not support checkpoint resume. The `OpenEvolve` controller class provides:
- `run(iterations, checkpoint_path)` for resume
- Direct access to results without parsing stdout
- Programmatic configuration (no need to write a temporary YAML file)

Trade-off: tighter coupling to OpenEvolve internals. Mitigated by isolating all OpenEvolve interaction in `infra/openevolve.py`.

### DD-05: Generated wrapper stored in run directory

The `_revolver_evaluator.py` is stored in the run directory (not a temporary file) because:
- **Traceability**: the exact evaluator code used for the run is preserved
- **Debugging**: the user can inspect the generated wrapper if results are unexpected
- **Resume**: the wrapper is copied to the new run directory on resume (DD-09)
- The `_` prefix signals it's an internal file, not user-authored

### DD-06: Environment variable cleanup via context manager

Env vars are set before the run and cleaned up after. The context manager pattern ensures cleanup even on exceptions, preventing env var pollution between sequential operations in the same process (e.g., running `revolver run` followed by `revolver eval` in a script).

### DD-07: Extract on demand — rank-1 auto-created, others on demand

`revolver run` materializes the single **best** program as `rank-1.py` in the run's `programs/` directory (S9-B2 revision — the engines reliably output one best program) and automatically promotes it to a solution in the DB. The rest of the population stays in the backend's own store; additional programs are promoted on demand via `revolver solution extract --run <id> --rank N` (or `--program-id`), which materializes the requested `rank-<N>.py` at extraction time on a top-N-capable backend (FR-SOL-021, §7.3).

**Key properties**:
- One auto-created solution per run (rank-1), with post-run training eval
- The full population is inspectable via `run population` (read from the backend store); `rank-<N>.py` files beyond rank-1 are materialized lazily at extraction time
- `solution extract` creates a new solution row `(run_id, rank)` and runs training eval at extraction time
- `UNIQUE(run_id, rank)` constraint prevents duplicate extractions
- No `--top-n` flag on `revolver run` — promotion depth is decided at extraction time, never at run time

**Why extract on demand** (v0.2 → v0.3 evolution):

The previous design (v0.2 DD-07) auto-created N solution rows when `--top-n > 1`. This was problematic:
- **Solution pollution**: top-N programs from the same run are often quasi-identical (optimized on the same `combined_score`), flooding `solution list` with near-duplicates
- **Wasted eval time**: post-run eval on all N solutions is expensive and often pointless for programs the user never inspects
- **User agency**: the user should see scores first (`run info`), then decide which ranks are worth promoting

**Workflow**:
1. `revolver run --version v1.1 --llm claude --dataset train-small` → auto-creates rank-1 solution
2. `revolver run population run-20260310-143000` → shows the ranked population with scores
3. `revolver solution extract --run run-20260310-143000 --rank 2 --alias "alt-approach"` → promotes rank-2

**Post-run behavior**:
- Post-run training evaluation (FR-RUN-019) runs on **rank-1 only** (DD-12 revised).
- `revolver run resume` operates on the **run** (which contains the full checkpoint with the entire population). It does not resume a specific solution.
- The `--alias` option (if provided) is set on the rank-1 solution.

> **S18 capability gate (FR-SOL-021)**: the on-demand promotion path is gated on the run
> backend's `capabilities().top_n_extraction` — Shinka-native (reads `programs.sqlite`
> retroactively, plus `--program-id`), OpenEvolve consciously deferred with a clear
> "not supported" error. See §7.3.

### DD-08: `--dry-run` validates without launching (D-005-g)

`revolver run --dry-run` performs all validation steps (problem version, LLM availability, dataset integrity, concurrency check) and displays the resolved OpenEvolve configuration, then exits without creating a run directory or launching the evolution. This helps catch configuration errors before committing to a potentially long run.

The `--dry-run` flag is checked after step 5 (concurrency check) and before step 7 (run ID generation) in the §2.1 flow. No run ID is generated, no directory is created, no lock file is written.

### DD-09: Wrapper reused on resume (D-005-h)

When resuming a run, the generated wrapper evaluator from the parent run is **copied** into the new run directory rather than being regenerated. This ensures:
- **Determinism**: the exact same evaluator code is used across the resume chain
- **Safety**: the problem version snapshot is immutable, so regenerating the wrapper would produce the same result — but copying avoids any risk of subtle changes in the generation logic between Revolver versions
- **Simplicity**: no need to re-detect evaluate() vs evaluate_instance() on resume

### DD-10: Evaluator detection priority: evaluate() > evaluate_instance() (D-005-a)

When both `evaluate()` and `evaluate_instance()` are defined in the user's evaluator, Revolver uses `evaluate()` (legacy mode). The rationale:
- `evaluate()` is the OpenEvolve-native interface — if the user wrote it, they want full control
- The user may call `evaluate_instance()` internally from their `evaluate()`, using a custom aggregation strategy
- This avoids silently ignoring the user's carefully crafted `evaluate()` in favor of a generated wrapper

Detection order:
1. `evaluate(program_path)` found → use as-is (legacy mode)
2. `evaluate_instance(program_path, instance_path)` found → generate wrapper
3. Neither → raise `EvaluatorError`

### DD-11: Per-run lock files instead of single lock (D-005-b)

Each active run has its own lock file in `.revolver/runs/locks/<run_id>.lock`, replacing the previous single `.revolver/run.lock`. This supports:
- **Multiple concurrent remote-LLM runs**: each tracked by its own lock file
- **Accurate status reporting**: `run status` can list all active runs
- **Clean lifecycle**: lock files are scoped to their run, reducing stale-lock confusion

The concurrency constraint (only one local-LLM run at a time, FR-RUN-014) is enforced by scanning all lock files and checking `llm_source` — not by the existence of a single lock.

### DD-12: Post-run eval on rank-1 only, eval at extraction time (D-005-e revised)

Post-run training evaluation (FR-RUN-019) runs on **rank-1 only** (the auto-created solution). This is a revision from v0.2, where all top-N solutions were evaluated post-run.

**Rationale for the change**:
- Evaluating N solutions post-run is expensive and often wasted — the user may never inspect ranks > 1
- With the extract-on-demand model, `revolver solution extract` triggers training eval at extraction time, so every promoted solution still gets training eval results
- The user inspects scores via `run info` (read from OpenEvolve output, no eval needed), then only extracts the ranks worth evaluating

**Guarantee**: every solution in the DB (whether auto-created or extracted) has training eval results. The eval is just deferred to extraction time for ranks > 1.

### DD-13: Problem description injection into system prompt (D-005-i)

When a problem version snapshot includes `problem.md`, its content is injected into OpenEvolve's `prompt.system_message` via `build_config()`. Design rationale:

- **Configuration-time injection**: The problem description is embedded in the config dict before OpenEvolve starts, not injected at runtime. This is simpler and consistent with how all other config values are handled.
- **Full replacement of system prompt**: When `problem.md` is present, the default OpenEvolve system prompt is replaced entirely with a template that includes the problem description. This avoids concatenation ambiguity and gives a clean, predictable prompt.
- **Optional**: If `problem.md` is absent from the snapshot, the default OpenEvolve system prompt is used unchanged. Existing problems without a `problem.md` are unaffected.
- **Override-compatible**: The user can still override `prompt.system_message` via `--config-override`, which takes precedence in the merge order.
- **Motivation**: POC #13 (OpenEvolve + Claude API) identified that the LLM only receives code and metric names without context. Adding a problem description to the system prompt significantly improves solution quality by giving the LLM domain knowledge.

### DD-14: Token tracking via transparent HTTP proxy (FR-RUN-028)

OpenEvolve does not expose token usage data (POC #13 finding). Revolver solves this by injecting a lightweight local HTTP proxy between OpenEvolve and the LLM API endpoint:

**Why a proxy** (vs alternatives):
- **OpenEvolve callback/hook**: OpenEvolve does not expose per-request hooks — no way to intercept responses
- **Log parsing**: OpenEvolve does not log token usage to any file
- **Provider billing API**: Provider-specific, not real-time, requires additional credentials
- **Proxy**: universal (works with any OpenAI-compatible endpoint), transparent, no OpenEvolve modification needed

**Trade-offs**:
- Adds a local network hop (+< 1ms vs LLM inference of seconds)
- Requires a local port allocation (random available port)
- Streaming responses may not include `usage` in intermediate chunks — the proxy reads the final `usage` from the stream termination message

**Lifecycle**: The proxy is started before `openevolve.run()` and stopped after it returns. It lives within the same process as `revolver run`, managed by `TokenCountingProxy`. On resume, a new proxy is started for the new run (token counts are per-run).

**Note on `config_snapshot`** (OpenEvolve backend only — backends without a proxy, e.g. ShinkaEvolve, store the real endpoint): the `config_snapshot` stored in SQLite (NFR-023) will contain the proxy URL (`http://127.0.0.1:<port>/v1`) instead of the real LLM endpoint. This is acceptable because: (1) the proxy is ephemeral and only exists during the run, (2) the real LLM endpoint is always recoverable from the `llms` registry via `runs.llm`, (3) `run info` displays the LLM name and model from the run metadata, not from the config snapshot.

### DD-15: `api_key_env` in config instead of resolved API key (F1, NFR-050/052)

`build_config()` stores the environment variable **name** (`api_key_env: "ANTHROPIC_API_KEY"`) in the config dict, not the resolved secret value. This ensures:

- **No secrets in `config_snapshot`**: The SQLite column and `manifest.yaml` never contain API keys
- **No secrets in lineage**: NFR-052 is satisfied — benchmark exports and solution lineage are clean
- **Runtime resolution**: A separate `resolve_api_keys()` function creates a deep copy with `llm.api_key_env` replaced by `llm.api_key` just before passing to OpenEvolve. The resolved copy is never persisted.

### DD-16: `completed_with_errors` run status (F3, FR-RUN-031)

A new run status `completed_with_errors` distinguishes post-processing failures from OpenEvolve failures. The previous design used `interrupted` for both cases, which was misleading — an interrupted run implies OE did not finish, while `completed_with_errors` means OE succeeded but post-processing (program collection, solution creation, or training eval) failed.

**Key properties**:
- `completed_with_errors` runs have a valid checkpoint and possibly valid programs in their directory
- `resume` accepts `completed_with_errors` as a valid parent status (FR-RUN-034)
- `solution extract` accepts `completed_with_errors` if the requested program file exists (FR-RUN-033)
- Error details are logged to `run-error.log` in the run directory (FR-RUN-032)
- The `oe_completed` flag pattern (§7.1) ensures correct status assignment in exception handlers

### DD-17: Google Generative Language API seed rejection (F2)

Google's `generativelanguage.googleapis.com` endpoint rejects the `seed` parameter with HTTP 400. `build_config()` detects Google providers via `base_url` and sets both `config["random_seed"]` (top-level) and `config["llm"]["random_seed"]` (nested) to `None`. Both levels are needed because OpenEvolve reads seed from the top-level config key, but the nested key can override it.

---

## 14. Architecture Impact

### New modules

| Module | Layer | Purpose |
|---|---|---|
| `infra/openevolve.py` | Infrastructure | OpenEvolve controller wrapper (launch, monitor, collect results) — migrates into `infra/backends/openevolve.py` in S13 (ADR-007) |
| `infra/token_proxy.py` | Infrastructure | Transparent HTTP proxy for token usage tracking (DD-14) — used by the OpenEvolve backend only |
| `infra/backends/` | Infrastructure | Evolution backend adapters (ADR-007): `base.py` (`EvolutionBackend` protocol, `BackendCapabilities`, `get_backend()`), `openevolve.py`, `shinka.py` |

### 14.1 Backend mediation (ADR-007 — introduced in S13)

From S13 onwards, `core/run.py` no longer imports `infra/openevolve.py` directly; it resolves the
run's backend via `get_backend(name)` and drives launch / resume / live-progress / population
parsing / token collection through the `EvolutionBackend` interface:

| Concern | Backend-mediated behavior |
|---|---|
| **Backend selection** | `--backend {openevolve,shinka}`; S18 (U4) resolution order **explicit `--backend` > version-stored backend (FR-PRB-016, DES-001 v14 / DES-003) > default `openevolve`** via the CLI/`RunConfig` `None` sentinel; an explicit-vs-version mismatch warns on stderr (never errors); `--dry-run` resolves identically; stored in the run record and manifest (`runs.backend`, DB migration — see DES-001); `resume` inherits the parent run's backend (FR-RUN-047 as amended) |
| **Resume semantics** | Backend-defined (FR-RUN-024), parent never mutated: OpenEvolve copies the parent checkpoint and passes `checkpoint_path`; ShinkaEvolve **clones** the parent `results_dir` (its SQLite DB is the resume state) into the new run dir and continues on the clone (clone-resume parity — S16 / TD-3). A `resume_precheck` hook validates the parent before any record is created |
| **Resolved config** | OE-shaped `ResolvedOEConfig` is replaced by the neutral `ResolvedConfig` + `backend_extras` dict (ADR-007 D4); the dry-run renderer iterates neutral fields plus a generic extras loop |
| **Ensemble selection** | Neutral levers `--selection` / `--selection-kwarg` / `--llm-weight` + the registry `reasoning_effort` field, mapped per backend (ADR-007 A1/A2, §4.2). **OE** (`ensemble_model="weighted"`): weighted-random sampler; `--selection` non-weighted → rejected; `--llm-weight` honored; per-member `reasoning_effort` honored. **Shinka** (`ensemble_model="bandit"`): `--selection` → `llm_dynamic_selection` (`fixed`/`ucb`/`ucb1`/`thompson`); weights → `FixedSampler.prior_probs` **fixed-only** (adaptive modes start uniform, weights warned+ignored — FACT B); `--selection-kwarg` branched per sampler (`cost_aware_coef` ucb-only, default 0 — A5); `reasoning_efforts` a single global pool with highest-effort-wins on disagreement + warn (FACT A) |
| **Capabilities** | `capabilities()` carries `selection_strategies` (OE `("fixed",)`, Shinka `("fixed","ucb","ucb1","thompson")`) and `per_member_reasoning_effort` (OE `True`, Shinka `False`) so `--selection`/effort validation is capability-driven, not backend-name-branched (ADR-007 A4, §4.6) |
| **Token strategy** | Backend decision via `wants_http_proxy()` / `collect_token_usage(run_dir)` — token-primary on all backends (ADR-007 D2). OE: proxy (§4.7, DD-14); Shinka: native per-program accounting read from `programs.sqlite`. **No cost is reported (S15 / #300)**: the `cost_usd` figure was dropped — the engines do not persist per-attempt or reasoning/thinking tokens, so no realistic cost is reachable. The inert pricing flags/columns were fully removed in S16 (schema migration v10) |
| **Capabilities** | `capabilities()` drives map-with-warn behavior for unsupported options (FR-RUN-048) and the per-backend reproducibility caveat (NFR-024) |

The post-engine boundary is unchanged: `launch_run` writes Revolver-owned artifacts
(`programs/rank-N.py` + manifest), keeping everything downstream (solution/eval/benchmark)
engine-agnostic (#267 §1.4).

### Existing modules impacted

| Module | Change |
|---|---|
| `core/run.py` | Implement `launch_run()`, `resume_run()`, `get_run_status()`, `list_runs()`, `get_run_info()`, `generate_wrapper()` |
| `cli/run.py` | Implement 5 Typer commands (`run`, `status`, `resume`, `list`, `info`) |
| `models/run.py` | Define `TokenUsage`, `RunConfig`, `RunManifest`, `RunResult`, `SolutionResult`, `RunStatus`, `RunSummary`, `RunInfo`, `ProgressInfo` (new file) |
| `infra/store.py` | Add `create_run_dir()`, `write_run_manifest()`, per-run lock management (`write_run_lock()`, `remove_run_lock()`, `get_active_runs()`) |
| `infra/db.py` | Add `insert_run()`, `insert_solution()` (run_id + rank), `get_run()`, `list_runs()`, `get_solutions_for_run()`, `get_resume_chain()`, `get_latest_run()`, `update_run_status()` |
| `core/solution.py` | Add `extract_solution()` — creates solution row, triggers training eval |
| `cli/solution.py` | Add `extract` Typer command |
| `core/eval.py` | Called by `_post_run_evaluation()` — must be implemented before or alongside DES-005 |

### Cross-DES dependencies

| Dependency | Direction | Details |
|---|---|---|
| DES-001 | DES-005 → DES-001 | Uses `runs` (§3.5) and `solutions` (§3.6) tables |
| DES-003 | DES-005 → DES-003 | Loads problem version snapshot, verifies integrity; reads the version-stored backend for the U4 resolution order (FR-PRB-016) |
| DES-004 | DES-005 → DES-004 | Loads dataset, verifies integrity, resolves path |
| DES-006 | DES-005 → DES-006 | Post-run evaluation reuses `core.eval.evaluate_solution()` |

---

## 15. Open Questions

- ~~**RQ-01**: Should `revolver run` support `--dry-run`?~~ **Resolved** (D-005-g): `--dry-run` accepted. Validates all inputs and displays the resolved OpenEvolve config without launching. See DD-08.
- ~~**RQ-02**: Should the generated wrapper be regenerated on `resume`?~~ **Resolved** (D-005-h): Wrapper reused on resume (copied from parent run). See DD-09.
- **RQ-03**: How should OpenEvolve's progress be monitored? Options: (a) parse stdout, (b) poll checkpoint directory, (c) callback from controller. This depends on the controller class API, which needs further investigation.
