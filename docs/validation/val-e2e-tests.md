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

This server (**implemented in S14** — stdlib-only `ThreadingHTTPServer`, no network egress possible):
- Exposes `POST /v1/chat/completions` (OpenAI-compatible, plain chat completions — no structured output)
- Exposes the minimal Ollama-native endpoints so `revolver llm add --source local` works for real
- Returns valid Python code via a configurable deterministic response (`response_content` attribute)
- Includes `usage.prompt_tokens` / `usage.completion_tokens` in responses
- No artificial latency by default (configurable if a scenario needs it)
- Starts as a pytest fixture (`fake_llm_server`) on a random port; `start()` guards against double start

Revolver registers it as:
```bash
revolver llm add fake-llm -s local --model <name> --base-url http://localhost:<port>/v1
```

This validates the entire chain (CLI → "LLM" → engine → evaluation) without a real model — including the engines' native clients (ShinkaEvolve's `local/<model>@<url>` path).

### 2.3 Response behavior

The fake server returns a configurable deterministic completion (set per test via `response_content`); every response includes a `usage` block so token accounting can be asserted. The content must produce valid Python that the evaluator can execute (Scenario 3 uses a full-rewrite response combined with `--rewrite-mode` for a stable mini-evolution).

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

### 3.3 Scenario 3 — ShinkaEvolve Backend Happy Path (**implemented — S14**, ADR-007)

`tests/e2e/test_shinka_backend.py` — a mirror of the Scenario 1 happy path on the ShinkaEvolve
backend, running the **real** `ShinkaEvolveRunner` against the fake LLM server (registered as a
local model, exercising Shinka's `local/<model>@<url>` native client path): `project init
--backend shinka` (scaffold validates cleanly) → `llm add` → `problem version create` → datasets
→ `run --backend shinka --iterations 2 --rewrite-mode` → asserts `programs/rank-1.py` exists and
is **not** the initial program, manifest + run record carry `backend: shinka`, native token
accounting > 0 (ADR-007 D2), and the engine-neutral downstream (`solution list`, `eval`,
`eval results`) works on the produced artifacts. Requires the `revolver[shinka]` extra; gated by
`@pytest.mark.e2e` (module `pytestmark`) plus `pytest.importorskip("shinka.database")` for
auto-skip when not installed (no dedicated marker). Runtime ≈ 6 s.

**FRs covered**: FR-RUN-047/048, NFR-024 (seed warning), NFR-061 (extra install), FR-SET-002
(doctor reports ShinkaEvolve availability as informational)

**CI suitability**: runs on any runner (no GPU required); non-blocking like L2-Shinka. E2E tests
are **deselected by default** (`addopts = "-m 'not e2e'"` in pyproject) — run explicitly with
`pytest -m e2e`.

---

## 4. Conventions

- **File layout**:
  ```
  tests/e2e/
  ├── test_alice_jobshop.py     # Scenario 1 (planned)
  ├── test_remote_only.py       # Scenario 2 (planned)
  └── test_shinka_backend.py    # Scenario 3 (implemented — S14, ADR-007)
  ```
- **Markers**:
  - `@pytest.mark.e2e` — runs with fake LLM server (no GPU); **deselected by default** (`addopts = "-m 'not e2e'"`), run with `pytest -m e2e`
  - `@pytest.mark.e2e_gpu` — runs with real Ollama + GPU
  - `@pytest.mark.slow` — always applied to E2E tests
- **Not blocking CI on push** — runs nightly or on manual trigger only
- **Cleanup**: each scenario creates its project in `tmp_path` and cleans up on exit
- **Assertions**: verify final state (DB contents, exported files, exit codes), not intermediate output formatting
