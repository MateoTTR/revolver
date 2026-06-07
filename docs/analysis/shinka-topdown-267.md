# Top-Down Analysis #267 — Pluggable Evolution Backend (CLI-first)

**Status:** Draft — top-down complement to the bottom-up impact study (no implementation)
**Date:** 2026-06-07 (session 047)
**Revolver version:** v0.12.1 working tree (`develop`)
**Companions:** [shinka-backend-impact.md](shinka-backend-impact.md) (bottom-up, from `infra/`),
[shinka-vs-openevolve.md](shinka-vs-openevolve.md) (comparison), [shinka-spike-266.md](shinka-spike-266.md)
(dependency spike — co-install verdict).

> **Goal:** walk Revolver **from the CLI down** to (a) confirm the engine-coupled vs
> engine-neutral command partition, (b) finalize the `EvolutionBackend` interface against real
> command needs, (c) resolve the LLM-registration and parameter/config-surface questions, then
> (d) extend to the **full engineering impact** (specs / design / validation) and (e) a
> **preliminary incremental sprint plan**. Output = material ready to feed the project agents (#268).

The bottom-up impact doc already established the OE coupling map (§1.1), the concept-mapping table
(§3.1), a draft interface (§3.2), ripple effects (§3.3), phasing (§4.3) and risks (§4.5). This doc
does **not** repeat that; it validates and sharpens it from the command surface and broadens to
specs/validation.

---

## 1. CLI partition — engine-coupled vs engine-neutral (CONFIRMED, with refinements)

Walking all ~44 leaf commands (`cli/__init__.py` tree → `cli/*.py` → `core/*.py`), the partition is
**much cleaner than feared**: the engine coupling is concentrated in 4 commands plus 4 single-call
touch points. **~82% of the CLI surface needs no backend awareness.**

### 1.1 Engine-COUPLED (launch the engine or read its on-disk layout)

| Command | Core fn | Coupling (file:line) |
|---|---|---|
| `run` (launch) | `core.run.launch_run` | imports `OpenEvolveRunner`/`build_config`/`RunOutput`/`resolve_api_keys`/`revolver_env` (`core/run.py:68-78`); token proxy (`:94`); `generate_wrapper`/`_WRAPPER_TEMPLATE` (`:2011`); post-run `find_latest_checkpoint`/`count_valid_programs` (`:903`); writes `programs/rank-N.py` from OE output (`:2181-2215`) |
| `run resume` | `core.run.resume_run` | `find_latest_checkpoint(parent)` (`:1296`); copies `oe-checkpoint` (`:1303-1305`); feeds checkpoint to runner (`:1457`) |
| `run status` (**active runs only**) | `core.run.get_run_status` | live checkpoint read `find_latest_checkpoint`+`count_valid_programs`+`read_checkpoint_best_score` (`:1712-1715`). The idle/latest branch (`:1740-1777`) is pure DB → neutral. |
| `run population` | `core.run.get_population` | `find_latest_checkpoint` (`:2117`) + `parse_population` reading `checkpoint_N/programs/*.json` (`:2124`, `:2092-2093`) |

### 1.2 Partially-coupled (one engine-presence touch point each — small backend-aware shims)

| Command | Touch point (file:line) | Needed change |
|---|---|---|
| `doctor` | `core/doctor.py:264` `_check_openevolve()` hard-checks `openevolve` package | dispatch by active/installed backend(s) |
| `setup` | install plan derives from doctor report (`core/setup`) | add Shinka install entry (`revolver[shinka]`) |
| `project init` | writes OE-shaped `config.yaml` template (`core/project.py:94-114,181-189`) | per-backend template (or backend-neutral default) |
| `problem version create` | `validate_oe_config()` on snapshot `config.yaml` (`core/problem.py:226-228`) | dispatch to per-backend validator |

### 1.3 Engine-NEUTRAL (the entire downstream surface — untouched by the refactor)

All of `llm` (10), `dataset` (5), `solution` (8), `eval` (2), `benchmark` (5), `problem test`,
`problem version list/delete`, **plus** `run list`, `run info`, `run delete`, `run cleanup`. These
touch only `infra/db.py` / `infra/store.py` / the snapshot evaluator / already-extracted program
files.

### 1.4 Refinements / surprises vs the prior hypothesis

- **`run cleanup` is NEUTRAL** (hypothesis said coupled): `detect_zombie_runs` only checks DB
  `status='running'` + lock-file PID liveness (`core/run.py:1853-1904`).
- **`run status` is only *conditionally* coupled** — neutral for a finished run; the engine read is
  only on the live-progress path.
- **`run info` is NEUTRAL** — reads the Revolver-written **manifest** (`read_run_manifest`,
  `core/run.py:1951`), not the checkpoint — unlike its sibling `run population`.
- **`run delete` is NEUTRAL** — `delete_run_dir` removes the run dir wholesale (`:2282`), no layout
  parsing.
- **The clean post-engine boundary:** once `launch_run` writes `programs/rank-N.py` + the manifest,
  *everything downstream is engine-agnostic by construction*. `solution extract` only promotes the
  Revolver-owned `programs/rank-N.py` file to a DB entry (`core/solution.py:352`); it never reads a
  checkpoint. This is the single most important structural fact for sizing: **the backend boundary
  is `launch_run` writing Revolver-owned artifacts.**

**Sizing implication:** the refactor = (a) a backend abstraction behind *launch / resume /
live-progress-read / population-parse*, concentrated in `core/run.py` + `infra/openevolve.py`, plus
(b) four small backend-aware shims (doctor, setup, project-init, version-create). The ~36 neutral
commands are not touched.

---

## 2. Finalized `EvolutionBackend` interface (validated against command needs)

The draft (impact §3.2) is sound. Validated against §1, the interface must serve exactly: `run`
(build/validate/wrapper/launch + token strategy), `run resume` (resume), `run status` active
(read_progress/count_valid), `run population` (parse_population), `--dry-run` (resolved_config),
`doctor`/`setup` (is_available), `problem version create` (validate_config), `project init`
(config_template). That yields the following refinement.

### 2.1 Refinements over the draft

1. **`resume()` is a first-class method, not a flag on `launch()`.** OE resumes by copying a
   checkpoint dir + passing `checkpoint_path`; Shinka resumes by reusing the same `results_dir`
   (DB-driven, no checkpoint arg). These are different enough mechanisms (impact §2.5) that a
   distinct `resume(spec, parent_run_dir)` keeps each backend honest. `BackendRunSpec.resume_from`
   stays as the data carrier; the dispatch is an explicit method.
2. **Add `config_template() -> str`** to serve `project init` (each backend scaffolds its own
   `config.yaml`).
3. **Split live-progress from population.** `run status` (active) needs a cheap
   `read_progress(run_dir) -> (iterations_done, best_score)`; `run population` needs the full
   `parse_population(run_dir)`. Keep both (the draft already had `read_progress` + `parse_population`).
4. **`capabilities() -> BackendCapabilities`** — a new method exposing what the backend can/can't do
   (global-seed reproducibility, MAP-Elites cells, native cost tracking, multi-language, bandit
   ensemble). This drives honest CLI/docs behavior (e.g. warn that `--seed` has no effect on Shinka)
   instead of silent divergence. This is the cleanest way to honor the "document, don't paper over"
   stance on reproducibility (R3).
5. **Token strategy stays a backend decision:** `wants_http_proxy()` + `collect_token_usage(run_dir)`
   (OE: proxy=True, parse OpenAI usage; Shinka: proxy=False, read `programs.sqlite` cost).

### 2.2 Proposed interface (refined)

```python
# infra/backends/base.py
@dataclass
class BackendCapabilities:
    global_seed: bool            # OE True / Shinka False (search-level reproducibility)
    map_elites_cells: bool       # OE True / Shinka False (no feature grid; island_idx only)
    native_cost_tracking: bool   # OE False (proxy) / Shinka True (DB)
    multi_language: bool         # OE False / Shinka True
    ensemble_model: str          # "weighted" (OE) | "bandit" (Shinka)

class EvolutionBackend(Protocol):
    name: str                                       # "openevolve" | "shinka"
    def capabilities(self) -> BackendCapabilities: ...
    def is_available(self) -> tuple[bool, str | None]: ...      # doctor/setup
    def config_template(self) -> str: ...                       # project init
    def validate_config(self, cfg: Path | dict) -> list[str]: ...   # problem version create
    def build_config(self, spec: BackendRunSpec) -> dict[str, Any]: ...
    def resolved_config(self, cfg: dict[str, Any]) -> ResolvedConfig: ...   # dry-run
    def generate_wrapper(self, spec: BackendRunSpec) -> Path: ...
    def launch(self, spec, cfg, on_progress=None) -> BackendRunResult: ...   # run
    def resume(self, spec, cfg, parent_run_dir, on_progress=None) -> BackendRunResult: ...  # run resume
    def read_progress(self, run_dir: Path) -> tuple[int | None, float | None]: ...  # run status (active)
    def parse_population(self, run_dir: Path) -> list[dict[str, Any]]: ...   # run population
    def count_valid(self, run_dir: Path) -> int | None: ...
    def wants_http_proxy(self) -> bool: ...
    def collect_token_usage(self, run_dir: Path) -> TokenUsage | None: ...

def get_backend(name: str) -> EvolutionBackend: ...   # factory
```

`BackendRunSpec` / `BackendRunResult` as in impact §3.2 (engine-neutral spec in, neutral result
out). `OpenEvolveBackend` wraps the existing `infra/openevolve.py` ~1:1; `ShinkaBackend` is new.

---

## 3. LLM-registration decision (RESOLVED)

**Decision: NO registry schema change.** Every datum Shinka needs (`model`, `source`, `base_url`,
`api_key_env`, `temperature`, `max_tokens`, the ensemble member set) already exists in `LLMEntry` /
`EnsembleEntry` / `EnsembleMember` (`models/llm.py:37-48,118-121,135-137`). The registry is already
backend-agnostic *storage*; OE consumes it via a build-time *projection*
(`_build_ensemble_llm_config`, `resolve_api_keys`). Shinka is simply a **different projection of the
same fields**, living in a sibling `infra/backends/shinka.py:build_config`. `models/llm.py` and
`core/llm.py` are untouched.

- **Local (Ollama) → Shinka** is fully derivable:
  `local/{model}@{base_url}?api_key_env={api_key_env or "OLLAMA_API_KEY"}`. `base_url` already
  defaults to `http://localhost:11434/v1` at registration (`core/llm.py:200`). Micro-gap: local
  entries have `api_key_env=None` today → the adapter synthesizes a default env name (no schema
  change; the field already accepts a value if a user sets one).
- **Weighted ensemble → bandit is lossy**: Shinka selects via `llm_dynamic_selection`
  (UCB/Thompson/fixed), so `EnsembleMember.weight` and per-member temperature/max_tokens overrides
  are dropped. Recommended default: `"fixed"` for single-LLM, `"ucb"` for true ensembles. The
  adapter must **warn** ("weights ignored; Shinka uses bandit selection"), mirroring the existing
  weight-sum warning (`core/llm.py:743-748`).
- **Provider routing** needs no hint: Shinka infers provider from the model string; Revolver's
  stored `provider`+`source` suffice.
- **Optional, deferred (Tier 1):** an additive nullable `dynamic_selection` on `EnsembleEntry` so a
  user can pin the bandit strategy. Only if users ask. Do **not** add a portable `weight` concept.

`timeout_s` and the per-mtok cost fields are *output-side losses* on the Shinka path (Shinka tracks
cost natively from `pricing.csv`); they are not registry gaps.

---

## 4. Parameter / config-surface decision (RESOLVED)

Replace the OE-shaped `ResolvedOEConfig` (`models/run.py:163-193`) with a neutral `ResolvedConfig`
+ a `backend_extras` escape hatch. Neutral subset = concepts that survive renaming across both
engines; everything PARTIAL/OE-ONLY/SHINKA-ONLY goes to extras.

**Neutral:** iterations (`max_iterations`/`num_generations`), num_islands, temperature, language,
llm_models (shape), config_overrides, initial-program, results-dir, system-prompt, combined_score.
**PARTIAL** (neutral concept, different shape → carry in extras with a note): temperature
(global vs per-model `llm_kwargs`), parallel (`parallel_evaluations` vs 3 job-slot pools),
diff/rewrite (`diff_based_evolution` bool vs `patch_types` list), random seed (global vs per-eval).
**OE-only:** checkpoint_interval, feature_dimensions/bins, max_code_length, population_size,
cascade_evaluation. **Shinka-only:** max_api_costs (USD cap), archive_size,
parent_selection_strategy, archive_criteria, evolve_prompts, novelty (embedding_model), meta LLM,
`cross` patch type, job_type/SLURM.

```python
class ResolvedConfig(BaseModel):
    backend: str                                   # "openevolve" | "shinka"
    iterations: int | None = None
    num_islands: int | None = None
    temperature: float | None = None
    language: str | None = None
    llm_models: list[dict[str, Any]] | None = None # {name, weight?, temperature?, max_tokens?}
    config_overrides: dict[str, Any] | None = None
    backend_extras: dict[str, Any] = Field(default_factory=dict)
```

Ship the `dict` form first (minimal churn, matches existing dict-shaped `config_overrides`); promote
to typed `OEExtras`/`ShinkaExtras` once a second backend exists. `RunResult.resolved_config`
(`models/run.py:225`) changes type; the dry-run renderer (`cli/run.py:160-197`) iterates neutral
fields + a generic `backend_extras` loop.

**CLI flags under `--backend`** (new flag, defaults `openevolve`): `--iterations` neutral;
`--temperature`→`llm_kwargs` default (warn if bandit ensemble); `--parallel`→`max_evaluation_jobs`
(warn: only sets eval pool); **`--rewrite-mode`→`patch_types=["full"]` + info that `max_code_length`
has no Shinka analog (map-with-warn, don't error — avoid breaking scripts)**;
`--config-override`→validate against Shinka dataclasses instead of OE. Add a `validate_shinka_config()`
sibling to `validate_oe_config()`. The OE-hardcoded help/stderr copy in `cli/run.py` (lines 44, 57,
78, 92, 138, "Running OpenEvolve evolution…") must be made backend-aware.

---

## 5. Full engineering impact (specs / design / validation)

The bottom-up doc covered code ripple (§3.3) and design docs (§4.4). This adds the **specs and
validation** dimensions with concrete IDs.

### 5.1 Specifications (FR/NFR)

| Doc | Change |
|---|---|
| `specifications.md` §1 Key Constraints | "OpenEvolve-based" → "evolution-backend-based (OpenEvolve default, ShinkaEvolve optional)". Add backend capability matrix concept. |
| **New FR-RUN-036+** | `revolver run --backend {openevolve,shinka}`; default `openevolve`; surfaced in `run info`/`run list`/dry-run; stored in run record. |
| **New FR-RUN-037** | Backend capability differences are reported (e.g. `doctor`, dry-run); unsupported flags warn rather than silently no-op. |
| FR-RUN-019 (post-run eval) | Already backend-neutral (reuses snapshot evaluator) — confirm wording stays engine-agnostic. |
| FR-RUN-023 (dry-run resolved config) | Reword to neutral `ResolvedConfig` + backend extras. |
| FR-RUN-024 (resume copies wrapper) | Generalize: "resume reuses the parent's evaluator and backend state" (OE copy-checkpoint vs Shinka reuse-`results_dir`). |
| FR-RUN-028..030 (token/cost) | Add: cost/token source is backend-defined (OE proxy vs Shinka native DB); `TokenUsage` semantics may be USD-cost-primary on Shinka. |
| FR-RUN-031/032 (failure handling) | Backend-neutral already (status + `run-error.log`) — keep, ensure exceptions from either engine map identically. |
| **NFR-023** ("OpenEvolve config stored verbatim") | Generalize to "the backend config used for a run is stored verbatim" (neutralize the OE mention). |
| **NFR Reproducibility §3.3** | Add a caveat NFR: search-level reproducibility (same config+seed ⇒ same run) is a **backend capability**; honored by OE (`random_seed`), **not guaranteed** by Shinka (no global search seed — impact R3). This is a softening of a current MUST — needs explicit sign-off in #268. |
| spec-llm.md | Note the per-backend projection (weighted→bandit lossiness) as informational; no command change. |

**The one spec tension to escalate (#268):** Revolver's "Reproducibility: runs must be reproducible
given the same config and seed" (CLAUDE.md Key Constraints + NFR §3.3) **cannot be fully honored on
Shinka**. Options: (a) scope the guarantee per-backend via `capabilities()`, (b) keep it MUST for OE
only. Recommend (a).

### 5.2 Design / architecture

| Doc | Change |
|---|---|
| **New ADR-007** "Pluggable evolution backend" | the abstraction, the factory, the capability matrix, the decision to read Shinka cost from the DB (not the proxy), and the reproducibility scoping. |
| `architecture.md` §3 package tree | add `infra/backends/{base,openevolve,shinka}.py`; note `core/run.py` becomes backend-mediated. |
| **DES-005** (run orchestration) | orchestration becomes backend-mediated; `resume` semantics per backend; manifest `backend` field; `ResolvedConfig` neutralization; token-strategy per backend. |
| **DES-006** (eval loop) | evaluator contract per backend: OE in-process `evaluate(program_path)->dict` vs Shinka subprocess CLI writing `metrics.json`/`correct.json`; how `evaluate_instance()` maps to `run_shinka_eval`. |
| ADR-006 (instance injection) | still valid for OE; note Shinka uses the same env-var/snapshot inputs but a different (file-based) wrapper output. |
| DES-001 (data model) | `runs.backend` column (+ migration). |

### 5.3 Validation

| Doc | Change |
|---|---|
| `validation.md` (strategy) | add a "backend matrix" axis: engine-coupled tests (L2-OE today) become parameterized per backend; engine-neutral tests run once (they don't depend on the engine). A new **L2-Shinka** contract-test track mirroring **L2-OE**. |
| `val-integration-tests.md` | the ~36 neutral command tests are unaffected; the `run`/`resume`/`status`/`population` matrices duplicate per backend; new Shinka fake/mocks (mock `ShinkaEvolveRunner` + a fixture `programs.sqlite`). |
| `val-e2e-tests.md` | one L3 Shinka happy-path mirroring the OE one (mock LLM or tiny local). |
| `traceability-matrix.md` | new rows for FR-RUN-036/037; update FR-RUN-023/024/028-030/NFR-023 rows; add the reproducibility-capability caveat. |

### 5.4 Code ripple (delta on top of impact §3.3)

Confirmed minimal beyond `core/run.py` + `infra/openevolve.py`: the 4 partial touch points
(doctor/setup/project-init/version-create) each need a ~few-line backend dispatch. The neutral
downstream (`solution`/`eval`/`benchmark`/`run list|info|delete|cleanup`) needs **no change** — a
strong de-risk for the refactor's blast radius.

---

## 6. Preliminary incremental dev + validation sprint plan

Sequenced after #268 (formalization). Each phase ships green and independently valuable. Sizing uses
the project's historical sprint cadence.

### Sprint S13 — Backend abstraction refactor (no behavior change) — **P1**
- `infra/backends/{base.py,openevolve.py}`: define `EvolutionBackend`/`BackendRunSpec`/
  `BackendRunResult`/`BackendCapabilities`/`get_backend`; wrap existing OE code as
  `OpenEvolveBackend` (move, don't rewrite).
- `core/run.py`: route launch/resume/status/population/token through `backend.*`.
- `models/run.py`: neutral `ResolvedConfig` + `backend_extras`; add `backend` field to
  config/manifest/summary/info.
- DB migration v9: `runs.backend TEXT NOT NULL DEFAULT 'openevolve'`.
- 4 shims: doctor/setup/project-init/version-create dispatch by backend.
- **Validation:** full existing L2/L3 suite stays green (proves neutrality); add tests asserting
  `backend='openevolve'` default end-to-end. **Exit criterion: zero behavior change.**

### Sprint S14 — ShinkaEvolve MVP — **P2**
- `pyproject.toml`: opt-in `shinka = ["shinka-evolve>=0.0.7"]` extra (spike #266 ✅ co-install
  viable).
- `infra/backends/shinka.py`: `build_config` (single-LLM, `llm_dynamic_selection="fixed"`,
  Python, `diff`+`full`); `generate_wrapper` → Shinka CLI `evaluate.py` adapting
  `evaluate_instance()` over the dataset via `run_shinka_eval`; `launch` via `ShinkaEvolveRunner`;
  read best/population/valid/cost from `programs.sqlite`; `wants_http_proxy()=False`.
- CLI: `run --backend shinka`, dry-run, doctor check.
- **Out of MVP:** ensemble/bandit, prompt evolution, novelty, multi-language, SLURM, full
  token-count parity, search-level reproducibility.
- **Validation:** new L2-Shinka contract tests (mock runner + fixture `programs.sqlite`); one L3
  Shinka happy path; the eval-contract correctness test (most likely silent-bug source, impact R4).

### Sprint S15 — Parity push + hardening — **P3**
- ensemble→bandit mapping (warn on weight loss), multi-language passthrough (ties to backlog #132),
  richer cost/token mapping, resume parity (`results_dir` clone), `max_api_costs` flag.
- Docs: ADR-007 finalized, DES-005/006 revisions, guides, spec/traceability updates.
- **Validation:** full L2/L3 matrices per backend; benchmark cross-backend comparison sanity.

**Critical-path risks to carry (from impact §4.5):** R4 (Shinka `evaluate.py` correctness) is the
top silent-bug risk → front-load its tests in S14. R2 (token/cost model mismatch) shapes
`benchmark` comparisons → decide `TokenUsage` semantics in ADR-007. R3 (reproducibility) → resolve
the spec tension (§5.1) before S13.

---

## 7. Handoff to #268 (formalization via project agents)

Decisions ready to formalize:
1. **Co-install** (`revolver[shinka]` extra, in-process programmatic launch) — from #266.
2. **No LLM-registry schema change** — §3.
3. **Neutral `ResolvedConfig` + `backend_extras`** — §4.
4. **Refined `EvolutionBackend` interface** (with `capabilities()`, first-class `resume()`,
   `config_template()`) — §2.
5. **CLI partition** confirms the refactor blast radius is `core/run.py` + `infra/openevolve.py` +
   4 small shims — §1.

Open questions for the user / agents:
- **Q1 (spec sign-off):** scope the reproducibility guarantee per-backend (recommend yes) — §5.1.
- **Q2 (`TokenUsage` semantics):** on Shinka, is USD cost the primary field and token counts
  best-effort? (recommend yes) — affects `benchmark`.
- **Q3 (extras typing):** ship `backend_extras: dict` first, type later? (recommend yes) — §4.

Next: drive #268 with the agents — ADR-007 (new), spec updates → spec-reviewer; DES-005/006 +
architecture revisions; validation updates → validation-reviewer; sprint structuring → scrum-master;
user-doc pass → doc-reviewer. Then implement P1→P2→P3 (S13→S14→S15).

---

## Appendix — investigation method

Top-down walk of `cli/__init__.py` → `cli/*.py` → `core/*.py` (all ~44 leaf commands), three
parallel deep-dive agents (CLI partition / LLM-registration / param-surface) grounded in the
v0.12.1 tree, synthesized against specs (`FR-RUN-001..035`, NFR §3.3), design (DES-005/006, ADR-006)
and validation (traceability matrix). Shinka facts reuse the verified bottom-up impact doc and the
#266 spike (no new Shinka clone needed).
