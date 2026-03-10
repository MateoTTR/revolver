# ADR-001 — Ollama as Local LLM Backend

**Date**: 2026-03-10
**Status**: Accepted
**Deciders**: Mathi, Claude

---

## Context

Revolver needs a local LLM serving backend to run OpenEvolve evolution loops on a single workstation (WSL2, NVIDIA RTX 5090, 32 GB VRAM). The backend must:

- Serve models via an OpenAI-compatible API (for OpenEvolve integration)
- Support quantized models (to fit large models in 32 GB VRAM)
- Provide clean lifecycle management (load, unload, swap models)
- Be simple to install and operate

Two candidates were evaluated in a POC: **Ollama** and **vLLM**.

## Decision

**Ollama** is the local LLM serving backend for Revolver V1.

All local LLM operations (`revolver llm add/start/stop/status`) are implemented via the Ollama API. The Ollama binary must be installed independently by the user — Revolver detects and reports its presence via `revolver doctor` (NFR-062).

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| **Ollama** (selected) | 9x faster throughput (Q4 quantization), 4x less VRAM, single binary install, native OpenAI-compat API, clean load/unload lifecycle, no VRAM leaks | Basic multi-user serving, quantization may reduce code quality |
| **vLLM** | Excellent multi-user serving, continuous batching, fp16 precision | 4x more VRAM (only 7B fits in 32 GB at fp16), 4x slower load, complex setup (conda + pip + HF auth), OOM on 22B+ models |
| **llama.cpp (direct)** | Maximum control, no daemon needed | No OpenAI-compat API out of the box, manual model management, no lifecycle API |
| **No local backend (remote-only)** | Zero setup | Requires internet, API costs, latency, no offline use |

### POC Benchmarks (RTX 5090, 32 GB)

| Metric | Ollama (Q4_K_M) | vLLM (fp16) |
|---|---|---|
| 7B VRAM | 7.0 GB | 28.1 GB |
| 7B throughput | 232 tok/s | 26 tok/s |
| 22B VRAM | 19.4 GB | OOM |
| 22B throughput | 95 tok/s | — |
| Max model | 72B (Q4) | 7B (fp16) |
| Load time (7B) | 32s | 136s |
| Install | `curl \| sh` | conda + pip + HF auth |

## Consequences

### Positive
- Users can run evolution loops entirely offline with high throughput
- Codestral 22B (recommended) fits comfortably at 19.4 GB, leaving headroom for system
- Simple install and lifecycle: `ollama pull`, load/unload via API
- Model pinning by digest ensures reproducibility (NFR-021)
- Native OpenAI-compatible endpoint — no adapter needed for OpenEvolve

### Negative
- Dependency on external binary (not Python-installable) — user must install Ollama separately
- Q4 quantization may reduce code generation quality vs fp16 (to be validated by future POC)
- Single-user design: not suitable if Revolver ever needs multi-tenant serving

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Q4 quantization degrades code quality | Medium | Future POC (backlog #14); use remote APIs for quality-critical runs |
| Ollama model updates change behavior | Medium | Pin model digests in registry |
| Ollama project abandoned or incompatible | Low | llama.cpp is the underlying engine, alternative frontends exist |
| 72B+ models too slow for iterative loops | High | Recommend 7B-22B local; remote APIs for higher quality |

## References

- [POC: Local LLM Deployment](../../pocs/poc-local-llm.md) — full benchmark data
- [spec-llm.md](../../specs/spec-llm.md) — FR-LLM-001 to FR-LLM-017
- [spec-setup.md](../../specs/spec-setup.md) — FR-SET-003 (Ollama detection in `revolver doctor`)
- ConOps §3.2 (LLM Backends), §4.8 (LLM Registry)
