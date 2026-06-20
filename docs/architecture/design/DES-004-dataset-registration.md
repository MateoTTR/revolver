# DES-004 — `revolver dataset` — Registration & Integrity

**Version**: 0.1 — Initial draft
**Date**: 2026-03-11
**Status**: Draft
**Traceable to**: [spec-dataset.md](../../specs/spec-dataset.md), [Architecture](../architecture.md) §4, [DES-001 Data Model](DES-001-sqlite-data-model.md) §3.2–3.4

---

## 1. Overview

This document details the design of the `revolver dataset` commands: `add`, `update`, `list`, and `info`. These commands handle dataset registration (hashing and recording), integrity verification, and compatibility tracking with problem versions.

### 1.1 Key Concepts

| Concept | Description |
|---|---|
| **Registration** | Recording a dataset's path, instance hashes, and metadata — not copying files |
| **Reference storage** | Default mode: only hashes are stored, files stay in place |
| **Snapshot storage** | Optional: files are copied into `.revolver/datasets/<name>/snapshot/` |
| **Integrity** | At usage time, instance hashes are recomputed and compared to stored values |
| **Compatibility** | A dataset declares which problem versions it works with (mutable) |
| **Instance** | A top-level entry (file or subdirectory) in the dataset directory |

---

## 2. Command → Layer Flow

### 2.1 `revolver dataset add`

Registers a new dataset by computing instance hashes and storing metadata.

```
CLI (cli/dataset.py)
  │ Parse: --name, --path, --split, --compatible-with, --snapshot, --description
  ▼
Core (core/dataset.py) → register_dataset()
  │ 1. Resolve and validate dataset path          ──► Path(path).resolve()
  │ 2. Validate path exists and is a directory
  │ 3. Check name uniqueness                       ──► Infra: db.get_dataset(name)
  │ 4. Validate problem version exists             ──► Infra: db.get_problem_version(tag)
  │ 5. Enumerate instances:
  │    instances = sorted(p for p in Path(path).iterdir() if not p.name.startswith('.'))
  │ 6. Validate at least one instance
  │ 7. Compute per-instance hashes:                ──► Infra: hashing.instance_hash(path)
  │    For each instance:
  │      if file → hashing.file_hash(path)
  │      if dir  → hashing.tree_hash(path)
  │ 8. Compute global hash:                        ──► Infra: hashing.global_hash(instance_hashes)
  │ 9. If --snapshot:
  │    Copy all files to .revolver/datasets/<name>/snapshot/  ──► shutil.copytree()
  │ 10. Write manifest.yaml                        ──► Infra: store.write_dataset_manifest()
  │ 11. Insert into SQLite:
  │     a. datasets row                            ──► Infra: db.insert_dataset()
  │     b. dataset_instances rows (batch)          ──► Infra: db.insert_dataset_instances()
  │     c. dataset_compat row                      ──► Infra: db.insert_dataset_compat()
  │ 12. Return DatasetRegistration
  ▼
Infra
  ├── hashing: file_hash(), tree_hash(), global_hash()
  ├── store: write manifest YAML, create snapshot directory
  └── db: INSERT INTO datasets, dataset_instances, dataset_compat
```

### 2.2 `revolver dataset update <name>`

Updates mutable metadata (compatibility list, description).

```
CLI (cli/dataset.py)
  │ Parse: name, --add-compatible-with, --remove-compatible-with, --description
  ▼
Core (core/dataset.py) → update_dataset()
  │ 1. Load dataset from DB                        ──► Infra: db.get_dataset(name)
  │ 2. Validate dataset exists
  │ 3. If --add-compatible-with:
  │    a. Validate problem version exists           ──► Infra: db.get_problem_version(tag)
  │    b. Insert compat row                        ──► Infra: db.insert_dataset_compat()
  │ 4. If --remove-compatible-with:
  │    a. Delete compat row                        ──► Infra: db.delete_dataset_compat()
  │ 5. If --description:
  │    a. Update description                       ──► Infra: db.update_dataset_description()
  │ 6. Update manifest.yaml                        ──► Infra: store.update_dataset_manifest()
  │ 7. Return updated DatasetRegistration
  ▼
Infra
  ├── db: SELECT, INSERT, DELETE on dataset_compat; UPDATE on datasets
  └── store: rewrite manifest YAML
```

