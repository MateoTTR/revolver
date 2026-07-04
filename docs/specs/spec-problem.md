# Spec: revolver problem

**Traceable to**: ConOps §4.2 (Problem), §5.3 (Workflow: Test), §5.4 (Workflow: Version), §7.1 (Problem Versioning)
**Status**: Draft

---

## 1. Scope

This spec covers problem testing and versioning. A problem is the user's optimization problem definition: initial program + evaluator + config + optional problem description (`problem.md`). The user works on mutable files in the project root and creates immutable versioned snapshots when ready.

---

## 2. Commands

### 2.1 `revolver problem test`

Validate the evaluator against data before versioning.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--instance <path>` | string | One of these | Path to a single instance file |
| `--dataset <dir>` | string | required | Path to a dataset directory (test all instances) |
| `--program <path>` | string | No | Program to evaluate. Defaults to `./initial_program.py` |
| `--evaluator <path>` | string | No | Evaluator to use. Defaults to `./evaluator.py` |
| `--timeout <seconds>` | int | No | Per-instance timeout. Default: 300s |
| `--verbose` | flag | No | Show full stack trace, stdout/stderr, returned dict |

**Behavior — Single instance** (`--instance`):
1. Set `REVOLVER_INSTANCE_PATH` and `REVOLVER_INSTANCE_ID` environment variables
2. Call the evaluator's `evaluate(program_path)` function
3. Display: returned metrics, execution time, any errors

**Behavior — Dataset** (`--dataset`):
1. Enumerate all top-level entries in the directory as instances
2. For each instance: run single-instance mode, collect results
3. Display: per-instance pass/fail, summary (N passed, M failed, mean/max time)

**Output** (human, single instance):
```
✓ Evaluator loaded successfully
✓ Instance: instance_001.json
✓ Metrics returned: {"makespan": 142.5, "combined_score": 0.35}
✓ Execution time: 0.8s
✓ No errors
```

**Output** (human, dataset):
```
Testing 50 instances from ./data/instances-small/
✓ 48/50 instances passed
✗ instance_023.json — KeyError: 'duration' in evaluator.py:45
✗ instance_041.json — Timeout after 300s
Summary: 48 passed, 2 failed, mean time: 1.1s, max time: 4.2s
```

**Output** (JSON):
```json
{
  "mode": "dataset",
  "dataset_path": "./data/instances-small/",
  "total": 50,
  "passed": 48,
  "failed": 2,
  "results": [
    {"instance": "instance_001.json", "status": "pass", "metrics": {"makespan": 142.5, "combined_score": 0.35}, "time_s": 0.8},
    {"instance": "instance_023.json", "status": "fail", "error": "KeyError: 'duration'", "traceback": "..."}
  ],
  "summary": {"mean_time_s": 1.1, "max_time_s": 4.2}
}
```

**Exit codes**: 0 all passed, 1 if any instance failed

### 2.2 `revolver problem version create`

Create an immutable snapshot of the current problem definition.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `TAG` | Yes | Version tag (e.g., `v1.0`, `v2.1`) — primary positional argument |

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--tag <version>` | string | No | **Deprecated** fallback alias for the positional `TAG`, kept for backward compatibility (UX-2 / S16-17). The positional argument wins when both are supplied. A tag is required via one of the two forms; providing neither is an error (exit 1). |
| `--message <text>` | string | No | Description of what changed. Default: `""` |
| `--backend <name>` | string | No | Evolution backend that validates `config.yaml` before snapshotting (`openevolve` or `shinka`, default `openevolve` — ADR-007) **and is persisted on the version record** as the version-default backend for `revolver run` (FR-PRB-016, FR-RUN-047). Validation degrades gracefully when the backend package is not installed; unknown names fail fast (exit 1) before snapshot creation. |

**Behavior**:
1. Copy `initial_program.py`, `evaluator.py`, `config.yaml`, and `problem.md` (if present) to `.revolver/problem/<tag>/`
2. Compute SHA-256 hash of the snapshot contents
3. Create `manifest.yaml` with hash, timestamp, message, and file list
4. Verify the tag does not already exist

**Output** (human):
```
Problem version "v1.0" created
  Files: initial_program.py, evaluator.py, config.yaml, problem.md
  Hash: sha256:a1b2c3d4...
  Message: Initial formulation
```

**Output** (human, without problem.md):
```
Problem version "v1.0" created
  Files: initial_program.py, evaluator.py, config.yaml
  Hash: sha256:a1b2c3d4...
  Message: Initial formulation
```

**Output** (JSON):
```json
{
  "tag": "v1.0",
  "hash": "sha256:a1b2c3d4...",
  "files": ["initial_program.py", "evaluator.py", "config.yaml", "problem.md"],
  "message": "Initial formulation",
  "backend": "openevolve",
  "created_at": "2026-03-10T14:30:00Z"
}
```

**Exit codes**: 0 success, 1 if tag already exists, 1 if required files missing

### 2.3 `revolver problem version list`

List all problem versions.

