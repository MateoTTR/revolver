# Refactor — Introduction de l'entité Run + Solutions comme références

**Date**: 2026-03-12
**Origine**: Session 009, retours utilisateur sur DES-005 et DES-006
**Statut**: À exécuter (session suivante)

---

## 1. Résumé des décisions

### 1.1 Nouvelle architecture conceptuelle

Le **run** devient l'entité physique de premier ordre (fichiers, checkpoint, config).
La **solution** devient une entité logique légère (référence DB vers un programme dans un run).

```
Run (entité physique)
  ├── checkpoint OpenEvolve (population complète)
  ├── config, wrapper evaluator, logs
  └── N programmes classés (rank 1..N)

Solution (entité logique — ligne en DB)
  └── pointe vers (run_id, rank) → résout le chemin du programme
```

### 1.2 Principes

- **Immutabilité** : un run terminé ne change jamais. Ses programmes, sa lineage, ses fichiers sont figés.
- **Resume = nouveau run** : `resume` crée un nouveau run (`resumed_from: <parent>`) avec de nouvelles solutions. L'ancien run et ses eval results restent intacts.
- **Solution = référence** : pas de répertoire propre, pas de copie de fichier. La solution est un pointeur (run_id, rank) avec un alias optionnel.
- **Run = unité physique** : checkpoint, config, wrapper, programmes vivent dans le répertoire du run.

---

## 2. Décisions détaillées (DES-005)

### D-005-a : Détection evaluator — priorité evaluate() sur evaluate_instance()

**Avant** : §3.3/3.4 ambigu, laisse entendre que c'est l'un OU l'autre.

**Après** :
1. Si `evaluate()` existe → l'utiliser tel quel (l'utilisateur peut appeler `evaluate_instance()` en interne s'il veut)
2. Sinon, si `evaluate_instance()` existe → générer le wrapper
3. Sinon → erreur

L'utilisateur a le droit d'écrire les deux fonctions dans le même fichier. Revolver ne regarde que `evaluate()` en priorité.

### D-005-b : `run status` avec exécutions concurrentes

**Avant** : un seul lock file `.revolver/run.lock`.

**Après** : répertoire `.revolver/runs/locks/` avec un fichier lock par run actif (`<run_id>.lock`). `run status` liste tous les runs actifs.

### D-005-c : `run resume` crée un nouveau run

**Avant** : resume modifie la solution existante (même ID, mise à jour du programme et de la lineage). Problème de traçabilité si des eval results référençaient l'ancien programme.

**Après** :
- `revolver run resume --run <run_id>` crée un **nouveau run** avec `resumed_from: <run_id>`
- Le nouveau run a son propre ID, ses propres programmes, ses propres solutions
- L'ancien run et ses solutions/eval results restent intacts
- Le checkpoint du run parent est lu mais pas modifié

### D-005-d : Variables d'environnement — clarification

- `REVOLVER_INSTANCE_LOG` et `REVOLVER_EVAL_LOG` : utilisées **uniquement** par le wrapper généré automatiquement. Un utilisateur en mode legacy n'en bénéficie pas (sauf s'il les implémente lui-même).
- Documenter cela explicitement dans le §5.

### D-005-e : Post-run eval sur toutes les top-N solutions

**Avant** : post-run eval uniquement sur la solution rank-1.

**Après** : post-run eval sur **chaque** solution du top-N. Le coût est raisonnable (N évaluations séquentielles).

### D-005-f : Renommage best.py → program.py

**Avant** : `best.py` dans chaque solution directory.

**Après** : `rank-1.py`, `rank-2.py`, etc. dans le répertoire du run (`runs/<id>/programs/`). Le nom reflète le rang, pas un jugement de valeur.

### D-005-g : RQ-01 — `--dry-run` accepté

`--dry-run` valide tout (version, LLM, dataset, intégrité, concurrence) et affiche la config OpenEvolve résolue sans lancer le run. Décision tranchée, à intégrer dans les commandes §11 et spec-run.

