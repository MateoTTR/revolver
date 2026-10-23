# Revolver

**MLOps CLI platform for LLM-guided evolutionary optimization via a pluggable evolution backend — [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) by default, [ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve) optional.**

Revolver adds the operational layer that evolution backends lack: LLM lifecycle management, problem versioning, dataset registration, solution traceability, and multi-solution benchmarking — all from the command line.

## Why Revolver?

OpenEvolve and ShinkaEvolve provide the core evolutionary loop for LLM-guided code optimization. Revolver wraps either backend with everything a domain expert needs to run reproducible experiments:

| Capability | Backend alone | With Revolver |
|---|---|---|
| LLM management | Manual URL in YAML | Register, start/stop, GPU monitoring |
| Problem versioning | Files on disk | Immutable snapshots with SHA-256 manifests |
| Dataset management | Hardcoded in evaluator | Named, versioned, split (train/eval) |
| Traceability | Partial checkpoints | Full lineage: problem + dataset + LLM + config → solution |
| Benchmarking | Single run | Multi-solution comparison on same evaluation dataset |
| Multi-LLM ensembles | Backend-specific YAML | Unified `--selection` (weighted / adaptive bandit) + `--llm-weight` + per-member `--reasoning-effort`, capability-gated per backend |
| Run metrics | None | Token usage (prompt/completion/total — no cost reported), compute time |
| Result export | Raw logs | Structured CSV/JSON with full metadata |

## Features

```
revolver project init                  # Initialize a new optimization project (--backend scaffolds the matching config.yaml)
revolver doctor                        # Verify environment dependencies
revolver setup                         # Install missing Python dependencies
revolver llm add/update/start/stop/remove  # Register and manage LLMs (local Ollama or remote API; per-LLM --timeout honored on both backends)
revolver llm list/status               # Monitor registered LLMs and GPU usage
revolver llm ensemble create/add/list/info/remove  # Create and manage multi-model ensembles (per-member --weight/--reasoning-effort)
revolver problem test                  # Validate evaluator against instances
revolver problem version create/list/delete  # Create (--backend validates config.yaml), list and delete immutable problem snapshots
revolver dataset add/update/remove     # Register and manage evaluation datasets
revolver dataset list/info             # Inspect datasets
revolver run/run resume                # Launch (--backend openevolve|shinka), tune ensembles (--selection/--llm-weight); resume inherits the parent's backend
revolver run status/list/info/population/cleanup/delete  # Monitor, inspect and clean up runs
revolver eval/eval results             # Evaluate solutions on datasets
revolver solution list/info/alias      # Browse and tag solutions
revolver solution show/extract/delete  # Show, extract (top-N via --rank N / --program-id on extract, ShinkaEvolve-native, gated per backend) or clean up
revolver solution export/diff          # Export solutions or compare two solutions
revolver benchmark/benchmark results   # Compare multiple solutions on same dataset
revolver benchmark list/export/delete  # Manage and export benchmark results (CSV/JSON)
```

## Architecture

```
src/revolver/
├── cli/           # Typer CLI commands (user-facing layer)
├── core/          # Domain logic (orchestration, validation)
├── infra/         # Infrastructure (SQLite, Ollama client, hashing, I/O)
└── models/        # Pydantic data models (frozen, type-safe)
```

Three-layer architecture: **CLI → Core → Infra**. Each layer only depends on the one below. External services (Ollama, LLM APIs, evolution backends) are abstracted behind infra modules for testability.

## Quick Start

### Prerequisites

