# DES-002 — `revolver llm` Subcommands — Ollama API Mapping

**Version**: 0.1 — Initial draft
**Date**: 2026-03-11
**Status**: Draft
**Traceable to**: [spec-llm.md](../../specs/spec-llm.md), [ADR-001](../adr/ADR-001-ollama-local-llm-backend.md), [Architecture](../architecture.md) §4, [DES-001 Data Model](DES-001-sqlite-data-model.md) §4.1

---

## 1. Overview

This document details how each `revolver llm` subcommand maps to Ollama REST API endpoints, and how calls flow through the three-layer architecture (CLI → Core → Infra).

### 1.1 Ollama API Endpoints Used by Revolver

| Ollama Endpoint | Method | Purpose in Revolver |
|---|---|---|
| `GET /` | GET | Health check — is Ollama running? |
| `GET /api/tags` | GET | List locally available models |
| `POST /api/show` | POST | Get model details (digest, size, family, capabilities) |
| `POST /api/pull` | POST | Download a model from Ollama registry |
| `DELETE /api/delete` | DELETE | Delete model files from disk |
| `GET /api/ps` | GET | List models currently loaded in VRAM |
| `POST /api/chat` | POST | Load/unload model (via `keep_alive`), health-check prompt |
| `GET /api/version` | GET | Report Ollama version (for `doctor`) |

### 1.2 Endpoints NOT Used

| Endpoint | Reason |
|---|---|
| `POST /api/generate` | Revolver uses `/api/chat` (OpenEvolve uses the OpenAI-compat `/v1/chat/completions`) |
| `POST /api/embed` | No embedding use case in V1 |
| `POST /api/push` | Revolver doesn't publish models |
| `POST /api/copy` | No model aliasing at Ollama level (Revolver has its own naming) |
| `POST /api/create` | No custom model creation in V1 |
| `POST /api/blobs/*` | Internal to create/push workflows |

---

## 2. Command → Endpoint Mapping

### 2.1 `revolver llm add <name>`

Registers an LLM in the global SQLite database. For local (Ollama) LLMs, optionally pulls the model.

```
CLI (cli/llm.py)
  │ Parse: name, --provider, --model, --source, --api-key-env, --base-url, --pull
  │ Validate: mutual exclusivity (--provider vs --source ollama)
  ▼
Core (core/llm.py) → register_llm()
  │ 1. Check name uniqueness in DB
  │ 2. If source=ollama:
  │    a. Check Ollama health          ──► Infra: ollama.health_check()
  │    b. Check if model exists locally ──► Infra: ollama.list_local_models()
  │    c. If not exists or --pull:
  │       Pull model with progress     ──► Infra: ollama.pull_model(model, stream=True)
  │    d. Get model digest + details   ──► Infra: ollama.show_model(model)
  │    e. Set base_url = "http://localhost:11434/v1"
  │ 3. If remote:
  │    a. Validate provider is known
  │    b. Validate api_key_env is provided
  │    c. Set default base_url per provider (if not overridden)
  │ 4. Insert into global DB           ──► Infra: db.insert_llm(entry)
  ▼
Infra (infra/ollama.py)
  GET /              → health_check() → bool
  GET /api/tags      → list_local_models() → list[OllamaModel]
  POST /api/pull     → pull_model(name, stream) → Generator[PullProgress]
  POST /api/show     → show_model(name) → ModelInfo (digest, size, family, capabilities)
```

**Ollama endpoints**: `GET /`, `GET /api/tags`, `POST /api/pull`, `POST /api/show`

### 2.2 `revolver llm start <name>`

Loads a local LLM into GPU memory via Ollama.

