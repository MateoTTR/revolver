# Sprint 011 — Multi-Model Ensemble Support (v0.11.0)

**Status**: Planning
**Goal**: Support OpenEvolve's native multi-model ensemble (`llm.models` array) so users can run AlphaEvolve-style ensembles (e.g. Flash 80% + Pro 20%) without editing raw YAML. Deliver named ensemble entities in the LLM registry, ensemble-aware `build_config()`, and CLI options for ensemble selection on `run start`/`run resume`.
**Demo**: `revolver llm ensemble create alphevo --add flash-lite:0.8 --add pro:0.2` registers an ensemble; `revolver run start --llm alphevo` runs OE with two models weighted 80/20; `revolver run info` shows ensemble name and member models in lineage.

---

## Source

- Demo feedback: `/home/mathi/revolver-demos/beamforming/demos/demo-v0.9.0/feedback.md` (F3 — Multi-model ensemble)
- Feedback summary: `/home/mathi/revolver-demos/feedback-summary.md`
- Predecessor: Sprint 010 (v0.10.0)
- Any Sprint 010 carry-over (notably B13 if not completed)

---

## Feature scope: F3 — Multi-model ensemble

### Problem

OpenEvolve supports a `llm.models` array in YAML for ensemble evolution:

```yaml
llm:
  models:
    - model: gemini-2.5-flash-lite
      base_url: https://generativelanguage.googleapis.com/v1beta/openai
      api_key_env: GEMINI_API_KEY
      weight: 0.8
    - model: gemini-2.5-pro
      base_url: https://generativelanguage.googleapis.com/v1beta/openai
      api_key_env: GEMINI_API_KEY
      weight: 0.2
      temperature: 0.5
```

Revolver currently only supports a single LLM via `--llm`, building a `llm.model` (singular) in `build_config()`. There is no way to use multi-model ensembles without editing the raw OE YAML manually.

### Design options

Two approaches for ensemble representation:

**Option A — Named ensemble entity in DB** (preferred):
- New `ensembles` table in global DB with ensemble name + members (JSON array or normalized `ensemble_members` table)
- `llm ensemble create`, `llm ensemble add`, `llm ensemble list`, `llm ensemble info`, `llm ensemble remove` subcommands
- `--llm` on `run start`/`run resume` accepts either a registered LLM name or a registered ensemble name
- Traceability: run metadata stores `llm_name` (ensemble name) or `ensemble_id`

**Option B — Inline syntax on CLI** (simpler, no DB change):
- `--llm flash:0.8,pro:0.2` syntax parsed at run time
- No persistent ensemble definition
- Less ergonomic for repeated use

**Decision**: Option A (named ensemble entity). Gives traceability (run → ensemble definition), repeatability, and better UX. ADR may be needed if the DB schema change is significant.

---

## Scope

### Command groups included

- `revolver llm ensemble` — new subcommand group: create, list, info, add (member), remove
- `revolver run` — `--llm` accepts ensemble name; `build_config()` emits `llm.models` array when ensemble used
- `revolver infra` (DB) — migration to add `ensembles` and `ensemble_members` tables
- `docs/guides` — ensemble strategies guide section

### Key FRs covered

- FR-LLM-001 — Support registering LLMs (extended: ensembles are composite LLMs)
- FR-LLM-003 — Store LLM registrations in global SQLite
- FR-LLM-017 — API keys never stored; only env var name
- FR-RUN-013 — `resume` creates a new run from parent checkpoint (must handle ensemble parent)

### Carry-over from Sprint 010

- B13 (`run population`) if not completed in Sprint 010

---

## Architecture decisions needed before implementation

| Question | Options | Recommendation |
|---|---|---|
| Ensemble storage: single `ensembles` table with JSON members, or normalized `ensemble_members` join table? | JSON simpler, normalized more queryable | Normalized (two tables): `ensembles (id, name, created_at)` + `ensemble_members (ensemble_id, llm_name, weight, temperature_override)` |
| DB migration version | Currently v7 | v8 for ensemble tables |
| How does `run info` distinguish single-LLM vs ensemble? | `llm_type: "single"/"ensemble"` column on runs, or check if `llm_name` resolves to ensemble | Add `llm_type` column to `runs` table (migration v8) |
| Does `--llm` resolution need a unified lookup? | Currently `get_llm(name)` → `LLMEntry`; now may also resolve ensemble | New `resolve_llm_or_ensemble(name) -> LLMEntry | EnsembleEntry` function in `core/llm.py` |
| Per-model overrides in ensemble (temperature, max_tokens)? | Member-level config vs ensemble-level | Support per-member `temperature` and `max_tokens` stored in `ensemble_members` |