### D-005-h : RQ-02 — Wrapper réutilisé au resume

Le wrapper stocké dans le run parent est réutilisé (copié dans le nouveau run). Pas de régénération. Décision tranchée.

### D-005-i : RQ-03 — Monitoring progrès

Reste ouvert. À analyser en fonction de l'API OpenEvolve.

### D-005-j : RQ-04 / DD-07 — Resume indépendant post-V1

Resume opère sur le **run** (checkpoint contenant toute la population). On ne peut pas resume une solution individuelle. Post-V1, un mécanisme de "seed" (nouveau run avec programme initial spécifique) serait un concept différent.

---

## 3. Décisions détaillées (DES-006)

### D-006-a : `revolver eval` — comportement si résultats existants

**Avant** : écrasement inconditionnel (§5).

**Après** :
- Si résultats existants → warning + confirmation interactive ("Evaluation already exists for solution X on dataset Y. Re-evaluate? [y/N]")
- `--force` pour sauter la confirmation
- En mode `--json` → erreur sans confirmation interactive (il faut `--force`)
- `revolver eval` **ré-évalue toujours** (ne retourne pas les résultats existants). Pour consulter sans recalculer → `revolver eval results`.

### D-006-b : `eval results` sans évaluation préalable

Erreur claire : "No evaluation found for solution X on dataset Y. Run `revolver eval --solution X --dataset Y` first." Exit code 1.

### D-006-c : Incohérence des agrégats en mode legacy

Risque accepté et documenté. En mode legacy (`evaluate()`), les agrégats calculés par `revolver eval` (moyenne des métriques par instance) peuvent différer du score retourné par `evaluate()` en mode agrégé. C'est la responsabilité de l'utilisateur.

Ajouter une section de documentation/guide dans le ConOps ou un template généré par `revolver problem init`.

### D-006-d : Mode single-instance pour evaluate() legacy

Confirme le design existant (§3.3). `REVOLVER_INSTANCE_PATH` est positionné, `REVOLVER_DATASET_DIR` n'est PAS positionné. L'utilisateur doit vérifier `REVOLVER_INSTANCE_PATH` en priorité. Documenter clairement.

### D-006-e : EQ-01 — Confirmation avant ré-évaluation

Tranché : oui, voir D-006-a ci-dessus.

### D-006-f : EQ-03 — Placement du runner partagé

Tranché : `infra/evaluator_runner.py`.

### D-006-g : Appel global evaluate() en mode legacy pour récupérer les agrégats custom

**Contexte** : en mode legacy (`evaluate()`), les agrégats calculés par Revolver (mean, p10, p90...) à partir des résultats per-instance peuvent différer du `combined_score` retourné par le `evaluate()` de l'utilisateur en mode agrégé (qui peut utiliser min, weighted average, etc.).

**Décision** : pour les évaluateurs legacy, `revolver eval` et `revolver benchmark` effectuent une **étape supplémentaire** après l'évaluation per-instance :
1. **Par instance** (comme actuellement) : appel `evaluate()` avec `REVOLVER_INSTANCE_PATH` par instance → métriques per-instance → agrégats Revolver (mean, min, max, p10, p50, p90, std)
2. **Agrégation globale** (nouveau) : un dernier appel `evaluate()` **sans** `REVOLVER_INSTANCE_PATH`, **avec** `REVOLVER_DATASET_DIR` → récupère le `combined_score` et les métriques agrégées custom de l'utilisateur

| Mode evaluator | Étape 1 (par instance) | Étape 2 (agrégation globale) |
|---|---|---|
| `evaluate_instance()` | Appel direct par instance | Pas d'étape 2 (pas d'agrégateur custom) |
| `evaluate()` legacy | Appel avec `REVOLVER_INSTANCE_PATH` | Appel avec `REVOLVER_DATASET_DIR` |

**Stockage** : champ JSON `user_aggregates` dans `eval_metadata`.