### 2.3 `revolver dataset remove <name>`

Unregisters a dataset. Deletes metadata from SQLite and the manifest. For snapshot datasets, also deletes the copied files.

```
CLI (cli/dataset.py)
  │ Parse: name, --force
  ▼
Core (core/dataset.py) → remove_dataset()
  │ 1. Load dataset from DB                        ──► Infra: db.get_dataset(name)
  │ 2. Validate dataset exists
  │ 3. Check if any solutions reference this dataset ──► Infra: db.get_solutions_by_dataset(name)
  │ 4. If solutions exist and no --force:
  │    Error: "Dataset 'X' is referenced by N solutions. Use --force to remove anyway."
  │ 5. Delete from SQLite (cascading):
  │    a. DELETE FROM dataset_compat                ──► Infra: db.delete_dataset_compat_all(name)
  │    b. DELETE FROM dataset_instances             ──► Infra: db.delete_dataset_instances(name)
  │    c. DELETE FROM datasets                      ──► Infra: db.delete_dataset(name)
  │ 6. Delete manifest and snapshot dir             ──► Infra: store.delete_dataset(name)
  │ 7. Return confirmation
  ▼
Infra
  ├── db: DELETE from datasets, dataset_instances, dataset_compat (in transaction)
  └── store: remove .revolver/datasets/<name>/ directory
```

**Note**: Solutions that referenced this dataset keep their lineage intact — `solution_lineage` stores the dataset hash at the time of the run, not a live reference. The dataset name in `solutions.dataset` becomes a dangling reference, but the hash in `solution_lineage.dataset_hash` preserves traceability.

### 2.4 `revolver dataset list`

Pure database query.

```
CLI (cli/dataset.py)
  │ Parse: --json
  ▼
Core (core/dataset.py) → list_datasets()
  │ 1. Query all datasets                          ──► Infra: db.list_datasets()
  │ 2. For each: query compatible versions         ──► Infra: db.get_dataset_compat(name)
  │ 3. Return list[DatasetSummary]
  ▼
Infra (infra/db.py)
  SELECT d.name, d.split, d.instance_count, d.storage,
         GROUP_CONCAT(dc.problem_version) as compat
  FROM datasets d
  LEFT JOIN dataset_compat dc ON d.name = dc.dataset_name
  GROUP BY d.name
  ORDER BY d.name;
```

### 2.5 `revolver dataset info <name>`

Shows detailed metadata. With `--verify`, performs integrity check.

```
CLI (cli/dataset.py)
  │ Parse: name, --verify, --json
  ▼
Core (core/dataset.py) → get_dataset_info(name, verify=False)
  │ 1. Load dataset from DB                        ──► Infra: db.get_dataset(name)
  │ 2. Load compat list                            ──► Infra: db.get_dataset_compat(name)
  │ 3. If --verify:
  │    a. Load stored instance hashes              ──► Infra: db.get_dataset_instances(name)
  │    b. Resolve dataset path:
  │       if storage=snapshot → .revolver/datasets/<name>/snapshot/
  │       if storage=reference → stored path
  │    c. Re-enumerate and re-hash instances       ──► Infra: hashing.instance_hash()
  │    d. Compare: find mismatches, missing, added
  │    e. Return DatasetInfo with IntegrityReport
  │ 4. Return DatasetInfo
  ▼
Infra
  ├── db: SELECT from datasets, dataset_instances, dataset_compat
  └── hashing: recompute instance hashes
```

---

## 3. Hashing Strategy

### 3.1 Instance Hashing

An instance is a top-level entry in the dataset directory. Two cases:

**File instance** (most common):
```python
def file_hash(path: Path) -> str:
    """SHA-256 of file contents. Returns 'sha256:...' prefixed hex digest."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"
```

