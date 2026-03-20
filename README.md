# Revolver

**MLOps CLI platform for LLM-guided evolutionary optimization via [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve).**

Revolver adds the operational layer that OpenEvolve lacks: LLM lifecycle management, problem versioning, dataset registration, solution traceability, and multi-solution benchmarking — all from the command line.

## Why Revolver?

OpenEvolve provides the core evolutionary loop for LLM-guided code optimization. Revolver wraps it with everything a domain expert needs to run reproducible experiments:

| Capability | OpenEvolve alone | With Revolver |
|---|---|---|
| LLM management | Manual URL in YAML | Register, start/stop, GPU monitoring |
| Problem versioning | Files on disk | Immutable snapshots with SHA-256 manifests |
| Dataset management | Hardcoded in evaluator | Named, versioned, split (train/eval) |
| Traceability | Partial checkpoints | Full lineage: problem + dataset + LLM + config → solution |
| Benchmarking | Single run | Multi-solution comparison on same evaluation dataset |
| Cost tracking | None | Token usage, API cost estimates, compute time |
| Result export | Raw logs | Structured CSV/JSON with full metadata |

## Features

```
revolver project init                  # Initialize a new optimization project
revolver llm add/start/stop/remove     # Register and manage LLMs (local Ollama or remote API)
revolver llm list/status               # Monitor registered LLMs and GPU usage
revolver problem test                  # Validate evaluator against instances
revolver problem version/versions      # Create and list immutable problem snapshots
revolver dataset add/update/remove     # Register and manage evaluation datasets
revolver dataset list/info/verify      # Inspect datasets and verify integrity
revolver run start/resume              # Launch or resume OpenEvolve optimization runs
revolver run status/list/info          # Monitor and inspect runs
revolver eval run/results              # Evaluate solutions on datasets
revolver solution list/info/alias      # Browse and tag solutions
revolver solution extract/delete       # Extract solution code or clean up
revolver benchmark run/results         # Compare multiple solutions on same dataset
revolver benchmark list/export/delete  # Manage and export benchmark results (CSV/JSON)
```

**Planned**: `doctor`, `setup` (Sprint 007)

## Architecture

```
src/revolver/
├── cli/           # Typer CLI commands (user-facing layer)
├── core/          # Domain logic (orchestration, validation)
├── infra/         # Infrastructure (SQLite, Ollama client, hashing, I/O)
└── models/        # Pydantic data models (frozen, type-safe)
```

Three-layer architecture: **CLI → Core → Infra**. Each layer only depends on the one below. External services (Ollama, LLM APIs, OpenEvolve) are abstracted behind infra modules for testability.

## Quick Start

### Prerequisites

- Python >= 3.11
- [Ollama](https://ollama.ai/) (for local LLMs, optional)
- A GPU with VRAM (for local inference, optional)

### Installation

```bash
# Clone and install in development mode
git clone https://github.com/MateoTTR/revolver.git
cd revolver
pip install -e ".[dev]"
```

### Initialize a project

```bash
revolver project init my-scheduling-problem
cd my-scheduling-problem
```

This creates:
- `.revolver/` — project database and versioned snapshots
- `initial_program.py` — starting code with `EVOLVE-BLOCK` markers
- `evaluator.py` — evaluator template (per-instance + legacy modes)
- `config.yaml` — OpenEvolve configuration

### Register LLMs

```bash
# Remote API (Anthropic, OpenAI, Google)
revolver llm add claude --provider anthropic --model claude-sonnet-4-6-20250514 \
    --api-key-env ANTHROPIC_API_KEY

# Local model via Ollama
revolver llm add codestral --source ollama --model codestral:22b --pull

# Check status
revolver llm list
revolver llm status
```

### Test your evaluator

```bash
# Single instance
revolver problem test --instance data/instances/instance_001.json

# Full dataset
revolver problem test --dataset data/instances/
```

### Version your problem

```bash
revolver problem version --tag v1.0 -m "Initial formulation"
revolver problem versions
```

### Register a dataset

```bash
revolver dataset add training-set data/instances/ --split train
revolver dataset add eval-set data/eval/ --split eval
```

### Run optimization

```bash
revolver run start --llm claude --problem-version v1.0 --dataset training-set
revolver run status
```

### Evaluate and benchmark solutions

```bash
revolver eval run --solution <solution-id> --dataset eval-set
revolver eval results --solution <solution-id>

revolver benchmark run --solutions sol1,sol2,sol3 --dataset eval-set
revolver benchmark results --id <benchmark-id>
revolver benchmark export --id <benchmark-id> --format csv
```

## Key Design Decisions

- **CLI-first**: all functionality exposed as composable CLI commands with `--json` output
- **LLM-agnostic**: supports Ollama (local), Anthropic, OpenAI, Google, and any OpenAI-compatible endpoint
- **Full traceability**: every solution traces back to its problem version, dataset, LLM, and config
- **Reproducibility**: immutable snapshots with SHA-256 content hashing
- **SQLite storage**: lightweight, zero-config, with WAL mode for concurrent access
- **API keys never stored**: only environment variable names are saved (e.g., `ANTHROPIC_API_KEY`)

## Tech Stack

- **Python >= 3.11** — implementation language
- **[Typer](https://typer.tiangolo.com/)** — CLI framework with auto-generated help
- **[Pydantic v2](https://docs.pydantic.dev/)** — frozen data models with validation
- **SQLite** — structured storage (project DB + global LLM registry)
- **[Rich](https://rich.readthedocs.io/)** — human-friendly tables and progress bars
- **[httpx](https://www.python-httpx.org/)** — HTTP client for Ollama REST API
- **[OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve)** — evolutionary optimization engine

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (710+ tests)
python -m pytest tests/

# Lint
ruff check src/ tests/
ruff format --check src/ tests/

# Type check
mypy
```

### Project Status

| Sprint | Focus | Version | Status |
|---|---|---|---|
| Sprint 001 | Project scaffolding, DB, shared infrastructure | v0.1.0 | Done |
| Sprint 002 | LLM registration & problem versioning | v0.2.0 | Done |
| Sprint 003 | Dataset registration & integrity | v0.3.0 | Done |
| Sprint 004 | Run orchestration (OpenEvolve integration) | v0.4.0 | Done |
| Sprint 004a | Demo feedback fixes | v0.4.4 | Done |
| Sprint 004b | Proxy robustness & UX | v0.4.5 | Done |
| Sprint 005 | Solution management & evaluation loop | v0.5.0 | Done |
| Sprint 005a | Demo feedback fixes | v0.5.1 | Done |
| Sprint 006 | Benchmark: multi-solution comparison & export | v0.6.0 | Done |
| Sprint 006a | Demo feedback fixes | v0.6.1 | Done |
| Sprint 006b | Demo feedback fixes | v0.6.2 | Done |
| Sprint 007 | Doctor, setup & cross-cutting polish | — | Planned |

## Documentation

Detailed documentation lives in `docs/`:

- [ConOps](docs/conops/conops.md) — concept of operations, personas, workflows
- [Specifications](docs/specs/specifications.md) — 106 functional + 20 non-functional requirements
- [Architecture](docs/architecture/architecture.md) — system design, ADRs, design documents
- [Validation](docs/validation/validation.md) — test strategy, traceability matrix

## License

MIT
