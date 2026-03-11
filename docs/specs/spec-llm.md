# Spec: revolver llm

**Traceable to**: ConOps §4.8 (LLM), §5.1 (Workflow: Setup LLMs), §3.2 (LLM Backends)
**Status**: Draft
**See also**: [POC Local LLM](../pocs/poc-local-llm.md)

---

## 1. Scope

This spec covers LLM registration, lifecycle management, and monitoring. LLMs are managed **globally** (`~/.revolver/revolver.db`), not per-project, since models are shared resources.

Revolver supports two LLM types:
- **Remote**: API-based (Anthropic, Google, OpenAI) — configured with provider, model name, API key env var
- **Local**: Served via Ollama — Revolver manages pull, load, unload, and VRAM monitoring

---

## 2. Commands

### 2.1 `revolver llm add <name>`

Register a new LLM in the global registry.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | User-facing identifier (e.g., `claude-opus`, `codestral-local`) |

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--provider <name>` | string | For remote | Provider: `anthropic`, `openai`, `google`, or `openai-compat` |
| `--model <id>` | string | Yes | Model identifier (e.g., `claude-opus-4-6`, `codestral:22b`) |
| `--source ollama` | string | For local | Use Ollama as the serving backend |
| `--api-key-env <var>` | string | For remote | Environment variable name holding the API key (e.g., `ANTHROPIC_API_KEY`) |
| `--base-url <url>` | string | No | Override API base URL. Auto-set to `http://localhost:11434/v1` for Ollama |
| `--pull` | flag | No | For Ollama: immediately pull the model after registration (default: prompt user) |

**Output** (human):
```
LLM "codestral-local" registered (source: ollama, model: codestral:22b)
Model pulled successfully (12 GB, digest: sha256:0898a8b2...)
```

**Output** (JSON):
```json
{
  "name": "codestral-local",
  "source": "ollama",
  "model": "codestral:22b",
  "digest": "sha256:0898a8b286d5...",
  "base_url": "http://localhost:11434/v1",
  "status": "pulled"
}
```

**Exit codes**: 0 success, 1 if name already registered, 3 if Ollama not running (local), 4 if pull fails

### 2.2 `revolver llm start <name>`

Load a local LLM into GPU memory.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Registered LLM name |

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--timeout <seconds>` | int | 120 | Maximum time to wait for model load |

**Behavior**:
1. Check if another local model is currently loaded
2. If yes, unload it first (with confirmation unless `--quiet`)
3. Load the requested model via Ollama API
4. Verify the model responds to a health-check prompt
5. Report VRAM usage

**Output** (human):
```
Unloading "qwen-7b"... done (VRAM freed)
Loading "codestral-local" (codestral:22b)... done (19.4 GB VRAM, 27s)
Endpoint: http://localhost:11434/v1
```

**Exit codes**: 0 success, 1 if name not registered, 3 if Ollama not running or GPU unavailable, 4 if health check fails

### 2.3 `revolver llm stop [name]`

Unload a local LLM from GPU memory.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | No | LLM to unload. If omitted, unload whatever is currently loaded. |

**Behavior**:
1. Send unload request to Ollama (`keep_alive: 0`)
2. Verify VRAM is freed

**Output** (human):
```
Unloaded "codestral-local" (VRAM freed: 19.4 GB → baseline)
```

**Exit codes**: 0 success (including if nothing was loaded), 3 if Ollama not running

### 2.4 `revolver llm status`

Show the current state of all registered LLMs.

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--loaded-only` | flag | false | Only show currently loaded models |

**Output** (human):
```
Name              Type    Model             Status     VRAM
codestral-local   local   codestral:22b     loaded     19.4 GB
qwen-7b           local   qwen2.5-coder:7b  stopped    —
claude-opus       remote  claude-opus-4-6   ready      —

GPU: RTX 5090 — 19,896 / 32,607 MiB used
```

**Output** (JSON):
```json
{
  "llms": [
    {
      "name": "codestral-local",
      "type": "local",
      "model": "codestral:22b",
      "status": "loaded",
      "vram_mib": 19896
    }
  ],
  "gpu": {
    "name": "RTX 5090",
    "vram_used_mib": 19896,
    "vram_total_mib": 32607
  }
}
```

**Exit codes**: 0 always (informational command)

### 2.5 `revolver llm list`

List all registered LLMs (brief format).

**Output** (human):
```
codestral-local   ollama    codestral:22b
qwen-7b           ollama    qwen2.5-coder:7b
claude-opus       anthropic claude-opus-4-6
```

**Exit codes**: 0 always

### 2.6 `revolver llm remove <name>`