**Directory instance** (multi-file instances, e.g., instance with input + metadata):
```python
def tree_hash(path: Path) -> str:
    """
    SHA-256 of a directory tree.

    Algorithm:
        1. Recursively list all files (sorted, relative paths)
        2. For each file: compute file_hash
        3. Concatenate: "relative/path:hash\n" (sorted)
        4. SHA-256 of the concatenation
    """
```

The tree hash algorithm mirrors the snapshot hash from [DES-003 §2.2.1](DES-003-problem-versioning.md) — same principle, applied to directories instead of problem files.

### 3.2 Global Hash

```python
def global_hash(instance_hashes: list[tuple[str, str]]) -> str:
    """
    SHA-256 of sorted instance hashes.

    Args:
        instance_hashes: list of (instance_id, hash) tuples

    Algorithm:
        1. Sort by instance_id
        2. Concatenate: "instance_id:hash\n"
        3. SHA-256 of the concatenation
    """
```

The global hash changes if any instance is modified, added, or removed. It enables quick dataset-level integrity checks without rehashing every instance.

### 3.3 Hash Reuse Across Commands

| Operation | What gets hashed | Module |
|---|---|---|
| `dataset add` | All instances + global | `infra/hashing.py` |
| `dataset info --verify` | All instances + global (recomputed, compared) | `infra/hashing.py` |
| `run` / `eval` / `benchmark` (pre-check) | Global only (quick integrity check) | `infra/hashing.py` |
| `problem version` | Problem files + snapshot | `infra/hashing.py` |

The `infra/hashing.py` module is shared across all these operations (single implementation).

---

## 4. Integrity Verification

### 4.1 When Does Verification Happen?

| Context | Level | Behavior on mismatch |
|---|---|---|
| `dataset info --verify` | Full (per-instance) | Report mismatches, exit code 2 |
| `revolver run` (before launching) | Quick (global hash only) | **Warn** on stderr, do not block (FR-DAT-010) |
| `revolver eval` (before evaluating) | Quick (global hash only) | **Warn** on stderr, do not block |
| `revolver benchmark` (before comparing) | Quick (global hash only) | **Warn** on stderr, do not block |

### 4.2 Quick vs Full Verification

**Quick** (global hash):
1. Recompute all instance hashes
2. Recompute global hash
3. Compare to stored global hash
4. Single boolean result: match or mismatch

**Full** (per-instance):
1. Recompute all instance hashes
2. Compare each to stored hash
3. Report: matched, mismatched (content changed), missing (deleted), added (new files)

Quick verification still requires hashing all files (O(total data size)) — there is no shortcut. The difference is in the output granularity, not performance.

### 4.3 Integrity Report Model

```python
class IntegrityReport(BaseModel):
    """Result of dataset integrity verification."""
    is_valid: bool
    total: int
    matched: int
    mismatched: list[str] = []    # instance_ids with changed content
    missing: list[str] = []       # instance_ids no longer on disk
    added: list[str] = []         # new files not in original registration
```

---

## 5. Pydantic Data Models

```python
from pydantic import BaseModel, ConfigDict
from datetime import datetime

class DatasetInstance(BaseModel):
    """Hash record for a single instance."""
    model_config = ConfigDict(frozen=True)

    instance_id: str           # filename or dirname
    hash: str                  # "sha256:..."

class DatasetRegistration(BaseModel):
    """Full dataset registration record."""
    model_config = ConfigDict(frozen=True)

    name: str
    path: str                  # absolute path
    split: str                 # "train" | "eval" | "both"
    storage: str = "reference" # "reference" | "snapshot"
    description: str = ""
    global_hash: str
    instance_count: int
    compatible_with: list[str] = []  # problem version tags
    registered_at: datetime
    instances: list[DatasetInstance] = []  # populated on detail view

class DatasetSummary(BaseModel):
    """Brief dataset info for list view."""
    name: str
    split: str
    instance_count: int
    storage: str
    compatible_with: list[str]

class DatasetInfo(BaseModel):
    """Detailed dataset info with optional integrity report."""
    registration: DatasetRegistration
    integrity: IntegrityReport | None = None
```

---

## 6. Storage Layout

### 6.1 Reference Mode (default)

```
.revolver/
└── datasets/
    └── train-small/
        └── manifest.yaml       # metadata + per-instance hashes
```

