# Revolver — Integration Tests (Level 2)

**Version**: 0.4 — v0.19.0 pre-release validation review: command count from the CLI-tree walker, §2.8 benchmark delete rows, §2.10/§2.12/§2.18 test ids re-verified, S18 rows Implemented on the 1586-passed baseline, §3 fixture tree and §4 file layout redrawn from the directory, no shared mock fixtures. Previous: 0.3 — S18 sync (§2.16 semantic-slice block, §2.17 migration v14, §2.18 top-N + reap hardening + doc lint)
**Date**: 2026-10-24
**Status**: Draft
**Traceable to**: [Validation Overview](validation.md), [Specifications](../specs/specifications.md)

---

## 1. Scope

Integration tests exercise each CLI command end-to-end through Typer's `CliRunner`, with a real SQLite database and real filesystem (in `tmp_path`). External services (Ollama, LLM APIs, OpenEvolve) are mocked at the `revolver.infra` boundary.

Each `revolver <command> <subcommand>` gets at least one integration test validating the happy path and key error cases.

**47 invocable commands** at v0.19.0: 44 leaf commands — 42 under the 8 command groups (`project`, `llm`, `problem`, `dataset`, `run`, `eval`, `solution`, `benchmark`; `llm` and `problem` each nest a sub-group, `llm ensemble` and `problem version`) plus the 2 top-level commands `doctor` and `setup` — and the 3 groups that run directly (`run`, `eval`, `benchmark`). Counted with the `revolver.cli._tree.walk_commands` walker (the CLI-tree helper of the doc command-lint), which the figure in [validation.md §3](validation.md) also uses.

### L2-OE: OpenEvolve Contract Tests

A separate sub-level (L2-OE) validates the contract between Revolver and the real OpenEvolve package. These tests import and exercise real OpenEvolve classes (`Config`, `Controller`) with test fixtures -- no LLM server or GPU required. They are skipped automatically when `openevolve` is not installed (via `pytest.importorskip`) and run as a **non-blocking** CI step.

L2-OE tests catch field-mapping bugs (e.g., `base_url` vs `api_base`) that are silently swallowed by `dacite.from_dict()` when the dict keys don't match OpenEvolve's dataclass fields.

### L2-Shinka: ShinkaEvolve Contract Tests (**implemented — S14**, ADR-007)

A mirror track for the ShinkaEvolve backend, delivered in S14 across three contract suites (the `shinkaevolve` marker is also carried by the Shinka-gated tests of `tests/integration/test_solution.py` and `tests/unit/core/test_solution.py` — five modules in all at v0.19.0, [validation.md §6.4](validation.md)):

- `tests/integration/test_shinka_wrapper.py` — the generated `evaluate.py` wrapper contract
  (`metrics.json`/`correct.json` output — the top silent-bug risk of the backend initiative):
  5 golden scenarios executed against the **real** `shinka.core.run_shinka_eval` plus the same
  5 scenarios against `ShinkaBackend.generate_wrapper()` output.
- `tests/integration/test_shinka_db.py` — `programs.sqlite` reading contract (token/cost
  collection from `metadata.api_costs` + nested `metadata.llm_result`, population ranking
  without MAP-Elites fields, valid count, progress) against the shared fixture factory
  (`tests/fixtures/programs_sqlite.py`, schema verified against shinka-evolve 0.0.7).
- `tests/integration/test_run_shinka.py` — CLI-level scenarios with a mocked
  `ShinkaEvolveRunner` (launch, dry-run, resume inheritance, token storage, population, and the
  zero-scored-programs regression guarding against bogus solution collection).

Auto-skip via `pytest.importorskip("shinka.database")`; run manually in a shinka-enabled
environment (no CI step — [validation.md §6.4](validation.md)). The
"shinka not installed" tests force un-importability via the shared `no_shinka` conftest fixture,
so the whole suite passes identically with or without the `[shinka]` extra installed.

**Backend impact on the existing matrix (ADR-007)**: the engine-neutral command tests (§2.1–2.4,
§2.6–2.9, and the `run list`/`info`/`delete`/`cleanup` rows of §2.5) are unaffected. The
engine-coupled rows of §2.5 (launch, resume, status active-path, population) get a per-backend
variant in S14. S13 (refactor, no behavior change) adds tests asserting `backend='openevolve'` is
recorded end-to-end by default.

**S17 additions (v0.17 multi-LLM ensemble, ADR-007 Amendment A1–A5)**: §2.12 adds the L2-Shinka
**bandit ensemble** block (multi-member projection, `--selection {fixed,ucb,ucb1,thompson}`,
`--llm-weight`, per-sampler kwarg routing, `reasoning_effort` global-pool mapping, `capabilities()`
axes, and the B9 `--config-override` no-op warning), plus the OE-side selection-rejection and
`--llm-weight` scenarios in `test_run.py`. §2.13 adds the v12/v13 migration tests; §2.14 adds the
B1/B2/B7 correctness-slice regression tests. The generated-wrapper aggregation exec test
(`test_mixed_numeric_and_non_numeric_metrics_no_crash`, L1 unit in `tests/unit/core/test_run_wrapper.py`)
is new — no existing test previously exercised the OE wrapper aggregation.

**S18 additions (v0.18 eval-honesty semantic slice + top-N flagship, sprint-018)**: §2.16 adds the
semantic-slice block — U13 honest timeout semantics (the `combined_score` display guard, wrapper
`instances_valid`/`instances_total` coverage keys + timeout side-channel on both backends, and
`evaluation.on_timeout: penalize|drop` + `timeout_score` with the release-noted default flip to
`penalize`), U11 honest best-score display (post-run eval persisted via `core.eval.evaluate_solution`,
dual-score `run info` labels), U4 backend-on-version resolution (with the mismatch warning), U8
`validate_seed_metrics` pre-flight fail-fast, and U6 phase-2 default checkpoint cadence. §2.17 adds
the migration-v14 test (`problem_versions.backend`); §2.18 adds the top-N extraction gate
(`solution extract --rank`/`--program-id` on `capabilities().top_n_extraction`, Shinka-native / OE
consciously deferred), the #359 reap-hardening grandchild test, and the #354 doc command-lint.
**16 L2 test IDs** added by S18 — all **Implemented** (flipped at the v0.18.0 release); the full
suite stands at **1586 passed / 4 skipped** at v0.19.0 (without the engine extras). Per-command
scenario rows land in §2.3 (problem), §2.5 (run), §2.6 (eval), and §2.7
(solution). (§2.11 remains a pre-existing numbering gap — not filled; the S18 blocks append after
§2.15 without renumbering.) Test-ID form, the `integration/` prefix rule, the top-level-file
exception, and the marker-vs-level rule are defined in [validation.md §8.1](validation.md).

