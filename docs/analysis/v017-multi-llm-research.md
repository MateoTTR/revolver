# v0.17 Multi-LLM — Source-Grounded Research & Design Corrections

**Date**: 2026-07-01 (session 055) · **Status**: input for the ADR-007 addendum + sprint-017
**Method**: 7-agent research + adversarial verification workflow (run `wf_0f3f3069-391`, 434k subagent tokens).
Full raw findings archived at the task output for this session; this doc is the distilled, decision-focused digest.
Sources read: ShinkaEvolve 0.0.7 (`envs/shinka-spike/.../shinka`), OpenEvolve (`envs/revolver/.../openevolve`),
Revolver `src/` + `docs/`.

---

## 0. Two design-changing facts (adversarially verified)

### FACT A — Per-member `reasoning_effort` is **OE-only**. On Shinka it is global. (V1 verdict: **REFUTED**, global-only)

Shinka's `reasoning_efforts`, `temperatures`, and `max_tokens` are **single global sampling pools** on the LLM
client, not per-model. The bandit picks only the *model* (one-hot `model_sample_probs`); the effort is then drawn
by `random.choice(reasoning_efforts)` **independent of which model was selected** (`shinka/llm/kwargs.py:107`;
client stores one value `llm/llm.py:349`; no model→effort keying anywhere).

- **OpenEvolve**: `LLMModelConfig.reasoning_effort` is a **per-model field** (`config.py:80`), inherited-if-None
  from the top-level `llm.reasoning_effort` (`config.py:180-190`). Per-member effort **is** honorable.
- **Shinka**: only one global effort (or a global pool sampled at random). Per-member is **not expressible** via
  public config (would need a fork/monkeypatch — dropped per the robustness rule).
- **Extra Shinka caveat**: effort only applies to models Shinka classes as reasoning models (present in its
  `pricing.csv`). **local/bridge models → `is_reasoning_model=False` → effort forced to `"disabled"`** regardless.
  So for the demos' Claude-Max-via-bridge fleet, `reasoning_effort` on the **Shinka** path is a full no-op.

