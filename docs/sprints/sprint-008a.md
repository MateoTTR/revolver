# Sprint 008a — Scriptability & UX Polish (v0.8.1)

**Status**: Planning
**Goal**: Improve scripting support, user experience, and documentation consistency. Delivers `llm update`, bulk run delete, problem version delete, real-time run progress, smarter defaults for `run`, UX fixes for misleading help text, and a full documentation alignment pass (README, user story E2E, specs, ConOps, architecture, traceability matrix). Target release: v0.8.1.
**Demo**: `revolver llm update claude-sonnet --max-tokens 16384` modifies the LLM without removing it; `revolver run delete --all --force` purges all runs; `revolver run` auto-selects the latest version and the only train dataset; `revolver run start` shows real-time iteration progress; `revolver benchmark results` help text no longer references `--format csv`.

---

## Source

- Demo feedback: `/home/mathi/revolver-demos/tsp/demos/benchmark-multimodel/feedback.md`
- CLI consistency audit: session 036 (2026-03-21)
- Pre-sprint doc audit: session 038 (2026-03-22) — spec-reviewer + manual review
- Predecessor: Sprint 008 (v0.8.0)

---

## Findings from benchmark demo (P3 priority)

| ID | Severity | Area | Description | Sprint action |
|---|---|---|---|---|
| FR6 | P3 | cli/core | No `llm update` command — must remove+add to change config | Implement `llm update` |
| FR2 | P3 | cli | No `run delete --all` for bulk cleanup | Implement `--all` flag on `run delete` |
| FR3 | P3 | cli | No `problem version delete` | Implement command with dependency check |
| FR7 | P3 | cli | Run progress is buffered — no feedback during evolution | Real-time progress output |
| P2 | P3 | cli | `project init` always creates template files | Add `--no-templates` flag |
| P4 | P3 | cli | `run` requires `--version` even when only one version exists | Smart default (latest version) |
| P5 | P3 | cli | `run` requires `--dataset` even when only one train dataset exists | Smart default (only train dataset) |
| P6 | P3 | cli | `benchmark results` help tip mentions `--format csv` (doesn't exist) | Fix help text |
| P7 | P3 | docs | `-s local` vs `--provider ollama` confusion in docs/help | Clarify help text |

## Findings from CLI consistency audit

Full audit of 37 subcommands comparing `--help` output, spec docs, and code implementation.

| ID | Severity | Area | Description | Sprint action |
|---|---|---|---|---|
| C1 | CRITICAL | spec | `llm add --source`: spec says `ollama`, code accepts `local` | Update spec-llm to match code (`local`/`remote`) |
| C2 | CRITICAL | spec | `--max-tokens` and `--timeout` on `llm add`: implemented but not in spec | Document in spec-llm |
| C4 | CRITICAL | spec/cli | `dataset add name`: positional in code, `--name` option in spec | Update spec-dataset to match code (positional) |
| C5 | CRITICAL | spec/cli | `dataset add --split`: required in spec, optional in code | Decide and align (recommend: make required in code) |
| C6 | CRITICAL | spec/cli | `dataset add --compatible-with`: required in spec, optional in code | Decide and align (recommend: keep optional) |
| W5 | WARNING | spec/cli | `solution list --sort`: in spec but not implemented | Remove from spec (low value) |
| W6 | WARNING | spec/cli | `run list --sort`: in spec but not implemented | Remove from spec (low value) |
| W9 | WARNING | spec | Specifications index omits `benchmark list` and `benchmark delete` | Update spec index |
| W10 | WARNING | spec | `benchmark delete` implemented but not in spec-benchmark | Add to spec-benchmark |
| W11 | WARNING | spec/cli | `project init name`: optional in spec, required in code | Update spec to match code (required) |

## Findings from pre-sprint documentation audit (session 038)

Cross-document consistency review (spec-reviewer agent + manual verification).

| ID | Severity | Area | Description | Sprint action |
|---|---|---|---|---|
| F1 | CRITICAL | README.md | Features list: `benchmark run` (inexistant), `dataset verify` (inexistant), `doctor`/`setup` "Planned" | Rewrite README features + sprint table |
| F5 | CRITICAL | user-story-e2e.md | `--source ollama`, `--name` option, version `0.1.0`, outdated outputs | Rewrite entire E2E scenario |
| F6 | CRITICAL | conops.md §5.1 | `--source huggingface` inexistant in code | Fix to `--source local` |
| F7 | CRITICAL | cli/eval.py | CLI calls `infra.db` directly (layer violation) | Refactor through `core.eval` |
| W1 | WARNING | README.md | Test count "710+" → actual 749 | Update in README rewrite |
| W2 | WARNING | README.md | Sprint table incomplete (missing S006c–S008) | Update in README rewrite |
| W6 | WARNING | traceability-matrix.md | `run delete`, `benchmark delete` not traced | Add entries |
| W7 | WARNING | traceability-matrix.md | All 199 statuses = "Planned" despite 749 tests passing | Update statuses |
| W8 | WARNING | architecture.md §3 | `run delete`, `solution delete` missing from package tree | Update tree comments |

---

## Scope

### Command groups included
- `revolver llm` — new `update` subcommand
- `revolver run delete` — `--all` flag for bulk delete
- `revolver problem version` — new `delete` subcommand
- `revolver run` — real-time progress, smarter defaults
- `revolver project init` — `--no-templates` flag
- `revolver benchmark results` — fix misleading help text
- `revolver llm add` — clarify `-s local` help text
- `revolver eval` — refactor CLI layer to route through core (architecture fix)
- Spec docs — align with code for all CLI consistency audit findings
- User-facing docs — README.md, user-story-e2e.md, ConOps §5.1, architecture §3
- Validation docs — traceability matrix status update + missing entries

### Key FRs covered
- FR-LLM-007 — LLM update (new)
- FR-RUN-028 — `run delete --all` (new)
- FR-PRB-014 — `problem version delete` (new)
- FR-RUN-005 — smart defaults for `--version` and `--dataset`
- NFR-002 — `--help` accuracy on all commands
- NFR-003 — spec/code/help consistency (CLI audit)

---

## Tasks

| # | Task | Layer | Depends on | PR | Status | Acceptance criteria |
|---|---|---|---|---|---|---|
| S8a-01 | Implement `core.llm.update_llm(name, conn, *, max_tokens, timeout_s, input_cost_per_mtok, output_cost_per_mtok)` — modify LLM record in place without re-registering. Validate positive values. Only provided (non-None) fields are updated. | domain | — | PR-A | [ ] | `update_llm()` updates only the specified fields; unspecified fields are unchanged; `RevolverError` if LLM not found; round-trip test passes |
| S8a-02 | Add `infra.db.update_llm(conn, name, **fields)` SQL helper — builds `UPDATE llms SET ... WHERE name=?` dynamically for only the fields provided. | infra | — | PR-A | [ ] | `UPDATE` only touches provided columns; existing columns unchanged; `conn.rowcount == 0` if not found |
| S8a-03 | Implement `cli.llm.llm_update` command: `revolver llm update <name> [--max-tokens N] [--timeout N] [--input-cost F] [--output-cost F]`. Print updated entry; `--json` outputs full record. | cli | S8a-01 | PR-A | [ ] | `revolver llm update my-llm --max-tokens 16384` updates DB; `revolver llm list` reflects change; error if no update flags provided |
| S8a-04 | Add `--all` flag to `revolver run delete` (from Sprint 008 (v0.8.0)). Deletes every run in the project. Requires `--force` when `--all` is used (or confirmation prompt listing the count). | cli | Sprint 008 (v0.8.0) done | PR-B | [ ] | `revolver run delete --all --force` removes all runs + solutions + files; `revolver run delete --all` without `--force` prompts with count; `run list` returns empty after |
| S8a-05 | Implement `core.run.delete_all_runs(project_root, force)` — domain function that lists all runs then calls `delete_run()` for each. Returns count of deleted runs. | domain | Sprint 008 (v0.8.0) done | PR-B | [ ] | All runs deleted; count returned; no partial state on failure (best-effort for disk ops) |
| S8a-06 | Implement `core.problem.delete_version(tag, project_root, *, force)` — domain function: (1) check no runs reference this version (query `runs` table); (2) if runs found and not `force`: raise `RevolverError` with count; (3) if `force` or no runs: delete version snapshot from disk + DB row. | domain | — | PR-C | [ ] | Version with no runs: deleted cleanly; version with runs + no `--force`: exit 1 with "N run(s) reference this version"; version with runs + `--force`: deleted; snapshot directory removed |
| S8a-07 | Add `infra.db.delete_problem_version(conn, tag)`, `count_runs_for_version(conn, tag)` helpers. | infra | — | PR-C | [ ] | `count_runs_for_version` returns correct count; `DELETE FROM problem_versions WHERE tag=?` works |
| S8a-08 | Implement `cli.problem.problem_version_delete` command: `revolver problem version delete <tag> [--force]`. Confirmation prompt unless `--force`. | cli | S8a-06 | PR-C | [ ] | `revolver problem version delete v1.0 --force` deletes; `revolver problem version delete v1.0` with runs → error listing count; `revolver problem versions` no longer shows deleted tag |
| S8a-09 | Real-time run progress: modify `cli/run.py` to stream OpenEvolve stdout/stderr line-by-line in real time instead of capturing all output then printing. Use `subprocess` with `stdout=PIPE` line-by-line reading, or ensure the existing `asyncio.run()` path flushes output. Disable buffering in child process (`PYTHONUNBUFFERED=1`). | cli | — | PR-D | [ ] | Lines appear as they are printed by OE (not buffered until end); `--quiet` suppresses OE output; `--json` still produces valid JSON at end |
| S8a-10 | Smart default for `--version` in `revolver run`: if `--version` is omitted and exactly one problem version exists, use it automatically and print a notice ("Using version v1.2 (only version)"). If multiple exist and `--version` is omitted, error with list of available versions. | cli | — | PR-E | [ ] | Single version → auto-selected with notice; multiple versions → helpful error listing them; explicit `--version` always respected |
| S8a-11 | Smart default for `--dataset` in `revolver run`: if `--dataset` is omitted and exactly one dataset with `split='train'` exists, use it automatically and print a notice. If no train dataset exists or multiple exist and `--dataset` is omitted, error with list. | cli | — | PR-E | [ ] | Single train dataset → auto-selected with notice; multiple → error with list; no train datasets → error pointing to `dataset add --split train`; explicit `--dataset` always respected |
| S8a-12 | Add `--no-templates` flag to `revolver project init`. When set, skip writing `evaluator.py`, `initial_program.py`, `config.yaml` template files (only create `.revolver/` directory and manifest). | cli | — | PR-F | [ ] | `revolver project init --no-templates` creates `.revolver/` only; template files absent; `revolver project init` (no flag) unchanged; L2 test for both modes |
| S8a-13 | Fix `benchmark results` help text: remove the misleading tip about `--format csv`. Add a tip pointing to `revolver benchmark export --format csv` instead. | cli | — | PR-G | [ ] | `revolver benchmark results --help` no longer mentions `--format csv`; the tip text reads "For CSV export use: revolver benchmark export --format csv" |
| S8a-14 | Clarify `llm add` help text for `-s local` vs provider: update `--source` help string to clearly state "use '-s local' for Ollama (provider is set automatically)"; remove any reference to `--provider ollama`. | cli | — | PR-G | [ ] | `revolver llm add --help` shows updated source option description; no reference to `--provider ollama` |
| S8a-16 | Update spec-llm: (C1) change `--source ollama` examples to `--source local`; (C2) document `--max-tokens` and `--timeout` options on `llm add`. | docs | — | PR-I | [ ] | spec-llm §2.1 shows `--source local`, documents `--max-tokens` and `--timeout` with defaults |
| S8a-17 | Update spec-dataset: (C4) change `--name` option to positional `NAME` argument; (C5) decide `--split` required/optional and align; (C6) mark `--compatible-with` as optional. | docs | — | PR-I | [ ] | spec-dataset §2.1 matches code: `NAME` positional, `--split` aligned, `--compatible-with` optional |
| S8a-18 | Update spec-benchmark and specifications index: (W9) add `benchmark list` and `benchmark delete` to index; (W10) add `benchmark delete` section to spec-benchmark. Update spec-project (W11): mark `name` as required argument. Remove `--sort` from spec-solution (W5) and spec-run (W6). Add `run delete` to spec-run §2 and spec index. | docs | — | PR-I | [ ] | Specifications index lists all implemented commands; spec-benchmark includes `delete`; `--sort` removed from specs where not implemented; spec-run includes `delete` |
| S8a-20 | Fix conops.md §5.1 workflow: change `--source huggingface` to `--source local`, align LLM registration example with actual CLI syntax. | docs | — | PR-I | [ ] | ConOps §5.1 uses `--source local` for Ollama models; workflow matches implemented CLI |
| S8a-21 | Update architecture.md §3 package tree comments: add `delete` to `run.py` and `solution.py` inline comments. | docs | — | PR-I | [ ] | Architecture §3 tree shows `run.py # revolver run {...,delete}` and `solution.py # revolver solution {...,delete}` |
| S8a-22 | Update README.md: fix features list (`benchmark` not `benchmark run`, remove `dataset verify`, add `run delete`), update sprint table through S008, update test count, remove "Planned" for `doctor`/`setup`, add version badge. | docs | — | PR-H | [ ] | README features match implemented commands; sprint table complete through S008; test count reflects v0.8.0 |
| S8a-23 | Rewrite user-story-e2e.md: fix `--source ollama` → `--source local`, `--name` → positional, version `0.1.0` → current, update all command outputs to match current CLI behavior. | docs | — | PR-H | [ ] | All CLI commands in user story are runnable with current implementation; outputs reflect actual format |
| S8a-24 | Refactor `cli/eval.py` lines 72-98: extract re-eval existence check into `core.eval.has_existing_eval(solution, dataset)`, replace direct `infra.db` calls with core-layer function. | code | — | PR-K | [ ] | `cli/eval.py` no longer imports `get_project_db`, `get_eval_metadata`, `get_solution` from `infra.db`; existing L2 eval tests still pass |
| S8a-25 | Update traceability matrix: (W6) add entries for `run delete` and `benchmark delete`; (W7) update all 199 "Planned" statuses by verifying each test ID against `tests/` directory. | docs | — | PR-L | [ ] | Matrix contains entries for all implemented commands; statuses reflect actual test existence (Implemented/Planned) |
| S8a-19 | Write L2 integration tests for Sprint 008a features. | test | S8a-01..S8a-25 | PR-J | [ ] | `test_llm_update_max_tokens`, `test_llm_update_no_fields_error`, `test_run_delete_all`, `test_problem_version_delete_no_runs`, `test_problem_version_delete_with_runs_no_force`, `test_problem_version_delete_with_runs_force`, `test_run_smart_default_version`, `test_run_smart_default_dataset`, `test_project_init_no_templates` all pass |

---

## Integration Tests (L2)

Tests that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `llm update` | Update `max_tokens` on existing LLM — reflects in `llm list` | `test_llm_update_max_tokens` | Planned |
| `llm update` | No update flags provided → exit 1 | `test_llm_update_no_fields_error` | Planned |
| `run delete --all` | All runs deleted with `--force` | `test_run_delete_all` | Planned |
| `problem version delete` | Version with no runs → deleted | `test_problem_version_delete_no_runs` | Planned |
| `problem version delete` | Version with runs, no `--force` → error with count | `test_problem_version_delete_with_runs_no_force` | Planned |
| `problem version delete` | Version with runs + `--force` → deleted | `test_problem_version_delete_with_runs_force` | Planned |
| `run` | Only one version exists → auto-selected | `test_run_smart_default_version` | Planned |
| `run` | Only one train dataset → auto-selected | `test_run_smart_default_dataset` | Planned |
| `project init` | `--no-templates` → no template files | `test_project_init_no_templates` | Planned |

**Cumulative L2 tests at sprint end: ~157 total (148 previous + ~9 new)**

---

## PR Decomposition

| PR | Scope | Files modified | Can parallelize |
|---|---|---|---|
| PR-A | `llm update` command | `infra/db.py`, `core/llm.py`, `cli/llm.py`, `tests/` | Independent |
| PR-B | `run delete --all` | `core/run.py`, `cli/run.py`, `tests/` | Depends on Sprint 008 (v0.8.0) merged |
| PR-C | `problem version delete` | `infra/db.py`, `core/problem.py`, `cli/problem.py`, `tests/` | Independent |
| PR-D | Real-time run progress | `cli/run.py`, `infra/openevolve.py` | Independent |
| PR-E | Smart defaults for `run` | `cli/run.py`, `core/run.py` | Independent (different sections than PR-D in run.py) |
| PR-F | `project init --no-templates` | `cli/project.py`, `core/project.py`, `tests/` | Independent |
| PR-G | Help text fixes (benchmark + llm) | `cli/benchmark.py`, `cli/llm.py` | Independent |
| PR-H | User-facing docs (README + E2E user story) | `README.md`, `docs/specs/user-story-e2e.md` | Independent |
| PR-I | Spec + doc alignment (CLI audit + pre-sprint audit) | `docs/specs/spec-*.md`, `docs/specs/specifications.md`, `docs/conops/conops.md`, `docs/architecture/architecture.md` | Independent |
| PR-J | Full regression + sprint L2 tests | `tests/` | Depends on all PRs merged |
| PR-K | Eval CLI layer refactor | `cli/eval.py`, `core/eval.py` | Independent |
| PR-L | Traceability matrix update | `docs/validation/traceability-matrix.md` | Independent |

---

## Parallelization

### Dependency graph

```
Sprint 008 (v0.8.0) complete ──┬──> S8a-02 (infra: update_llm SQL)
                      │         ↓
                      │    S8a-01 (domain: update_llm)
                      │         ↓
                      │    S8a-03 (cli: llm update)  ─────────────────────────────┐
                      │                                                            │
                      ├──> S8a-07 (infra: delete_version SQL helpers)              │
                      │         ↓                                                  │
                      │    S8a-06 (domain: delete_version)                          │
                      │         ↓                                                  │
                      │    S8a-08 (cli: problem version delete) ───────────────────┤
                      │                                                            │
                      ├──> S8a-05 (domain: delete_all_runs)                        │
                      │         ↓                                                  │
                      │    S8a-04 (cli: run delete --all) ─────────────────────────┤
                      │                                                            │
                      ├──> S8a-09 (cli: real-time progress) ───────────────────────┤
                      │                                                            │
                      ├──> S8a-10 (cli: smart --version default)                   │
                      │    S8a-11 (cli: smart --dataset default) ──────────────────┤
                      │                                                            │
                      ├──> S8a-12 (cli: project init --no-templates) ──────────────┤
                      │                                                            │
                      ├──> S8a-13 (cli: help text fixes) ──────────────────────────┤
                      │    S8a-14 (cli: llm add help text) ────────────────────────┤
                      │                                                            │
                      ├──> S8a-16..S8a-21 (docs: spec + conops + arch alignment)──┤
                      │                                                            │
                      ├──> S8a-22..S8a-23 (docs: README + E2E user story) ────────┤
                      │                                                            │
                      ├──> S8a-24 (code: eval.py layer refactor) ─────────────────┤
                      │                                                            │
                      ├──> S8a-25 (docs: traceability matrix update) ─────────────┤
                      │                                                            │
                      └──────────────────────────────── S8a-19 (tests) ◄───────────┘
```

### Critical path
Sprint 008 (v0.8.0) → S8a-02 → S8a-01 → S8a-03 → S8a-19
Estimated sequential depth: 4 steps (unchanged — new tasks are all independent).

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — `llm update` | S8a-02, S8a-01, S8a-03 | Sprint 008 (v0.8.0) done | Agent 1 |
| B — `problem version delete` | S8a-07, S8a-06, S8a-08 | Sprint 008 (v0.8.0) done | Agent 2 |
| C — `run delete --all` | S8a-05, S8a-04 | Sprint 008 (v0.8.0) done | Agent 3 |
| D — Real-time progress | S8a-09 | Sprint 008 (v0.8.0) done | Agent 4 |
| E — Smart defaults | S8a-10, S8a-11 | Sprint 008 (v0.8.0) done | Agent 1 (after S8a-03) |
| F — `project init --no-templates` | S8a-12 | Sprint 008 (v0.8.0) done | Agent 2 (after S8a-08) |
| G — Help text fixes | S8a-13, S8a-14 | Sprint 008 (v0.8.0) done | Agent 3 (after S8a-04) |
| H — User-facing docs (README + E2E) | S8a-22, S8a-23 | Sprint 008 (v0.8.0) done | Agent 2 (after S8a-08) |
| I — Spec + doc alignment | S8a-16..S8a-21 | Sprint 008 (v0.8.0) done | Agent 4 (after S8a-09) |
| J — Eval CLI refactor | S8a-24 | Sprint 008 (v0.8.0) done | Agent 3 (after S8a-04) |
| K — Traceability matrix | S8a-25 | Sprint 008 (v0.8.0) done | Agent 1 (after S8a-03) |
| L — Integration tests + regression | S8a-19 | All PRs merged | Any agent |

Peak parallelism: 4 agents (Streams A, B, C, D simultaneously). Streams E–K fit into agent gaps after their first task completes.

### Conflict risks
- **`cli/run.py`** — PR-D (real-time progress, `launch_run` output) and PR-E (smart defaults, argument parsing) both touch `cli/run.py`. Coordinate merge order: merge PR-E first (argument validation at top of function), then PR-D (output loop in body). Alternatively, scope PRs to non-overlapping line ranges.
- **`infra/db.py`** — PR-A (`update_llm` helper) and PR-C (`delete_problem_version`, `count_runs_for_version`) both add functions to `infra/db.py`. Low conflict risk (additive changes in different areas of the file).
- **`cli/llm.py`** — PR-A (new `llm update` command) and PR-G (help text fix on `llm add`) both touch `cli/llm.py`. Merge PR-G first (1-line change to help string), then PR-A adds a new command function.
- **`cli/eval.py`** — PR-K (layer refactor) is the only PR touching this file. No conflict risk.
- **`docs/specs/`** — PR-I is the only PR touching spec files. PR-H touches README and user-story-e2e only. No overlap.

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- X / 9 new integration tests passing
- X / ~160 total cumulative integration tests passing

### Demo-able features
- [ ] `revolver llm update <name> --max-tokens N` modifies LLM without remove+add
- [ ] `revolver run delete --all --force` purges entire run history
- [ ] `revolver problem version delete <tag>` refuses if runs reference it (without `--force`)
- [ ] `revolver run` auto-selects version when only one exists
- [ ] `revolver run` auto-selects train dataset when only one exists
- [ ] `revolver run` shows iteration progress in real time (not buffered)
- [ ] `revolver project init --no-templates` creates bare project structure
- [ ] `revolver benchmark results --help` no longer shows misleading `--format csv` tip
- [ ] `revolver llm add --help` clearly explains `-s local` for Ollama
- [ ] All spec docs aligned with code (CLI consistency audit findings resolved)
- [ ] README.md reflects v0.8.1 feature set and sprint history
- [ ] User story E2E uses correct CLI syntax throughout
- [ ] ConOps §5.1 workflow uses `--source local`
- [ ] `cli/eval.py` no longer imports from `infra.db`
- [ ] Traceability matrix statuses reflect actual test implementation

### Carry-over
_TBD at sprint end._
