# Sprint 007 — Doctor, Setup & Cross-Cutting Polish

**Status**: Done
**Goal**: Deliver the `revolver doctor` and `revolver setup` top-level commands (dependency verification and assisted installation). Implement all cross-cutting integration tests (JSON output consistency, error codes, progress indicators, confirmation summaries, tab completion). Run the full regression suite (~80 L2 scenarios) to confirm no regressions across all sprints. This sprint makes the CLI production-ready.
**Demo**: `revolver doctor` produces a clean OK/WARN/FAIL per-dependency report; `revolver setup --dry-run` previews what would be installed; all 80+ integration tests pass; all commands produce valid `--json`; all errors go to stderr with correct codes.

---

## Scope

### Command groups included
- `revolver doctor` — top-level command, full implementation
- `revolver setup` — top-level command, full implementation
- Cross-cutting polish: `--json` consistency, error codes, progress indicators, confirmation summaries, tab completion

### Key FRs covered

**Setup & Doctor (17 FRs)**:
- FR-SET-001 — `doctor` checks Python package dependencies (versions, importability)
- FR-SET-002 — `doctor` checks OpenEvolve importability and version
- FR-SET-003 — `doctor` checks Ollama: HTTP health, version string
- FR-SET-004 — `doctor` checks nvidia-smi and GPU availability
- FR-SET-005 — Per-dependency OK / WARN / FAIL status with actionable messages (NFR-066)
- FR-SET-006 — Distinguish fixable issues (pip-installable) from system-level (instructions only)
- FR-SET-007 — `setup` installs missing Python packages via pip with confirmation
- FR-SET-008 — `setup` asks user confirmation before any installation
- FR-SET-009 — `setup` never installs system-level software (GPU drivers, OS packages, conda itself)
- FR-SET-010 — `setup` provides manual instructions for non-fixable dependencies
- FR-SET-011 — `setup --dry-run` preview: shows what would be installed without doing it
- FR-SET-012 — `doctor` works outside any project directory (global health check)
- FR-SET-013 — `doctor` reports version strings for all detected dependencies
- FR-SET-014 — Detect conda / mamba environment manager
- FR-SET-015 — Propose `conda install conda-forge::ollama` when conda available + Ollama missing
- FR-SET-016 — Report install method (pip vs conda) for each dependency
- FR-SET-017 — Manual installation instructions when conda unavailable + Ollama missing

### NFRs covered (cross-cutting audit)
- NFR-001 — Exit codes 0-4 validated across all command groups
- NFR-002 — `--help` verified on all 28 commands
- NFR-003 — `--json` produces valid JSON on ALL commands (comprehensive audit)
- NFR-004 — Error messages on stderr on all commands
- NFR-005 — Progress indicators on long-running commands (`run`, `eval`, `benchmark`, `problem test --dataset`, `dataset add`)
- NFR-006 — Confirmation summaries on all state-modifying commands
- NFR-007 — `revolver` root command with all subgroup structure
- NFR-008 — Tab completion for bash and zsh (SHOULD)

---

## Tasks

