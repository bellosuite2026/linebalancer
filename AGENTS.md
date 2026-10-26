# AGENTS.md

Guide de contribution pour le projet **Textile Line Balancer**.

## Commandes

```bash
# Environnement virtuel
source .venv/bin/activate

# Tests (moteur + GUI)
QT_QPA_PLATFORM=offscreen pytest tests/ -v

# Lint / format
black gui/ engine/ tests/
mypy engine/   # optionnel

# Lancer l'interface
python -m gui.main

# Lancer l'équilibrage CLI
python scripts/balance.py --sam data/samples/... --cycle-time 1.5 --solver rpw
```

## Architecture

- `engine/` : logique métier pure (modèles, solveurs, parsers, adaptateurs). **Aucune dépendance GUI.**
  - `engine/resources.py` (v2.2) : postes multi-machines, fractionnement des opérations > cadence (parts + reliquat), affectation des postes et des ouvriers (compétences + rendement, méthode hongroise). Partagé par RPW et CP-SAT. Options du problème : `max_machines_per_station` (3), `machine_change_time` (0), `section_policy` (prefer|strict), `split_mode` (share|parallel) ; `Worker.skill_levels` = matrice de polyvalence. Voir `docs/saas/RECHERCHE_ALGO.md`.
- `gui/` : présentation PySide6, découpée par responsabilité :
  - `main.py` — point d'entrée (< 30 lignes)
  - `main_window.py` — MainWindow : composition des vues, coordination (~660 lignes)
  - `balance_bar.py` — BalanceBar : contrôles solveur + terminal + runner thread
  - `project_io.py` — Import/export projets (new, load, save, SAM, glTF)
  - `node_editor.py` — Vue Logique (graphe de nœuds)
  - `inspector.py` — panneau propriétés (3 vues)
  - `theme.py` — source unique des constantes visuelles (couleurs, styles, icônes)
  - `viz_widgets.py` — Yamazumi / Spaghetti / Gantt / Résultats
  - `balance_runner.py` — worker thread d'équilibrage
  - `layout_toolbar.py` — outils Implantation 2D
  - `svg_icons.py` — loader d'icônes SVG (machines + UI)
- `api/` : API FastAPI du SaaS (adaptateur fin, **aucune logique métier** ; dépend de `engine/`, jamais de `gui/`). Lancer : `uvicorn api.main:app --reload`. Doc : `api/README.md`.
- `tests/` : 72 tests moteur + 20 GUI + `tests/test_engine_multi.py` (moteur v2.2 : multi-machines, partage, ouvriers) + `tests/test_api.py` (API) + `tests/test_api_saas.py` (comptes, hors-ligne).
- `supabase/migrations/` : schéma Postgres (ateliers, membres, offres, lignes, gammes, calculs) + RLS. Toute évolution de schéma = nouveau fichier horodaté, jamais de modification d'une migration appliquée.
- `scripts/e2e_supabase.py` : test de bout en bout contre un vrai projet Supabase ; `scripts/e2e_admin.py` : super admin (/v1/admin/*).
- `api/routes_admin.py` + `web/src/pages/Admin.tsx` : espace super admin (rôle dans `private.platform_admins`).
- `gui/assets/` : icônes machines (15 SVG), icônes UI (10 SVG), ATTRIBUTION.txt.

## Conventions

- `engine/` ne doit jamais importer depuis `gui/` ni `api/`.
- Pas de `sys.path.insert` (imports de packages via `pyproject.toml`).
- Source unique de construction du problème : `engine/builders.build_problem_from_workflow`.
- Pont v1<->v2 : `engine/adapters.py` (`unified_to_problem`, `problem_to_unified`).
- Source unique de constantes visuelles : `gui/theme.py` (couleurs, styles, dimensions nœuds).

## Avant de committer

1. Lancer `QT_QPA_PLATFORM=offscreen pytest tests/ -q` — tous les tests doivent passer (72).
2. Vérifier que `python -m gui.main` démarre (utiliser `QT_QPA_PLATFORM=offscreen` en CI/sans écran).
3. Lancer `python -c "import ast; ast.parse(open('gui/main_window.py').read())"` pour vérifier la syntaxe.