**Design consequence**: `--reasoning-effort` is a neutral registry field; the OE backend maps it **per member**,
the Shinka backend maps it to the **single global** `llm_kwargs.reasoning_efforts` and **warns** if members
disagree (and warns that it's inert for local endpoints). This is exactly the honest-divergence job of
`capabilities()`.

### FACT B — Ensemble weights seed the bandit **only in `fixed` mode**. (V2 verdict: PLAUSIBLE + GAP 1)

`prior_probs` (the positional weight vector, aligned to `llm_models` order, renormalized to sum 1) exists **only on
`FixedSampler`** (`prioritization.py:956`). `AsymmetricUCB` and `ThompsonSampler` have **no `prior_probs` and no
`**kwargs`** → passing it raises `TypeError` (`prioritization.py:297-314`, `:1107-1121`).

- Member weights → `prior_probs` works **only under `--selection fixed`**.
- Under `ucb`/`ucb1`/`thompson` the arms are learned adaptively **from a uniform start** — weights **cannot** be
  seeded and are **ignored** (that is the point of the bandit).

**This corrects the earlier synthesis** ("weights become the bandit's initial priors" — false). So `--llm-weight`
and registry weights carry across **OE-weighted** and **Shinka-fixed** only; under Shinka bandit modes they are
inert → **warn**.

### Supporting facts
- `llm_dynamic_selection` string values: `fixed`, `ucb`, `ucb1` (**alias** → same `AsymmetricUCB`, no separate
  class), `thompson`, `None` (uniform). Unknown → `ValueError`. Mapped at `async_runner.py:361-383`.
- `llm_dynamic_selection_kwargs` is **spread verbatim into the chosen sampler's constructor** → Revolver must
  **branch the kwargs per sampler** (never send a union). Shinka's own default `{cost_aware_coef: 0.5}` is valid
  for ucb/ucb1, silently ignored by fixed, and **TypeErrors under thompson**.
- `cost_aware_coef` (M4) is **inert when costs are undifferentiated** (all-local/bridge → cost 0 → no effect on
  argmax). Defaulting it to 0 (M4) is correct but for the bridge fleet it changes nothing anyway. Low urgency.
- OE ensemble is **static weighted-random**, weights auto-normalized, one model sampled per generation, **no
  bandit** (`openevolve/llm/ensemble.py:29-75`). Separate judge ensemble = `evaluator_models`, gated by
  `use_llm_feedback` (default False) — out of v0.17 scope (flag as known gap, M2).

---

## 1. Corrected multi-LLM semantics (accurate mapping table)

| Neutral lever | OpenEvolve (`ensemble_model="weighted"`) | ShinkaEvolve (`ensemble_model="bandit"`) |
|---|---|---|
| ensemble members | `llm.models[]` weighted sampler | `evo_config.llm_models[]` |
| `--selection fixed` | the only mode (implicit) | `FixedSampler`, weights → `prior_probs` (**honored**) |
| `--selection ucb`/`ucb1`/`thompson` | **rejected** (exit clear: weighted only) | bandit; **weights ignored** (uniform start) → warn |
| `--llm-weight m=w` | honored (patches `weight`) | honored **only under `fixed`**; inert under bandit → warn |
| `--selection-kwarg k=v` | N/A | folded into the **selected** sampler's kwargs (branch per sampler) |
| `--reasoning-effort` (per-member) | **honored per member** (`LLMModelConfig.reasoning_effort`) | **global only** (`llm_kwargs.reasoning_efforts`); warn if members differ; inert for local/bridge |

The headline demo comparison is therefore: **OE-weighted** vs **Shinka-fixed** (same weights, apples-to-apples) vs
**Shinka-ucb** (adaptive, weights deliberately ignored — the differentiator).

---

## 2. Insertion map (Revolver `src/`) — from F3

- **`models/llm.py`**: add `reasoning_effort: str|None` to `LLMEntry` (after L43) and `EnsembleMember` (after L117).
- **`infra/backends/base.py`** (BackendRunSpec, L85-131 — already carries `ensemble: EnsembleEntry|None` at L128):
  add `selection`, `selection_kwargs: dict|None`, `llm_weight_overrides: dict|None` after L128.
- **`models/run.py`**: mirror `selection`/`selection_kwargs`/`llm_weight_overrides` on `RunConfig` (after L75);
  `ResolvedConfig` (L172-197) already exposes `llm_models`/`backend_extras` for dry-run surfacing.
- **`cli/run.py`** (`run_launch` callback L29-100): add `--selection` / `--selection-kwarg` (list) / `--llm-weight`
  (list) after L99; thread into `RunConfig` at L123-135. **Both** `launch_run` (spec build L596-607) **and**
  `resume_run` (L1307-1320) must copy the new fields.
- **`cli/llm.py`**: add `--reasoning-effort` to `llm add` (after L98) and `ensemble add` (after L596); thread
  through `core/llm.register_llm` (L131) and `add_ensemble_member` (L689) → DB.
- **Shinka mapping** (`infra/backends/shinka.py`): replace the ensemble hard-raise (L614-619); generalize the
  single-LLM projection (L633-638) to loop members → `llm_models`, set `llm_dynamic_selection` from `--selection`,
  map weights → `prior_probs` **only for fixed**, branch `selection_kwargs` per sampler, write global
  `llm_kwargs.reasoning_efforts` (near L646).
- **OE mapping** (`infra/backends/openevolve.py`): thread `weight_overrides` + per-member `reasoning_effort` through
  `_build_ensemble_llm_config` (L355-423, weight set at L399, add effort block after L419) and `build_config`
  (L426-438, call site L509); `--selection` non-fixed → warn/reject (capabilities `weighted`, L1336).
- **`--config-override` confirmed cannot reach array members** (`_set_nested` L683-693, no `[i]` indexing; shared by
  both backends) → per-member weight/effort **must** use the dedicated flags. Reinforces the "config-override is an
  exception" principle.
- **DB migrations** (`infra/db.py`): new column `reasoning_effort` on `llms` (after L172) and
  `ensemble_members` (two DDL copies: L181-189 and migration copy L546-552). Current head = v11 → new **v12** (+v13
  if kept separate per table).

---

## 3. Correctness slice B1/B2/B7 — from F4

- **B1** (OE wrapper agg crashes on non-numeric metric): fix = copy the numeric guard from `shinka.py:322-331`
  into the OE `_WRAPPER_TEMPLATE` loop (`openevolve.py:1140-1144`) + harden the `combined_score` mean (L1133).
  Preserve the template's `{{`/`}}` brace escaping. **No existing test execs the OE wrapper aggregation** → add one
  (generate wrapper, feed an instance returning `{'combined_score':0.5,'error':'boom'}`, assert numeric result, no
  crash). Guard idiom `isinstance(x,(int,float)) and not isinstance(x,bool)` already used 3× in the OE module.
- **B2** (OE post-run teardown hang): symmetric to #224. Wrap `OpenEvolveRunner.run` (`openevolve.py:301-349`,
  currently no `finally`) in try/finally; reuse `_current_child_pids`/`_reap_run_children` from `shinka.py:1448-1506`
  (hoist to `base.py` to avoid duplication) + an OE-specific `_shutdown_runner` (controller's executor via guarded
  `getattr`, **`shutdown(wait=False)` + `contextlib.suppress`** — else reintroduces the #159 hang). Result is
  persisted before teardown (safe to reap). Test template: `tests/integration/test_shinka_shutdown.py` →
  `test_openevolve_shutdown.py`.
- **B7** (OE best of a killed run): **premise corrected** — Shinka also only materializes `best/` after `run()`
  returns; what survives is the DB. True OE analogue: the latest `oe-output/checkpoints/checkpoint_N/` survives
  (`best_program_id` in `metadata.json` + `programs/{id}.json` code). Fix: let `solution extract` recover from the
  latest checkpoint for `interrupted`/`failed` runs **behind an explicit flag** (`--from-checkpoint`), routed via an
  `EvolutionBackend` method (backend-neutral). **Must consciously revise the F3 decision**:
  `test_extract_rejects_interrupted_run` (`test_solution.py:643`) currently *asserts* interrupted runs are NOT
  extractable — update it (default still rejects; flag path succeeds). Gate cleanly on "no checkpoint yet" (too
  short to checkpoint).

---

## 4. Spec/design/validation edit surface — from F5

- **Numbering**: next FR-RUN = **049/050/051** (042 stays a permanent gap). Next FR-LLM = **026**. New FR-EVL number
  to confirm from the full `spec-eval.md §3` list (read only through FR-EVL-011). DES-001 migration ≥ **v12**.
- **ADD**: FR-RUN-049 `--selection` (+ OE-rejects-non-weighted error case), FR-RUN-050 `--llm-weight`,
  FR-RUN-051 OE best-on-interrupt (B7), FR-LLM-026 per-LLM `--reasoning-effort` (both backends), one FR-EVL for the
  B1 aggregation guard, and a normative principle in `specifications.md §4.4/§4.5` ("neutral levers first-class;
  `--config-override` is the exception").
- **SUPERSEDE** (ADR-007, verbatim confirmed): D5 lossy bullet (L127-128), Negative consequence (L175-176), roadmap
  "S15 — parity (ensemble→bandit…)" (L143). Also FR-RUN-046 (`spec-run.md:322`) "weights dropped/warned" and the
  spec-llm projection note (`spec-llm.md:378-383`). ADR-007 says `ucb` singular → widen to `ucb`/`ucb1`/`thompson`.
- **AMEND** DES-005 (§2.1 opts L49, §4.2 merge order L443-460, §4.2 Shinka L489-496, §4.6 capabilities L571-578,
  §4.7/§7.1 teardown L598-623/L741-761 for B2/B7, §8 RunConfig L771-779, §11 CLI L1026, §14.1 L1327-1331); DES-002
  (§2.1/§2.8/§5/§6 for `--reasoning-effort`); DES-006 §4.3 `compute_aggregates` (L273-317) + §1.3 wrapper contract
  for B1; DES-001 §4.1/§4.3 schema for the new migration.
- **Validation**: traceability rows for each new FR + B1/B2/B7; val-integration adds L2-Shinka bandit ensemble,
  selection-strategy validation (OE reject), reasoning_effort projection, B1/B2/B7 regression; val-e2e adds a Shinka
  bandit-ensemble scenario against the fake server.

---

## 5. Open policy question (for the addendum author)

Amend **ADR-007 in place** (add a "v0.17 Amendment" section superseding D5's lossy bullet + the Negative consequence
+ the roadmap line, and widening `capabilities()` to carry selection strategies + a `reasoning_effort` axis) **vs.**
a new superseding **ADR-008**. Given the changes *refine* D4/D5 of an Accepted ADR rather than reverse the core
decision, an **in-place amendment section** is the lighter, more honest choice — but this is a documentation-policy
call to confirm.
