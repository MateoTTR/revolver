# Sprint 004b — Proxy Robustness & UX Fixes

**Status**: Planning
**Goal**: Fix all carry-over items from Sprint 004a (NF1, NF2, NF4, NF5, NF6, NF7, NF8) discovered during demo v0.4.4 sessions (codestral + Gemini). Make the proxy transparent to upstream errors, support Google provider detection through the proxy, and polish UX rough edges. Target release: v0.5.0.
**Demo**: Launch a Gemini run without `--config-override random_seed=null` workaround; observe 400 errors forwarded with real status codes; verify `run list` shows alias; confirm no false-positive wrapper warning.

---

## Scope

### Command groups affected
- `revolver run` — proxy behavior, config building, wrapper evaluator warning, `run list` output
- `revolver problem` — `problem version` duplicate content UX

### Key FRs covered
- FR-RUN-028 — Token proxy must transparently forward upstream HTTP responses
- FR-RUN-006 — Configure OpenEvolve LLM endpoint from registry (Google provider detection)
- FR-RUN-021 — `run list` filterable and informative (alias inclusion)
- FR-RUN-023 — `--config-override` key=value pairs (`null`/`none` support)

### Feedback items addressed

| ID | Finding | Severity | Source |
|---|---|---|---|
| NF5 | Proxy masks Google URL → `seed` rejected | BLOQUANT | Demo v0.4.4 (Gemini) |
| NF7 | Proxy returns 502 for all upstream errors | MOYEN | Demo v0.4.4 (Gemini) |
| NF8 | No `Retry-After` header forwarding | MOYEN | Demo v0.4.4 (Gemini) |
| NF6 | `_parse_value()` no `null`/`none` support | MOYEN | Demo v0.4.4 (Gemini) |
| NF1 | False-positive dual-function warning on wrapper | MINEUR | Demo v0.4.4 (codestral) |
| NF2 | Alias absent from `run list` / `run list --json` | MINEUR | Demo v0.4.4 (codestral) |
| NF4 | Initial program structure best practices | DOC | Demo v0.4.4 (codestral) |

### Explicitly out of scope

