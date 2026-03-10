# Revolver — Functional & Non-Functional Specifications

**Version**: 0.1 — Initial draft
**Date**: 2026-03-09
**Status**: Draft
**Traceable to**: [ConOps v0.3](../conops/conops.md)

---

## 1. Purpose

This document is the root of Revolver's specification tree. It defines:
- Specification conventions and numbering
- Non-functional requirements (cross-cutting)
- Global CLI conventions
- Index and traceability to ConOps

Functional requirements are organized by CLI command group in separate files (see §5).

---

## 2. Conventions

### 2.1 Requirement Numbering

| Prefix | Domain | Spec File |
|---|---|---|
| FR-PRJ | Project management | [spec-project.md](spec-project.md) |
| FR-LLM | LLM management | [spec-llm.md](spec-llm.md) |
| FR-PRB | Problem definition & testing | [spec-problem.md](spec-problem.md) |
| FR-DAT | Dataset management | [spec-dataset.md](spec-dataset.md) |
| FR-RUN | Solution generation | [spec-run.md](spec-run.md) |
| FR-EVL | Evaluation | [spec-eval.md](spec-eval.md) |
| FR-BEN | Benchmarking | [spec-benchmark.md](spec-benchmark.md) |
| FR-SOL | Solution management | [spec-solution.md](spec-solution.md) |
| FR-SET | Setup & dependencies | [spec-setup.md](spec-setup.md) |
| NFR | Non-functional requirements | This file (§3) |

Each requirement has a unique ID (e.g., `FR-LLM-003`) that is stable across versions. Deleted requirements are marked `[DELETED]`, never renumbered.

### 2.2 Requirement Status

| Status | Meaning |
|---|---|
| `MUST` | Mandatory for V1 |
| `SHOULD` | Expected for V1, can be deferred if needed |
| `MAY` | Nice-to-have, not committed |

### 2.3 Specification Template

Each `spec-*.md` file follows this structure:
1. **Scope** — what CLI commands are covered
2. **Commands** — interface contract (arguments, options, output, exit codes)
3. **Functional Requirements** — enumerated, traceable to ConOps
4. **Error Cases** — trigger, behavior, exit code
5. **Dependencies** — links to other spec files for cross-cutting concerns

---

## 3. Non-Functional Requirements

### 3.1 CLI Ergonomics

| ID | Priority | Requirement |
|---|---|---|
| NFR-001 | MUST | All commands return exit code 0 on success, non-zero on failure |
| NFR-002 | MUST | All commands support `--help` displaying usage, arguments, and options |
| NFR-003 | MUST | All commands support `--json` flag to output machine-readable JSON instead of human-readable text |
| NFR-004 | MUST | Error messages are written to stderr; normal output to stdout |
| NFR-005 | SHOULD | Long-running commands (run, eval, benchmark) display a progress indicator on stderr |
| NFR-006 | SHOULD | Commands that modify state display a confirmation summary (e.g., "Problem version v1.0 created") |
| NFR-007 | MUST | The CLI binary is a single command `revolver` with subcommands (e.g., `revolver llm list`) |
| NFR-008 | SHOULD | Tab completion support for bash and zsh |

### 3.2 Storage & Data Integrity

| ID | Priority | Requirement |
|---|---|---|
| NFR-010 | MUST | Project data is stored in `.revolver/` within the project directory (ConOps §4.1) |
| NFR-011 | MUST | Global data (LLM registry) is stored in `~/.revolver/` (ConOps §4.8) |
| NFR-012 | MUST | Structured metadata uses YAML format (manifests, project config) |
| NFR-013 | MUST | Metrics and lineage data are stored in SQLite (`revolver.db`) |
| NFR-014 | MUST | All hashes use SHA-256 |
| NFR-015 | MUST | Immutable snapshots (problem versions, dataset registrations) cannot be modified after creation |
| NFR-016 | SHOULD | SQLite database supports concurrent reads (WAL mode) |
| NFR-017 | MUST | Dataset integrity is verified by hash comparison at usage time (run, eval, benchmark) |

### 3.3 Reproducibility

| ID | Priority | Requirement |
|---|---|---|
| NFR-020 | MUST | Every solution records its full lineage: problem version, dataset, LLM, config, timestamp |
| NFR-021 | MUST | Local LLM models can be pinned by digest (e.g., `codestral:22b@sha256:...`) |
| NFR-022 | MUST | Dataset registration records per-instance hashes for integrity verification |
| NFR-023 | SHOULD | OpenEvolve config used for a run is stored verbatim in the solution manifest |

### 3.4 Performance

| ID | Priority | Requirement |
|---|---|---|
| NFR-030 | MUST | CLI commands that do not involve LLM inference or evaluation complete in under 2 seconds |
| NFR-031 | SHOULD | Dataset hash computation scales linearly with total data size |
| NFR-032 | SHOULD | SQLite queries for listing solutions/benchmarks return in under 500ms for up to 1000 entries |

### 3.5 Compatibility

| ID | Priority | Requirement |
|---|---|---|
| NFR-040 | MUST | Supported OS: Linux (native), WSL2 |
| NFR-041 | MUST | Requires NVIDIA GPU with compatible driver for local LLM inference |
| NFR-042 | MUST | Ollama must be installed and running for local LLM commands |
| NFR-043 | SHOULD | Graceful degradation when Ollama is not available (remote-only LLMs still work) |
| NFR-044 | MUST | Network access required only for remote LLM APIs and Ollama model downloads |

### 3.6 Security

| ID | Priority | Requirement |
|---|---|---|
| NFR-050 | MUST | API keys are read from environment variables, never stored in Revolver config files |
| NFR-051 | MUST | `.revolver/` directory permissions default to user-only (700) |
| NFR-052 | MUST | No secrets are included in solution lineage or benchmark exports |

