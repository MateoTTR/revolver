# POC: OpenEvolve Integration with Instance Injection

**Date**: 2026-03-11
**Status**: Completed
**Resolves**: OQ-05 (evaluator iteration vs instance injection), OQ-06 (dataset control mechanism)
**Full report**: `/home/mathi/revolver-pocs/openevolve-integration/README.md`
**Detailed findings**: `/home/mathi/revolver-pocs/openevolve-integration/results/findings.md`

---

## Objective

Validate how Revolver can inject dataset instances into OpenEvolve's evaluation loop, given that OpenEvolve's evaluator interface accepts only `program_path` with no instance argument. Three strategies were tested across 7 scenarios.

## Test Environment

| Component | Value |
|---|---|
| OpenEvolve | 0.2.26 |
| LLM | qwen2.5-coder:7b via Ollama (localhost:11434) |
| Platform | Linux 6.6.87 (WSL2), Python 3.12.13 |

---

## Strategies Tested

| Strategy | Mechanism | Result |
|---|---|---|
| **A — Env var injection** | `REVOLVER_DATASET_DIR` set before `run_evolution()`, evaluator reads it | PASS — robust, cross-platform |
| **B — SQLite side-channel** | Evaluator writes per-instance metrics to `REVOLVER_INSTANCE_LOG` DB | PASS — zero lock errors with WAL mode, 4 parallel workers |
| **C — Callable evaluator** | Pass evaluator as callable to `run_evolution(evaluator=fn)` | PASS (fragile) — works on Linux (fork), fails on macOS (spawn) |

## Scenarios (7/7 PASS)

| # | Scenario | Key finding |
|---|---|---|
| S1 | Baseline OpenEvolve run | Works out of the box with Ollama endpoint |
| S2 | Env var propagation to workers | `os.environ` inherited by all worker processes |
| S3 | Dataset switching between runs | Changing `REVOLVER_DATASET_DIR` between runs works correctly |
| S4 | Concurrent SQLite writes (4 workers) | 50 rows, 5 PIDs, zero lock errors (WAL mode + timeout=10s) |
| S5 | Callable evaluator | Works via module attribute trick, but fork-dependent |
| S6 | Single-instance eval mode | Dual-mode evaluator pattern validated for `revolver eval` |
| S7 | Checkpoint resume with env-based dataset | Must use `OpenEvolve` controller class (not `run_evolution()`) |

---

## Decision

**Recommended strategy**: **A + B hybrid**

- **Strategy A** (env var) as core mechanism — simple, robust, cross-platform
- **Strategy B** (SQLite side-channel) as optional add-on — per-instance visibility during training
- **Strategy C** (callable) rejected — fragile, platform-dependent, relies on OpenEvolve internals

→ Formalized in [ADR-006](../architecture/adr/ADR-006-openevolve-instance-injection.md)

## Environment Variables

| Variable | Set by | Purpose |
|---|---|---|
| `REVOLVER_DATASET_DIR` | Revolver orchestrator | Path to instance directory (training mode) |
| `REVOLVER_INSTANCE_PATH` | Revolver eval/benchmark | Path to single instance file (eval mode) |
| `REVOLVER_INSTANCE_ID` | Revolver eval/benchmark | Instance filename (convenience) |
| `REVOLVER_INSTANCE_LOG` | Revolver orchestrator | Path to SQLite side-channel DB (optional) |
| `REVOLVER_EVAL_LOG` | Revolver orchestrator | Path to evaluator log file (optional) |

## Dual-Mode Evaluator Pattern

```python
def evaluate(program_path: str) -> dict[str, float]:
    instance_path = os.environ.get("REVOLVER_INSTANCE_PATH")

    if instance_path:
        # Single-instance mode (revolver eval / revolver benchmark)
        return _evaluate_one(program_path, instance_path)

    # Aggregated mode (OpenEvolve training)
    dataset_dir = os.environ["REVOLVER_DATASET_DIR"]
    instances = sorted(Path(dataset_dir).glob("*.json"))
    scores = [_evaluate_one(program_path, str(inst)) for inst in instances]
    return {"combined_score": mean(s["combined_score"] for s in scores)}
```

## Caveats

- **Logging**: `logging.basicConfig()` doesn't work in evaluators (OpenEvolve configures logging first). Use a dedicated `FileHandler` on a named logger.
- **Resume API**: `run_evolution()` doesn't support resume. Must use `OpenEvolve` controller class directly.
- **LLM quality**: Small models (7B) occasionally fail to produce valid diffs — not a strategy issue.

## Implications for Revolver

- `revolver.infra.openevolve` wrapper must use `OpenEvolve` controller class (not `run_evolution()`) for resume support
- Revolver generates the wrapper evaluator: user writes only `evaluate_instance()`, Revolver adds the dual-mode boilerplate
- `REVOLVER_INSTANCE_LOG` enables optional per-instance SQLite logging during training
- Evaluator templates should include the full dual-mode pattern with optional side-channel logging

## Follow-Up

- [x] ADR-006: Formalize A+B hybrid strategy
- [ ] DES-005: `revolver run` design (can now rely on ADR-006)
- [ ] DES-006: `revolver eval` design (can now rely on ADR-006)
- [ ] Implement wrapper evaluator generator (evaluate_instance → evaluate)