```
CLI (cli/llm.py)
  │ Parse: name, --timeout
  ▼
Core (core/llm.py) → start_llm(name, timeout)
  │ 1. Look up LLM in DB                    ──► Infra: db.get_llm(name)
  │ 2. Validate source=local (reject remote)
  │ 3. Check Ollama health                   ──► Infra: ollama.health_check()
  │ 4. List currently loaded models          ──► Infra: ollama.list_running()
  │ 5. If another model loaded:
  │    a. Confirm unload (unless --quiet)
  │    b. Unload it                          ──► Infra: ollama.unload_model(other)
  │ 6. Check model exists locally            ──► Infra: ollama.list_local_models()
  │    If not: auto-pull                     ──► Infra: ollama.pull_model(model)
  │ 7. Load model (keep_alive=-1)            ──► Infra: ollama.load_model(model)
  │ 8. Wait for model to appear in /api/ps   ──► Infra: ollama.wait_loaded(model, timeout)
  │ 9. Health-check: send minimal prompt     ──► Infra: ollama.health_prompt(model)
  │ 10. Read VRAM usage                      ──► Infra: ollama.list_running() → size_vram
  │ 11. Optionally update measured stats     ──► Infra: db.update_llm_stats(name, vram, tps)
  ▼
Infra (infra/ollama.py)
  GET /              → health_check()
  GET /api/ps        → list_running() → list[RunningModel] (name, size, size_vram, digest)
  GET /api/tags      → list_local_models()
  POST /api/pull     → pull_model() (if needed)
  POST /api/chat     → load_model(model) — body: {model, messages:[], keep_alive:"-1"}
  POST /api/chat     → health_prompt(model) — body: {model, messages:[{role:"user", content:"ping"}], stream:false}
  POST /api/chat     → unload_model(model) — body: {model, messages:[], keep_alive:"0"}
```

**Ollama endpoints**: `GET /`, `GET /api/ps`, `GET /api/tags`, `POST /api/pull`, `POST /api/chat` (×3 patterns)

### 2.3 `revolver llm stop [name]`

Unloads a local LLM from GPU memory.

```
CLI (cli/llm.py)
  │ Parse: name (optional)
  ▼
Core (core/llm.py) → stop_llm(name=None)
  │ 1. Check Ollama health                   ──► Infra: ollama.health_check()
  │ 2. List currently loaded models          ──► Infra: ollama.list_running()
  │ 3. If name provided: validate it's loaded
  │    If name omitted: use whatever is loaded (if any)
  │ 4. If nothing loaded: no-op, exit 0
  │ 5. Unload model (keep_alive=0)           ──► Infra: ollama.unload_model(model)
  │ 6. Verify unloaded                       ──► Infra: ollama.list_running()
  ▼
Infra (infra/ollama.py)
  GET /              → health_check()
  GET /api/ps        → list_running()
  POST /api/chat     → unload_model(model) — body: {model, messages:[], keep_alive:"0"}
```

**Ollama endpoints**: `GET /`, `GET /api/ps`, `POST /api/chat`

### 2.4 `revolver llm status`

Shows the state of all registered LLMs, cross-referencing with Ollama runtime state.

```
CLI (cli/llm.py)
  │ Parse: --loaded-only, --json
  ▼
Core (core/llm.py) → get_llm_status(loaded_only=False)
  │ 1. Load all LLMs from DB                ──► Infra: db.list_llms()
  │ 2. Check Ollama health                   ──► Infra: ollama.health_check()
  │ 3. If Ollama running:
  │    a. List loaded models                 ──► Infra: ollama.list_running()
  │    b. Cross-reference: mark local LLMs as "loaded" or "stopped"
  │ 4. If Ollama not running:
  │    a. Mark all local LLMs as "unavailable"
  │ 5. For remote LLMs:
  │    a. Check if api_key_env is set in environment
  │    b. Mark as "ready" or "unconfigured"
  │ 6. Get GPU info                          ──► Infra: gpu.get_gpu_info() (nvidia-smi)
  │ 7. Return LLMStatusReport
  ▼
Infra (infra/ollama.py)
  GET /              → health_check()
  GET /api/ps        → list_running()

Infra (infra/gpu.py)  [new module]
  nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader,nounits
  → GpuInfo(name, vram_used_mib, vram_total_mib)
```

**Ollama endpoints**: `GET /`, `GET /api/ps`

**Note**: GPU info via `nvidia-smi` is separate from Ollama. Extracted into `infra/gpu.py` for reuse by `doctor` and `status`.

### 2.5 `revolver llm list`

Brief listing of registered LLMs. Pure database query — no Ollama interaction.

```
CLI (cli/llm.py)
  │ Parse: --json
  ▼
Core (core/llm.py) → list_llms()
  │ 1. Load all LLMs from DB                ──► Infra: db.list_llms()
  │ 2. Return list
  ▼
Infra (infra/db.py)
  SELECT name, source, provider, model FROM llms ORDER BY name;
```

**Ollama endpoints**: None (offline command)

### 2.6 `revolver llm remove <name>`

Unregisters an LLM and optionally deletes model files.