### 3.7 Deployment & Dependencies

| ID | Priority | Requirement |
|---|---|---|
| NFR-060 | MUST | Revolver is installable as a Python package via `pip install` (or compatible tool: uv, pipx, etc.) |
| NFR-061 | MUST | All Python dependencies (CLI framework, YAML parser, SQLite driver, OpenEvolve, etc.) are declared in the package metadata and installed automatically |
| NFR-062 | MUST | System-level dependencies (nvidia-smi, GPU drivers) are NOT managed by the installer — they are detected and reported at runtime. Ollama can be installed via conda-forge by `revolver setup` when conda/mamba is available. |
| NFR-063 | MUST | A `revolver doctor` command checks the presence, version, and health of all required dependencies (Python and non-Python) |
| NFR-064 | MUST | A `revolver setup` command installs or upgrades missing dependencies: Python packages via pip, Ollama via conda-forge (when conda/mamba is available), with user confirmation |
| NFR-065 | MUST | `revolver setup` never attempts to install system-level software (GPU drivers, OS packages) — it only reports what is missing with instructions. It never installs conda itself. |
| NFR-066 | SHOULD | `revolver doctor` produces a clear pass/warn/fail status per dependency, with actionable messages for failures |
| NFR-067 | SHOULD | Revolver degrades gracefully when optional dependencies are missing: local LLM features require Ollama, GPU features require nvidia-smi, but remote-only workflows remain functional |
| NFR-068 | SHOULD | `revolver setup` supports `--dry-run` to preview what would be installed without making changes |

---

## 4. Global CLI Conventions

### 4.1 Output Modes

All commands that produce output support two modes:

- **Human mode** (default): formatted text, colors, tables
- **JSON mode** (`--json`): structured JSON to stdout, suitable for piping

### 4.2 Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General error (invalid arguments, missing files, etc.) |
| 2 | Integrity error (hash mismatch, corrupted data) |
| 3 | Resource error (Ollama not running, GPU not available, OOM) |
| 4 | External error (OpenEvolve failure, LLM API error) |

### 4.3 Common Options

These options are available on all commands:

| Option | Description |
|---|---|
| `--help` | Show usage information |
| `--json` | Output in JSON format |
| `--verbose` | Increase output verbosity (show debug info on stderr) |
| `--quiet` | Suppress non-essential output |

### 4.4 Configuration Hierarchy

Configuration is resolved in this order (last wins):
1. Built-in defaults
2. Global config (`~/.revolver/config.yaml`)
3. Project config (`project.yaml`)
4. Command-line arguments
5. Environment variables (`REVOLVER_*`)

---

## 5. Specification Index

| Spec File | Commands Covered | ConOps Reference | Summary |
|---|---|---|---|
| [spec-project.md](spec-project.md) | `revolver project init` | §4.1, §5.2 | Project creation and initialization |
| [spec-llm.md](spec-llm.md) | `revolver llm {add,start,stop,status,list,remove}` | §4.8, §5.1 | LLM registration, lifecycle, monitoring |
| [spec-problem.md](spec-problem.md) | `revolver problem {test,version,versions}` | §4.2, §5.3, §5.4, §7.1 | Problem testing and versioning |
| [spec-dataset.md](spec-dataset.md) | `revolver dataset {add,update,list,info}` | §4.3, §4.4, §5.4, §7.2 | Dataset registration, integrity, compatibility |
| [spec-run.md](spec-run.md) | `revolver run {<default>,status,resume}` | §4.6, §5.5 | OpenEvolve orchestration, solution generation |
| [spec-eval.md](spec-eval.md) | `revolver eval {<default>,results}` | §5.6 | Single solution evaluation |
| [spec-benchmark.md](spec-benchmark.md) | `revolver benchmark {<default>,results,export}` | §4.7, §5.7, §8 | Multi-solution comparison and export |
| [spec-solution.md](spec-solution.md) | `revolver solution {list,info,alias}` | §4.6 | Solution browsing and metadata |
| [spec-setup.md](spec-setup.md) | `revolver doctor`, `revolver setup` | NFR-060–068 | Dependency verification and assisted installation |

---

## 6. Traceability Matrix — ConOps to Specs

| ConOps Section | Topic | Spec Requirements |
|---|---|---|
| §3.1 | Target environment | NFR-040 to NFR-044 |
| §3.2 | LLM backends | FR-LLM-* |
| §3.3 | Concurrency model | FR-RUN-* |
| §4.1 | Project structure | FR-PRJ-*, NFR-010 |
| §4.2 | Problem definition | FR-PRB-* |
| §4.3 | Dataset | FR-DAT-* |
| §4.4 | Instance injection | FR-RUN-*, FR-EVL-* |
| §4.5 | Metrics and objectives | FR-EVL-*, FR-BEN-* |
| §4.6 | Solution | FR-SOL-*, FR-RUN-* |
| §4.7 | Benchmark | FR-BEN-* |
| §4.8 | LLM registry | FR-LLM-* |
| §5.1 | Workflow: Setup LLMs | FR-LLM-* |
| §5.2 | Workflow: Create project | FR-PRJ-* |
| §5.3 | Workflow: Test problem | FR-PRB-* |
| §5.4 | Workflow: Version & register | FR-PRB-*, FR-DAT-* |
| §5.5 | Workflow: Generate solution | FR-RUN-* |
| §5.6 | Workflow: Evaluate | FR-EVL-* |
| §5.7 | Workflow: Benchmark | FR-BEN-* |
| §7 | Immutability & integrity | NFR-014 to NFR-017, NFR-020 to NFR-023 |
| §8 | Export format | FR-BEN-* |
| §9 | V1 scope | All FR-* and NFR-* |
