# POC: OpenEvolve + Claude API (Anthropic)

**Date**: 2026-03-13
**Status**: Completed
**Resolves**: Validation that OpenEvolve works with cloud LLM APIs (Anthropic Claude) via the OpenAI-compatible endpoint
**Full report**: kept in a private POC repository (this document is the summary)
**Handoff prompt**: private POC repository

---

## Objective

Validate that OpenEvolve (v0.2.26) works with Anthropic's Claude API through its OpenAI-compatible endpoint, without any code changes or adapters. Compare solution quality and cost against local models (Ollama).

## Test Environment

| Component | Value |
|---|---|
| OpenEvolve | 0.2.26 |
| LLM (cloud) | Claude Sonnet 4.6, Claude Haiku 4.5 via `https://api.anthropic.com/v1/` |
| LLM (local) | qwen2.5-coder:7b, codestral:22b via Ollama |
| Platform | Linux 6.6.87 (WSL2), Python 3.12.13 |

---

## Scenarios (7/7 PASS)

| # | Scenario | Key finding |
|---|---|---|
| S1 | Sonnet basic (10 iter) | All HTTP 200, 100% correctness, best score 0.861 |
| S2 | Haiku basic (10 iter) | Faster but lower quality (0.749) |
| S3 | Config parity | Only `name`, `api_base`, `api_key` differ from Ollama config |
| S4 | Extended thinking | `reasoning_effort: "high"` silently ignored — no error, no benefit |
| S5 | Ensemble Sonnet+Haiku | Both models sampled per weighted distribution — works |
| S6 | Quality comparison (20 iter) | 3-model head-to-head (see below) |
| S7 | Cost tracking | ~$0.33 total for entire POC (57 API calls) |

---

## Key Finding: Zero-Code Integration

OpenEvolve works out of the box with Claude API. Switching between providers requires changing only 3 YAML fields:

```yaml
# Anthropic
- name: "claude-sonnet-4-6"
  api_base: "https://api.anthropic.com/v1/"
  api_key: "${ANTHROPIC_API_KEY}"

# Ollama (local)
- name: "qwen2.5-coder:7b"
  api_base: "http://localhost:11434/v1"
  api_key: "ollama"

# OpenAI
- name: "gpt-4o"
  api_base: "https://api.openai.com/v1"
  api_key: "${OPENAI_API_KEY}"

# Google AI Studio
- name: "gemini-2.0-flash"
  api_base: "https://generativelanguage.googleapis.com/v1beta/openai/"
  api_key: "${GOOGLE_API_KEY}"
```

This means Revolver does **not** need provider-specific code. The CLI just generates the right YAML config.

---

## Quality Comparison (S6 — 20 iterations each)

| Model | Best Score | Best Speedup | Time/iter | Cost/iter |
|---|---|---|---|---|
| **Claude Sonnet 4.6** | **0.867** | **0.56x** | 6.9s | ~$0.008 |
| Qwen 2.5 Coder 7B | 0.842 | 0.47x | 3.2s | $0 (local) |
| Codestral 22B | 0.744 | 0.15x | 8.4s | $0 (local) |

- Sonnet dominates in quality — produces quicksort/mergesort from iteration 1
- Qwen 7B surprisingly competitive for a 7B model
- Codestral 22B struggles with OpenEvolve's SEARCH/REPLACE diff format
- Gap will likely widen on complex problems

---

## Cost Analysis

| Metric | Value |
|---|---|
| Total POC cost | **~$0.33** (57 API calls) |
| Sonnet cost/iteration | ~$0.008 |
| Estimated 100-iter run (Sonnet) | $0.80–1.50 |

Pricing: Sonnet $3/$15 per M tokens (input/output), Haiku $0.80/$4 per M tokens.

---

## Decision

**No adapter needed** — OpenEvolve handles all providers natively via its `OpenAILLM` class. Revolver's `revolver.infra.openevolve` wrapper generates YAML configs with the right `api_base`/`api_key`/`name` based on user's provider settings. This is config-only switching.

---

## Limitations Discovered

| Limitation | Severity | Impact on Revolver |
|---|---|---|
| Anthropic endpoint "not production-recommended" | Medium | Monitor for deprecation; native Messages API adapter as fallback plan |
| No prompt caching (requires native API) | Low | Prompts are small; ~20% savings on long runs |
| `seed` parameter silently ignored | Low | Reproducibility already limited in evolutionary search |
| `reasoning_effort` has no effect | Low | Extended thinking requires native API; not critical |
| OpenEvolve does NOT track token usage | Medium | Revolver should fill this gap (new requirement) |
| Temperature capped at 1.0 | Low | OpenEvolve uses 0.8 — within range |

---

## New Concerns Raised for Revolver

These items are **not currently in our specs or design docs** and need triage:

1. **Token/cost tracking** — OpenEvolve doesn't log `usage.prompt_tokens`/`usage.completion_tokens`. Revolver should intercept API responses or query billing APIs.
2. **Provider presets** — `revolver init` could offer presets (anthropic, ollama, openai, google) that populate config templates.
3. **Ensemble CLI support** — Mix cloud + local models in a single run (e.g., `--models sonnet:0.7,haiku:0.3`).
4. **Problem description enrichment** — Structured `problem.md` injected into OpenEvolve system prompt to give the LLM domain knowledge beyond code/metrics.

→ See backlog for triage status.

---

## Implications for Revolver Architecture

- **`revolver.infra.openevolve`**: No provider-specific logic needed. Config-only switching confirmed.
- **`revolver.toml`**: Provider config is just `api_base` + `api_key_env` + `default_model` per provider.
- **DES-005 (run)**: No structural change needed — already supports `api_key` and `base_url` in YAML generation.
- **ADR-006**: Confirmed — env var injection works identically with cloud and local LLMs.

## Artifacts

Full benchmark scripts, configs, and results are kept in a private POC repository:
`run_scenario.py`, `measure_tokens.py`, `config_claude_*.yaml`, `config_s6_*.yaml`, `results/S*.json`, `output/S*_*/`
