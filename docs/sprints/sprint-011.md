# Sprint 011 — Multi-Model Ensemble Support (v0.11.0)

**Status**: Planning
**Goal**: Support OpenEvolve's native multi-model ensemble (`llm.models` array) so users can run AlphaEvolve-style ensembles (e.g. Flash 80% + Pro 20%) without editing raw YAML. Deliver named ensemble entities in the LLM registry, ensemble-aware `build_config()`, structured LLM snapshot for traceability, and CLI options for ensemble selection on `run start`/`run resume`.
**Demo**: `revolver llm ensemble create alphevo --add flash-lite:0.8 --add pro:0.2` registers an ensemble; `revolver run start --llm alphevo` runs OE with two models weighted 80/20; `revolver run info` shows ensemble name, member models, and weights from a structured `llm_snapshot` JSON field — no YAML parsing required.

---

## Source

- Demo feedback: `/home/mathi/revolver-demos/beamforming/demos/demo-v0.9.0/feedback.md` (F3 — Multi-model ensemble)
- Feedback summary: `/home/mathi/revolver-demos/feedback-summary.md`
- Predecessor: Sprint 010 (v0.10.0) — 965 tests passing
- POC: Multi-model ensemble OE format validated in `revolver-demos` (2026-03-28)

---

## Feature scope: F3 — Multi-model ensemble

### Problem

OpenEvolve supports a `llm.models` array in YAML for ensemble evolution:

```yaml
llm:
  models:
    - name: gemini-2.5-flash-lite
      api_base: https://generativelanguage.googleapis.com/v1beta/openai
      api_key_env: GEMINI_API_KEY
      weight: 0.8
    - name: gemini-2.5-pro
      api_base: https://generativelanguage.googleapis.com/v1beta/openai
      api_key_env: GEMINI_API_KEY
      weight: 0.2
      temperature: 0.5
```

Revolver currently only supports a single LLM via `--llm`, building a `llm.model` (singular) in `build_config()`. There is no way to use multi-model ensembles without editing the raw OE YAML manually.

### Design selected

**Option A — Named ensemble entity in DB**:
- New `ensembles` + `ensemble_members` tables in global DB
- `llm ensemble create`, `llm ensemble add`, `llm ensemble list`, `llm ensemble info`, `llm ensemble remove` subcommands
- `--llm` on `run start`/`run resume` accepts either a registered LLM name or a registered ensemble name
- Traceability: run record stores structured `llm_snapshot` JSON (queryable, no YAML parsing)

---

## Scope

### Command groups included

- `revolver llm ensemble` — new subcommand group: create, list, info, add (member), remove
- `revolver run` — `--llm` accepts ensemble name; `build_config()` emits `llm.models` array when ensemble used
- `revolver infra` (DB) — migration v8: `ensembles` + `ensemble_members` tables (global DB); `llm_type` column + `llm_snapshot` column on `runs` (project DB)
- `docs/guides` — ensemble strategies guide section

### Key FRs covered

- FR-LLM-001 — Support registering LLMs (extended: ensembles are composite LLMs)
- FR-LLM-003 — Store LLM registrations in global SQLite
- FR-LLM-017 — API keys never stored; only env var name
- FR-RUN-013 — `resume` creates a new run from parent checkpoint (must handle ensemble parent)

---

## Architecture decisions (resolved)

| Question | Decision |
|---|---|
| Ensemble storage | Normalized two tables: `ensembles (id, name, created_at)` + `ensemble_members (ensemble_id, llm_name, weight, temperature_override, max_tokens_override)` |
| DB migration version | v8 (v7 is current) |
| How `run info` distinguishes single vs ensemble | `llm_type TEXT DEFAULT 'single'` column on `runs` + `llm_snapshot TEXT` JSON column |
| Unified `--llm` lookup | `resolve_llm_or_ensemble(name) -> LLMEntry \| EnsembleEntry` in `core/llm.py` |
| Per-model overrides | Supported: per-member `temperature` and `max_tokens` in `ensemble_members` |
| OE field mapping | OE uses `name` (not `model`) and `api_base` (not `base_url`) in `LLMModelConfig` |
| Weight normalization | OE auto-normalizes — Revolver warns if sum is not close to 1.0 but does NOT auto-normalize |
| Resume ensemble↔single | Any combination allowed — traceability preserved via `llm_snapshot` |

