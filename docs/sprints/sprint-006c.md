# Sprint 006c — LLM Registry Config & Iteration Tracking

**Status**: Planning
**Goal**: Two features from POC local LLMs feedback: (1) store `max_tokens` and `timeout` per LLM in the registry, auto-inject into OpenEvolve config via `build_config()`; (2) compute iteration success rate from OpenEvolve checkpoint after run, store in run metadata and display in `run info`. Target release: v0.6.3.
**Demo**: `revolver llm add codestral-local ollama codestral:22b --max-tokens 8192 --timeout 120` stores config; `revolver run start` auto-applies without `--config-override`; `revolver run info` shows `Iterations: 42/100 valid (42%)`.

---

## Scope

### Feature 1 — LLM registry per-model config (`max_tokens`, `timeout`)

| Item | Detail |
|---|---|
| Problem | `max_tokens` and `timeout` vary by LLM (small model: 4096/60s, large: 8192/300s) but currently require `--config-override llm.max_tokens=N` on every run |
| Solution | Store `max_tokens` and `timeout` as optional fields on `LLMEntry`, inject into `build_config()` at step 2 (after problem config, before `--config-override`) |
| Priority injection | problem `config.yaml` → **LLM registry values** → `--config-override` (manual override always wins) |

### Feature 2 — Iteration success rate tracking

| Item | Detail |
|---|---|
| Problem | OpenEvolve handles invalid diffs silently via MAP-Elites — no visibility on how many iterations produced valid code |
| Solution | After run, read `database.json` from checkpoint, count programs, compute `valid_iterations / total_iterations` ratio |
| Storage | New fields on `RunManifest`, `RunInfo`, `RunSummary`; stored in `runs` DB table |
| Display | `run info` shows iteration stats; `run list` shows success rate column |

### Explicitly out of scope

| Item | Reason |
|---|---|
| `llm recommend-config` / presets | User rejected — too many models, too fast-moving |
| Per-iteration error categorization | Requires log parsing, fragile dependency on OpenEvolve internals |
| Per-iteration token breakdown | Not available from OpenEvolve or token proxy |
| F2 — split='train' warning | Deferred, minor and not actionable |

---

## Tasks

### Feature 1 — LLM per-model config

| # | Task | PR | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S6c-01 | **Model** — Add `max_tokens: int \| None` and `timeout_s: int \| None` to `LLMEntry` in `models/llm.py` | PR-A | — | [ ] | Fields are optional, default `None`, model still frozen |
| S6c-02 | **DB migration v4** — Add `max_tokens INTEGER` and `timeout_s INTEGER` columns to `llms` table; update `CURRENT_SCHEMA_VERSION` to 4; add migration 3→4 | PR-A | S6c-01 | [ ] | Existing DBs migrate cleanly; new DBs create with both columns; `SELECT max_tokens, timeout_s FROM llms` works |
| S6c-03 | **Core** — Update `register_llm()` and `update_llm()` in `core/llm.py` to accept and persist `max_tokens` and `timeout_s` | PR-A | S6c-02 | [ ] | Values round-trip through register → DB → get |
| S6c-04 | **CLI** — Add `--max-tokens` and `--timeout` options to `llm add` and `llm update` in `cli/llm.py`; display in `llm list` and `llm info` (if set) | PR-A | S6c-03 | [ ] | `llm add --max-tokens 8192 --timeout 120` stores values; `llm list` shows non-null values |
| S6c-05 | **Config injection** — In `build_config()`, inject `llm.max_tokens` and `llm.timeout` from `LLMEntry` at step 2 (after problem config, before config overrides) | PR-A | S6c-01 | [ ] | Values appear in merged config; `--config-override` still wins; `None` values are not injected |
| S6c-06 | **Tests** — L1 unit tests for model/DB/core changes + L2 integration tests for CLI and config injection | PR-A | S6c-04, S6c-05 | [ ] | `test_llm_add_with_max_tokens_timeout`, `test_llm_update_max_tokens`, `test_build_config_injects_llm_settings`, `test_config_override_wins_over_registry`, `test_migration_v3_to_v4` |

### Feature 2 — Iteration success rate

| # | Task | PR | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S6c-07 | **Model** — Add `valid_iterations: int \| None` to `RunManifest`, `RunResult`, `RunInfo`, `RunSummary` in `models/run.py` | PR-B | — | [ ] | Field optional, default `None`, no breaking change |
| S6c-08 | **DB** — Add `valid_iterations INTEGER` column to `runs` table (in same migration v4 as S6c-02) | PR-B | — | [ ] | Column nullable, existing runs keep `NULL` |
| S6c-09 | **Core** — After OpenEvolve run, read `database.json` from checkpoint dir, count programs, store as `valid_iterations` in run record | PR-B | S6c-07, S6c-08 | [ ] | `valid_iterations` populated for completed runs; graceful fallback to `None` if checkpoint unreadable |
| S6c-10 | **CLI** — Display iteration stats in `run info` (e.g. `Iterations: 42/100 valid (42%)`) and `run list` (success rate column) | PR-B | S6c-09 | [ ] | `run info` shows stats when available; `run list` shows `—` when `None` |
| S6c-11 | **Tests** — L1 unit test for checkpoint parsing + L2 integration tests for display | PR-B | S6c-10 | [ ] | `test_parse_checkpoint_database`, `test_run_info_shows_valid_iterations`, `test_run_list_success_rate` |

---

## Integration Tests (L2)

| Component | Scenario | Test ID | PR |
|---|---|---|---|
| `llm add` | Register with `--max-tokens 8192 --timeout 120` | `test_llm_add_with_max_tokens_timeout` | PR-A |
| `llm update` | Update `max_tokens` on existing LLM | `test_llm_update_max_tokens` | PR-A |
| `llm list` | Display max_tokens/timeout columns when set | `test_llm_list_shows_config` | PR-A |
| `build_config` | LLM registry values injected into OE config | `test_build_config_injects_llm_settings` | PR-A |
| `build_config` | `--config-override` wins over registry values | `test_config_override_wins_over_registry` | PR-A |
| DB migration | v3→v4 adds columns, existing data preserved | `test_migration_v3_to_v4` | PR-A |
| `run info` | Shows `valid_iterations` when available | `test_run_info_shows_valid_iterations` | PR-B |
| `run list` | Shows success rate column | `test_run_list_success_rate` | PR-B |
| checkpoint | Parse `database.json`, count programs | `test_parse_checkpoint_database` | PR-B |

---

## Parallelization

### Dependency graph

```
                    ┌── S6c-01 (model: LLMEntry) ──┐
                    │                                ├── S6c-03 (core: register/update)
                    │   S6c-02 (DB migration v4) ───┤           │
                    │                                │      S6c-04 (cli: llm add/update)
                    │                                │           │
PR-A (LLM config) ─┤                                └── S6c-05 (config: build_config)
                    │                                            │
                    └────────────────────────────────── S6c-06 (tests)

                    ┌── S6c-07 (model: RunManifest) ─┐
                    │                                  ├── S6c-09 (core: checkpoint parse)
PR-B (iteration) ──┤   S6c-08 (DB: valid_iterations) ┘           │
                    │                                    S6c-10 (cli: run info/list)
                    │                                             │
                    └─────────────────────────────────── S6c-11 (tests)
```

### Parallel work streams

| Stream | Tasks | Agent |
|---|---|---|
| A — LLM per-model config | S6c-01 → S6c-06 | Agent 1 (worktree) |
| B — Iteration success rate | S6c-07 → S6c-11 | Agent 2 (worktree) |

**Conflict point**: S6c-02 and S6c-08 both modify `infra/db.py` (migration v4). Resolution: **bundle into a single PR** or coordinate — Agent A owns the migration file, Agent B adds its column to the same migration.

**Recommended approach**: Single PR with both features. The DB migration is shared (v3→v4 adds 3 columns: `max_tokens`, `timeout_s`, `valid_iterations`). One agent, one branch, avoids merge conflicts on `db.py`.

### Files modified

| Feature | Files |
|---|---|
| LLM config | `models/llm.py`, `infra/db.py`, `core/llm.py`, `cli/llm.py`, `infra/openevolve.py` |
| Iteration tracking | `models/run.py`, `infra/db.py`, `core/run.py`, `cli/run.py`, `infra/openevolve.py` |
| Tests | `tests/test_models_llm.py`, `tests/integration/test_llm.py`, `tests/test_openevolve.py`, `tests/test_models_run.py`, `tests/integration/test_run.py` |

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- 0 / ~9 new integration tests
- 0 / ~720 total cumulative tests (710 + ~10 new)

### PRs merged
| PR | Branch | Scope | Session |
|---|---|---|---|
| — | `feature/s6c-llm-config-iteration-tracking` | LLM config + iteration tracking | — |

### Demo-able features
- [ ] `revolver llm add <name> ollama <model> --max-tokens 8192 --timeout 120` stores config
- [ ] `revolver llm list` shows max_tokens/timeout columns
- [ ] `revolver run start` auto-injects max_tokens/timeout from LLM registry
- [ ] `--config-override` overrides registry values
- [ ] `revolver run info <id>` shows iteration success rate
- [ ] `revolver run list` shows success rate column
- [ ] DB migration v3→v4 transparent on existing projects
