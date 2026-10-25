# Textile Line Balancer — Équilibrage de lignes de production habillement

Application d'équilibrage de lignes (Assembly Line Balancing Problem - ALBP) pour le secteur textile/habillement.
Architecture modulaire inspirée de **VisoNode** (node-graph editor PySide6) mais spécialisée pour l'ordonnancement.

## Fonctionnalités

| Fonction | Description |
|----------|-------------|
| **Import SAM** | CSV / Excel / JSON (Standard Allowed Minutes) |
| **Gestion ressources** | Postes machines, ouvriers + compétences, sections |
| **Contraintes** | Précédence, temps cycle, type machine, compétences, affectations forcées/interdites |
| **Solveurs** | RPW (heuristique rapide, O(n²)), CP-SAT (OR-Tools, optimal) |
| **Objectifs** | Min stations, min cycle time, max efficacité, équilibrage charge |
| **Export** | JSON, Excel (rapport détaillé), Gantt (JSON pour visualisation) |
| **Validation** | Détection cycles, compétences manquantes, machines manquantes |
| **Vue Logique (Flow/VSM)** | Éditeur de graphe de nœuds PySide6 (opérations, postes, ouvriers) |
| **Vue Implantation 2D** | Plan d'usine : murs, zones, machines, cotes, snap (type LibreCAD) |
| **Vue 3D** | Visualisation 3D synchronisée du bâtiment et des flux (VisPy) |
| **Tests GUI** | 20 tests pytest-qt (navigation, contrôles, terminal) |

## Structure du projet

```
textile-line-balancer/
├── pyproject.toml            # Projet installable (pip install -e .)
├── engine/                   # Logique métier (sans dépendance GUI)
│   ├── models.py             # Modèle v1: Operation, Workstation, Worker, Problem, Result
│   ├── models_v2.py          # Modèle unifié: UnifiedProject, BuildingLayout, PhysicalAsset...
│   ├── builders.py           # Construction LineBalancingProblem depuis un workflow (source unique)
│   ├── adapters.py           # Pont UnifiedProject <-> LineBalancingProblem (v1<->v2)
│   ├── parsers.py            # Import SAM (CSV/Excel/JSON), postes, ouvriers
│   ├── solvers/
│   │   ├── __init__.py       # Registry: solve_rpw, solve_cp_sat, solve_cp_sat_ml
│   │   ├── rpw_solver.py     # Ranked Positional Weight (heuristique O(n²))
│   │   └── cpsat_solver.py   # OR-Tools CP-SAT (optimal, contraintes complètes)
│   └── exporters.py          # Export JSON, Excel, Gantt
├── gui/                      # Présentation PySide6 (découpée par responsabilité)
│   ├── main.py               # Point d'entrée (< 30 lignes)
│   ├── main_window.py        # MainWindow: composition des vues, coordination (~660 lignes)
│   ├── balance_bar.py        # BalanceBar: contrôles solveur + terminal + runner thread
│   ├── project_io.py         # Opérations projet (import/export fichier)
│   ├── theme.py              # Source unique des constantes visuelles (couleurs, styles, icônes)
│   ├── node_editor.py        # Vue Logique: NodeEditor, EdgeItem, NodeItem, palettes
│   ├── inspector.py          # UnifiedInspector: panneau propriétés (3 vues)
│   ├── viz_widgets.py        # YamazumiChart, SpaghettiDiagram, TimelineGantt, ResultsTab
│   ├── balance_runner.py     # Worker thread d'équilibrage (QObject + signaux)
│   ├── layout_toolbar.py     # TextileLayoutStandards + LayoutToolBar (Implantation 2D)
│   ├── layout_view_2d.py     # Vue Implantation 2D (murs, zones, cotes, snap, export glTF)
│   ├── svg_icons.py          # Loader d'icônes SVG (machines + UI)
│   ├── view3d.py             # Rendu 3D VisPy (VisMesh)
│   ├── yamazumi.py           # Graphique Yamazumi (PySide6)
│   ├── spaghetti.py          # Diagramme spaghetti (heatmap)
│   ├── timeline_gantt.py     # Gantt multi-pistes
│   ├── assets/
│   │   ├── machines/         # 15 icônes machines SVG (piqueuse, surjeteuse, etc.)
│   │   ├── icons/            # 10 icônes UI SVG (vues, fichiers, zoom)
│   │   └── ATTRIBUTION.txt   # Licence et sources des icônes
│   └── project.json          # Projet courant (auto-save)
├── tests/                    # Tests automatisés (pytest)
│   ├── test_engine.py        # 52 tests : modèles, solveurs, parseurs, export, géométrie mur/porte
│   └── test_gui.py           # 20 tests GUI : MainWindow, BalanceBar, Terminal, navigation
├── data/                     # Échantillons SAM, taxonomie compétences, modèles
├── scripts/
│   ├── generate_templates.py # Génère fichiers modèles vides
│   └── balance.py            # Point d'entrée CLI principal
├── results/                  # Résultats d'équilibrage (créé à l'exécution)
└── projects/                 # Projets sauvegardés (JSON)
```