Actual data files remain at their original location (e.g., `./data/instances-small/`).

### 6.2 Snapshot Mode (`--snapshot`)

```
.revolver/
└── datasets/
    └── eval-benchmark/
        ├── manifest.yaml
        └── snapshot/            # full copy of all instance files
            ├── instance_001.json
            ├── instance_002.json
            └── ...
```

When `storage=snapshot`, integrity verification and evaluation use the snapshot path instead of the original path.

---

## 7. Core Layer: Function Signatures

```python
# --- Registration ---
def register_dataset(
    name: str,
    path: Path,
    split: str,
    compatible_with: str,
    snapshot: bool = False,
    description: str = "",
) -> DatasetRegistration:
    """Register a new dataset. Computes all hashes."""

# --- Remove ---
def remove_dataset(
    name: str,
    force: bool = False,
) -> None:
    """Unregister a dataset. Refuses if solutions reference it (unless force=True)."""

# --- Update ---
def update_dataset(
    name: str,
    add_compatible_with: str | None = None,
    remove_compatible_with: str | None = None,
    description: str | None = None,
) -> DatasetRegistration:
    """Update mutable dataset metadata."""

# --- Query ---
def list_datasets() -> list[DatasetSummary]:
    """List all registered datasets."""

def get_dataset_info(
    name: str,
    verify: bool = False,
) -> DatasetInfo:
    """Get detailed dataset info with optional integrity verification."""

# --- Integrity (used by run/eval/benchmark) ---
def verify_dataset_integrity(name: str) -> IntegrityReport:
    """Quick integrity check. Returns report, does not raise."""

def resolve_dataset_path(name: str) -> Path:
    """Resolve the effective path (original or snapshot) for a dataset."""
```

---

## 8. CLI Layer: Typer Commands

```python
import typer
from pathlib import Path

app = typer.Typer(name="dataset", help="Manage datasets for training and evaluation")

@app.command()
def add(
    name: str = typer.Option(..., "--name", help="Dataset identifier"),
    path: Path = typer.Option(..., "--path", help="Dataset directory"),
    split: str = typer.Option(..., "--split", help="Dataset split: 'train', 'eval', or 'both' (usable for both)"),
    compatible_with: str = typer.Option(..., "--compatible-with", help="Problem version tag"),
    snapshot: bool = typer.Option(False, "--snapshot", help="Copy files into .revolver/"),
    description: str = typer.Option("", "--description", help="Short description"),
): ...

@app.command()
def update(
    name: str = typer.Argument(..., help="Dataset name"),
    add_compatible_with: str | None = typer.Option(None, "--add-compatible-with"),
    remove_compatible_with: str | None = typer.Option(None, "--remove-compatible-with"),
    description: str | None = typer.Option(None, "--description"),
): ...

@app.command()
def remove(
    name: str = typer.Argument(..., help="Dataset to unregister"),
    force: bool = typer.Option(False, "--force", help="Remove even if referenced by solutions"),
): ...

@app.command(name="list")
def list_cmd(): ...

@app.command()
def info(
    name: str = typer.Argument(..., help="Dataset name"),
    verify: bool = typer.Option(False, "--verify", help="Recompute and verify hashes"),
): ...
```

---

## 9. Sequence Diagrams

### 9.1 `revolver dataset add --name train-small --path ./data/small/ --split train --compatible-with v1.0`

```
User           CLI              Core                Hashing        Store          DB
 │              │                │                    │              │             │
 │─ dataset add►│                │                    │              │             │
 │              │─ register() ──►│                    │              │             │
 │              │                │── check name ────────────────────────────────►│
 │              │                │◄── not found ───────────────────────────────│
 │              │                │── check version ────────────────────────────►│
 │              │                │◄── exists ──────────────────────────────────│
 │              │                │                    │              │             │
 │              │                │── enumerate instances              │             │
 │              │                │── for each instance: │              │             │
 │              │                │   hash() ──────────►│              │             │
 │◄─ progress ──│◄── progress ──│◄── hash ────────────│              │             │
 │              │                │                    │              │             │
 │              │                │── global_hash() ───►│              │             │
 │              │                │◄── hash ────────────│              │             │
 │              │                │── write_manifest() ───────────────►│             │
 │              │                │── insert_dataset() ──────────────────────────►│
 │              │                │── insert_instances() (batch) ───────────────►│
 │              │                │── insert_compat() ──────────────────────────►│
 │◄─ success ──│◄── Registration│                    │              │             │
```

