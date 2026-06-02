# ADR-002 — Python as Implementation Language

**Date**: 2026-03-10
**Status**: Accepted
**Deciders**: Mathi, Claude

---

## Context

Revolver needs a primary implementation language. The choice impacts development speed, ecosystem compatibility, distribution model, and maintenance effort. Key constraints:

- OpenEvolve (the core evolution engine) is written in Python
- User evaluators are Python scripts (`evaluator.py`)
- The target audience (ML engineers, researchers) predominantly uses Python
- Revolver must be installable via `pip install` (NFR-060)

## Decision

**Python** (>= 3.12) is the implementation language for Revolver V1.

Python 3.12 is chosen as the minimum version for:
- Significant performance improvements over earlier 3.x releases
- `tomllib` in stdlib (useful for pyproject.toml parsing)
- Exception groups and `TaskGroup` (for future parallel evaluation)
- Cleaner typing (no `unused-ignore` workarounds needed under mypy)
- Broad availability (Ubuntu 24.04, current Homebrew, conda)

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| **Python** (selected) | Native OpenEvolve integration (import, not subprocess), same language as user evaluators, rich ML/data ecosystem (numpy, pandas), mature CLI frameworks (Typer, Click), fast prototyping, pip-installable | ~200ms CLI startup, no single-binary distribution, weaker type safety than compiled languages |
| **Rust** | Fast CLI startup (~5ms), single binary, strong type safety, excellent error handling | No OpenEvolve integration (would need subprocess/IPC), different language from user evaluators, slower development, steeper learning curve |
| **Go** | Fast CLI startup, single binary, good concurrency | Same OpenEvolve integration issue as Rust, weaker ML ecosystem, no generics until recently |
| **Mixed (Rust CLI + Python core)** | Best of both: fast CLI, native OpenEvolve integration | Two languages to maintain, complex build pipeline, FFI overhead, harder to contribute |

## Consequences

### Positive
- **Direct OpenEvolve integration**: import OpenEvolve as a library, configure programmatically, access internal state for progress monitoring — no subprocess orchestration needed
- **Evaluator compatibility**: Revolver can import and call user evaluators directly (same process), enabling better error reporting, timeout enforcement, and metrics collection
- **Ecosystem**: SQLite via stdlib, YAML via PyYAML, HTTP via httpx, hashing via hashlib — minimal external dependencies for core functionality
- **Distribution**: standard `pip install revolver` workflow, familiar to target users
- **Development speed**: rapid iteration, easy testing, no compilation step

### Negative
- **CLI startup**: ~200ms cold start (well within NFR-030's 2s limit, but noticeable vs compiled CLIs)
- **No single binary**: users need a Python >= 3.12 installation (mitigated by pipx/uv for isolated installs)
- **Type safety**: runtime type errors possible (mitigated by strict mypy/pyright in CI)

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| CLI startup perceived as slow | Low | 200ms is acceptable; can use lazy imports to reduce further |
| Python version availability | Low | 3.12 is widely available (Ubuntu 24.04, Homebrew, conda); document in prerequisites |
| Dependency conflicts with user environment | Medium | Recommend pipx or uv for isolated installation (NFR-060) |

## References

- [ADR-001](ADR-001-ollama-local-llm-backend.md) — Ollama backend (also accessed via Python httpx/requests)
- [spec-setup.md](../../specs/spec-setup.md) — NFR-060 (pip-installable)
- [spec-eval.md](../../specs/spec-eval.md) — Evaluator integration (direct Python import)
- OpenEvolve repository — Python package
