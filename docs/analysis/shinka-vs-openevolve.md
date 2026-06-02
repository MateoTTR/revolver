# ShinkaEvolve vs OpenEvolve — Technical & Ecosystem Comparison

**Date:** 2026-06-02
**Author:** Automated deep analysis (source-level read of both repos + paper + GitHub API)
**Purpose:** Assess whether Revolver (which currently wraps OpenEvolve) should also support ShinkaEvolve as an alternative evolutionary backend.

**Method:** Both repos cloned shallow into `/tmp/shinka` and `/tmp/openevolve` (latest `main`, 2026-06-02). Source, README, docs, configs, and `pyproject.toml` read directly. GitHub metrics via authenticated `gh api`. ShinkaEvolve paper (arXiv:2509.19349) and Sakana blog fetched. Facts marked **[verified]** were read from source/API; **[inference]** is reasoning; **[unverified]** could not be confirmed.

---

## A. What each framework is

| | **ShinkaEvolve** | **OpenEvolve** |
|---|---|---|
| Origin | Sakana AI (Lange, Imajuku, Cetin). Paper arXiv:2509.19349, accepted ICLR 2026. | Community project by `codelion` (Asankhaya Sharma), now under the `algorithmicsuperintelligence` GitHub org. |
| Lineage | Inspired by AlphaEvolve + AI Scientist + Darwin-Gödel Machine. Explicitly positions itself as a *more sample-efficient* AlphaEvolve-style system. | Direct open-source reimplementation of DeepMind's AlphaEvolve. |
| Tagline | "Towards Open-Ended and Sample-Efficient Program Evolution" | "Open-source implementation of AlphaEvolve" |
| First release | v0.0.1 — 2026-03-12 (repo created 2025-09-17, alongside paper) **[verified]** | v0.0.x from 2025-05; v0.2.27 on 2026-03-18 **[verified]** |
| Maturity (self-declared) | `Development Status :: 3 - Alpha` in `pyproject.toml`; versions still `0.0.x` **[verified]** | No PyPI classifier; 52 releases, version `0.2.27`; markedly more iterated **[verified]** |
| License | Apache-2.0 **[verified]** | Apache-2.0 **[verified]** |

Both are LLM-guided evolutionary code-optimization frameworks built on the same core idea: maintain a population of programs, use LLMs as mutation operators to propose edits, evaluate candidates against a user-supplied scorer, and keep the best. ShinkaEvolve's README even lists OpenEvolve under "Related Open-Source Projects."

---

## B. Fundamental algorithmic differences

### Evolutionary strategy & archive

| Aspect | ShinkaEvolve | OpenEvolve |
|---|---|---|
| Population model | Islands + global archive. `num_islands` default **2**; `archive_size` default **40** **[verified, `shinka/database/dbase.py` DatabaseConfig]** | MAP-Elites quality-diversity grid + islands. `num_islands` default **5**; `population_size` **1000**; `archive_size` **100** **[verified, `openevolve/config.py:295`]** |
| Quality-Diversity | No explicit MAP-Elites feature grid. Diversity comes from islands + novelty rejection + code-embedding similarity. **[verified]** | Explicit MAP-Elites with configurable `feature_dimensions` (default `["complexity","diversity"]`, also `score`, or any evaluator metric) binned into `feature_bins` (default 10). **[verified, `config.py:317-332`]** |
| Parent selection | Pluggable `parent_selection_strategy`: `weighted` (default, sigmoid-scaled fitness with `parent_selection_lambda`), `power_law` (`exploitation_alpha`), `beam_search` (`num_beams`). `exploitation_ratio` 0.2 chance to draw from archive. This is the paper's "parent sampling balancing exploration/exploitation." **[verified, `shinka/database/parents.py`]** | `elite_selection_ratio` 0.1, `exploration_ratio` 0.2, `exploitation_ratio` 0.7; selection over MAP-Elites cells; "double selection" (different programs for performance vs inspiration). **[verified, config + README]** |
| Novelty handling | **Code novelty rejection-sampling** — a core paper contribution. Embeds candidate code, computes similarity to existing programs; if too similar (`code_embed_sim_threshold` 0.99) it can invoke an LLM novelty judge and *reject/resample* (`max_novelty_attempts` 3). **[verified, `shinka/core/novelty_judge.py`]** | Has a `novelty_judge.py` (LLM-based) and `embedding.py` + `similarity_threshold` 0.99, but novelty is a diversity signal within MAP-Elites rather than a hard rejection-sampling loop. **[verified]** |
| Dynamic islands | Optional stagnation-triggered island spawning (`enable_dynamic_islands`, `stagnation_threshold` 100). **[verified]** | Fixed island count with periodic migration. **[verified]** |
| Migration | `migration_interval` 10 gens, `migration_rate` 0.0 default (off). **[verified]** | `migration_interval` 50, `migration_rate` 0.1. **[verified]** |

