# DES-008: LoongFlow Evolution Backend Integration

- **Status:** Draft
- **Date:** 2026-10-22
- **Author:** Gemini CLI & admjgu
- **Traceability:** ADR-007, FR-RUN-054, NFR-MLOPS-001

---

## 1. Context & Motivation

Revolver acts as an MLOps orchestrator over LLM-guided evolution frameworks (ADR-007). While OpenEvolve and ShinkaEvolve provide population-level mutation mechanisms, **LoongFlow** (Baidu Baige Team, arXiv:2512.24077) introduces a structured cognitive paradigm: **Plan-Execute-Summarize (PES)**.

Integrating LoongFlow allows Revolver users to conduct causal reflection and structured prompt evolution while benefiting from Revolver's dataset splits, SQLite versioning, and unified benchmarking.

---

## 2. Architecture & Contracts

### 2.1 The Pluggable Contract (`EvolutionBackend`)
The `LoongFlowBackend` implements the structural protocol defined in `src/revolver/infra/backends/base.py`:
- `capabilities()`: Reports native multi-language and PES search strategy support.
- `generate_wrapper()`: Generates `_loongflow_evaluator.py` **strictly inside `spec.run_dir`** (preserving immutable `spec.snapshot_dir` invariants).
- `launch()`: Instantiates native `loongflow.framework.evolve.context.EvolveChainConfig` and `loongflow.framework.evolve.evolve_agent.EvolveAgent`.

### 2.2 Invariant Guarantees (MLOps Safety)
1. **Snapshot Immutability:** No file writes may touch `spec.snapshot_dir` during evaluation or runtime generation. All execution outputs and wrappers are written to `spec.run_dir / "loongflow-output"`.
2. **Evaluator Contract:** The generated wrapper must expose `evaluate_instance(instance_data)` to satisfy Revolver's pre-flight evaluation checks.
3. **Token Accounting:** If `wants_http_proxy()` is `True`, all HTTP calls from `litellm` (used by LoongFlow) are directed to Revolver's local token-counting proxy.
