# Revolver — Architecture Overview

**Version**: 0.1 — Initial draft
**Date**: 2026-03-10
**Status**: Draft
**Traceable to**: [ConOps v0.3](../conops/conops.md), [Specifications v0.1](../specs/specifications.md)

---

## 1. System Context

Revolver is a CLI tool that orchestrates OpenEvolve and manages the operational layer around it. It interacts with:

```
                                    ┌──────────────────┐
                                    │  Remote LLM APIs │
                                    │  (Anthropic,     │
                                    │   Google, OpenAI)│
                                    └────────▲─────────┘
                                             │ OpenAI-compat API
                                             │
┌──────────┐    CLI commands    ┌────────────┴──────────────┐
│          │ ──────────────────>│                           │
│   User   │                   │        Revolver           │
│          │<────────────────  │                           │
└──────────┘   stdout/stderr   │   ┌───────────────────┐  │
                               │   │  .revolver/ store  │  │
                               │   │  (SQLite + files)  │  │
                               │   └───────────────────┘  │
                               │                           │
                               └──────┬─────────┬─────────┘
                                      │         │
                            import    │         │ HTTP (localhost)
                                      │         │
                               ┌──────▼──┐  ┌───▼──────────┐
                               │OpenEvolve│  │   Ollama     │
                               │(Python   │  │  (local LLM  │
                               │ library) │  │   server)    │
                               └─────────┘  └──────────────┘
```

### External dependencies

| Dependency | Type | Managed by Revolver? | Install method | Reference |
|---|---|---|---|---|
| OpenEvolve | Python library (import) | Yes (`revolver setup`) | pip | NFR-060, FR-SET-* |
| Ollama | Service (HTTP on localhost) | Yes, if conda available | conda-forge | ADR-001, NFR-042, FR-SET-015 |
| Remote LLM APIs | Network services | No (user provides API keys) | — | NFR-050 |
| Python >= 3.12 | Runtime | No (prerequisite) | — | ADR-002 |
| NVIDIA GPU + drivers | Hardware/system | No (detected by `doctor`) | — | NFR-041 |

---

## 2. Layered Architecture

Revolver follows a **three-layer architecture** separating CLI presentation, domain logic, and infrastructure concerns.

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI Layer (Typer)                         │
│  revolver.cli                                                   │
│  ┌──────┐ ┌─────┐ ┌───────┐ ┌───────┐ ┌─────┐ ┌────┐ ┌──────┐│
│  │project│ │ llm │ │problem│ │dataset│ │ run │ │eval│ │bench ││
│  └──┬───┘ └──┬──┘ └───┬───┘ └───┬───┘ └──┬──┘ └─┬──┘ └──┬───┘│
│     │        │        │         │         │      │        │     │
│  ┌──┴──┐ ┌───┴──┐ ┌───┴───┐    │    ┌────┴──┐   │   ┌────┴──┐ │
│  │soln │ │setup │ │doctor │    │    │       │   │   │       │ │
│  └──┬──┘ └───┬──┘ └───┬───┘    │    │       │   │   │       │ │
│─────┼────────┼────────┼────────┼────┼───────┼───┼───┼───────┼─│
│                     Domain Layer                                │
│  revolver.core                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ project  │ │   llm    │ │ problem  │ │     dataset      │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │   run    │ │   eval   │ │benchmark │ │     solution     │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │
│  ┌──────────┐ ┌──────────┐                                     │
│  │  setup   │ │  doctor  │                                     │
│  └──────────┘ └──────────┘                                     │
│─────────────────────────────────────────────────────────────────│
│                   Infrastructure Layer                          │
│  revolver.infra                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │  store   │ │    db    │ │ hashing  │ │     config       │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                        │
│  │  output  │ │  ollama  │ │openevolve│                        │
│  └──────────┘ └──────────┘ └──────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

### Layer responsibilities

| Layer | Package | Responsibility | Depends on |
|---|---|---|---|
| **CLI** | `revolver.cli` | Parse arguments (Typer), validate input, format output (human/JSON), exit codes | Domain |
| **Domain** | `revolver.core` | Business logic, orchestration, invariants (immutability, integrity, lineage) | Infrastructure |
| **Infrastructure** | `revolver.infra` | File I/O, SQLite, hashing, Ollama HTTP client, OpenEvolve wrapper, config loading | External libs |

**Dependency rule**: each layer depends only on the layer below it. The CLI layer never accesses SQLite directly; the domain layer never formats output.

---

## 3. Package Structure