### How candidates are proposed (edit strategy)

- **ShinkaEvolve:** Mixed strategy per proposal, sampled from `patch_types = ["diff","full","cross"]` with `patch_type_probs = [0.6, 0.3, 0.1]`. "diff" = search/replace patches, "full" = full rewrite, **"cross" = crossover** between two parents (a distinct operator OpenEvolve lacks as a first-class type). Diff/full application code in `shinka/edit/`. **[verified, `core/config.py`, `edit/`]**
- **OpenEvolve:** `diff_based_evolution` (default `True`) using SEARCH/REPLACE blocks (`diff_pattern` regex); set to `False` for full rewrites. No built-in crossover operator. **[verified, `config.py:421-423`]**

Both use `# EVOLVE-BLOCK-START` / `# EVOLVE-BLOCK-END` markers to delimit mutable regions — **identical convention** **[verified, both READMEs]**.

### LLM usage

| | ShinkaEvolve | OpenEvolve |
|---|---|---|
| Ensemble | Yes, multi-model list (`llm_models`). Default mixes GPT-5-mini, Gemini-3-flash/pro, GPT-5.4. **[verified]** | Yes, `LLMEnsemble` with weighted random sampling; `models` + separate `evaluator_models`. **[verified, `llm/ensemble.py`]** |
| Adaptive model selection | **Bandit-based (UCB) dynamic selection** with cost-aware blending (`llm_dynamic_selection="ucb"`, `cost_aware_coef` 0.5) — a core paper contribution. **[verified, `llm/prioritization.py`, `docs/bandit_selection.md`]** | Static weights only; no bandit. **[verified]** |
| Meta-prompting / prompt evolution | **System-prompt co-evolution** (`evolve_prompts`, prompt archive, UCB prompt sampling) — implemented and documented. **[verified, `core/prompt_evolver.py`]** | `use_meta_prompting` flag exists but config comment says **"meta-prompting features not implemented."** **[verified, `config.py:262`]** |
| Meta-recommendations | Periodic LLM "meta-recommendations" every `meta_rec_interval` 10 gens. **[verified]** | None equivalent. |
| Text feedback | `use_text_feedback` lets evaluator return `text_feedback` strings into the loop. **[verified]** | "Artifact side-channel" — evaluator returns artifacts (e.g. stderr) fed into next prompt. **[verified, `evaluation_result.py`]** |

### Parallelism, checkpointing, resume

| | ShinkaEvolve | OpenEvolve |
|---|---|---|
| Parallelism | Async runner overlapping proposal + evaluation; `max_evaluation_jobs`, `max_proposal_jobs`, `max_db_workers`. Adaptive proposal oversubscription controller (EWMA-based). Claims 5–10x throughput. **[verified, README, `core/async_runner.py`]** | `process_parallel.py` multiprocessing; `parallel_evaluations`. Cascade evaluation (cheap→expensive stages, `cascade_thresholds [0.5,0.75,0.9]`). **[verified]** |
| Execution backends | Local (current interpreter / sourced venv), **SLURM+Conda, SLURM+Docker** — first-class cluster support. **[verified, `shinka/launch/`]** | Local + Docker image; no native SLURM. **[verified]** |
| Persistence | **SQLite database** (`shinka/database/dbase.py` uses `sqlite3`, WAL, retries). Strong, queryable, transactional. **[verified]** | **In-memory dict + JSON checkpoint files** (`database.save()` writes JSON; programs as `programs/<id>.json`). `checkpoint_interval` 100; resume via `_load_checkpoint`. **[verified, `database.py:590`, `controller.py:253-273`]** |
| Resume | Via SQLite DB path. **[verified]** | Via `--checkpoint` path. **[verified]** |
| Budget cap | `max_api_costs` (USD) stops new proposals at cap. **[verified]** | No native USD budget cap (iteration/early-stopping based). **[verified]** |

