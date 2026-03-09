# Spec: revolver dataset

**Traceable to**: ConOps §4.3 (Dataset), §4.4 (Instance Injection), §5.4 (Workflow: Version & Register), §7.2 (Dataset Registration)
**Status**: Draft

---

## 1. Scope

This spec covers dataset registration, integrity management, and compatibility tracking. Datasets are collections of problem instances used for training (OpenEvolve evolution) or evaluation (benchmarking). They are registered by reference (hash-only) — files are not copied unless `--snapshot` is used.

---

## 2. Commands

### 2.1 `revolver dataset add`

Register a dataset directory.

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--name <id>` | string | Yes | User-defined identifier |
| `--path <dir>` | string | Yes | Path to the dataset directory |
| `--split <type>` | string | Yes | `train` or `eval` |
| `--compatible-with <tag>` | string | Yes | Problem version tag this dataset works with |
| `--snapshot` | flag | No | Copy all instance files into `.revolver/datasets/<name>/snapshot/` |
| `--description <text>` | string | No | Short description |

**Behavior**:
1. Verify the directory exists and contains at least one entry
2. Count top-level entries as instances
3. Compute SHA-256 hash per instance (file content hash, or tree hash for subdirectories)
4. Compute a global hash of the dataset (hash of sorted instance hashes)
5. Store manifest in `.revolver/datasets/<name>/manifest.yaml`
6. If `--snapshot`: copy all files into `.revolver/datasets/<name>/snapshot/`

**Output** (human):
```
Dataset "train-small" registered
  Path: ./data/instances-small/
  Split: train
  Instances: 50
  Global hash: sha256:f1e2d3c4...
  Compatible with: v1.0
  Storage: reference (hash-only)
```

**Output** (JSON):
```json
{
  "name": "train-small",
  "path": "/absolute/path/to/data/instances-small/",
  "split": "train",
  "instance_count": 50,
  "global_hash": "sha256:f1e2d3c4...",
  "compatible_with": ["v1.0"],
  "storage": "reference",
  "registered_at": "2026-03-10T14:30:00Z"
}
```

**Exit codes**: 0 success, 1 if name already registered, 1 if directory empty or missing

### 2.2 `revolver dataset update <name>`

Modify dataset metadata (compatibility, description).

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Dataset name |

**Options**:

| Option | Type | Description |
|---|---|---|
| `--add-compatible-with <tag>` | string | Add a problem version to the compatibility list |
| `--remove-compatible-with <tag>` | string | Remove a problem version from the compatibility list |
| `--description <text>` | string | Update description |

**Output** (human):
```
Dataset "train-small" updated
  Compatible with: v1.0, v1.1
```

**Exit codes**: 0 success, 1 if dataset not found or tag not found

### 2.3 `revolver dataset list`

List all registered datasets.

**Output** (human):
```
Name            Split  Instances  Compatible With  Storage
train-small     train  50         v1.0, v1.1       reference
eval-benchmark  eval   100        v1.0             snapshot
```

**Exit codes**: 0 always

### 2.4 `revolver dataset info <name>`

Show detailed information about a dataset, including integrity status.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Dataset name |

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--verify` | flag | false | Recompute hashes and check integrity |

**Behavior**:
- Without `--verify`: display stored metadata only
- With `--verify`: recompute all instance hashes, compare to stored values, report mismatches

**Output** (human, with `--verify`):
```
Dataset: train-small
  Path: ./data/instances-small/
  Split: train
  Instances: 50
  Compatible with: v1.0, v1.1
  Storage: reference

Integrity check:
  ✓ 49/50 instances match stored hashes
  ✗ instance_023.json — hash mismatch (file modified since registration)
  ⚠ Re-register dataset if changes are intentional
```

**Exit codes**: 0 if integrity OK, 2 if hash mismatches detected

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-DAT-001 | MUST | Register datasets by reference: store path + hashes, not file copies | §4.3, §7.2 |
| FR-DAT-002 | MUST | Compute and store SHA-256 hash per instance and a global hash | §7.2 |
| FR-DAT-003 | MUST | Store the absolute path to the dataset directory | §7.2 |
| FR-DAT-004 | MUST | Count instances automatically (top-level entries in directory) | §4.3 |
| FR-DAT-005 | MUST | Support `--snapshot` to copy files into `.revolver/datasets/<name>/snapshot/` | §4.3 |
| FR-DAT-006 | MUST | Each dataset declares a split: `train` or `eval` | §4.3 |
| FR-DAT-007 | MUST | Each dataset declares compatibility with one or more problem versions | §7.4 |
| FR-DAT-008 | MUST | `update` allows adding/removing compatible problem versions | §5.4 |
| FR-DAT-009 | MUST | `info --verify` recomputes hashes and reports mismatches | §7.2 |
| FR-DAT-010 | MUST | Integrity verification occurs automatically at usage time (run, eval, benchmark) — warn on mismatch, do not block | §7.2, §7.4 |
| FR-DAT-011 | MUST | Refuse to register a name that already exists | — |
| FR-DAT-012 | SHOULD | Support subdirectory instances (tree hash for directories containing multiple files per instance) | §4.3 |
| FR-DAT-013 | SHOULD | Warn (do not block) if a dataset is used with an incompatible problem version | §7.4 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Dataset name already registered | Error: "Dataset '<name>' already exists" | 1 |
| Dataset directory does not exist | Error: "Directory not found: <path>" | 1 |
| Dataset directory is empty | Error: "No instances found in <path>" | 1 |
| `--split` is not `train` or `eval` | Error: "Split must be 'train' or 'eval'" | 1 |
| `--compatible-with` tag does not exist | Error: "Problem version '<tag>' not found" | 1 |
| `info --verify` finds hash mismatches | Warning on stderr + details; exit code 2 | 2 |
| Dataset path no longer accessible | Error: "Dataset path no longer accessible: <path>" | 1 |
| Not in a Revolver project | Error: "Not a Revolver project" | 1 |

---

## 5. Manifest Format

`.revolver/datasets/<name>/manifest.yaml`:

```yaml
name: "train-small"
path: "/absolute/path/to/data/instances-small/"
split: "train"
description: ""
compatible_with: ["v1.0", "v1.1"]
storage: "reference"  # or "snapshot"
instance_count: 50
global_hash: "sha256:f1e2d3c4..."
registered_at: "2026-03-10T14:30:00Z"
instances:
  - name: "instance_001.json"
    hash: "sha256:..."
  - name: "instance_002.json"
    hash: "sha256:..."
  # ...
```

---

## 6. Dependencies

- Requires an initialized project ([spec-project.md](spec-project.md))
- Requires at least one problem version for `--compatible-with` ([spec-problem.md](spec-problem.md))
- Integrity verification is shared with `revolver run` ([spec-run.md](spec-run.md)), `revolver eval` ([spec-eval.md](spec-eval.md)), and `revolver benchmark` ([spec-benchmark.md](spec-benchmark.md))
