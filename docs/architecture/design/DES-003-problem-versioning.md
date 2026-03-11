# DES-003 — `revolver problem` — Testing & Versioning

**Version**: 0.1 — Initial draft
**Date**: 2026-03-11
**Status**: Draft
**Traceable to**: [spec-problem.md](../../specs/spec-problem.md), [Architecture](../architecture.md) §4, [DES-001 Data Model](DES-001-sqlite-data-model.md) §3.1

---

## 1. Overview

This document details the design of the `revolver problem` commands: `test`, `version`, and `versions`. These commands handle problem validation (evaluator testing against instances) and immutable snapshotting (creating versioned copies of the problem definition).

### 1.1 Problem Structure

A Revolver problem is composed of three files in the project root:

| File | Purpose | Required |
|---|---|---|
| `initial_program.py` | Starting code with `EVOLVE-BLOCK` markers | Yes |
| `evaluator.py` | Evaluator defining `evaluate(program_path) -> dict[str, float]` | Yes |
| `config.yaml` | OpenEvolve configuration (iterations, LLM params, etc.) | Yes |

These files are **mutable** — the user edits them freely. `revolver problem version` creates an **immutable snapshot** at a point in time.

---

## 2. Command → Layer Flow

### 2.1 `revolver problem test`

Tests the evaluator against one or more instances to validate correctness before versioning.

```
CLI (cli/problem.py)
  │ Parse: --instance | --dataset, --program, --evaluator, --timeout, --verbose
  │ Validate: at least one of --instance or --dataset provided
  ▼
Core (core/problem.py) → test_problem()
  │ 1. Resolve file paths:
  │    program = --program or ./initial_program.py
  │    evaluator = --evaluator or ./evaluator.py
  │ 2. Validate files exist                       ──► check Path.exists()
  │ 3. Load evaluator module dynamically           ──► Infra: evaluator_loader.load(path)
  │ 4. Validate evaluate() function exists
  │ 5. If --instance:
  │    a. Run single instance                      ──► _test_instance(evaluator, program, instance, timeout)
  │    b. Return TestResult (single)
  │ 6. If --dataset:
  │    a. Enumerate instances in directory          ──► sorted(Path(dataset).iterdir())
  │    b. Validate non-empty
  │    c. For each instance:
  │       _test_instance(evaluator, program, instance, timeout)
  │    d. Compute summary: passed, failed, mean_time, max_time
  │    e. Return TestResult (dataset)
  ▼
Infra (infra/evaluator_loader.py)  [new module]
  │ importlib.util.spec_from_file_location()
  │ importlib.util.module_from_spec()
  │ spec.loader.exec_module()
  └── Returns module with evaluate() callable
```

#### 2.1.1 `_test_instance()` — Single Instance Evaluation

This is the core evaluation primitive, reused by `problem test`, `eval`, and indirectly by `run` (via OpenEvolve).

```python
def _test_instance(
    evaluator_module: ModuleType,
    program_path: Path,
    instance_path: Path,
    timeout_s: int = 300,
) -> InstanceTestResult:
    """
    1. Set environment variables:
       REVOLVER_INSTANCE_PATH = str(instance_path.resolve())
       REVOLVER_INSTANCE_ID   = instance_path.name
    2. Call evaluator_module.evaluate(str(program_path)) with timeout
    3. Validate return type: dict[str, float]
    4. Validate 'combined_score' key exists (warn if missing, FR-PRB-013)
    5. Return InstanceTestResult(status, metrics, time_s, error)
    """
```

**Timeout implementation**: use `concurrent.futures.ProcessPoolExecutor` with a single worker. The evaluator runs in a subprocess to:
- Enforce timeout via `future.result(timeout=timeout_s)`
- Isolate evaluator crashes from the main Revolver process
- Ensure environment variables are set in the child process only

**Why subprocess, not thread?** The evaluator is user-provided arbitrary Python code. A thread cannot be forcefully killed on timeout (only daemon threads die at process exit). A subprocess can be terminated cleanly.

### 2.2 `revolver problem version`

Creates an immutable snapshot of the current problem definition.

