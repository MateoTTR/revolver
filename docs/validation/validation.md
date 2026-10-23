# Revolver — Validation Overview

**Version**: 0.3 — Tooling sections (§4, §6.1, §6.2, §6.4, §8) aligned with `pyproject.toml` and `ci.yml`; `--strict-markers` adopted; the unregistered `e2e_gpu` marker dropped (S19-27, ADR-008). Previous: 0.2 — Test ID conventions (§8.1) (S18)
**Date**: 2026-10-23
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
│  Level 2-OE — OpenEvolve Contract Tests (pytest)    │  every PR (non-blocking)
├─────────────────────────────────────────────────────┤
│  Level 3 — E2E Tests (pytest or bash)               │  manual (on demand)
└─────────────────────────────────────────────────────┘
```

| Level | Scope | Speed | External deps | CI trigger | Detailed in |
|---|---|---|---|---|---|
| 0 — Static | Code style, types | ~seconds | None | Every push | This file (§4) |
| 1 — Unit | Functions, classes | ~seconds | None (mocked) | Every push | This file (§5) |
| 2 — Integration | CLI commands, DB, filesystem | ~seconds to minutes | SQLite (real), filesystem (tmpdir) | Every push + PR | [val-integration-tests.md](val-integration-tests.md) |
| 2-OE — OpenEvolve | Config roundtrip, controller init | ~seconds | openevolve (pip), no LLM/GPU | Every PR (non-blocking) | [val-integration-tests.md](val-integration-tests.md) |
| 2-Shinka — ShinkaEvolve *(implemented — S14, ADR-007)* | Config projection, wrapper contract (`metrics.json`), `programs.sqlite` parsing | ~seconds | shinka-evolve (pip extra), no LLM/GPU | Every PR (non-blocking) | [val-integration-tests.md](val-integration-tests.md) |
| 3 — E2E | Full workflows | ~minutes to hours | Ollama, GPU, network (optional) | Manual (on demand) | [val-e2e-tests.md](val-e2e-tests.md) |

**Backend matrix axis (ADR-007)**: with the pluggable evolution backend, tests split along a new
axis. **Engine-neutral** tests (~36 of the ~44 commands: `llm`, `dataset`, `solution`, `eval`,
`benchmark`, `problem`, `run list/info/delete/cleanup`) run **once** — they do not depend on the
engine. **Engine-coupled** tests (`run` launch, `run resume`, `run status` active-path,
`run population`, plus the doctor/setup/project-init/version-create shims) are **parameterized per
backend**: the existing matrices stay as-is for OpenEvolve, with a ShinkaEvolve variant since S14.
Each backend keeps a dedicated contract-test track (L2-OE, L2-Shinka).

---

## 4. Level 0 — Static Analysis

### 4.1 Ruff (linting + formatting)

**Tool**: [ruff](https://docs.astral.sh/ruff/) — fast Python linter and formatter.

**Configuration** (`pyproject.toml`):

```toml
[tool.ruff]
target-version = "py312"
src = ["src"]
line-length = 99

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "UP",   # pyupgrade
    "B",    # flake8-bugbear
    "SIM",  # flake8-simplify
    "RUF",  # ruff-specific
]

[tool.ruff.lint.isort]
force-sort-within-sections = true
force-single-line = false
combine-as-imports = true
```

**Usage**:
- `ruff check src/ tests/` — lint
- `ruff format --check src/ tests/` — formatting check (what CI runs); `ruff format src/ tests/` applies it
- CI gate: both must pass with zero errors

### 4.2 Mypy (type checking)

**Tool**: [mypy](https://mypy.readthedocs.io/) — static type checker.

**Configuration** (`pyproject.toml`):

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_configs = true
packages = ["revolver"]
mypy_path = "src"
```

**Rationale for `strict = true`**:
- Pydantic v2 models (ADR-005) benefit heavily from strict typing
- The codebase is greenfield — strict mode is easier to adopt from day one than to retrofit
- The engine packages (`openevolve`, `shinka`) ship no type stubs and are optional at runtime: the backend adapters import them lazily inside functions with targeted `# type: ignore[import-not-found,import-untyped]` comments, so no per-module override is needed and `mypy` passes without the engines installed

**Usage**: `mypy` with no path argument — the targets come from `packages` / `mypy_path` in `pyproject.toml` (this is what CI runs).

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
| `core.run` | Run configuration, env var setup, lineage recording | Mock `infra.backends.openevolve`, `infra.db`, `infra.store` |
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
| **pytest** | Test runner, fixtures, markers, parametrize | >= 8 |
| **pytest-cov** | Coverage measurement and enforcement | >= 5 |
| **ruff** | Linting and formatting | >= 0.9 |
| **mypy** | Static type checking | >= 1.14 (+ `types-PyYAML` stubs) |
| **typer.testing.CliRunner** | CLI integration testing | (bundled with Typer) |

Versions are those of the `dev` extra in `pyproject.toml` (`pip install -e ".[dev]"`).