- Python >= 3.12
- [Ollama](https://ollama.ai/) (for local LLMs, optional)
- A GPU with VRAM (for local inference, optional)

### Installation

```bash
# Clone and install in development mode
git clone https://github.com/MateoTTR/revolver.git
cd revolver
pip install -e ".[dev]"

# Optional: ShinkaEvolve backend (run --backend shinka)
pip install -e ".[shinka]"
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
revolver llm add codestral --source local --model codestral:22b --pull

# Check status
revolver llm list
revolver llm status
```

Registered LLMs live in the **global store** at `~/.revolver/` (the
`config.yaml` and the `revolver.db`). Two knobs relocate it for power users /
CI isolation:

- **`REVOLVER_HOME`** — a base *directory*; Revolver appends `.revolver/`, so it
  moves both the global `config.yaml` and the global DB (e.g. isolating parallel
  CI runners that share `$HOME`).
- **`--global-db <path>`** — a global CLI flag taking the full *file* path to the
  global DB, overriding only the DB location (not `config.yaml`). Precedence:
  `--global-db` > `REVOLVER_HOME` > `~`.

```bash
# CI isolation: pin the whole global store under a scratch dir.
REVOLVER_HOME=/tmp/ci-$RUN_ID revolver llm list

# Or route just the global DB to an explicit file.
revolver --global-db /tmp/ci-$RUN_ID.db llm add foo --provider openai --model gpt-4o-mini
revolver --global-db /tmp/ci-$RUN_ID.db llm list
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
revolver problem version create v1.0 -m "Initial formulation"
revolver problem version list
```

### Register a dataset

```bash
revolver dataset add training-set --path data/instances/ --split train
revolver dataset add eval-set --path data/eval/ --split eval
```

### Run optimization

```bash
revolver run --version v1.0 --llm claude --dataset training-set
revolver run status

# Or on the ShinkaEvolve backend (requires the [shinka] extra).
# Tip: initialize with `revolver project init <name> --backend shinka`
# to scaffold a Shinka-shaped config.yaml (evo_config/db_config/job_config).
revolver run --version v1.0 --llm claude --dataset training-set --backend shinka
```

### Evaluate and benchmark solutions

```bash
revolver eval --solution <solution-id> --dataset eval-set
revolver eval results --solution <solution-id>

revolver benchmark --solutions sol1,sol2,sol3 --dataset eval-set
revolver benchmark results --id <benchmark-id>
revolver benchmark export --id <benchmark-id> --format csv --output results.csv
```

Every evaluation runs in an isolated subprocess that is **killed at the
per-instance timeout** (no leaked workers), with BLAS/OpenMP threads capped
per eval process to avoid core oversubscription:

- **`REVOLVER_EVAL_NUM_THREADS`** — numeric thread cap per eval subprocess
  (`OMP_NUM_THREADS` family). Defaults to `max(1, cpu_count // 2)`; set `0`
  to disable the cap. If you already set any cap variable yourself (e.g.
  `OMP_NUM_THREADS=2`), Revolver injects nothing — you own threading.

```bash
# Cap each eval subprocess at 4 BLAS/OpenMP threads
REVOLVER_EVAL_NUM_THREADS=4 revolver eval --solution <solution-id> --dataset eval-set

# Disable the cap (single big-BLAS evaluation on a dedicated machine)
REVOLVER_EVAL_NUM_THREADS=0 revolver eval --solution <solution-id> --dataset eval-set
```

## Key Design Decisions

- **CLI-first**: all functionality exposed as composable CLI commands with `--json` output
- **LLM-agnostic**: supports Ollama (local), Anthropic, OpenAI, Google, and any OpenAI-compatible endpoint
- **Full traceability**: every solution traces back to its problem version, dataset, LLM, and config
- **Reproducibility**: immutable snapshots with SHA-256 content hashing
- **SQLite storage**: lightweight, zero-config, with WAL mode for concurrent access
- **API keys never stored**: only environment variable names are saved (e.g., `ANTHROPIC_API_KEY`)

## Tech Stack

- **Python >= 3.12** — implementation language
- **[Typer](https://typer.tiangolo.com/)** — CLI framework with auto-generated help
- **[Pydantic v2](https://docs.pydantic.dev/)** — frozen data models with validation
- **SQLite** — structured storage (project DB + global LLM registry)
- **[Rich](https://rich.readthedocs.io/)** — human-friendly tables and progress bars
- **[httpx](https://www.python-httpx.org/)** — HTTP client for Ollama REST API
- **[OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve)** — default evolutionary optimization engine
- **[ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve)** — optional evolution backend (`pip install 'revolver[shinka]'`, ADR-007)

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (1585 passed / 4 skipped, ~35s; +58 shinkaevolve-marked tests need a real-shinka env; L3 e2e tests are deselected by default — run with -m e2e)
python -m pytest tests/

# Lint
ruff check src/ tests/
ruff format --check src/ tests/

# Type check
mypy
```

## Releases

Latest release: **v0.18.0**. The full release history, one section per tag since
v0.1.0, is in [CHANGELOG.md](CHANGELOG.md). Behavior changes that affect existing
configurations (for example the v0.18.0 timeout-penalty and checkpoint-cadence
defaults) are recorded there under the release that introduced them — see the
[v0.18.0 entry](CHANGELOG.md#0180---2026-07-05).

To install a specific tagged version straight from GitHub:

```bash
pip install "revolver @ git+https://github.com/MateoTTR/revolver@v0.18.0"
revolver --version
```

## Known Issues

- **Engine `best_score` is a single, possibly optimistic engine evaluation.**
  `best_score` is a `max()` over single noisy evaluations, so it can overstate
  the champion's true quality. As of v0.18, timed-out instances are penalized
  into the fitness mean by default (`evaluation.on_timeout: drop` restores the
  0.17 survivor-mean), and `run info` shows the engine best labeled
  "(engine, single eval)" next to a coverage-labeled post-eval mean — report
  the post-eval mean, or re-score with `revolver eval` (which runs every
  instance). See the
  [tuning guide](docs/guides/tuning-evolution.md#known-issues) for details.

## Documentation

Detailed documentation lives in `docs/`:

- [ConOps](docs/conops/conops.md) — concept of operations, personas, workflows
- [Specifications](docs/specs/specifications.md) — functional (FR-*) and non-functional (NFR-*) requirements by command group
- [Architecture](docs/architecture/architecture.md) — system design, ADRs, design documents
- [Validation](docs/validation/validation.md) — test strategy, traceability matrix
- [Changelog](CHANGELOG.md) — release history, one section per tag
- [Process checklists](docs/process/README.md) — code / spec / validation / doc review, sprint planning, release, Definition of Done
- [AGENTS.md](AGENTS.md) — the canonical project guide for humans and AI agents
- [Contributing](CONTRIBUTING.md) — how a change goes from an issue to a merged pull request
- [Security policy](SECURITY.md) — supported versions, private vulnerability reporting
- [Code of Conduct](CODE_OF_CONDUCT.md) — Contributor Covenant 2.1

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) (issue first,
fork workflow, local gates, review) and [AGENTS.md](AGENTS.md), the canonical project
guide for humans and AI agents; the review, planning and release procedures are the
checklists under [docs/process/](docs/process/README.md). This project follows the
[Code of Conduct](CODE_OF_CONDUCT.md); report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

## License

MIT