```
CLI (cli/problem.py)
  │ Parse: --tag, --message
  ▼
Core (core/problem.py) → create_version()
  │ 1. Resolve project root                       ──► Infra: store.find_project_root()
  │ 2. Check required files exist:
  │    initial_program.py, evaluator.py, config.yaml
  │ 3. Check tag uniqueness                        ──► Infra: db.get_problem_version(tag)
  │ 4. Create snapshot directory:
  │    .revolver/problem/<tag>/
  │ 5. Copy files to snapshot directory             ──► shutil.copy2()
  │ 6. Set snapshot files read-only (0o444)        ──► chmod() on each file
  │ 7. Compute per-file SHA-256 hashes             ──► Infra: hashing.file_hash()
  │ 8. Compute snapshot hash:
  │    SHA-256 of sorted(file_name + ":" + file_hash)
  │ 9. Write manifest.yaml (also read-only)        ──► Infra: store.write_manifest()
  │ 10. Insert into SQLite                         ──► Infra: db.insert_problem_version()
  │ 11. Return ProblemVersion
  ▼
Infra
  ├── store: create dir, write manifest YAML
  ├── hashing: SHA-256 per file + snapshot hash
  └── db: INSERT INTO problem_versions
```

#### 2.2.1 Snapshot Hash Algorithm

The snapshot hash uniquely identifies the content of a problem version, independent of file timestamps or metadata.

```python
def compute_snapshot_hash(files: list[tuple[str, str]]) -> str:
    """
    Args:
        files: list of (filename, file_hash) tuples
    Returns:
        SHA-256 hex digest

    Algorithm:
        1. Sort files by filename (lexicographic)
        2. Concatenate: "filename1:hash1\nfilename2:hash2\n..."
        3. SHA-256 of the concatenated string (UTF-8 encoded)
    """
```

This ensures:
- Same files with same content → same hash, regardless of copy timestamp
- Adding/removing/renaming a file → different hash
- Deterministic (sorted order eliminates filesystem ordering differences)

### 2.3 `revolver problem versions`

Lists all problem versions. Pure database query.

```
CLI (cli/problem.py)
  │ Parse: --json
  ▼
Core (core/problem.py) → list_versions()
  │ 1. Query all versions                         ──► Infra: db.list_problem_versions()
  │ 2. Return list[ProblemVersion]
  ▼
Infra (infra/db.py)
  SELECT tag, hash, message, created_at
  FROM problem_versions
  ORDER BY created_at ASC;
```

---

## 3. Pydantic Data Models

```python
from pydantic import BaseModel, ConfigDict
from datetime import datetime

class FileSnapshot(BaseModel):
    """A single file within a problem version snapshot."""
    model_config = ConfigDict(frozen=True)

    name: str                  # "evaluator.py"
    hash: str                  # "sha256:a1b2c3d4..."

class ProblemVersion(BaseModel):
    """Immutable problem version metadata."""
    model_config = ConfigDict(frozen=True)

    tag: str                   # "v1.0"
    hash: str                  # snapshot hash
    message: str = ""
    created_at: datetime
    files: list[FileSnapshot] = []  # populated when reading manifest

class InstanceTestResult(BaseModel):
    """Result of evaluating a single instance."""
    instance_id: str
    status: str                # "pass" | "fail" | "timeout"
    metrics: dict[str, float] | None = None
    time_s: float
    error: str | None = None
    traceback: str | None = None

class TestResult(BaseModel):
    """Aggregate result of problem test."""
    mode: str                  # "single" | "dataset"
    results: list[InstanceTestResult]
    total: int
    passed: int
    failed: int
    mean_time_s: float
    max_time_s: float
```

---

## 4. Storage Layout

### 4.1 Filesystem

```
.revolver/
└── problem/
    ├── v1.0/
    │   ├── manifest.yaml
    │   ├── initial_program.py     # immutable copy
    │   ├── evaluator.py           # immutable copy
    │   └── config.yaml            # immutable copy
    └── v1.1/
        ├── manifest.yaml
        ├── initial_program.py
        ├── evaluator.py
        └── config.yaml
```

### 4.2 Manifest Format

`.revolver/problem/<tag>/manifest.yaml`:

```yaml
tag: "v1.0"
hash: "sha256:a1b2c3d4e5f6..."
created_at: "2026-03-10T14:30:00Z"
message: "Initial formulation"
files:
  - name: "config.yaml"
    hash: "sha256:..."
  - name: "evaluator.py"
    hash: "sha256:..."
  - name: "initial_program.py"
    hash: "sha256:..."
```

Files are listed in sorted order (matching the hash algorithm).

### 4.3 SQLite

Uses the `problem_versions` table from [DES-001 §3.1](DES-001-sqlite-data-model.md):

```sql
INSERT INTO problem_versions (tag, hash, message, created_at)
VALUES (:tag, :hash, :message, :created_at);
```

