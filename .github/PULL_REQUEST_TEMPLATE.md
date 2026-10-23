Closes #N

<!-- Keep `Closes #N` as the first line (AGENTS.md, "Pull request workflow").
     Open the pull request as a DRAFT; mark it ready only when the latest review
     carries 0 CRITICAL (docs/process/code-review.md, "Exit rule").
     Delete these comments as you fill the sections. -->

## Summary

<!-- What changes and why, in a few lines. Link the design issue when the change
     went through one (RFC-lite). -->

## Spec impact

<!-- "None" — or what changed, before or with the code:
     - docs/specs/spec-<group>.md: Commands-table row / FR-<GROUP>-NNN / Error Cases row
     - DES-NNN § …, header version bumped
     - ADR-NNN in-place dated amendment, or a new ADR, indexed in architecture.md § 9 and AGENTS.md
     - docs/validation/: val-integration-tests.md and traceability-matrix.md rows (test ids; Planned → Implemented) -->

## Tests

<!-- Test ids added or changed (`<path-under-tests/>::<test_name>`), with their markers. -->

- Engine-specific tests (`-m openevolve`, `-m shinkaevolve`), which CI does not run: **not applicable** / **run in**: <engine package and version, Python version, result>
- Pre-existing tests modified: **none** / <list — mechanical changes only>

## Definition of Done

