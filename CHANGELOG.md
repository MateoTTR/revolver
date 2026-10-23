# Changelog

All notable changes to Revolver are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Revolver is pre-1.0: a minor version may change default behavior; such changes
are flagged **Behavior change** in the entry that introduces them.

Entries up to v0.18.0 were reconstructed after the fact from the sprint records
(`docs/sprints/`), the annotated tag messages and the merged pull requests;
`(#N)` refers to a pull request. From v0.19.0 on, this file is the release-note
vehicle: each pull request adds its line under `[Unreleased]`, and the release
moves that block under a dated version heading (see `docs/process/release.md`).

## [Unreleased]

### Added

- `AGENTS.md` as the canonical, tool-neutral entry file for humans and agents; `CLAUDE.md` and `GEMINI.md` become one-line pointers to it (issue #277).
- `docs/process/` checklists — code, specification, validation and documentation review, sprint planning, release and hotfix, Definition of Done — extracted from the former agent definitions so that a contributor with no AI tooling can run the process (issue #277).
- ADR-008 "Documentation and process strategy", with the sanitized development-process analysis committed under `docs/analysis/` as its evidence (issue #277).
- `CHANGELOG.md` as the release-note vehicle, seeded with every release since v0.1.0 (#280, closes #275).
- MIT `LICENSE` file (#274, closes #272).

### Changed

- `pytest` runs with `--strict-markers` (an unregistered marker now fails collection); the tooling sections of `docs/validation/validation.md` match `pyproject.toml` and `ci.yml`, and the never-registered `e2e_gpu` marker is dropped from them (issue #277).
- CI runs on GitHub-hosted runners (`ubuntu-latest`) instead of a self-hosted pool; the runner image under `.github/runner/` is removed (#274).
- Planning is frozen in the repository at the end of Sprint 019: `docs/tasks/backlog.md` and `docs/sprints/` become historical records; from Sprint 020 on, planning lives in GitHub issues and milestones (#280).

### Removed

- Tool-specific automation (`.claude/`, `.mcp.json`) leaves git and is ignored: tooling stays private per contributor and its knowledge lives in `docs/process/` (ADR-008 D5) (issue #277).
- The maintainer's session journal (`docs/sessions/*`) leaves the public repository; a `docs/sessions/README.md` pointer remains and the history stays in git (#280).

## [0.18.0] - 2026-07-05

Sprint 018 — eval-honesty semantic slice and ShinkaEvolve-native top-N promotion.

### Added

- `solution extract --rank N` and `--program-id <id>` promote any program of a ShinkaEvolve run's population into a solution; OpenEvolve reports a clear "not supported" (#268).
- `problem version create --backend <name>` persists the backend on the problem version; `run` resolves it from the version when `--backend` is omitted and warns on an explicit mismatch (DB migration v14) (#264).
- ShinkaEvolve honors the registry LLM timeout (`llm add --timeout`) for its LLM requests; `--dry-run` surfaces `llm_timeout` (#269).
- Doc anti-rot: fenced `revolver` commands in the documentation are linted against the CLI tree in CI, guides carry `verified-against` freshness stamps, and the tuning guide is backend-neutral (`docs/guides/tuning-evolution.md`) (#251, #256, #250).

### Changed

- **Behavior change** — timeout handling penalizes by default: an instance that times out during evolution contributes `evaluation.timeout_score` (default `0.0`) to the program's fitness mean instead of being silently dropped. Set `evaluation.on_timeout: drop` (or `--config-override evaluation.on_timeout=drop`) to restore the 0.17 survivor-mean; on negative-is-good metrics set `timeout_score` below your worst valid score (#257).
- **Behavior change** — default checkpoint cadence: when `checkpoint_interval` is unset, a run checkpoints every `max(1, min(100, iterations // 10))` iterations (previously a flat `100`), so a killed short run has a mid-run checkpoint to resume from; explicit values are never overridden (#265).
- **Behavior change** — the automatic post-run evaluation persists `eval_metadata`/`eval_instances` through the standard eval path and uses that path's per-instance timeout (previously stderr-only with a hardcoded 300 s timeout) (#261).
- **Behavior change** — seed-metric pre-flight: a run whose seed program lacks a declared non-builtin `database.feature_dimensions` metric aborts before iteration 0 with a clear message; the builtins `complexity`/`diversity`/`combined_score` are allowed, and runs that previously launched with such a seed no longer do (#265).
- **Behavior change** — `run info` shows the engine best labeled "(engine, single eval)" next to the coverage-labeled post-eval mean (#261).
- **Behavior change** — generated evaluator wrappers emit the `instances_valid`/`instances_total` coverage keys; the `instances_` metric prefix is reserved and never summed into the displayed score (#257).

### Fixed

- Child-process reap hardened: recursive descendants, process-group kill and a `(pid, starttime)` guard against PID reuse (#267).
- A ShinkaEvolve `max_proposal_jobs` override is no longer silently dropped (#254).

## [0.17.1] - 2026-07-04

Sprint 017a — corrective release after the v0.17.0 demo feedback (defensive slice, no change to scores or display).

### Added

- `REVOLVER_EVAL_NUM_THREADS` caps BLAS/OpenMP threads per evaluation subprocess (default `max(1, cpu_count // 2)`; `0` disables; a cap you already set is respected) (#242).
- `--dry-run` surfaces the resolved bandit kwargs (`llm_dynamic_selection_kwargs`), including the injected `cost_aware_coef` (#243).
- A `key=value` token given as a bare `run` argument gets a hint naming the repeatable options (`--config-override`, `--selection-kwarg`, `--llm-weight`) (#243).

### Fixed

- Evaluation subprocesses are killed at the per-instance timeout, and a finalize backstop reaps any survivor — no more leaked evaluation workers after a timed-out instance (#242, #245).
- `--selection-kwarg` values are coerced to their declared types (`false` is no longer read as `True`) and an invalid kwarg fails at `--dry-run` instead of at launch (#243).
- A key-less local OpenEvolve ensemble member no longer crashes at init (placeholder key, no ambient key forwarded) (#243).
- The snapshot `config.yaml` is re-validated at run start, and a `checkpoint_interval` larger than the iteration count triggers a recoverability warning (#243).

## [0.17.0] - 2026-07-02

Sprint 017 — multi-LLM ensemble validated end-to-end on both backends.

### Added

- Ensemble selection on `run`: `--selection {fixed,ucb,ucb1,thompson}` (adaptive bandits on ShinkaEvolve) and per-run `--llm-weight <member>=<weight>`, capability-gated per backend with explicit warnings where a backend ignores a setting (#228, #232, #233).
- Per-LLM `--reasoning-effort` on `llm add`/`llm update` and `llm ensemble add`, honored per member on OpenEvolve and pooled with a warning on ShinkaEvolve (#235).
- `REVOLVER_HOME` (base directory) and the global `--global-db <path>` flag relocate the global store for CI isolation (#239).
- `solution extract --from-checkpoint` recovers the best program of an interrupted OpenEvolve run (#229).

### Changed

- `--config-override` warns when a key is a no-op for the selected backend (#237).

### Fixed

- The OpenEvolve wrapper no longer crashes on a non-numeric metric field, and an OpenEvolve run no longer busy-loops after completion (#229).

## [0.16.1] - 2026-06-23

Sprint 016a — corrective release after the v0.16.0 demo feedback.

### Changed

- OpenEvolve runs on a `--source local` LLM auto-pin `parallel_evaluations` to 1; an explicit `--parallel` above 1 warns (#222).
- `run resume <run-id>` accepts the run id positionally (`--run <id>` still works) (#219).
- `run info` carries a token under-count caveat for runs served through a local OpenAI-compatible shim; CI isolates the global DB per job (#221, #225).

### Fixed

- `llm add --source local --base-url <url>` probes the given Ollama host (a scheme-less `OLLAMA_HOST` is accepted) instead of `localhost`, so a network Ollama serves both backends (#220).
- A ShinkaEvolve run returns to the prompt cleanly after completion (orchestrator-owned shutdown and child reap) (#224).
- A fresh `project init` followed by `problem version create --backend openevolve` produces a warning-free OpenEvolve config (#222).

## [0.16.0] - 2026-06-20

Sprint 016 — technical-debt paydown and CLI/UX polish.

### Added

- `dataset add --split both` (DB migration v11) (#210).
- `run info` shows `programs_extracted` and `programs_in_db` counters, with a rank-1 score fallback labeled "(from run)" (#210).
- CI `version-check` job blocks a tag push whose version does not match `pyproject.toml` and `__init__.py` (#206).

### Changed

- `problem version create <tag>` takes the tag positionally; `--tag` is deprecated but still accepted (#210).
- ShinkaEvolve resume clones the parent output directory so the parent run stays untouched; a `resume_precheck` fails fast on an unusable parent (#212).
- A ShinkaEvolve dry-run on a `--source local` LLM pins `max_proposal_jobs: 1` (#210).
- DES-005 rewritten around the backend abstraction; pre-release documentation audit across the living docs (#207, #214).

### Removed

- Inert pricing machinery: `llm add --input-cost`/`--output-cost` and the cost columns (DB migration v10) (#208).

## [0.15.0] - 2026-06-20

Sprint 015 — thinking-model usability, token honesty, slow-local-endpoint timeout.

### Added

- Thinking-capable models are usable on ShinkaEvolve: `max_tokens=16384` and `max_patch_attempts=10` defaults, configurable `reasoning_efforts` (#199).

### Changed

- `run info` reports prompt/completion/total tokens with an honesty caveat; the cost estimate is no longer reported (#202).
- A run where every proposal fails ends as `completed_with_errors` with a visible warning instead of `completed` (#201).
- OpenEvolve runs against a `--source local` endpoint use a 600 s request timeout (was 60 s), so slow local endpoints no longer abort (#202).

### Removed

- The `infra/openevolve.py` re-export shim (#202).

## [0.14.0] - 2026-06-13

Sprint 014 — ShinkaEvolve MVP.

### Added

- `run --backend shinka` runs a real ShinkaEvolve evolution end-to-end; install the backend with `pip install 'revolver[shinka]'` (#192, #196, #197).
- `project init --backend shinka` scaffolds a ShinkaEvolve-shaped `config.yaml`; `problem version create --backend <name>` validates the config per backend (#197).
- `run --backend shinka --dry-run` shows the neutral config plus the ShinkaEvolve `backend_extras` (#196).
- `doctor` reports ShinkaEvolve availability with an install hint; `setup` lists the `[shinka]` extra (#196, #197).

### Changed

- `run resume` works on ShinkaEvolve parents (in-place continuation); `solution`, `eval` and `benchmark` work unchanged on ShinkaEvolve-generated artifacts (#196, #197).
- Orchestrator seams (staging, program counting, config tier) made backend-neutral (#193).

## [0.13.0] - 2026-06-12

Sprint 013 — pluggable evolution backend (ADR-007), zero behavior change.

### Added

- `EvolutionBackend` abstraction with OpenEvolve wrapped as the default `OpenEvolveBackend` (#184).
- `run --backend <name>`; `run info`, `run list` and `--dry-run` show `backend: openevolve`; runs record their backend (DB migration v9) (#185, #188).
- `run --backend shinka` stub fails cleanly with an install hint (exit 3); an unknown backend exits 1 (#189).
- `doctor` reports ShinkaEvolve availability as informational (#189).

### Changed

- No user-visible change: the pre-existing test suite passes unmodified apart from import relocations (#188).

## [0.12.1] - 2026-06-07

Hotfix after v0.12.0.

### Fixed

- `click>=8` declared as a direct dependency: the global-option handling imports Click directly and Typer 0.26 dropped it as a transitive dependency (#181).
- Global-option parsing typed against Typer's vendored Click context (mypy clean) (#181).

### Changed

- CI builds an ephemeral conda environment per run (#181).

## [0.12.0] - 2026-04-02

Sprint 012 — demo feedback: UX and reliability.

### Added

- `run status` during an active run shows iterations completed and best score from the latest checkpoint (#177).
- `run population` includes the MAP-Elites cell indices and island of each program (#175).
- `solution info` on a resumed run shows `resume_chain` and `resumed_from` (#179).

### Changed

- `--dry-run` reflects the complete resolved OpenEvolve config: `diff_based_evolution`, `max_code_length`, config overrides and ensemble `llm_models` (#176).
- `run list` marks ensemble runs with an `(E)` prefix (#179).

### Fixed

- Run status classification: a run with errors is `completed_with_errors` (binary valid/failed logic, no 10 % threshold), and exception handlers count valid programs before marking the status (#178).

## [0.11.0] - 2026-03-28

Sprint 011 — multi-model ensemble support.

### Added

- `llm ensemble create/add/list/info/remove`: named multi-model ensembles in the LLM registry (global DB migration v8) (#161, #164).
- `run --llm <ensemble>` emits OpenEvolve's native `llm.models` array with per-member weights; `run info` and `run list` show the ensemble (#165).
- Runs store a structured `llm_snapshot` (and `llm_type`) for traceability, for single-LLM runs too (#165).

### Changed

- Tuning guide gains an ensemble-strategies section; documentation audit cascade (#167, #169).

## [0.10.0] - 2026-03-28

Sprint 010 — resume, robustness and UX.

### Added

- `run resume --llm <name>` and `run resume --config-override` switch the LLM and tune the config on resume (#151).
- `run --rewrite-mode` (also on `run resume`): full-rewrite evolution in one flag (#153).
- `run cleanup` marks orphaned runs `interrupted`; `run list` auto-detects zombie runs and warns (#155).
- `run population <run-id>`: MAP-Elites population table (#157).
- `llm update --model <name>` fixes a model name without delete/re-add (#148).

### Changed

- A run with 100 % LLM errors ends `failed`; one with under 10 % valid iterations ends `completed_with_errors` (#149).

### Fixed

- `problem version` no longer warns on the `initial_program`, `timeout_per_instance` and `num_generations` keys of `config.yaml` (#147).

## [0.9.1] - 2026-03-27

Sprint 009a — bugfix delta: resume, config validation, UX polish.

### Added

- `run resume --iterations/--temperature/--parallel` tune OpenEvolve on resume (#142).
- `run --dry-run` displays the resolved OpenEvolve config (iterations, checkpoint interval, islands, feature dimensions, temperature, parallel evaluations) (#140).
- `config.yaml` validation at `problem version` and at run start: misplaced keys (such as `num_islands` outside `database:`) produce an actionable warning (#141).

### Fixed

- `run resume` resolves the checkpoint under `oe-output/checkpoints/checkpoint_N/`, and a checkpoint interval larger than the iteration count is guarded (#139).
- Tuning guide examples use the `database:` namespace (#143).

## [0.9.0] - 2026-03-25

Sprint 009 — solution UX, fluent config, run robustness.

### Added

- `solution show`, `solution export [-o <path>]` and `solution diff <a> <b>` for direct access to generated programs (#124).
- `run --temperature` and `run --parallel` tune OpenEvolve without editing `config.yaml`; `llm add/update --temperature` stores a per-LLM temperature (DB migration v6) (#133, #121).
- `--config-override` accepts JSON arrays and objects (#128).
- `solution extract --force` re-extracts, replacing an existing solution (#122).
- Guides: tuning the OpenEvolve config (MAP-Elites, islands, parallelism) and an updated initial-program guide (#131, #132).

### Changed

- A crashed run is marked `failed`/`interrupted` instead of staying `running` (#130).
- Commands run outside a workspace report "Not in a Revolver workspace" explicitly (#123).

## [0.8.1] - 2026-03-22

Sprint 008a — scriptability and UX polish.

### Added

- `llm update <name>` modifies a registered LLM without remove+add (#104).
- `run delete --all --force` purges the run history (#99).
- `problem version delete <tag>`, refusing when runs reference the version unless `--force` (#105).
- `project init --no-templates` creates a bare project (#103).
- `run` auto-selects the only problem version and the only train dataset when unambiguous, and shows iteration progress in real time (#112, #113).

### Changed

- `problem version` / `problem versions` restructured as `problem version create/list/delete` (#105).
- Help-text fixes (`benchmark results`, `llm add -s local`) and a documentation alignment pass across README, user story, specs, ConOps and traceability matrix (#108, #114, #115, #116).

## [0.8.0] - 2026-03-21

Sprint 008 — reliability and lifecycle management.

### Added

- `run delete <run-id> --force` removes a run with its solutions, eval data and files (#93).
- `llm remove --force` and `dataset remove --force` skip the confirmation prompt (#89).
- Pre-flight API-key gate: `run` aborts with a clear error when the LLM's API key environment variable is unset (#88).

### Fixed

- The generated wrapper evaluator enforces the per-instance timeout (#87).
- `problem test` works with evaluators exposing `evaluate_instance()` (#86).
- The post-run evaluation phase announces itself; DB migration v5 (#88, #91).

## [0.7.1] - 2026-03-21

Sprint 007a — post-demo fix.

### Fixed

- `--json`, `--verbose` and `--quiet` are recognized after any subcommand (`revolver llm list --json`), not only before it (#81).

## [0.7.0] - 2026-03-20

Sprint 007 — doctor, setup and cross-cutting polish.

### Added

- `doctor`: per-dependency OK/WARN/FAIL report with versions, usable outside a project, `--json` output (#76).
- `setup`: installs missing Python dependencies with confirmation, `--dry-run` previews the plan, proposes conda for Ollama when available (#76).

### Changed

- Cross-cutting consistency pass: every command produces valid `--json`, errors go to stderr with documented exit codes, progress spinners on long commands, confirmation summaries on state-modifying commands, tab completion via `--show-completion` (#77, #79).

## [0.6.3] - 2026-03-20

Sprint 006c — LLM registry config and iteration tracking.

### Added

- `llm add --max-tokens` and `--timeout` stored per LLM (DB migration v4) and injected into the OpenEvolve config; `--config-override` still wins (#73).
- Iteration success rate computed from the OpenEvolve checkpoint and shown in `run info` and `run list` (#73).

## [0.6.2] - 2026-03-19

Sprint 006b — demo feedback fixes.

### Added

- `benchmark delete <id>` with confirmation (`--force` to skip) (#71).

### Fixed

- `benchmark list` and `solution list` show full aliases; `--metric all` help carries a wide-output tip; `llm add --pull` no longer times out on large models (#71).

## [0.6.1] - 2026-03-19

Sprint 006a — demo feedback fixes.

### Added

- `benchmark --all --dataset <name>` benchmarks every solution; `--solutions` accepts a comma-separated list (#69).

### Changed

- Benchmark tables default to `combined_score`; `benchmark results --metric all` shows every metric; `--per-instance` defaults to `combined_score` (#69).

### Fixed

- `eval_id` collision (`IntegrityError`) when evaluating several solutions within the same second (#68).

## [0.6.0] - 2026-03-18

Sprint 006 — benchmark: multi-solution comparison and export.

### Added

- `benchmark --solutions <a> <b> ... --dataset <name>`: multi-solution comparison that reuses existing eval results and evaluates the rest (#60, #61, #64, #65).
- `benchmark results --latest [--per-instance --metric <m>]` with comparative aggregates and a per-instance wins summary (#65).
- `benchmark export --latest --format csv|json --output <file>`; exports contain no file paths or API-key environment names (#64, #65).
- `benchmark list` (#65).

## [0.5.1] - 2026-03-18

Sprint 005a — demo feedback fixes.

### Added

- `solution delete <alias>` with confirmation and `--force`, cascading to eval results (#55).
- `completed_with_errors` run status plus `run-error.log` when post-processing fails; `solution extract` works on such runs (DB migration v2) (#57).

### Fixed

- Security: `config_snapshot` stores `api_key_env` names, never cleartext API keys; a warning is emitted when the variable is missing (#56).
- Google provider: the top-level `random_seed` is cleared in addition to `llm.random_seed` (#56).

## [0.5.0] - 2026-03-17

Sprint 005 — solution management and evaluation loop.

### Added

- `solution list [--version <tag>]`, `solution info`, `solution alias` and `solution extract --run <id>` (#46, #50).
- `eval --solution <id> --dataset <name>` with per-instance progress; `eval results [--per-instance]` with aggregates (mean, p10/p50/p90) (#47, #51).
- Re-evaluation confirmation prompt; legacy evaluators with `user_aggregates` shown alongside Revolver aggregates (#51).

## [0.4.5] - 2026-03-17

Sprint 004b — proxy robustness and UX fixes.

### Added

- Guide on initial program structure best practices (#41).
- `--config-override key=null` (or `none`) sets a key to `None` (#43).

### Changed

- The token-tracking proxy forwards the upstream HTTP status and body (no more generic 502) and the `Retry-After` header, with optional backoff on 429 (#42).
- `run list` (and `--json`) shows the rank-1 solution alias (#43).

### Fixed

- Google provider detected behind the proxy: `random_seed` is cleared automatically, no manual override needed (#42).
- False-positive dual-function wrapper warning during pre-flight suppressed (#43).

## [0.4.4] - 2026-03-17

Sprint 004a — demo feedback fixes, third patch.

### Added

- Pre-flight check: the initial program is evaluated on the first instance before OpenEvolve launches (#33).

### Changed

- DES-005, specs and validation docs updated for the v0.4.x fixes (#36, #37).

### Fixed

- Local LLMs get the placeholder `api_key` OpenEvolve expects, `cascade_evaluation` is forced off, and `best_score` is extracted from the program metrics (#31).
- Program collection from `oe-output/best/`, post-run eval in `evaluate_instance()` mode and wrapper error logging (#32).
- The evaluator template uses the correct `evaluate_instance(program_path, instance_path)` signature (#35).

## [0.4.3] - 2026-03-16

Sprint 004a — demo feedback fixes, second patch.

### Fixed

- `build_config()` strips Revolver-specific keys (`evaluator`, `initial_program`) before handing the config to OpenEvolve and maps `num_generations` to `max_iterations` (#27).

## [0.4.2] - 2026-03-16

Sprint 004a — demo feedback fixes, first patch. The v0.4.1 hotfix was never tagged; its fixes shipped with this release.

### Added

- L2-OE integration tests against a real OpenEvolve installation, without an LLM (#26).

### Fixed

- Crash at run launch: the OpenEvolve controller receives a `Config` object instead of a dict (#25).
- `--dry-run` with an `iterations=0` fallback and a null `generation_time_s` default (#25).
- OpenEvolve config field mapping (`api_base`, `primary_model`, `max_iterations`) (#26).

## [0.4.0] - 2026-03-15

Sprint 004 — run orchestration (OpenEvolve integration).

### Added

- `run --version <tag> --llm <name> --dataset <name> [--alias <alias>]`: OpenEvolve orchestration with wrapper-evaluator generation, environment setup and result collection (#19, #20, #22, #24).
- `run --dry-run` displays the resolved config (#24).
- `run status`, `run list`, `run info <run-id>` (lineage, programs, token usage) and `run resume --run <run-id>` from a checkpoint (#22, #24).
- Token usage tracking through a local HTTP proxy; the post-run evaluation on the training set auto-creates eval results (#20, #22).

### Changed

- Minimum Python version raised to 3.12.

## [0.3.0] - 2026-03-14

Sprint 003 — dataset registration and integrity.

### Added

- `dataset add` registers a named dataset (path, `train`/`eval` split, compatible problem versions, optional snapshot copy) with per-instance SHA-256 hashing (#13, #14).
- `dataset list`, `dataset info <name> [--verify]` with a per-instance integrity report, `dataset update --add-compatible-with` and `dataset remove` (#14).

### Fixed

- Pre-sprint fixes: version string and duplicate-hash error message (#16).

## [0.2.0] - 2026-03-14

Sprint 002 — LLM registration and problem versioning.

### Added

- `llm add/start/stop/status/list/remove`: register local (Ollama) or remote API LLMs in the global registry, manage the Ollama lifecycle, show runtime state and VRAM (#5, #9).
- `problem test --instance <file>` / `--dataset <dir>` validate an evaluator in an isolated subprocess (#6, #10).
- `problem version --tag <tag> -m <message>` and `problem versions`: immutable problem snapshots with a SHA-256 manifest (#6, #10).

## [0.1.0] - 2026-03-14

Sprint 001 — foundation: project scaffolding, database, shared infrastructure.

### Added

- Project scaffold: pip-installable package, Typer root app with `--json`/`--verbose`/`--quiet`, typed exceptions mapped to exit codes 0–4, CI pipeline (#1, #3).
- Shared infrastructure: SQLite (WAL mode, schema, migrations), hashing, `.revolver/` store, configuration hierarchy, Rich tables and JSON output (#2).
- `project init <name> [--path <dir>] [--json]` creates a project with `.revolver/`, template files and an initialized database (#4).

[Unreleased]: https://github.com/MateoTTR/revolver/compare/v0.18.0...develop
[0.18.0]: https://github.com/MateoTTR/revolver/compare/v0.17.1...v0.18.0
[0.17.1]: https://github.com/MateoTTR/revolver/compare/v0.17.0...v0.17.1
[0.17.0]: https://github.com/MateoTTR/revolver/compare/v0.16.1...v0.17.0
[0.16.1]: https://github.com/MateoTTR/revolver/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/MateoTTR/revolver/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/MateoTTR/revolver/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/MateoTTR/revolver/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/MateoTTR/revolver/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/MateoTTR/revolver/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/MateoTTR/revolver/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/MateoTTR/revolver/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/MateoTTR/revolver/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/MateoTTR/revolver/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/MateoTTR/revolver/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/MateoTTR/revolver/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/MateoTTR/revolver/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/MateoTTR/revolver/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/MateoTTR/revolver/compare/v0.6.3...v0.7.0
[0.6.3]: https://github.com/MateoTTR/revolver/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/MateoTTR/revolver/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/MateoTTR/revolver/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/MateoTTR/revolver/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/MateoTTR/revolver/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/MateoTTR/revolver/compare/v0.4.5...v0.5.0
[0.4.5]: https://github.com/MateoTTR/revolver/compare/v0.4.4...v0.4.5
[0.4.4]: https://github.com/MateoTTR/revolver/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/MateoTTR/revolver/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/MateoTTR/revolver/compare/v0.4.0...v0.4.2
[0.4.0]: https://github.com/MateoTTR/revolver/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/MateoTTR/revolver/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/MateoTTR/revolver/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/MateoTTR/revolver/releases/tag/v0.1.0