| # | Task | Layer | Depends on | Status | Acceptance criteria |
|---|---|---|---|---|---|
| S7-01 | Implement `revolver.core.doctor` — dependency health checks: (1) Python packages: typer, pydantic, pyyaml, rich, httpx versions via importlib; (2) OpenEvolve: importlib + version; (3) Ollama: `infra.ollama.health_check()` + `version()`; (4) nvidia-smi: `infra.gpu.get_gpu_info()`; produce `DoctorReport` with per-check `DependencyStatus(name, status, version, message, fixable)` | domain | Sprint 001-002 | [ ] | Unit tests with mocked subprocess/imports: all-pass case → all OK; missing dep → FAIL with correct message; `test_fixable_vs_system` |
| S7-02 | Implement `revolver.core.setup` — assisted installation: detect package managers (pip always, conda/mamba via subprocess), compute install plan from `DoctorReport`, display plan with confirmation prompt, execute pip install for Python packages, propose conda install for Ollama, re-run `doctor` after installation to verify; `--dry-run` shows plan only | domain | S7-01 | [ ] | Unit tests with mocked pip/conda subprocesses: `test_never_installs_system_pkg`, `test_detects_conda`, `test_reports_install_method`; dry-run produces no side effects |
| S7-03 | Implement `revolver.cli.doctor` — top-level Typer command (not a subgroup); render `DoctorReport` as rich table with status icons; works outside project directory | cli | S7-01 | [ ] | CliRunner: all deps OK → exit 0; any FAIL → exit 1; WARN-only → exit 0; `--json` outputs structured report; works without `.revolver/` |
| S7-04 | Implement `revolver.cli.setup` — top-level Typer command with `--dry-run`, `--force`; `--force` skips confirmation prompts for scripted use; display installation plan; show post-install verification results | cli | S7-02 | [ ] | CliRunner: `--dry-run` shows plan without changes; confirmation prompt can be bypassed with `--force`; `test_asks_confirmation`, `test_dry_run`, `test_installs_missing_pip`, `test_instructions_for_non_fixable`, `test_ollama_via_conda`, `test_manual_instructions_no_conda` |
| S7-05 | Cross-cutting audit: verify `--json` output on all 28 commands — parse each command's JSON output with `json.loads()`; fix any command returning non-JSON or mixed output in `--json` mode | cli | Sprint 001-006 | [ ] | `test_json_flag_all_commands`: for each command, `json.loads(result.output)` succeeds; no human-formatted text in stdout when `--json` is set |
| S7-06 | Cross-cutting audit: verify error handling on all commands — ensure all error paths write to stderr (not stdout); verify correct exit codes (1/2/3/4) per error class; add missing `raise typer.Exit(code=N)` where needed | cli | Sprint 001-006 | [ ] | `test_errors_on_stderr`: error message in `result.stderr`, not `result.stdout`; exit code matches error type; `test_exit_code_0_on_success` |
| S7-07 | Cross-cutting: add or verify progress indicators on long-running commands — `revolver run`, `revolver eval`, `revolver benchmark`, `revolver problem test --dataset`, `revolver dataset add` (large datasets); use `rich.progress.Progress` on stderr | cli | Sprint 001-006 | [ ] | `test_progress_on_stderr`: progress indicator renders to stderr during long operations; does not appear in `--quiet` mode |
| S7-08 | Cross-cutting: add confirmation summaries to all state-modifying commands — `project init`, `problem version`, `dataset add/update/remove`, `llm add/remove`, `run`, `eval`, `solution alias/extract`, `benchmark`; one-line "Done: X created/removed/updated" on success | cli | Sprint 001-006 | [ ] | `test_confirmation_summary`: all state-modifying commands print confirmation to stdout in human mode; summaries absent in `--quiet` mode; `test_single_binary_subcommands` |
| S7-09 | Implement tab completion for bash and zsh via Typer's built-in `--install-completion` / `--show-completion`; verify it generates valid shell completion script | cli | Sprint 001 | [ ] | `revolver --install-completion bash` exits 0 and writes completion script; script sources correctly; `revolver l[TAB]` would complete to `revolver llm` |
| S7-10 | Write L2 integration tests for `doctor` (3 scenarios) and `setup` (5 scenarios from val-integration-tests §2.9) | test | S7-03, S7-04 | [ ] | All 8 doctor/setup scenarios pass: `test_checks_python_packages`, `test_checks_openevolve`, `test_checks_ollama`, `test_checks_nvidia_smi`, `test_ok_warn_fail_status`, `test_works_outside_project`, `test_reports_versions`, `test_installs_missing_pip`, `test_asks_confirmation`, `test_instructions_for_non_fixable`, `test_dry_run`, `test_ollama_via_conda`, `test_manual_instructions_no_conda` |
| S7-11 | Write cross-cutting L2 integration tests (6 scenarios from val-integration-tests §2.10) | test | S7-05, S7-06, S7-07, S7-08 | [ ] | `test_json_flag_all_commands`, `test_help_on_all_commands`, `test_errors_on_stderr`, `test_confirmation_summary`, `test_progress_on_stderr`, `test_single_binary_subcommands` |
| S7-12 | Full regression: run all ~80 L2 integration tests from Sprints 001-007 in a single `pytest -m integration` run | test | S7-10, S7-11 | [ ] | All 80+ integration tests pass; CI green; no regressions across any sprint; total suite runs in under 2 minutes (NFR per val-integration-tests.md §4) |

---

## Integration Tests (L2)

Tests from `val-integration-tests.md §2.9–2.10` that must pass at sprint end:

| Command | Scenario | Test ID | Status |
|---|---|---|---|
| `doctor` | All deps present (mocked) — all checks pass, versions reported | `test_checks_python_packages` + `test_checks_openevolve` + `test_checks_ollama` + `test_checks_nvidia_smi` + `test_ok_warn_fail_status` + `test_reports_versions` | Planned |
| `doctor` | Ollama missing — WARN/FAIL status, actionable message | `test_ollama_missing` | Planned |
| `doctor` | Outside project dir — still works (global) | `test_works_outside_project` | Planned |
| `setup --dry-run` | Missing OpenEvolve — preview install commands | `test_dry_run` | Planned |
| `setup` | Missing pip package — installs, asks confirmation | `test_installs_missing_pip` + `test_asks_confirmation` | Planned |
| `setup` | System-level dep missing — instructions only | `test_instructions_for_non_fixable` | Planned |
| `setup` | Conda available, Ollama missing — proposes `conda install` | `test_ollama_via_conda` | Planned |
| `setup` | No conda, Ollama missing — manual instructions | `test_manual_instructions_no_conda` | Planned |
| Any command `--json` | Valid JSON to stdout, no human formatting | `test_json_flag_all_commands` | Planned |
| Any command `--help` | Usage text displayed | `test_help_on_all_commands` | Planned |
| Any error case | Message on stderr, correct exit code | `test_errors_on_stderr` + `test_exit_code_0_on_success` | Planned |
| State-modifying command | Confirmation summary displayed | `test_confirmation_summary` | Planned |
| Long-running command | Progress indicator on stderr | `test_progress_on_stderr` | Planned |
| `revolver` (root) | Subcommand structure accessible | `test_single_binary_subcommands` | Planned |

**Cumulative L2 tests at sprint end: ~94 total (80 previous + ~14 new)**

---

## Parallelization

### Dependency graph

```
Sprint 001-006 (all command groups complete) ──┬──> S7-01 (domain: doctor)
                                                │         ↓
                                                │    S7-02 (domain: setup)
                                                │         ↓
                                                ├──> S7-03 (cli: doctor) ─────────────────┐
                                                │         ↓                                 │
                                                ├──> S7-04 (cli: setup) ──────────────────┤
                                                │                                           │
                                                ├──> S7-05 (cross: --json audit) ──────┐  │
                                                ├──> S7-06 (cross: error audit) ───────┤  │
                                                ├──> S7-07 (cross: progress) ──────────┤  │
                                                ├──> S7-08 (cross: confirmations) ─────┤  │
                                                └──> S7-09 (cross: tab completion) ────┤  │
                                                                                        │  │
                                                                    S7-10 (test: doctor/setup)◄──┘
                                                                             │
                                                             S7-11 (test: cross-cutting) ◄──┘
                                                                             │
                                                                    S7-12 (full regression)
```

### Critical path
Sprint 006 → S7-01 → S7-02 → S7-03 → S7-04 → S7-10 → S7-12
Estimated sequential depth: 5 steps.

### Parallel work streams

| Stream | Tasks | Can start after | Agent assignment |
|---|---|---|---|
| A — Doctor + Setup commands | S7-01, S7-02, S7-03, S7-04 | Sprint 006 done | Agent 1 |
| B — Cross-cutting audit + tab completion | S7-05, S7-06, S7-07, S7-08, S7-09 | Sprint 006 done | Agent 2 |
| C — Tests + full regression | S7-10, S7-11, S7-12 | Streams A+B done | Agent 1 + Agent 2 |

Peak parallelism: 2 agents on Streams A and B simultaneously.

### Conflict risks
- **All `cli/*.py` files** — Streams A and B both touch CLI modules for consistency fixes (S7-05 to S7-08 audit every command); coordinate by file ownership or use sequential integration after individual audits
- `infra/output.py` — progress bars and formatting changes may affect rendering across all 10 command groups; changes here risk regressions in earlier sprint tests
- `cli/__init__.py` — global callback and global options may need updates for `--quiet` mode (suppress summaries/progress); also registers doctor + setup top-level commands

---

## Sprint Review

**Completed**: 2026-03-20 — Session 034
**Release**: v0.7.0

### Tests passing
- 20 / 20 integration tests passing (this sprint — 7 doctor + 7 setup + 6 cross-cutting)
- 138 / 138 total cumulative integration tests passing (full regression)
- 799 total tests (unit + integration), all passing
- Full suite runs in ~28s (well under 2-minute target)

### Demo-able features
- [x] `revolver doctor` shows per-dependency OK/WARN/FAIL table with version strings
- [x] `revolver doctor` works outside a project directory
- [x] `revolver doctor --json` outputs structured JSON report
- [x] `revolver setup --dry-run` shows installation plan without making changes
- [x] `revolver setup` installs missing packages with confirmation (mocked pip)
- [x] `revolver setup` proposes conda install for Ollama when conda detected
- [x] All commands produce valid `--json` output (automated verification)
- [x] All errors write to stderr with correct exit code
- [x] Progress spinners on `run`, `eval`, `benchmark`, `problem test --dataset`, `dataset add`
- [x] All 14 state-modifying commands show confirmation summaries
- [x] Tab completion script generated by `revolver --show-completion bash`
- [x] Full regression suite passes in under 2 minutes

### Carry-over
- L3 end-to-end scenarios (val-e2e-tests.md) — deferred to post-Phase 5 manual validation
- Performance NFRs (NFR-030, NFR-031, NFR-032) — manual validation only, not CI-gated
- FR-EVL-014 (`--parallelism N`) — deferred to v2