---

## Traceability snapshot design

The `llm_snapshot` column in `runs` stores a JSON blob populated at run creation time:

**Single LLM example:**
```json
{"type": "single", "name": "flash", "model": "gemini-2.5-flash", "temperature": 0.7, "max_tokens": 8192}
```

**Ensemble example:**
```json
{
  "type": "ensemble",
  "name": "alphevo",
  "members": [
    {"name": "flash-lite", "model": "gemini-2.5-flash-lite", "weight": 0.8, "api_key_env": "GEMINI_API_KEY"},
    {"name": "pro", "model": "gemini-2.5-pro", "weight": 0.2, "temperature": 0.5, "api_key_env": "GEMINI_API_KEY"}
  ]
}
```

This makes lineage **queryable** without parsing YAML. The existing `config_snapshot` (full YAML blob) remains as a secondary source.

---

## Tasks

| # | Task | Layer | PR | Status |
|---|---|---|---|---|
| S11-01 | DB migration v8: `ensembles (id, name, created_at)` + `ensemble_members (ensemble_id, llm_name, weight, temperature_override, max_tokens_override)` in **global** DB. `runs` table (project DB): add `llm_type TEXT DEFAULT 'single'` and `llm_snapshot TEXT` columns. | infra | PR-A | [ ] |
| S11-02 | `infra.db` helpers: `insert_ensemble()`, `get_ensemble()`, `list_ensembles()`, `delete_ensemble()`, `add_ensemble_member()`, `get_ensemble_members()`. | infra | PR-A | [ ] |
| S11-03 | `models.llm` — new `EnsembleMember` and `EnsembleEntry` Pydantic models. | domain | PR-A | [ ] |
| S11-04 | `core.llm` — `create_ensemble()`, `add_member()`, `remove_ensemble()`, `list_ensembles()`, `get_ensemble_info()`. Validate each member LLM exists. Warn (not error) if weights do not sum close to 1.0. | domain | PR-B | [ ] |
| S11-05 | `cli.llm` — new `ensemble` Typer sub-app: `ensemble create <name>`, `ensemble add <name> --llm <llm> --weight <w> [--temperature T] [--max-tokens N]`, `ensemble list`, `ensemble info <name>`, `ensemble remove <name> [--force]`. | cli | PR-B | [ ] |
| S11-06 | `core.llm` — `resolve_llm_or_ensemble(name)` function: try `get_llm(name)` first; if not found try `get_ensemble(name)`; raise `RevolverError` if neither. Returns `LLMEntry \| EnsembleEntry`. | domain | PR-C | [ ] |
| S11-07 | `infra.openevolve.build_config()` — when passed `EnsembleEntry`, emit `llm.models` array. Each member entry uses OE field names: `name` (not `model`), `api_base` (not `base_url`), plus `api_key_env`, `weight`, optional `temperature`, optional `max_tokens`. Single-LLM path unchanged. | infra | PR-C | [ ] |
| S11-08 | `core.run.launch_run()` + `core.run.resume_run()` — resolve via `resolve_llm_or_ensemble()`; pass `LLMEntry \| EnsembleEntry` to `build_config()`; store `llm_type` (`single`/`ensemble`) and `llm_snapshot` JSON in run record. | domain | PR-C | [ ] |
| S11-09 | `cli.run.run_start` + `cli.run.run_resume` — `--llm` resolves via `resolve_llm_or_ensemble()`. `run info` and `run list` display ensemble indicator (e.g., `alphevo (ensemble: flash-lite×0.8, pro×0.2)`). | cli | PR-C | [ ] |
| S11-10 | L2 integration tests for Sprint 011 — ensemble CRUD, ensemble in run config, `llm.models` array in OE config, `run info` ensemble display, `llm_snapshot` content verification. | test | PR-D | [ ] |
| S11-11 | Update `docs/guides/tuning-oe-config.md` — "Ensemble strategies" section: AlphaEvolve pattern, weight recommendations, per-model temperature, cost implications. | docs | PR-D | [ ] |
| S11-12 | **Documentation audit cascade** — spec-reviewer → validation-reviewer → doc-reviewer. Update specs (spec-llm: ensemble commands, spec-run: ensemble `--llm`), DES-002 (ensemble subcommands), DES-005 (ensemble in `build_config`, `llm_snapshot` field), ConOps (ensemble workflow), traceability matrix (new FRs), README, user-story-e2e. Fix all FAIL/WARN findings before release. | docs | PR-E | [ ] |

