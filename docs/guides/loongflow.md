# LoongFlow Backend Guide

LoongFlow (Baidu Baige Team, arXiv:2512.24077) is an evolution backend for Revolver driven by the **Plan-Execute-Summarize (PES)** cognitive paradigm.

Unlike classical evolutionary algorithms that rely solely on random syntactic mutations, LoongFlow structures each iteration around causal diagnosis and reflective heuristic synthesis:
1. **Plan (P):** Causal analysis of current performance, diagnosing constraint bottlenecks and failure modes.
2. **Execute (E):** Synthesis of refined heuristic code followed by execution against sandboxed evaluation benchmarks.
3. **Summarize (S):** Lineage registration, tracking fitness gains, and archiving in a diversity-preserving MAP-Elites grid.

---

## Installation

LoongFlow is an opt-in extra in Revolver:

```bash
pip install -e ".[loongflow]"
```

Verify your environment:
```bash
revolver doctor
```

---

## Initializing a Project

To scaffold a project pre-configured for LoongFlow:

```bash
revolver project init my-loongflow-project --backend loongflow
cd my-loongflow-project
```

This generates a dedicated `config.yaml` with documented parameters:

```yaml
agent:
  type: "GeneralAgent"
  loop: "PES"                       # Loop strategy: Plan-Execute-Summarize
  prompt_language: "english"

memory:
  evolution_tree: true              # Track causal mutation history
  map_elites_archive: true          # Diverse grid archive
  boltzmann_selection: true         # Exploration/exploitation balance
  reflection_depth: 3               # Diagnostic traceback depth

execution:
  max_cognitive_steps: 50           # Total number of iterations
  concurrency: 1                    # Parallel candidates per step
  verification_timeout_sec: 10      # Sandbox timeout per candidate
```

---

## Running LoongFlow

```bash
# Preview configuration and generated wrapper without executing LLM calls
revolver run --backend loongflow --dry-run

# Run full optimization loop with 5 concurrent candidate proposals
revolver run --backend loongflow --llm gpt-4o --dataset training-set --parallel 5 --iterations 50
```

---

## Resuming and Checkpoints

All iteration history is continuously checkpointed under `.revolver/runs/<run_id>/loongflow-output/history.json` and `best_program.py`.

You can resume an interrupted run at any time:
```bash
revolver run --resume <run_id>
```
