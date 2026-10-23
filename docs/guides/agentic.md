---
verified-against: v0.18.0
---

# Agentic Multi-Agent Backend Guide

The **Agentic** backend in Revolver introduces conversational, test-driven optimization (*REPL loop*) with autonomous **Multi-Agent delegation via Tool Calling**.

Unlike evolutionary algorithms (OpenEvolve, ShinkaEvolve, LoongFlow) that apply stochastic mutations across populations, the Agentic backend conducts a focused dialogue between an **Architect Lead Agent** and optional **Specialist Sub-Agents**.

---

## Architecture Overview

```
                      ┌───────────────────────────────┐
                      │    Lead Architect Agent       │
                      │  (e.g., Gemini / Claude / GPT) │
                      └──────────────┬────────────────┘
                                     │
           ┌─────────────────────────┴─────────────────────────┐
           │ Tool Call: delegate_to_specialist                 │ Direct Code Proposal
           ▼                                                   ▼
┌───────────────────────────────┐               ┌───────────────────────────────┐
│     Specialist Sub-Agent      │               │   Revolver Sandboxed Wrapper  │
│ (Modular constraint solver)   │               │   `_agentic_evaluator.py`     │
└──────────────┬────────────────┘               └──────────────┬────────────────┘
               │ Returns code                                  │ Traceback / Score
               └───────────────────────► Lead Synthesizes ◄────┘
```

1. **Lead Architect:** Analyzes the problem specification and decides whether to write the code directly or delegate modular algorithmic sub-tasks.
2. **Tool Calling Delegation:** The Architect calls `delegate_to_specialist(subtask_description)` to task a specialist model (e.g. focused on a knapsack or temporal interval routine) without bloating the lead context window.
3. **Conversational Feedback:** The generated solution is tested against the evaluation benchmark. Any constraint violations or tracebacks are fed back to the Architect as a user critique for immediate repair.

---

## Configuration (`config.yaml`)

Initialize a project with:
```bash
revolver project init my-agentic-study --backend agentic
```

Generated configuration:
```yaml
agentic:
  mode: "multi_agent"               # "single" (mono-agent) or "multi_agent"
  max_turns: 15                     # Maximum debugging / reflection rounds
  temperature: 0.2                  # Low temperature for deterministic code synthesis
  specialist_model: null            # Sub-agent model (defaults to lead model)
  system_prompt: |
    You are an autonomous Principal Optimization Engineer.
    Analyze the problem specifications, decompose complex constraints, and iteratively refine
    the `solve(data)` Python entrypoint. You have access to a specialist sub-agent tool.
```

---

## Supported LLM Providers

Powered by `litellm`, the Agentic backend supports all frontier foundation models registered in Revolver:

* **Google Gemini:** `gemini/gemini-1.5-pro`, `gemini/gemini-2.0-flash`
* **Anthropic Claude:** `claude-3-5-sonnet-20241022`
* **OpenAI:** `gpt-4o`, `o3-mini`

Register your preferred model:
```bash
# Example with Gemini
revolver llm add gemini-lead --provider google --model gemini/gemini-1.5-pro --api-key-env GEMINI_API_KEY

# Run multi-agent optimization
revolver run --backend agentic --llm gemini-lead --dataset training-set --iterations 15
```
