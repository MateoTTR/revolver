# ADR-006 — Strategy A+B Hybrid for OpenEvolve Instance Injection

**Date**: 2026-03-11
**Status**: Accepted
**Deciders**: Mathi (domain expert), Claude (architecture assistant)

---

## Context

OpenEvolve's evaluator interface accepts only `program_path` — there is no mechanism to pass dataset instances or configuration to the evaluator function. Revolver needs to:

1. **During training** (`revolver run`): tell the evaluator which dataset directory to iterate over (ConOps OQ-05)
2. **During eval/benchmark** (`revolver eval`, `revolver benchmark`): tell the evaluator which single instance to evaluate
3. **Provide per-instance visibility** during training runs for detailed metrics
4. **Support checkpoint resume** across runs with different datasets

Three strategies were evaluated in POC #12 (7 scenarios, all PASS):

- **Strategy A**: Environment variable injection (`REVOLVER_DATASET_DIR`)
- **Strategy B**: SQLite side-channel logging (`REVOLVER_INSTANCE_LOG`)
- **Strategy C**: Callable evaluator passed to `run_evolution(evaluator=fn)`

The seven scenarios covered a baseline OpenEvolve run against an Ollama endpoint, env-var propagation to the worker processes, dataset switching between runs, concurrent SQLite writes from 4 workers, the callable evaluator, the single-instance eval mode and checkpoint resume with an env-based dataset; all passed on OpenEvolve 0.2.26.

## Decision

Adopt a **hybrid A+B strategy**:

- **Strategy A** (env var injection) as the **core mechanism** for dataset injection
- **Strategy B** (SQLite side-channel) as an **optional add-on** for per-instance visibility during training
- **Strategy C** (callable) is **rejected**

### Core mechanism — Environment variables

| Variable | Set by | Mode | Purpose |
|---|---|---|---|
| `REVOLVER_DATASET_DIR` | `revolver run` | Training (aggregated) | Path to instance directory |
| `REVOLVER_INSTANCE_PATH` | `revolver eval/benchmark` | Eval (single-instance) | Path to single instance file |
| `REVOLVER_INSTANCE_ID` | `revolver eval/benchmark` | Eval (single-instance) | Instance filename (convenience) |
| `REVOLVER_INSTANCE_LOG` | `revolver run` | Training (optional) | Path to SQLite side-channel DB |
| `REVOLVER_EVAL_LOG` | `revolver run` | Training (optional) | Path to evaluator log file |

### Dual-mode evaluator pattern

The evaluator supports two modes based on which env var is set:

- **Single-instance mode**: `REVOLVER_INSTANCE_PATH` is set → evaluate one instance, return per-instance metrics
- **Aggregated mode**: Only `REVOLVER_DATASET_DIR` is set → iterate all instances, return aggregated `combined_score`

Revolver **generates the wrapper evaluator**: the user writes only `evaluate_instance(program_path, instance_path) -> dict[str, float]`, and Revolver generates the full dual-mode `evaluate(program_path)` wrapper.

### Resume API

The `revolver.infra.openevolve` wrapper must use the `OpenEvolve` controller class directly (not the high-level `run_evolution()` function), because only the controller class supports checkpoint resume:

```python
from openevolve.controller import OpenEvolve as OEController
controller = OEController(initial_program_path, evaluation_file, config, output_dir)
best = asyncio.run(controller.run(iterations=N, checkpoint_path="path/to/checkpoint"))
```

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| **Strategy A only** (env var) | Simplest, zero overhead, cross-platform | No per-instance visibility during training |
| **Strategy B only** (SQLite) | Full per-instance visibility | More boilerplate, SQLite dependency in evaluator |
| **Strategy C** (callable) | Cleanest API (no env vars) | Fork-dependent (fails on macOS spawn), relies on OpenEvolve internal module attribute trick, fragile |
| **Modify OpenEvolve** | Could add instance argument to evaluator | Upstream dependency, maintenance burden, against project constraint of not modifying OpenEvolve |

## Consequences

### Positive

- **Zero OpenEvolve modification**: works with stock OpenEvolve, no fork needed
- **Cross-platform**: `os.environ` propagation works on all platforms (Linux, macOS, Windows)
- **Simple core mechanism**: env vars are universally understood, easy to debug
- **Optional complexity**: SQLite side-channel is opt-in, not required for basic usage
- **Dual-mode evaluator**: same evaluator file works for both training and eval/benchmark
- **Generated wrapper**: user only writes domain logic (`evaluate_instance`), Revolver handles boilerplate

### Negative

- **Env var coupling**: evaluator must read specific `REVOLVER_*` variables — cannot run standalone without them
- **Generated code**: wrapper generation adds a code generation step to `revolver run`
- **SQLite in evaluator**: if side-channel is enabled, evaluator has a SQLite dependency

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Env var not propagated in future OpenEvolve versions | Low | OpenEvolve uses standard `multiprocessing` fork — env vars are inherited by default |
| SQLite locking under high parallelism (>4 workers) | Low | WAL mode + timeout=10s handles 4 workers with zero errors; retry logic is built in |
| `OpenEvolve` controller class API changes | Medium | Pin OpenEvolve version; wrapper isolates the integration point |
| Evaluator logging conflict with OpenEvolve | Low | Document: use dedicated `FileHandler` on named logger, not `basicConfig()` |

## Addendum (2026-06-11, ADR-007)

This ADR remains valid and unchanged for the OpenEvolve backend. With the pluggable-backend
abstraction ([ADR-007](ADR-007-pluggable-evolution-backend.md)), the ShinkaEvolve backend reuses
the **same inputs** — the `REVOLVER_*` env vars and the user's `evaluate_instance()` from the
problem snapshot — but its generated wrapper has a **different output shape**: a subprocess CLI
script writing `metrics.json`/`correct.json` (ShinkaEvolve's file-based evaluator contract)
instead of the in-process dual-mode `evaluate()` returning a dict. See DES-006 §1.3.

## References

- The OpenEvolve instance-injection proof of concept (former backlog row 12): the full report is kept in a private POC repository; the findings this record relies on are stated above
- [ConOps §4.4](../../conops/conops.md) — Instance Injection Mechanism
- ConOps OQ-05, OQ-06
- Architecture AQ-03
- [Specifications](../../specs/specifications.md) — FR-RUN-*, FR-EVL-*