---

## Tasks (coarse-grained — to be refined before sprint start)

| # | Task | Layer | PR | Status |
|---|---|---|---|---|
| S11-01 | DB migration v8: `ensembles (id, name, created_at)` + `ensemble_members (ensemble_id, llm_name, weight, temperature, max_tokens)` tables in global DB. `runs` table: add `llm_type TEXT DEFAULT 'single'` column in project DB. | infra | PR-A | [ ] |
| S11-02 | `infra.db` helpers: `insert_ensemble()`, `get_ensemble()`, `list_ensembles()`, `delete_ensemble()`, `add_ensemble_member()`, `get_ensemble_members()`. | infra | PR-A | [ ] |
| S11-03 | `models.llm` — new `EnsembleMember` and `EnsembleEntry` Pydantic models. | domain | PR-A | [ ] |
| S11-04 | `core.llm` — `create_ensemble()`, `add_member()`, `remove_ensemble()`, `list_ensembles()`, `get_ensemble_info()` functions. Validate that each member LLM exists in registry. Validate weights sum to 1.0 (warn if not, do not error). | domain | PR-B | [ ] |
| S11-05 | `cli.llm` — new `ensemble` Typer sub-app with commands: `ensemble create <name>`, `ensemble add <name> --llm <llm> --weight <w> [--temperature T] [--max-tokens N]`, `ensemble list`, `ensemble info <name>`, `ensemble remove <name> [--force]`. | cli | PR-B | [ ] |
| S11-06 | `core.llm` — `resolve_llm_or_ensemble(name)` function: try `get_llm(name)` first; if not found try `get_ensemble(name)`; raise `RevolverError` if neither found. Returns `LLMEntry | EnsembleEntry`. | domain | PR-C | [ ] |
| S11-07 | `infra.openevolve.build_config()` — when passed an `EnsembleEntry`, emit `llm.models` array instead of `llm.model`. Each member maps to an entry with `model`, `base_url`, `api_key_env`, `weight`, optional `temperature`, optional `max_tokens`. API key resolution uses per-member `api_key_env`. | infra | PR-C | [ ] |
| S11-08 | `core.run.launch_run()` + `core.run.resume_run()` — pass resolved `LLMEntry | EnsembleEntry` to `build_config()`. Store `llm_type` (`single`/`ensemble`) and `llm_name` in run metadata. | domain | PR-C | [ ] |
| S11-09 | `cli.run.run_start` + `cli.run.run_resume` — `--llm` now resolves via `resolve_llm_or_ensemble()`. `run info` and `run list` display ensemble indicator (e.g., `llm: alphevo (ensemble: 2 models)`). | cli | PR-C | [ ] |
| S11-10 | L2 integration tests for Sprint 011 — ensemble CRUD, ensemble in run config, `llm.models` array in OE config, `run info` ensemble display. | test | PR-D | [ ] |
| S11-11 | Update `docs/guides/tuning-oe-config.md` — "Ensemble strategies" section: AlphaEvolve pattern, weight recommendations, per-model temperature config, cost implications. Update `initial-program-structure.md` if applicable. | docs | PR-D | [ ] |
| S11-12 | (Carry-over) `revolver run population <run_id>` if not completed in Sprint 010. | domain + cli | PR-D | [ ] |
| S11-13 | **Documentation audit cascade** — spec-reviewer → validation-reviewer → doc-reviewer. Update specs (spec-llm: ensemble commands, spec-run: ensemble --llm), DES-002 (ensemble subcommands), DES-005 (ensemble in build_config), ConOps (ensemble workflow), traceability matrix (new FRs), README, user-story-e2e. Fix all FAIL/WARN findings before release. | docs | PR-E | [ ] |

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
| `infra build_config` | `EnsembleEntry` → `llm.models` array in OE config | `test_build_config_ensemble_generates_models_array` | Planned |
| `infra build_config` | Per-member temperature in `llm.models` | `test_build_config_ensemble_per_member_temperature` | Planned |
| `run start --llm` | `--llm` resolves ensemble name → run config has `llm.models` | `test_run_start_with_ensemble` | Planned |
| `run start --llm` | `--llm` resolves single LLM → run config has `llm.model` (no regression) | `test_run_start_single_llm_no_regression` | Planned |
| `run info` | Ensemble run shows `llm_type: ensemble` and member names | `test_run_info_ensemble_display` | Planned |
| `run resume --llm` | Resume with ensemble override | `test_resume_llm_ensemble_override` | Planned |
| `core resolve_llm_or_ensemble` | Name resolves to LLM | `test_resolve_llm_or_ensemble_llm` | Planned |
| `core resolve_llm_or_ensemble` | Name resolves to ensemble | `test_resolve_llm_or_ensemble_ensemble` | Planned |
| `core resolve_llm_or_ensemble` | Name not found → RevolverError | `test_resolve_llm_or_ensemble_not_found` | Planned |

