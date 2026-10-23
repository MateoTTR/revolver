# DES-009: Agentic Multi-Agent Optimization Backend

- **Status:** Draft
- **Date:** 2026-10-22
- **Author:** Jonathan Guerra & Gemini CLI
- **Traceability:** ADR-007, FR-RUN-054, NFR-MLOPS-001

---

## 1. Context & Motivation

Traditional evolutionary backends in Revolver (OpenEvolve, ShinkaEvolve, LoongFlow) optimize heuristics through stochastic genetic variations (mutations/crossovers/islands) across populations. While effective for continuous exploration, they lack interactive test-driven debugging.

The **Agentic Backend** introduces an interactive **REPL (Read-Eval-Print-Loop) optimization loop** with autonomous **Multi-Agent Tool Delegation**. Instead of blind mutations, an autonomous Lead Architect analyzes runtime error traces and constraint violations, iteratively repairing code proposals while preserving token context through modular sub-agent delegation.

---

## 2. Architecture & Contracts

### 2.1 Pluggable Contract (`EvolutionBackend`)
The `AgenticBackend` satisfies the structural protocol defined in `src/revolver/infra/backends/base.py`:
- `capabilities()`: Declares `ensemble_model="none"`, `map_elites_cells=False`, `native_cost_tracking=True`, and strategy `("conversational",)`.
- `generate_wrapper()`: Generates `_agentic_evaluator.py` **strictly inside `spec.run_dir / "agentic-output"`** (preserving the immutable `spec.snapshot_dir` invariant).
- `launch()`: Conducts the conversational loop with LiteLLM, maintaining the message history while routing sub-agent requests.

### 2.2 Multi-Agent Delegation Mechanism
1. **Lead Architect:** The primary agent receives the problem formulation, baseline code, and evaluator instructions.
2. **Specialist Tool Calling:** The Architect is equipped with `delegate_to_specialist(subtask_description)`. When invoked, a secondary LLM session is spawned with a fresh scratchpad to implement the modular subroutine.
3. **Synthesis & Validation:** The output is returned as a tool response to the Architect, who synthesizes the final `solve(data)` script for evaluation.
4. **Conversational Feedback:** The sandboxed evaluator executes the solution. If constraints are violated (e.g., memory overflow or collision), the exact traceback/metrics are fed back as the user critique in the next turn.

### 2.3 MLOps Safety Invariants
1. **Snapshot Immutability (NFR-MLOPS-001):** Neither `generate_wrapper()` nor `resume()` may mutate `spec.snapshot_dir`. The snapshot's SHA-256 manifest remains strictly read-only.
2. **Evaluator Contract:** The generated wrapper exposes `evaluate_instance(instance_data)` to satisfy Revolver's pre-flight verification checks.
3. **Token Accounting:** All LLM calls transit through Revolver's token-counting proxy (`wants_http_proxy=True`) to report prompt/completion token usage accurately for Pareto benchmark comparisons.