> **Règle d'architecture** : `engine/` est la source de vérité (modèle + solveurs), `gui/` dépend de `engine/` mais jamais l'inverse. `gui/theme.py` est la source unique des constantes visuelles (plus de duplication). Pas de `sys.path.insert` — les imports passent par `pyproject.toml`.

## Installation

```bash
cd /home/belloumi/Bureau/textile-line-balancer

# Créer venv
python3 -m venv .venv
source .venv/bin/activate

# Installer le projet (packages engine/ et gui/ importables)
pip install -e .

# Dépendances optionnelles (déjà dans pyproject.toml)
pip install ortools openpyxl   # CP-SAT (optimal) + export Excel
```

## Lancer l'interface

```bash
python -m gui.main
```

## Tests

```bash
# Toute la suite (moteur + GUI)
QT_QPA_PLATFORM=offscreen pytest tests/ -v

# Moteur uniquement
QT_QPA_PLATFORM=offscreen pytest tests/test_engine.py -v

# GUI uniquement (nécessite pytest-qt)
QT_QPA_PLATFORM=offscreen pytest tests/test_gui.py -v

# 93 tests : 72 moteur + 21 GUI
```

## Formats fichiers d'entrée

### SAM (Standard Allowed Minutes) — `sam_chemise_homme.csv`

```csv
Op_ID;Description;SAM_min;Predecesseurs;Type_Machine;Competences;Section;Optionnel
OP010;Préparation pièces;0.45;;table_travail;lecture_plan;Montage;FALSE
OP020;Montage épaule;0.55;OP010;piqueuse_plate;couture_droite;Montage;FALSE
OP030;Montage côtés;0.65;OP020;piqueuse_plate;couture_droite;Montage;FALSE
...
```

**Colonnes obligatoires** : `Op_ID`, `SAM_min`
**Colonnes optionnelles** : `Description`, `Predecesseurs` (séparés par `;`), `Type_Machine`, `Competences` (séparés par `;`), `Section`, `Optionnel`

### Postes de travail — `workstations_chemise.csv`

```csv
Poste_ID;Nom;Type_Machine;Disponible;Max_Ouvriers;Section
WS01;Poste préparation;table_travail;Oui;1;Montage
WS02;Piqueuse plate 1;piqueuse_plate;Oui;1;Montage
WS03;Surjeteuse 5 fils;surjeteuse_5_fils;Oui;1;Montage
...
```

### Ouvriers — `workers_chemise.csv`

```csv
Ouvrier_ID;Nom;Competences;Efficacite;Disponible;Poste_Assigne
W001;Marie D.;lecture_plan;couture_droite;1.0;Oui;
W002;Ahmed B.;couture_droite;surjet_5_fils;1.05;Oui;
...
```

**Compétences** : séparées par `;` — doivent correspondre à la taxonomie `data/skills/skills_taxonomy.yaml`

## Utilisation rapide

### 1. Générer modèles vides

```bash
python scripts/generate_templates.py --output-dir data/templates --formats csv xlsx
```

### 2. Test rapide avec exemple chemise (RPW - heuristique)

