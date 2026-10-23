# Definition of Done

Two checklists: one for any feature pull request, one for the addition of an
evolution backend (a feature pull request plus the backend-specific items).
Each item names the repository file or convention that makes it a rule.
`CONTRIBUTING.md` and the pull-request template, where present, mirror these
lists.

## 1. Feature pull request

1. **Issue and traceability** — a GitHub issue exists with scope, acceptance criteria and test scenarios; the pull-request description starts with `Closes #N` ([`AGENTS.md`](../../AGENTS.md), "Pull request workflow").
2. **Specification surface updated before or with the code** — a new or changed CLI option has its Commands-table row, a functional requirement (next free id; `MUST` / `SHOULD` / `MAY`) and an Error Cases row in `docs/specs/spec-<group>.md` (`specifications.md` §2.1–2.3); affected DES sections are amended and the DES header version bumped; a changed architectural decision is an in-place dated amendment of its ADR — or a new ADR for a new decision — indexed in `architecture.md` §9 and `AGENTS.md` ([spec-review.md](spec-review.md)).
3. **Validation documents** — `docs/validation/val-integration-tests.md` and `traceability-matrix.md` rows name the real test ids (`validation.md` §8.1), status `Planned` while in flight and `Implemented` once merged; `validation.md` / `val-e2e-tests.md` updated when levels or CI change ([validation-review.md](validation-review.md)).
4. **Code** respects the layer rule `cli/` → `core/` → `infra/` (`architecture.md` §2), the `RevolverError` hierarchy and exit codes 0–4 (`specifications.md` §4.2), strict typing and docstrings, parameterized SQL, secrets as environment-variable names only (NFR-050 / NFR-052) — the [code review](code-review.md) items.
5. **Tests** — L1 + L2 tests for every new public function or command path, in the right directory with the right marker (`validation.md` §5.3 and §8.1; `val-integration-tests.md` §4); engine tests gated by `pytest.importorskip` plus the engine marker; a DB schema change ships a sequential migration `vN`, its DES-001 §5 narrative and `tests/unit/test_db_migration_vN.py`.
6. **Local gates green** — `ruff check src/ tests/`, `ruff format --check src/ tests/`, `mypy`, `pytest --cov=revolver --cov-fail-under=80 -m "unit or integration"` (the CI jobs of `.github/workflows/ci.yml`, on Python 3.12 and 3.14); no pre-existing test modified except mechanical changes listed in the pull-request description.
7. **Documentation** — `README.md` features / install / behavior changes when user-facing; every fenced `revolver …` example resolves (doc command-lint); new or changed guides and `docs/specs/user-story-e2e.md` carry a current `verified-against: vX.Y.Z` stamp (`tests/unit/test_doc_freshness.py`); one line under `[Unreleased]` in `CHANGELOG.md`, flagged **Behavior change** when a default path changes.
8. **Review and merge** — opened as a draft; self-review and reviewer pass per [code-review.md](code-review.md); **0 CRITICAL**, WARNINGs fixed or carried over; marked ready; the four required checks green; the maintainer merges.
9. **Public-file rule** respected in every committed file and in the pull-request text ([docs/process/README.md § Public-file rule](README.md#public-file-rule)).

## 2. New evolution backend

Derived from ADR-007 (D1–D6 and amendments A1–A5) and from the files the
OpenEvolve and ShinkaEvolve adapters touch. All of section 1 applies; in
addition:

| Area | Done when | Where |
|---|---|---|
| **Registry and protocol** | `src/revolver/infra/backends/<name>.py` implements every member of the `EvolutionBackend` protocol (`capabilities`, `is_available`, `config_template`, `validate_config`, `build_config`, `resolved_config`, `generate_wrapper`, `validate_seed_metrics`, `launch`, `resume_precheck`, `resume`, `recover_best_from_checkpoint`, `extract_ranked_program`, `read_progress`, `parse_population`, `count_valid`, `count_total`, `count_evolved_children`, `wants_http_proxy`, `collect_token_usage`) and the class attributes `name`, `default_output_subdir`, `wrapper_filename`; inherits `ChildProcessReaperMixin` or documents why not; is added to `AVAILABLE_BACKENDS` **and** to the `get_backend()` registry; is exported from `backends/__init__.py`; the conformance tests in `tests/unit/infra/test_backends.py` (the `AVAILABLE_BACKENDS` tuple, the protocol `isinstance` loop) are updated | `infra/backends/base.py`; DES-005 §4.1; ADR-007 D1 |
| **Capabilities** | `capabilities()` returns honest values for every axis of `BackendCapabilities` (`global_seed`, `map_elites_cells`, `native_cost_tracking`, `multi_language`, `ensemble_model`, `top_n_extraction`, `selection_strategies`, `per_member_reasoning_effort`); DES-005 §4.6 gains a column; the ADR-007 D1 wording ("two implementations") is amended | `infra/backends/base.py::BackendCapabilities`; DES-005 §4.6; ADR-007 A4 |
| **Config template and validation** | `config_template()` parses as YAML and passes `validate_config()`; `project init --backend <name>` and `problem version create --backend <name>` work (the help text lists `AVAILABLE_BACKENDS`); `validate_config()` degrades gracefully when the engine is absent; FR-PRJ-005 and the `spec-problem.md` option row cite the new name | `cli/project.py`, `cli/problem.py`; `spec-project.md`, `spec-problem.md` |
| **Doctor and setup** | `doctor` reports the backend through `is_available()`; an absent optional backend is INFO with an install hint (FR-SET-002); entries in `_BACKEND_CHECK_NAMES` / `_BACKEND_DIST_NAMES`; `setup` lists the extra; L1 `tests/unit/test_doctor.py` and L2 `integration/test_doctor.py` rows; the `user-story-e2e.md` doctor transcript updated | `core/doctor.py`; `spec-setup.md` |
| **DB and traceability** | `runs.backend` and `problem_versions.backend` are free `TEXT` columns — no migration unless a constraint is added; `run info` / `run list` / `--dry-run` / the manifest show the new value (FR-RUN-047); the DES-001 §3.1 / §3.5 value lists and the `spec-run.md` §5 manifest comment mention it | `infra/db.py`; DES-001; `spec-run.md` |
| **Token accounting (D2)** | either `wants_http_proxy()` is `True` (OpenAI-compatible HTTP engine), or it is `False` and `collect_token_usage()` reads engine-native counts; token-primary, no USD; an L2 test asserts tokens are stored after a mocked run | ADR-007 D2 |
| **Reproducibility (D3)** | `global_seed` is truthful; the CLI warns when a seed is requested and unsupported (NFR-024 row in the traceability matrix) | ADR-007 D3 |
| **Neutral config (D4)** | `build_config()` maps the neutral levers (`--iterations`, `--temperature`, `--parallel`, `--rewrite-mode`, `--selection`, `--llm-weight`, `--reasoning-effort`) or warns per capabilities; `resolved_config()` returns a `ResolvedConfig` with engine-only keys in `backend_extras`; unknown `--config-override` keys warn; `evaluation.on_timeout` / `timeout_score` honored in the wrapper (FR-RUN-054) | ADR-007 D4 and A1; `specifications.md` §4.5; `spec-run.md` |
| **LLM registry projection (D5)** | `LLMEntry` / `EnsembleEntry` (local Ollama and remote) are projected into the engine's model syntax; only provider environment-variable **names** are exported (NFR-050); ensembles are accepted or rejected per `selection_strategies`; the `spec-llm.md` projection note is extended | ADR-007 D5 and A2–A5 |
| **Dependency extra (D6)** | `[project.optional-dependencies] <name> = ["<package>>=x,<y"]` with an upper bound; never in the `dev` extra; `is_available()` import probe with an install hint; exit code 3 when the backend is selected but absent; README install block and NFR-061 example | `pyproject.toml`; ADR-007 D6 |
| **CLI** | `run --backend <name>` works with the explicit > version-stored > default resolution and the mismatch warning (FR-RUN-047, FR-PRB-016); `solution extract --rank` / `--program-id` gated on `top_n_extraction` (FR-SOL-021); help wording lists the backend | `cli/run.py`; `core/solution.py`; `spec-run.md` |
| **Wrapper evaluator and L2 contract track** | `generate_wrapper()` bridges `evaluate_instance()` to the engine contract, emits `instances_valid` / `instances_total` and a distinct timeout branch (FR-RUN-053); contract tests (`tests/integration/test_<name>_wrapper.py`, `test_run_<name>.py`, `test_<name>_db.py` or equivalent) with module-level `pytest.importorskip`, `@pytest.mark.integration` and `@pytest.mark.<name>` (marker registered in `pyproject.toml` — markers are strict); a `no_<name>` fixture in `tests/conftest.py` for "not installed" tests; fixtures under `tests/fixtures/`; the L1 suite runs **without** the engine; an L3 scenario in `tests/e2e/` (`e2e` + `slow`) against the fake LLM server | `val-integration-tests.md` §1 and §4; `val-e2e-tests.md`; `tests/conftest.py` |
| **Specs, DES, ADR** | FR-RUN-047/048, FR-SET-002, FR-PRJ-005, FR-PRB-016, FR-SOL-021, NFR-024/061 wording widened to the new backend; DES-005 §4.1–§4.6 and §14; DES-006 §1.3 wrapper table row; `architecture.md` §1 external-dependencies table, §3 package tree, §8 stack; ADR-007 amended when the engine shares its paradigm (an evolution engine with the `EVOLVE-BLOCK` / `combined_score` conventions), **or a new ADR** when the paradigm differs | `docs/specs/`, `docs/architecture/` |
| **Validation documents** | `validation.md` §3 level table gets a `2-<Name>` row and the backend-matrix paragraph; `val-integration-tests.md` §1 scope, §2 rows and §4 conventions bullet; a `val-e2e-tests.md` scenario; traceability rows (FR-RUN-047/048, FR-SET-002, NFR-024/061) with the new test ids; the §13 summary | `docs/validation/` |
| **Guides and README** | a new or updated guide stamped `verified-against`; the tuning guide gains a per-backend knob section; README features block, install extras, narrative | `docs/guides/`, `README.md` |
| **Process evidence** | the issue follows the new-backend shape (paradigm, engine package and version bound, capabilities matrix, real-engine test plan); the pull-request description states how the engine-marked tests were run against the **real engine** and its version, since CI does not run engine tests | `AGENTS.md`; `validation.md` §6.4 |

## Where it is checked

Section 1 is walked by the author before marking the pull request ready and
by the reviewer ([code-review.md](code-review.md), exit rule); section 2 is
walked in addition for backend pull requests (code review, step 3). The
maintainer re-checks items 2, 3 and 7 during the pre-release documentation
audit ([release.md](release.md), step 0).

## Provenance

Both lists were implicit practice, reconstructed at v0.19.0 from the
repository files cited above and from the first backend integration
(ShinkaEvolve, Sprints 013–014).
**(changed)** The former post-merge steps "backlog row closed with the PR
number, sprint-file task ticked" are replaced by the issue closure
(`Closes #N`) and the planning issue's task table, since the backlog and
sprint files are no longer in the repository (ADR-008 D2, amended
2026-10-23).