---

## Integration Tests (L2)

Target scenarios for Sprint 011. All must pass at sprint end.

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `llm ensemble create` | Create ensemble with valid name | `test_ensemble_create` | Planned |
| `llm ensemble add` | Add member LLM with weight | `test_ensemble_add_member` | Planned |
| `llm ensemble add` | Add member with nonexistent LLM → error | `test_ensemble_add_nonexistent_llm` | Planned |
| `llm ensemble list` | Lists all ensembles | `test_ensemble_list` | Planned |
| `llm ensemble info` | Displays members and weights | `test_ensemble_info` | Planned |
| `llm ensemble remove` | Removes ensemble and members | `test_ensemble_remove` | Planned |
| `llm ensemble remove` | Nonexistent ensemble → error | `test_ensemble_remove_not_found` | Planned |
| `core resolve_llm_or_ensemble` | Name resolves to LLM | `test_resolve_llm_or_ensemble_llm` | Planned |
| `core resolve_llm_or_ensemble` | Name resolves to ensemble | `test_resolve_llm_or_ensemble_ensemble` | Planned |
| `core resolve_llm_or_ensemble` | Name not found → RevolverError | `test_resolve_llm_or_ensemble_not_found` | Planned |
| `infra build_config` | `EnsembleEntry` → `llm.models` array with OE field names (`name`, `api_base`) | `test_build_config_ensemble_generates_models_array` | Planned |
| `infra build_config` | Per-member temperature override in `llm.models` | `test_build_config_ensemble_per_member_temperature` | Planned |
| `infra build_config` | Single LLM path unchanged (no regression) | `test_run_start_single_llm_no_regression` | Planned |
| `run start --llm` | `--llm` resolves ensemble name → run created with `llm_type='ensemble'` and `llm_snapshot` populated | `test_run_start_with_ensemble` | Planned |
| `run info` | Ensemble run shows `llm_type: ensemble`, member names and weights from `llm_snapshot` | `test_run_info_ensemble_display` | Planned |
| `run resume --llm` | Resume with ensemble → `llm_snapshot` updated for new run | `test_resume_llm_ensemble_override` | Planned |
| `run start --llm` | Single-LLM run stores valid `llm_snapshot` JSON | `test_run_start_llm_snapshot_single` | Planned |

**Cumulative L2 tests at sprint end: ~982 total (~965 previous + ~17 new)**

---

## Parallelization

### Dependency graph

```
Sprint 010 complete ──> S11-01 (infra: DB migration v8)           ← foundation
                              |
                              v
                        S11-02 (infra: db helpers)                ← sequential with S11-01
                              |
                              v
                        S11-03 (models: EnsembleMember/EnsembleEntry)  ← sequential
                              |
                        [PR-A merged] ──────────────────────────────────
                              |
              ┌───────────────┴─────────────────────┐
              v                                     v
        S11-04 (domain: core ensemble CRUD)   S11-06 (domain: resolve_llm_or_ensemble)
              |                                     |
        S11-05 (cli: llm ensemble commands)   S11-07 (infra: build_config ensemble)
              |                                     |
           [PR-B]                            S11-08 (domain: launch_run/resume_run)
                                                    |
                                             S11-09 (cli: run --llm ensemble)
                                                    |
                                                 [PR-C]
                                                    |
                                      [PR-B + PR-C merged]
                                                    |
                                         S11-10 (test: L2 integration)
                                         S11-11 (docs: ensemble guide)
                                                    |
                                                 [PR-D]
                                                    |
                                         S11-12 (docs: audit cascade)
                                                    |
                                                 [PR-E]
```