### 6.2 Pytest Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-m 'not e2e' --strict-markers"
markers = [
    "unit: L1 unit tests",
    "integration: L2 integration tests",
    "openevolve: L2-OE tests requiring the openevolve package (no LLM needed)",
    "shinkaevolve: L2-Shinka tests requiring the shinka-evolve package (no LLM needed)",
    "e2e: L3 end-to-end tests",
    "slow: long-running tests (always applied to E2E tests)",
]
```

- `-m 'not e2e'` deselects the L3 E2E tests by default (they are manual — [val-e2e-tests.md](val-e2e-tests.md)), so a plain `pytest tests/` never runs them even with the engine extras installed; run them explicitly with `-m e2e`.
- `--strict-markers` (adopted at v0.19.0, S19-27) turns an unregistered `@pytest.mark.<name>` into a collection error instead of a warning, so every marker — including the per-backend engine markers — must be registered in the list above. The full suite was verified to collect cleanly under the flag before adoption.
- The `e2e_gpu` marker is registered for the manual GPU track (real Ollama + GPU, see [val-e2e-tests.md](val-e2e-tests.md)); no test uses it yet. Under `--strict-markers` only registered markers are accepted.

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
push / PR — ci.yml (no path filters: every job is a required status check under the branch rulesets,
                    and a required check that never runs would leave the PR stuck on "Expected"):
  ├── Lint (ruff + mypy): ruff check + ruff format --check + mypy --strict
  ├── Test (pytest + coverage): pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"  (Python 3.12 + 3.14 matrix)
  │     └── pip install "openevolve>=0.2.26" && pytest tests/integration/test_run_oe.py  (3.12 only, non-blocking)
  └── Doc command-lint (fenced CLI invocations): pytest tests/unit/test_doc_command_lint.py tests/unit/test_doc_freshness.py
        (#354 command-lint + #355 freshness stamps, blocking; formerly the separate doc-lint.yml workflow)

tag push (v*) — ci.yml version-check:
  └── tag == pyproject.toml version == src/revolver/__init__.py __version__

manual (no dedicated workflow yet — run by hand on a developer machine):
  ├── pytest tests/e2e/ -m e2e  (fake LLM server, no GPU)
  └── the GPU-backed E2E scenarios of val-e2e-tests.md against a local Ollama (manual procedure, no marker)
```

**CI gate**: the four jobs of the push/PR pipeline (Level 0 + 1 + 2 and the doc command-lint) are the required status checks for merge, on docs-only and code-only changes alike. L2-OE and E2E failures are reported but do not block.

**No Shinka job in CI**: ci.yml runs **no** ShinkaEvolve step — the main test job's `-m "unit or integration"` selection runs without the `[shinka]` extra installed (Shinka-gated modules auto-skip via `pytest.importorskip`), and only the OpenEvolve contract tests get a dedicated non-blocking step. The L2-Shinka contract suites are selected by the `-m shinkaevolve` marker (6+ modules — no longer the historic 3-file list) and run manually in a shinka-enabled environment (e.g. before a release); adding a Shinka-env CI step remains aspirational.

**Draft PRs**: the lint, test and doc-lint jobs are skipped for draft PRs to save CI minutes; they run once the PR is marked ready.

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

### 8.1 Test ID Conventions

The validation documents ([val-integration-tests.md](val-integration-tests.md), the
[traceability matrix](traceability-matrix.md)) reference tests by an ID of the form
`<path-under-tests/>::<test_name>` — e.g. `integration/test_llm::test_llm_add_remote` or
`unit/core/test_problem::test_warns_missing_combined_score`.

- **Canonical L2 home**: new integration suites live in `tests/integration/test_<command>.py`
  and their IDs carry the `integration/` prefix.
- **Top-level exception (historic)**: several L2 suites predate the `tests/integration/` layout
  and live in top-level `tests/test_*.py` files (e.g. `test_project_integration.py`,
  `test_core_run.py`, `test_run_delete.py`, `test_db_migration_v*.py`, `test_run_population.py`).
  Their IDs are referenced without a prefix — still relative to `tests/`. Tests added to one of
  these existing top-level suites keep the file's unprefixed form (e.g. the S18
  `test_run_population::test_oe_display_prefers_combined_score`). A **new** top-level file is
  admissible only when its CI marker must diverge from the directory convention (e.g. the S18
  `test_doc_command_lint`, a `unit`-marked lint suite — see the next bullet); otherwise new L2
  suites go under `tests/integration/`.
- **Marker vs. level**: the documentary level (L1/L2/L3) classifies a test's *scope*; the pytest
  marker (`unit` / `integration` / …, §6.2) drives *CI selection*. The two usually coincide but
  may deliberately differ — e.g. the #354 doc command-lint
  (`test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_invocations_resolve`, S18) is tracked as an L2
  scenario (it exercises the real Typer CLI tree against the whole docs corpus) but runs under
  the `unit` marker so it executes in the blocking CI selection (sprint-018 S18-21). Where marker
  and level differ, the validation docs say so on the row. Note that historic top-level suites
  without any marker fall outside a marker-filtered CI selection and run via a plain
  `pytest tests/`.

**Running tests**:

```bash
# All fast tests (unit + integration)
pytest tests/unit/ tests/integration/

# Unit only
pytest tests/unit/

# Integration only
pytest tests/integration/ -m integration

# E2E with fake LLM (no GPU needed); GPU-backed runs are the manual procedure of val-e2e-tests.md
pytest tests/e2e/ -m e2e

# With coverage (what CI runs)
pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"

# Static analysis (what CI runs; mypy targets come from pyproject.toml)
ruff check src/ tests/
ruff format --check src/ tests/
mypy
```
