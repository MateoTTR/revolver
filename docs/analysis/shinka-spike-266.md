# Spike #266 — ShinkaEvolve dependency cohabitation & runtime layout

**Date:** 2026-06-07 (session 047)
**Goal (backlog #266):** founding decision for the multi-backend initiative — can Revolver and
ShinkaEvolve be **co-installed** in one environment (`revolver[shinka]` extra), or must
ShinkaEvolve be **isolated** in a separate venv/subprocess? This determines the `launch()` shape
and the whole downstream dependency strategy.

**Method:** throwaway conda env `shinka-spike` (Python 3.12.13), Revolver installed from tag
`v0.12.1`, then `shinka-evolve` (PyPI, `0.0.7`, Apache-2.0) added. Raw logs in
`~/projects/shinka-spike/logs/` (not committed). Runtime layout (`programs.sqlite`, cost fields)
established by **direct DB introspection + source reading** — no live LLM run was needed (and none
was made: no API key spent).

---

## 1. Headline decision: **co-install is VIABLE** ✅

`pip install revolver==0.12.1 shinka-evolve` resolves cleanly. Both the **sequential** install
(Revolver first, then Shinka over it) and the **single-pass combined resolve** (`--dry-run`, =
exactly what `revolver[shinka]` would trigger) succeed with **exit 0** and identical results.
`pip check` → **"No broken requirements found."** Both tools work at runtime in the shared env:
`revolver 0.12.1` runs, `import shinka` works, and the 4 Shinka entry points
(`shinka_launch`, `shinka_run`, `shinka_models`, `shinka_visualize`) are all present.

### What Shinka forces on Revolver's deps

| Package | Revolver constraint | Baseline (Revolver alone) | After Shinka | Verdict |
|---|---|---|---|---|
| `httpx` | `>=0.27` | `0.28.1` | **`0.27.0`** (Shinka pins `httpx==0.27`) | downgraded, still satisfies `>=0.27` ✅ |
| `rich` | `>=13` | `15.0.0` | **`14.3.4`** | downgraded, still satisfies `>=13` ✅ |
| `hydra-core` | (not used by Revolver) | — | `1.3.2` (Shinka hard-pin) | additive, no conflict ✅ |
| `pydantic` | `>=2` | `2.13.4` | `2.13.4` (unchanged) | ✅ |
| `click`, `typer`, `pyyaml` | — | unchanged | unchanged | ✅ |

The two theoretical collision risks flagged in the earlier bottom-up analysis
(`httpx==0.27`, `hydra-core==1.3.2`) **do not materialize today**: Revolver's lower-bound-only
pinning absorbs both. The only cost is that Revolver can no longer float `httpx` to `0.28+` or
`rich` to `15.x` while Shinka is installed.

### The real cost is footprint, not conflict

- Revolver alone: **24** packages.
- Revolver + Shinka: **99** packages (+75 transitive).
- Shinka pulls a heavy grappe: `anthropic`, `google-genai`, `boto3`/`botocore`/`s3transfer`,
  `instructor`, `openai`, `matplotlib`/`seaborn`/`contourpy`/`fonttools`, `moviepy`/`imageio`,
  `scikit-learn`/`scipy`/`numpy`/`pandas`, `networkx`, `radon`, `dill`, `cryptography`, `hydra-core`.

This is why the extra must stay **opt-in** (`pip install revolver[shinka]`), never a default dep.
Revolver's own lightness (ADR ethos) is preserved for the OpenEvolve-only majority.

---

## 2. Recommendation: `revolver[shinka]` extra + **in-process programmatic launch**

Co-install being clean removes the main reason that would have forced subprocess isolation
(dependency pins). Recommended shape:

- **Packaging:** add an opt-in extra `shinka = ["shinka-evolve>=0.0.7"]` in
  `pyproject.toml`, mirroring the existing `openevolve` extra. Default install stays light.
- **Invocation:** call Shinka **programmatically** (its Python API), the same strategy already
  used for OpenEvolve's controller — *not* the Hydra CLI (`shinka_launch`), which is the heaviest,
  least-stable entry point. This keeps `launch()` symmetric across backends.
- **Isolation is NOT required for deps.** It may still be desirable later for *fault* isolation
  (Shinka's heavy stack / long runs), but that is an operational choice, not a packaging
  necessity. Decision: **co-install now; revisit subprocess only if runtime instability appears.**

This unblocks a symmetric `EvolutionBackend.launch()` signature for #267.

---

## 3. Runtime layout established (feeds #267)

### 3.1 Persistence — `programs.sqlite` (verified by instantiating `ProgramDatabase`, no LLM)

A real DB was created from `DatabaseConfig(db_path=...)`. Tables:
`programs`, `archive`, `attempt_log`, `generation_event_log`, `metadata_store`.

`programs` columns (authoritative — matches `shinka/database/dbase.py:420`):

```
id TEXT PK, code TEXT, language TEXT, parent_id TEXT,
archive_inspiration_ids TEXT(JSON), top_k_inspiration_ids TEXT(JSON),
generation INTEGER, timestamp REAL, code_diff TEXT,
combined_score REAL,                      -- shared maximization metric with OE
public_metrics TEXT(JSON), private_metrics TEXT(JSON),
text_feedback TEXT, complexity REAL,
embedding TEXT(JSON), embedding_pca_2d/3d TEXT(JSON), embedding_cluster_id INTEGER,
correct BOOLEAN, children_count INTEGER,
metadata TEXT(JSON),                       -- LLM cost lives here: metadata["llm"]["cost"]
migration_history TEXT(JSON), island_idx INTEGER, system_prompt_id TEXT
```

**Implication for `run population`:** Revolver's OE path parses
`oe-output/checkpoints/checkpoint_N/` JSON files with MAP-Elites `cell_indices`. Shinka has **no
checkpoint dir and no MAP-Elites cells** — population is `SELECT ... FROM programs` keyed by
`island_idx` + `generation`. `parse_population()` must be reimplemented per-backend; the
`cell_indices` field has no Shinka analog (island_idx is the closest concept).

### 3.2 Cost/token tracking — native, proxy-blind (confirms hard problem #2)

Shinka computes cost **per-provider in-process** (`shinka/llm/providers/pricing.py:calculate_cost`),
including for **local OpenAI-compatible endpoints** (`local_openai.py:_extract_costs(model,
in_tokens, out_tokens)`). Per-call cost is stored in each program's `metadata["llm"]["cost"]` and
surfaced as an `api_costs` series (`shinka/plots/plot_costs.py`). `EvolutionConfig.max_api_costs`
is a native **USD budget cap**.

→ Revolver's HTTP `TokenCountingProxy` **cannot see** these calls (Shinka uses native
`anthropic`/`google-genai`/`boto3`/`openai` SDKs, not a proxied OpenAI base URL). For the Shinka
backend, token/cost must be read **from `programs.sqlite` after the run**, not from the proxy.

### 3.3 Evaluator contract (confirms hard problem #1)

`shinka/core/wrap_eval.py` writes results to a `results_dir` as **`metrics.json`** + **`correct.json`**
(filesystem), vs OpenEvolve's **in-process dict return**. The backend adapter must bridge Revolver's
snapshot-evaluator contract to Shinka's file-based one.

### 3.4 Config surface (`EvolutionConfig`, feeds the param-surface question of #267)

Programmatic entry is `EvolutionConfig` (single dataclass, no Hydra needed). Notable fields and how
they map to Revolver's current OE-specific surface:

| Shinka field | Meaning | Revolver mapping |
|---|---|---|
| `num_generations` (50) | iterations | ↔ Revolver `--iterations` (neutral) |
| `llm_models` (list) + `llm_dynamic_selection='ucb'` | **bandit** ensemble (UCB/Thompson) | ✗ Revolver ensemble is **weighted** — different selection model |
| `llm_kwargs` | per-model temperature etc. | ↔ `--temperature`, but **per-model** in Shinka vs global in Revolver |
| `init_program_path` | initial program | ↔ Revolver snapshot `initial_program.py` |
| `results_dir` | output dir | ↔ Revolver run dir |
| `language` ('python') | **native multi-language** | Revolver hardcodes Python (backlog #132) |
| `max_api_costs` | USD budget cap | ✗ no Revolver analog (new capability) |
| `evolve_prompts`, `embedding_model`, `max_novelty_attempts` | prompt co-evolution, novelty rejection | ✗ Shinka-only — must be "per-backend extras" |

This confirms #267's framing: define a **neutral subset** (iterations, initial program, results dir,
temperature, combined_score) and **per-backend extras** (OE: `--rewrite-mode`/`--parallel`;
Shinka: bandit selection, `max_api_costs`, prompt evolution, novelty).

---

## 4. Conclusions & handoff to #267

1. **Founding decision answered:** co-install is clean → ship a `revolver[shinka]` opt-in extra,
   invoke Shinka programmatically in-process. No subprocess isolation needed for dependencies.
2. **Footprint is the only real tax** (+75 deps) → keep the extra strictly opt-in.
3. The three hard problems from the bottom-up analysis are all **confirmed empirically**:
   evaluator contract (file `metrics.json`/`correct.json` vs in-process dict), cost tracking
   (native/proxy-blind → read `programs.sqlite`), population/checkpoint (SQLite `programs` table,
   no MAP-Elites cells).
4. **Not done (deferred, by design):** a live `examples/circle_packing` evolution run — it needs
   API credits and only adds confirmation of the already-introspected layout. Can be run during
   #267/P2 (Shinka MVP) when a real backend integration exists to exercise.

Next: **#267 top-down analysis** — walk each Revolver CLI command for the engine-coupled vs
engine-neutral partition, finalize the `EvolutionBackend` interface against these findings, and
extend to the full engineering impact (specs/design/validation) + a preliminary sprint plan.

### Reproduction

```bash
mamba create -y -n shinka-spike python=3.12 && conda activate shinka-spike
pip install "revolver @ git+file:///path/to/revolver@v0.12.1"   # 24 pkgs
pip install shinka-evolve                                        # +75 pkgs, downgrades httpx->0.27, rich->14.x
pip check                                                        # No broken requirements found
```