### 9.2 `revolver dataset info train-small --verify`

```
User           CLI              Core                Hashing        DB
 │              │                │                    │             │
 │─ info ──────►│                │                    │             │
 │              │─ get_info() ──►│                    │             │
 │              │                │── get_dataset() ──────────────►│
 │              │                │◄── registration ─────────────│
 │              │                │── get_instances() ────────────►│
 │              │                │◄── stored hashes ────────────│
 │              │                │                    │             │
 │              │                │── for each instance: │             │
 │              │                │   hash() ──────────►│             │
 │              │                │◄── current hash ───│             │
 │              │                │                    │             │
 │              │                │── compare hashes    │             │
 │              │                │── build IntegrityReport          │
 │◄─ report ───│◄── DatasetInfo│                    │             │
```

---

## 10. Design Decisions

### DD-01: Reference by default, snapshot optional

Datasets can be large (GBs of instance files). Copying them by default would waste disk space and slow registration. Reference mode stores only hashes (~100 bytes per instance).

Snapshot mode is useful when:
- The dataset is on removable/network storage
- The user wants a portable project (`.revolver/` contains everything)
- Immutability guarantee is critical (reference files could be modified externally)

### DD-02: Hidden files excluded from enumeration

Files starting with `.` (e.g., `.DS_Store`, `.gitkeep`) are excluded from instance enumeration. This prevents platform-specific artifacts from affecting hashes and instance counts.

### DD-03: Warn, don't block on integrity mismatch at usage time

Per FR-DAT-010, `run`/`eval`/`benchmark` warn on integrity mismatch but do not block. Rationale:
- The user may have intentionally modified instances (e.g., fixing a bug in one instance)
- Blocking would require re-registration, disrupting workflow
- The warning is logged and visible — the user can re-register if needed
- Traceability is preserved: the stored hash records what was *originally* registered

### DD-04: Compatibility is advisory, not enforced

The compatibility list (dataset ↔ problem version) is advisory. Using a dataset with an incompatible version produces a **warning**, not an error (FR-DAT-013). This avoids blocking legitimate use cases (e.g., testing a new problem version with an existing dataset before formally declaring compatibility).

### DD-05: Batch insertion for instance hashes

Instance hashes are inserted in a single transaction (`executemany`) for performance. A dataset with 10,000 instances produces 10,000 rows in `dataset_instances` — individual INSERTs would be slow.

```python
db.executemany(
    "INSERT INTO dataset_instances (dataset_name, instance_id, hash) VALUES (?, ?, ?)",
    [(name, inst_id, inst_hash) for inst_id, inst_hash in instance_hashes]
)
```

---

## 11. Architecture Impact

### Existing modules impacted

| Module | Change |
|---|---|
| `core/dataset.py` | Implement `register_dataset()`, `update_dataset()`, `remove_dataset()`, `list_datasets()`, `get_dataset_info()`, `verify_dataset_integrity()`, `resolve_dataset_path()` |
| `cli/dataset.py` | Implement 5 Typer commands (`add`, `update`, `remove`, `list`, `info`) |
| `models/dataset.py` | Define `DatasetRegistration`, `DatasetInstance`, `DatasetSummary`, `DatasetInfo`, `IntegrityReport` |
| `infra/hashing.py` | Add `file_hash()`, `tree_hash()`, `global_hash()` (shared with problem versioning) |
| `infra/store.py` | Add `write_dataset_manifest()`, `update_dataset_manifest()`, snapshot directory management |
| `infra/db.py` | Add CRUD for `datasets`, `dataset_instances`, `dataset_compat` tables |

### No new modules

All dataset functionality fits within existing module boundaries. The hashing functions are shared with problem versioning ([DES-003](DES-003-problem-versioning.md)).