The manifest YAML and the SQLite row store complementary data:
- **SQLite**: queryable metadata (tag, hash, created_at, message) for `versions` listing
- **YAML manifest**: file-level detail (per-file hashes) for integrity verification

---

## 5. Core Layer: Function Signatures

```python
# --- Testing ---
def test_problem(
    instance: Path | None = None,
    dataset: Path | None = None,
    program: Path | None = None,
    evaluator: Path | None = None,
    timeout: int = 300,
) -> TestResult:
    """Test evaluator against instance(s). At least one of instance/dataset required."""

# --- Versioning ---
def create_version(
    tag: str,
    message: str = "",
) -> ProblemVersion:
    """Create immutable snapshot of current problem definition."""

def list_versions() -> list[ProblemVersion]:
    """List all problem versions, ordered by creation date."""

def get_version(tag: str) -> ProblemVersion:
    """Get a specific version by tag. Raises if not found."""
```

---

## 6. CLI Layer: Typer Commands

```python
import typer
from pathlib import Path

app = typer.Typer(name="problem", help="Test and version problem definitions")

@app.command()
def test(
    instance: Path | None = typer.Option(None, "--instance", help="Single instance file"),
    dataset: Path | None = typer.Option(None, "--dataset", help="Dataset directory"),
    program: Path | None = typer.Option(None, "--program", help="Program to evaluate"),
    evaluator: Path | None = typer.Option(None, "--evaluator", help="Evaluator module"),
    timeout: int = typer.Option(300, "--timeout", help="Per-instance timeout (seconds)"),
    verbose: bool = typer.Option(False, "--verbose", help="Show full traces"),
): ...

@app.command()
def version(
    tag: str = typer.Option(..., "--tag", help="Version tag (e.g., v1.0)"),
    message: str = typer.Option("", "--message", "-m", help="Version description"),
): ...

@app.command()
def versions(): ...
```

---

## 7. Infra Layer: New Module `evaluator_loader.py`

The evaluator is user-provided Python code. Loading it dynamically requires care:

```python
import importlib.util
from pathlib import Path
from types import ModuleType

def load_evaluator(path: Path) -> ModuleType:
    """
    Dynamically import a Python file as a module.

    Args:
        path: Path to the evaluator Python file

    Returns:
        The loaded module

    Raises:
        FileNotFoundError: if path doesn't exist
        EvaluatorLoadError: if module fails to import
        EvaluatorLoadError: if module has no evaluate() callable
    """
    spec = importlib.util.spec_from_file_location("evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "evaluate") or not callable(module.evaluate):
        raise EvaluatorLoadError(
            f"Evaluator must define an 'evaluate(program_path)' function"
        )

    return module
```

**Security note**: The evaluator runs arbitrary user code. This is by design — the user writes and owns the evaluator. Revolver does not sandbox it beyond subprocess isolation for timeout enforcement.

---

## 8. Sequence Diagrams

### 8.1 `revolver problem test --dataset ./data/instances-small/`

```
User           CLI              Core                    EvalLoader     Subprocess
 │              │                │                        │              │
 │─ test ──────►│                │                        │              │
 │              │─ test_problem()►│                       │              │
 │              │                │── load_evaluator() ───►│              │
 │              │                │◄── module ─────────────│              │
 │              │                │                        │              │
 │              │                │── enumerate instances   │              │
 │              │                │                        │              │
 │              │                │── for each instance:    │              │
 │              │                │   ├── spawn subprocess ──────────────►│
 │              │                │   │   set env vars                    │
 │              │                │   │   call evaluate()                 │
 │              │                │   │◄── metrics ─────────────────────│
 │◄─ progress ──│◄── progress ──│   │                     │              │
 │              │                │                        │              │
 │              │                │── compute summary       │              │
 │◄─ results ──│◄── TestResult ─│                        │              │
```

### 8.2 `revolver problem version --tag v1.0 -m "Initial formulation"`

```
User           CLI              Core             Store       Hashing        DB
 │              │                │                 │            │             │
 │─ version ───►│                │                 │            │             │
 │              │─ create_version()►               │            │             │
 │              │                │── find_root() ─►│            │             │
 │              │                │── check files    │            │             │
 │              │                │── check tag ────────────────────────────►│
 │              │                │◄── not found ──────────────────────────│
 │              │                │── mkdir + copy ─►│            │             │
 │              │                │── file_hash() ──────────────►│             │
 │              │                │◄── per-file hashes ─────────│             │
 │              │                │── snapshot_hash()────────────►│             │
 │              │                │◄── hash ────────────────────│             │
 │              │                │── write_manifest()►│         │             │
 │              │                │── insert() ───────────────────────────►│
 │              │                │◄── ok ────────────────────────────────│
 │◄─ success ──│◄── ProblemVersion│               │            │             │
```

