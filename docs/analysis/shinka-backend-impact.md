# Impact Analysis — Pluggable Evolution Backend (OpenEvolve + ShinkaEvolve)

**Status:** Draft — architecture/impact study (no implementation)
**Date:** 2026-06-02
**Revolver version:** v0.12.0
**Author:** deep-impact analysis (research agent)

> Goal: assess what it would take to abstract Revolver's evolution engine into a
> pluggable **backend** that can target **either OpenEvolve** (current) **or
> ShinkaEvolve** (https://github.com/SakanaAI/ShinkaEvolve).

Facts are tagged **[verified]** (read directly in source) or **[inferred]**
(reasoned from surrounding code/docs, not executed) or **[unverifiable]** (could
not confirm without running). All Revolver line references are against the
v0.12.0 working tree; ShinkaEvolve references are against a `--depth 1` clone of
`main` taken on 2026-06-02 into `/tmp/shinka`.

---

## 1. Revolver's current OpenEvolve coupling

OpenEvolve (OE) assumptions are concentrated in two infra modules and the run
domain logic. The three-layer architecture (CLI → core → infra) already isolates
*most* OE knowledge in `infra/`, but several OE concepts have leaked into
`core/run.py` and the persisted data model.

### 1.1 Where OE-specific assumptions live

| Concern | Location | Coupling detail |
|---|---|---|
| Controller import/launch | `src/revolver/infra/openevolve.py:234-312` (`OpenEvolveRunner._init_controller`, `run`) | Imports `openevolve.config.Config`, `openevolve.controller.OpenEvolve`; calls `asyncio.run(controller.run(iterations=…, checkpoint_path=…))` **[verified]** |
| Config schema (key names) | `infra/openevolve.py:389-586` (`build_config`) | Emits OE keys: `max_iterations`, `diff_based_evolution`, `max_code_length`, `checkpoint_interval`, `random_seed`, `llm.primary_model`, `llm.api_base`, `llm.api_key`, `llm.models[]`, `evaluator.cascade_evaluation`, `evaluator.parallel_evaluations`, `prompt.system_message`, `database.*` **[verified]** |
| Config validation | `infra/openevolve.py:107-201` (`validate_oe_config`) | dacite strict parse against `openevolve.config.Config`; `_DATABASE_KEYS`, `REVOLVER_KEYS` **[verified]** |
| Override parsing | `infra/openevolve.py:604-644` (`_set_nested`, `_parse_value`) | Generic dotted-key/JSON parsing — backend-agnostic **[verified]** |
| Ensemble mapping | `infra/openevolve.py:318-386` (`_build_ensemble_llm_config`) | Maps Revolver `LLMEntry`/`EnsembleMember` → OE `llm.models[]` with `name`/`api_base`/`api_key`/`weight`/`temperature`/`max_tokens` **[verified]** |
| API-key resolution | `infra/openevolve.py:676-722` (`resolve_api_keys`) | Resolves `llm.api_key_env` and `${ENV}` in `models[]` — OE config shape **[verified]** |
| Checkpoint discovery | `infra/openevolve.py:725-758` (`find_latest_checkpoint`) | Hard-codes `oe-output/checkpoints/checkpoint_N/`, sorts by numeric suffix **[verified]** |
| MAP-Elites cell map | `infra/openevolve.py:761-811` (`_build_cell_reverse_map`) | Parses `metadata.json` → `island_feature_maps` (list per island of `"d0-d1" → program_id`) **[verified]** |
| Population parsing | `infra/openevolve.py:814-875` (`parse_population`) | Scans `checkpoint_N/programs/*.json`; `combined_score = sum(numeric metrics)`; fields `id`, `generation`, `iteration_found`, `parent_id`, `cell_indices`, `island` **[verified]** |
| Best-score read | `infra/openevolve.py:878-926` (`read_checkpoint_best_score`) | Reads `metadata.json:best_program_id` → `programs/{id}.json:metrics` **[verified]** |
| Valid-program count | `infra/openevolve.py:929-964` (`count_valid_programs`) | Reads `database.json` (list, or dict with `programs`) **[verified]** |
| Env-var injection | `infra/openevolve.py:650-673` (`revolver_env`); used `core/run.py:802-806,1393-1397` | Sets `REVOLVER_DATASET_DIR`, `REVOLVER_INSTANCE_LOG`, `REVOLVER_EVAL_LOG`; wrapper reads `REVOLVER_INSTANCE_PATH` **[verified]** |
| Wrapper-evaluator template | `core/run.py:180-295` (`_WRAPPER_TEMPLATE`), `core/run.py:2011-2080` (`generate_wrapper`) | Generates `_revolver_evaluator.py` exposing OE's `evaluate(program_path) -> dict[str,float]`; aggregates `evaluate_instance()` over the dataset; expects `combined_score` key **[verified]** |
| Token proxy wiring | `core/run.py:786-794,1379-1387`; `infra/token_proxy.py` | Starts an HTTP proxy, rewrites `llm.api_base` to the proxy URL, parses OpenAI `usage` from responses **[verified]** |
| Output collection | `core/run.py:2177-2219` (`_collect_programs`) | Globs `top_programs/`, `best_programs/`, `best/`, or root `*.py` from `oe-output/` → `programs/rank-N.py` **[verified]** |
| Resume semantics | `core/run.py:1192-1657` (`resume_run`) | Copies parent `_revolver_evaluator.py` + latest checkpoint → new run's `oe-checkpoint/`; passes `checkpoint=` to runner **[verified]** |
| Status / valid_iterations | `core/run.py:117-175` (`_determine_run_status`, `_determine_crash_status`) | Uses `count_valid_programs(checkpoint)` to derive `completed`/`completed_with_errors`/`failed` **[verified]** |
| Live status / progress | `core/run.py:1667-1779` (`get_run_status`) | Reads progress from checkpoint while running **[verified]** |
| Score extraction | `infra/openevolve.py:589-601` (`_extract_best_score`) | OE returns a number or `Program` with `.metrics["combined_score"]` **[verified]** |

### 1.2 Persisted data-model coupling

`src/revolver/models/run.py` mixes generic and OE-specific fields:

- `ResolvedOEConfig` (`models/run.py:163-193`) is **entirely OE-shaped**:
  `num_islands`, `feature_dimensions`, `feature_bins`, `diff_based_evolution`,
  `max_code_length`, `parallel_evaluations`, `llm_models` **[verified]**.
- `RunManifest.checkpoint` defaults to `"oe-checkpoint/"` (`models/run.py:159`)
  **[verified]**.
- `RunManifest`/`RunInfo`/`RunSummary` carry `valid_iterations`, `llm_type`,
  `llm_snapshot`, `llm_model` — generic enough to keep, but `valid_iterations`
  semantics ("iterations that produced valid programs") is derived from the OE
  checkpoint database **[verified]**.
- The DB `runs` table stores `config_snapshot` (a YAML dump of the OE config) and
  `llm_snapshot` (`core/run.py:755-771`, `1347-1364`) **[verified]**.

### 1.3 The evaluator contract (Revolver side)

`generate_wrapper` (`core/run.py:2011-2080`) accepts a user evaluator
(`evaluator.py`) exposing **either**:
- `evaluate(program_path: str) -> dict[str, float]` (legacy, copied verbatim), or
- `evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]`
  (wrapped; aggregated over `REVOLVER_DATASET_DIR` instances, mean per metric,
  must produce `combined_score`).

This is **OE's evaluator contract** (`evaluate(program_path)`), wrapped to inject
Revolver's per-instance dataset model. The `combined_score` convention and the
"sum of numeric metrics" scoring are OE conventions **[verified]**.

### 1.4 Reproducibility / traceability anchors

- `random_seed` is an OE top-level + `llm.random_seed` key (`build_config:508-512`)
  **[verified]**.
- Lineage: `problem_hash`, `dataset_hash`, `llm_snapshot`, `config_snapshot`,
  `resumed_from` chain (`core/run.py`, `models/run.py`) **[verified]**.
- Design docs: `docs/architecture/adr/ADR-006-openevolve-instance-injection.md`
  (Strategy A+B: env-var injection + generated wrapper), `DES-005`
  (orchestration), `DES-006` (eval loop). The wrapper/env-var contract is the
  core of ADR-006 **[verified — referenced in module docstrings]**.

---

## 2. ShinkaEvolve integration surface

ShinkaEvolve (`shinka-evolve` on PyPI; **Apache-2.0**; `requires-python >=3.10`;
classifiers list 3.10–3.12) **[verified — `/tmp/shinka/pyproject.toml`]**.

### 2.1 How a run is configured and launched

Two entry points **[verified]**:
1. **Programmatic** (the integration target): construct three dataclasses and call
   `.run()`:
   ```python
   from shinka.core import ShinkaEvolveRunner, EvolutionConfig
   from shinka.database import DatabaseConfig
   from shinka.launch import LocalJobConfig
   runner = ShinkaEvolveRunner(evo_config=…, job_config=…, db_config=…,
                               max_evaluation_jobs=…, max_proposal_jobs=…,
                               max_db_workers=…, verbose=True)
   runner.run()   # sync wrapper around asyncio.run(self.run_async())
   ```
   (`/tmp/shinka/examples/circle_packing/run_evo.py`; runner class
   `shinka/core/async_runner.py:219-967`) **[verified]**.
2. **CLI / Hydra**: `shinka_launch` → `shinka/launch_hydra.py` uses Hydra +
   OmegaConf to instantiate `job_config`/`db_config`/`evo_config` from YAML config
   groups (`shinka/configs/*.yaml`) **[verified]**. Revolver should use the
   **programmatic** path (mirrors how it uses OE's controller) and avoid Hydra.

`.run()` raises `RuntimeError` if called inside a running event loop (same
constraint as `OpenEvolveRunner.run`) **[verified — `async_runner.py:955-967`]**.

The three config objects **[verified]**:
- `EvolutionConfig` (`shinka/core/config.py:19-72`): `task_sys_msg`, `patch_types`
  (`["diff","full","cross"]`), `patch_type_probs`, `num_generations` (default 50),
  `job_type` (`"local"`/`"slurm_*"`), `language` (default `"python"`),
  `llm_models: List[str]`, `llm_dynamic_selection` (`"ucb"`/`"thompson"`/`"fixed"`/
  bandit obj), `llm_kwargs: dict`, `meta_llm_models`, `embedding_model`
  (`"text-embedding-3-small"`), `init_program_path` (default `"initial.py"`),
  `results_dir`, `max_api_costs`, `evolve_prompts`, novelty settings.
- `DatabaseConfig` (`shinka/database/dbase.py:52+`): `db_path` (SQLite),
  `num_islands` (2), `archive_size` (40), `migration_interval` (10),
  `migration_rate`, `parent_selection_strategy`, `archive_selection_strategy`
  (`"fitness"`/`"crowding"`), `archive_criteria` (e.g.
  `{combined_score: 1.0, loc: -0.3}`), dynamic-islands settings.
- `JobConfig`/`LocalJobConfig`/`SlurmDockerJobConfig`/`SlurmCondaJobConfig`
  (`shinka/launch/scheduler.py:33-93`): `eval_program_path` (default
  `"evaluate.py"`), `extra_cmd_args: dict`, plus local conda/python-executable
  and SLURM resource fields.

`init_program_str` and `evaluate_str` can be passed directly as **strings** to the
runner (written to `results_dir`), an alternative to file paths
(`async_runner.py:300-315`) **[verified]** — convenient for Revolver injection.

### 2.2 The evaluator / scoring contract

Shinka's evaluator is a **standalone CLI script**, not an imported function.
The scheduler invokes it as a subprocess
(`shinka/launch/scheduler.py:125-157`) **[verified]**:
```
python <eval_program_path> --program_path <prog> --results_dir <dir> [--<k> <v> …]
```
The script must write `results_dir/metrics.json` and `results_dir/correct.json`
(`{"correct": bool, "error": str|None}`). The runner reads these back. Helper
`run_shinka_eval(...)` (`shinka/core/wrap_eval.py:103-484`) does the heavy lifting:
runs `experiment_fn_name` N times, optional `validate_fn`, `aggregate_metrics_fn`,
early stopping, parallel runs, and `save_json_results`. The aggregated metrics
**must include `combined_score`** (numeric; NaN/inf marks the program incorrect)
**[verified]**. `public_metrics`/`private_metrics` are first-class
(`dbase.py:168-169`, example `evaluate.py:114-125`) **[verified]**.

So Shinka's contract is **file-on-disk + subprocess CLI + `metrics.json`**, vs
OE's **in-process `evaluate(program_path)` returning a dict**. Fundamentally
different shape from Revolver's current wrapper, but Revolver's
`evaluate_instance()` user contract can still be adapted (see §3).

### 2.3 Program representation & EVOLVE markers

- Evolvable regions are marked `# EVOLVE-BLOCK-START` … `# EVOLVE-BLOCK-END`
  (`/tmp/shinka/examples/circle_packing/initial.py:1,91`) **[verified]**. Comment
  prefix is language-aware (`shinka/utils/languages.py`) **[verified]**. **This is
  the same marker convention OpenEvolve uses** — a major compatibility win.
- Patch modes: `diff`, `full` (full rewrite), `cross` (crossover)
  (`EvolutionConfig.patch_types`) **[verified]**. OE's `diff_based_evolution`
  boolean maps onto Shinka's `diff` vs `full` patch types.
- Multi-language: `python`, `cpp`, `cuda`, `rust`, Fortran, Julia, Wolfram
  (`utils/languages.py`, `examples/`) **[verified]** — Shinka is **not**
  Python-only, unlike Revolver's evaluator-import model.

### 2.4 Where results / checkpoints / population are written

- Single SQLite DB: `results_dir/programs.sqlite` (`async_runner.py:1136-1144`)
  **[verified]**. Tables include `programs` (`id`, `generation`,
  `combined_score`, `public_metrics`, `private_metrics`, `metadata`,
  `archive_inspiration_ids`, `migration_history`, `correct`, …) and a
  `metadata_store` holding `best_program_id` (`dbase.py:425-469,630-642`)
  **[verified]**.
- Per-generation directories: `results_dir/gen_<N>/main.<ext>` and
  `gen_<N>/results/` containing `metrics.json`/`correct.json`
  (`async_runner.py:1527-1547`, `FOLDER_PREFIX="gen"`) **[verified]**.
- Best program tracked via `db.best_program_id`; API `db.get_best_program()`,
  `db.get_top_programs_async(k)`, `db.get_all_programs()` (`dbase.py:1549+`,
  `async_dbase.py`) **[verified]**. Programs have `.combined_score`, `.correct`,
  `.public_metrics`, `.metadata` **[verified]**.
- Bandit state: `results_dir/bandit_state.pkl` (`async_runner.py:568-596`)
  **[verified]**.

There is **no `checkpoint_N/` directory and no `island_feature_maps` JSON**.
Population/island state lives in the SQLite DB, not on the OE-style filesystem
layout. Revolver's `parse_population`, `find_latest_checkpoint`,
`read_checkpoint_best_score`, `count_valid_programs`, `_build_cell_reverse_map`
have **no direct analog** and must be reimplemented against `programs.sqlite`.

### 2.5 Resume / checkpoint support

Resume is **DB-driven**: if `results_dir/programs.sqlite` exists and
`db.last_iteration > 0`, the runner resumes (`async_runner.py:1157-1178`,
`_restore_resume_progress`), reloading API costs and bandit state **[verified]**.
There is **no explicit "checkpoint path" argument**; you resume by pointing at the
same `results_dir`. This is simpler than OE's checkpoint-copy model but means
Revolver's "copy parent checkpoint into new run dir" resume strategy
(`resume_run`) must change to "reuse / clone the parent's `programs.sqlite` +
`gen_*` dirs into the new run dir."

### 2.6 LLM / providers / ensemble

- LLMs are selected **by model name string**, resolved to a provider via
  `resolve_model_backend()` (`shinka/llm/client.py:24-107`). Providers: `anthropic`,
  `bedrock`, `openai`, `azure_openai`, `deepseek`, `google` (genai), `openrouter`,
  `local_openai`, `headless` **[verified]**.
- Each provider uses its **native SDK** (`anthropic.Anthropic`, `openai.OpenAI`,
  `google-genai`, etc.) — **not** a uniform OpenAI base_url. Only `openai`,
  `azure_openai`, `deepseek`, `openrouter`, and `local_openai` go through the
  OpenAI SDK; `anthropic`/`bedrock` use the Anthropic SDK and `google` uses
  google-genai **[verified — `client.py`]**.
- **Local OpenAI-compatible** models are addressed with a special model-name
  syntax: `local/<model>@http://host:port/v1?api_key_env=ENV`
  (`shinka/local_openai_config.py`) **[verified]**. So a Revolver "local" LLM
  (Ollama) maps to `local/<model>@<base_url>?api_key_env=…` — a clean mapping,
  and one where the HTTP proxy *could* still intercept.
- **Ensemble** is native and richer than OE's weighted models: `llm_models` is a
  list and `llm_dynamic_selection` chooses among them per-proposal via a bandit
  (UCB/Thompson/fixed) — a multi-armed-bandit model rather than OE's static
  weights (`async_runner.py:360-383`, `EvolutionConfig`) **[verified]**.
- Cost/usage is tracked **natively**: per-program `metadata.api_costs`
  (+ `embed_cost`, `novelty_cost`, `meta_cost`) summed from the DB
  (`async_runner.py:745-803`); pricing from a bundled `pricing.csv`
  (`shinka/llm/providers/pricing.py`) **[verified]**. `EvolutionConfig.max_api_costs`
  is a native budget cap **[verified]**. Token counts are captured per provider in
  `shinka/llm/providers/result.py` (input/output tokens) **[inferred — file present,
  not read line-by-line]**.

### 2.7 Parallelism, seeds, dependencies

- Parallelism is **async + slot pools** (`max_evaluation_jobs`,
  `max_proposal_jobs`, `max_db_workers`) auto-tuned to CPU/RAM
  (`async_runner.py:657-729`) **[verified]**. This subsumes OE's
  `evaluator.parallel_evaluations`.
- Per-run seeds: the default `get_experiment_kwargs` passes `{"seed": i+1}` to the
  evaluation function (`wrap_eval.py:243-247,320-324`) **[verified]**. There is no
  single global `random_seed` knob like OE's; reproducibility of the *search* (LLM
  sampling, bandit) is **not obviously seedable** — see Risk R3.
- Heavy dependency footprint: `hydra-core==1.3.2`, `httpx==0.27`, `instructor`,
  `boto3`, `google-genai`, `anthropic`, `openai`, `matplotlib`, `seaborn`,
  `moviepy`, `scikit-learn`, `networkx`, `radon`, `dill`, … (`pyproject.toml`)
  **[verified]**. Notably **pins `httpx==0.27`** and `hydra-core==1.3.2`, which
  may conflict with Revolver's deps — see Risk R1.

---

## 3. Gap analysis

### 3.1 Concept mapping table

| Revolver concept | OpenEvolve mechanism | ShinkaEvolve mechanism | Verdict |
|---|---|---|---|
| Launch a run | `OpenEvolve(...).run(iterations, checkpoint_path)` (async) | `ShinkaEvolveRunner(...).run()` (async) | **Maps cleanly** (both sync-wrap asyncio) |
| Iterations budget | `max_iterations` | `EvolutionConfig.num_generations` | **Maps cleanly** (rename) |
| Config object | dict → `OEConfig.from_dict` | 3 dataclasses (`evo`/`db`/`job`) | **Partial** — one dict vs three typed configs |
| Initial program | file path | `init_program_path` **or** `init_program_str` | **Maps cleanly** (Shinka also accepts string) |
| Evaluator contract | in-process `evaluate(program_path)->dict` | subprocess CLI writing `metrics.json` | **Incompatible shape** — needs a different wrapper |
| Per-instance dataset model | wrapper aggregates over `REVOLVER_DATASET_DIR` | no native concept; `get_experiment_kwargs`/`num_runs` | **Partial** — emulate via generated `evaluate.py` |
| `combined_score` convention | sum of numeric metrics | explicit `metrics["combined_score"]` | **Maps cleanly** (Shinka is stricter/explicit) |
| EVOLVE markers | `# EVOLVE-BLOCK-START/END` | `# EVOLVE-BLOCK-START/END` | **Maps cleanly** (identical) |
| Diff vs rewrite | `diff_based_evolution: bool` | `patch_types` incl. `diff`/`full`/`cross` | **Maps cleanly** (richer in Shinka) |
| MAP-Elites / islands | `database.num_islands`, `feature_dimensions`, `feature_bins`; `island_feature_maps` JSON | `DatabaseConfig.num_islands`, archive + bandit selection; **no feature_bins/dimensions** | **Partial** — islands map; MAP-Elites feature-grid does **not** |
| Population query | `parse_population(checkpoint_N)` from JSON files | `db.get_all_programs()` from `programs.sqlite` | **Partial** — reimplement against SQLite; no `cell_indices` |
| Best program | `metadata.json:best_program_id` → file | `db.best_program_id` / `db.get_best_program()` | **Maps cleanly** (different storage) |
| valid_iterations | `count_valid_programs(database.json)` | `COUNT(*) WHERE correct=1` in DB | **Partial** — reimplement; semantics align |
| Checkpoint layout | `oe-output/checkpoints/checkpoint_N/` | `results_dir/programs.sqlite` + `gen_N/` | **Incompatible layout** |
| Resume | copy checkpoint dir; pass `checkpoint_path` | reuse same `results_dir` (DB-driven) | **Partial** — different mechanism, same intent |
| Output programs | glob `top_programs/*.py` | `db.get_top_programs()` → write files | **Partial** — reimplement extraction |
| Single LLM | `llm.primary_model` + `api_base` + `api_key` | `llm_models=[name]`, `llm_dynamic_selection="fixed"` | **Maps cleanly** |
| Local LLM (Ollama) | `api_base` + placeholder `api_key` | `local/<model>@<url>?api_key_env=…` | **Maps cleanly** (syntax change) |
| Ensemble | static `llm.models[]` weights | bandit over `llm_models` (UCB/Thompson) | **Partial** — weights → bandit; richer, lossy round-trip |
| Provider routing | OpenAI-compatible base_url for all | native SDK per provider | **Partial** — affects proxy (see token tracking) |
| Token/cost tracking | HTTP proxy parses OpenAI `usage` | native per-program `api_costs` in DB + pricing.csv | **Incompatible mechanism** — proxy mostly won't apply |
| System prompt injection | `prompt.system_message` | `EvolutionConfig.task_sys_msg` | **Maps cleanly** (rename) |
| Global seed | `random_seed` | per-eval `seed`; no global search seed | **Missing** (search-level reproducibility) |
| Temperature | `llm.temperature` | `llm_kwargs` (model-dependent) | **Partial** |
| Parallelism | `evaluator.parallel_evaluations` | `max_evaluation_jobs` (+ proposal/db) | **Maps cleanly** (rename) |
| Language | Python only (evaluator import) | python/cpp/cuda/rust/julia/… | **Shinka superset** |
| Config validation | dacite strict vs `OEConfig` | dataclass `__init__` (TypeError on bad key) | **Partial** — reimplement validator |

### 3.2 Proposed backend abstraction

Introduce `src/revolver/infra/backends/` with a `Protocol`/ABC. Keep all
engine-specific knowledge inside backend implementations; `core/run.py` becomes
backend-agnostic orchestration.

```python
# infra/backends/base.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

@dataclass
class BackendRunSpec:
    """Everything a backend needs to launch one run (engine-neutral)."""
    initial_program: Path
    evaluator_path: Path            # user evaluator.py (snapshot)
    snapshot_dir: Path              # problem version snapshot
    dataset_dir: Path
    run_dir: Path                   # Revolver-owned output dir
    problem_description: str | None
    llm: LLMEntry                   # primary / shared
    ensemble: EnsembleEntry | None
    iterations: int
    temperature: float | None
    parallel: int | None
    rewrite_mode: bool
    config_overrides: list[str]
    resume_from: Path | None = None # parent run dir (resume)

@dataclass
class BackendRunResult:
    best_score: float | None
    valid_iterations: int | None
    token_usage: TokenUsage | None      # may be filled by backend OR proxy
    programs: list[ProgramEntry]        # written into run_dir/programs/
    raw_best: Any = None

class EvolutionBackend(Protocol):
    name: str                       # "openevolve" | "shinka"

    def is_available(self) -> tuple[bool, str | None]: ...
    def validate_config(self, problem_config: Path | dict) -> list[str]: ...
    def build_config(self, spec: BackendRunSpec) -> dict[str, Any]: ...
    def resolved_config(self, cfg: dict[str, Any]) -> ResolvedConfig: ...  # dry-run
    def generate_wrapper(self, spec: BackendRunSpec) -> Path: ...
    def launch(
        self, spec: BackendRunSpec, cfg: dict[str, Any],
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult: ...
    # population / inspection (read-only, from run_dir)
    def parse_population(self, run_dir: Path) -> list[dict[str, Any]]: ...
    def read_progress(self, run_dir: Path) -> tuple[int | None, float | None]: ...
    def count_valid(self, run_dir: Path) -> int | None: ...
    # token tracking strategy
    def wants_http_proxy(self) -> bool: ...      # OE: True; Shinka: usually False
    def collect_token_usage(self, run_dir: Path) -> TokenUsage | None: ...
```

`OpenEvolveBackend` wraps the existing `infra/openevolve.py` functions almost
1:1. `ShinkaBackend` is new and translates `BackendRunSpec` → the three Shinka
dataclasses, generates a Shinka-style `evaluate.py`, runs `ShinkaEvolveRunner`,
and reads back `programs.sqlite`.

A factory `get_backend(name: str) -> EvolutionBackend` is selected from a new
`backend` field (config/CLI). This preserves the three-layer architecture: CLI
flags → `RunConfig.backend` → `core.run` calls `backend = get_backend(...)` →
backend lives in `infra/`. Traceability is preserved by storing `backend` +
`config_snapshot` + `llm_snapshot` in the run record/manifest.

### 3.3 Ripple effects (enumerated)

| Area | Change | Size |
|---|---|---|
| `infra/backends/` | New package: `base.py`, `openevolve.py` (refactor existing), `shinka.py` (new) | L |
| `core/run.py` | Replace direct `OpenEvolveRunner`/`build_config`/`find_latest_checkpoint`/`count_valid_programs`/`parse_population` calls with `backend.*`; resume path generalized | L |
| `models/run.py` | Add `backend: str` to `RunConfig`/manifest/summary/info; replace `ResolvedOEConfig` with a neutral `ResolvedConfig` (+ backend-specific extras dict) | M |
| DB schema | Add `runs.backend TEXT NOT NULL DEFAULT 'openevolve'`; **migration** required (Revolver uses SQLite, ADR-004) | M |
| `config.yaml` (problem version) | Allow Shinka-shaped config (`db_config`/`evo_config`/`job_config`) **or** keep OE shape; per-backend validation; `problem version create` validation hook | M |
| CLI | `revolver run --backend {openevolve,shinka}`; surface in `run info`, `run list`, dry-run | S |
| `build_config` | Split: OE keeps `infra/backends/openevolve.py`; Shinka builds dataclasses | M |
| Wrapper generation | Per-backend: OE template stays; Shinka generates a CLI `evaluate.py` calling `run_shinka_eval` and adapting `evaluate_instance()` over the dataset | L |
| Population / checkpoint parsing | Shinka: query `programs.sqlite` (no `cell_indices`/feature map) | M |
| Token tracking | Shinka path: read `api_costs` from DB instead of proxy; proxy only for OpenAI-compatible/local models | M |
| `validate_*_config` | New `ShinkaBackend.validate_config` (dataclass-key check) | S |
| Dry-run output | Neutral `ResolvedConfig`; backend fills its known fields | S |
| Doctor / setup | New optional extra `revolver[shinka]`; `doctor` checks Shinka import + provider env vars (`validate_model_env_access`) | S |
| Population CLI (`get_population`) | Tolerate missing `cell_indices`/`island` for Shinka | S |
| Docs | New ADR (backend abstraction), DES-005 revision, DES-006 revision (eval contract per backend), guides, specs FR updates | M |
| Tests | L2/L3 matrices duplicated per backend; new Shinka fake/mocks | L |

### 3.4 Token tracking assessment

**[verified]** Revolver's `TokenCountingProxy` works by rewriting `llm.api_base`
to a local HTTP proxy and parsing the OpenAI-style `usage` field
(`infra/token_proxy.py`, `core/run.py:786-794`). This is only viable when **all**
LLM traffic goes through an OpenAI-compatible HTTP endpoint.

ShinkaEvolve uses **native SDKs** per provider (`shinka/llm/client.py`):
Anthropic and Google traffic does **not** pass through an OpenAI base_url, so the
proxy cannot intercept it. Only `local_openai`/`openai`/`deepseek`/`openrouter`
go through `openai.OpenAI(base_url=…)`, and even then Shinka builds the client
internally — Revolver cannot trivially rewrite the base_url unless it uses the
`local/<model>@<url>` syntax (where the URL is user-controlled and could point at
the proxy) **[inferred]**.

**Recommended strategy:** for the Shinka backend, **abandon the proxy and read
native cost/usage from `programs.sqlite`** (`metadata.api_costs` summed across
programs; `async_runner._get_total_api_costs` shows the exact query) **[verified]**.
This is more accurate (includes embedding/novelty/meta costs) but changes the
*meaning* of `token_usage`: Shinka reports **USD cost** robustly and token counts
per-provider; Revolver's `TokenUsage` is `prompt_tokens`/`completion_tokens` +
estimated cost. Mapping Shinka → Revolver `TokenUsage` may leave
`prompt/completion_tokens` approximate or zero while `estimated_cost_usd` comes
straight from Shinka **[inferred]**. This is the single biggest data-model
mismatch (see §4).

### 3.5 Reproducibility / traceability differences

- **Seeds:** OE has a global `random_seed`; Shinka has per-evaluation `seed=i+1`
  and bandit/LLM sampling that is **not** obviously globally seedable
  **[verified — no global seed knob found; unverifiable whether one exists
  undocumented]**. Revolver's reproducibility guarantee ("same config + seed ⇒
  same run") **cannot be fully honored** on the Shinka backend without upstream
  support. Document this as a backend capability difference.
- **Lineage:** Shinka stores parent/inspiration IDs and migration history in the
  DB (`dbase.py`) — richer lineage than OE, but in a different schema. Revolver's
  `resumed_from` chain still works at the run level.
- **Snapshotting:** Revolver already snapshots problem/dataset hashes + config;
  this is backend-agnostic and preserved.

---

## 4. Verdict

### 4.1 Feasibility

**Feasible, medium-to-large effort.** The architecture is favorable: Revolver's
three-layer design already isolates most OE knowledge in `infra/`, EVOLVE markers
are identical, the `combined_score` convention matches, both engines sync-wrap
asyncio, both accept an initial-program-as-string, and Shinka is Apache-2.0 /
Python 3.10–3.12 (compatible). The hard parts are (1) the **evaluator contract**
(in-process dict vs subprocess `metrics.json`), (2) **token/cost tracking** (proxy
vs native DB), and (3) **population/checkpoint** (JSON files vs SQLite).

### 4.2 T-shirt sizing per workstream

| Workstream | Size | Notes |
|---|---|---|
| `EvolutionBackend` ABC + factory + refactor OE into a backend | **M** | Mostly moving code; low risk |
| `models.run` neutralization + `backend` field | **S–M** | Touches many models |
| DB migration (`runs.backend`) | **S** | One column + default |
| `ShinkaBackend.build_config` (3 dataclasses) + validation | **M** | Mapping + dep wrangling |
| Shinka `evaluate.py` generation (per-instance → `run_shinka_eval`) | **L** | New contract; correctness-critical |
| Shinka launch/monitor/resume | **M** | `results_dir` reuse model |
| Shinka population/best/valid from SQLite | **M** | New parsers |
| Token/cost from Shinka DB; proxy gating | **M** | Data-model mismatch |
| CLI `--backend`, dry-run, doctor/setup, `[shinka]` extra | **S–M** | |
| Docs (ADR + DES-005/006 + guides + specs) | **M** | |
| Tests (L2/L3 per backend, Shinka mocks) | **L** | Likely the biggest single cost |

**Overall: ~2–3 sprints** for a solid MVP + parity-minus, on the order of the
sprint cadence implied by the v0.x history (one engine-integration sprint, one
data/CLI/docs sprint, one hardening/test sprint). A bare MVP could land in ~1
sprint if scope is held tight (see phasing).

### 4.3 Phasing

**Phase 0 — Spike (timeboxed):** install `shinka-evolve` alongside Revolver in a
throwaway env; confirm dependency co-installability (`httpx==0.27`,
`hydra-core==1.3.2`) **[the #1 unknown]**; run `examples/circle_packing` to learn
the real `programs.sqlite`/`gen_*` layout and cost fields.

**Phase 1 — Refactor (no behavior change):** extract `EvolutionBackend` ABC,
wrap existing OE code as `OpenEvolveBackend`, add `backend` field defaulting to
`openevolve`, DB migration. Ship with OE-only; full green tests prove the
abstraction is neutral.

**Phase 2 — ShinkaEvolve MVP:** single-LLM only (`llm_dynamic_selection="fixed"`),
Python only, `diff`+`full` patch types, generated `evaluate.py` adapting
`evaluate_instance()`, launch + read best/population/valid from `programs.sqlite`,
cost from DB (no proxy), `revolver run --backend shinka`, dry-run, doctor check.
**Explicitly out of MVP:** ensemble/bandit, prompt evolution, novelty judge,
multi-language, SLURM, full token-count parity, search-level reproducibility.

**Phase 3 — Parity push:** ensemble→bandit mapping, multi-language passthrough,
richer cost/token mapping, resume parity, guides, full L2/L3 matrices.

### 4.4 New/updated design docs required

- **New ADR** (e.g. ADR-007 "Pluggable evolution backend"): the abstraction, the
  backend capability matrix (seeds, token tracking, MAP-Elites), and the decision
  to read Shinka cost from the DB rather than via the proxy.
- **DES-005 revision:** orchestration becomes backend-mediated; resume semantics
  per backend; manifest `backend` field; `ResolvedConfig` neutralization.
- **DES-006 revision:** evaluator contract per backend (in-process vs CLI
  `metrics.json`); how `evaluate_instance()` maps to `run_shinka_eval`.
- Specs (FR-RUN-*) updates for `--backend`, capability differences, and the
  reproducibility caveat; traceability-matrix rows.

### 4.5 Key risks & unknowns

- **R1 — Dependency conflict [biggest technical risk].** Shinka pins
  `httpx==0.27` and `hydra-core==1.3.2` and pulls a large stack (boto3,
  matplotlib, moviepy, scikit-learn, instructor, google-genai). Co-installing in
  Revolver's environment may be infeasible or force version downgrades.
  *Mitigation:* isolate Shinka behind the `revolver[shinka]` optional extra and/or
  run Shinka in a **subprocess** (it already has a CLI entry point
  `shinka_launch`), so its deps never share Revolver's import space.
  **[unverified — must be tested in Phase 0].**
- **R2 — Token/cost model mismatch.** `TokenUsage(prompt,completion)` does not map
  cleanly to Shinka's per-program USD `api_costs`. Risk of misleading cost
  reporting / broken comparisons in `benchmark`. *Mitigation:* read USD cost
  natively; treat token counts as best-effort.
- **R3 — Reproducibility.** No global search seed in Shinka ⇒ Revolver's
  reproducibility guarantee is weaker on this backend. Must be documented, not
  papered over.
- **R4 — Evaluator contract drift.** Generating a correct Shinka `evaluate.py`
  that faithfully reproduces Revolver's per-instance aggregation (and `correct`
  semantics) is subtle and is the most likely source of silent scoring bugs.
- **R5 — Population semantics.** No MAP-Elites feature grid / `cell_indices` in
  Shinka ⇒ `revolver run population` output is partial; downstream UI/tests that
  assume `cell_indices`/`island` need guards.
- **R6 — Async/event-loop & subprocess interplay.** If Shinka runs in-process,
  its `asyncio.run` + slot pools + RichHandler logging may clash with Revolver's
  stderr/quiet conventions and the proxy threads. (Running it as a subprocess,
  per R1, also resolves this.)

### 4.6 The single biggest open question

**Can ShinkaEvolve be co-installed in Revolver's environment, or must it be driven
as an isolated subprocess?** This determines the entire integration shape
(in-process `EvolutionBackend.launch` calling `ShinkaEvolveRunner` vs a
subprocess/CLI adapter reading `programs.sqlite` afterward), the dependency
strategy, and the token/async risks (R1/R6). **Resolve this first, in Phase 0,
before committing to the ABC's `launch()` signature.**

---

## Appendix — Source references

**Revolver (v0.12.0):**
`src/revolver/infra/openevolve.py`, `src/revolver/core/run.py`,
`src/revolver/infra/token_proxy.py`, `src/revolver/models/run.py`,
`docs/architecture/adr/ADR-006-openevolve-instance-injection.md`,
`docs/architecture/design/DES-005-run-orchestration.md`,
`docs/architecture/design/DES-006-eval-loop.md`.

**ShinkaEvolve (`/tmp/shinka`, `main` @ 2026-06-02, Apache-2.0):**
`pyproject.toml`, `shinka/core/async_runner.py` (`ShinkaEvolveRunner`),
`shinka/core/config.py` (`EvolutionConfig`), `shinka/core/wrap_eval.py`
(`run_shinka_eval`), `shinka/database/dbase.py` (`DatabaseConfig`,
`ProgramDatabase`, `Program`), `shinka/launch/scheduler.py`
(`JobConfig`/`JobScheduler`), `shinka/llm/client.py`,
`shinka/local_openai_config.py`, `shinka/utils/languages.py`,
`shinka/launch_hydra.py`, `examples/circle_packing/{run_evo.py,evaluate.py,initial.py}`.
