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
- `tests/` : 72 tests pytest (52 moteur + 20 GUI).
- `gui/assets/` : icônes machines (15 SVG), icônes UI (10 SVG), ATTRIBUTION.txt.

## Conventions

- `engine/` ne doit jamais importer depuis `gui/`.
- Pas de `sys.path.insert` (imports de packages via `pyproject.toml`).
- Source unique de construction du problème : `engine/builders.build_problem_from_workflow`.
- Pont v1<->v2 : `engine/adapters.py` (`unified_to_problem`, `problem_to_unified`).
- Source unique de constantes visuelles : `gui/theme.py` (couleurs, styles, dimensions nœuds).

## Avant de committer

1. Lancer `QT_QPA_PLATFORM=offscreen pytest tests/ -q` — tous les tests doivent passer (72).
2. Vérifier que `python -m gui.main` démarre (utiliser `QT_QPA_PLATFORM=offscreen` en CI/sans écran).
3. Lancer `python -c "import ast; ast.parse(open('gui/main_window.py').read())"` pour vérifier la syntaxe.