---

## C. Integration-relevant interface differences (for Revolver)

### Configuration surface

| | ShinkaEvolve | OpenEvolve |
|---|---|---|
| Primary config | **Hydra** YAML presets + dataclasses (`EvolutionConfig`, `DatabaseConfig`, `JobConfig`). Also an agent CLI (`shinka_run`) that takes `--task-dir` + `--set k=v` overrides, no Hydra needed. Also a Python API (`ShinkaEvolveRunner`). **[verified]** | Single flat **YAML** file (`Config.from_yaml`) + dataclasses (dacite). CLI `openevolve-run.py initial.py evaluator.py --config c.yaml`. Also a Python API (`run_evolution`, `evolve_function`). **[verified]** |
| Config complexity | Higher: 3 config objects, Hydra group overrides, ~40+ Evolution fields + ~25 DB fields. **[verified]** | Moderate: one `Config` tree (`llm`/`prompt`/`database`/`evaluator`/`evolution_trace`). **[verified]** |
| Required entry artifacts | `initial.<ext>` + `evaluate.py` in a task dir. **[verified]** | `initial_program.py` + `evaluator.py` + `config.yaml`. **[verified]** |

### Evaluator / scoring contract (very similar — good for Revolver)

- **Both** key off a `combined_score` float for maximization. **[verified — Shinka README "Higher `combined_score`… maximization"; OpenEvolve `database.py:527-531` ranks on `combined_score`]**
- **ShinkaEvolve:** evaluator calls `run_shinka_eval(...)`, returns dict with `combined_score`, plus `public`/`private`/`extra_data`/`text_feedback`. **[verified, README]**
- **OpenEvolve:** evaluator returns `dict[str,float]` or an `EvaluationResult(metrics=..., artifacts=...)`. Custom MAP-Elites dimensions must be **raw continuous values** (binning internal). **[verified, `evaluation_result.py`]**

The contracts are close enough that a Revolver adapter layer mapping a common evaluator interface to both is feasible. The main divergence: ShinkaEvolve's `run_shinka_eval` helper and multi-run aggregation vs OpenEvolve's plain metrics-dict return.

### Program representation & outputs

- **ShinkaEvolve:** results dir per run; SQLite DB of program records + diffs + timing + prompt-evo artifacts; built-in WebUI (`shinka_visualize`). **[verified]**
- **OpenEvolve:** `openevolve_output/` with `best/`, `checkpoints/`, `logs/`, `programs/<id>.json`, optional `evolution_trace.{jsonl,json,hdf5}`. **[verified, `controller.py`]**

### LLM provider configuration

- **ShinkaEvolve:** Provider-specific clients (`shinka/llm/providers/`: openai, anthropic, gemini, deepseek, bedrock, **local_openai**, **headless** CLI for subscription agents like Codex/Claude). Models named by string (`"gpt-5-mini"`, `"headless/codex@gpt-5.5?effort=high"`, `"local/<model>@http://host/v1"`). Bundled pricing CSV. **[verified]**
- **OpenEvolve:** **OpenAI-compatible only** — any provider exposed through an OpenAI API (`api_base`, `api_key`, env-var `${VAR}` resolution). Simpler, more uniform. **[verified, `config.py:50-100`]**

> Note for Revolver: its key constraint is "all LLMs expose an OpenAI-compatible API." OpenEvolve matches this 1:1. ShinkaEvolve also supports local OpenAI-compatible endpoints but additionally hard-codes provider SDKs (anthropic, google-genai, boto3), which is a heavier dependency surface.

### Language support

- **ShinkaEvolve:** python, cpp, cuda, go, rust, swift, julia, fortran, wolfram, json/json5, markdown — explicit per-language extension/comment/fence tables. **[verified, `shinka/utils/languages.py`]**. Examples exist for Python, Julia, Fortran, Go, Wolfram. **[verified, `examples/`]**
- **OpenEvolve:** language-agnostic via `language`/`file_suffix`; examples for Python, Rust, R, Metal shaders. **[verified, README + `examples/`]**

