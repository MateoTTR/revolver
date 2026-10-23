# Revolver — Validation Overview

**Version**: 0.4 — v0.19.0 pre-release validation review: §6.3 shared-fixture table and §8 directory tree redrawn from the test tree, §6.4 doc guards described, CI gate names the four required checks, §8.1 marker-vs-level rule tightened, command count (§3) from the CLI-tree walker. Previous: 0.3 — Tooling sections aligned with `pyproject.toml` and `ci.yml`; `--strict-markers`; `e2e_gpu` reserved (S19-27, ADR-008)
**Date**: 2026-10-24
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
axis. **Engine-neutral** tests (39 of the 47 invocable commands counted by the
`revolver.cli._tree` walker at v0.19.0 — `llm` incl. `llm ensemble` (12), `dataset` (5),
`solution` (8), `eval` + `eval results`, `benchmark` + its 4 subcommands,
`problem test` / `version list` / `version delete`, `run list/info/delete/cleanup`) run **once** —
they do not depend on the engine. **Engine-coupled** tests (the other 8: `run` launch,
`run resume`, `run status` active-path, `run population`, plus the `doctor` / `setup` /
`project init` / `problem version create` shims) are **parameterized per backend**: the existing
matrices stay as-is for OpenEvolve, with a ShinkaEvolve variant since S14. Each backend keeps a
dedicated contract-test track (L2-OE, L2-Shinka). The 47 commands are the 44 leaf commands
(including the top-level `doctor` and `setup`) plus the three groups that run directly (`run`,
`eval`, `benchmark`) — [val-integration-tests.md §1](val-integration-tests.md).

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
- **Fixtures**: shared fixtures live in `tests/conftest.py` (`tmp_project`, `no_shinka`) and, for L3, `tests/e2e/conftest.py` (`fake_llm_server`); there is no `tests/unit/conftest.py` — see §6.3
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
    "e2e_gpu: L3 end-to-end tests against a real Ollama + GPU (manual only; reserved, no test uses it yet)",
    "slow: long-running tests (always applied to E2E tests)",
]
```

- `-m 'not e2e'` deselects the L3 E2E tests by default (they are manual — [val-e2e-tests.md](val-e2e-tests.md)), so a plain `pytest tests/` never runs them even with the engine extras installed; run them explicitly with `-m e2e`.
- `--strict-markers` (adopted at v0.19.0, S19-27) turns an unregistered `@pytest.mark.<name>` into a collection error instead of a warning, so every marker — including the per-backend engine markers — must be registered in the list above. The full suite was verified to collect cleanly under the flag before adoption.
- The `e2e_gpu` marker is registered for the manual GPU track (real Ollama + GPU, see [val-e2e-tests.md](val-e2e-tests.md)); no test uses it yet. Under `--strict-markers` only registered markers are accepted.

### 6.3 Shared Fixtures

Shared fixtures are deliberately few:

| Fixture | Scope | Defined in | Provides |
|---|---|---|---|
| `tmp_project` | function | `tests/conftest.py` | `tmp_path` with an initialized `.revolver/` store (`init_project_store`). Suites that need the project DB or the template files define a local `tmp_project` that shadows it (e.g. `tests/test_core_run.py`, `tests/test_run_delete.py`, `tests/integration/test_run.py`, `tests/integration/test_solution.py`) |
| `no_shinka` | function | `tests/conftest.py` | Makes `shinka` (and `shinka.core` / `.database` / `.launch`) un-importable via `sys.modules[...] = None`, so "shinka not installed" tests pass identically with or without the `[shinka]` extra |
| `fake_llm_server` | function | `tests/e2e/conftest.py` | A started `tests.fixtures.fake_llm_server.FakeLLMServer` on a random port (OpenAI-compatible `/v1/chat/completions` plus the minimal Ollama endpoints), stopped on teardown; tests script replies via `response_content` (L3 only) |

There is no shared CLI-runner or database fixture. L2 suites instantiate `typer.testing.CliRunner()` at module level. Ollama, OpenEvolve, ShinkaEvolve and HTTP are mocked inside each module with `unittest.mock.patch` at the `revolver.infra` / `revolver.core.run` seams (the Ollama client at its `revolver.cli.llm.OllamaClient` import site). Test data lives in `tests/fixtures/` and is referenced by path.

### 6.4 CI Pipeline

```
push / PR — ci.yml (no path filters: every job is a required status check under the branch rulesets,
                    and a required check that never runs would leave the PR stuck on "Expected"):
  ├── Lint (ruff + mypy): ruff check + ruff format --check + mypy (strict via pyproject)
  ├── Test (pytest + coverage): pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"  (Python 3.12 + 3.14 matrix)
  │     └── pip install "openevolve>=0.2.26" && pytest tests/integration/test_run_oe.py  (3.12 only, non-blocking)
  └── Doc command-lint (fenced CLI invocations): pytest tests/unit/test_doc_command_lint.py tests/unit/test_doc_freshness.py
        (#354 command-lint + #355 freshness stamps, blocking; formerly the separate doc-lint.yml workflow)

tag push (v*) — ci.yml version-check:
  └── tag == pyproject.toml version == src/revolver/__init__.py __version__

manual (no dedicated workflow yet — run by hand on a developer machine):
  ├── pytest tests/e2e/ -m e2e  (fake LLM server, no GPU)
  └── the GPU-backed E2E scenarios of val-e2e-tests.md against a local Ollama (`e2e_gpu`, manual; no test uses it yet)
```

**CI gate**: the four required checks (`Lint (ruff + mypy)`, `Test (pytest + coverage) (3.12)`, `Test (pytest + coverage) (3.14)`, `Doc command-lint (fenced CLI invocations)`) produced by the three push/PR jobs (Level 0 + 1 + 2 and the doc guards) are the required status checks for merge, on docs-only and code-only changes alike. L2-OE and E2E failures are reported but do not block.

**Doc guards** (the `Doc command-lint` job; both modules are `unit`-marked, so they also run in the main test job):

- `tests/unit/test_doc_command_lint.py` — **command-lint**: every *line-initial* `revolver` invocation inside a fenced block of the documentation corpus must resolve against the real Typer CLI tree (`revolver.cli._tree`: subcommands, flags, positional-argument caps; untagged fences parsed; inline-prose mentions out of scope). The corpus is the root files `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CLAUDE.md`, `GEMINI.md` (`ROOT_DOC_FILES`) plus `docs/**/*.md`; `CHANGELOG.md` is excluded because its entries quote historical flags. `unit/test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_includes_contributor_docs` pins that composition: every *tracked* root `*.md` is either linted or explicitly excluded.
- `tests/unit/test_doc_freshness.py` — **freshness**: `docs/guides/*.md` and `docs/specs/user-story-e2e.md` must open with a YAML front-matter `verified-against: vX.Y.Z` stamp at most one minor version behind `revolver.__version__`; a stamp ahead of the current version never fails; during the fresh-major window (current version `X.0.*`) stamps from major `X-1` still pass; a UTF-8 BOM before the front-matter is tolerated. Refreshing the stamps is part of the release procedure (`docs/process/release.md`).

**No Shinka job in CI**: ci.yml runs **no** ShinkaEvolve step — the main test job's `-m "unit or integration"` selection runs without the `[shinka]` extra installed (Shinka-gated modules auto-skip via `pytest.importorskip`), and only the OpenEvolve contract tests get a dedicated non-blocking step. The L2-Shinka contract suites are selected by the `-m shinkaevolve` marker (five modules carry it at v0.19.0: the three S14 contract suites `test_run_shinka.py`, `test_shinka_db.py`, `test_shinka_wrapper.py` plus the Shinka-gated tests of `tests/integration/test_solution.py` and `tests/unit/core/test_solution.py`) and run manually in a shinka-enabled environment (e.g. before a release); adding a Shinka-env CI step remains aspirational.

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
├── __init__.py
├── conftest.py                 # shared fixtures: tmp_project, no_shinka (§6.3)
├── fixtures/                   # test data, referenced by path (+ two importable factories)
│   ├── __init__.py
│   ├── config_simple.yaml
│   ├── evaluator_simple.py     # + evaluator_legacy / _instance / _both / _neither /
│   │                           #   _dualmode / _mixed_metrics.py
│   ├── initial_program_simple.py
│   ├── problem_simple.md
│   ├── instances/              # instance_001..003.json
│   ├── instance_bad.json
│   ├── fake_llm_server.py      # OpenAI-compatible fake server for L3 (val-e2e-tests.md §2.2)
│   ├── programs_sqlite.py      # ShinkaEvolve programs.sqlite factory (L2-Shinka)
│   └── shinka_evaluate_py.py   # reference Shinka evaluate.py wrapper (L2-Shinka)
├── test_*.py                   # historic L1/L2 suites, marker-classified (§8.1) — e.g.
│                               #   test_core_run.py, test_run_delete.py, test_run_population.py,
│                               #   test_project_integration.py, test_db*.py, test_models*.py
├── unit/                       # Level 1 (canonical home)
│   ├── __init__.py
│   ├── core/                   # test_<module>.py mirroring revolver.core
│   ├── infra/                  # test_<module>.py mirroring revolver.infra
│   ├── test_*.py               # flat L1 suites that predate the core/ + infra/ split — e.g.
│   │                           #   test_db_migration_v9..v14.py, test_core_benchmark.py,
│   │                           #   test_run_ensemble.py, test_doctor.py, test_setup.py
│   ├── test_doc_command_lint.py  # doc guards (§6.4): unit-marked, L2 by scope (§8.1)
│   └── test_doc_freshness.py
├── integration/                # Level 2 (canonical home); file list in val-integration-tests.md §4
│   ├── __init__.py
│   ├── test_<command>.py       # one suite per command group (+ test_ensemble.py,
│   │                           #   test_cross_cutting.py, test_workspace_detection.py, ...)
│   ├── test_run_oe.py          # L2-OE contract suite
│   └── test_run_shinka.py, test_shinka_wrapper.py, test_shinka_db.py   # L2-Shinka contract suites
└── e2e/                        # Level 3
    ├── __init__.py
    ├── conftest.py             # fake_llm_server fixture
    └── test_shinka_backend.py  # Scenario 3 — the only E2E suite in the tree; Scenarios 1/2/4/5
                                #   are planned (val-e2e-tests.md §4)
```

The `conftest.py`, `fixtures/` and `e2e/` entries and the three contract suites are exact at v0.19.0; the `test_*.py`, `unit/` and `integration/` entries are illustrative (patterns plus a few examples — `find tests -maxdepth 2` gives the current layout, and [val-integration-tests.md §4](val-integration-tests.md) lists the integration files).

### 8.1 Test ID Conventions

The validation documents ([val-integration-tests.md](val-integration-tests.md), the
[traceability matrix](traceability-matrix.md)) reference tests by an ID of the form
`<path-under-tests/>::<test_name>` — e.g. `integration/test_llm::test_llm_add_remote` or
`unit/core/test_ensemble::TestAddEnsembleMember::test_weight_sum_warning` (class-qualified when
the test is a method).

- **Canonical L2 home**: new integration suites live in `tests/integration/test_<command>.py`
  and their IDs carry the `integration/` prefix.
- **Top-level exception (historic)**: several L2 suites predate the `tests/integration/` layout
  and live in top-level `tests/test_*.py` files (e.g. `test_project_integration.py`,
  `test_core_run.py`, `test_run_delete.py`, `test_db_migration_v*.py`, `test_run_population.py`).
  Their IDs are referenced without a prefix — still relative to `tests/`. Tests added to one of
  these existing top-level suites keep the file's unprefixed form (e.g. the S18
  `test_run_population::test_oe_display_prefers_combined_score`). A **new** top-level file is
  admissible only when its CI marker must diverge from the directory convention; otherwise new
  L2 suites go under `tests/integration/` and new L1 suites under `tests/unit/`.
- **Marker vs. level**: the documentary level (L1/L2/L3) classifies a test's *scope*; the pytest
  marker (`unit` / `integration` / …, §6.2) drives *CI selection*. The two usually coincide but
  may deliberately differ — e.g. the backlog-row-354 doc command-lint
  (`unit/test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_invocations_resolve`, S18)
  is an L2-scope test (it exercises the real Typer CLI tree against the whole docs corpus) that
  lives under `tests/unit/` and runs under the `unit` marker so it executes in the blocking CI
  selection (sprint-018 S18-21). Where marker and level deliberately differ, the validation docs
  say so on the row; where they disagree without such a note, the marker is the truth and the
  row is relabelled (v0.19.0 pre-release review). A suite without any marker would fall
  outside a marker-filtered CI selection and run only via a plain `pytest tests/`; none is left:
  `test_run_population.py` and the seven suites that carried no marker (`test_db_dataset.py`,
  `test_db_problem.py`, `test_evaluator_loader.py`, `test_models_dataset.py`,
  `test_models_problem.py`, `test_store_dataset.py` — `unit`; `integration/test_shinka_shutdown.py`
  — `integration`) were marked at v0.19.0, so the CI selection now equals the full suite: without
  the engine extras both collect 1591 tests (1587 passed, 4 skipped, 0 deselected — the four skips
  are the import-gated Shinka modules `e2e/test_shinka_backend.py`,
  `integration/test_run_shinka.py`, `test_shinka_db.py` and `test_shinka_wrapper.py`).

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