```bash
python scripts/balance.py \
  --sam data/samples/sam_chemise_homme.csv \
  --workstations data/samples/workstations_chemise.csv \
  --workers data/samples/workers_chemise.csv \
  --cycle-time 1.5 \
  --solver rpw \
  --output results \
  --project-name chemise_test
```

### 3. Résolution optimale (CP-SAT)

```bash
# Nécessite: pip install ortools
python scripts/balance.py \
  --sam data/samples/sam_chemise_homme.csv \
  --workstations data/samples/workstations_chemise.csv \
  --workers data/samples/workers_chemise.csv \
  --cycle-time 1.5 \
  --solver cp-sat \
  --time-limit 60 \
  --export-excel \
  --export-gantt \
  --verbose
```

### 4. Avec contraintes personnalisées

Créez un fichier projet JSON (voir `projects/exemple_projet.json`) avec:
- `forced_assignments`: {"OP020": 2} — OP020 doit être en station 2
- `forbidden_assignments`: {"OP030": [1, 5]} — OP030 interdit stations 1 et 5
- `same_station_groups`: [["OP020", "OP030"]] — ces ops ensemble

Puis:
```bash
python scripts/balance.py --project projects/exemple_projet.json
```

## Sorties

### Console (résumé)
```
✅ CP-SAT - OPTIMAL en 3.2s
📊 Stations utilisées: 9
⏱️  Cycle time réel: 1.48 min (cible: 1.50)
📈 Efficacité ligne: 92.3%
⚖️  Balance delay: 7.7%
📐 Smoothness index: 0.15

📋 Détail par poste:
  Station 1: 1.45 min | 3 ops | Charge: 96.7% | Ouvriers: Marie D.
  Station 2: 1.48 min | 2 ops | Charge: 98.7% | Ouvriers: Ahmed B.
  ...
```

### Fichiers générés dans `results/`

| Fichier | Contenu |
|---------|---------|
| `chemise_test_result.json` | Résultat complet (sérialisable) |
| `chemise_test_result.xlsx` | Rapport Excel multi-feuilles (Résumé, Détail Postes, Opérations) |
| `chemise_test_gantt.json` | Données pour diagramme Gantt (JS/Plotly) |

## Algorithmes

### RPW (Ranked Positional Weight) — Rapide
- **Complexité**: O(n²) — quelques ms
- **Qualité**: Solution feasible, ~5-15% au-dessus optimal
- **Usage**: Exploration rapide, solution initiale CP-SAT

### CP-SAT (OR-Tools) — Optimal
- **Modèle**: Programmation par contraintes avec variables booléennes
- **Contraintes gérées**:
  - Précédence (DAG)
  - Temps cycle par station
  - Type machine par station
  - Compétences ouvriers par station
  - Affectations forcées/interdites
  - Groupes même station
- **Objectifs**: Min stations, Min cycle, Max efficacité, Équilibrage
- **Temps**: 10-60s selon taille (100-300 ops)

## Exemples fournis

| Exemple | Opérations | Temps total | Cycle suggéré |
|---------|------------|-------------|---------------|
| `sam_chemise_homme.csv` | 23 ops | ~13.5 min | 1.5 min (9 postes) |
| `sam_pantalon_homme.csv` | 22 ops | ~11.2 min | 1.3 min (9 postes) |
| `sam_veste_homme.csv` | 31 ops | ~22.8 min | 2.0 min (12 postes) |

## Développement

### Ajouter un solveur
```python
# engine/solvers/mon_solveur.py
from engine.models import LineBalancingProblem, BalancingResult

def solve_mon_algo(problem: LineBalancingProblem) -> BalancingResult:
    # ... implémentation
    return BalancingResult(...)
```

### Étendre la taxonomie compétences
Éditez `data/skills/skills_taxonomy.yaml` — structure hiérarchique:
```yaml
categories:
  - id: "couture"
    families:
      - id: "piqueuse_plate"
        skills:
          - id: "couture_droite"
            level: 1
```

### Lancer les tests
```bash
# Installer les dépendances dev (pytest)
pip install -e ".[dev]"

# Toute la suite (moteur + GUI, 69 tests)
QT_QPA_PLATFORM=offscreen pytest tests/ -v
```

## Roadmap