---

## 2. Command Test Matrix

### 2.1 `revolver project`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `project init` | Create project in empty dir | Directory structure, project.yaml, revolver.db created | FR-PRJ-001..005 |
| `project init` | Dir already has `.revolver/` | Exit code 1, error message | FR-PRJ-006 |
| `project init --path` | Create and init new dir | Dir created at target path | FR-PRJ-007 |
| `project init` | Check `.revolver/` permissions | Mode 700 on `.revolver/` dir | FR-PRJ-008, NFR-051 |

### 2.2 `revolver llm`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `llm add` (Ollama) | Register local LLM with `--pull` | DB entry (global), source=ollama, digest stored | FR-LLM-002, 004, 005 |
| `llm add` (API) | Register remote LLM | DB entry, provider, api-key-env name stored (pricing fields removed — #300) | FR-LLM-001, 017 |
| `llm add` (openai-compat) | Register custom endpoint | DB entry, base_url stored | FR-LLM-016 |
| `llm add` | Duplicate name | Exit code 1 | — |
| `llm list` | After 2 adds | Both listed, correct columns | — |
| `llm remove` | Remove existing | DB entry removed | FR-LLM-014 |
| `llm remove` | Remove non-existent | Exit code 1 | — |
| `llm status` | Mock Ollama response | Status displayed, VRAM info, remote=ready if env set | FR-LLM-009, 015 |
| `llm start` | Mock Ollama load | Success message, VRAM info, health check | FR-LLM-006, 013 |
| `llm start` | Another model already loaded | Previous model unloaded first | FR-LLM-008 |
| `llm stop` | Mock Ollama unload | Success message | FR-LLM-007 |
| `llm add --temperature 0.7` | Temperature stored in DB | DB entry includes temperature=0.7 | FR-LLM-019 |
| `llm update --temperature 1.0` | Temperature updated in DB | DB entry updated to temperature=1.0 | FR-LLM-019 |
| `llm add --reasoning-effort high` | Reasoning effort stored in DB (`llms.reasoning_effort`, migration v12) | DB entry includes reasoning_effort=high; `llm info` displays it | FR-LLM-026 |
| `llm update --reasoning-effort low` | Reasoning effort updated in DB | DB entry updated to reasoning_effort=low | FR-LLM-026 |

### 2.2b `revolver llm ensemble`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `llm ensemble create` | Create named ensemble | DB entry created, 0 members | FR-LLM-020 |
| `llm ensemble add` | Add registered LLM with weight | Member row created, weight stored | FR-LLM-021 |
| `llm ensemble add --reasoning-effort high` | Per-member effort override stored (distinct from the member LLM's registry value) | `ensemble_members.reasoning_effort` set; precedence over the member LLM's own registry value | FR-LLM-026 |
| `llm ensemble add` | Add non-existent LLM | Exit code 1, error message | FR-LLM-021 |
| `llm ensemble list` | After 2 creates | Both listed with member counts | FR-LLM-022 |
| `llm ensemble info` | Existing ensemble with 2 members | Members, weights, per-member overrides displayed | FR-LLM-023 |
| `llm ensemble remove` | Remove existing ensemble | DB entry and members cascade-deleted | FR-LLM-024 |
| `llm ensemble remove` | Remove non-existent ensemble | Exit code 1 | FR-LLM-024 |

### 2.2c Ensemble `build_config()` integration

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `run --dry-run --llm <ensemble>` | Ensemble resolves to `llm.models` array | OE config contains models array with correct fields | FR-RUN-046 |
| `run --dry-run --llm <ensemble>` | Per-member temperature override | OE config member has overridden temperature | FR-RUN-046 |
| `run --dry-run --llm <ensemble>` (OE) | Per-member `reasoning_effort` override (`high`/`low`) | Each `llm.models[].reasoning_effort` matches the member's effective effort (per-member override else registry value); `test_oe_ensemble_reasoning_effort_per_member` | FR-LLM-026 |
| `llm ensemble add --reasoning-effort high` | Per-member effort stored distinct from the member LLM's registry `reasoning_effort` | `ensemble_members.reasoning_effort` row-level override; `test_shinka_reasoning_effort_global_pool` reads it back | FR-LLM-026 |

### 2.2d Run with ensemble

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `run --llm <ensemble>` | Full run with mocked OE | Run record stores `llm_type=ensemble` and `llm_snapshot` JSON | FR-RUN-044, 045 |
| `run info` | Ensemble run | Displays ensemble name and member models | FR-RUN-044 |
| `run resume --llm <ensemble>` | Override LLM on resume | New run uses ensemble config | FR-RUN-046 |
| `run` | Single LLM (no regression) | Run record stores `llm_type=single` and `llm_snapshot` JSON; `integration/test_run::test_run_start_single_llm_no_regression`, `::test_run_start_llm_snapshot_single` (L2) | FR-RUN-044, 045 |

### 2.3 `revolver problem`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `problem test --instance` | Valid evaluator + single instance | Metrics output (`dict[str, float]` with `combined_score`), exit code 0 | FR-PRB-001, 005 |
| `problem test --dataset` | Valid evaluator + 3 instances | Summary with pass/fail counts | FR-PRB-002 |
| `problem test` | Evaluator raises exception | Exit code 4, error displayed, Revolver does not crash | FR-PRB-003 |
| `problem test` | Instance exceeds timeout | Timeout reported per instance | FR-PRB-004 |
| `problem test --verbose` | Valid evaluator | Full stdout/stderr and stack traces | FR-PRB-011 |
| `problem version create` | Create v1.0 from valid files (positional `TAG`; deprecated `--tag` still resolves) | Snapshot dir, manifest.yaml, DB entry, SHA-256 hash | FR-PRB-006, 007, 009 |
| `problem version create` | `problem.md` exists | Included in snapshot | FR-PRB-014 |
| `problem version create` | Missing `evaluator.py` | Exit code 1, clear error | FR-PRB-010 |
| `problem version create` | Duplicate tag | Exit code 1 | FR-PRB-008 |
| `problem version list` | After 2 versions | Both listed chronologically | — |
| `problem version create --backend shinka` | Backend persisted on the version record (migration v14, `problem_versions.backend`; legacy rows default `openevolve`) | Stored backend becomes the version-default backend for `revolver run` (FR-RUN-047 as amended) | FR-PRB-016 |

### 2.4 `revolver dataset`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `dataset add` | Valid directory, 3 JSON files | DB entry, per-instance hashes, global hash, absolute path, count=3 | FR-DAT-001..004 |
| `dataset add --snapshot` | Copy files into `.revolver/` | Snapshot dir created with copies | FR-DAT-005 |
| `dataset add --split train` | Specify split | Split stored in DB | FR-DAT-006 |
| `dataset add --split both` | Dual-use split | `both` accepted and stored (migration v11); usable for train and eval, no run split-warning | FR-DAT-006 |
| `dataset add --split bogus` | Invalid split | Exit code 1, "Must be 'train', 'eval', or 'both'" | FR-DAT-006 |
| `dataset add --compatible-with v1.0` | Declare compat | Compat entry in DB | FR-DAT-007 |
| `dataset add` | Non-existent path | Exit code 1 | — |
| `dataset add` | Duplicate name | Exit code 1 | FR-DAT-011 |
| `dataset list` | After 2 adds | Both listed with counts, splits | — |
| `dataset info` | Existing dataset | Detail view: hash, instances, compat | — |
| `dataset info --verify` | After modifying a file | Hash mismatch reported | FR-DAT-009 |
| `dataset update` | Add compat version | DB updated | FR-DAT-008 |
| `dataset remove` | Existing dataset, no references | DB entry + manifest removed | FR-DAT-014 |
| `dataset remove` | Dataset referenced by solution | Exit code 1 (blocked) | FR-DAT-015 |
| `dataset remove --force` | Force remove despite references | Removed | FR-DAT-015 |
| `dataset remove` | Snapshot storage | Copied files also deleted | FR-DAT-016 |

### 2.5 `revolver run`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `run` | Valid config, mocked OpenEvolve | Run dir created, DB entries (run + solution), lineage, env vars set | FR-RUN-001, 005..010 |
| `run --alias` | User-friendly name | Solution alias set | FR-RUN-012 |
| `run --dry-run` | Valid config | Config displayed, no run launched | FR-RUN-023 |
| `run --dry-run` | Pre-flight skipped | No pre-flight check executed | FR-RUN-023 |
| `run` | Unknown LLM name | Exit code 1 | FR-RUN-001 |
| `run` | Dataset integrity failure (tampered file) | Exit code 2, warning message | FR-RUN-004 |
| `run` | Dataset split=eval | Warning on stderr, run proceeds | FR-RUN-002 |
| `run` | Dataset incompatible with version | Warning on stderr, run proceeds | FR-RUN-003 |
| `run` | Completion with tokens | Token usage displayed (tokens only — **no cost**, #300), stored in DB | FR-RUN-028, 029 |
| `run` | Post-run eval on train set | Rank-1 program evaluated, results in DB | FR-RUN-019, 020 |
| `run` (pre-flight) | Evaluator returns score > 0 on first instance | Pre-flight passes, run proceeds | FR-RUN-001 |
| `run` (pre-flight) | Evaluator raises exception | Run aborts with RevolverError | FR-RUN-001 |
| `run` (pre-flight) | Evaluator hangs | Run aborts after 60s timeout | FR-RUN-001 |
| `run` (pre-flight) | Evaluator returns 0.0 | Warning emitted, run proceeds | FR-RUN-001 |
| `run` (collect) | Programs in `oe-output/best/` dir | `best_program.py` collected as rank-1.py | FR-RUN-008 |
| `run list` | After 2 runs | Both listed with status, filterable | FR-RUN-021 |
| `run info` | Existing run | Full details: lineage, tokens, solution, stored programs | FR-RUN-022 |
| `run resume` | Existing checkpoint | New run from parent, wrapper copied | FR-RUN-013, 024 |
| `run --temperature 0.5` | Temperature injected into OE config | OE config contains temperature=0.5 — `unit/infra/test_openevolve::TestBuildConfig::test_run_temperature_flag` (L1, `build_config()`); the flag's presence on `run resume` is checked by `integration/test_sprint_009a::test_resume_cli_temperature_flag` | FR-RUN-040 |
| `run --parallel 4` | Parallel evaluations injected into OE config | OE config contains num_parallel=4 — `unit/infra/test_openevolve::TestBuildConfig::test_run_parallel_flag` (L1, `build_config()`); `integration/test_sprint_009a::test_resume_cli_parallel_flag` | FR-RUN-041 |
| `run` (internal) | Post-processing failure | Status set to `completed_with_errors`, `run-error.log` written | FR-RUN-043, 032 |
| `run` (internal) | OE failure (regression) | Status set to `failed` | FR-RUN-031 |
| `run status` / `run population` | Metrics dict carrying `combined_score` plus other numerics | Display/ranking prefers numeric `combined_score` over the sum-of-numeric-metrics; sum is the fallback only without `combined_score`; no crash when absent | FR-RUN-052 |
| `run` | One instance times out (default policy) | Timed-out instance contributes `timeout_score` (default 0.0) to the mean (**penalize**); wrapper emits `instances_valid`/`instances_total`, never summed into the score; timeout recorded on the side-channel | FR-RUN-053, 054 |
| `run --config-override evaluation.on_timeout=drop` | Timed-out instance under `drop` | Survivor-mean restored (0.17 behavior); zero-timeout runs produce identical scores under both policies | FR-RUN-054 |
| `run` / `run --dry-run` | `evaluation.on_timeout=bogus` or non-finite `timeout_score` | Rejected at run/dry-run, exit code 1 (`evaluation.*` is a validated Revolver-owned section) | FR-RUN-054 |
| `run` | Post-run eval on train set (S18 path) | Results persisted via `core.eval.evaluate_solution` into `eval_metadata`/`eval_instances` (no longer stderr-only); no DB contention with the open launch connection; failure stays warn-only; hardcoded 300 s timeout gone | FR-RUN-019, 020 |
| `run info` | Completed run with post-eval | Engine best labeled "engine, single eval" next to the coverage-labeled post-eval mean; #306 fallback labeled (never renders bare); JSON output carries both fields | FR-RUN-055 |
| `run` (no `--backend`) | Version created with `--backend shinka` | Resolution order explicit `--backend` > version's stored backend > default `openevolve` (`None` sentinel); an explicit mismatch **warns** on stderr, never errors; `--dry-run` resolves identically; resume inherits the parent backend | FR-RUN-047, FR-PRB-016 |
| `run` (pre-flight) | Seed lacks a declared non-builtin `feature_dimensions` metric | `validate_seed_metrics` fails fast **before iteration 0** (launch + resume), naming the missing dim + available metrics; builtins `complexity`/`diversity`/`combined_score` allowed; Shinka no-op; skipped when pre-flight is skipped | FR-RUN-056 |
| `run` | `checkpoint_interval` unset, ≤100 iterations (OE) | Effective interval defaults to `max(1, min(100, iterations//10))` — a killed short run has a mid-run checkpoint; an explicit value is never overridden | FR-RUN-057 |
| `run --backend shinka` (LLM with `timeout_s`) | Per-run LLM-request timeout | Resolved `llm_timeout` set on `shinka.llm.client.TIMEOUT` before the engine run and **restored** after (incl. when the engine raises); untouched when unset; ensemble takes the max over members; `--dry-run` surfaces `llm_timeout` in backend_extras — `integration/test_run_shinka::test_shinka_llm_timeout_set_and_restored`, `::test_shinka_llm_timeout_restored_when_engine_raises`, `::test_shinka_no_llm_timeout_global_untouched`, `::test_shinka_ensemble_llm_timeout_max_wins`, `::test_shinka_dry_run_surfaces_llm_timeout` | — (infra, R2 #260/#269) |

### 2.6 `revolver eval`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `eval` | Valid solution + 3 instances | Per-instance results in DB, aggregates displayed | FR-EVL-001..006 |
| `eval` | One instance fails | Recorded as unsolved, eval continues | FR-EVL-010, 011 |
| `eval` | Non-existent solution | Exit code 1 | — |
| `eval` | Integrity check fails | Warning, eval proceeds | FR-EVL-007 |
| `eval` | Incompatible version | Warning on stderr | FR-EVL-008 |
| `eval` | Split=train (not eval) | Warning on stderr | FR-EVL-009 |
| `eval` | Results already exist | Confirmation required; `--force` skips | FR-EVL-018 |
| `eval results` | After eval, human mode | Aggregates + per-instance breakdown | FR-EVL-015, 016 |
| `eval results --json` | After eval, JSON mode | Full raw per-instance data | FR-EVL-017 |
| `eval` | Legacy evaluator (`evaluate()`) | Global aggregation call, `user_aggregates` stored | FR-EVL-019, 020 |
| `eval` | Evaluator with only `evaluate_instance()` | Per-instance function called correctly | FR-EVL-001, 002 |
| `eval` | Evaluator with only `evaluate()` (legacy) | Legacy global function called correctly | FR-EVL-019 |
| `eval` | Evaluator with both functions | Warning emitted, `evaluate()` used (legacy mode) | FR-EVL-019 |
| `eval results` | Metrics include reserved `instances_*` coverage keys | Coverage keys excluded from read-time aggregation (`compute_aggregates`) — coverage is metadata, never averaged into a score | FR-EVL-021, FR-RUN-053 |

### 2.7 `revolver solution`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `solution list` | After 2 runs | Solutions listed with ID, alias, version, LLM, score, rank | FR-SOL-001 |
| `solution list --version v1.0` | Filter by version | Only matching solutions | FR-SOL-002 |
| `solution info` | Existing solution | Full lineage (via run JOIN), program path, eval results if available | FR-SOL-003..005 |
| `solution info` | Solution with siblings | Other solutions from same run shown | FR-SOL-009 |
| `solution alias` | Set alias | DB updated, alias unique | FR-SOL-006, 007 |
| `solution alias` | Duplicate alias | Exit code 1 | FR-SOL-007 |
| `solution list` | Reference by alias | Alias works in filters | FR-SOL-008 |
| `solution extract` | Promote rank #2 from run | New solution entry in DB, unique ID | FR-SOL-011, 013 |
| `solution extract` | Same (run_id, rank) already extracted | Exit code 1, blocked | FR-SOL-012 |
| `solution delete` | Delete by alias | Removed from DB | FR-SOL-014 |
| `solution delete` | Delete by ID with `--force` | No confirmation prompt, removed | FR-SOL-015 |
| `solution delete` | Non-existent alias | Exit code 1 | — |
| `solution delete` | JSON mode without `--force` | Exit code 1 (interactive prompt forbidden) | FR-SOL-017 |
| `solution delete` | User cancels at prompt | No deletion | — |
| `solution delete` | Cascade-deletes eval data | Eval entries removed with solution | FR-SOL-016 |
| `solution extract` | `completed_with_errors` run with program | Extraction succeeds | FR-RUN-033 |
| `solution extract` | `interrupted` run (default, no flag) | Extraction rejected (unchanged default); `test_extract_rejects_interrupted_run` (revised) | FR-RUN-033, FR-RUN-051 |
| `solution extract --from-checkpoint` | `interrupted`/`failed` OE run with a checkpoint | Recovers `best_program_id` from latest `checkpoint_N/metadata.json` + `programs/{id}.json`, creates a solution; `test_extract_from_checkpoint_recovers_interrupted_run` | FR-RUN-051 |
| `solution extract --from-checkpoint` | Run too short to have checkpointed yet | Clear typed error (distinct from "not supported"); `test_extract_from_checkpoint_no_checkpoint_yet_errors` | FR-RUN-051 |
| `solution show` | Display source code of existing solution on stdout | Source code printed to stdout | FR-SOL-018 |
| `solution show --json` | JSON output with alias and code fields | Valid JSON with alias and code keys | FR-SOL-018 |
| `solution show` | Exit 1 if alias not found | Exit code 1, error message | FR-SOL-018 |
| `solution export` | Copy program file to default path (`<alias>.py`) | File created at `<alias>.py` | FR-SOL-019 |
| `solution export -o <path>` | Copy to explicit path | File created at specified path | FR-SOL-019 |
| `solution export` | Exit 1 if alias not found | Exit code 1, error message | FR-SOL-019 |
| `solution diff` | Unified diff between two different solutions | Diff output on stdout | FR-SOL-020 |
| `solution diff` | Empty diff, exit 0 for identical solutions | No output, exit code 0 | FR-SOL-020 |
| `solution diff --json` | JSON with diff text and identical flag | Valid JSON with diff and identical fields | FR-SOL-020 |
| `solution extract --rank 2` | Shinka run (top-N-capable) | 2nd-best program read from `programs.sqlite` (retroactive, no run-dir layout change), materialized as `programs/rank-2.py`, promoted; `(run_id, rank)` uniqueness enforced | FR-SOL-021, FR-SOL-011/012 |
| `solution extract --program-id <id>` | Shinka run | Arbitrary population program promoted by id | FR-SOL-021 |
| `solution extract --rank 2` | OpenEvolve run (`top_n_extraction=False`) | Exit code 1, clear "not supported on `<backend>`" error (OE consciously deferred) | FR-SOL-021 |

### 2.8 `revolver benchmark`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `benchmark` | 2 solutions + eval dataset | Comparison table, DB entries, lineage included | FR-BEN-001, 004, 005, 006 |
| `benchmark` | One solution already evaluated | Reuses existing results, no redundant eval | FR-BEN-002 |
| `benchmark` | One solution not yet evaluated | Runs evaluation for that solution | FR-BEN-003 |
| `benchmark results` | After benchmark, human mode | Aggregate table with eval_time, instances_solved | FR-BEN-004, 009 |
| `benchmark results --per-instance` | Per-instance comparison | Side-by-side, best per instance highlighted | FR-BEN-014, 015 |
| `benchmark export --format csv` | After benchmark | Valid CSV, no secrets, run_id included | FR-BEN-007, 013, 017 |
| `benchmark export --format json` | After benchmark | Valid JSON matching ConOps §8.2 schema | FR-BEN-008 |
| `benchmark export --per-instance` | Raw data export | Per-instance rows for all solutions | FR-BEN-016 |
| `benchmark list` | After 2 benchmarks | Both listed with date, dataset, solution count | FR-BEN-012 |
| `benchmark delete` | Existing benchmark, no `--force` | Confirmation prompt; `y` deletes the benchmark and its solution references | FR-BEN-018 |
| `benchmark delete` | Non-existent ID | Exit code 1, "not found" | FR-BEN-018 |
| `benchmark delete --force` | Existing benchmark | No prompt; benchmark and `benchmark_solutions` rows removed | FR-BEN-019 |
| `benchmark delete --json` (no `--force`) | JSON mode | Exit code 1, error naming `--force`; benchmark untouched | FR-BEN-020 |

### 2.9 `revolver doctor` / `revolver setup`

| Command | Scenario | Validates | FRs |
|---|---|---|---|
| `doctor` | All deps present (mocked) | All checks pass, versions reported | FR-SET-001..005, 013 |
| `doctor` | Ollama missing | Warn/fail status, actionable message | FR-SET-003, 005, 006 |
| `doctor` | Outside project dir | Still works (global health check) | FR-SET-012 |
| `setup --dry-run` | Missing OpenEvolve | Preview of install commands | FR-SET-011 |
| `setup` | Missing pip package | Installs via pip, asks confirmation | FR-SET-007, 008 |
| `setup` | System-level dep missing | Instructions only, never installs | FR-SET-009, 010 |
| `setup` | Conda available, Ollama missing | Proposes `conda install conda-forge::ollama` | FR-SET-015, 016 |
| `setup` | No conda, Ollama missing | Manual instructions, suggests conda activation | FR-SET-017 |

### 2.10 L2-OE: `revolver run` — OpenEvolve Contract

These tests use real OpenEvolve classes (`Config`, `Controller`) and are located in `tests/integration/test_run_oe.py`. They are marked with `@pytest.mark.openevolve` and skipped when `openevolve` is not installed.

| Test | Scenario | Validates | FRs |
|---|---|---|---|
| `test_build_config_roundtrip_to_oe_config` | `build_config()` dict round-trips through `OEConfig.from_dict()` | Field mapping: `api_base`, `primary_model`, `max_iterations`, `system_message` | FR-RUN-005, FR-RUN-006 |
| `test_oe_controller_instantiation` | Real `OpenEvolve(program, evaluator, config, output_dir)` with fixtures | Controller accepts our config and fixture files without crash | FR-RUN-001 |
| `test_openevolve_runner_init_controller` | `OpenEvolveRunner._init_controller()` with real OpenEvolve | The exact code path that crashed in v0.4.0 works end-to-end | FR-RUN-005, FR-RUN-006 |
| `test_build_config_local_llm_api_key` | `build_config()` with local LLM | `api_key="ollama"` injected in config | FR-RUN-006 |
| `test_build_config_cascade_evaluation_default` | `build_config()` default output | `evaluator.cascade_evaluation=false` | FR-RUN-006 |
| `test_build_config_cascade_evaluation_user_override` | User config.yaml has `cascade_evaluation: true` | User override preserved in merged config | FR-RUN-006 |

The test names above are the functions of `TestBuildConfigRoundtrip`, `TestControllerInstantiation` and `TestOpenEvolveRunnerInitController` (ids `integration/test_run_oe::<Class>::<test>`). Best-score extraction from a `Program` object (FR-RUN-008) is **not** an L2-OE test: it is covered at L1 by `unit/infra/test_openevolve::TestExtractBestScore::test_best_score_from_program_object`, which runs without `openevolve` installed.

### 2.12 L2-Shinka: Bandit Ensemble & Multi-LLM Selection (S17 — ADR-007 Amendment)

New scenarios in `tests/integration/test_run_shinka.py` (Shinka half) and `tests/integration/test_run.py` (OE half — the CLI-level selection rejection and `--llm-weight` scenarios; the OE `reasoning_effort` and `capabilities()` rows are L1, in `tests/unit/test_run_ensemble.py` and `tests/unit/infra/test_backends.py`), added for the v0.17 multi-LLM ensemble (ADR-007 A1–A5). The Shinka rows use the mocked `ShinkaEvolveRunner` and assert on the **constructed** `evo_config` (`llm_models`, `llm_dynamic_selection`, `llm_dynamic_selection_kwargs`, `llm_kwargs.reasoning_efforts`) plus emitted warnings, and auto-skip via the existing `pytest.importorskip` / `@pytest.mark.shinkaevolve` gating; the OE rows assert on the built `llm.models` array and CLI exit codes with OpenEvolve mocked, so they run in the main CI selection.

#### Selection-strategy validation

| Command | Scenario | Validates | Test ID | FRs |
|---|---|---|---|---|
| `run --backend openevolve --llm <ensemble> --selection ucb` | Non-`fixed` selection on OE | Exit code 1, clear message naming `fixed` as the only OE strategy (`capabilities().selection_strategies == ("fixed",)`) | `test_run_selection_ucb_rejected_on_oe`, `test_run_selection_fixed_accepted_on_oe` | FR-RUN-049 |
| `run --backend shinka --selection fixed --llm <weighted-ensemble>` | Fixed selection maps weights | `FixedSampler.prior_probs` == the renormalized member weights, order-aligned to `llm_models` | `test_shinka_selection_fixed_prior_probs` | FR-RUN-046, FR-RUN-049 |
| `run --backend shinka --selection ucb --llm <weighted-ensemble>` | Adaptive bandit ignores weights | Warning emitted (weights ignored under adaptive mode); **no** `prior_probs` key in the sampler kwargs (avoids the verified `TypeError`); uniform start | `test_shinka_adaptive_ignores_weights_warns` | FR-RUN-049 |
| `run --backend shinka --selection thompson --selection-kwarg cost_aware_coef=0.3` | Per-sampler kwarg routing | `cost_aware_coef` warned + dropped for `thompson` (would `TypeError`); for `--selection ucb` it is kept in `llm_dynamic_selection_kwargs`; for `--selection fixed` it is warned + dropped | `test_shinka_ucb_cost_aware_coef_default_zero`, `test_shinka_ucb_cost_aware_coef_user_value`, `test_shinka_fixed_drops_cost_aware_coef_warns`, `test_shinka_thompson_drops_cost_aware_coef_warns`, `test_shinka_ucb_drops_unknown_kwarg_warns` | FR-RUN-049 |

#### `--llm-weight` per-run override

| Command | Scenario | Validates | Test ID | FRs |
|---|---|---|---|---|
| `run --backend openevolve --llm <ensemble> --llm-weight gpt4o=0.9 --llm-weight claude=0.1` | Override honored on OE | `llm.models[].weight` reflects the CLI override, not the registry weight | `test_run_llm_weight_overrides_oe_ensemble`, `test_run_llm_weight_unknown_member_rejected`, `test_run_llm_weight_on_single_llm_rejected` | FR-RUN-050 |
| `run --backend shinka --selection fixed --llm-weight ...` vs `--selection ucb --llm-weight ...` | Honored on Shinka-fixed; warned-and-ignored on Shinka-adaptive | Fixed → weights fold into `prior_probs`; `ucb`/`thompson` → warning + weights ignored | `test_shinka_fixed_llm_weight_override_wins`, `test_shinka_adaptive_ignores_weights_warns` | FR-RUN-050 |

#### Multi-member bandit ensemble projection

| Command | Scenario | Validates | Test ID | FRs |
|---|---|---|---|---|
| `run --backend shinka --llm <N-member-ensemble>` | All members project to `llm_models` | `evo_config.llm_models` has length N; per-member env exports collected; single-LLM spec still produces the identical config as before (S14 regression) | `test_shinka_selection_fixed_prior_probs` (multi-member) | FR-RUN-046, FR-RUN-049 |

#### `reasoning_effort` projection

| Command | Scenario | Validates | Test ID | FRs |
|---|---|---|---|---|
| `run --backend openevolve --llm <ensemble>` (per-member effort) | Per-member effort onto OE | `llm.models[].reasoning_effort` matches each member's effective effort | `test_oe_ensemble_reasoning_effort_per_member` | FR-LLM-026 |
| `run --backend shinka --llm <ensemble>` (uniform / disagreeing effort) | Global pool + highest-wins on disagreement | Uniform → `llm_kwargs.reasoning_efforts` set silently; disagreeing → warning + the **highest** effort chosen (order `min < low < medium < high < max`) | `test_shinka_reasoning_effort_global_pool`, `test_shinka_reasoning_effort_disagreement_picks_highest` | FR-LLM-026 |
| `run --backend shinka --llm <local-source ensemble>` (effort set) | Local/bridge inert warning | Warning that `reasoning_effort` is inert for `local`/bridge members (Shinka `is_reasoning_model=False`) | `test_shinka_reasoning_effort_inert_local_warns` | FR-LLM-026 |

#### `capabilities()` axes

| Scenario | Validates | Test ID | FRs |
|---|---|---|---|
| `capabilities()` on both backends | `selection_strategies` (OE `("fixed",)`, Shinka `("fixed","ucb","ucb1","thompson")`) and `per_member_reasoning_effort` (OE `True`, Shinka `False`) exposed with documented values | `test_openevolve_selection_and_effort_axes`, `test_shinka_selection_and_effort_axes` | FR-RUN-049, FR-LLM-026 |

#### `--config-override` no-op key warning (B9)

| Command | Scenario | Validates | Test ID | FRs |
|---|---|---|---|---|
| `run --config-override evo_config.nonexistent_key=1` | Unrecognized override key | Warning naming the dropped key (not a silent no-op); a recognized key (e.g. `db_config.num_islands=4`) does not warn | `test_config_override_noop_key_warns` (L1 unit — in both `tests/unit/infra/test_openevolve.py` and `tests/unit/infra/test_shinka_backend.py`) | — (B9; composes with A5 per-sampler routing) |

### 2.13 DB Migrations v12 / v13 (S17)

Mirror the `unit/test_db_migration_v10` / `v11` structure. Simple additive `ALTER TABLE ADD COLUMN` per the v6/v9 pattern; v12 must precede v13; both land after the current head v11.

| Test | Scenario | Validates | FRs |
|---|---|---|---|
| `test_fresh_global_db_has_reasoning_effort_column`, `test_migration_v11_to_v12_adds_column_preserves_rows`, `test_migration_v11_to_v12_project_db` | Fresh + v11→v12 global/project DB | `llms.reasoning_effort` column present; existing LLM rows preserved with `NULL` (also `test_current_schema_version_at_least_12`, `test_reasoning_effort_round_trips_through_crud`) | FR-LLM-026, NFR-013 |
| `test_fresh_global_db_has_member_reasoning_effort_column`, `test_migration_v12_to_v13_adds_column_preserves_rows`, `test_migration_v12_to_v13_project_db` | Fresh + v12→v13 global/project DB | `ensemble_members.reasoning_effort` column present (both DDL copies in sync); existing member rows preserved with `NULL` (also `test_current_schema_version_at_least_13`) | FR-LLM-026, NFR-013 |

### 2.14 Correctness-Slice Regression (S17 — B1 / B2 / B7)

| Test | Scenario | Validates | FRs |
|---|---|---|---|
| `test_mixed_numeric_and_non_numeric_metrics_no_crash`, `test_all_numeric_metrics_aggregate_normally` | Generated OE `evaluate.py` wrapper fed an instance returning `{'combined_score': 0.5, 'error': 'boom'}` (non-numeric mixed in) and a fully-numeric instance | Aggregates without raising; non-numeric keys dropped from the aggregate, numeric `combined_score` result; runs without OpenEvolve installed (pure wrapper exec). Real tests are L1 unit (`tests/unit/core/test_run_wrapper.py`) | FR-EVL-021 (B1) |
| `test_run_invokes_teardown_on_success` | `OpenEvolveRunner.run()` completes | Teardown+reap sequence runs after completion; no process left in the pre/post child-PID diff | B2 |
| `test_run_teardown_runs_on_failure`, `test_shutdown_runner_never_raises` | Exception raised inside the controller | `finally` block still runs teardown+reap; `_shutdown_runner` uses `shutdown(wait=False)` (no `wait=True` call site — guards against the #159 hang) | B2 |
| `test_extract_from_checkpoint_recovers_interrupted_run` | `solution extract --from-checkpoint` on an interrupted OE run with a checkpoint | Best program recovered from latest `checkpoint_N/`, solution created | FR-RUN-051 (B7) |
| `test_extract_rejects_interrupted_run` (revised) | Default `solution extract` on an interrupted run (no flag) | Still rejects (unchanged default); docstring notes the v0.17 policy change vs the original F3 decision | FR-RUN-033, FR-RUN-051 |
| `test_extract_from_checkpoint_no_checkpoint_yet_errors` | `--from-checkpoint` on a run too short to have checkpointed | Clear typed error, distinct from "backend does not support checkpoint recovery" | FR-RUN-051 (B7) |

### 2.15 Cross-Cutting

| Scenario | Validates | FRs / NFRs |
|---|---|---|
| Any command with `--json` | Valid JSON to stdout, no human formatting | NFR-003 |
| Any command with `--help` | Usage text displayed | NFR-002 |
| Any error case | Message on stderr, correct exit code (0-4) | NFR-001, 004 |
| Any state-modifying command | Confirmation summary displayed | NFR-006 |
| Progress on long commands | Progress indicator on stderr | NFR-005 |
| `revolver` (root) | Subcommand structure accessible | NFR-007 |

### 2.16 S18 Semantic Slice — Eval Honesty (U13 / U11 / U4 / U8 / U6 phase 2)

New scenarios for the v0.18 semantic slice (Sprint 018 integration-test plan; the v0.17 demo-feedback
triage fixed the strict order U13 → U11 → U4 → U8 → U6 phase 2). All **Implemented** (v0.18.0); the
full suite stands at 1586 passed / 4 skipped at v0.19.0 (without the engine extras). The
Shinka-gated rows auto-skip via the existing `pytest.importorskip` / marker gating.

| Test | Scenario | Validates | FRs |
|---|---|---|---|
| `test_oe_display_prefers_combined_score` | `run population` / live `run status` on metrics with `combined_score` + other numerics (lands in the existing top-level `tests/test_run_population.py` suite — validation.md §8.1 top-level exception; `unit`-marked and L1 by scope since v0.19.0: it drives `parse_population` / `read_checkpoint_best_score` directly) | `parse_population`/`read_checkpoint_best_score` rank by `combined_score`, not sum-of-metrics; sum fallback only without `combined_score`; no crash when absent | FR-RUN-052 |
| `test_wrapper_coverage_keys_not_in_score` | Generated wrapper over a mixed valid/timed-out dataset (both backends) | `instances_valid`/`instances_total` emitted; the reserved `instances_` prefix is excluded from the metric mean — coverage never inflates the score | FR-RUN-053, FR-EVL-021 |
| `test_shinka_wrapper_timeout_branch` | Shinka wrapper instance timeout (L2-Shinka) | The new **distinct `TimeoutError` branch** (previously one catch-all) fires and records the timeout on the side-channel | FR-RUN-053 |
| `test_on_timeout_penalize_vs_drop` | Same run with a timed-out instance under both policies | Default **penalize** writes `timeout_score` (0.0) into the mean; `evaluation.on_timeout=drop` restores the 0.17 survivor-mean; zero-timeout runs identical under both | FR-RUN-054 |
| `test_evaluation_on_timeout_validation` | `evaluation.on_timeout=bogus` / non-finite `timeout_score` | Rejected at run **and** dry-run (exit 1) — `evaluation.*` is a validated Revolver-owned config section | FR-RUN-054 |
| `test_post_run_eval_persists_via_evaluate_solution` | Completed run with a train dataset | Post-run eval routed through `core.eval.evaluate_solution`; `eval_metadata`/`eval_instances` written (no longer stderr-only); no DB-contention error vs the open launch connection; warn-only preserved; hardcoded 300 s timeout gone | FR-RUN-019, FR-RUN-020 |
| `test_run_info_honest_score_labels` | `run info` on a run with a post-eval | Engine best labeled "engine, single eval" next to the coverage-labeled post-eval mean; the #306 fallback is labeled (never renders bare); JSON carries both fields | FR-RUN-055 |
| `test_run_backend_resolution_order_and_mismatch_warn` | `version create --backend shinka`, then `run` with/without `--backend` | Persisted backend resolved when the flag is omitted; explicit flag wins; explicit mismatch **warns** on stderr (never errors); `--dry-run` identical | FR-RUN-047, FR-PRB-016 |
| `test_validate_seed_metrics_missing_dim_fails` | Seed missing a declared non-builtin `feature_dimensions` metric | Pre-flight hook aborts **before iteration 0** (launch + resume), naming the missing dim + the available metrics | FR-RUN-056 |
| `test_validate_seed_metrics_builtins_and_shinka_noop` | Declared builtin dim / Shinka backend | `complexity`/`diversity`/`combined_score` allowlisted (computed inside OpenEvolve); the Shinka hook is a no-op | FR-RUN-056 |
| `test_checkpoint_cadence_default_when_unset` | Unset vs explicit `checkpoint_interval` (OE) | Default `max(1, min(100, iterations//10))` when unset (mid-run checkpoint exists on a ≤100-iter run); explicit value untouched; S17a-12 warn fires only on explicit equality | FR-RUN-057 |

### 2.17 DB Migration v14 (S18)

Mirror §2.13 / the `unit/test_db_migration_v13` structure. One column per migration
(`problem_versions.backend TEXT NOT NULL DEFAULT 'openevolve'`, project DB only — mirrors the
`runs.backend` v9 shape); the global DB **no-ops-and-bumps** (table-presence guard, v10/v12/v13
pattern); lands after the former head v13. Implemented (v0.18.0).

| Test | Scenario | Validates | FRs |
|---|---|---|---|
| `test_db_migration_v14_problem_versions_backend` | Fresh + v13→v14 project DB; global DB | `problem_versions.backend` column present; existing version rows preserved defaulting `'openevolve'`; global DB no-ops-and-bumps; `CURRENT_SCHEMA_VERSION = 14` | FR-PRB-016, NFR-013 |

### 2.18 Top-N Extraction, Reap Hardening & Doc Lint (S18)

| Test | Scenario | Validates | FRs |
|---|---|---|---|
| `test_solution_extract_rank_n_shinka` | `solution extract --rank 2` / `--program-id <id>` on a Shinka run | 2nd-best program read from `programs.sqlite` (retroactive on old runs, no run-dir layout change), materialized as `programs/rank-2.py`, promoted; `(run_id, rank)` uniqueness; `--rank 1` behaves exactly as today | FR-SOL-021, FR-SOL-011/012 |
| `test_solution_extract_rank_unsupported_oe` | `--rank 2` on an OE run | `capabilities().top_n_extraction == False` → exit 1 with a clear "not supported on `<backend>`" message (OE consciously deferred) | FR-SOL-021 |
| `test_reaper_grandchild_killpg` | Mocked run leaking a **grandchild** process (new suite `tests/integration/test_reaper_hardening.py`, next to the 017a backstops — ID `integration/test_reaper_hardening::test_reaper_grandchild_killpg`) | Recursive-descendant enumeration + `killpg` in `ChildProcessReaperMixin` reap it (not just direct children); single-PID fallback; the 017a backstop tests (`test_openevolve_shutdown.py`/`test_shinka_shutdown.py`) unaffected | — (#359 reap hardening) |
| `unit/test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_invocations_resolve` | Docs corpus with fenced `revolver` invocations (L2 by scope; lives under `tests/unit/` and runs under the `unit` CI marker in the blocking selection, sprint-018 S18-21 — validation.md §8.1 marker-vs-level rule) | Every **line-initial** fenced invocation resolves in the Typer CLI tree (untagged fences parsed); a renamed/removed flag is caught; deprecated `problem version create --tag` denylisted (no false positive); inline-prose backtick mentions out of scope | — (#354 doc anti-rot) |
| `unit/test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_includes_contributor_docs` | Corpus composition pin (#290, issue #279; same marker/level note as the row above) | The root Markdown files (`README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CLAUDE.md`, `GEMINI.md`) are in the corpus and exist; `CHANGELOG.md` is excluded; every *tracked* root `*.md` is either linted or excluded; everything else in the corpus sits under `docs/` | — (#354 doc anti-rot) |

---

## 3. Test Data

Integration tests use a **minimal test fixture set** stored in `tests/fixtures/`:

```
tests/fixtures/
├── __init__.py                 # Makes the two factories below importable as tests.fixtures.*
├── evaluator_simple.py         # Trivial evaluator: score from the program's source length
├── evaluator_legacy.py         # Legacy evaluator with evaluate() (global mode) for FR-EVL-019
├── evaluator_instance.py       # Evaluator with only evaluate_instance() function
├── evaluator_both.py           # Evaluator with both evaluate() and evaluate_instance()
├── evaluator_neither.py        # Evaluator with neither function (triggers error)
├── evaluator_dualmode.py       # Evaluator supporting both per-instance and aggregated modes
├── evaluator_mixed_metrics.py  # Emits numeric + non-numeric metrics (B1 / FR-EVL-021 wrapper aggregation)
├── initial_program_simple.py   # Trivial program with EVOLVE-BLOCK markers
├── problem_simple.md           # Minimal problem description
├── config_simple.yaml          # OpenEvolve config with 1 iteration
├── instances/                  # 3 tiny JSON instances
│   ├── instance_001.json
│   ├── instance_002.json
│   └── instance_003.json
├── instance_bad.json           # Malformed: missing "jobs" key → triggers KeyError
├── fake_llm_server.py          # OpenAI-compatible fake LLM server for L3 (val-e2e-tests.md §2.2)
├── programs_sqlite.py          # Factory for a ShinkaEvolve programs.sqlite (L2-Shinka, schema of shinka-evolve 0.0.7)
└── shinka_evaluate_py.py       # Reference Shinka evaluate.py wrapper + required markers (L2-Shinka)
```

**Principles**:
- Scenarios must be trivially fast (no real LLM, no real evolution)
- Fixtures are committed to the repo and versioned with the tests
- OpenEvolve is mocked at the `infra.backends.openevolve` boundary — integration tests never run real evolution
- Mock OpenEvolve returns deterministic program code and scores

---

## 4. Conventions

- **File layout**: `tests/integration/` organized by command group (exact at v0.19.0; the `project init` suite is the historic top-level `tests/test_project_integration.py` — [validation.md §8.1](validation.md))
  ```
  tests/integration/
  ├── __init__.py
  ├── test_llm.py
  ├── test_ensemble.py          # `llm ensemble` subcommands (S17)
  ├── test_problem.py
  ├── test_dataset.py
  ├── test_run.py               # `run` incl. the OE-side ensemble selection / `--llm-weight` scenarios (§2.12)
  ├── test_eval.py
  ├── test_solution.py          # incl. the Shinka-gated top-N extraction tests (`shinkaevolve` marker)
  ├── test_benchmark.py
  ├── test_doctor.py
  ├── test_setup.py
  ├── test_cross_cutting.py
  ├── test_workspace_detection.py  # workspace guard: commands outside a `.revolver/` project exit 1 (S9)
  ├── test_sprint_009a.py       # S9a: checkpoint_interval guard, config validation, resume flags, dry-run
  ├── test_run_oe.py            # L2-OE contract (§2.10; `openevolve` marker, importorskip)
  ├── test_run_shinka.py        # L2-Shinka CLI scenarios (S14; extended S17 — bandit ensemble/selection)
  ├── test_shinka_wrapper.py    # L2-Shinka wrapper contract (implemented — S14)
  ├── test_shinka_db.py         # L2-Shinka programs.sqlite contract (implemented — S14)
  ├── test_openevolve_shutdown.py  # B2 OE post-run teardown regression (S17, mirrors test_shinka_shutdown.py)
  ├── test_shinka_shutdown.py   # A2 Shinka post-run teardown regression (S16a; runner mocked, no extra needed)
  └── test_reaper_hardening.py  # #359 grandchild reap (S18)
  ```
- **Pattern**: each test creates a temporary project via `tmp_project` fixture, runs CLI commands through `CliRunner`, asserts on stdout/stderr/exit code and DB state
- **Markers**: `@pytest.mark.integration` — allows running unit-only or integration-only via `-m`
- **Speed**: full integration suite must run in under 2 minutes
- **No network**: all HTTP calls (Ollama, LLM APIs) and the engines are mocked with `unittest.mock.patch` inside each test module (no shared mock fixtures — [validation.md §6.3](validation.md))
- **L2-OE tests**: use `pytest.importorskip("openevolve.config")` at module level for auto-skip when `openevolve` is not installed. Marked with `@pytest.mark.openevolve` in addition to `@pytest.mark.integration`. A dummy `OPENAI_API_KEY` is set via `monkeypatch` for tests that instantiate the OpenEvolve controller (it requires an API key even though no LLM call is made).
- **L2-Shinka tests** (implemented — S14): use `pytest.importorskip("shinka.database")` at module level for auto-skip when the `shinka` extra is not installed. Marked with `@pytest.mark.shinkaevolve` in addition to `@pytest.mark.integration`.