```
CLI (cli/llm.py)
  │ Parse: name, --delete-model, --json
  ▼
Core (core/llm.py) → remove_llm(name, delete_model=False)
  │ 1. Look up LLM in DB                    ──► Infra: db.get_llm(name)
  │ 2. If source=local and Ollama running:
  │    a. Check if model is loaded           ──► Infra: ollama.list_running()
  │    b. If loaded: unload first            ──► Infra: ollama.unload_model(model)
  │    c. If --delete-model:
  │       Delete model files from Ollama     ──► Infra: ollama.delete_model(model)
  │ 3. Remove from DB                        ──► Infra: db.delete_llm(name)
  ▼
Infra (infra/ollama.py)
  GET /              → health_check()
  GET /api/ps        → list_running()
  POST /api/chat     → unload_model(model)
  DELETE /api/delete  → delete_model(model) — body: {model: "name"}
```

**Ollama endpoints**: `GET /`, `GET /api/ps`, `POST /api/chat`, `DELETE /api/delete`

---

## 3. Infra Layer: `ollama.py` Client Interface

### 3.1 Class Design

```python
class OllamaClient:
    """HTTP client for Ollama REST API."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        # Uses httpx.Client for sync HTTP

    # --- Health ---
    def health_check(self) -> bool:
        """GET / — Returns True if Ollama is reachable."""

    def version(self) -> str:
        """GET /api/version — Returns Ollama version string."""

    # --- Model Management ---
    def list_local_models(self) -> list[LocalModel]:
        """GET /api/tags — List all models downloaded locally."""

    def show_model(self, name: str) -> ModelInfo:
        """POST /api/show — Get model details (digest, size, family, quantization, capabilities)."""

    def pull_model(self, name: str, stream: bool = True) -> Iterator[PullProgress]:
        """POST /api/pull — Download model. Yields progress events if streaming."""

    def delete_model(self, name: str) -> None:
        """DELETE /api/delete — Remove model files from disk."""

    # --- Runtime (Load/Unload) ---
    def list_running(self) -> list[RunningModel]:
        """GET /api/ps — List models currently loaded in VRAM."""

    def load_model(self, name: str) -> None:
        """POST /api/chat with keep_alive=-1, empty messages. Triggers model load."""

    def unload_model(self, name: str) -> None:
        """POST /api/chat with keep_alive=0, empty messages. Triggers model unload."""

    def wait_loaded(self, name: str, timeout_s: int = 120) -> RunningModel:
        """Poll GET /api/ps until model appears. Raises TimeoutError."""

    # --- Health Check Prompt ---
    def health_prompt(self, name: str) -> bool:
        """POST /api/chat with minimal prompt. Returns True if model responds."""
```

### 3.2 Data Types

```python
@dataclass
class LocalModel:
    """A model available on disk (from GET /api/tags)."""
    name: str           # "codestral:22b"
    digest: str         # "sha256:0898a8b2..."
    size_bytes: int     # on-disk size
    modified_at: str    # ISO 8601

@dataclass
class ModelInfo:
    """Detailed model info (from POST /api/show)."""
    family: str         # "llama", "qwen2", etc.
    parameter_size: str # "22B", "7B"
    quantization: str   # "Q4_K_M", "F16"
    capabilities: list[str]  # ["completion", "tools", ...]
    digest: str         # full digest

@dataclass
class RunningModel:
    """A model currently loaded in VRAM (from GET /api/ps)."""
    name: str
    digest: str
    size_bytes: int     # total model size
    size_vram: int      # VRAM occupied (bytes)
    expires_at: str     # when it will auto-unload ("" if keep_alive=-1)

@dataclass
class PullProgress:
    """Progress event during model pull."""
    status: str         # "pulling manifest", "pulling sha256:...", "verifying", "success"
    total: int | None   # total bytes (if downloading)
    completed: int | None  # bytes downloaded so far
```

---

## 4. Infra Layer: `gpu.py` Module

GPU monitoring is independent of Ollama and used by both `llm status` and `doctor`.

```python
@dataclass
class GpuInfo:
    name: str              # "NVIDIA GeForce RTX 5090"
    vram_used_mib: int
    vram_total_mib: int

def get_gpu_info() -> GpuInfo | None:
    """Run nvidia-smi and parse output. Returns None if no GPU or nvidia-smi not found."""
    # nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader,nounits
```

---

## 5. Core Layer: `llm.py` Function Signatures

