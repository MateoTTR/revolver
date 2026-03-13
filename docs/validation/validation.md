# Revolver — Validation Overview

**Version**: 0.1 — Initial draft
**Date**: 2026-03-13
**Status**: Draft
**Traceable to**: [Specifications](../specs/specifications.md), [Architecture](../architecture/architecture.md)

---

## 1. Purpose

This document is the root of Revolver's validation documentation. It defines the overall test strategy (levels, tools, CI pipeline, coverage targets) and indexes detailed test plans for integration and E2E tests.

Unit tests (Level 1) are not detailed in a separate document — they are managed dynamically during implementation, guided by the scope and conventions defined here.

Integration tests (Level 2) and E2E tests (Level 3) are described in detail in their respective documents, as they require upfront scenario design.

---

## 2. Validation Document Index

| Document | Path | Purpose |
|---|---|---|
| **This file** | [validation.md](validation.md) | Overview, strategy, tools, CI pipeline |
| Integration Tests | [val-integration-tests.md](val-integration-tests.md) | L2 command test matrix, test data, scenarios |
| E2E Tests | [val-e2e-tests.md](val-e2e-tests.md) | L3 scenarios, LLM mocking strategy, fake server |
| Traceability Matrix | [traceability-matrix.md](traceability-matrix.md) | FR/NFR → DES → test mapping |

---

## 3. Test Levels

```
┌─────────────────────────────────────────────────────┐
│  Level 0 — Static Analysis (ruff, mypy)             │  every commit
├─────────────────────────────────────────────────────┤
│  Level 1 — Unit Tests (pytest)                      │  every commit
├─────────────────────────────────────────────────────┤
│  Level 2 — Integration Tests (pytest + CliRunner)   │  every commit / PR
├─────────────────────────────────────────────────────┤
│  Level 3 — E2E Tests (pytest or bash)               │  nightly / manual
└─────────────────────────────────────────────────────┘
```

| Level | Scope | Speed | External deps | CI trigger | Detailed in |
|---|---|---|---|---|---|
| 0 — Static | Code style, types | ~seconds | None | Every push | This file (§4) |
| 1 — Unit | Functions, classes | ~seconds | None (mocked) | Every push | This file (§5) |
| 2 — Integration | CLI commands, DB, filesystem | ~seconds to minutes | SQLite (real), filesystem (tmpdir) | Every push + PR | [val-integration-tests.md](val-integration-tests.md) |
| 3 — E2E | Full workflows | ~minutes to hours | Ollama, GPU, network (optional) | Nightly / manual | [val-e2e-tests.md](val-e2e-tests.md) |

---

## 4. Level 0 — Static Analysis

### 4.1 Ruff (linting + formatting)

