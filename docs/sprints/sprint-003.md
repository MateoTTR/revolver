# Sprint 003 — Dataset Registration & Integrity

**Status**: Planning
**Goal**: Deliver the `revolver dataset` command group (registration, integrity verification, compatibility tracking, snapshot support, remove). Datasets are a mandatory prerequisite for `revolver run`. This sprint completes the "pre-run" layer: problem versions + datasets are now both managed by Revolver.
**Demo**: Register a training dataset with per-instance SHA-256 hashing; register an eval dataset with snapshot copy; verify integrity with `--verify` after modifying a file; declare compatibility with a problem version; remove a dataset.

---

## Scope

### Command groups included
- `revolver dataset {add,update,remove,list,info}` — full implementation (DES-004)

### Key FRs covered
- FR-DAT-001 — Register dataset by reference: path stored, files stay in place
- FR-DAT-002 — Compute SHA-256 hash per instance + global hash
- FR-DAT-003 — Store absolute resolved path
- FR-DAT-004 — Auto-count instances (non-hidden top-level entries)
- FR-DAT-005 — `--snapshot` copies dataset files into `.revolver/datasets/<name>/snapshot/`
- FR-DAT-006 — Split declaration (`train` or `eval`)
- FR-DAT-007 — Declare compatibility with one or more problem versions at add time
- FR-DAT-008 — `update --add-compatible-with` / `--remove-compatible-with`
- FR-DAT-009 — `info --verify` recomputes hashes and reports mismatches
- FR-DAT-010 — Integrity verification at usage time (warn, not block) via `verify_dataset_integrity()`
- FR-DAT-011 — Refuse duplicate dataset names
- FR-DAT-012 — Subdirectory instances supported via `tree_hash()`
- FR-DAT-013 — Warn when using dataset with incompatible problem version
- FR-DAT-014 — `remove` deletes DB rows, manifest, and `.revolver/datasets/<name>/` dir
- FR-DAT-015 — `remove` refuses if dataset referenced by solutions (unless `--force`)
- FR-DAT-016 — `remove` with snapshot storage also deletes the copied files

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S3-01 | Implement `revolver.models.dataset` — `DatasetInstance` (frozen), `DatasetRegistration` (frozen), `DatasetSummary`, `DatasetInfo`, `IntegrityReport` Pydantic models (DES-004 §5); hidden-file exclusion rule documented | models | Sprint 001 | [ ] | Models validate; `frozen=True` on immutable entities; `IntegrityReport.is_valid` reflects comparison state |
| S3-02 | Add dataset CRUD to `revolver.infra.db` — `insert_dataset()`, `insert_dataset_instances()` (batch executemany), `insert_dataset_compat()`, `get_dataset(name)`, `get_dataset_instances(name)`, `get_dataset_compat(name)`, `list_datasets()`, `update_dataset_description()`, `delete_dataset(name)`, `delete_dataset_instances(name)`, `delete_dataset_compat_all(name)`, `get_solutions_by_dataset(name)` | infra | Sprint 001 | [ ] | Unit tests: all 12 CRUD functions; batch insert handles 1000+ instances; `get_solutions_by_dataset` returns empty list when no solutions reference dataset |
| S3-03 | Add dataset store operations to `revolver.infra.store` — `write_dataset_manifest(name, data)`, `update_dataset_manifest(name, data)`, `delete_dataset_store(name)`, `create_dataset_snapshot(name, source_path)`, `get_snapshot_path(name)` | infra | Sprint 001 | [ ] | Unit tests: manifest write/read/delete; snapshot directory created with file copies; deletion removes directory tree |
| S3-04 | Implement `revolver.core.dataset` — `register_dataset()`, `update_dataset()`, `remove_dataset()`, `list_datasets()`, `get_dataset_info()`, `verify_dataset_integrity()`, `resolve_dataset_path()` (DES-004 §7); hidden-file exclusion (`.`-prefix); warn-not-block on usage-time integrity; compatibility advisory warning | domain | S3-01, S3-02, S3-03 | [ ] | Unit tests with mocked infra: `test_register_by_reference`, `test_absolute_path_stored`, `test_instance_count_auto`, `test_integrity_check_at_usage`, `test_warns_incompatible_version`, `test_hash_verified_at_usage` |
| S3-05 | Implement `revolver.cli.dataset` — 5 Typer commands: `add`, `update`, `remove`, `list`, `info` (DES-004 §8); `--snapshot`, `--split`, `--compatible-with`, `--verify`, `--force` options; progress bar for large dataset hashing | cli | S3-04 | [ ] | CliRunner tests for all 5 commands; exit 1 on non-existent path; exit 1 on duplicate name; exit 1 on blocked remove |
| S3-06 | Write L2 integration tests for `dataset` (14 scenarios from val-integration-tests §2.4) | test | S3-05 | [ ] | All 14 dataset scenarios pass |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md §2.4` that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `dataset add` | Valid directory, 3 JSON files — DB entry, per-instance hashes, global hash, count=3 | `test_add_basic` | Planned |
| `dataset add --snapshot` | Copy files into `.revolver/` — snapshot dir created | `test_add_with_snapshot` | Planned |
| `dataset add --split train` | Split stored in DB | `test_add_with_split` | Planned |
| `dataset add --compatible-with v1.0` | Compat entry in DB | `test_add_with_compatible_version` | Planned |
| `dataset add` | Non-existent path — exit code 1 | `test_add_nonexistent_path` | Planned |
| `dataset add` | Duplicate name — exit code 1 | `test_add_duplicate_name_fails` | Planned |
| `dataset list` | After 2 adds — both listed with counts, splits | `test_list_after_adds` | Planned |
| `dataset info` | Existing dataset — detail view with hash, instances, compat | `test_info_basic` | Planned |
| `dataset info --verify` | After modifying a file — hash mismatch reported | `test_info_verify_recomputes_hash` | Planned |
| `dataset update` | Add compat version — DB entry created | `test_update_compat_versions` | Planned |
| `dataset remove` | Existing dataset, no references — DB + manifest removed | `test_remove_deletes_metadata` | Planned |
| `dataset remove` | Dataset referenced by solution — exit code 1 | `test_remove_blocked_by_reference` | Planned |
| `dataset remove --force` | Force remove despite references — removed | `test_remove_forced` | Planned |
| `dataset remove` | Snapshot storage — copied files also deleted | `test_remove_snapshot_deletes_files` | Planned |

**Cumulative L2 tests passing: 39 / 39 (sprints 001+002+003)**

---

## Parallelization

### Dependency graph

```
Sprint 001 + Sprint 002 (problem versions needed for --compatible-with validation)
  │
  ├──> S3-01 (models: dataset) ──────┐
  │                                   │
  ├──> S3-02 (infra: db/dataset) ────┼──> S3-04 (domain: dataset)
  │                                   │         ↓
  └──> S3-03 (infra: store/dataset) ─┘    S3-05 (cli: dataset)
                                                  ↓
                                           S3-06 (test: L2 — 14 scenarios)