Unregister an LLM from the global registry.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | LLM to remove |

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--delete-model` | flag | false | For Ollama: also delete the model files from disk (`ollama rm`) |

**Behavior**:
1. If the model is currently loaded, unload it first
2. Remove the registration from the global database
3. Optionally delete model files from Ollama

**Exit codes**: 0 success, 1 if name not found

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-LLM-001 | MUST | Support registering remote LLMs with provider, model ID, and API key env var | §4.8 |
| FR-LLM-002 | MUST | Support registering local LLMs served via Ollama | §4.8 |
| FR-LLM-003 | MUST | Store LLM registrations in global SQLite database (`~/.revolver/revolver.db`) | §4.8 |
| FR-LLM-004 | MUST | For Ollama LLMs, trigger `ollama pull` at registration time (or on demand) | §5.1 |
| FR-LLM-005 | MUST | Record and store Ollama model digest for reproducibility | §7, POC |
| FR-LLM-006 | MUST | Provide `start` command that loads a local model into GPU via Ollama API | §5.1, POC |
| FR-LLM-007 | MUST | Provide `stop` command that unloads a model and frees VRAM | §5.1, POC |
| FR-LLM-008 | MUST | Enforce single-model-at-a-time for local LLMs: unload current before loading new | §3.3 |
| FR-LLM-009 | MUST | `status` command shows loaded model, VRAM usage (from Ollama `/api/ps` + `nvidia-smi`) | POC |
| FR-LLM-010 | MUST | Expose the OpenAI-compatible base URL for each registered LLM | §3.2 |
| FR-LLM-011 | SHOULD | Warn user if requested model's expected VRAM exceeds available GPU memory | POC |
| FR-LLM-012 | SHOULD | Record measured throughput and VRAM footprint after first model load | POC |
| FR-LLM-013 | SHOULD | Health-check after `start`: send a minimal prompt and verify response | — |
| FR-LLM-014 | MUST | `remove` command deletes the registration; optionally deletes Ollama model files | — |
| FR-LLM-015 | MUST | Remote LLMs have status `ready` if the API key env var is set, `unconfigured` otherwise | §4.8 |
| FR-LLM-016 | SHOULD | Support `--provider openai-compat` for arbitrary OpenAI-compatible endpoints | §3.2 |
| FR-LLM-017 | MUST | API keys are never stored in Revolver files — only the env var name is stored | NFR-050 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| `llm add` with a name that already exists | Error: "LLM '<name>' already registered. Use `revolver llm remove` first." | 1 |
| `llm start` when Ollama is not running | Error: "Ollama is not running. Start it with `ollama serve`." | 3 |
| `llm start` on a remote LLM | Error: "LLM '<name>' is remote — no start/stop needed. It is ready if <ENV_VAR> is set." | 1 |
| `llm start` and model not yet pulled | Auto-trigger pull with progress display; fail if pull fails | 4 |
| `llm start` and insufficient VRAM (estimated) | Warning: "Model <name> requires ~X GB VRAM but only Y GB available. Continue? [y/N]" | 0 or 3 |
| `llm stop` when nothing is loaded | No-op, exit 0 | 0 |
| `llm remove` with name not found | Error: "LLM '<name>' not found in registry." | 1 |
| `~/.revolver/` does not exist | Auto-create it | — |

---

## 5. LLM Registry Storage

LLM registrations are stored in the **global SQLite database** (`~/.revolver/revolver.db`, table `llms`). See [DES-001 §4.1](../architecture/design/DES-001-sqlite-data-model.md) for the schema definition.

Using SQLite (rather than individual YAML files) ensures atomic writes and prevents manual edits that could introduce inconsistencies with actual LLM state. All mutations go through `revolver llm add/remove`.

**Stored fields per LLM**:

| Field | Local (Ollama) | Remote (API) |
|---|---|---|
| `name` | User-facing identifier | User-facing identifier |
| `source` | `"local"` | `"remote"` |
| `provider` | — | `"anthropic"`, `"openai"`, `"google"`, `"openai-compat"` |
| `model` | `"codestral:22b"` | `"claude-opus-4-6"` |
| `base_url` | `"http://localhost:11434/v1"` | Provider default or custom |
| `api_key_env` | — | `"ANTHROPIC_API_KEY"` |
| `registered_at` | ISO 8601 | ISO 8601 |

**Runtime-only fields** (not persisted in the `llms` table, queried live):
- VRAM usage → from Ollama `GET /api/ps`
- Loaded/stopped status → from Ollama `GET /api/ps`
- GPU info → from `nvidia-smi`
- API key availability → from `os.environ`

---

## 6. Dependencies

- **Ollama** must be installed and running for local LLM commands (NFR-042)
- **nvidia-smi** must be available for VRAM reporting (NFR-041)