**Tool**: [ruff](https://docs.astral.sh/ruff/) — fast Python linter and formatter.

**Configuration** (`pyproject.toml`):

```toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "N",    # pep8-naming
    "UP",   # pyupgrade
    "B",    # flake8-bugbear
    "SIM",  # flake8-simplify
    "RUF",  # ruff-specific rules
]
```

**Usage**:
- `ruff check src/ tests/` — lint
- `ruff format src/ tests/` — format
- CI gate: both must pass with zero errors

### 4.2 Mypy (type checking)

**Tool**: [mypy](https://mypy.readthedocs.io/) — static type checker.

**Configuration** (`pyproject.toml`):

```toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true

[[tool.mypy.overrides]]
module = "openevolve.*"
ignore_missing_imports = true
```

**Rationale for `strict = true`**:
- Pydantic v2 models (ADR-005) benefit heavily from strict typing
- The codebase is greenfield — strict mode is easier to adopt from day one than to retrofit
- `openevolve` is excluded as a third-party dependency without type stubs

**CI gate**: zero errors.

---

## 5. Level 1 — Unit Tests

Unit tests are not documented individually — they are written alongside implementation in Phase 5. This section defines the scope, coverage targets, and conventions.

### 5.1 Scope

Unit tests cover individual functions and classes in the **domain layer** (`revolver.core`) and **infrastructure layer** (`revolver.infra`), isolated from external dependencies.

| Layer | What to test | Mocking strategy |
|---|---|---|
| `core.project` | Config resolution, project discovery logic | Mock `infra.store`, `infra.config` |
| `core.llm` | Registration validation, status logic | Mock `infra.ollama`, `infra.db` |
| `core.problem` | Version snapshotting, hash computation | Mock `infra.store`, `infra.hashing` |
| `core.dataset` | Registration, integrity check logic, compat rules | Mock `infra.store`, `infra.db`, `infra.hashing` |
| `core.run` | Run configuration, env var setup, lineage recording | Mock `infra.openevolve`, `infra.db`, `infra.store` |
| `core.eval` | Per-instance iteration logic, aggregate computation | Mock `infra.db`, `infra.evaluator_loader` |
| `core.solution` | Query filtering, alias logic, on-demand extraction | Mock `infra.db`, `infra.store` |
| `core.benchmark` | Result reuse logic, comparison stats | Mock `infra.db` |
| `core.doctor` | Dependency detection logic | Mock subprocess calls |
| `core.setup` | Install command generation | Mock subprocess calls |
| `infra.hashing` | SHA-256 of files, directories, datasets | Real filesystem (`tmp_path`) |
| `infra.config` | Config hierarchy merge | Fixtures with YAML strings |
| `infra.db` | Schema creation, migrations, typed queries | SQLite in-memory (`:memory:`) |
| `infra.output` | Human and JSON formatting | Pure function tests |
| `infra.store` | Manifest read/write, directory structure | Real filesystem (`tmp_path`) |
| `infra.token_proxy` | Token extraction from response payloads | Pure function tests |
| `models.*` | Pydantic validation, serialization, frozen models | Pure model tests |

### 5.2 Coverage Targets

| Metric | Target | Rationale |
|---|---|---|
| **Overall line coverage** | >= 80% | Industry standard for a CLI tool with external deps |
| **Domain layer (`core/`)** | >= 90% | Business logic — highest criticality |
| **Infrastructure layer (`infra/`)** | >= 75% | Some modules wrap external tools (Ollama, OpenEvolve) — hard to unit-test fully |
| **Models (`models/`)** | >= 95% | Pure data, easy to test exhaustively |
| **CLI layer (`cli/`)** | Covered by Level 2 | Not unit-tested separately — thin adapter |

**Tool**: `pytest-cov` with `--cov-fail-under` in CI.

### 5.3 Conventions

- **File layout**: `tests/unit/` mirrors `src/revolver/` structure
- **Naming**: `test_<function_or_behavior>` (e.g., `test_hash_directory_deterministic`)
- **Fixtures**: shared fixtures in `tests/conftest.py` and `tests/unit/conftest.py`
- **No real I/O**: all filesystem access via `tmp_path`, all DB via `:memory:`, all HTTP mocked
- **Fast**: full unit suite must run in under 30 seconds

---

## 6. Test Infrastructure

### 6.1 Tooling Summary

| Tool | Purpose | Version |
|---|---|---|
| **pytest** | Test runner, fixtures, markers, parametrize | >= 8.0 |
| **pytest-cov** | Coverage measurement and enforcement | >= 5.0 |
| **ruff** | Linting and formatting | >= 0.8 |
| **mypy** | Static type checking | >= 1.13 |
| **typer.testing.CliRunner** | CLI integration testing | (bundled with Typer) |

### 6.2 Pytest Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: CLI integration tests (real DB + filesystem, mocked externals)",
    "e2e: end-to-end tests with fake LLM server (no GPU required)",
    "e2e_gpu: end-to-end tests requiring Ollama + GPU",
    "slow: tests that take more than 10 seconds",
]
addopts = "--strict-markers -v"
```

### 6.3 Shared Fixtures

Key fixtures defined in `tests/conftest.py`:

| Fixture | Scope | Provides |
|---|---|---|
| `tmp_project` | function | Initialized Revolver project in `tmp_path` with `.revolver/`, DB, default files |
| `cli_runner` | function | `CliRunner` instance configured for the test project |
| `memory_db` | function | SQLite `:memory:` connection with schema applied |
| `sample_instances` | session | Path to `tests/fixtures/instances/` |
| `simple_evaluator` | session | Path to `tests/fixtures/evaluator_simple.py` |
| `mock_ollama` | function | Mocked Ollama HTTP responses (httpx mock) |
| `mock_openevolve` | function | Mocked OpenEvolve that returns deterministic results |
| `fake_llm_server` | session | Local HTTP server exposing OpenAI-compatible `/v1/chat/completions` (E2E only) |

### 6.4 CI Pipeline

```
push / PR:
  ├── ruff check + ruff format --check
  ├── mypy --strict
  ├── pytest tests/unit/ --cov --cov-fail-under=80
  └── pytest tests/integration/ -m integration

nightly (standard runner):
  └── pytest tests/e2e/ -m e2e  (fake LLM server, no GPU)

manual (self-hosted + GPU):
  └── pytest tests/e2e/ -m e2e_gpu  (Ollama + real model)
```

**CI gate**: push/PR pipeline must pass (Level 0 + 1 + 2) for merge. E2E failures are reported but do not block.

---

## 7. What Is NOT Tested

| Exclusion | Reason |
|---|---|
| OpenEvolve internals | Third-party library — tested upstream |
| Ollama server behavior | Third-party service — tested upstream |
| GPU driver functionality | System-level — outside Revolver's control |
| `rich` terminal rendering fidelity | Output library — visual testing not practical |
| Performance benchmarks (NFR-030/031/032) | Validated manually during development; not stable enough for CI gates |

---

## 8. Directory Structure

```
tests/
├── conftest.py                 # Shared fixtures
├── fixtures/                   # Test data (committed to repo)
│   ├── evaluator_simple.py
│   ├── initial_program_simple.py
│   ├── problem_simple.md
│   ├── config_simple.yaml
│   ├── fake_llm_server.py      # OpenAI-compatible fake server for E2E
│   ├── instances/
│   └── instance_bad.json
├── unit/                       # Level 1
│   ├── conftest.py
│   ├── core/
│   │   └── test_<module>.py
│   ├── infra/
│   │   └── test_<module>.py
│   └── models/
│       └── test_<module>.py
├── integration/                # Level 2
│   └── test_<command>.py
└── e2e/                        # Level 3
    ├── test_alice_jobshop.py
    └── test_remote_only.py
```

**Running tests**:

```bash
# All fast tests (unit + integration)
pytest tests/unit/ tests/integration/

# Unit only
pytest tests/unit/

# Integration only
pytest tests/integration/ -m integration

# E2E with fake LLM (no GPU needed)
pytest tests/e2e/ -m e2e

# E2E with real Ollama + GPU
pytest tests/e2e/ -m e2e_gpu

# With coverage
pytest tests/unit/ tests/integration/ --cov=src/revolver --cov-fail-under=80

# Static analysis
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
```