```

### Critical path
Sprint 002 → S3-01 + S3-02 + S3-03 (parallel) → S3-04 → S3-05 → S3-06
Estimated sequential depth: 4 steps after prerequisites.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Models | S3-01 | Sprint 002 done | Agent 1 |
| B — Infra (DB + store) | S3-02, S3-03 | Sprint 002 done | Agent 2 |
| C — Domain + CLI | S3-04, S3-05 | Streams A+B done | Agent 1 |
| D — Tests | S3-06 | Stream C done | Agent 2 |

Peak parallelism: 2 agents on Streams A and B simultaneously.

Note: Sprint 003 is intentionally simpler and narrower than Sprint 002. The dataset command group has a single implementation chain with limited internal parallelism. The value is in completing the prerequisite data management layer before the complex Sprint 004 run orchestration.

### Conflict risks
- `infra/db.py` — adds dataset CRUD to a file modified in Sprints 001 and 002; use clear function grouping per table to minimize merge conflicts
- `infra/store.py` — adds dataset manifest operations alongside project store operations from Sprint 001
- `infra/hashing.py` — reuses `file_hash()`, `tree_hash()`, `global_hash()` from Sprint 001; no changes expected

---

## Sprint Review

_Filled at sprint end._

### Tests passing
- 0 / 14 integration tests passing (this sprint)
- 0 / 39 total cumulative integration tests

### Demo-able features
- [ ] `revolver dataset add --name train --path ./data/ --split train --compatible-with v1.0`
- [ ] `revolver dataset add --name eval --path ./eval/ --split eval --compatible-with v1.0 --snapshot`
- [ ] `revolver dataset list` shows both datasets with counts and splits
- [ ] `revolver dataset info train` shows detail with global hash and compat versions
- [ ] `revolver dataset info train --verify` detects file modification with per-instance report
- [ ] `revolver dataset update train --add-compatible-with v1.1`
- [ ] `revolver dataset remove eval` removes dataset entry and snapshot directory

### Carry-over
- Tasks or issues deferred to next sprint