### Critical path

Sprint 010 → S11-01 → S11-02 → S11-03 → S11-06 → S11-07 → S11-08 → S11-09 → S11-10 → S11-12

Estimated sequential depth: 9 steps. DB foundation (PR-A) blocks all domain work.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — DB foundation | S11-01, S11-02, S11-03 | Sprint 010 done | Agent 1 |
| B — Ensemble CRUD | S11-04, S11-05 | PR-A merged | Agent 2 |
| C — Run integration | S11-06, S11-07, S11-08, S11-09 | PR-A merged | Agent 3 |
| D — Tests + Docs | S11-10, S11-11 | PR-B and PR-C merged | Agent 1 or 4 |
| E — Audit cascade | S11-12 | PR-D merged | Agent 1 or 4 |

Peak parallelism: 2 agents after PR-A (Streams B and C in parallel).

### Conflict risks

- **`src/revolver/infra/db.py`** — Stream A (S11-01, S11-02) modifies global DB schema and adds helpers. Merge PR-A completely before starting B and C.
- **`src/revolver/infra/openevolve.py`** — Stream C (S11-07) modifies `build_config()`. Ensure Sprint 010 is fully merged first.
- **`src/revolver/core/run.py`** — Stream C (S11-08) modifies `launch_run()` and `resume_run()`. Ensure Sprint 010 is fully merged first.
- **`src/revolver/cli/llm.py`** — Stream B (S11-05) adds a new `ensemble` sub-app. Low conflict risk (additive).
- **`src/revolver/models/run.py`** — Stream C (S11-08) may add `llm_type`/`llm_snapshot` fields to `RunInfo`, `RunSummary`, `RunManifest`. Coordinate with PR-A (S11-03 also touches `models/llm.py`).

---

## Open questions / risks

All previously open questions are now resolved by the POC (2026-03-28):

1. **OE ensemble format** — VALIDATED: `llm.models` array works. OE uses `name` (not `model`) and `api_base` (not `base_url`) in `LLMModelConfig`. Single model in array works as edge case.
2. **Weight normalization** — OE auto-normalizes weights. Revolver should warn if sum deviates from 1.0 (threshold: `|sum - 1.0| > 0.01`) but must NOT auto-normalize to preserve user intent.
3. **API key per member** — Each member inherits `api_key_env` from its registered LLM. The `ensemble_members` table does not store `api_key_env` directly; it is resolved at `build_config()` time from the member's `LLMEntry`.
4. **Resume ensemble↔single** — Any combination allowed (ensemble→single, single→ensemble, ensemble→different ensemble). The `llm_snapshot` on the *new* run records the actual LLM used for that run leg, ensuring full traceability.

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / 17 new integration tests passing

### Demo-able features
- [ ] `revolver llm ensemble create alphevo` + `ensemble add` — ensemble registration
- [ ] `revolver llm ensemble list` and `revolver llm ensemble info alphevo` — ensemble inspection
- [ ] `revolver run start --llm alphevo` — run with ensemble (OE config has `llm.models` array with `name`/`api_base` fields)
- [ ] `revolver run info <id>` — shows `ensemble: alphevo (flash-lite × 0.8, pro × 0.2)` from `llm_snapshot`
- [ ] Single-LLM run stores `llm_snapshot` JSON (traceability improvement, no UX change)

### Carry-over
_TBD at sprint end._