```python
# --- Registration ---
def register_llm(
    name: str,
    model: str,
    source: str = "remote",        # "local" | "remote"
    provider: str | None = None,   # "anthropic" | "openai" | "google" | "openai-compat"
    api_key_env: str | None = None,
    base_url: str | None = None,
    pull: bool = False,
) -> LLMEntry:
    """Register a new LLM in the global database."""

def remove_llm(name: str, delete_model: bool = False) -> None:
    """Unregister an LLM. Optionally delete Ollama model files."""

# --- Lifecycle ---
def start_llm(name: str, timeout: int = 120) -> StartResult:
    """Load a local LLM into GPU memory."""

def stop_llm(name: str | None = None) -> StopResult:
    """Unload a local LLM from GPU memory."""

# --- Query ---
def list_llms() -> list[LLMEntry]:
    """List all registered LLMs (brief, no runtime state)."""

def get_llm_status(loaded_only: bool = False) -> LLMStatusReport:
    """Get full status of all LLMs, cross-referenced with Ollama runtime."""
```

---

## 6. CLI Layer: `llm.py` Typer Commands

```python
import typer

app = typer.Typer(name="llm", help="Manage LLM backends")

@app.command()
def add(
    name: str = typer.Argument(..., help="User-facing LLM identifier"),
    model: str = typer.Option(..., help="Model ID (e.g., codestral:22b, claude-opus-4-6)"),
    source: str = typer.Option(None, help="'ollama' for local models"),
    provider: str = typer.Option(None, help="Remote provider: anthropic, openai, google, openai-compat"),
    api_key_env: str = typer.Option(None, "--api-key-env", help="Env var name for API key"),
    base_url: str = typer.Option(None, "--base-url", help="Override API base URL"),
    pull: bool = typer.Option(False, "--pull", help="Pull model immediately (Ollama)"),
): ...

@app.command()
def start(
    name: str = typer.Argument(..., help="LLM to load into GPU"),
    timeout: int = typer.Option(120, "--timeout", help="Max seconds to wait for load"),
): ...

@app.command()
def stop(
    name: str = typer.Argument(None, help="LLM to unload (default: current)"),
): ...

@app.command()
def status(
    loaded_only: bool = typer.Option(False, "--loaded-only", help="Only show loaded models"),
): ...

@app.command(name="list")
def list_cmd(): ...

@app.command()
def remove(
    name: str = typer.Argument(..., help="LLM to unregister"),
    delete_model: bool = typer.Option(False, "--delete-model", help="Also delete Ollama files"),
): ...
```

---

## 7. Summary: Endpoint Usage Matrix

| Command | `GET /` | `GET /api/tags` | `POST /api/show` | `POST /api/pull` | `DELETE /api/delete` | `GET /api/ps` | `POST /api/chat` |
|---|---|---|---|---|---|---|---|
| `llm add` (local) | **health** | list models | **digest** | **pull** | — | — | — |
| `llm add` (remote) | — | — | — | — | — | — | — |
| `llm start` | **health** | check exists | — | auto-pull | — | **loaded?** | **load + health** |
| `llm stop` | **health** | — | — | — | — | **loaded?** | **unload** |
| `llm status` | **health** | — | — | — | — | **loaded?** | — |
| `llm list` | — | — | — | — | — | — | — |
| `llm remove` | health | — | — | — | **delete** | loaded? | unload |

**Bold** = always called. Normal = conditionally called.

---

## 8. Error Handling Flow

All Ollama communication errors are caught in `infra/ollama.py` and re-raised as typed domain exceptions:

| Infra Error | Domain Exception | CLI Exit Code |
|---|---|---|
| `httpx.ConnectError` (Ollama unreachable) | `OllamaNotRunningError` | 3 |
| HTTP 404 on `/api/show` (model not found) | `ModelNotFoundError` | 1 |
| Pull failure (network, disk space) | `ModelPullError` | 4 |
| Health prompt timeout / bad response | `ModelHealthCheckError` | 4 |
| `TimeoutError` from `wait_loaded()` | `ModelLoadTimeoutError` | 3 |
| `nvidia-smi` not found | `GpuNotAvailableError` (warning, not fatal) | — |

---

## 9. Sequence Diagrams

### 9.1 `revolver llm add codestral-local --source ollama --model codestral:22b --pull`

```
User           CLI              Core             OllamaClient        GlobalDB
 │              │                │                    │                  │
 │─ llm add ──►│                │                    │                  │
 │              │─ register() ──►│                    │                  │
 │              │                │── health_check() ─►│                  │
 │              │                │◄── true ───────────│                  │
 │              │                │── list_local() ───►│ GET /api/tags    │
 │              │                │◄── [models] ───────│                  │
 │              │                │── pull_model() ───►│ POST /api/pull   │
 │              │                │◄── progress... ────│ (streaming)      │
 │◄─ progress ──│◄── progress ───│                    │                  │
 │              │                │── show_model() ───►│ POST /api/show   │
 │              │                │◄── ModelInfo ──────│                  │
 │              │                │── insert_llm() ───────────────────────►│
 │              │                │◄── ok ────────────────────────────────│
 │◄─ success ──│◄── LLMEntry ──│                    │                  │
```

