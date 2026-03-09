# POC: Local LLM Deployment — Ollama vs vLLM

**Date**: 2026-03-09
**Status**: Completed
**Resolves**: OQ-01 (local LLM backend), OQ-08 (WSL2 + RTX 5090 compatibility)
**Full report**: `/home/mathi/revolver-pocs/local-llm/README.md`

---

## Objective

Validate local LLM deployment on a single workstation (WSL2, NVIDIA RTX 5090, 32 GB VRAM) and select between Ollama and vLLM as the serving backend for Revolver.

## Test Environment

| Component | Value |
|---|---|
| GPU | NVIDIA RTX 5090 (32 GB VRAM, Blackwell, compute cap 12.0) |
| Driver | 595.71 (Windows-side, forwarded to WSL2 via GPU-PV) |
| CUDA | 13.2 runtime (no toolkit install needed in WSL2) |
| OS | WSL2 (Linux 6.6.87.2-microsoft-standard-WSL2) |

---

## Results Summary

### Ollama — Inference Performance

Prompt: A* pathfinding implementation, 512 generated tokens, 3 runs averaged.

| Model | Params | Quant | VRAM | TTFT | Throughput | OpenAI API |
|---|---|---|---|---|---|---|
| qwen2.5-coder:7b | 7B | Q4_K_M | 7.0 GB | 70ms | **232 tok/s** | OK |
| codestral:22b | 22B | Q4_K_M | 19.4 GB | 30ms | **95 tok/s** | OK |
| qwen2.5:72b | 72.7B | Q4_K_M | 23.7 GB | 630ms | **1.9 tok/s** | OK |

### vLLM — Inference Performance

| Model | Params | Precision | VRAM | Throughput | Status |
|---|---|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct | 7B | fp16 | 28.1 GB | **26 tok/s** | OK |
| Codestral-22B-v0.1 | 22B | fp16 | >32 GB | — | **OOM** |

### Head-to-Head (7B Model)

| Metric | Ollama (Q4_K_M) | vLLM (fp16) | Winner |
|---|---|---|---|
| VRAM | 7.0 GB | 28.1 GB | **Ollama** (4x less) |
| Load time | 32s | 136s | **Ollama** (4x faster) |
| Throughput | 232 tok/s | 26 tok/s | **Ollama** (9x faster) |
| Max model on 32 GB | 72B (Q4) | 7B (fp16) | **Ollama** |
| Setup | `curl \| sh` + `pull` | conda + pip + HF auth | **Ollama** |
| Multi-user serving | Basic | Excellent | vLLM |

### Ollama — Lifecycle Management

| Test | Result |
|---|---|
| VRAM freed after unload | Full recovery, no leak |
| Model swap 7B ↔ 22B | 2.6 – 3.1s |
| Model swap 7B ↔ 72B | 7.9 – 40.0s |
| VRAM leak (5 load/unload cycles) | None detected |

---

## Decision

**Ollama** is selected as the local LLM backend for Revolver V1.

| Factor | Rationale |
|---|---|
| Performance | 9x faster throughput via Q4 quantization |
| VRAM efficiency | Fits 72B on 32 GB; vLLM can only fit 7B |
| Simplicity | Single binary, no Python env, no HF auth |
| Lifecycle | Clean load/unload/swap API, no VRAM leaks |
| OpenAI compat | Native `/v1/chat/completions`, direct OpenEvolve integration |

**vLLM** is not recommended for V1 but remains relevant for future multi-user serving scenarios.

### Recommended Model Tiers

| Tier | Example | VRAM | Throughput | Use Case |
|---|---|---|---|---|
| Fast / dev | qwen2.5-coder:7b | 7 GB | 232 tok/s | Quick iterations, testing |
| **Balanced** | codestral:22b | 20 GB | 95 tok/s | **Production runs** — best quality/speed tradeoff |
| Quality | Remote API (Claude, GPT-4) | — | — | When local quality insufficient |

72B-class models (1.9 tok/s) are impractical for iterative OpenEvolve evolution loops.

---

## Implications for Revolver

### `revolver llm` Subcommand Mapping

| Revolver Command | Ollama Implementation |
|---|---|
| `revolver llm add --source ollama` | `ollama pull <model>` |
| `revolver llm start <name>` | Load via `POST /api/generate` (first call) |
| `revolver llm stop <name>` | Unload via `POST /api/generate` with `keep_alive: 0` |
| `revolver llm status` | `GET /api/ps` (loaded models + VRAM) |
| `revolver llm list` | `ollama list` / local registry |
| OpenEvolve integration | `http://localhost:11434/v1` as OpenAI base URL |

### VRAM Management (V1)

- Single model at a time (ConOps §3.3 concurrency model confirmed)
- Unload current model before loading a new one (swap: 2-40s)
- Expose VRAM usage via `nvidia-smi` + Ollama `/api/ps`
- Warn user if requested model exceeds available VRAM

### Model Registry (`~/.revolver/llms/`)

- Store Ollama model name + tag (e.g., `codestral:22b`)
- Pin digest for reproducibility (`@sha256:...`)
- Record VRAM footprint and measured throughput

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| 72B+ models too slow for iterative runs | High | Recommend 7B-22B local; use remote APIs for higher quality |
| Q4 quantization may degrade code generation quality | Medium | Future POC: compare quality across quantization levels with OpenEvolve |
| Ollama model updates may change behavior | Medium | Pin model digests in registry |
| WSL2 VRAM monitoring discrepancy with Windows tools | Low | Always use `nvidia-smi` in WSL2 |

---

## Follow-Up Tasks

- [ ] Create ADR-001: Ollama as local LLM backend (backlog #5)
- [ ] Design `revolver llm` subcommands (backlog #8)
- [ ] POC: Code generation quality with OpenEvolve + local LLM (backlog #14)
- [ ] POC: End-to-end OpenEvolve + Ollama integration (backlog #15)

## Artifacts

Full benchmark scripts and raw data are in `/home/mathi/revolver-pocs/local-llm/`:
`bench_ollama.py`, `bench_vllm.py`, `bench_lifecycle.py`, `ollama_results.json`, `vllm_results.json`, `lifecycle_results.json`