| Item | Reason |
|---|---|
| NF9 — Thinking mode breaks diff parser | OpenEvolve upstream; tracked as backlog #120/#121 |
| NF3 — Pre-flight score=1.0 auto-referential | By design (confirms evaluator works, not quality) |
| NF8 full — Retry logic in OpenEvolve | Out of Revolver's control |
| `--json` on all subcommands | Sprint 007 (S7-05, task #102) |

---

## Tasks

| # | Task | PR | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| 123 | **FB-01** — Forward upstream HTTP status code + body in proxy instead of generic 502. `HTTPError` has `.code` and `.read()` — propagate them. Non-HTTP errors (connection refused, DNS) remain 502. | A | — | [ ] | Unit test: proxy returns 400 with upstream body on 400 response; returns 429 with body on 429; returns 502 only for connection errors |
| 124 | **FB-02** — In `build_config()`, detect Google provider (check LLM's `base_url` before proxy replacement) and set `random_seed=None` in config. Prevents OpenEvolve from sending `seed=42` to Google. | A | — | [ ] | Unit test: `build_config()` with Google base_url sets `random_seed: null`; non-Google LLMs unaffected; existing `random_seed` override preserved |
| 125 | **FB-03** — Forward `Retry-After` header from upstream responses. Free once FB-01 is implemented — the header is already in the upstream response headers being forwarded. Verify it's not stripped. | A | 123 | [ ] | Unit test: proxy forwards `Retry-After` header from 429 response |
| 126 | **FB-04** (stretch) — Optional proxy-level backoff on 429 with `Retry-After` delay before returning response to client. Configurable via `TokenCountingProxy(backoff_on_429=True)`. | A | 123, 125 | [ ] | Unit test: when `backoff_on_429=True` and upstream returns 429 with `Retry-After: 2`, proxy waits ~2s before returning; when False, returns immediately |
| 127 | **FB-05** — Add `null`/`none` → `None` support in `_parse_value()`. Two-line fix. | B | — | [ ] | Unit test: `_parse_value("null")` returns `None`; `_parse_value("None")` returns `None`; `_parse_value("NULL")` returns `None`; existing types unaffected |
| 128 | **FB-06** — Suppress the false-positive dual-function warning when the evaluator being checked is the generated wrapper (`_revolver_evaluator.py`), not the user's evaluator. The warning should only fire during `generate_wrapper()` on the **user's** evaluator file. | B | — | [ ] | Unit test: `generate_wrapper()` with user evaluator having both functions → warning emitted; wrapper evaluator loaded during pre-flight → no warning |
| 129 | **FB-07** — Include alias (from rank-1 solution) in `run list` and `run list --json` output. LEFT JOIN `solutions` table on `run_id` with `rank=1` in the `list_runs` DB query. Add `alias` field to `RunSummary` model. | B | — | [ ] | Unit test: `run list` after run with `--alias foo` shows `foo` in output; `--json` output includes `"alias": "foo"`; run without alias shows `null`/`—` |
| 130 | **FB-08** (bonus) — `problem version` with identical content → friendly "Content unchanged since vX.X" message instead of raw `UNIQUE constraint failed` error. Detect duplicate hash before INSERT. | B | — | [ ] | Unit test: second `problem version` with same content → exit 1 with user-friendly message mentioning the existing version tag; different content → succeeds normally |
| 131 | **FB-09** — Write a guide on best practices for structuring initial programs: small functions, hints in EVOLVE-BLOCKs, stubs. Based on codestral 0%→100% finding (NF4). | C | — | [ ] | Guide exists in `docs/guides/initial-program-structure.md`; covers function decomposition, EVOLVE-BLOCK hints, stub patterns; references TSP v1→v2 example |

---

## Integration Tests (L2)

Tests to add or verify at sprint end:

| Component | Scenario | Test ID | Status |
|---|---|---|---|
| `token_proxy` | Upstream returns 400 → proxy forwards 400 + body | `test_proxy_forwards_400_status` | Planned |
| `token_proxy` | Upstream returns 429 + Retry-After → proxy forwards both | `test_proxy_forwards_429_with_retry_after` | Planned |
| `token_proxy` | Upstream connection refused → proxy returns 502 | `test_proxy_returns_502_on_connection_error` | Planned |
| `token_proxy` | Token counting still works on 200 responses after error handling changes | `test_proxy_token_counting_unchanged` | Planned |
| `build_config` | Google LLM → `random_seed=None` injected | `test_build_config_google_disables_seed` | Planned |
| `build_config` | Non-Google LLM → `random_seed` untouched | `test_build_config_non_google_seed_unchanged` | Planned |
| `_parse_value` | `null`/`none`/`None` → Python `None` | `test_parse_value_null_none` | Planned |
| `generate_wrapper` | User evaluator with both functions → warning on stderr | `test_wrapper_warns_dual_function_user_evaluator` | Planned |
| `generate_wrapper` | Wrapper evaluator pre-flight → no warning | `test_wrapper_no_warning_on_generated_wrapper` | Planned |
| `run list` | Run with alias → alias shown in list output | `test_run_list_shows_alias` | Planned |
| `run list --json` | Run with alias → `alias` field in JSON | `test_run_list_json_includes_alias` | Planned |
| `problem version` | Identical content → friendly error with existing tag | `test_problem_version_duplicate_content_friendly_error` | Planned |

**Cumulative L2 tests passing: 52 + N (sprints 001–004 + 004b additions)**

---

## Parallelization

### Dependency graph

```
Sprint 004a complete (v0.4.4 — all carry-over items identified)
  │
  ├──> PR A: Proxy robustness (FB-01, FB-02, FB-03, FB-04)
  │         FB-01 (forward status codes)
  │           ↓
  │         FB-03 (Retry-After header — free from FB-01)
  │           ↓
  │         FB-04 (optional backoff — stretch)
  │         FB-02 (Google seed detection — independent)
  │
  ├──> PR B: Config + UX fixes (FB-05, FB-06, FB-07, FB-08)
  │         FB-05 (null/none parse — independent)
  │         FB-06 (suppress wrapper warning — independent)
  │         FB-07 (alias in run list — independent)
  │         FB-08 (duplicate version message — independent)
  │
  └──> PR C: Documentation (FB-09)
              FB-09 (initial program guide — independent)
```

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Proxy robustness | FB-01, FB-02, FB-03, FB-04 | Sprint 004a done | Agent 1 (worktree) |
| B — Config + UX fixes | FB-05, FB-06, FB-07, FB-08 | Sprint 004a done | Agent 2 (worktree) |
| C — Documentation | FB-09 | Sprint 004a done | Agent 3 (or main) |

Peak parallelism: 3 agents simultaneously (all streams independent).

### Conflict risks
- **`infra/token_proxy.py`** — PR A only; no conflict with PR B or C
- **`infra/openevolve.py`** — PR A (FB-02: `build_config()`) and PR B (FB-05: `_parse_value()`) both modify this file. Coordinate: FB-02 touches `build_config()` body (Google detection), FB-05 touches `_parse_value()` (separate function). Low conflict risk but merge order matters — merge PR B first (smaller change) then PR A.
- **`core/run.py`** — PR B only (FB-06: `generate_wrapper()` warning suppression). No conflict with PR A.
- **`infra/db.py`** — PR B only (FB-07: `list_runs` query, FB-08: duplicate version detection). No conflict with PR A.
- **`models/run.py`** — PR B only (FB-07: `RunSummary.alias` field). No conflict.

---

## Sprint Review

_(To be filled at sprint end)_

### Tests passing
- TBD

### PRs merged
| PR | Branch | Scope | Sessions |
|---|---|---|---|
| TBD | `feature/s4b-proxy-robustness` | FB-01, FB-02, FB-03, FB-04 | TBD |
| TBD | `feature/s4b-config-ux-fixes` | FB-05, FB-06, FB-07, FB-08 | TBD |
| TBD | `docs/s4b-initial-program-guide` | FB-09 | TBD |

### Demo-able features
- [ ] Gemini run works without `--config-override random_seed=null` workaround
- [ ] 400/429 errors show real upstream status + body (not generic 502)
- [ ] `--config-override random_seed=null` works (null/none parsing)
- [ ] No false-positive wrapper warning during pre-flight check
- [ ] `run list` shows alias from rank-1 solution
- [ ] `problem version` with identical content shows friendly message

### Carry-over
_(To be filled at sprint end)_