```sql
-- Ajout à eval_metadata
user_aggregates TEXT    -- JSON: {"combined_score": 0.72, "makespan": 155.3}
                        -- NULL si evaluate_instance() (pas d'agrégateur custom)
```

**Affichage** : `revolver eval results` affiche les deux sections :
- "Revolver aggregates" : nos stats calculées à partir des données per-instance
- "User aggregates" : le résultat brut du evaluate() global (uniquement si mode legacy)

Les deux visions coexistent sans conflit. L'utilisateur voit immédiatement si/pourquoi ses scores diffèrent.

**Impact** :
- DES-006 §4 : ajouter l'étape d'agrégation globale
- DES-006 §6 : Pydantic `EvalMetadata` + `EvalResult` : ajouter `user_aggregates`
- DES-001 : ajouter colonne `user_aggregates TEXT` à `eval_metadata`
- spec-eval : documenter l'affichage dual (Revolver + user aggregates)

---

## 4. Nouveau schéma SQLite (DES-001)

### 4.1 Nouvelle table `runs`

```sql
CREATE TABLE runs (
    id                TEXT PRIMARY KEY,       -- "run-YYYYMMDD-HHMMSS"
    problem_version   TEXT NOT NULL REFERENCES problem_versions(tag),
    llm               TEXT NOT NULL,          -- LLM name from registry
    dataset           TEXT NOT NULL REFERENCES datasets(name),
    top_n             INTEGER NOT NULL DEFAULT 1,
    iterations        INTEGER NOT NULL,
    generation_time_s REAL,
    config_snapshot   TEXT,                   -- verbatim OpenEvolve YAML config (NFR-023)
    problem_hash      TEXT NOT NULL,          -- hash of problem snapshot used
    dataset_hash      TEXT NOT NULL,          -- hash of dataset at registration
    llm_model         TEXT NOT NULL,          -- full model ID (e.g., "claude-opus-4-6")
    resumed_from      TEXT REFERENCES runs(id), -- NULL if fresh run, parent run_id if resumed
    status            TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'completed', 'interrupted')),
    created_at        TEXT NOT NULL           -- ISO 8601
);

CREATE INDEX idx_runs_version ON runs(problem_version);
CREATE INDEX idx_runs_created ON runs(created_at DESC);
CREATE INDEX idx_runs_resumed ON runs(resumed_from);
```

### 4.2 Table `solutions` simplifiée (remplace l'ancienne)

```sql
CREATE TABLE solutions (
    id        TEXT PRIMARY KEY,       -- "sol-YYYYMMDD-HHMMSS"
    run_id    TEXT NOT NULL REFERENCES runs(id),
    rank      INTEGER NOT NULL,       -- 1 = best
    best_score REAL,
    alias     TEXT UNIQUE,
    UNIQUE(run_id, rank)
);

CREATE INDEX idx_solutions_run ON solutions(run_id);
```

### 4.3 Table `solution_lineage` — supprimée

La lineage est désormais portée par la table `runs`. Plus besoin de `solution_lineage`.

### 4.4 Tables inchangées

- `problem_versions` (§3.1)
- `datasets` (§3.2)
- `dataset_instances` (§3.3)
- `dataset_compat` (§3.4)
- `eval_metadata` (§3.7) — FK `solution_id` reste vers `solutions(id)`. Ajouter colonne `user_aggregates TEXT` (JSON, NULL si evaluate_instance mode). Voir D-006-g.
- `eval_instances` (§3.8)
- `benchmarks` (§3.9)
- `benchmark_solutions` (§3.10) — FK `solution_id` reste vers `solutions(id)`

### 4.5 ID Generation — mise à jour

| Entity | Pattern | Example |
|---|---|---|
| Run | `run-{YYYYMMDD}-{HHMMSS}` | `run-20260310-143000` |
| Solution | `sol-{YYYYMMDD}-{HHMMSS}` | `sol-20260310-143000` |
| Evaluation | `eval-{YYYYMMDD}-{HHMMSS}` | `eval-20260310-160000` |
| Benchmark | `bench-{YYYYMMDD}-{HHMMSS}` | `bench-20260310-170000` |