Mirror of [docs/process/definition-of-done.md § 1](https://github.com/MateoTTR/revolver/blob/develop/docs/process/definition-of-done.md). Tick what is done; strike (`~~…~~`) what does not apply and say why.

### Gates (local, Python 3.12 — and 3.14 when available)

- [ ] `ruff check src/ tests/`
- [ ] `ruff format --check src/ tests/`
- [ ] `mypy`
- [ ] `pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"`
- [ ] L1 + L2 tests for every new public function or command path, in the right directory with the right marker; engine tests gated by `pytest.importorskip` plus the engine marker
- [ ] DB schema change: sequential migration `vN`, its DES-001 § 5 narrative and `tests/unit/test_db_migration_vN.py` — or no schema change

### Documentation

- [ ] Specification surface (Commands table, FR, Error Cases) and DES / ADR updated — see **Spec impact**
- [ ] Validation rows (`val-integration-tests.md`, `traceability-matrix.md`) name the real test ids
- [ ] `README.md` updated when user-facing (features, install, behavior)
- [ ] Every fenced `revolver …` example resolves (`pytest tests/unit/test_doc_command_lint.py`)
- [ ] Changed guides and `docs/specs/user-story-e2e.md` carry a current `verified-against: vX.Y.Z` stamp (`pytest tests/unit/test_doc_freshness.py`)
- [ ] One line under `[Unreleased]` in `CHANGELOG.md`, flagged **Behavior change** when a default path changes

### Review and rules

- [ ] Self-review against `docs/process/code-review.md` done
- [ ] Code respects `cli/` → `core/` → `infra/`, the `RevolverError` hierarchy and exit codes 0–4, parameterized SQL, secrets as environment-variable names only
- [ ] [Public-file rule](https://github.com/MateoTTR/revolver/blob/develop/docs/process/README.md#public-file-rule) respected in the diff and in this description
- [ ] Latest review: 0 CRITICAL; WARNINGs fixed, or carried over here: <list, or "none">

<details>
<summary><strong>New evolution backend</strong> — additional checklist (ADR-007; Definition of Done § 2)</summary>

- [ ] **Registry and protocol** — `src/revolver/infra/backends/<name>.py` implements every `EvolutionBackend` member and the class attributes `name`, `default_output_subdir`, `wrapper_filename`; `ChildProcessReaperMixin` inherited, or the reason documented; added to `AVAILABLE_BACKENDS` and `get_backend()`, exported from `backends/__init__.py`; `tests/unit/infra/test_backends.py` conformance tests updated
- [ ] **Capabilities** — honest values on every `BackendCapabilities` axis; DES-005 § 4.6 column; ADR-007 D1 wording amended
- [ ] **Config template and validation** — `config_template()` parses and passes `validate_config()`; `project init --backend <name>` and `problem version create --backend <name>` work; graceful degradation without the engine; FR-PRJ-005 and the `spec-problem.md` option row cite the name
- [ ] **Doctor and setup** — `doctor` reports through `is_available()` (absent optional backend = INFO with an install hint, FR-SET-002); `_BACKEND_CHECK_NAMES` / `_BACKEND_DIST_NAMES`; `setup` lists the extra; L1 + L2 doctor tests; `user-story-e2e.md` doctor transcript
- [ ] **DB and traceability** — `run info` / `run list` / `--dry-run` / the manifest show the backend (FR-RUN-047); DES-001 § 3.1 / § 3.5 value lists and `spec-run.md` § 5 updated; no migration unless a constraint is added
- [ ] **Token accounting (D2)** — `wants_http_proxy()` is true, or false with `collect_token_usage()` reading engine-native counts; token-primary, no USD; an L2 test asserts stored tokens
- [ ] **Reproducibility (D3)** — `global_seed` truthful; the CLI warns when a seed is requested and unsupported (NFR-024 row)
- [ ] **Neutral config (D4)** — `build_config()` maps the neutral levers or warns per capabilities; `resolved_config()` puts engine-only keys in `backend_extras`; unknown `--config-override` keys warn; `evaluation.on_timeout` / `timeout_score` honored (FR-RUN-054)
- [ ] **LLM registry projection (D5)** — `LLMEntry` / `EnsembleEntry` projected into the engine's model syntax; only environment-variable **names** exported (NFR-050); ensembles accepted or rejected per `selection_strategies`; `spec-llm.md` projection note extended
- [ ] **Dependency extra (D6)** — `[project.optional-dependencies] <name> = ["<package>>=x,<y"]` with an upper bound, never in `dev`; import probe with an install hint; exit code 3 when selected but absent; README install block and NFR-061 example
- [ ] **CLI** — `run --backend <name>` with the explicit > version-stored > default resolution and the mismatch warning (FR-RUN-047, FR-PRB-016); `solution extract --rank` / `--program-id` gated on `top_n_extraction` (FR-SOL-021); help wording lists the backend
- [ ] **Wrapper evaluator and L2 contract track** — `generate_wrapper()` bridges `evaluate_instance()`, emits `instances_valid` / `instances_total` and a distinct timeout branch (FR-RUN-053); contract tests with module-level `pytest.importorskip`, `@pytest.mark.integration` and `@pytest.mark.<name>` (marker registered); `no_<name>` fixture; fixtures under `tests/fixtures/`; the L1 suite runs without the engine; an L3 scenario in `tests/e2e/`
- [ ] **Specs, DES, ADR** — FR-RUN-047/048, FR-SET-002, FR-PRJ-005, FR-PRB-016, FR-SOL-021, NFR-024/061 widened; DES-005 § 4.1–§ 4.6 and § 14; DES-006 § 1.3 row; `architecture.md` § 1, § 3, § 8; ADR-007 amended (same paradigm) **or** a new ADR (different paradigm)
- [ ] **Validation documents** — `validation.md` § 3 row and backend-matrix paragraph; `val-integration-tests.md` § 1, § 2, § 4; a `val-e2e-tests.md` scenario; traceability rows; the § 13 summary
- [ ] **Guides and README** — a guide stamped `verified-against`; the tuning guide's per-backend knob section; README features, extras, narrative
- [ ] **Process evidence** — the issue follows the new-backend form; **Tests** above states how the engine-marked tests were run against the real engine and its version

</details>

## Status

<!-- Update at the end of each working session (AGENTS.md, "Pull request workflow", step 3). -->

- **Done**:
- **Next**:
- **Blocked**:
