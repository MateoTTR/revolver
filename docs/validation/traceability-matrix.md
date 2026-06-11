# Revolver — Traceability Matrix

**Version**: 0.4 — Backend abstraction rows (ADR-007: FR-RUN-047/048, NFR-024)
**Date**: 2026-06-11
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
| **Test ID** | Test name — references actual test functions in `tests/` |
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
| FR-LLM-001 | MUST | DES-002 §add | L2 | `integration/test_llm::test_llm_add_remote_with_pricing` | Implemented |
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
| FR-LLM-018 | SHOULD | DES-002, DES-005 §4.5 | L2 | `integration/test_llm::test_llm_add_remote_with_pricing` | Implemented |
| FR-LLM-019 | SHOULD | DES-002, DES-005 | L2 | `integration/test_llm::test_llm_add_temperature` | Implemented |
| FR-LLM-020 | MUST | DES-002 §ensemble | L2 | `integration/test_llm_ensemble::test_ensemble_create` | Implemented |
| FR-LLM-021 | MUST | DES-002 §ensemble | L2 | `integration/test_llm_ensemble::test_ensemble_add_member` | Implemented |
| FR-LLM-022 | MUST | DES-002 §ensemble | L2 | `integration/test_llm_ensemble::test_ensemble_list` | Implemented |
| FR-LLM-023 | MUST | DES-002 §ensemble | L2 | `integration/test_llm_ensemble::test_ensemble_info` | Implemented |
| FR-LLM-024 | MUST | DES-002 §ensemble | L2 | `integration/test_llm_ensemble::test_ensemble_remove_cascade` | Implemented |
| FR-LLM-025 | SHOULD | DES-002 §ensemble | L2 | `integration/test_llm_ensemble::test_weight_sum_warning` | Implemented |

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
| FR-RUN-030 | SHOULD | DES-005 §4.5 | L1 | `unit/infra/test_token_proxy::test_with_pricing` | Implemented |
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
| FR-RUN-031 | MUST | DES-005 | L2 | `integration/test_run::test_run_oe_failure_marks_failed` | Implemented |
| FR-RUN-043 | MUST | DES-005 §post-run | L1 | `test_core_run::test_launch_run_post_processing_failure_sets_completed_with_errors` | Implemented |
| FR-RUN-032 | MUST | DES-005 §post-run | L1 | `test_core_run::test_handle_post_run_failure_sets_completed_with_errors` | Implemented |
| FR-RUN-033 | MUST | DES-005 §extract | L2 | `integration/test_solution::test_extract_accepts_completed_with_errors` | Implemented |
| FR-RUN-034 | MUST | DES-005 §resume | L1, L2 | `test_core_run::test_resume_run_creates_new_run`, `integration/test_run::test_run_resume` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_delete_run_returns_true` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_delete_run_returns_false_not_found` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_delete_run_cascades_solutions` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_run_delete_running_run_raises` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_run_delete_by_id` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_run_delete_force_skips_prompt` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_run_delete_not_found` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_run_delete_json_mode_requires_force` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_run_delete_json_mode_with_force` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_run_delete_missing_directory` | Implemented |
| FR-RUN-035 | MUST | DES-005 | L1 | `test_run_delete::test_run_delete_user_cancels` | Implemented |
| FR-RUN-040 | SHOULD | DES-005 | L2 | `integration/test_run::test_run_temperature_flag` | Implemented |
| FR-RUN-041 | SHOULD | DES-005 | L2 | `integration/test_run::test_run_parallel_flag` | Implemented |
| FR-RUN-044 | MUST | DES-005 §4.3.1, DES-001 | L1 | `unit/core/test_run::test_llm_type_stored` | Implemented |
| FR-RUN-045 | MUST | DES-005 §4.3.1, DES-001 | L1 | `unit/core/test_run::test_llm_snapshot_stored` | Implemented |
| FR-RUN-046 | MUST | DES-005 §4.3 | L2 | `integration/test_run::test_run_with_ensemble` | Implemented |
| FR-RUN-047 | MUST | ADR-007, DES-005 §14.1, DES-001 §3.5 | L2 | `integration/test_run::test_run_backend_flag_and_default` (S13) | Planned |
| FR-RUN-047 | MUST | ADR-007, DES-005 §14.1 | L2 | `integration/test_run::test_resume_inherits_parent_backend` (S13) | Planned |
| FR-RUN-048 | MUST | ADR-007, DES-005 §14.1 | L2 | `integration/test_run_shinka::test_unsupported_option_warns` (S14) | Planned |