Both are genuinely multi-language; ShinkaEvolve encodes more languages first-class.

### Dependencies, Python version

| | ShinkaEvolve | OpenEvolve |
|---|---|---|
| Python | `>=3.10` (3.10–3.12) **[verified]** | `>=3.10` **[verified]** |
| Dependency weight | **Heavy** — ~30 deps incl. anthropic, google-genai, boto3, instructor, hydra-core==1.3.2, matplotlib, seaborn, moviepy, scikit-learn, networkx, radon, dill, **httpx==0.27 (pinned)**. **[verified]** | **Light** — openai, pyyaml, numpy, tqdm, flask, dacite. **[verified]** |
| Pin risk | `hydra-core==1.3.2` and `httpx==0.27` are hard pins → potential conflict with a host app. **[verified]** | Loose lower bounds only → easy to embed. **[verified]** |

For an embedding host like Revolver, OpenEvolve's tiny, loosely-pinned dependency set is markedly easier to integrate than ShinkaEvolve's heavy, partly-pinned set (`hydra-core` and `httpx` pins are the main collision risk).

---

## D. Repository activity & community (GitHub API, 2026-06-02)

| Metric | ShinkaEvolve | OpenEvolve |
|---|---|---|
| Stars | **1,180** | **6,472** |
| Forks | 238 | 1,040 |
| Contributors | 22 | 45 |
| Top contributor share | RobertTLange 329 commits (dominant) | codelion 631 commits (dominant) |
| Releases / tags | 7 (v0.0.1→v0.0.7) | 52 (→v0.2.27) |
| Release cadence | ~monthly since 2026-03 | very frequent (52 tags) |
| Last commit | 2026-06-02 (active today) | 2026-03-18 (~2.5 months stale) |
| Commits (participation stat, ~1y) | ~370 | ~649 |
| Open issues (real) | **1** | **75** |
| Closed issues | 43 | 109 |
| Open PRs | 6 | 42 |
| Closed PRs | 87 | 193 |
| Docs | Dedicated mkdocs site (getting started, config, async, local models, WebUI, agentic) + Colab tutorial + CHANGELOG | Large README + `configs/README.md` + HF blog + GitHub Discussions |
| Community channel | GitHub issues/PRs, Sakana blog, talks (AutoML seminar) | GitHub Discussions |
| Backing | **Corporate (Sakana AI)** — paid maintainers | Individual-led community project |

**Reading the numbers:** OpenEvolve has ~5.5x the stars and broader contributor base, reflecting first-mover advantage (released May 2025 vs Sept 2025) and "the AlphaEvolve repo" mindshare. But its `main` has been **stale since 2026-03-18** with **75 open issues and 42 open PRs** piling up — a sign of maintenance lag for an individual-led project. ShinkaEvolve is **smaller but currently more actively maintained** (commits today, near-zero open issue backlog, corporate backing, regular releases). **[all verified via gh api]**

---

## E. Existing benchmarks

### ShinkaEvolve paper (arXiv:2509.19349) — claimed results **[verified via arXiv HTML/abstract]**

Three core innovations: (1) exploration/exploitation parent sampling, (2) code-novelty rejection sampling, (3) bandit-based LLM ensemble selection.