- [x] Interface graphique PySide6 (Vue Logique + Implantation 2D + Vue 3D)
- [x] Architecture moteur/gui séparée (pyproject.toml, packages installables)
- [x] Suite de tests moteur (52 tests : modèles, solveurs, parseurs, export, géométrie mur/porte)
- [x] Découpage GUI modulaire (Phase 3 : main_window, balance_bar, project_io, theme)
- [x] Tests GUI avec pytest-qt (20 tests : navigation, contrôles, terminal)
- [x] Thème unifié (theme.py) : source unique couleurs, styles, icônes
- [x] Icônes SVG UI + machines (25 icônes libres de droit)
- [ ] Multi-modèles (gammes mixtes chemise/pantalon)
- [ ] Stochastic ALBP (temps aléatoires)
- [ ] Intégration ERP (import OF, export instructions poste)
- [ ] Visualisation Gantt interactive (Plotly Dash)
- [ ] API REST pour intégration MES

## Hygiène du code

### Phase 3 — Découpage final de la GUI
- `gui/main.py` réduit de **956 → 28 lignes** (simple point d'entrée).
- Extraction de `gui/main_window.py` : MainWindow (composition UI, coordination des vues).
- Extraction de `gui/balance_bar.py` : contrôles solveur + terminal + runner thread.
- Extraction de `gui/project_io.py` : import/export projets (new, load, save, SAM, glTF).
- Extraction de `gui/theme.py` : source unique des constantes visuelles (couleurs, stylesheet, icônes, dimensions).
- Ajout de **20 tests GUI** avec pytest-qt (navigation, sidebars, contrôles d'équilibrage, terminal).
- Icônes SVG UI (10) + ATTRIBUTION.txt (`gui/assets/`).

### Phase 2 — Découpage GUI initial
- `gui/main.py` réduit de **3278 → 956 lignes**.
- Composants extraits : `node_editor`, `inspector`, `viz_widgets`, `balance_runner`, `layout_toolbar`.

### Phase 1 — Modèle + adaptateurs + tests
- Ajout de `validate()` sur `BuildingLayout` et `UnifiedProject` (`engine/models_v2.py`).
- Ajout du champ `task_type` au modèle `Operation` v1 (`engine/models.py`).
- `build_problem_from_workflow` préserve `task_type` et `optional`.
- Adaptateurs renforcés : `unified_to_problem` valide avant conversion.
- Correction bug critique dans `adapters.py` (`NameError` sur les arêtes de précédence).

### Tâches d'hygiène antérieures
- Suppression du code mort (`gui/three_view_main.py`, `engine/solvers/rpw.py` dupliqué, etc.).
- Unification des 2 solveurs RPW en un seul.
- Source unique de construction du problème : `engine/builders.build_problem_from_workflow`.
- Suppression de tous les `sys.path.insert`.

## Licence

MIT — Usage libre, modification, distribution.

---

**Basé sur l'architecture VisoNode** — Merci à l'équipe VisoNode pour la structure modulaire PySide6 réutilisée.


## Changelog v2.1.0 (2026-10-25)

- **Diagnostics de faisabilité** (`engine/diagnostics.py`) : capacité machines, compétences, effectif, prédécesseurs inconnus, opérations plus longues que le cycle — avec action corrective chiffrée.
- **Postes parallèles (dédoublement)** : une opération > cycle est répartie sur `ceil(durée/cycle)` postes, dans RPW et CP-SAT.
- **RPW honnête** : respecte le nombre de postes physiques par type machine et la polyvalence des ouvriers ; renvoie `INFEASIBLE_CONSTRAINTS` au lieu d'un faux `FEASIBLE`. Affectation des ouvriers par couplage biparti.
- **CP-SAT complet** : un type machine par station, capacité en postes physiques, postes parallèles ; message d'infaisabilité explicite.
- **KPIs corrigés** : efficacité calculée sur le cycle réel et le nombre réel d'opérateurs.
- **`find_min_cycle`** : cadence maximale atteignable (recherche dichotomique).
- **Parseurs** : réparent les listes écrites avec le séparateur du fichier (`a;b` dans un CSV `;`).
