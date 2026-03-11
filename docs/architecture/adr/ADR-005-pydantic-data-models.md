# ADR-005 — Pydantic for Data Models

**Date**: 2026-03-11
**Status**: Accepted
**Deciders**: Project team

---

## Context

Revolver needs shared data models (`revolver.models`) used across all three layers (CLI, Domain, Infrastructure). These models represent LLM entries, solutions, evaluation results, dataset registrations, etc.

Key requirements for these models:
- **Serialization**: JSON output (`--json` flag, NFR-003) and YAML manifests require easy dict/JSON conversion
- **Validation**: data coming from SQLite queries, CLI arguments, and YAML files needs type checking and constraint enforcement
- **Immutability**: many entities (snapshots, lineage records) must be immutable after creation
- **Clarity**: models are the shared vocabulary between layers — they must be self-documenting

The two main options in the Python ecosystem are `dataclasses` (stdlib) and `Pydantic` (third-party).

## Decision

Use **Pydantic v2** (`pydantic >= 2.0`) for all shared data models in `revolver.models`.

Models will use `BaseModel` with `model_config = ConfigDict(frozen=True)` for immutable entities.

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| **dataclasses (stdlib)** | Zero dependencies, simple, familiar | No built-in validation, manual JSON/dict conversion, no frozen+default_factory combo, manual `__post_init__` for constraints |
| **Pydantic v2** | Built-in validation, `model_dump()`/`model_validate()`, JSON schema generation, frozen models, excellent error messages | Extra dependency (~2 MB), learning curve for team unfamiliar with Pydantic |
| **attrs** | Similar to dataclasses but more powerful, validators, frozen | Less ecosystem adoption than Pydantic, no native JSON schema, still needs manual serialization |

## Consequences

### Positive
- `model_dump()` and `model_dump_json()` eliminate boilerplate for `--json` output
- `model_validate()` provides safe construction from dicts (SQLite rows, YAML parsed data)
- Field validators enforce constraints at construction time (e.g., `source IN ('local', 'remote')`)
- `frozen=True` enforces immutability at runtime for snapshot/lineage models
- Pydantic v2 is compiled (Rust core), with negligible performance overhead for our scale
- Widely adopted in the Python ecosystem — good documentation and community support

### Negative
- Adds one third-party dependency to the project
- Team members unfamiliar with Pydantic need to learn the v2 API

### Risks
- Pydantic v2 breaking changes vs v1: mitigated by pinning `pydantic >= 2.0, < 3.0`
- Over-validation: risk of adding too many validators. Mitigation: validate only at system boundaries (DB reads, CLI input, YAML parsing), not between internal layers

## References

- [Architecture Overview §4.4](../architecture.md) — pending decision on data models
- [DES-001 — SQLite Data Model](../design/DES-001-sqlite-data-model.md) — defines the entities to model
- [Specifications NFR-003](../../specs/specifications.md) — JSON output requirement
- [Pydantic v2 documentation](https://docs.pydantic.dev/latest/)
