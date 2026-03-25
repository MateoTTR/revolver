# Revolver — End-to-End Tests (Level 3)

**Version**: 0.1 — Initial draft
**Date**: 2026-03-13
**Status**: Draft
**Traceable to**: [Validation Overview](validation.md), [User Story E2E](../specs/user-story-e2e.md)

---

## 1. Scope

E2E tests validate complete user workflows from CLI input to final output. Unlike integration tests (Level 2), they exercise the full stack including LLM interaction — either via a fake server or a real Ollama instance.

---

## 1.1 Test Level Comparison

| Aspect | L2 (Integration) | L2-OE (OpenEvolve Contract) | L3 (E2E) |
|---|---|---|---|
| **OpenEvolve** | Mocked at `infra` boundary | Real classes (`Config`, `Controller`) | Real + running LLM |
| **LLM** | Mocked | Not called (dummy API key) | Fake server or real Ollama |
| **GPU** | Not needed | Not needed | Optional (Ollama) |
| **External deps** | SQLite, filesystem | openevolve (pip) | Ollama, network |
| **CI trigger** | Every push + PR | Every PR (non-blocking) | Nightly / manual |
| **Speed** | ~seconds | ~seconds | ~minutes to hours |
| **What it catches** | CLI command logic, DB state | Field mapping bugs (dacite), constructor crashes | Full workflow regressions |

---

## 2. LLM Mocking Strategy

A key challenge for CI is that real LLM inference requires either a GPU (for Ollama) or API costs (for remote LLMs). The strategy differs by test level.

### 2.1 Level 1 + 2 (recap): fully mocked

External services are mocked at the `revolver.infra` boundary. No LLM, no GPU, no network. See [validation.md §6.3](validation.md) for shared fixture details.

### 2.2 Level 3: fake LLM server

For E2E tests in CI, a lightweight **fake OpenAI-compatible server** replaces a real LLM:

```
tests/fixtures/fake_llm_server.py
```

This server:
- Exposes `POST /v1/chat/completions` (OpenAI-compatible)
- Returns valid Python code (pre-defined, deterministic responses)
- Includes `usage.prompt_tokens` / `usage.completion_tokens` in responses
- Simulates realistic latency (~100ms per request)
- Starts as a pytest fixture (`fake_llm_server`) on a random port

Revolver registers it as:
```bash
revolver llm add fake-llm --provider openai-compat --base-url http://localhost:<port>/v1
```

This validates the entire chain (CLI → token proxy → "LLM" → OpenEvolve → evaluation) without a real model.

### 2.3 Response behavior

The fake server returns different responses based on the request content:

| Request context | Response |
|---|---|
| Code generation (contains `EVOLVE-BLOCK`) | Pre-defined Python function with minor variation |
| System prompt / planning | Generic acknowledgment response |
| Any request | Includes `usage: {prompt_tokens: 150, completion_tokens: 50}` |

The responses must produce valid Python that the evaluator can execute. Pre-defined responses are stored alongside the server fixture.

### 2.4 Variants by environment

| Environment | LLM backend | Marker | CI trigger |
|---|---|---|---|
| CI (standard runner) | Fake LLM server | `@pytest.mark.e2e` | Nightly |
| CI (self-hosted + GPU) | Ollama + micro-model (`qwen2.5-coder:0.5b`) | `@pytest.mark.e2e_gpu` | Manual |
| Developer workstation | Ollama + any model | `@pytest.mark.e2e_gpu` | Manual |

---

## 3. Scenarios

### 3.1 Scenario 1 — Alice / Job-Shop Scheduling

Derived from [user-story-e2e.md](../specs/user-story-e2e.md). Tests the canonical workflow end-to-end.

**Steps**:

| # | Command | Assertion |
|---|---|---|
| 1 | `revolver doctor` | Exit code 0, all checks pass |
| 2 | `revolver llm add fake-llm --provider openai-compat --base-url ...` | LLM registered |
| 3 | `revolver project init e2e-scheduling --description "E2E test"` | Project structure created |
| 4 | Copy test evaluator + initial_program + instances into project | Files in place |
| 5 | `revolver problem test --instance instances/instance_001.json` | Metrics returned, exit 0 |
| 6 | `revolver problem test --dataset instances/` | 3/3 passed |
| 7 | `revolver problem version create --tag v1.0 --message "E2E test version"` | Snapshot created, hash computed |
| 8 | `revolver dataset add e2e-train --path instances/ --split train --compatible-with v1.0` | Dataset registered, 3 instances |
| 9 | `revolver dataset add e2e-eval --path instances/ --split eval --compatible-with v1.0` | Second dataset registered |
| 10 | `revolver run --version v1.0 --llm fake-llm --dataset e2e-train --iterations 2 --alias e2e-run` | Run completes, solution created, tokens tracked |
| 11 | `revolver solution list` | Solution listed with alias |
| 12 | `revolver eval --solution e2e-run --dataset e2e-eval` | Per-instance results stored |
| 13 | `revolver eval results --solution e2e-run --dataset e2e-eval` | Results displayed |
| 14 | `revolver benchmark --solutions e2e-run --dataset e2e-eval --alias e2e-bench` | Benchmark created (single solution) |
| 15 | `revolver benchmark export --latest --format csv --output /tmp/e2e.csv` | Valid CSV file |
| 16 | `revolver benchmark export --latest --format json --output /tmp/e2e.json` | Valid JSON file |

**Adaptations vs the user story**:
- Fake LLM server instead of Codestral/Claude (no GPU, no API costs)
- 2 iterations instead of 100
- Tiny dataset (3 instances)
- Single LLM only

**FRs covered**: FR-SET-001..005, FR-LLM-001/010/016, FR-PRJ-001..006, FR-PRB-001..009, FR-DAT-001..007, FR-RUN-001..012/028/029, FR-SOL-001..008, FR-EVL-001..007/015..017, FR-BEN-001..009

**With real Ollama** (`@pytest.mark.e2e_gpu`):
- Step 2 becomes: `revolver llm add test-model --source ollama --model qwen2.5-coder:0.5b --pull`
- Add `revolver llm start test-model` before step 10
- Add `revolver llm stop` after step 10

### 3.2 Scenario 2 — Remote-Only Workflow

A scenario validating Revolver behavior without Ollama or GPU. Defined during Phase 5, it will cover:

- Remote LLM only (fake server registered as `--provider openai-compat`)
- Token tracking with pricing (`--input-cost 10.0 --output-cost 30.0`)
- Estimated cost displayed in run output
- Graceful degradation: `revolver doctor` reports Ollama/GPU as WARN, not FAIL
- `revolver llm status` shows remote LLM as `ready`

**FRs covered**: FR-LLM-001/015/017/018, FR-RUN-015/028..030, NFR-043, NFR-067

**CI suitability**: runs on any runner (no GPU required).

---

## 4. Conventions

- **File layout**:
  ```
  tests/e2e/
  ├── test_alice_jobshop.py     # Scenario 1 (fake LLM + optional real Ollama)
  └── test_remote_only.py       # Scenario 2 (TBD in Phase 5)
  ```
- **Markers**:
  - `@pytest.mark.e2e` — runs with fake LLM server (no GPU)
  - `@pytest.mark.e2e_gpu` — runs with real Ollama + GPU
  - `@pytest.mark.slow` — always applied to E2E tests
- **Not blocking CI on push** — runs nightly or on manual trigger only
- **Cleanup**: each scenario creates its project in `tmp_path` and cleans up on exit
- **Assertions**: verify final state (DB contents, exported files, exit codes), not intermediate output formatting