| Task | Result | Sample efficiency |
|---|---|---|
| **Circle packing (n=26, unit square)** | New SOTA, sum of radii ≈ **2.6360** (≈2.63598 exact-verified per AlphaEvolve's checker) | **~150 program evaluations** vs "thousands" for prior methods (incl. AlphaEvolve) |
| **AIME-2024 math (agentic harness)** | Beats single-query + majority-voting baselines, capped at 10 LLM queries/problem | — |
| **ALE-Bench (competitive programming)** | Improves ALE-Agent solutions ~**2.3%** over 10 tasks; reached 2nd place on ahc039 (3140 vs 2880 baseline) | — |
| **MoE load-balancing loss** | New LBL formulation beating global-batch LBL baseline | — |

The headline claim is **sample efficiency**: SOTA circle packing in ~150 evaluations.

### Head-to-head ShinkaEvolve vs OpenEvolve

- **No direct, tabulated head-to-head numbers exist** in the paper. **[verified]** The paper cites OpenEvolve as related work and uses OpenEvolve's published solution as one reference point for the circle-packing problem, but does not publish an apples-to-apples OpenEvolve run with matched budget. **[verified by reading arXiv HTML]**
- Third-party coverage (MarkTechPost, ResearchGate) repeats Sakana's framing: ShinkaEvolve reaches AlphaEvolve-class circle-packing results with orders-of-magnitude fewer samples. **No independent benchmark pitting the two frameworks under identical conditions was found.** **[unverified — none located]**
- OpenEvolve's own README claims it "matches published benchmarks for n=26 circle packing" and reports 2–3x kernel speedups, but these are self-reported, not a controlled comparison. **[verified self-claim, not independently validated]**

> **Caveat:** the sample-efficiency gap is real per the paper but is a comparison vs AlphaEvolve-style budgets, *not* a controlled ShinkaEvolve-vs-OpenEvolve study. Treat "ShinkaEvolve is more sample-efficient than OpenEvolve" as **plausible-but-unproven**.

---

## F. Maturity & risk assessment

| Dimension | ShinkaEvolve | OpenEvolve |
|---|---|---|
| Self-declared maturity | Alpha (`0.0.x`) | More iterated (`0.2.27`, 52 releases) |
| API stability | **Lower** — README documents a Mar 2026 API rename (`EvolutionRunner`/`AsyncEvolutionRunner` → unified `ShinkaEvolveRunner`). Expect churn. **[verified, README]** | Moderate — long release history but `main` currently stale; some config fields marked "not implemented" (meta-prompting, resource limits, distributed). **[verified]** |
| Dependency / integration risk | **Higher** — heavy deps + `hydra-core==1.3.2`/`httpx==0.27` pins; Hydra-centric design fights an embedding host. **[verified]** | **Lower** — minimal deps, plain YAML + simple Python API, designed to be `pip install`-and-call. **[verified]** |
| License | Apache-2.0 — fully compatible with Revolver. **[verified]** | Apache-2.0 — fully compatible. **[verified]** |
| Momentum / trajectory | **Rising** — corporate-backed, active today, ICLR 2026, frequent feature additions (headless agents, dynamic islands, prompt evo). **[verified]** | **Plateauing-to-stalling** — huge mindshare but maintenance backlog (75 issues / 42 PRs open, ~2.5 mo since last commit). **[verified]** |
| Algorithmic sophistication | **Higher** — novelty rejection, UCB ensemble, prompt co-evolution, crossover, SLURM, SQLite, cost budgets. **[verified]** | Solid AlphaEvolve baseline (MAP-Elites + islands + cascade + artifacts) but fewer novel mechanisms. **[verified]** |

---

## G. Bottom line

### Verdict table

| Criterion | ShinkaEvolve | OpenEvolve | Winner |
|---|---|---|---|
| Algorithmic richness | UCB ensemble, novelty rejection, prompt co-evo, crossover | MAP-Elites QD, cascade eval, artifacts | **Shinka** |
| Sample efficiency (claimed) | SOTA in ~150 evals (paper) | Self-claimed parity, more evals | **Shinka** (paper, not head-to-head verified) |
| Ease of embedding (deps/config) | Heavy deps, Hydra, pins | Tiny deps, plain YAML + simple API | **OpenEvolve** |
| OpenAI-compatible LLM fit (Revolver constraint) | Supported + extra SDKs | Native, OpenAI-only | **OpenEvolve** |
| Persistence / queryability | SQLite (transactional) | JSON checkpoints | **Shinka** |
| Cluster scale (SLURM) | Native SLURM+Docker/Conda | Local + Docker only | **Shinka** |
| Multi-language breadth | 11 langs first-class | Language-agnostic, fewer examples | ~Tie (Shinka edge) |
| Community / mindshare | 1.2k stars, 22 contributors | 6.5k stars, 45 contributors | **OpenEvolve** |
| Current maintenance velocity | Active today, ~0 issue backlog | Stale 2.5 mo, 75 issues open | **Shinka** |
| API stability | Recent rename, alpha | More versions, some stubs | ~Tie |
| Reproducibility (seeds) | Per-run DB, seedable | `random_seed=42` default, deterministic ensemble | ~Tie |
| Evaluator contract compatibility | `combined_score` + EVOLVE-BLOCK | `combined_score` + EVOLVE-BLOCK | **Tie (key win for dual support)** |

### Recommendation: **Worth supporting ShinkaEvolve as a second backend — but as a deliberate, adapter-isolated addition, not a replacement.**

The two frameworks share enough surface (EVOLVE-BLOCK markers, `combined_score` maximization, initial-program + evaluator pattern) that Revolver's existing abstraction can plausibly accommodate both behind one interface. ShinkaEvolve adds genuinely differentiated capabilities (UCB LLM-ensemble selection, novelty rejection sampling, prompt co-evolution, SLURM, SQLite, USD budget caps) and is the more actively maintained, research-current project.

**Strongest arguments FOR supporting ShinkaEvolve:**
1. **Differentiated, paper-backed algorithms** (novelty rejection + UCB ensemble + prompt co-evolution + crossover) that OpenEvolve lacks — directly relevant to sample efficiency and cost, which matter for an MLOps cost-tracking platform.
2. **Active corporate backing & current momentum** (commits today, ICLR 2026, near-zero issue backlog) vs OpenEvolve's stalling `main` and growing backlog — reduces long-term abandonment risk.
3. **Operationally richer**: native SLURM, SQLite persistence (aligns with Revolver's SQLite/traceability choices per ADR-004), per-run cost budget caps — strong fit for traceability/reproducibility requirements.
4. **Low marginal cost**: shared evaluator/EVOLVE-BLOCK conventions mean a thin adapter, not a rewrite.

**Strongest arguments AGAINST (or to defer):**
1. **Heavy, partly-pinned dependencies** (`hydra-core==1.3.2`, `httpx==0.27`, anthropic/boto3/google-genai, moviepy, seaborn) raise real dependency-conflict risk for an embedding host; likely needs process/venv isolation.
2. **Alpha maturity + recent API rename** (`ShinkaEvolveRunner` unification) signals ongoing churn — an adapter may need frequent updates.
3. **Sample-efficiency superiority over OpenEvolve is unproven head-to-head** — the paper compares against AlphaEvolve budgets, not a controlled OpenEvolve run; benefits are plausible but not independently verified.
4. **Hydra-centric design** partially conflicts with Revolver's own CLI/config model; the `shinka_run` task-dir CLI mitigates this but is the newest, least-stable entry point.

**Suggested path:** Keep OpenEvolve as the default/stable backend (lighter, matches the OpenAI-compatible constraint cleanly). Add ShinkaEvolve behind a feature-flagged adapter, isolated in its own virtualenv/process to contain dependency pins, exposing only the shared evaluator contract. Re-evaluate promoting it once ShinkaEvolve reaches a `0.1.x`/`1.0` with a stabilized API.

---

## Source references

- ShinkaEvolve repo (clone, 2026-06-02): `/tmp/shinka` — `README.md`, `pyproject.toml`, `shinka/core/config.py`, `shinka/database/dbase.py`, `shinka/database/parents.py`, `shinka/core/novelty_judge.py`, `shinka/llm/providers/`, `shinka/utils/languages.py`, `shinka/launch/`, `docs/core_concepts.md`.
- OpenEvolve repo (clone, 2026-06-02): `/tmp/openevolve` — `README.md`, `pyproject.toml`, `openevolve/config.py`, `openevolve/database.py`, `openevolve/controller.py`, `openevolve/api.py`, `openevolve/llm/ensemble.py`, `openevolve/evaluation_result.py`, `openevolve/cli.py`.
- Paper: ShinkaEvolve, arXiv:2509.19349 (Lange, Imajuku, Cetin; ICLR 2026). https://arxiv.org/abs/2509.19349 , https://arxiv.org/html/2509.19349v1
- Sakana AI blog: https://sakana.ai/shinka-evolve/
- AlphaEvolve (DeepMind): https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/
- Third-party: MarkTechPost (2025-09-26), ResearchGate PR_395805982, OpenReview lKEdGCoDNC.
- GitHub API metrics: `gh api repos/SakanaAI/ShinkaEvolve`, `repos/algorithmicsuperintelligence/openevolve`, plus `/contributors`, `/releases`, `/commits`, `/stats/participation`, `search/issues` (all queried 2026-06-02).