---

## 9. Design Decisions

### DD-01: Subprocess for evaluator execution

The evaluator runs in a subprocess (`ProcessPoolExecutor` with 1 worker) rather than in-process. This provides:
- **Hard timeout**: `future.result(timeout=N)` followed by process termination
- **Crash isolation**: if the evaluator segfaults or corrupts memory, the main process survives
- **Clean environment**: env vars set in the child don't pollute the parent

Trade-off: subprocess spawn overhead (~50-100ms per instance). Acceptable for evaluation workloads where each instance typically takes seconds.

### DD-02: Dual storage (manifest + SQLite) for versions

The manifest YAML is the source of truth for file-level details. SQLite stores only the queryable metadata. This keeps:
- **Manifest**: human-inspectable, self-contained (one can understand a version without DB access)
- **SQLite**: fast queries for `versions` listing (no need to parse N manifest files)

### DD-03: Deterministic snapshot hash

Using sorted filenames + file hashes ensures the snapshot hash is deterministic and content-addressable. Two identical problem definitions produce the same hash, enabling integrity verification and deduplication detection.

### DD-04: Read-only snapshot files

After copying files to `.revolver/problem/<tag>/`, Revolver sets them to `0o444` (read-only for all). This prevents accidental modification of immutable snapshots. The manifest is also set read-only.

This is a lightweight filesystem-level guard. It does not protect against deliberate tampering (the user can `chmod` and edit), but it catches accidental writes (e.g., an editor opening the wrong file, a script writing to the wrong path).

### DD-05: Integrity verification at usage time

When `revolver run` loads a problem version, it recomputes the snapshot hash from the files in `.revolver/problem/<tag>/` and compares it to the hash stored in SQLite. If they differ (files modified, deleted, or corrupted):
- **Exit code 2** (integrity error) — this is a hard stop, unlike datasets which only warn
- The error message lists which files are affected

Problem integrity is stricter than dataset integrity because the snapshot files are under Revolver's control (copied into `.revolver/`), so any mismatch indicates corruption or tampering, not a legitimate workflow.

### DD-06: Versioning strategy — internal manifest-based (AQ-04)

Problem versioning is **internal to Revolver**, not git-integrated. Rationale:
- **Independence from git**: projects may or may not use git. Revolver must work standalone.
- **Immutable snapshots**: git commits can be amended/rebased. Revolver snapshots are truly immutable (stored in `.revolver/` with integrity hashes).
- **Simplicity**: no need to parse git history, handle branches, or resolve merge conflicts.
- **Coexistence**: users can (and should) also use git for their project. The two systems are complementary — git for collaboration, Revolver for traceability.

The user provides explicit tags (`v1.0`, `v1.1`) rather than auto-generated version numbers. This mirrors git's tagging model and gives the user control over versioning semantics.

---

## 10. Architecture Impact

### New modules

| Module | Layer | Purpose |
|---|---|---|
| `infra/evaluator_loader.py` | Infrastructure | Dynamic Python module loading for evaluators |

### Existing modules impacted

| Module | Change |
|---|---|
| `core/problem.py` | Implement `test_problem()`, `create_version()`, `list_versions()`, `get_version()` |
| `cli/problem.py` | Implement 3 Typer commands (`test`, `version`, `versions`) |
| `models/problem.py` | Define `ProblemVersion`, `FileSnapshot`, `InstanceTestResult`, `TestResult` |
| `infra/store.py` | Add `find_project_root()`, `write_manifest()`, snapshot directory creation |
| `infra/hashing.py` | Add `file_hash()`, `compute_snapshot_hash()` |
| `infra/db.py` | Add `insert_problem_version()`, `get_problem_version()`, `list_problem_versions()` |

---

## 11. Open Questions

- **PQ-01**: Should `test` results be stored in SQLite (for history)? Current design: no — `test` is a validation tool, not a persistence tool. Only `eval` stores results.
- **PQ-02**: Should `version` auto-run `test` before snapshotting? Current design: no — the user decides when to version. A warning could be added if no test has been run recently (SHOULD, not MUST).