**Cumulative L2 tests at sprint end: ~949 total (~933 previous + ~16 new)**

---

## Parallelization

### Dependency graph

```
Sprint 010 complete ──┬──> S11-01 (infra: DB migration v8)           ← foundation
                       │         ↓
                       │    S11-02 (infra: db helpers)                ← sequential
                       │         ↓
                       │    S11-03 (models: EnsembleEntry)            ← sequential
                       │
                       │   [after S11-01..S11-03 merged] ──────────────────────────────
                       │
                       ├──> S11-04 (domain: core ensemble CRUD)       ← parallel streams start here
                       │         ↓
                       │    S11-05 (cli: llm ensemble commands)       ← PR-B
                       │
                       ├──> S11-06 (domain: resolve_llm_or_ensemble)  ← parallel with S11-04
                       │         ↓
                       │    S11-07 (infra: build_config ensemble)
                       │         ↓
                       │    S11-08 (domain: launch_run/resume_run)
                       │         ↓
                       │    S11-09 (cli: run --llm ensemble)          ← PR-C
                       │
                       └──> S11-10/S11-11/S11-12 (tests + docs + carry-over)  ← PR-D
                            [after PR-B and PR-C merged]
```

### Critical path

Sprint 010 → S11-01 → S11-02 → S11-03 → S11-06 → S11-07 → S11-08 → S11-09 → S11-10

Estimated sequential depth: 8 steps (longer than typical — DB foundation blocks all domain work).

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — DB foundation | S11-01, S11-02, S11-03 | Sprint 010 done | Agent 1 |
| B — Ensemble CRUD | S11-04, S11-05 | PR-A merged | Agent 2 |
| C — Run integration | S11-06, S11-07, S11-08, S11-09 | PR-A merged | Agent 3 |
| D — Tests + Docs | S11-10, S11-11, S11-12 | PR-B and PR-C merged | Agent 1 or 4 |

Peak parallelism: 2 agents after PR-A (Streams B and C in parallel).

### Conflict risks

- **`src/revolver/infra/db.py`** — Stream A (S11-01, S11-02) modifies global DB schema and adds helpers. Stream C (S11-07 indirectly reads LLM data) reads but does not write schema. Merge A completely before starting B and C.
- **`src/revolver/infra/openevolve.py`** — Stream C (S11-07) modifies `build_config()`. Sprint 010 may also have modified this file (PR-A, PR-D). Ensure Sprint 010 is fully merged before Sprint 011 starts.
- **`src/revolver/core/run.py`** — Stream C (S11-08) modifies `launch_run()` and `resume_run()`. Conflicts likely with Sprint 010 carry-over. Merge Sprint 010 completely first.
- **`src/revolver/cli/llm.py`** — Stream B (S11-05) adds a new `ensemble` sub-app. Low conflict risk (additive).

---

## Open questions / risks

1. **OE ensemble format validation**: Does OE's strict config parser accept `llm.models` alongside (absent) `llm.model`? Needs empirical verification before finalizing `build_config()` implementation.
2. **Weight normalization**: Should Revolver auto-normalize weights to sum to 1.0, or warn and let OE handle it? Recommend: warn if not close to 1.0, do not auto-normalize (preserve user intent).
3. **API key per member vs shared**: All ensemble members may share the same `api_key_env` (e.g., all Gemini models use `GEMINI_API_KEY`). The `ensemble_members` table should store `api_key_env` per member defaulting to the member LLM's registered `api_key_env`.
4. **Resume with ensemble parent**: When resuming a run that used an ensemble, should `--llm` allow switching from ensemble to single, or single to ensemble? Propose: any combination allowed — traceability is maintained via the run record.

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / 16 new integration tests passing

### Demo-able features
- [ ] `revolver llm ensemble create alphevo --add flash-lite:0.8 --add pro:0.2` — ensemble registration
- [ ] `revolver llm ensemble list` and `revolver llm ensemble info alphevo` — ensemble inspection
- [ ] `revolver run start --llm alphevo` — run with ensemble (OE config has `llm.models` array)
- [ ] `revolver run info <id>` — shows `ensemble: alphevo (flash-lite × 0.8, pro × 0.2)`

### Carry-over
_TBD at sprint end._
