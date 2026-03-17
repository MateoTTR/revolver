# Revolver — Traceability Matrix

**Version**: 0.1 — Initial draft
**Date**: 2026-03-13
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
| **Test ID** | Planned test name (placeholder until Phase 5) |
| **Status** | `Planned` → `Written` → `Passing` |

> **Note:** A single FR may appear on multiple rows when covered by tests at different levels (L1, L2) or by distinct test scenarios.

---

## 2. Project — `revolver project`

Design: [Architecture §4.1](../architecture/architecture.md), [DES-001](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-PRJ-001 | MUST | Arch §4.1, DES-001 | L2 | `integration/test_project::test_init_creates_structure` | Planned |
| FR-PRJ-002 | MUST | Arch §4.1 | L2 | `integration/test_project::test_init_creates_project_yaml` | Planned |
| FR-PRJ-003 | MUST | DES-003 §2 | L2 | `integration/test_project::test_init_creates_initial_program` | Planned |
| FR-PRJ-004 | MUST | DES-003 §2, ADR-006 | L2 | `integration/test_project::test_init_creates_evaluator` | Planned |
| FR-PRJ-005 | MUST | DES-005 | L2 | `integration/test_project::test_init_creates_config` | Planned |
| FR-PRJ-006 | MUST | — | L2 | `integration/test_project::test_init_existing_project_fails` | Planned |
| FR-PRJ-007 | SHOULD | — | L2 | `integration/test_project::test_init_with_path_option` | Planned |
| FR-PRJ-008 | SHOULD | NFR-051 | L2 | `integration/test_project::test_init_directory_permissions` | Planned |

---

## 3. LLM — `revolver llm`

Design: [DES-002](../architecture/design/DES-002-llm-subcommands.md), [DES-001 §llms](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-LLM-001 | MUST | DES-002 §add | L2 | `integration/test_llm::test_add_remote_llm` | Planned |
| FR-LLM-002 | MUST | DES-002 §add | L2 | `integration/test_llm::test_add_ollama_llm` | Planned |
| FR-LLM-003 | MUST | DES-001, DES-002 | L1 | `unit/core/test_llm::test_registration_persisted_global_db` | Planned |
| FR-LLM-004 | MUST | DES-002 §add | L2 | `integration/test_llm::test_add_with_pull` | Planned |
| FR-LLM-005 | MUST | DES-002 §add | L1 | `unit/core/test_llm::test_digest_recorded` | Planned |
| FR-LLM-006 | MUST | DES-002 §start | L2 | `integration/test_llm::test_start_loads_model` | Planned |
| FR-LLM-007 | MUST | DES-002 §stop | L2 | `integration/test_llm::test_stop_unloads_model` | Planned |
| FR-LLM-008 | MUST | DES-002 §start | L1 | `unit/core/test_llm::test_single_model_at_a_time` | Planned |
| FR-LLM-009 | MUST | DES-002 §status | L2 | `integration/test_llm::test_status_shows_vram` | Planned |
| FR-LLM-010 | MUST | DES-002 | L1 | `unit/core/test_llm::test_base_url_exposed` | Planned |
| FR-LLM-011 | SHOULD | DES-002 §start | L1 | `unit/core/test_llm::test_vram_warning` | Planned |
| FR-LLM-012 | SHOULD | DES-002 §start | L1 | `unit/core/test_llm::test_throughput_recorded` | Planned |
| FR-LLM-013 | SHOULD | DES-002 §start | L2 | `integration/test_llm::test_health_check_after_start` | Planned |
| FR-LLM-014 | MUST | DES-002 §remove | L2 | `integration/test_llm::test_remove_existing` | Planned |
| FR-LLM-015 | MUST | DES-002 §status | L1 | `unit/core/test_llm::test_remote_status_ready_if_env_set` | Planned |
| FR-LLM-016 | SHOULD | DES-002 §add | L2 | `integration/test_llm::test_add_openai_compat` | Planned |
| FR-LLM-017 | MUST | DES-002, NFR-050 | L1 | `unit/core/test_llm::test_api_key_never_stored` | Planned |
| FR-LLM-018 | SHOULD | DES-002, DES-005 §4.5 | L2 | `integration/test_llm::test_add_with_pricing` | Planned |

---

## 4. Problem — `revolver problem`

Design: [DES-003](../architecture/design/DES-003-problem-versioning.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-PRB-001 | MUST | DES-003 §test | L2 | `integration/test_problem::test_test_single_instance` | Planned |
| FR-PRB-002 | MUST | DES-003 §test | L2 | `integration/test_problem::test_test_dataset` | Planned |
| FR-PRB-003 | MUST | DES-003 §test | L2 | `integration/test_problem::test_test_catches_evaluator_error` | Planned |
| FR-PRB-004 | MUST | DES-003 §test | L1 | `unit/core/test_problem::test_per_instance_timeout` | Planned |
| FR-PRB-005 | MUST | DES-003 §test | L1 | `unit/core/test_problem::test_validates_return_dict` | Planned |
| FR-PRB-006 | MUST | DES-003 §version | L2 | `integration/test_problem::test_version_creates_snapshot` | Planned |
| FR-PRB-007 | MUST | DES-003 §version | L1 | `unit/infra/test_hashing::test_snapshot_hash_sha256` | Planned |
| FR-PRB-008 | MUST | DES-003 §version | L2 | `integration/test_problem::test_version_duplicate_tag_fails` | Planned |
| FR-PRB-009 | MUST | DES-003 §version | L2 | `integration/test_problem::test_version_creates_manifest` | Planned |
| FR-PRB-010 | MUST | DES-003 §version | L2 | `integration/test_problem::test_version_missing_file_fails` | Planned |
| FR-PRB-011 | SHOULD | DES-003 §test | L2 | `integration/test_problem::test_test_verbose_output` | Planned |
| FR-PRB-012 | SHOULD | DES-003 §test | L2 | `integration/test_problem::test_test_progress_bar` | Planned |
| FR-PRB-013 | MAY | DES-003 §test | L1 | `unit/core/test_problem::test_warns_missing_combined_score` | Planned |
| FR-PRB-014 | SHOULD | DES-003 §version | L2 | `integration/test_problem::test_version_includes_problem_md` | Planned |
| FR-PRB-015 | SHOULD | DES-003, DES-005 | L2 | `integration/test_run::test_problem_md_injected` | Planned |

---

## 5. Dataset — `revolver dataset`

Design: [DES-004](../architecture/design/DES-004-dataset-registration.md), [DES-001 §datasets](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-DAT-001 | MUST | DES-004 §add | L1 | `unit/core/test_dataset::test_register_by_reference` | Planned |
| FR-DAT-002 | MUST | DES-004 §hash | L1 | `unit/infra/test_hashing::test_dataset_hash_computation` | Planned |
| FR-DAT-003 | MUST | DES-004 §add | L1 | `unit/core/test_dataset::test_absolute_path_stored` | Planned |
| FR-DAT-004 | MUST | DES-004 §add | L1 | `unit/core/test_dataset::test_instance_count_auto` | Planned |
| FR-DAT-005 | MUST | DES-004 §snapshot | L2 | `integration/test_dataset::test_add_with_snapshot` | Planned |
| FR-DAT-006 | MUST | DES-004 §add | L2 | `integration/test_dataset::test_add_with_split` | Planned |
| FR-DAT-007 | MUST | DES-004 §compat | L2 | `integration/test_dataset::test_add_with_compatible_version` | Planned |
| FR-DAT-008 | MUST | DES-004 §update | L2 | `integration/test_dataset::test_update_compat_versions` | Planned |
| FR-DAT-009 | MUST | DES-004 §verify | L2 | `integration/test_dataset::test_info_verify_recomputes_hash` | Planned |
| FR-DAT-010 | MUST | DES-004 §verify | L1 | `unit/core/test_dataset::test_integrity_check_at_usage` | Planned |
| FR-DAT-011 | MUST | DES-004 §add | L2 | `integration/test_dataset::test_add_duplicate_name_fails` | Planned |
| FR-DAT-012 | SHOULD | DES-004 §hash | L1 | `unit/infra/test_hashing::test_subdirectory_tree_hash` | Planned |
| FR-DAT-013 | SHOULD | DES-004 §compat | L1 | `unit/core/test_dataset::test_warns_incompatible_version` | Planned |
| FR-DAT-014 | MUST | DES-004 §remove | L2 | `integration/test_dataset::test_remove_deletes_metadata` | Planned |
| FR-DAT-015 | MUST | DES-004 §remove | L2 | `integration/test_dataset::test_remove_blocked_by_reference` | Planned |
| FR-DAT-016 | MUST | DES-004 §remove | L2 | `integration/test_dataset::test_remove_snapshot_deletes_files` | Planned |

---

## 6. Run — `revolver run`

Design: [DES-005](../architecture/design/DES-005-run-orchestration.md), [DES-001 §runs/solutions](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-RUN-001 | MUST | DES-005 §2.1 | L2, L2-OE | `integration/test_run::test_run_validates_inputs`, `integration/test_run_oe::test_oe_controller_instantiation` | Planned |
| FR-RUN-002 | MUST | DES-005 §2.1 | L1 | `unit/core/test_run::test_warns_non_train_split` | Planned |
| FR-RUN-003 | MUST | DES-005 §2.1 | L1 | `unit/core/test_run::test_warns_incompatible_dataset` | Planned |
| FR-RUN-004 | MUST | DES-005 §2.1 | L1 | `unit/core/test_run::test_integrity_check_before_run` | Planned |
| FR-RUN-005 | MUST | DES-005 §env, ADR-006 | L1, L2-OE | `unit/core/test_run::test_sets_dataset_dir_env`, `integration/test_run_oe::test_build_config_roundtrip_to_oe_config`, `integration/test_run_oe::test_openevolve_runner_init_controller` | Planned |
| FR-RUN-006 | MUST | DES-005 §config | L1, L2-OE | `unit/core/test_run::test_configures_openevolve_llm`, `integration/test_run_oe::test_build_config_roundtrip_to_oe_config`, `integration/test_run_oe::test_openevolve_runner_init_controller` | Planned |
| FR-RUN-007 | MUST | DES-005 §id | L1 | `unit/core/test_run::test_unique_run_id_format` | Planned |
| FR-RUN-008 | MUST | DES-005 §post-run | L2 | `integration/test_run::test_run_stores_programs_and_solution` | Planned |
| FR-RUN-009 | MUST | DES-005 §manifest | L2 | `integration/test_run::test_run_records_lineage` | Planned |
| FR-RUN-010 | MUST | DES-005, DES-001 | L1 | `unit/core/test_run::test_metrics_stored_in_db` | Planned |
| FR-RUN-011 | MUST | DES-005 §checkpoint | L2 | `integration/test_run::test_run_stores_checkpoint` | Planned |
| FR-RUN-012 | MUST | DES-005 §alias | L2 | `integration/test_run::test_run_with_alias` | Planned |
| FR-RUN-013 | MUST | DES-005 §resume | L2 | `integration/test_run::test_resume_creates_new_run` | Planned |
| FR-RUN-014 | MUST | DES-005 §concurrency | L1 | `unit/core/test_run::test_local_llm_sequential` | Planned |
| FR-RUN-015 | MUST | DES-005 §concurrency | L1 | `unit/core/test_run::test_remote_llm_parallel` | Planned |
| FR-RUN-016 | SHOULD | DES-005 §progress | L2 | `integration/test_run::test_run_shows_progress` | Planned |
| FR-RUN-017 | SHOULD | DES-005 §config | L2 | `integration/test_run::test_config_stored_verbatim` | Planned |
| FR-RUN-018 | SHOULD | DES-005 §manifest | L1 | `unit/core/test_run::test_wallclock_recorded` | Planned |
| FR-RUN-019 | MUST | DES-005 §post-run | L2 | `integration/test_run::test_run_evaluates_rank1_on_train` | Planned |
| FR-RUN-020 | MUST | DES-005, DES-006 | L2 | `integration/test_run::test_train_results_accessible_via_eval` | Planned |
| FR-RUN-021 | MUST | DES-005 | L2 | `integration/test_run::test_run_list_with_filters` | Planned |
| FR-RUN-022 | MUST | DES-005 | L2 | `integration/test_run::test_run_info_full_details` | Planned |
| FR-RUN-023 | MUST | DES-005 §2.1 | L2 | `integration/test_run::test_dry_run_no_launch` | Planned |
| FR-RUN-024 | MUST | DES-005 §resume | L1 | `unit/core/test_run::test_resume_copies_wrapper` | Planned |
| FR-RUN-025 | SHOULD | DES-005 §locks | L1 | `unit/core/test_run::test_lock_file_management` | Planned |
| FR-RUN-026 | SHOULD | DES-005, ADR-006 | L1 | `unit/core/test_run::test_sets_instance_log_env` | Planned |
| FR-RUN-027 | SHOULD | DES-005 | L1 | `unit/core/test_run::test_sets_eval_log_env` | Planned |
| FR-RUN-028 | SHOULD | DES-005 §4.5, DD-14 | L1 | `unit/infra/test_token_proxy::test_token_extraction` | Planned |
| FR-RUN-029 | SHOULD | DES-005 §4.5 | L2 | `integration/test_run::test_run_displays_tokens` | Planned |
| FR-RUN-030 | SHOULD | DES-005 §4.5 | L1 | `unit/core/test_run::test_cost_estimation` | Planned |
| FR-RUN-001 | MUST | DES-005 §2.1 | L2 | `integration/test_run::test_preflight_passes` | Planned |
| FR-RUN-001 | MUST | DES-005 §2.1 | L2 | `integration/test_run::test_preflight_crash_aborts` | Planned |
| FR-RUN-001 | MUST | DES-005 §2.1 | L2 | `integration/test_run::test_preflight_timeout_aborts` | Planned |
| FR-RUN-001 | MUST | DES-005 §2.1 | L2 | `integration/test_run::test_preflight_zero_score_warns` | Planned |
| FR-RUN-023 | MUST | DES-005 §2.1 | L2 | `integration/test_run::test_dry_run_skips_preflight` | Planned |
| FR-RUN-008 | MUST | DES-005 §post-run | L2 | `integration/test_run::test_collect_programs_from_best_dir` | Planned |
| FR-RUN-006 | MUST | DES-005 §config | L2-OE | `integration/test_run_oe::test_build_config_local_llm_api_key` | Planned |
| FR-RUN-006 | MUST | DES-005 §config | L2-OE | `integration/test_run_oe::test_build_config_cascade_evaluation_default` | Planned |
| FR-RUN-006 | MUST | DES-005 §config | L2-OE | `integration/test_run_oe::test_build_config_cascade_evaluation_override` | Planned |
| FR-RUN-008 | MUST | DES-005 §post-run | L2-OE | `integration/test_run_oe::test_best_score_from_program` | Planned |
| FR-RUN-031 | MUST | DES-005 §post-run | L2 | `integration/test_run::test_run_postprocessing_failure_status` | Planned |
| FR-RUN-032 | MUST | DES-005 §post-run | L2 | `integration/test_run::test_run_postprocessing_failure_status` | Planned |
| FR-RUN-033 | MUST | DES-005 §extract | L2 | `integration/test_solution::test_extract_accepts_completed_with_errors` | Planned |
| FR-RUN-034 | MUST | DES-005 §resume | L2 | (covered by resume tests) | Planned |

---

## 7. Evaluation — `revolver eval`

Design: [DES-006](../architecture/design/DES-006-eval-loop.md), [DES-001 §eval_metadata/eval_instances](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-EVL-001 | MUST | DES-006 §loop | L1 | `unit/core/test_eval::test_iterates_all_instances` | Planned |
| FR-EVL-002 | MUST | DES-006 §env, ADR-006 | L1 | `unit/core/test_eval::test_sets_instance_env_vars` | Planned |
| FR-EVL-003 | MUST | DES-006 §eval | L1 | `unit/core/test_eval::test_uses_version_evaluator` | Planned |
| FR-EVL-004 | MUST | DES-006 §collect | L1 | `unit/core/test_eval::test_collects_metrics_and_time` | Planned |
| FR-EVL-005 | MUST | DES-006 §store, DES-001 | L2 | `integration/test_eval::test_stores_per_instance_results` | Planned |
| FR-EVL-006 | MUST | DES-006 §aggregate | L1 | `unit/core/test_eval::test_aggregates_computed_at_read_time` | Planned |
| FR-EVL-007 | MUST | DES-006 §pre | L1 | `unit/core/test_eval::test_integrity_check` | Planned |
| FR-EVL-008 | MUST | DES-006 §pre | L1 | `unit/core/test_eval::test_warns_incompatible_version` | Planned |
| FR-EVL-009 | MUST | DES-006 §pre | L1 | `unit/core/test_eval::test_warns_non_eval_split` | Planned |
| FR-EVL-010 | MUST | DES-006 §error | L1 | `unit/core/test_eval::test_handles_per_instance_exception` | Planned |
| FR-EVL-011 | MUST | DES-006 §error | L1 | `unit/core/test_eval::test_records_unsolved_instances` | Planned |
| FR-EVL-012 | SHOULD | DES-006 §progress | L2 | `integration/test_eval::test_progress_bar` | Planned |
| FR-EVL-013 | SHOULD | DES-006 §timeout | L1 | `unit/core/test_eval::test_per_instance_timeout` | Planned |
| FR-EVL-014 | MAY | DES-006 | — | — | Deferred (v2) |
| FR-EVL-015 | MUST | DES-006 §results | L2 | `integration/test_eval::test_results_command` | Planned |
| FR-EVL-016 | MUST | DES-006 §results | L2 | `integration/test_eval::test_results_per_instance` | Planned |
| FR-EVL-017 | MUST | DES-006 §results | L2 | `integration/test_eval::test_results_per_instance_json` | Planned |
| FR-EVL-018 | MUST | DES-006 §re-eval | L2 | `integration/test_eval::test_re_eval_requires_confirmation` | Planned |
| FR-EVL-019 | MUST | DES-006 §legacy | L1 | `unit/core/test_eval::test_legacy_evaluator_global_call` | Planned |
| FR-EVL-020 | MUST | DES-006 §results | L2 | `integration/test_eval::test_results_shows_user_aggregates` | Planned |
| FR-EVL-001 | MUST | DES-006 §loop | L2 | `integration/test_eval::test_evaluate_instance_mode` | Planned |
| FR-EVL-019 | MUST | DES-006 §legacy | L2 | `integration/test_eval::test_legacy_evaluate_mode` | Planned |
| FR-EVL-001 | MUST | DES-006 §loop | L2 | `integration/test_eval::test_dual_function_warning` | Planned |

---

## 8. Solution — `revolver solution`

Design: [DES-005 §post-run](../architecture/design/DES-005-run-orchestration.md), [DES-001 §solutions](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-SOL-001 | MUST | DES-001 | L2 | `integration/test_solution::test_list_shows_all_solutions` | Planned |
| FR-SOL-002 | MUST | DES-001 | L2 | `integration/test_solution::test_list_filters` | Planned |
| FR-SOL-003 | MUST | DES-001, DES-005 | L2 | `integration/test_solution::test_info_full_lineage` | Planned |
| FR-SOL-004 | MUST | DES-005 §storage | L1 | `unit/core/test_solution::test_program_path_derived` | Planned |
| FR-SOL-005 | MUST | DES-001, DES-006 | L2 | `integration/test_solution::test_info_shows_eval_results` | Planned |
| FR-SOL-006 | MUST | DES-001 | L2 | `integration/test_solution::test_alias_set` | Planned |
| FR-SOL-007 | MUST | DES-001 | L2 | `integration/test_solution::test_alias_unique` | Planned |
| FR-SOL-008 | MUST | DES-001 | L2 | `integration/test_solution::test_reference_by_alias` | Planned |
| FR-SOL-009 | SHOULD | DES-005 | L2 | `integration/test_solution::test_info_shows_sibling_solutions` | Planned |
| FR-SOL-010 | MUST | DES-001 | L1 | `unit/core/test_solution::test_lineage_via_run_id` | Planned |
| FR-SOL-011 | MUST | DES-005 §extract | L2 | `integration/test_solution::test_extract_promotes_program` | Planned |
| FR-SOL-012 | MUST | DES-005 §extract | L2 | `integration/test_solution::test_extract_duplicate_blocked` | Planned |
| FR-SOL-013 | MUST | DES-001 | L1 | `unit/core/test_solution::test_extract_generates_id` | Planned |
| FR-SOL-014 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_by_alias` | Planned |
| FR-SOL-015 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_by_id_force` | Planned |
| FR-SOL-016 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_cascades_eval` | Planned |
| FR-SOL-017 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_json_requires_force` | Planned |

---

## 9. Benchmark — `revolver benchmark`

Design: [DES-007](../architecture/design/DES-007-benchmark-design.md), [DES-001 §benchmarks](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-BEN-001 | MUST | DES-007 §input | L2 | `integration/test_benchmark::test_accepts_multiple_solutions` | Planned |
| FR-BEN-002 | MUST | DES-007 §reuse | L1 | `unit/core/test_benchmark::test_reuses_existing_eval` | Planned |
| FR-BEN-003 | MUST | DES-007 §eval | L2 | `integration/test_benchmark::test_runs_missing_evals` | Planned |
| FR-BEN-004 | MUST | DES-007 §compare | L2 | `integration/test_benchmark::test_comparative_table` | Planned |
| FR-BEN-005 | MUST | DES-007 §lineage | L1 | `unit/core/test_benchmark::test_includes_lineage` | Planned |
| FR-BEN-006 | MUST | DES-007, DES-001 | L2 | `integration/test_benchmark::test_metadata_stored_in_db` | Planned |
| FR-BEN-007 | MUST | DES-007 §export | L2 | `integration/test_benchmark::test_export_csv` | Planned |
| FR-BEN-008 | MUST | DES-007 §export | L2 | `integration/test_benchmark::test_export_json` | Planned |
| FR-BEN-009 | MUST | DES-007 §results | L1 | `unit/core/test_benchmark::test_includes_eval_time_solved` | Planned |
| FR-BEN-010 | SHOULD | DES-007 §sort | L1 | `unit/core/test_benchmark::test_sort_by_metric` | Planned |
| FR-BEN-011 | SHOULD | DES-007 §lineage | L1 | `unit/core/test_benchmark::test_includes_gen_time` | Planned |
| FR-BEN-012 | MUST | DES-007 | L2 | `integration/test_benchmark::test_list_benchmarks` | Planned |
| FR-BEN-013 | MUST | DES-007 §export, NFR-052 | L1 | `unit/core/test_benchmark::test_no_secrets_in_export` | Planned |
| FR-BEN-014 | MUST | DES-007 §results | L2 | `integration/test_benchmark::test_results_per_instance` | Planned |
| FR-BEN-015 | SHOULD | DES-007 §results | L1 | `unit/core/test_benchmark::test_best_per_instance` | Planned |
| FR-BEN-016 | MUST | DES-007 §export | L2 | `integration/test_benchmark::test_export_per_instance` | Planned |
| FR-BEN-017 | MUST | DES-007 §results, DES-001 | L1 | `unit/core/test_benchmark::test_includes_run_id` | Planned |

---

## 10. Setup & Doctor — `revolver doctor`, `revolver setup`

Design: [Architecture §4.2](../architecture/architecture.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-SET-001 | MUST | Arch §4.2 | L2 | `integration/test_doctor::test_checks_python_packages` | Planned |
| FR-SET-002 | MUST | Arch §4.2 | L2 | `integration/test_doctor::test_checks_openevolve` | Planned |
| FR-SET-003 | MUST | Arch §4.2, ADR-001 | L2 | `integration/test_doctor::test_checks_ollama` | Planned |
| FR-SET-004 | MUST | Arch §4.2 | L2 | `integration/test_doctor::test_checks_nvidia_smi` | Planned |
| FR-SET-005 | MUST | Arch §4.2 | L2 | `integration/test_doctor::test_ok_warn_fail_status` | Planned |
| FR-SET-006 | MUST | Arch §4.2 | L1 | `unit/core/test_doctor::test_fixable_vs_system` | Planned |
| FR-SET-007 | MUST | Arch §4.2 | L2 | `integration/test_setup::test_installs_missing_pip` | Planned |
| FR-SET-008 | MUST | Arch §4.2 | L2 | `integration/test_setup::test_asks_confirmation` | Planned |
| FR-SET-009 | MUST | Arch §4.2 | L1 | `unit/core/test_setup::test_never_installs_system_pkg` | Planned |
| FR-SET-010 | MUST | Arch §4.2 | L2 | `integration/test_setup::test_instructions_for_non_fixable` | Planned |
| FR-SET-011 | SHOULD | Arch §4.2 | L2 | `integration/test_setup::test_dry_run` | Planned |
| FR-SET-012 | SHOULD | Arch §4.2 | L2 | `integration/test_doctor::test_works_outside_project` | Planned |
| FR-SET-013 | SHOULD | Arch §4.2 | L2 | `integration/test_doctor::test_reports_versions` | Planned |
| FR-SET-014 | SHOULD | Arch §4.2 | L1 | `unit/core/test_setup::test_detects_conda` | Planned |
| FR-SET-015 | SHOULD | Arch §4.2 | L2 | `integration/test_setup::test_ollama_via_conda` | Planned |
| FR-SET-016 | SHOULD | Arch §4.2 | L1 | `unit/core/test_setup::test_reports_install_method` | Planned |
| FR-SET-017 | SHOULD | Arch §4.2 | L2 | `integration/test_setup::test_manual_instructions_no_conda` | Planned |

---

## 11. Non-Functional Requirements (testable)

| NFR ID | Pri | Category | Level | Test ID | Status |
|---|---|---|---|---|---|
| NFR-001 | MUST | CLI | L2 | `integration/test_cross_cutting::test_exit_code_0_on_success` | Planned |
| NFR-002 | MUST | CLI | L2 | `integration/test_cross_cutting::test_help_on_all_commands` | Planned |
| NFR-003 | MUST | CLI | L2 | `integration/test_cross_cutting::test_json_flag_all_commands` | Planned |
| NFR-004 | MUST | CLI | L2 | `integration/test_cross_cutting::test_errors_on_stderr` | Planned |
| NFR-005 | SHOULD | CLI | L2 | `integration/test_cross_cutting::test_progress_on_stderr` | Planned |
| NFR-006 | SHOULD | CLI | L2 | `integration/test_cross_cutting::test_confirmation_summary` | Planned |
| NFR-007 | MUST | CLI | L2 | `integration/test_cross_cutting::test_single_binary_subcommands` | Planned |
| NFR-010 | MUST | Storage | L2 | `integration/test_project::test_data_in_revolver_dir` | Planned |
| NFR-011 | MUST | Storage | L2 | `integration/test_llm::test_global_data_in_home` | Planned |
| NFR-013 | MUST | Storage | L2 | `integration/test_project::test_sqlite_db_created` | Planned |
| NFR-014 | MUST | Storage | L1 | `unit/infra/test_hashing::test_sha256_used` | Planned |
| NFR-015 | MUST | Storage | L2 | `integration/test_problem::test_snapshot_immutable` | Planned |
| NFR-016 | SHOULD | Storage | L1 | `unit/infra/test_db::test_wal_mode_enabled` | Planned |
| NFR-017 | MUST | Storage | L1 | `unit/core/test_dataset::test_hash_verified_at_usage` | Planned |
| NFR-020 | MUST | Reprod. | L2 | `integration/test_run::test_full_lineage_recorded` | Planned |
| NFR-021 | MUST | Reprod. | L1 | `unit/core/test_llm::test_model_pinned_by_digest` | Planned |
| NFR-022 | MUST | Reprod. | L1 | `unit/infra/test_hashing::test_per_instance_hashes` | Planned |
| NFR-023 | SHOULD | Reprod. | L2 | `integration/test_run::test_config_stored_verbatim` | Planned |
| NFR-030 | MUST | Perf. | — | Manual validation (not CI-gated) | — |
| NFR-031 | SHOULD | Perf. | — | Manual validation (not CI-gated) | — |
| NFR-032 | SHOULD | Perf. | — | Manual validation (not CI-gated) | — |
| NFR-050 | MUST | Security | L1 | `unit/core/test_llm::test_no_secrets_in_config` | Planned |
| NFR-051 | MUST | Security | L2 | `integration/test_project::test_dir_permissions_700` | Planned |
| NFR-052 | MUST | Security | L1 | `unit/core/test_benchmark::test_no_secrets_in_export` | Planned |
| NFR-060 | MUST | Deploy | — | Verified by packaging (pyproject.toml) | — |
| NFR-061 | MUST | Deploy | — | Verified by packaging (pyproject.toml) | — |

### NFRs with indirect coverage

The following MUST NFRs are not tested independently — they are satisfied by FR-level tests or by infrastructure constraints. Listed here for traceability completeness.

| NFR ID | Pri | Category | Covered by | Rationale |
|---|---|---|---|---|
| NFR-008 | SHOULD | CLI | — | Tab completion: not automatically testable, verified manually |
| NFR-012 | MUST | Storage | FR-PRB-009, FR-PRJ-002 | YAML manifests tested via problem version and project init |
| NFR-040 | MUST | Compat. | CI pipeline | Linux enforced by CI runner OS; WSL2 verified by dev environment |
| NFR-041 | MUST | Compat. | FR-SET-004 | GPU detection tested via `doctor` checks |
| NFR-042 | MUST | Compat. | FR-SET-003 | Ollama detection tested via `doctor` checks |
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
| **Scenario 2 — Remote-Only (TBD)** | FR-LLM-001/015/017/018, FR-RUN-015/028..030, NFR-043 | Planned |

---

## 13. Coverage Summary

| Spec File | Total FRs | MUST | SHOULD | MAY | L1 Tests | L2 Tests | L3 (E2E) | Untested |
|---|---|---|---|---|---|---|---|---|
| spec-project | 8 | 6 | 2 | 0 | 0 | 8 | via Sc.1 | 0 |
| spec-llm | 18 | 11 | 6 | 0 | 8 | 10 | via Sc.1 | 0 |
| spec-problem | 15 | 10 | 4 | 1 | 4 | 10 | via Sc.1 | 0 |
| spec-dataset | 16 | 12 | 2 | 0 | 6 | 10 | via Sc.1 | 0 |
| spec-run | 34 | 25 | 9 | 0 | 16 | 18 | via Sc.1 | 0 |
| spec-eval | 20 | 15 | 3 | 1 | 10 | 9 | via Sc.1 | 1 (FR-EVL-014, deferred) |
| spec-solution | 17 | 16 | 1 | 0 | 3 | 14 | via Sc.1 | 0 |
| spec-benchmark | 17 | 12 | 4 | 0 | 7 | 10 | via Sc.1 | 0 |
| spec-setup | 17 | 10 | 7 | 0 | 4 | 13 | — | 0 |
| NFR (direct) | 27 | 19 | 8 | 0 | 8 | 11 | — | 3 (perf, manual) |
| NFR (indirect) | 13 | 8 | 5 | 0 | — | — | — | 0 (covered by FR tests) |
| **Total** | **202** | **141** | **49** | **2** | **66** | **113** | **2 scenarios** | **4** |

Notes:
- 55 FR-SOL, FR-RUN, FR-EVL requirements share test coverage across unit and integration tests. The total counts distinct test assignments (some FRs have both L1 and L2 tests).
- 13 NFRs are covered indirectly by FR-level tests (see §11 indirect coverage table). They are not double-counted in L1/L2 totals.
- 4 untested items: 3 performance NFRs (manual validation) + 1 deferred MAY (FR-EVL-014).