---

## 5. Nouveau layout filesystem

### 5.1 Répertoire des runs

```
.revolver/
├── runs/
│   ├── run-20260310-143000/
│   │   ├── manifest.yaml              # Metadata + lineage du run
│   │   ├── config.yaml                # Config OpenEvolve verbatim
│   │   ├── _revolver_evaluator.py     # Wrapper généré (ou copie legacy)
│   │   ├── oe-checkpoint/             # Checkpoint OpenEvolve
│   │   ├── instance_log.db            # Side-channel (optionnel)
│   │   ├── eval.log                   # Log evaluator (optionnel)
│   │   └── programs/
│   │       ├── rank-1.py
│   │       ├── rank-2.py
│   │       └── rank-3.py
│   ├── run-20260310-160000/           # Autre run
│   │   └── ...
│   └── locks/                         # Lock files pour runs actifs
│       └── run-20260310-143000.lock
├── problem/                           # Inchangé
├── datasets/                          # Inchangé
└── revolver.db                        # Inchangé
```

### 5.2 Plus de répertoire `solutions/`

Les solutions n'ont pas de répertoire propre. Le chemin du programme est résolu via :
```
.revolver/runs/<run_id>/programs/rank-<N>.py
```

---

## 6. Requêtes clés mises à jour

### 6.1 Solution detail (`revolver solution info`)

```sql
SELECT s.id, s.alias, s.rank, s.best_score,
       r.id AS run_id, r.problem_version, r.llm, r.dataset,
       r.llm_model, r.iterations, r.generation_time_s,
       r.top_n, r.config_snapshot, r.resumed_from, r.created_at
FROM solutions s
JOIN runs r ON s.run_id = r.id
WHERE s.id = :id_or_alias OR s.alias = :id_or_alias;
```

### 6.2 Solution list (`revolver solution list`)

```sql
SELECT s.id, s.alias, s.rank, s.best_score,
       r.id AS run_id, r.problem_version, r.llm, r.dataset, r.created_at
FROM solutions s
JOIN runs r ON s.run_id = r.id
WHERE (:version IS NULL OR r.problem_version = :version)
  AND (:llm IS NULL OR r.llm = :llm)
  AND (:rank IS NULL OR s.rank = :rank)
ORDER BY r.created_at DESC, s.rank;
```

### 6.3 Run list (`revolver run list`)

```sql
SELECT r.id, r.problem_version, r.llm, r.dataset, r.top_n,
       r.iterations, r.generation_time_s, r.status, r.resumed_from,
       r.created_at,
       MIN(s.best_score) AS worst_score,
       MAX(s.best_score) AS best_score
FROM runs r
LEFT JOIN solutions s ON s.run_id = r.id
GROUP BY r.id
ORDER BY r.created_at DESC;
```

### 6.4 Sibling solutions from same run

```sql
SELECT s.id, s.alias, s.rank, s.best_score
FROM solutions s
WHERE s.run_id = :run_id
ORDER BY s.rank;
```

### 6.5 Resume chain (lignée de resume)

```sql
-- Récursif : tous les ancêtres d'un run
WITH RECURSIVE chain(id, resumed_from, depth) AS (
    SELECT id, resumed_from, 0 FROM runs WHERE id = :run_id
    UNION ALL
    SELECT r.id, r.resumed_from, c.depth + 1
    FROM runs r JOIN chain c ON r.id = c.resumed_from
)
SELECT * FROM chain ORDER BY depth;
```

---

## 7. Modifications par fichier

### 7.1 Documents à modifier