```
src/revolver/
├── __init__.py
├── __main__.py              # Entry point: python -m revolver
│
├── cli/                     # CLI Layer
│   ├── __init__.py          # Root Typer app, global options callback
│   ├── project.py           # revolver project init
│   ├── llm.py               # revolver llm {add,start,stop,status,list,remove}
│   ├── problem.py           # revolver problem {test,version,versions}
│   ├── dataset.py           # revolver dataset {add,update,remove,list,info}
│   ├── run.py               # revolver run {<default>,status,resume,list,info,delete}
│   ├── eval.py              # revolver eval {<default>,results}
│   ├── solution.py          # revolver solution {list,info,alias,extract,delete,show,export,diff}
│   ├── benchmark.py         # revolver benchmark {<default>,results,export,list,delete}
│   ├── doctor.py            # revolver doctor
│   └── setup.py             # revolver setup
│
├── core/                    # Domain Layer
│   ├── __init__.py
│   ├── project.py           # Project creation, discovery, config resolution
│   ├── llm.py               # LLM registration, lifecycle management
│   ├── problem.py           # Problem testing, version snapshotting
│   ├── dataset.py           # Dataset registration, integrity verification
│   ├── run.py               # OpenEvolve orchestration, run management
│   ├── eval.py              # Evaluation loop (per-instance iteration)
│   ├── solution.py          # Solution browsing, alias management, on-demand extraction
│   ├── benchmark.py         # Multi-solution comparison, export
│   ├── doctor.py            # Dependency health checks
│   └── setup.py             # Assisted dependency installation
│
├── infra/                   # Infrastructure Layer
│   ├── __init__.py
│   ├── store.py             # .revolver/ directory management (read/write manifests, snapshots)
│   ├── db.py                # SQLite connection, schema migration, queries
│   ├── hashing.py           # SHA-256 computation (files, directories, datasets)
│   ├── config.py            # Config hierarchy resolution (defaults → global → project → CLI → env)
│   ├── output.py            # Output formatting (human tables, JSON, progress bars)
│   ├── ollama.py            # Ollama HTTP client (pull, start, stop, status, models)
│   ├── gpu.py               # nvidia-smi wrapper (GPU name, VRAM usage/total)
│   ├── evaluator_loader.py  # Dynamic Python module loading for evaluator (DES-003)
│   ├── openevolve.py        # OpenEvolve wrapper (import, configure, launch, monitor)
│   └── token_proxy.py      # Transparent HTTP proxy for token usage tracking (DES-005 DD-14)
│
└── models/                  # Shared data models (dataclasses / Pydantic)
    ├── __init__.py
    ├── project.py           # ProjectConfig
    ├── llm.py               # LLMEntry, LLMStatus
    ├── problem.py           # ProblemVersion, ProblemManifest
    ├── dataset.py           # DatasetRegistration, InstanceHash
    ├── run.py               # Run, RunManifest, RunResult
    ├── solution.py          # Solution (lightweight reference)
    ├── eval.py              # EvalResult, InstanceResult
    └── benchmark.py         # BenchmarkResult, BenchmarkExport
```

### Why `src/` layout?

The `src/revolver/` layout (vs flat `revolver/`) prevents accidental imports from the working directory during development and is the recommended practice for pip-installable packages (PEP 517).

---

## 4. Component Details

### 4.1 CLI Layer — `revolver.cli`

Each CLI module defines a `typer.Typer()` instance composed into the root app.

**Root app** (`cli/__init__.py`):
- Defines global options via `@app.callback()`: `--json`, `--verbose`, `--quiet`
- Stores global state in `typer.Context.obj` (a shared dict or dataclass)
- Registers all command groups via `app.add_typer()`
- Registers top-level commands: `doctor`, `setup`

**Per-module pattern**:
```
1. Parse and validate CLI arguments (Typer handles types)
2. Call domain layer function
3. Format result via output module (human or JSON based on --json flag)
4. Set exit code (sys.exit or raise typer.Exit)
```

The CLI layer does **no business logic** — it is a thin adapter.

### 4.2 Domain Layer — `revolver.core`

Each module encapsulates the business rules for one command group. Key responsibilities:

| Module | Key operations |
|---|---|
| `project` | Init project directory, discover `.revolver/`, resolve config hierarchy |
| `llm` | Register/remove LLMs, start/stop local models via Ollama client, check status. See [DES-002](design/DES-002-llm-subcommands.md) for Ollama API mapping |
| `problem` | Run evaluator on instances (test), create immutable snapshots (version), list versions. See [DES-003](design/DES-003-problem-versioning.md) |
| `dataset` | Register dataset by reference, compute hashes, verify integrity, manage compatibility. See [DES-004](design/DES-004-dataset-registration.md) |
| `run` | Configure OpenEvolve, set environment variables for instance injection, launch run, store run artifacts, create solution DB references (run_id, rank), record lineage in runs table |
| `eval` | Iterate instances, invoke evaluator per instance, collect metrics, compute aggregates, store in SQLite |
| `solution` | Query solutions from SQLite, manage aliases, `show_solution()`, `diff_solutions()`, `extract_solution(force=True)` |
| `benchmark` | Orchestrate multi-solution eval, reuse existing results, compute comparison stats, export CSV/JSON |
| `doctor` | Check Python version, Ollama availability, GPU (nvidia-smi), OpenEvolve importability |
| `setup` | Install/upgrade Python dependencies (OpenEvolve, etc.) with user confirmation |

**Cross-cutting rules enforced here**:
- Immutability: snapshots and registrations cannot be modified after creation
- Integrity: hash verification before any run/eval/benchmark
- Lineage: every solution records full provenance
- Split warnings: warn (not block) on train/eval mismatch

### 4.3 Infrastructure Layer — `revolver.infra`

| Module | Responsibility | Key details |
|---|---|---|
| `store` | File-based storage in `.revolver/` | Read/write YAML manifests, create snapshot directories, manage directory structure |
| `db` | SQLite database (`revolver.db`) | Schema creation/migration, WAL mode (NFR-016), typed query functions |
| `hashing` | SHA-256 computation | File hash, directory tree hash, dataset global hash (NFR-014) |
| `config` | Configuration resolution | 5-level hierarchy: defaults → global → project → CLI → env vars (§4.4 of specs) |
| `output` | Output formatting | Human-readable tables (rich), JSON serialization, progress bars (rich.progress) |
| `ollama` | Ollama HTTP client | Wraps Ollama REST API: pull model, load/unload, list models, check health |
| `gpu` | GPU monitoring | Wraps `nvidia-smi` for GPU name, VRAM used/total. Used by `llm status` and `doctor` |
| `openevolve` | OpenEvolve integration | Import OpenEvolve as library, configure programmatically, launch evolution, monitor progress |

### 4.4 Data Models — `revolver.models`

Shared dataclasses (or Pydantic models) used across layers. These are pure data containers with no side effects.

Data models use **Pydantic v2** `BaseModel` ([ADR-005](adr/ADR-005-pydantic-data-models.md)). Immutable entities use `frozen=True`. Serialization via `model_dump()` / `model_dump_json()` for `--json` output. Validation via `model_validate()` at system boundaries (DB reads, CLI input, YAML parsing).

---

## 5. Data Storage

### 5.1 Dual storage strategy

| Store | Format | Contents | Scope |
|---|---|---|---|
| `.revolver/` (project) | Files + YAML manifests | Problem snapshots, dataset manifests, run artifacts (programs, checkpoints, configs, wrapper evaluators) | Per-project |
| `.revolver/revolver.db` | SQLite | Metrics, lineage, eval results, benchmark results, timestamps | Per-project |
| `~/.revolver/` (global) | YAML | LLM registry, global config | Per-user |

### 5.2 Why both files and SQLite?

- **Files** for artifacts that are naturally file-based: source code (programs, evaluators), configs, checkpoints. These benefit from direct filesystem access and are easy to inspect.
- **SQLite** for structured, queryable data: metrics, lineage, evaluation results. These benefit from SQL queries (filtering, sorting, aggregation) and atomic writes. SQLite in WAL mode supports concurrent reads (NFR-016).
- **YAML** for human-readable configuration and manifests. Easy to inspect and version-control.

### 5.3 SQLite schema (high-level)

Detailed schema in [DES-001 — SQLite Data Model](design/DES-001-sqlite-data-model.md). Key tables:

| Table | Purpose | Key columns |
|---|---|---|
| `problem_versions` | Version metadata | tag, hash, created_at, message |
| `datasets` | Dataset registrations | name, path, split, global_hash, instance_count |
| `dataset_instances` | Per-instance hashes | dataset_name, instance_id, hash |
| `dataset_compat` | Version compatibility | dataset_name, problem_version |
| `llms` | LLM registry (global DB) | name, provider, model, source, base_url, api_key_env |
| `ensembles` | Named LLM ensembles (global DB) | name, created_at |
| `ensemble_members` | Ensemble member LLMs with weights (global DB) | ensemble_name, llm_name, weight, temperature, max_tokens |
| `runs` | Evolution run metadata + lineage | id, problem_version, llm, dataset, status, llm_type, llm_snapshot, resumed_from, created_at |
| `solutions` | Lightweight solution references | id, run_id, rank, best_score, alias |
| `eval_metadata` | Evaluation session metadata | eval_id, solution_id, dataset_name, instance_count, instances_solved, eval_time_s, user_aggregates, evaluated_at |
| `eval_instances` | Per-instance results | eval_id, instance_id, metric_name, value, compute_time_s |
| `benchmarks` | Benchmark metadata | id, alias, dataset_name, created_at |
| `benchmark_solutions` | Benchmark membership | benchmark_id, solution_id |

---

## 6. Key Data Flows

### 6.1 Solution generation (`revolver run`)

```
User: revolver run --version v1.1 --llm claude --dataset train-small

CLI Layer
  │ parse args, resolve --json flag
  ▼
Domain Layer (core.run)
  │ 1. Load problem version v1.1 from store
  │ 2. Load dataset "train-small" manifest
  │ 3. Verify dataset integrity (recompute hashes)
  │ 4. Resolve LLM config from registry
  │ 5. Set env vars: REVOLVER_DATASET_DIR
  │ 6. Configure OpenEvolve programmatically
  │ 7. Launch OpenEvolve evolution loop
  │ 8. On completion: store run artifacts, create solution references in SQLite
  ▼
Infrastructure Layer
  ├── store: read problem snapshot, write run directory
  ├── db: insert run + solution rows
  ├── hashing: verify dataset integrity
  ├── ollama: (if local LLM) ensure model is loaded
  └── openevolve: import and run OpenEvolve
```

### 6.2 Evaluation (`revolver eval`)

```
User: revolver eval --solution claude-v1.1 --dataset eval-bench

Domain Layer (core.eval)
  │ 1. Load solution metadata + parent run
  │ 2. Resolve program path from run directory: `.revolver/runs/<run_id>/programs/rank-<N>.py`
  │ 3. Load dataset manifest + verify integrity
  │ 4. For each instance in dataset:
  │    a. Set REVOLVER_INSTANCE_PATH, REVOLVER_INSTANCE_ID
  │    b. Import evaluator from problem version snapshot
  │    c. Call evaluate_instance() or evaluate() in subprocess
  │    d. Collect metrics dict + wall-clock time
  │    e. Store raw per-instance result in SQLite immediately
  │ 5. Store eval metadata in SQLite
  │ 6. Compute aggregates at read time from raw data (not stored)
  ▼
Infrastructure Layer
  ├── store: resolve program path from run dir, resolve evaluator path
  ├── db: insert eval_metadata + eval_instances rows
  └── hashing: verify dataset integrity
```

### 6.3 Benchmark (`revolver benchmark`)

```
Domain Layer (core.benchmark)
  │ 1. For each solution in --solutions:
  │    a. Check if eval results already exist for this (solution, dataset) pair
  │    b. If not: run evaluation (reuse core.eval logic)
  │    c. If yes: reuse stored results
  │ 2. Aggregate and compare across solutions
  │ 3. Store benchmark metadata + references in SQLite
  ▼
Infrastructure Layer
  ├── db: query existing eval results, insert benchmark rows
  └── output: format comparison table or export CSV/JSON
```

---

## 7. Cross-Cutting Concerns

### 7.1 Output formatting

All commands support two output modes (NFR-003):
- **Human mode** (default): rich tables, colors, progress bars via `rich` library
- **JSON mode** (`--json`): structured JSON to stdout

The `output` module provides a unified interface. CLI modules call `output.render(data, json_mode)` — they never format output directly.

Errors always go to stderr (NFR-004). Progress indicators go to stderr (NFR-005).

### 7.2 Error handling and exit codes

| Code | Meaning | Raised by |
|---|---|---|
| 0 | Success | All commands |
| 1 | General error (invalid args, missing files, name conflict) | All commands |
| 2 | Integrity error (hash mismatch, corrupted data) | dataset, eval, benchmark, run |
| 3 | Resource error (Ollama not running, GPU unavailable, OOM) | llm, run |
| 4 | External error (OpenEvolve failure, LLM API error) | llm, run, eval |

Domain layer raises typed exceptions (e.g., `IntegrityError`, `ResourceError`). CLI layer catches them and maps to exit codes.

### 7.3 Configuration hierarchy

Resolution order (last wins), as defined in specifications §4.4:

```
Built-in defaults
  └── ~/.revolver/config.yaml (global)
       └── project.yaml (project)
            └── CLI arguments
                 └── REVOLVER_* environment variables
```

The `config` module resolves this chain and returns a merged config object.

### 7.4 Project discovery

Commands that require a project context (all except `llm`, `doctor`, `setup`, `project init`) search upward from the current directory for a `.revolver/` directory. If not found, they exit with code 1 and a clear error message.

---

## 8. Technology Stack Summary

| Concern | Technology | ADR |
|---|---|---|
| Language | Python >= 3.12 | ADR-002 |
| CLI framework | Typer (>= 0.21) on Click | ADR-003 |
| Local LLM server | Ollama | ADR-001 |
| Structured storage | SQLite (WAL mode) | ADR-004 |
| Config/manifest format | YAML (PyYAML) | — |
| Hashing | SHA-256 (hashlib, stdlib) | — |
| Terminal output | rich | — |
| Data models | Pydantic v2 | ADR-005 |
| HTTP client | httpx (for Ollama API) | — |
| Evolution engine | OpenEvolve (Python import) | — |
| Package format | pip-installable (`pyproject.toml`) | NFR-060 |

---

## 9. Architecture Decision Records

| ADR | Title | Status |
|---|---|---|
| [ADR-001](adr/ADR-001-ollama-local-llm-backend.md) | Ollama as local LLM backend | Accepted |
| [ADR-002](adr/ADR-002-python-language.md) | Python as implementation language | Accepted |
| [ADR-003](adr/ADR-003-cli-framework-typer.md) | Typer as CLI framework | Accepted |
| [ADR-004](adr/ADR-004-sqlite-structured-storage.md) | SQLite for structured storage | Accepted |
| [ADR-005](adr/ADR-005-pydantic-data-models.md) | Pydantic for data models | Accepted |
| [ADR-006](adr/ADR-006-openevolve-instance-injection.md) | Strategy A+B hybrid for OpenEvolve instance injection | Accepted |

---

## 10. Design Documents

Detailed design notes expanding on specific architectural areas. Each document traces back to relevant ADRs and specifications.

| ID | Title | Traces to | Status |
|---|---|---|---|
| [DES-001](design/DES-001-sqlite-data-model.md) | SQLite Data Model | ADR-004, NFR-013/016 | Draft |
| [DES-002](design/DES-002-llm-subcommands.md) | `revolver llm` Subcommands — Ollama API Mapping | ADR-001, spec-llm | Draft |
| [DES-003](design/DES-003-problem-versioning.md) | `revolver problem` — Testing & Versioning | spec-problem, AQ-04 | Draft |
| [DES-004](design/DES-004-dataset-registration.md) | `revolver dataset` — Registration & Integrity | spec-dataset, DES-001 | Draft |
| [DES-005](design/DES-005-run-orchestration.md) | `revolver run` — OpenEvolve Orchestration | spec-run, ADR-006, DES-001, DES-003, DES-004, POC #12, POC #13 | Draft |
| [DES-006](design/DES-006-eval-loop.md) | `revolver eval` — Evaluation Loop | spec-eval, ADR-006, DES-001, DES-003, DES-005 | Draft |
| [DES-007](design/DES-007-benchmark-design.md) | `revolver benchmark` — Benchmark Design | spec-benchmark, DES-001, DES-005, DES-006 | Draft |

---

## 11. Open Architectural Questions

- [x] **AQ-01**: Dataclasses vs Pydantic for data models → **Pydantic v2** (ADR-005)
- [ ] **AQ-02**: SQLite schema migration strategy (manual SQL scripts vs alembic-like tool)
- [x] **AQ-03**: How to handle OpenEvolve's evaluator iteration vs Revolver's instance injection during training → **A+B hybrid strategy**: env var injection (`REVOLVER_DATASET_DIR`) + optional SQLite side-channel (`REVOLVER_INSTANCE_LOG`). Wrapper uses `OpenEvolve` controller class for resume support. Revolver generates the dual-mode evaluator wrapper. (ADR-006, POC #12)
- [x] **AQ-04**: Project/problem versioning strategy → **Internal manifest-based** (DES-003 §9 DD-06)
- [x] **AQ-05**: Benchmark export format for visualization → **CSV + JSON** (DES-007 DD-03). Parquet not supported in v1 (adds ~150MB dependency for marginal benefit). `--per-instance` export provides raw data for external visualization tools (pandas, matplotlib, Jupyter).