### 9.2 `revolver llm start codestral-local`

```
User           CLI              Core             OllamaClient        GlobalDB
 │              │                │                    │                  │
 │─ llm start ─►│               │                    │                  │
 │              │─ start() ─────►│                    │                  │
 │              │                │── get_llm() ──────────────────────────►│
 │              │                │◄── LLMEntry ─────────────────────────│
 │              │                │── health_check() ─►│                  │
 │              │                │── list_running() ─►│ GET /api/ps      │
 │              │                │◄── [other_model] ──│                  │
 │◄─ confirm? ──│◄── confirm? ──│                    │                  │
 │─ yes ───────►│─ yes ─────────►│                    │                  │
 │              │                │── unload(other) ──►│ POST /api/chat   │
 │              │                │                    │ keep_alive:"0"   │
 │              │                │── load(model) ────►│ POST /api/chat   │
 │              │                │                    │ keep_alive:"-1"  │
 │              │                │── wait_loaded() ──►│ GET /api/ps      │
 │              │                │                    │ (poll until ok)  │
 │              │                │── health_prompt() ─►│ POST /api/chat  │
 │              │                │◄── ok ─────────────│ "ping" → reply   │
 │              │                │── list_running() ─►│ GET /api/ps      │
 │              │                │◄── RunningModel ──│ (size_vram)      │
 │◄─ loaded ───│◄── StartResult│                    │                  │
```

---

## 10. Design Decisions

### DD-01: Load/unload via `POST /api/chat` with `keep_alive`

Ollama has no dedicated load/unload endpoint. The documented pattern is:
- **Load**: `POST /api/chat` with `messages: []` and `keep_alive: "-1"` (indefinite)
- **Unload**: `POST /api/chat` with `messages: []` and `keep_alive: "0"` (immediate)

This is the officially documented approach. Alternative (`POST /api/generate`) works too, but `/api/chat` is preferred since it's the primary inference endpoint.

### DD-02: Health check via minimal chat prompt

After loading a model, Revolver sends a minimal prompt (`"ping"`) and verifies a non-empty response. This catches cases where the model loads into VRAM but fails to generate (corrupted weights, incompatible architecture).

### DD-03: Polling `GET /api/ps` for load completion

Model loading is async — the `POST /api/chat` load request returns quickly but the model may take 10-60s to fully load (especially large models). Revolver polls `/api/ps` with exponential backoff (100ms → 200ms → 400ms → ... capped at 2s) until the model appears or timeout.

### DD-04: GPU info from `nvidia-smi`, not Ollama

Ollama's `/api/ps` reports `size_vram` per model, but not total GPU capacity. For the "GPU: RTX 5090 — X / Y MiB" line in `llm status`, we call `nvidia-smi` directly. This is extracted into `infra/gpu.py` for reuse.

### DD-05: Global DB storage (SQLite, not YAML)

Per data model decision DM-02, the LLM registry uses SQLite (`~/.revolver/revolver.db`) rather than individual YAML files. This prevents manual edits that could introduce inconsistencies and ensures atomic writes. The `llms` table schema is defined in [DES-001 §4.1](DES-001-sqlite-data-model.md).

**Note**: spec-llm.md §5 has been updated to reflect the SQLite decision (was previously YAML files in `~/.revolver/llms/`).

---

## 11. Architecture Impact

### New modules

| Module | Layer | Purpose |
|---|---|---|
| `infra/gpu.py` | Infrastructure | `nvidia-smi` wrapper for GPU info |

### Existing modules impacted

| Module | Change |
|---|---|
| `infra/ollama.py` | Implement `OllamaClient` class (§3) |
| `infra/db.py` | Add LLM CRUD queries for global DB |
| `core/llm.py` | Implement 6 orchestration functions (§5) |
| `cli/llm.py` | Implement 6 Typer commands (§6) |
| `models/llm.py` | Define `LLMEntry`, `LLMStatus`, `StartResult`, `StopResult`, `LLMStatusReport` |

### Package structure update

```
src/revolver/infra/
├── ...
├── ollama.py    # OllamaClient (§3)
└── gpu.py       # GpuInfo, get_gpu_info() (§4) ← NEW
```