| Fichier | Type de modification | Détails |
|---|---|---|
| **DES-001** | Majeure | Remplacer `solutions` + `solution_lineage` par `runs` + `solutions` (§4 ci-dessus). Mettre à jour ER diagram, requêtes, ID generation, design decisions. |
| **DES-005** | Majeure | Refondre autour du concept de run. §2 flows, §3 wrapper detection priority, §5 env vars clarification, §6 locks multiples, §7 post-run eval all top-N, §8 Pydantic models, §9 storage layout, §10 function signatures, §11 CLI commands (ajouter `run list`, `run info`, modifier `resume`), §12 sequence diagrams, §13 design decisions (DD-07 révisé, nouvelles DD). Résoudre RQ-01 (dry-run), RQ-02 (wrapper reuse). |
| **DES-006** | Moyenne | §2.1 : solution_id_or_alias inchangé (la solution existe toujours). §3.3 clarification dual-mode. §5 : ajouter confirmation/force. Résoudre EQ-01, EQ-03. Mettre à jour cross-DES dependencies. |
| **architecture.md** | Moyenne | §3 package structure (ajouter `models/run.py`). §5.3 schema overview (runs remplace solution_lineage). §6.1 data flow run. CLI layer: ajouter `run list`, `run info`. |
| **spec-run.md** | Moyenne | Ajouter commandes `run list`, `run info`. Modifier `run resume` (--run au lieu de --solution). Ajouter `--dry-run`. Mettre à jour output JSON (RunResult). Ajouter FRs pour run list/info. |
| **spec-solution.md** | Moyenne | Solution = référence vers (run, rank). Retirer les champs lineage de la solution info (ils viennent du run). Garder alias, eval results. |
| **spec-eval.md** | Mineure | Ajouter confirmation/--force pour re-eval. Ajouter erreur si eval results inexistants. |
| **spec-benchmark.md** | Mineure | Vérifier que --solutions reste cohérent (les solutions existent toujours comme entités). |
| **architecture.md §5.3** | Mineure | Mettre à jour le tableau des tables SQLite. |
| **ConOps** | Mineure | §4.1 structure répertoire : `runs/` remplace `solutions/`. §4.6 concept de solution mis à jour. |
| **CLAUDE.md** | Mineure | Ajouter DES-007 quand créé. Mettre à jour les open questions résolues. |

### 7.2 Nouveau document à créer

| Fichier | Contenu |
|---|---|
| **DES-007** (benchmark) | Design de `revolver benchmark`. À rédiger après le refactor, car il dépend du nouveau modèle run/solution. |

### 7.3 Documents inchangés

- DES-002 (llm subcommands) — pas d'impact
- DES-003 (problem versioning) — pas d'impact
- DES-004 (dataset registration) — pas d'impact
- ADR-001 à ADR-006 — pas d'impact (les ADRs restent valides)
- spec-project, spec-llm, spec-problem, spec-dataset, spec-setup — pas d'impact

---

## 8. Questions ouvertes restantes

| ID | Question | Contexte |
|---|---|---|
| RQ-03 | Mécanisme de monitoring progrès OpenEvolve | DES-005, dépend de l'API OpenEvolve |
| AQ-02 | Stratégie migration SQLite (scripts manuels vs Alembic) | Architecture |
| AQ-05 | Format export benchmark (CSV, Parquet, plots) | spec-benchmark, DES-007 |
| NEW-01 | Template/guide pour evaluate() dual-mode dans ConOps ou `problem init` | Découvert en D-006-c/d |

---

## 9. Plan d'exécution (session suivante)

### Phase 1 — Fondation (séquentiel)
1. Modifier DES-001 (schema) — c'est la base de tout

### Phase 2 — Design docs (parallélisable)
2. Modifier DES-005 (run orchestration) — en parallèle avec 3
3. Modifier DES-006 (eval loop) — en parallèle avec 2

### Phase 3 — Specs et architecture (parallélisable)
4. Modifier spec-run + spec-solution — en parallèle avec 5-6
5. Modifier spec-eval + spec-benchmark
6. Modifier architecture.md + ConOps

### Phase 4 — Vérification
7. Spec-reviewer sur tous les documents modifiés
8. Corrections des incohérences détectées
9. Deuxième passe spec-reviewer

### Phase 5 — Finalisation
10. Créer DES-007 (benchmark design)
11. Mettre à jour CLAUDE.md et backlog
