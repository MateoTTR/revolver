# Revolver — Traceability Matrix

**Version**: 0.9 — v0.19.0 pre-release validation review: every cited test id re-verified against the test sources (FR-LLM-020..025, FR-RUN-031/040/041/044/045/046, doc-guard ids repointed), FR-BEN-019/020 + FR-RUN-042 + NFR-043 rows added, marker-driven level relabels, §13 recomputed with a stated method. Previous: 0.8 — S18 sync (FR-RUN-052..057, FR-PRB-016, FR-SOL-021 rows; migration v14 + reap-hardening + doc-lint + R2 `llm_timeout` + #355 freshness test rows)
**Date**: 2026-10-24
**Status**: Draft
**Traceable to**: [Specifications](../specs/specifications.md), [Validation Overview](validation.md)

---

## 1. Purpose

This document maps every functional requirement (FR) and testable non-functional requirement (NFR) to its design reference (DES) and planned test. It ensures full traceability from requirements to verification.

### Legend

| Column | Description |
|---|---|
| **FR ID** | Requirement identifier from specs |
| **Priority** | MUST / SHOULD / MAY |
| **DES Ref** | Design document section |
| **Test Level** | Unit (L1), Integration (L2), E2E (L3), Static (L0) |
| **Test ID** | Test name — references actual test functions in `tests/` (ID form, the `integration/` prefix rule and the top-level-file exception: [validation.md §8.1](validation.md)) |
| **Status** | `Planned` → `Implemented` → `Passing` |

> **Note:** A single FR may appear on multiple rows when covered by tests at different levels (L1, L2) or by distinct test scenarios.

---

## 2. Project — `revolver project`

Design: [Architecture §4.1](../architecture/architecture.md), [DES-001](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-PRJ-001 | MUST | Arch §4.1, DES-001 | L2 | `test_project_integration::test_init_creates_structure` | Implemented |
| FR-PRJ-002 | MUST | Arch §4.1 | L2 | `test_project_integration::test_init_creates_structure` (checks project.yaml) | Implemented |
| FR-PRJ-003 | MUST | DES-003 §2 | L2 | `test_project_integration::test_init_creates_structure` (checks initial_program.py) | Implemented |
| FR-PRJ-004 | MUST | DES-003 §2, ADR-006 | L2 | `test_project_integration::test_init_creates_structure` (checks evaluator.py) | Implemented |
| FR-PRJ-005 | MUST | DES-005 | L2 | `test_project_integration::test_init_creates_structure` (checks config.yaml) | Implemented |
| FR-PRJ-006 | MUST | — | L2 | `test_project_integration::test_init_existing_project_fails` | Implemented |
| FR-PRJ-007 | SHOULD | — | L2 | `test_project_integration::test_init_with_path_option` | Implemented |
| FR-PRJ-008 | SHOULD | NFR-051 | L2 | `test_project_integration::test_init_directory_permissions` | Implemented |

---

## 3. LLM — `revolver llm`

Design: [DES-002](../architecture/design/DES-002-llm-subcommands.md), [DES-001 §llms](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-LLM-001 | MUST | DES-002 §add | L2 | `integration/test_llm::test_llm_add_remote` | Implemented |
| FR-LLM-002 | MUST | DES-002 §add | L2 | `integration/test_llm::test_llm_add_ollama_with_pull` | Implemented |
| FR-LLM-003 | MUST | DES-001, DES-002 | L1 | `test_db_llm::test_insert_and_get_llm` | Implemented |
| FR-LLM-004 | MUST | DES-002 §add | L2 | `integration/test_llm::test_llm_add_ollama_with_pull` | Implemented |
| FR-LLM-005 | MUST | DES-002 §add | L1 | `unit/core/test_llm::test_digest_recorded` | Planned |
| FR-LLM-006 | MUST | DES-002 §start | L2 | `integration/test_llm::test_llm_start_mock_load` | Implemented |
| FR-LLM-007 | MUST | DES-002 §stop | L2 | `integration/test_llm::test_llm_stop_mock_unload` | Implemented |
| FR-LLM-008 | MUST | DES-002 §start | L2 | `integration/test_llm::test_llm_start_unloads_previous` | Implemented |
| FR-LLM-009 | MUST | DES-002 §status | L2 | `integration/test_llm::test_llm_status_with_mock_ollama` | Implemented |
| FR-LLM-010 | MUST | DES-002 | L1 | `unit/core/test_llm::test_base_url_exposed` | Planned |
| FR-LLM-011 | SHOULD | DES-002 §start | L1 | `unit/core/test_llm::test_vram_warning` | Planned |
| FR-LLM-012 | SHOULD | DES-002 §start | L1 | `unit/core/test_llm::test_throughput_recorded` | Planned |
| FR-LLM-013 | SHOULD | DES-002 §start | L2 | `integration/test_llm::test_health_check_after_start` | Planned |
| FR-LLM-014 | MUST | DES-002 §remove | L2 | `integration/test_llm::test_llm_remove_existing` | Implemented |
| FR-LLM-015 | MUST | DES-002 §status | L1 | `unit/core/test_llm::test_remote_status_ready_if_env_set` | Planned |
| FR-LLM-016 | SHOULD | DES-002 §add | L2 | `integration/test_llm::test_llm_add_openai_compat` | Implemented |
| FR-LLM-017 | MUST | DES-002, NFR-050 | L1 | `test_db_llm::test_api_key_env_stored_not_value` | Implemented |
| FR-LLM-018 | ~~SHOULD~~ | DES-002, DES-005 §4.5 | — | — | **Removed** (S16 / #300) — `--input-cost`/`--output-cost` flags and the `llms` pricing columns dropped (migration v10); cost no longer reported. Mirrors FR-RUN-030. |
| FR-LLM-019 | SHOULD | DES-002, DES-005 | L2 | `integration/test_llm::test_llm_add_temperature` | Implemented |
| FR-LLM-020 | MUST | DES-002 §ensemble | L2 | `integration/test_ensemble::TestEnsembleCreate::test_create_human`, `::test_create_duplicate` | Implemented |
| FR-LLM-021 | MUST | DES-002 §ensemble | L2 | `integration/test_ensemble::TestEnsembleAdd::test_add_member_human`, `::test_add_member_llm_not_found` | Implemented |
| FR-LLM-022 | MUST | DES-002 §ensemble | L2 | `integration/test_ensemble::TestEnsembleList::test_list_human_populated` | Implemented |
| FR-LLM-023 | MUST | DES-002 §ensemble | L2 | `integration/test_ensemble::TestEnsembleInfo::test_info_human` | Implemented |
| FR-LLM-024 | MUST | DES-002 §ensemble | L2 | `integration/test_ensemble::TestEnsembleRemove::test_remove_human_force`, `::test_remove_not_found` | Implemented |
| FR-LLM-025 | SHOULD | DES-002 §ensemble | L1 | `unit/core/test_ensemble::TestAddEnsembleMember::test_weight_sum_warning` | Implemented |
| FR-LLM-026 | SHOULD | ADR-007 A1/A3, DES-002 §2.1/§2.8 | L1 | `unit/test_db_migration_v12::test_reasoning_effort_round_trips_through_crud`, `unit/test_db_migration_v13::test_fresh_global_db_has_member_reasoning_effort_column` | Implemented (S17 — `reasoning_effort` registry field on `llms` + `ensemble_members`; `llm add`/`update`/`ensemble add --reasoning-effort`) |
| FR-LLM-026 | SHOULD | ADR-007 A3, DES-002 §5/§6 | L1 | `unit/test_run_ensemble::test_oe_ensemble_reasoning_effort_per_member` | Implemented (S17 — OE maps effort **per member** onto `llm.models[].reasoning_effort`) |
| FR-LLM-026 | SHOULD | ADR-007 A3, DES-002 §5/§6 | L1 | `unit/infra/test_shinka_backend::test_shinka_reasoning_effort_global_pool`, `::test_shinka_reasoning_effort_disagreement_picks_highest`, `::test_shinka_reasoning_effort_inert_local_warns` | Implemented (S17 — Shinka maps effort to the **single global** `llm_kwargs.reasoning_efforts` pool; highest-effort-wins on member disagreement + warn; inert-for-local warn) |

---

## 4. Problem — `revolver problem`

Design: [DES-003](../architecture/design/DES-003-problem-versioning.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-PRB-001 | MUST | DES-003 §test | L2 | `integration/test_problem::test_problem_test_single_instance` | Implemented |
| FR-PRB-002 | MUST | DES-003 §test | L2 | `integration/test_problem::test_problem_test_dataset` | Implemented |
| FR-PRB-003 | MUST | DES-003 §test | L2 | `integration/test_problem::test_problem_test_evaluator_exception` | Implemented |
| FR-PRB-004 | MUST | DES-003 §test | L2 | `integration/test_problem::test_problem_test_timeout` | Implemented |
| FR-PRB-005 | MUST | DES-003 §test | L1 | `unit/core/test_problem::test_validates_return_dict` | Planned |
| FR-PRB-006 | MUST | DES-003 §version | L2 | `integration/test_problem::test_problem_version_creates_snapshot` | Implemented |
| FR-PRB-007 | MUST | DES-003 §version | L1 | `test_hashing::test_snapshot_hash_sha256` | Implemented |
| FR-PRB-008 | MUST | DES-003 §version | L2 | `integration/test_problem::test_problem_version_duplicate_tag` | Implemented |
| FR-PRB-009 | MUST | DES-003 §version | L2 | `integration/test_problem::test_problem_version_creates_snapshot` (checks manifest) | Implemented |
| FR-PRB-010 | MUST | DES-003 §version | L2 | `integration/test_problem::test_problem_version_missing_evaluator` | Implemented |
| FR-PRB-011 | SHOULD | DES-003 §test | L2 | `integration/test_problem::test_problem_test_verbose` | Implemented |
| FR-PRB-012 | SHOULD | DES-003 §test | L2 | `integration/test_problem::test_test_progress_bar` | Planned |
| FR-PRB-013 | MAY | DES-003 §test | L1 | `unit/core/test_problem::test_warns_missing_combined_score` | Planned |
| FR-PRB-014 | SHOULD | DES-003 §version | L2 | `integration/test_problem::test_problem_version_includes_problem_md` | Implemented |
| FR-PRB-015 | SHOULD | DES-003, DES-005 | L2 | `integration/test_run::test_problem_md_injected` | Planned |
| FR-PRB-016 | MUST | DES-003 §version, DES-001 (migration v14) | L1 | `unit/test_db_migration_v14::test_db_migration_v14_problem_versions_backend` | Implemented (S18 / U4 #369 — `problem version create` persists `--backend` on the version record: `problem_versions.backend`, legacy rows default `'openevolve'`; global DB no-ops-and-bumps) |
| FR-PRB-016 | MUST | DES-003 §version, DES-005 §2.1 | L2 | `integration/test_run::test_run_backend_resolution_order_and_mismatch_warn` | Implemented (S18 / U4 #369 — the stored backend is the version-default backend for `revolver run`; cross FR-RUN-047 as amended) |

---

## 5. Dataset — `revolver dataset`

Design: [DES-004](../architecture/design/DES-004-dataset-registration.md), [DES-001 §datasets](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-DAT-001 | MUST | DES-004 §add | L2 | `integration/test_dataset::test_add_basic` | Implemented |
| FR-DAT-002 | MUST | DES-004 §hash | L1 | `test_hashing::test_dataset_hash_computation` | Implemented |
| FR-DAT-003 | MUST | DES-004 §add | L2 | `integration/test_dataset::test_add_basic` (checks absolute path) | Implemented |
| FR-DAT-004 | MUST | DES-004 §add | L1 | `unit/core/test_dataset::test_instance_count_auto` | Planned |
| FR-DAT-005 | MUST | DES-004 §snapshot | L2 | `integration/test_dataset::test_add_with_snapshot` | Implemented |
| FR-DAT-006 | MUST | DES-004 §add | L2 | `integration/test_dataset::test_add_with_split` | Implemented |
| FR-DAT-007 | MUST | DES-004 §compat | L2 | `integration/test_dataset::test_add_with_compatible_version` | Implemented |
| FR-DAT-008 | MUST | DES-004 §update | L2 | `integration/test_dataset::test_update_compat_versions` | Implemented |
| FR-DAT-009 | MUST | DES-004 §verify | L2 | `integration/test_dataset::test_info_verify_recomputes_hash` | Implemented |
| FR-DAT-010 | MUST | DES-004 §verify | L2 | `integration/test_run::test_run_dataset_integrity_failure` | Implemented |
| FR-DAT-011 | MUST | DES-004 §add | L2 | `integration/test_dataset::test_add_duplicate_name_fails` | Implemented |
| FR-DAT-012 | SHOULD | DES-004 §hash | L1 | `test_hashing::test_subdirectory_tree_hash` | Implemented |
| FR-DAT-013 | SHOULD | DES-004 §compat | L2 | `integration/test_run::test_run_dataset_incompatible_warning` | Implemented |
| FR-DAT-014 | MUST | DES-004 §remove | L2 | `integration/test_dataset::test_remove_deletes_metadata` | Implemented |
| FR-DAT-015 | MUST | DES-004 §remove | L2 | `integration/test_dataset::test_remove_blocked_by_reference` | Implemented |
| FR-DAT-016 | MUST | DES-004 §remove | L2 | `integration/test_dataset::test_remove_snapshot_deletes_files` | Implemented |

---

## 6. Run — `revolver run`

Design: [DES-005](../architecture/design/DES-005-run-orchestration.md), [DES-001 §runs/solutions](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-RUN-001 | MUST | DES-005 §2.1 | L1, L2-OE | `test_core_run::test_launch_run_happy_path`, `integration/test_run_oe::test_oe_controller_instantiation` | Implemented |
| FR-RUN-002 | MUST | DES-005 §2.1 | L1 | `test_core_run::test_launch_run_warns_non_train_split` | Implemented |
| FR-RUN-003 | MUST | DES-005 §2.1 | L1 | `test_core_run::test_launch_run_warns_incompatible_dataset` | Implemented |
| FR-RUN-004 | MUST | DES-005 §2.1 | L1 | `test_core_run::test_launch_run_integrity_failure` | Implemented |
| FR-RUN-005 | MUST | DES-005 §env, ADR-006 | L1, L2-OE | `test_core_run::test_launch_run_happy_path`, `integration/test_run_oe::test_build_config_roundtrip_to_oe_config`, `integration/test_run_oe::test_openevolve_runner_init_controller` | Implemented |
| FR-RUN-006 | MUST | DES-005 §config | L1, L2-OE | `test_core_run::test_launch_run_happy_path`, `integration/test_run_oe::test_build_config_roundtrip_to_oe_config`, `integration/test_run_oe::test_openevolve_runner_init_controller` | Implemented |
| FR-RUN-007 | MUST | DES-005 §id | L1 | `test_core_run::test_generate_run_id_format` | Implemented |
| FR-RUN-008 | MUST | DES-005 §post-run | L1, L2 | `test_core_run::test_launch_run_happy_path`, `integration/test_run::test_run_valid_config` | Implemented |
| FR-RUN-009 | MUST | DES-005 §manifest | L2 | `integration/test_run::test_run_info_full_details` | Implemented |
| FR-RUN-010 | MUST | DES-005, DES-001 | L1 | `test_core_run::test_launch_run_happy_path` (stores metrics in DB) | Implemented |
| FR-RUN-011 | MUST | DES-005 §checkpoint | L2 | `integration/test_run::test_run_stores_checkpoint` | Planned |
| FR-RUN-012 | MUST | DES-005 §alias | L2 | `integration/test_run::test_run_with_alias` | Implemented |
| FR-RUN-013 | MUST | DES-005 §resume | L2 | `integration/test_run::test_run_resume` | Implemented |
| FR-RUN-014 | MUST | DES-005 §concurrency | L1 | `test_core_run::test_launch_run_local_llm_sequential` | Implemented |
| FR-RUN-015 | MUST | DES-005 §concurrency | L1 | `unit/core/test_run::test_remote_llm_parallel` | Planned |
| FR-RUN-016 | SHOULD | DES-005 §progress | L2 | `integration/test_run::test_run_shows_progress` | Planned |
| FR-RUN-017 | SHOULD | DES-005 §config | L2 | `integration/test_run::test_config_stored_verbatim` | Planned |
| FR-RUN-018 | SHOULD | DES-005 §manifest | L1 | `unit/core/test_run::test_wallclock_recorded` | Planned |
| FR-RUN-019 | MUST | DES-005 §post-run | L2 | `integration/test_run::test_run_post_run_evaluation` | Implemented |
| FR-RUN-020 | MUST | DES-005, DES-006 | L2 | `integration/test_run::test_train_results_accessible_via_eval` | Planned |
| FR-RUN-021 | MUST | DES-005 | L2 | `integration/test_run::test_run_list_after_two_runs` | Implemented |
| FR-RUN-022 | MUST | DES-005 | L2 | `integration/test_run::test_run_info_full_details` | Implemented |
| FR-RUN-023 | MUST | DES-005 §2.1 | L2 | `integration/test_run::test_run_dry_run` | Implemented |
| FR-RUN-024 | MUST | DES-005 §resume | L1 | `test_core_run::test_resume_run_creates_new_run` | Implemented |
| FR-RUN-025 | SHOULD | DES-005 §locks | L1 | `test_core_run::test_get_run_status_with_active_lock`, `test_core_run::test_get_run_status_removes_stale_lock` | Implemented |
| FR-RUN-026 | SHOULD | DES-005, ADR-006 | L1 | `unit/core/test_run::test_sets_instance_log_env` | Planned |
| FR-RUN-027 | SHOULD | DES-005 | L1 | `unit/core/test_run::test_sets_eval_log_env` | Planned |
| FR-RUN-028 | SHOULD | DES-005 §4.5, DD-14 | L1 | `unit/infra/test_token_proxy::test_captures_tokens` | Implemented |
| FR-RUN-029 | SHOULD | DES-005 §4.5 | L2 | `integration/test_run::test_run_with_token_usage` | Implemented |
| FR-RUN-029 | SHOULD | DES-005 §4.5 | L2 | `integration/test_run::test_run_info_token_caveat` | Implemented (S15 caveat #300) |
| FR-RUN-030 | ~~SHOULD~~ | DES-005 §4.5 | — | — | **Removed** (S15 / #300, completed S16) — `estimate_cost()` and the `--input-cost`/`--output-cost` pricing flags/columns dropped (migration v10); cost no longer reported |
| #307 (no FR) | bug-fix | DES-005 §4.5, tuning guide | L1 | `test_llm_config::test_build_config_local_default_timeout` (+3 variants) | Implemented (S15) — `--source local` default LLM timeout |
| Scope F (no FR) | infra | DES-005 §env | L1 | `unit/infra/test_openevolve::test_pythonunbuffered_restored_when_absent` (+ prior-value) | Implemented (S15) — PYTHONUNBUFFERED restore |
| FR-RUN-001 | MUST | DES-005 §2.1 | L1 | `test_core_run::test_preflight_check_pass` | Implemented |
| FR-RUN-001 | MUST | DES-005 §2.1 | L1 | `test_core_run::test_preflight_check_evaluator_crash` | Implemented |
| FR-RUN-001 | MUST | DES-005 §2.1 | L1 | `test_core_run::test_preflight_check_timeout` | Implemented |
| FR-RUN-001 | MUST | DES-005 §2.1 | L1 | `test_core_run::test_preflight_check_score_zero` | Implemented |
| FR-RUN-023 | MUST | DES-005 §2.1 | L1 | `test_core_run::test_dry_run_skips_preflight` | Implemented |
| FR-RUN-008 | MUST | DES-005 §post-run | L1 | `test_core_run::test_collect_programs_from_top_programs` | Implemented |
| FR-RUN-006 | MUST | DES-005 §config | L2-OE | `integration/test_run_oe::test_build_config_local_llm_api_key` | Implemented |
| FR-RUN-006 | MUST | DES-005 §config | L2-OE | `integration/test_run_oe::test_build_config_cascade_evaluation_default` | Implemented |
| FR-RUN-006 | MUST | DES-005 §config | L2-OE | `integration/test_run_oe::test_build_config_cascade_evaluation_user_override` | Implemented |
| FR-RUN-008 | MUST | DES-005 §post-run | L1 | `unit/infra/test_openevolve::test_best_score_from_program_object` | Implemented |
| FR-RUN-031 | MUST | DES-005 | L2 | `test_core_run::test_run_oe_failure_marks_failed` | Implemented (`integration`-marked test in the historic top-level `tests/test_core_run.py` suite) |
| FR-RUN-043 | MUST | DES-005 §post-run | L1 | `test_core_run::test_launch_run_post_processing_failure_sets_completed_with_errors` | Implemented |
| FR-RUN-032 | MUST | DES-005 §post-run | L1 | `test_core_run::test_handle_post_run_failure_sets_completed_with_errors` | Implemented |
| FR-RUN-033 | MUST | DES-005 §extract | L2 | `integration/test_solution::test_extract_accepts_completed_with_errors` | Implemented |
| FR-RUN-034 | MUST | DES-005 §resume | L1, L2 | `test_core_run::test_resume_run_creates_new_run`, `integration/test_run::test_run_resume` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::TestDeleteRunDB::test_delete_run_returns_true` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::TestDeleteRunDB::test_delete_run_returns_false_not_found` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::TestDeleteRunDB::test_delete_run_cascades_solutions` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::TestDeleteRunDB::test_run_delete_running_run_raises` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_by_id` | Implemented (CLI class, `integration`-marked — relabelled L2 at v0.19.0) |
| FR-RUN-035 | MUST | DES-005 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_force_skips_prompt` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_not_found` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_json_mode_requires_force` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_json_mode_with_force` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_missing_directory` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_user_cancels` | Implemented |
| FR-RUN-036 | MUST | DES-005 §4.8 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_force_skips_prompt` | Implemented |
| FR-RUN-036 | MUST | DES-005 §4.8 | L2 | `integration/test_run::test_run_delete_all` | Implemented |
| FR-RUN-037 | MUST | DES-005 §4.8 | L1 | `test_run_delete::TestDeleteRunDB::test_delete_run_cascades_solutions` | Implemented |
| FR-RUN-037 | MUST | DES-005 §4.8 | L1 | `test_db_migration_v5::test_cascade_delete_run` | Implemented |
| FR-RUN-038 | MUST | DES-005 §4.8 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_by_id` | Implemented |
| FR-RUN-038 | MUST | DES-005 §4.8 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_missing_directory` | Implemented |
| FR-RUN-039 | MUST | DES-005 §4.8 | L2 | `test_run_delete::TestRunDeleteCLI::test_run_delete_json_mode_requires_force` | Implemented |
| FR-RUN-039 | MUST | DES-005 §4.8 | L2 | `integration/test_run::test_run_delete_all_no_force` | Implemented |
| FR-RUN-040 | SHOULD | DES-005 | L1, L2 | `unit/infra/test_openevolve::TestBuildConfig::test_run_temperature_flag`, `integration/test_sprint_009a::test_resume_cli_temperature_flag` (flag exposed on `run resume --help`) | Implemented |
| FR-RUN-041 | SHOULD | DES-005 | L1, L2 | `unit/infra/test_openevolve::TestBuildConfig::test_run_parallel_flag`, `integration/test_sprint_009a::test_resume_cli_parallel_flag` (flag exposed on `run resume --help`) | Implemented |
| FR-RUN-042 | — | — | — | — | **Deleted** — never defined (numbering gap since Sprint 013; spec-run marks the id `[DELETED]`, no behavior owed) |
| FR-RUN-044 | MUST | DES-005 §4.3.1, DES-001 | L1, L2 | `unit/test_run_ensemble::TestLlmSnapshot::test_single_llm_snapshot`, `::test_ensemble_snapshot`; `integration/test_run::test_run_start_single_llm_no_regression`, `::test_run_start_with_ensemble` | Implemented |
| FR-RUN-045 | MUST | DES-005 §4.3.1, DES-001 | L1, L2 | `unit/test_run_ensemble::TestLlmSnapshot::test_single_llm_snapshot`, `::test_ensemble_snapshot`; `integration/test_run::test_run_start_llm_snapshot_single` | Implemented |
| FR-RUN-046 | MUST | DES-005 §4.3 | L2 | `integration/test_run::test_run_start_with_ensemble` | Implemented |
| FR-RUN-046 | MUST | ADR-007 A2, DES-005 §4.2 | L2-Shinka | `integration/test_run_shinka::test_shinka_selection_fixed_prior_probs` | Implemented (S17 — Shinka bandit ensemble, weights → `FixedSampler.prior_probs`; supersedes the "weights dropped/warned" framing) |
| FR-RUN-047 | MUST | ADR-007, DES-005 §14.1, DES-001 §3.5 | L2 | `integration/test_run::test_run_backend_flag_and_default` | Implemented |
| FR-RUN-047 | MUST | ADR-007, DES-005 §14.1 | L2 | `integration/test_run::test_resume_inherits_parent_backend` | Implemented |
| FR-RUN-048 | MUST | ADR-007, DES-005 §14.1 | L1 | `unit/infra/test_shinka_backend::test_parallel_warns` | Implemented |
| FR-RUN-049 | MUST | ADR-007 A1/A2/A4, DES-005 §2.1/§14.1 | L2 | `integration/test_run::test_run_selection_ucb_rejected_on_oe`, `::test_run_selection_fixed_accepted_on_oe` | Implemented (S17 — `--selection`; OE `capabilities().selection_strategies == ("fixed",)` rejects non-`fixed` → exit 1) |
| FR-RUN-049 | MUST | ADR-007 A1/A2, DES-005 §4.2 | L2-Shinka | `integration/test_run_shinka::test_shinka_adaptive_ignores_weights_warns`, `::test_shinka_ucb_cost_aware_coef_default_zero`, `::test_shinka_ucb_cost_aware_coef_user_value`, `::test_shinka_fixed_drops_cost_aware_coef_warns`, `::test_shinka_thompson_drops_cost_aware_coef_warns`, `::test_shinka_ucb_drops_unknown_kwarg_warns` | Implemented (S17 — `--selection {fixed,ucb,ucb1,thompson}` → `llm_dynamic_selection`; per-sampler kwarg routing) |
| FR-RUN-050 | MUST | ADR-007 A1/A3, DES-005 §4.2 | L2 | `integration/test_run::test_run_llm_weight_overrides_oe_ensemble`, `::test_run_llm_weight_unknown_member_rejected`, `::test_run_llm_weight_on_single_llm_rejected` | Implemented (S17 — `--llm-weight model=w`; honored on OE weighted sampler) |
| FR-RUN-050 | MUST | ADR-007 A1/A3, DES-005 §4.2 | L2-Shinka | `integration/test_run_shinka::test_shinka_fixed_llm_weight_override_wins`, `::test_shinka_adaptive_ignores_weights_warns` | Implemented (S17 — `--llm-weight model=w`; honored on Shinka-`fixed` (`FixedSampler.prior_probs`), warned-and-ignored on Shinka-adaptive) |
| FR-RUN-051 | MUST | ADR-007 scope note, DES-005 §7.2 | L2 | `integration/test_solution::test_extract_from_checkpoint_recovers_interrupted_run`, `integration/test_solution::test_extract_rejects_interrupted_run` (revised), `integration/test_solution::test_extract_from_checkpoint_no_checkpoint_yet_errors` | Implemented (S17 / B7 — `solution extract --from-checkpoint` recovers best of an interrupted/failed OE run; default still rejects) |
| B2 (no FR) | infra | ADR-007 scope note, DES-005 §4.4 | L2 | `integration/test_openevolve_shutdown::test_run_invokes_teardown_on_success`, `::test_run_teardown_runs_on_failure`, `::test_shutdown_runner_never_raises` | Implemented (S17 / B2 — OE post-run teardown reaps children / shuts down executors on completion and on exception; symmetric to #224) |
| FR-RUN-049 + FR-LLM-026 | MUST | DES-005 §4.6 | L1 | `unit/infra/test_backends::test_openevolve_selection_and_effort_axes`, `::test_shinka_selection_and_effort_axes` | Implemented (S17 — `capabilities().selection_strategies` (OE `("fixed",)`, Shinka `("fixed","ucb","ucb1","thompson")`) and `per_member_reasoning_effort` (OE `True`, Shinka `False`) axes exposed with documented values on both backends) |
| B9 (no FR) | infra | DES-005 §4.2 | L1 | `unit/infra/test_openevolve::test_config_override_noop_key_warns`, `unit/infra/test_shinka_backend::test_config_override_noop_key_warns` | Implemented (S17 / B9 — unrecognized `--config-override` key warns naming the dropped key, not a silent no-op; recognized key does not warn) |
| FR-RUN-019 + FR-RUN-020 | MUST | DES-005 §7, DES-006 | L2 | `test_core_run::test_post_run_eval_persists_via_evaluate_solution` | Implemented (S18 / U11 #368 commit A — amended: post-run training eval persists via `core.eval.evaluate_solution` into `eval_metadata`/`eval_instances` (no longer stderr-only); the hardcoded 300 s timeout is gone (eval-path timeout); failure stays warn-only; DB-contention guard vs the still-open launch connection; FR-RUN-020's "accessible via `revolver eval results`" becomes literally true) |
| FR-RUN-047 | MUST | ADR-007, DES-005 §2.1/§14.1, DES-003 §version | L2 | `integration/test_run::test_run_backend_resolution_order_and_mismatch_warn` | Implemented (S18 / U4 #369 — amended: resolution order explicit `--backend` > the version's stored backend (FR-PRB-016) > default `openevolve`, via the `None` sentinel; an explicit mismatch **warns** on stderr (never errors); `--dry-run` resolves identically; resume still inherits the parent run's backend) |
| FR-RUN-052 | MUST | DES-005 §4.5 | L1 | `test_run_population::test_oe_display_prefers_combined_score` | Implemented (S18 / U13 #367 i — `run status`/`run population`/checkpoint best-score fallback prefer a numeric `combined_score` over the sum-of-numeric-metrics; sum is the fallback only when no `combined_score` exists; no crash on a metrics dict lacking it; lands in the existing top-level `tests/test_run_population.py` suite — unprefixed ID per the validation.md §8.1 top-level exception. Relabelled L1 at v0.19.0: the test drives `parse_population` / `read_checkpoint_best_score` directly and is `unit`-marked — the suite was unmarked before v0.19.0 and therefore absent from the CI selection) |
| FR-RUN-053 | MUST | DES-005 §3.2 | L2 | `integration/test_run::test_wrapper_coverage_keys_not_in_score` | Implemented (S18 / U13 #367 ii — generated wrapper on both backends emits `instances_valid`/`instances_total` coverage keys + a timeout side-channel; reserved `instances_` prefix excluded from the metric mean, cross FR-EVL-021) |
| FR-RUN-053 | MUST | DES-005 §3.2 | L2-Shinka | `integration/test_shinka_wrapper::test_shinka_wrapper_timeout_branch` | Implemented (S18 / U13 #367 ii — the Shinka wrapper's new **distinct `TimeoutError` branch** (previously one catch-all) records the timed-out instance on the side-channel) |
| FR-RUN-054 | MUST | DES-005 §2.1/§3.2 | L2 | `integration/test_run::test_on_timeout_penalize_vs_drop`, `::test_evaluation_on_timeout_validation` | Implemented (S18 / U13 #367 iii — `evaluation.on_timeout: penalize\|drop` (default **penalize** — release-noted fitness-landscape change) + finite `evaluation.timeout_score` (default 0.0), parsed at the shared launch point on both backends; values validated at run/dry-run (bad value → exit 1); `drop` restores the 0.17 survivor-mean; zero-timeout runs identical under both policies; resume inherits the parent wrapper's baked policy) |
| FR-RUN-055 | MUST | DES-005 §2.5/§8 | L2 | `integration/test_run::test_run_info_honest_score_labels` | Implemented (S18 / U11 #368 commit B — `run info` shows the engine best labeled "engine, single eval" next to the post-eval mean labeled with FR-RUN-053 coverage (`instances_valid/instances_total`); the #306 display fallback is labeled so the inflated number never renders bare; JSON output carries both fields) |
| FR-RUN-056 | MUST | DES-005 §2.1/§4.1 | L2 | `integration/test_run::test_validate_seed_metrics_missing_dim_fails`, `::test_validate_seed_metrics_builtins_and_shinka_noop` | Implemented (S18 / U8 #370 — backend `validate_seed_metrics` hook after the existing pre-flight (launch + resume) fails fast **before iteration 0** when a `database.feature_dimensions` metric is absent or non-numeric in the seed's pre-flight metrics, naming the missing dim + available metrics; builtins `complexity`/`diversity`/`combined_score` allowlisted; Shinka no-op; skipped when pre-flight itself is skipped) |
| FR-RUN-057 | SHOULD | DES-005 §4.2 | L2 | `integration/test_run::test_checkpoint_cadence_default_when_unset` | Implemented (S18 / U6 phase 2 #364 — OE-only: when `checkpoint_interval` is unset, the effective interval defaults to `max(1, min(100, iterations//10))`; an explicit value is never overridden; the S17a-12 phase-1 warn fires only on explicit equality; release-noted default-path change) |
| #359 reap (no FR) | infra | DES-005 §4.4 | L2 | `integration/test_reaper_hardening::test_reaper_grandchild_killpg` | Implemented (S18 — recursive-descendant enumeration + `killpg` in `ChildProcessReaperMixin`; a leaked **grandchild** is reaped; single-PID fallback; 017a backstop tests unaffected; new suite `tests/integration/test_reaper_hardening.py`, next to the 017a `test_openevolve_shutdown.py`/`test_shinka_shutdown.py` backstops) |
| R2 llm_timeout (no FR) | infra | DES-005 §4.2 | L2 | `integration/test_run_shinka::test_shinka_llm_timeout_set_and_restored` | Implemented (S18 stretch R2 #260/#269 — registry `timeout_s` mapped to `shinka.llm.client.TIMEOUT`, max-over-members, set/restore incl. on engine raise, dry-run surface; unit twins in `unit/infra/test_shinka_backend.py`) |

---

## 7. Evaluation — `revolver eval`

Design: [DES-006](../architecture/design/DES-006-eval-loop.md), [DES-001 §eval_metadata/eval_instances](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-EVL-001 | MUST | DES-006 §loop | L1 | `unit/core/test_eval::test_iterates_all_instances` | Planned |
| FR-EVL-002 | MUST | DES-006 §env, ADR-006 | L2 | `test_evaluator_runner::TestRunInstance::test_env_vars_set` | Implemented (module `integration`-marked, runs the evaluator in a real subprocess — relabelled L2 at v0.19.0) |
| FR-EVL-003 | MUST | DES-006 §eval | L1 | `unit/core/test_eval::test_uses_version_evaluator` | Planned |
| FR-EVL-004 | MUST | DES-006 §collect | L1 | `unit/core/test_eval::test_collects_metrics_and_time` | Planned |
| FR-EVL-005 | MUST | DES-006 §store, DES-001 | L2 | `integration/test_eval::test_stores_per_instance_results` | Implemented |
| FR-EVL-006 | MUST | DES-006 §aggregate | L1 | `unit/core/test_eval::test_aggregates_computed_at_read_time` | Planned |
| FR-EVL-007 | MUST | DES-006 §pre | L2 | `integration/test_eval::test_integrity_warning` | Implemented |
| FR-EVL-008 | MUST | DES-006 §pre | L2 | `integration/test_eval::test_warns_incompatible_version` | Implemented |
| FR-EVL-009 | MUST | DES-006 §pre | L2 | `integration/test_eval::test_warns_non_eval_split` | Implemented |
| FR-EVL-010 | MUST | DES-006 §error | L2 | `integration/test_eval::test_handles_instance_failure` | Implemented |
| FR-EVL-011 | MUST | DES-006 §error | L1 | `unit/core/test_eval::test_records_unsolved_instances` | Planned |
| FR-EVL-012 | SHOULD | DES-006 §progress | L2 | `integration/test_eval::test_progress_bar` | Planned |
| FR-EVL-013 | SHOULD | DES-006 §timeout | L2 | `test_evaluator_runner::TestRunInstance::test_timeout` | Implemented (module `integration`-marked — relabelled L2 at v0.19.0) |
| FR-EVL-014 | MAY | DES-006 | — | — | Deferred (v2) |
| FR-EVL-015 | MUST | DES-006 §results | L2 | `integration/test_eval::test_results_command` | Implemented |
| FR-EVL-016 | MUST | DES-006 §results | L2 | `integration/test_eval::test_results_per_instance` | Implemented |
| FR-EVL-017 | MUST | DES-006 §results | L2 | `integration/test_eval::test_results_per_instance_json` | Planned |
| FR-EVL-018 | MUST | DES-006 §re-eval | L2 | `integration/test_eval::test_re_eval_requires_confirmation` | Implemented |
| FR-EVL-019 | MUST | DES-006 §legacy | L1 | `unit/core/test_collect_eval_wrapper::test_evaluate_legacy_still_works` | Implemented |
| FR-EVL-020 | MUST | DES-006 §results | L2 | `integration/test_eval::test_results_shows_user_aggregates` | Implemented |
| FR-EVL-001 | MUST | DES-006 §loop | L1 | `unit/core/test_collect_eval_wrapper::test_evaluate_instance_only` | Implemented |
| FR-EVL-019 | MUST | DES-006 §legacy | L1 | `unit/core/test_collect_eval_wrapper::test_evaluate_legacy_still_works` | Implemented |
| FR-EVL-001 | MUST | DES-006 §loop | L1 | `unit/core/test_collect_eval_wrapper::test_warning_emitted_for_both_functions` | Implemented |
| FR-EVL-021 | MUST | DES-006 §1.3/§4.3, ADR-007 scope note | L1 | `unit/core/test_run_wrapper::test_mixed_numeric_and_non_numeric_metrics_no_crash`, `::test_all_numeric_metrics_aggregate_normally` | Implemented (S17 / B1 — generated OE `evaluate.py` wrapper aggregates mixed numeric/non-numeric metrics without crashing; numeric guard on the per-instance loop + `combined_score` mean) |
| FR-EVL-021 | MUST | DES-006 §4.3, DES-005 §3.2 | L2 | `integration/test_run::test_wrapper_coverage_keys_not_in_score` | Implemented (S18 / U13 #367 ii — amended: the reserved `instances_*` coverage keys (FR-RUN-053) are excluded from metric aggregation everywhere — the wrapper mean loop **and** read-time `compute_aggregates`; coverage is metadata, never averaged into a score) |

---

## 8. Solution — `revolver solution`

Design: [DES-005 §post-run](../architecture/design/DES-005-run-orchestration.md), [DES-001 §solutions](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-SOL-001 | MUST | DES-001 | L2 | `integration/test_solution::test_list_shows_all_solutions` | Implemented |
| FR-SOL-002 | MUST | DES-001 | L2 | `integration/test_solution::test_list_filters` | Implemented |
| FR-SOL-003 | MUST | DES-001, DES-005 | L2 | `integration/test_solution::test_info_full_lineage` | Implemented |
| FR-SOL-004 | MUST | DES-005 §storage | L1 | `unit/core/test_solution::test_program_path_derived` | Planned |
| FR-SOL-005 | MUST | DES-001, DES-006 | L2 | `integration/test_solution::test_info_shows_eval_results` | Planned |
| FR-SOL-006 | MUST | DES-001 | L2 | `integration/test_solution::test_alias_set` | Implemented |
| FR-SOL-007 | MUST | DES-001 | L2 | `integration/test_solution::test_alias_unique` | Implemented |
| FR-SOL-008 | MUST | DES-001 | L2 | `integration/test_solution::test_reference_by_alias` | Implemented |
| FR-SOL-009 | SHOULD | DES-005 | L2 | `integration/test_solution::test_info_shows_sibling_solutions` | Implemented |
| FR-SOL-010 | MUST | DES-001 | L1 | `unit/core/test_solution::test_lineage_via_run_id` | Planned |
| FR-SOL-011 | MUST | DES-005 §extract | L2 | `integration/test_solution::test_extract_promotes_program` | Implemented (amended S18 — promotes the rank-1 program **by default**; arbitrary rank/program via FR-SOL-021) |
| FR-SOL-012 | MUST | DES-005 §extract | L2 | `integration/test_solution::test_extract_duplicate_blocked` | Implemented (amended S18 — duplicate prevention generalized from `(run_id, rank=1)` to `(run_id, rank)`; `--force` semantics per rank) |
| FR-SOL-013 | MUST | DES-001 | L1 | `test_core_run::test_generate_solution_id_format` | Implemented |
| FR-SOL-014 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_by_alias` | Implemented |
| FR-SOL-015 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_by_id_force` | Implemented |
| FR-SOL-016 | MUST | DES-005 | L1 | `unit/test_db_solution::test_delete_solution_cascades_eval` | Implemented |
| FR-SOL-017 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_json_mode_requires_force` | Implemented |
| FR-SOL-018 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_show_stdout` | Implemented |
| FR-SOL-019 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_export_default` | Implemented |
| FR-SOL-020 | SHOULD | DES-005 | L2 | `integration/test_solution::test_solution_diff_different` | Implemented |
| FR-SOL-021 | MUST | DES-005 §extract/§4.6, ADR-007 §capabilities | L2 | `integration/test_solution::test_solution_extract_rank_n_shinka` | Implemented (S18 / top-N #299 — `solution extract --rank N` (and `--program-id <id>` where supported) promotes an arbitrary-ranked/identified population program, gated on `capabilities().top_n_extraction`; Shinka reads `programs.sqlite` retroactively and materializes `programs/rank-<N>.py`; `(run_id, rank)` uniqueness enforced; `--rank 1` behaves exactly as today) |
| FR-SOL-021 | MUST | DES-005 §4.6, ADR-007 §capabilities | L2 | `integration/test_solution::test_solution_extract_rank_unsupported_oe` | Implemented (S18 / top-N #299 — a non-capable backend (OpenEvolve, consciously deferred) exits 1 with a clear "not supported on `<backend>`" error) |

---

## 9. Benchmark — `revolver benchmark`

Design: [DES-007](../architecture/design/DES-007-benchmark-design.md), [DES-001 §benchmarks](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-BEN-001 | MUST | DES-007 §input | L2 | `integration/test_benchmark::test_accepts_multiple_solutions` | Implemented |
| FR-BEN-002 | MUST | DES-007 §reuse | L1 | `unit/test_core_benchmark::test_reuses_existing_eval` | Implemented |
| FR-BEN-003 | MUST | DES-007 §eval | L2 | `integration/test_benchmark::test_runs_missing_evals` | Implemented |
| FR-BEN-004 | MUST | DES-007 §compare | L2 | `integration/test_benchmark::test_comparative_table` | Implemented |
| FR-BEN-005 | MUST | DES-007 §lineage | L1 | `unit/test_core_benchmark::test_includes_lineage` | Implemented |
| FR-BEN-006 | MUST | DES-007, DES-001 | L2 | `integration/test_benchmark::test_benchmark_output_contains_benchmark_id` | Implemented |
| FR-BEN-007 | MUST | DES-007 §export | L2 | `integration/test_benchmark::test_export_csv` | Implemented |
| FR-BEN-008 | MUST | DES-007 §export | L2 | `integration/test_benchmark::test_export_json` | Implemented |
| FR-BEN-009 | MUST | DES-007 §results | L1 | `unit/test_core_benchmark::test_get_results_per_instance` (checks eval_time, solved) | Implemented |
| FR-BEN-010 | SHOULD | DES-007 §sort | L1 | `unit/test_core_benchmark::test_win_counting` | Implemented |
| FR-BEN-011 | SHOULD | DES-007 §lineage | L1 | `unit/core/test_benchmark::test_includes_gen_time` | Planned |
| FR-BEN-012 | MUST | DES-007 | L2 | `integration/test_benchmark::test_list_benchmarks` | Implemented |
| FR-BEN-013 | MUST | DES-007 §export, NFR-052 | L1 | `unit/test_core_benchmark::test_no_secrets_in_csv_export`, `unit/test_core_benchmark::test_no_secrets_in_json_export` | Implemented |
| FR-BEN-014 | MUST | DES-007 §results | L2 | `integration/test_benchmark::test_results_per_instance` | Implemented |
| FR-BEN-015 | SHOULD | DES-007 §results | L1 | `unit/test_core_benchmark::test_get_results_per_instance` | Implemented |
| FR-BEN-016 | MUST | DES-007 §export | L2 | `integration/test_benchmark::test_export_per_instance` | Implemented |
| FR-BEN-017 | MUST | DES-007 §results, DES-001 | L1 | `unit/test_core_benchmark::test_includes_lineage` (checks run_id) | Implemented |
| FR-BEN-018 | MUST | DES-007 | L2 | `integration/test_benchmark::test_benchmark_delete_confirm_prompt` | Implemented |
| FR-BEN-018 | MUST | DES-007 | L2 | `integration/test_benchmark::test_benchmark_delete_nonexistent` | Implemented |
| FR-BEN-018 | MUST | DES-007 | L2 | `integration/test_benchmark::test_benchmark_delete_force` | Implemented |
| FR-BEN-019 | MUST | DES-007 | L2 | `integration/test_benchmark::test_benchmark_delete_force` | Implemented (`delete --force` skips the prompt; benchmark and `benchmark_solutions` rows removed) |
| FR-BEN-020 | MUST | DES-007, NFR-003 | L2 | `integration/test_benchmark::test_benchmark_delete_json_requires_force` | Implemented (v0.19.0 pre-release review — `--json` without `--force` exits 1 naming `--force`; the benchmark stays) |

---

## 10. Setup & Doctor — `revolver doctor`, `revolver setup`

Design: [Architecture §4.2](../architecture/architecture.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-SET-001 | MUST | Arch §4.2 | L2 | `integration/test_doctor::test_doctor_all_ok` | Implemented |
| FR-SET-002 | MUST | Arch §4.2 | L1 | `unit/test_doctor::test_check_openevolve_installed`, `unit/test_doctor::test_check_openevolve_missing` | Implemented |
| FR-SET-003 | MUST | Arch §4.2, ADR-001 | L2 | `integration/test_doctor::test_doctor_ollama_missing` | Implemented |
| FR-SET-004 | MUST | Arch §4.2 | L1 | `unit/test_doctor::test_check_nvidia_smi_available`, `unit/test_doctor::test_check_nvidia_smi_not_found` | Implemented |
| FR-SET-005 | MUST | Arch §4.2 | L2 | `integration/test_doctor::test_doctor_all_ok`, `integration/test_doctor::test_doctor_warn_only`, `integration/test_doctor::test_doctor_missing_dep_fail` | Implemented |
| FR-SET-006 | MUST | Arch §4.2 | L1 | `unit/test_doctor::test_fixable_vs_system` | Implemented |
| FR-SET-007 | MUST | Arch §4.2 | L2 | `integration/test_setup::test_setup_installs_missing_pip` | Implemented |
| FR-SET-008 | MUST | Arch §4.2 | L2 | `integration/test_setup::test_setup_asks_confirmation` | Implemented |
| FR-SET-009 | MUST | Arch §4.2 | L1 | `unit/test_setup::test_plan_never_installs_system_pkg` | Implemented |
| FR-SET-010 | MUST | Arch §4.2 | L2 | `integration/test_setup::test_setup_instructions_for_non_fixable` | Implemented |
| FR-SET-011 | SHOULD | Arch §4.2 | L2 | `integration/test_setup::test_setup_dry_run` | Implemented |
| FR-SET-012 | SHOULD | Arch §4.2 | L2 | `integration/test_doctor::test_doctor_works_outside_project` | Implemented |
| FR-SET-013 | SHOULD | Arch §4.2 | L2 | `integration/test_doctor::test_doctor_reports_versions` | Implemented |
| FR-SET-014 | SHOULD | Arch §4.2 | L1 | `unit/test_setup::test_detects_conda` | Implemented |
| FR-SET-015 | SHOULD | Arch §4.2 | L2 | `integration/test_setup::test_setup_ollama_via_conda` | Implemented |
| FR-SET-016 | SHOULD | Arch §4.2 | L1 | `unit/test_setup::test_plan_reports_install_method` | Implemented |
| FR-SET-017 | SHOULD | Arch §4.2 | L2 | `integration/test_setup::test_setup_manual_instructions_no_conda` | Implemented |

---

## 11. Non-Functional Requirements (testable)

| NFR ID | Pri | Category | Level | Test ID | Status |
|---|---|---|---|---|---|
| NFR-001 | MUST | CLI | L2 | `integration/test_cross_cutting::test_exit_code_0_on_success` | Planned |
| NFR-002 | MUST | CLI | L2 | `integration/test_cross_cutting::test_help_on_all_commands` | Implemented |
| NFR-003 | MUST | CLI | L2 | `integration/test_cross_cutting::test_json_flag_all_commands` | Implemented |
| NFR-004 | MUST | CLI | L2 | `integration/test_cross_cutting::test_errors_on_stderr` | Implemented |
| NFR-005 | SHOULD | CLI | L2 | `integration/test_cross_cutting::test_progress_on_stderr` | Implemented |
| NFR-006 | SHOULD | CLI | L2 | `integration/test_cross_cutting::test_confirmation_summary` | Implemented |
| NFR-007 | MUST | CLI | L2 | `integration/test_cross_cutting::test_single_binary_subcommands` | Implemented |
| NFR-010 | MUST | Storage | L2 | `test_project_integration::test_init_creates_structure` (checks .revolver/ dir) | Implemented |
| NFR-011 | MUST | Storage | L2 | `integration/test_llm::test_global_data_in_home` | Planned |
| B6 (no FR) | MUST | Storage — `--global-db` / `REVOLVER_HOME` | L1, L2 | `test_config::test_global_config_respects_revolver_home`, `test_db::test_global_db_respects_revolver_home`, `test_db::test_global_db_path_override_beats_revolver_home`, `integration/test_llm::test_global_db_flag_routes_reads_and_writes` (+ `::test_global_db_flag_equals_form`, `::test_global_db_flag_beats_revolver_home`, `::test_global_db_flag_does_not_swallow_following_option`, `::test_global_db_flag_empty_value_is_ignored`) | Implemented (S17 / B6 — global DB path resolution via `--global-db` flag and `REVOLVER_HOME`; documented override precedence) |
| NFR-013 | MUST | Storage | L2 | `test_project_integration::test_init_creates_structure` (checks revolver.db) | Implemented |
| NFR-013 | MUST | DES-001 §5.9 | L1 | `unit/test_db_migration_v10::test_migration_v9_to_v10_drops_cost_columns`, `::test_migration_v9_to_v10_project_db` | Implemented (S16 — drop `llms` pricing columns, #300) |
| NFR-013 | MUST | DES-001 §5.10 | L1 | `unit/test_db_migration_v11::test_migration_v10_to_v11_widens_split_check`, `::test_migration_v10_to_v11_global_db` | Implemented (S16 — widen `datasets.split` to `both`, UX-3) |
| NFR-013 | MUST | DES-001 §4.1 | L1 | `unit/test_db_migration_v12::test_current_schema_version_at_least_12`, `::test_fresh_global_db_has_reasoning_effort_column`, `::test_migration_v11_to_v12_adds_column_preserves_rows`, `::test_reasoning_effort_round_trips_through_crud`, `::test_migration_v11_to_v12_project_db` | Implemented (S17 — add `llms.reasoning_effort` column; v11→v12 upgrade preserves existing rows) |
| NFR-013 | MUST | DES-001 §4.3 | L1 | `unit/test_db_migration_v13::test_current_schema_version_at_least_13`, `::test_fresh_global_db_has_member_reasoning_effort_column`, `::test_migration_v12_to_v13_adds_column_preserves_rows`, `::test_migration_v12_to_v13_project_db` | Implemented (S17 — add `ensemble_members.reasoning_effort` column; v12→v13 upgrade preserves existing rows) |
| NFR-013 | MUST | DES-001 (migration v14) | L1 | `unit/test_db_migration_v14::test_db_migration_v14_problem_versions_backend` | Implemented (S18 — add `problem_versions.backend` column, project DB only; fresh + v13→v14 upgrade preserve existing rows defaulting `'openevolve'`; global DB no-ops-and-bumps, v10/v12/v13 guard pattern) |
| NFR-014 | MUST | Storage | L1 | `test_hashing::test_sha256_used` | Implemented |
| NFR-015 | MUST | Storage | L2 | `integration/test_problem::test_snapshot_immutable` | Planned |
| NFR-016 | SHOULD | Storage | L1 | `test_db::test_wal_mode_enabled` | Implemented |
| NFR-017 | MUST | Storage | L2 | `integration/test_run::test_run_dataset_integrity_failure` | Implemented |
| NFR-020 | MUST | Reprod. | L2 | `integration/test_run::test_run_info_full_details` | Implemented |
| NFR-021 | MUST | Reprod. | L1 | `unit/core/test_llm::test_model_pinned_by_digest` | Planned |
| NFR-022 | MUST | Reprod. | L1 | `test_hashing::test_per_instance_hashes` | Implemented |
| NFR-023 | SHOULD | Reprod. | L2 | `integration/test_run::test_config_stored_verbatim` | Planned |
| NFR-024 | SHOULD | Reprod. | L2 | `integration/test_run_shinka::test_seed_warning_on_shinka` (S14) | Planned |
| NFR-030 | MUST | Perf. | — | Manual validation (not CI-gated) | — |
| NFR-031 | SHOULD | Perf. | — | Manual validation (not CI-gated) | — |
| NFR-032 | SHOULD | Perf. | — | Manual validation (not CI-gated) | — |
| NFR-050 | MUST | Security | L1 | `test_db_llm::test_api_key_env_stored_not_value` | Implemented |
| NFR-051 | MUST | Security | L2 | `test_project_integration::test_init_directory_permissions`, `test_store::test_permissions_700` | Implemented |
| NFR-052 | MUST | Security | L1 | `unit/test_core_benchmark::test_no_secrets_in_csv_export` | Implemented |
| NFR-060 | MUST | Deploy | — | Verified by packaging (pyproject.toml) | — |
| NFR-061 | MUST | Deploy | — | Verified by packaging (pyproject.toml) | — |
| #354 doc-lint (no FR) | infra | Docs — CLI-tree lint | L2 | `unit/test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_invocations_resolve`, `::test_corpus_includes_contributor_docs` | Implemented (S18 / #354 — every **line-initial** fenced `revolver` invocation in the docs resolves in the Typer CLI tree; a renamed/removed flag is caught; deprecated `--tag` denylisted; untagged fences parsed; inline-prose backtick mentions out of scope; L2 by scope but runs under the `unit` CI marker in the blocking selection, sprint-018 S18-21 — validation.md §8.1 marker-vs-level rule. `test_corpus_includes_contributor_docs` (#290, issue #279) pins the corpus composition: the root Markdown files are linted, `CHANGELOG.md` is excluded, every tracked root `*.md` is classified) |
| #355 freshness stamps (no FR) | infra | Docs — verified-against stamps | L1 | `unit/test_doc_freshness::TestDocFreshnessCorpus::test_corpus_is_stamped_and_fresh` | Implemented (S18 / #355 PR #256 — guides + specs-side E2E walkthrough carry `verified-against` front-matter; >1-minor lag or missing stamp fails CI incl. docs-only PRs via the doc-lint job of ci.yml; fresh-major X.0 grace window) |

### NFRs with indirect coverage

The following MUST NFRs are not tested independently — they are satisfied by FR-level tests or by infrastructure constraints. Listed here for traceability completeness.

| NFR ID | Pri | Category | Covered by | Rationale |
|---|---|---|---|---|
| NFR-008 | SHOULD | CLI | — | Tab completion: not automatically testable, verified manually |
| NFR-012 | MUST | Storage | FR-PRB-009, FR-PRJ-002 | YAML manifests tested via problem version and project init |
| NFR-040 | MUST | Compat. | CI pipeline | Linux enforced by CI runner OS; WSL2 verified by dev environment |
| NFR-041 | MUST | Compat. | FR-SET-004 | GPU detection tested via `doctor` checks |
| NFR-042 | MUST | Compat. | FR-SET-003 | Ollama detection tested via `doctor` checks |
| NFR-043 | SHOULD | Compat. | E2E Sc.2 (planned) | Graceful degradation without Ollama (remote-only LLMs keep working) — covered by the remote-only E2E scenario once implemented; no dedicated L1/L2 test |
| NFR-044 | MUST | Compat. | Architecture | Network isolation enforced by mocking in L1/L2; no outbound calls except explicit LLM/Ollama |
| NFR-062 | MUST | Deploy | FR-SET-006, FR-SET-009 | System deps detected (not managed) — tested via doctor fixable/system classification and setup never-install-system |
| NFR-063 | MUST | Deploy | FR-SET-001..005 | `doctor` checks all deps — tested per dependency type |
| NFR-064 | MUST | Deploy | FR-SET-007, FR-SET-008 | `setup` installs missing — tested via install and confirmation tests |
| NFR-065 | MUST | Deploy | FR-SET-009, FR-SET-010 | `setup` never installs system software — tested explicitly |
| NFR-066 | SHOULD | Deploy | FR-SET-005 | Clear pass/warn/fail status — tested via ok_warn_fail_status test |
| NFR-067 | SHOULD | Compat. | NFR-043 (E2E Sc.2) | Graceful degradation — covered by remote-only E2E scenario |
| NFR-068 | SHOULD | Deploy | FR-SET-011 | `setup --dry-run` — tested via dry_run integration test |

---

## 12. End-to-End Coverage

| E2E Scenario | FRs Covered | Status |
|---|---|---|
| **Scenario 1 — Alice / Job-Shop** | FR-SET-001..005, FR-LLM-001..010, FR-PRJ-001..006, FR-PRB-001..009, FR-DAT-001..007, FR-RUN-001..012, FR-SOL-001..008, FR-EVL-001..007, FR-BEN-001..009 | Planned |
| **Scenario 2 — Remote-Only (TBD)** | FR-LLM-001/015/017, FR-RUN-015/028/029, NFR-043 | Planned |
| **Scenario 3 — ShinkaEvolve Backend Happy Path** | FR-RUN-047/048, NFR-024/061, FR-SET-002 | Implemented (S14) |
| **Scenario 4 — Shinka Bandit Ensemble** | FR-RUN-046/049/050, FR-LLM-026 | Planned (S17 — 2+ members, `--selection ucb`, adaptive bandit against the fake server) |
| **Scenario 5 — Timeout Penalize-vs-Drop** | FR-RUN-052/053/054/055, FR-EVL-021 | Planned (S19 carry-over — was S18-optional per sprint-018 §doc-cascade; the penalize/drop semantics are L2-covered by `test_on_timeout_penalize_vs_drop`; this row is the L3 fake-server variant: a hanging instance under default `penalize` vs `--config-override evaluation.on_timeout=drop`) |

---

## 13. Coverage Summary

| Spec File | Total Reqs | MUST | SHOULD | MAY | L1 Tests | L2 Tests | L3 (E2E) | Untested |
|---|---|---|---|---|---|---|---|---|
| spec-project | 8 | 6 | 2 | 0 | 0 | 8 | 0 (Sc.1 planned) | 0 |
| spec-llm | 26 | 18 | 7 | 0 | 4 | 15 | 0 (Sc.1/2 planned) | 6 |
| spec-problem | 16 | 11 | 4 | 1 | 2 | 11 | 0 (Sc.1 planned) | 4 |
| spec-dataset | 16 | 14 | 2 | 0 | 2 | 13 | 0 (Sc.1 planned) | 1 |
| spec-run | 57 | 44 | 11 | 0 | 26 | 34 | 2 (Sc.3) | 7 |
| spec-eval | 21 | 18 | 2 | 1 | 3 | 12 | 0 (Sc.1/5 planned) | 7 (incl. 1 deferred) |
| spec-solution | 21 | 20 | 1 | 0 | 2 | 16 | 0 (Sc.1 planned) | 3 |
| spec-benchmark | 20 | 17 | 3 | 0 | 7 | 12 | 0 (Sc.1 planned) | 1 |
| spec-setup | 17 | 10 | 7 | 0 | 6 | 11 | 1 (Sc.3) | 0 |
| NFR (direct) | 27 | 20 | 7 | 0 | 6 | 11 | 2 (Sc.3) | 9 (3 perf manual + NFR-060 packaging + 5 Planned) |
| NFR (indirect) | 14 | 9 | 5 | 0 | — | — | — | 0 (covered by FR tests) |
| **Total** | **243** | **187** | **51** | **2** | **58** | **143** | **5** (Sc.3 only; Sc.1/2/4/5 planned) | **38** |

Counting method (recomputed at v0.19.0 with a script over the real files; the previous recount dated from v0.17):
- **Total / MUST / SHOULD / MAY** — the FR rows (`| FR-XXX-NNN | PRI |`) of each `docs/specs/spec-*.md`; the three Removed / deleted rows (FR-LLM-018, FR-RUN-030, FR-RUN-042) count in Total only, hence Total − (MUST + SHOULD + MAY) = 3. NFR priorities come from `specifications.md` §3; "direct" = ids in the §11 main table (27), "indirect" = the §11 indirect table (14) — together all 41 NFRs.
- **L1 / L2 Tests** — distinct requirement ids of the spec with at least one matrix row whose Status is `Implemented` / `Passing` and whose Level cell contains L1 (resp. L2, L2-OE or L2-Shinka); an id with both levels counts once in each column.
- **L3 (E2E)** — distinct ids covered by a §12 scenario whose Status is `Implemented` (today only Scenario 3: FR-RUN-047/048, FR-SET-002, NFR-024/061).
- **Untested** — ids with a priority and no `Implemented` row at any level: Planned-only (28 FRs + 5 NFRs), the deferred MAY FR-EVL-014, the three manual performance NFRs and the packaging-verified NFR-060.
- Row basis for comparison: 286 rows across §2–§11 — 241 `Implemented`, 36 `Planned`, 9 without a test (Removed / Deleted / Deferred / manual / packaging).

Notes:
- **Traceability debt (v0.19.0)**: fifteen MUST requirements are still traced to Planned tests only — FR-LLM-005/010/015, FR-PRB-005, FR-DAT-004, FR-RUN-011/015, FR-EVL-003/004/006/011/017, FR-SOL-004/005/010; tracked as issue #297 (traceability debt), to be resolved in Sprint 020.
- FR-RUN-030 (cost estimation) and FR-LLM-018 (`--input-cost`/`--output-cost` pricing) are both **Removed** (S15 / #300, completed in S16): cost is no longer reported. The `estimate_cost()` helper and the LLM pricing flags/columns were dropped — schema migration v10 removes the two `llms` pricing columns. Both rows carry no test (status **Removed**); their former coverage is dropped from the counts. The renamed test `test_llm_add_remote_with_pricing` → `test_llm_add_remote` is re-pointed to FR-LLM-001.
- Schema migrations v10 (drop `llms` pricing columns, #300) and v11 (widen `datasets.split` to `both`, UX-3) add 4 new L1 migration-test rows under NFR-013 (`unit/test_db_migration_v10`, `unit/test_db_migration_v11`).
- **S17 (v0.17 multi-LLM ensemble, ADR-007 Amendment A1–A5)**: FR-RUN-049 (`--selection`, incl. OE-rejects-non-weighted), FR-RUN-050 (`--llm-weight`), FR-RUN-051 (B7 OE best-on-interrupt via `solution extract --from-checkpoint`), FR-LLM-026 (per-LLM `reasoning_effort`, both backends), and FR-EVL-021 (B1 aggregation numeric guard) added. FR-RUN-046 gains a second row targeting the Shinka **bandit** ensemble (`FixedSampler.prior_probs`), superseding the "weights dropped/warned" framing (ADR-007 A2). B2 (OE post-run teardown) gets its own regression row. Schema migrations v12 (`llms.reasoning_effort`) and v13 (`ensemble_members.reasoning_effort`) add 2 L1 migration-test rows under NFR-013. All S17 rows are now **Implemented** (code shipped and passing); the repointed Test IDs reference the real test functions. The new L3 Shinka bandit-ensemble scenario is tracked in §12 (E2E Scenario 4).
- **S18 (v0.18 eval-honesty semantic slice + top-N flagship, sprint-018)**: FR-RUN-052 (display prefers `combined_score`), FR-RUN-053 (wrapper `instances_*` coverage keys + timeout side-channel), FR-RUN-054 (`evaluation.on_timeout` penalize|drop + `timeout_score`, default **penalize**), FR-RUN-055 (dual-score `run info` labels), FR-RUN-056 (`validate_seed_metrics` pre-flight hook), FR-RUN-057 (default checkpoint cadence, SHOULD), FR-PRB-016 (`problem_versions.backend`, migration v14), and FR-SOL-021 (`solution extract --rank N`/`--program-id` gated on `capabilities().top_n_extraction`) added — all rows enter as **Planned** with the sprint-018 L2 test IDs and flip to Implemented as the S18 PRs land (S18 rows were flipped to Implemented in the v0.18.0 pre-release pass). Amended: FR-RUN-019/020 (post-run eval persists via `core.eval.evaluate_solution`), FR-RUN-047 (backend resolution explicit > version > default + mismatch warn), FR-SOL-011/012 (rank-1 default / duplicate per `(run_id, rank)`), FR-EVL-021 (reserved `instances_*` keys excluded from aggregation). Migration v14 adds 1 L1 test row under NFR-013 (v12/v13 precedent). Two no-FR infra rows: #359 reap hardening (`test_reaper_grandchild_killpg`, §6) and #354 doc command-lint (`unit/test_doc_command_lint::TestDocCommandLintCorpus::test_corpus_invocations_resolve`, §11). The new L3 penalize-vs-drop scenario is tracked in §12 (E2E Scenario 5).
- Run delete: FR-RUN-035 keeps its 11 entries; FR-RUN-036..039 (previously absorbed under FR-RUN-035) now have **dedicated rows** mapped to `DES-005 §4.8` and the real `test_run_delete::*` / `integration/test_run::test_run_delete_all*` tests.
- Benchmark delete (FR-BEN-018) adds 3 new test entries covering confirmation, nonexistent, and force delete.
- Many FR-level tests cover multiple requirements. The total counts distinct test assignments (some FRs have both L1 and L2 tests).
- 13 NFRs are covered indirectly by FR-level tests (see §11 indirect coverage table). They are not double-counted in L1/L2 totals.
- Untested/planned items: 3 performance NFRs (manual validation) + 1 deferred MAY (FR-EVL-014) + 36 rows still Planned (row-based recount at the v0.19.0 pre-release pass: 36 Planned vs 241 Implemented rows across §2–§11). The §13 table above aggregates at the requirement level (a different basis than rows) and was last fully recomputed at v0.19.0 — see "Counting method" above.
- **v0.19.0 pre-release validation review**: every cited test id was re-verified against the test sources — FR-LLM-020..025 (`integration/test_ensemble`), FR-RUN-031/040/041/044/045/046 and the doc-guard ids (`unit/` prefix) were repointed; FR-BEN-019/020 rows added (FR-BEN-020 with a new test); the `test_evaluator_runner` and `TestRunDeleteCLI` rows are relabelled L2 and FR-RUN-052 L1 to follow the modules' markers (validation.md §8.1); FR-RUN-042 (deleted id) and NFR-043 (indirect, E2E Sc.2) now have rows so that every spec id resolves in the matrix.
- Compared to v0.1, the majority of entries have been updated from Planned to Implemented based on verification of existing test functions in the `tests/` directory.
