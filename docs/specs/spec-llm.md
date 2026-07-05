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
| `--source local` | string | For local | Use Ollama as the serving backend (default: `remote`) |
| `--api-key-env <var>` | string | For remote | Environment variable name holding the API key (e.g., `ANTHROPIC_API_KEY`) |
| `--base-url <url>` | string | No | Override API base URL. Auto-set to `http://localhost:11434/v1` for Ollama |
| `--pull` | flag | No | For Ollama: immediately pull the model after registration (default: prompt user) |
| `--max-tokens <n>` | int | No | Maximum tokens per LLM response. Stored in the registry and projected into the backend config at run time (OE: `llm.max_tokens`; Shinka: `llm_kwargs.max_tokens`) — FR-LLM-019. |
| `--timeout <seconds>` | int | No | Request timeout in seconds. Stored in the registry and projected into the backend config at run time (OE: `llm.timeout`; Shinka: `llm_timeout` → the engine's LLM-request timeout, R2) — FR-LLM-019. |
| `--temperature <float>` | float | No | Sampling temperature (0.0–2.0). Stored in the registry and projected into the backend config at run time (OE: `llm.temperature`; Shinka: `llm_kwargs.temperatures`) — FR-LLM-019. |
| `--reasoning-effort <level>` | string | No | Reasoning effort for reasoning-capable models: `min`, `low`, `medium`, `high`, or `max`. Stored in the registry and projected per backend at run time (FR-LLM-026). |

**Output** (human):
```
LLM "codestral-local" registered (source: ollama, model: codestral:22b)
Model pulled successfully (12 GB, digest: sha256:0898a8b2...)
```

```bash
$ revolver llm add claude-opus --provider anthropic --model claude-opus-4-6 --api-key-env ANTHROPIC_API_KEY
```
```
LLM "claude-opus" registered (provider: anthropic, model: claude-opus-4-6)
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

List all registered LLMs (brief format). If any LLM has config fields set (max_tokens, timeout, temperature), additional columns are displayed.

**Output** (human):
```
codestral-local   ollama    codestral:22b
qwen-7b           ollama    qwen2.5-coder:7b
claude-opus       anthropic claude-opus-4-6       temperature=0.7
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

### 2.7 `revolver llm update <name>`

Update configuration fields of a registered LLM. At least one option must be provided.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Registered LLM name |

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--max-tokens <n>` | int | No | Maximum tokens per LLM response |
| `--timeout <seconds>` | int | No | Request timeout in seconds |
| `--temperature <float>` | float | No | Sampling temperature (0.0–2.0) |
| `--reasoning-effort <level>` | string | No | Reasoning effort: `min`, `low`, `medium`, `high`, or `max` (FR-LLM-026) |

**Output** (human):
```
LLM "claude-opus" updated (max_tokens: 4096, temperature: 0.7)
```

**Exit codes**: 0 success, 1 if name not found, 1 if no update flags provided

### 2.8 `revolver llm ensemble create <name>`

Create a named LLM ensemble in the global registry. An ensemble groups multiple LLMs with weights for multi-model evolution runs.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Unique ensemble name (e.g., `multi-model-v1`) |

**Output** (human):
```
Ensemble "multi-model-v1" created (0 members)
```

**Exit codes**: 0 success, 1 if name already exists

### 2.9 `revolver llm ensemble add <name> --llm <llm> --weight <w>`

Add a member LLM to an existing ensemble with a sampling weight.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Ensemble name (positional) |

**Options**:

| Option | Type | Required | Description |
|---|---|---|---|
| `--llm <name>` | string | Yes | Registered LLM name to add as member |
| `--weight <w>` | float | Yes | Sampling weight for this member (0.0–1.0) |
| `--temperature <float>` | float | No | Per-member temperature override (0.0–2.0) |
| `--max-tokens <n>` | int | No | Per-member max tokens override |
| `--reasoning-effort <level>` | string | No | Per-member reasoning-effort override: `min`, `low`, `medium`, `high`, `max`. Takes precedence over the member LLM's registry-level value. Honored per-member on OpenEvolve; global-only on ShinkaEvolve (FR-LLM-026) |

**Behavior**:
1. Validate the ensemble exists
2. Validate the LLM is registered
3. Add the member with the given weight
4. Warn if total weights across all members do not sum to approximately 1.0

**Output** (human):
```
Added "claude-opus" to ensemble "multi-model-v1" (weight: 0.7)
Warning: Total weights sum to 0.7 (expected ~1.0). Add more members or adjust weights.
```

**Exit codes**: 0 success, 1 if ensemble or LLM not found, 1 if duplicate member

### 2.10 `revolver llm ensemble list`

List all registered ensembles.

**Output** (human):
```
Name              Members  Created
multi-model-v1    2        2026-03-25
coding-mix        3        2026-03-26
```

**Exit codes**: 0 always

### 2.11 `revolver llm ensemble info <name>`

Show detailed information about an ensemble including its members and weights.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Ensemble name |

**Output** (human):
```
Ensemble: multi-model-v1
  Created: 2026-03-25

Members:
  LLM              Weight  Temperature  Max Tokens
  claude-opus      0.7     —            —
  gemini-pro       0.3     0.9          4096

Total weight: 1.0
```

**Output** (JSON):
```json
{
  "name": "multi-model-v1",
  "created_at": "2026-03-25T10:00:00Z",
  "members": [
    {"llm_name": "claude-opus", "weight": 0.7, "temperature": null, "max_tokens": null},
    {"llm_name": "gemini-pro", "weight": 0.3, "temperature": 0.9, "max_tokens": 4096}
  ],
  "total_weight": 1.0
}
```

**Exit codes**: 0 success, 1 if not found

### 2.12 `revolver llm ensemble remove <name>`

Remove an ensemble from the global registry. This cascade-deletes all ensemble members.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Ensemble to remove |

**Output** (human):
```
Ensemble "multi-model-v1" removed (2 members deleted)
```

**Exit codes**: 0 success, 1 if not found

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
| FR-LLM-018 | ~~SHOULD~~ | **Removed (S16 / #300).** The `--input-cost`/`--output-cost` pricing flags and the `input_cost_per_mtok`/`output_cost_per_mtok` columns were dropped (cost is no longer reported — mirrors FR-RUN-030). Schema migration v10 removes the columns from the `llms` table. | POC #13 |
| FR-LLM-019 | SHOULD | LLM temperature stored in registry and injected into the backend config when present | — |
| FR-LLM-020 | MUST | Create a named ensemble in the global registry with a unique name | — |
| FR-LLM-021 | MUST | Add a member LLM to an ensemble with a sampling weight (and optional per-member temperature/max_tokens overrides) | — |
| FR-LLM-022 | MUST | List all registered ensembles with member counts | — |
| FR-LLM-023 | MUST | Show ensemble details including members, weights, and per-member overrides | — |
| FR-LLM-024 | MUST | Remove an ensemble with cascade deletion of its members | — |
| FR-LLM-025 | SHOULD | Warn if member weights do not sum to approximately 1.0 when adding a member | — |
| FR-LLM-026 | SHOULD | Store a per-LLM `reasoning_effort` (`min`/`low`/`medium`/`high`/`max`) in the registry, settable via `llm add --reasoning-effort`, `llm update --reasoning-effort`, and per-member via `ensemble add --reasoning-effort` (member override wins over the LLM's registry value). Projected per backend at run time: OpenEvolve maps it **per member** (`LLMModelConfig.reasoning_effort`); ShinkaEvolve maps it to a **single global** pool (`llm_kwargs.reasoning_efforts`). When ensemble members disagree on ShinkaEvolve, Revolver aligns on the **highest** effort (total order `min < low < medium < high < max`, a conservative default that never under-thinks) and **warns** that per-member effort is not honored. Also inert (warned) for local/bridge models, which ShinkaEvolve classes as non-reasoning (ADR-007 A1/A3.2). | — |

> **Note — per-backend projection (ADR-007 D5, amended by the v0.17 Amendment)**: the registry stores backend-agnostic data; each
> evolution backend projects it at run time. On ShinkaEvolve: local entries map to
> `local/<model>@<base_url>?api_key_env=…`; remote entries require the model id to be recognized by
> Shinka's pricing table (documented limitation); custom `api_key_env` names are bridged by exporting
> the provider-standard variable. Ensemble mapping is now **first-class** (ADR-007 A2/A3), not a silent
> drop: all members project to `evo_config.llm_models[]`, and under `--selection fixed` member weights
> seed `FixedSampler.prior_probs` (apples-to-apples with the OE weighted ensemble). Two verified
> ShinkaEvolve 0.0.7 asymmetries remain, surfaced via `capabilities()` (map-with-warn): (1) member
> weights seed the bandit **only under `fixed`** — under `ucb`/`ucb1`/`thompson` the arms start uniform
> and weights are **ignored with a warning**; (2) per-member `reasoning_effort` is **OpenEvolve-only** —
> ShinkaEvolve has a single global `reasoning_efforts` pool, so on disagreement Revolver aligns on the
> **highest** effort and warns (also inert for local/bridge models). The registry gains a
> `reasoning_effort` field for both `llms` and `ensemble_members` (FR-LLM-026; DB migrations v12/v13).

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

Using SQLite (rather than individual YAML files) ensures atomic writes and prevents manual edits that could introduce inconsistencies with actual LLM state. All mutations go through `revolver llm add/update/remove`.

**Stored fields per LLM**:

| Field | Local (Ollama) | Remote (API) |
|---|---|---|
| `name` | User-facing identifier | User-facing identifier |
| `source` | `"local"` | `"remote"` |
| `provider` | — | `"anthropic"`, `"openai"`, `"google"`, `"openai-compat"` |
| `model` | `"codestral:22b"` | `"claude-opus-4-6"` |
| `base_url` | `"http://localhost:11434/v1"` | Provider default or custom |
| `api_key_env` | — | `"ANTHROPIC_API_KEY"` |
| `max_tokens` | Optional | Optional |
| `timeout_s` | Optional | Optional |
| `temperature` | Optional (0.0–2.0) | Optional (0.0–2.0) |
| `reasoning_effort` | Optional (`min`/`low`/`medium`/`high`/`max`; inert for local) | Optional (`min`/`low`/`medium`/`high`/`max`) |
| `registered_at` | ISO 8601 | ISO 8601 |

### 5.1 Ensemble Storage

Ensembles are stored in two additional tables in the **global SQLite database** (`~/.revolver/revolver.db`). See [DES-001 §4.2–4.3](../architecture/design/DES-001-sqlite-data-model.md) for the schema definition.

**`ensembles` table** — one row per ensemble:

| Field | Description |
|---|---|
| `name` | Unique ensemble identifier (PK) |
| `created_at` | ISO 8601 timestamp |

**`ensemble_members` table** — one row per member LLM:

| Field | Description |
|---|---|
| `ensemble_name` | FK to `ensembles(name)` with CASCADE delete |
| `llm_name` | FK to `llms(name)` |
| `weight` | Sampling weight (0.0–1.0) |
| `temperature` | Per-member temperature override (optional) |
| `max_tokens` | Per-member max tokens override (optional) |
| `reasoning_effort` | Per-member reasoning-effort override (optional; `min`/`low`/`medium`/`high`/`max`) |

**Runtime-only fields** (not persisted in the `llms` table, queried live):
- VRAM usage → from Ollama `GET /api/ps`
- Loaded/stopped status → from Ollama `GET /api/ps`
- GPU info → from `nvidia-smi`
- API key availability → from `os.environ`

---

## 6. Dependencies

- **Ollama** must be installed and running for local LLM commands (NFR-042)
- **nvidia-smi** must be available for VRAM reporting (NFR-041)