**Output** (human):
```
Tag    Hash (short)  Backend     Date                 Message
v1.0   a1b2c3d4      openevolve  2026-03-10 14:30     Initial formulation
v1.1   e5f6g7h8      shinka      2026-03-11 09:15     Refined objective function
```

**Output** (JSON):
```json
{
  "versions": [
    {"tag": "v1.0", "hash": "sha256:a1b2c3d4...", "backend": "openevolve", "created_at": "2026-03-10T14:30:00Z", "message": "Initial formulation"},
    {"tag": "v1.1", "hash": "sha256:e5f6g7h8...", "backend": "shinka", "created_at": "2026-03-11T09:15:00Z", "message": "Refined objective function"}
  ]
}
```

**Exit codes**: 0 always

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-PRB-001 | MUST | `test` runs the evaluator with `REVOLVER_INSTANCE_PATH` set (single-instance mode) | §4.4 |
| FR-PRB-002 | MUST | `test` with `--dataset` iterates over all instances and reports per-instance pass/fail | §5.3 |
| FR-PRB-003 | MUST | `test` catches evaluator exceptions and displays them without crashing Revolver | §5.3 |
| FR-PRB-004 | MUST | `test` enforces a per-instance timeout (default 300s) | §5.3 |
| FR-PRB-005 | MUST | `test` validates the evaluator returns a `dict[str, float]` with a `combined_score` key | §4.5 |
| FR-PRB-006 | MUST | `version create` creates an immutable copy of initial_program.py, evaluator.py, config.yaml in `.revolver/problem/<tag>/` | §7.1 |
| FR-PRB-007 | MUST | `version create` computes and stores a SHA-256 hash of the snapshot | §7.1 |
| FR-PRB-008 | MUST | `version create` refuses to overwrite an existing tag | §7.1 |
| FR-PRB-009 | MUST | `version create` creates a `manifest.yaml` with hash, timestamp, message, file list | §7.1 |
| FR-PRB-010 | MUST | `version create` fails if any of the required files (initial_program.py, evaluator.py, config.yaml) are missing. `problem.md` is **not** required. | — |
| FR-PRB-011 | SHOULD | `test --verbose` shows full stdout/stderr and stack traces | §5.3 |
| FR-PRB-012 | SHOULD | `test` displays a progress bar when testing a dataset with many instances | — |
| FR-PRB-013 | MAY | `test` warns if `combined_score` is not in the returned dict (non-blocking warning) | §4.5 |
| FR-PRB-014 | SHOULD | `version create` includes `problem.md` in the snapshot if it exists in the project root | §4.2 |
| FR-PRB-015 | SHOULD | `problem.md` content is injected into the OpenEvolve system prompt during `revolver run` (see DES-005) | §4.2 |
| FR-PRB-016 | MUST | `version create` **persists the `--backend` value on the version record** (project-DB schema v14, `problem_versions.backend`; legacy rows default `openevolve` — see DES-001/DES-003). The stored backend is the **version-default backend** for `revolver run`: a run omitting `--backend` resolves to it, and an explicit mismatch warns (FR-RUN-047 resolution order — U4/#369) | §7.1 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Neither `--instance` nor `--dataset` provided | Error: "Provide --instance or --dataset" | 1 |
| Instance file does not exist | Error: "Instance not found: <path>" | 1 |
| Dataset directory is empty | Error: "No instances found in <path>" | 1 |
| Evaluator file does not exist | Error: "Evaluator not found: <path>" | 1 |
| Evaluator does not define `evaluate()` function | Error: "Evaluator must define an `evaluate(program_path)` function" | 1 |
| Evaluator returns non-dict or non-float values | Error: "Evaluator must return dict[str, float], got: <type>" | 1 |
| Instance evaluation timeout | Mark instance as failed with "Timeout after Xs" | — |
| `version create` without a tag (neither positional `TAG` nor deprecated `--tag`) | Error: "A version tag is required..." | 1 |
| `version create` with tag that already exists | Error: "Version '<tag>' already exists" | 1 |
| `version create` with missing files | Error: "Missing required file: <filename>" | 1 |
| Not in a Revolver project (no `.revolver/`) | Error: "Not a Revolver project. Run `revolver project init` first." | 1 |

---

## 5. Manifest Format

`.revolver/problem/<tag>/manifest.yaml`:

```yaml
tag: "v1.0"
hash: "sha256:a1b2c3d4e5f6..."
created_at: "2026-03-10T14:30:00Z"
message: "Initial formulation"
files:
  - name: "initial_program.py"
    hash: "sha256:..."
  - name: "evaluator.py"
    hash: "sha256:..."
  - name: "config.yaml"
    hash: "sha256:..."
  - name: "problem.md"       # Only present if problem.md exists in project root
    hash: "sha256:..."
```

---

## 6. Dependencies

- Requires an initialized project ([spec-project.md](spec-project.md))
- `test` uses the instance injection mechanism also used by `revolver eval` ([spec-eval.md](spec-eval.md))