---

## 7. Evaluation — `revolver eval`

Design: [DES-006](../architecture/design/DES-006-eval-loop.md), [DES-001 §eval_metadata/eval_instances](../architecture/design/DES-001-sqlite-data-model.md)

| FR ID | Pri | DES Ref | Level | Test ID | Status |
|---|---|---|---|---|---|
| FR-EVL-001 | MUST | DES-006 §loop | L1 | `unit/core/test_eval::test_iterates_all_instances` | Planned |
| FR-EVL-002 | MUST | DES-006 §env, ADR-006 | L1 | `test_evaluator_runner::test_env_vars_set` | Implemented |
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
| FR-EVL-013 | SHOULD | DES-006 §timeout | L1 | `test_evaluator_runner::test_timeout` | Implemented |
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
| FR-SOL-011 | MUST | DES-005 §extract | L2 | `integration/test_solution::test_extract_promotes_program` | Implemented |
| FR-SOL-012 | MUST | DES-005 §extract | L2 | `integration/test_solution::test_extract_duplicate_blocked` | Implemented |
| FR-SOL-013 | MUST | DES-001 | L1 | `test_core_run::test_generate_solution_id_format` | Implemented |
| FR-SOL-014 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_by_alias` | Implemented |
| FR-SOL-015 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_by_id_force` | Implemented |
| FR-SOL-016 | MUST | DES-005 | L1 | `unit/test_db_solution::test_delete_solution_cascades_eval` | Implemented |
| FR-SOL-017 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_delete_json_mode_requires_force` | Implemented |
| FR-SOL-018 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_show_stdout` | Implemented |
| FR-SOL-019 | MUST | DES-005 | L2 | `integration/test_solution::test_solution_export_default` | Implemented |
| FR-SOL-020 | SHOULD | DES-005 | L2 | `integration/test_solution::test_solution_diff_different` | Implemented |

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
| NFR-013 | MUST | Storage | L2 | `test_project_integration::test_init_creates_structure` (checks revolver.db) | Implemented |
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

| Spec File | Total Reqs | MUST | SHOULD | MAY | L1 Tests | L2 Tests | L3 (E2E) | Untested |
|---|---|---|---|---|---|---|---|---|
| spec-project | 8 | 6 | 2 | 0 | 0 | 8 | via Sc.1 | 0 |
| spec-llm | 25 | 16 | 9 | 0 | 4 | 15 | via Sc.1 | 6 |
| spec-problem | 15 | 10 | 4 | 1 | 1 | 10 | via Sc.1 | 3 |
| spec-dataset | 16 | 12 | 2 | 0 | 2 | 14 | via Sc.1 | 0 |
| spec-run | 54 | 41 | 11 | 0 | 30 | 16 | via Sc.1 | 6 |
| spec-eval | 23 | 17 | 3 | 1 | 7 | 9 | via Sc.1 | 5 (incl. 1 deferred) |
| spec-solution | 20 | 18 | 2 | 0 | 2 | 16 | via Sc.1 | 2 |
| spec-benchmark | 20 | 15 | 4 | 0 | 7 | 10 | via Sc.1 | 1 |
| spec-setup | 17 | 10 | 7 | 0 | 4 | 13 | — | 0 |
| NFR (direct) | 28 | 19 | 9 | 0 | 6 | 12 | — | 5 (3 perf manual + 2 planned) |
| NFR (indirect) | 13 | 8 | 5 | 0 | — | — | — | 0 (covered by FR tests) |
| **Total** | **239** | **172** | **56** | **2** | **73** | **133** | **3 scenarios (1 planned)** | **28** |

Notes:
- Run delete (FR-RUN-035) adds 11 new test entries covering DB layer, core logic, CLI, and edge cases.
- Benchmark delete (FR-BEN-018) adds 3 new test entries covering confirmation, nonexistent, and force delete.
- Many FR-level tests cover multiple requirements. The total counts distinct test assignments (some FRs have both L1 and L2 tests).
- 13 NFRs are covered indirectly by FR-level tests (see §11 indirect coverage table). They are not double-counted in L1/L2 totals.
- 28 untested items: 3 performance NFRs (manual validation) + 1 deferred MAY (FR-EVL-014) + 24 still Planned.
- Compared to v0.1, the majority of entries have been updated from Planned to Implemented based on verification of existing test functions in the `tests/` directory.
