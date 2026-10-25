# Textile Line Balancer - Manuel d'Utilisation

**Version 2.0** - Juillet 2026

---

## Table des Matières

1. [Introduction](#1-introduction)
2. [Installation et Démarrage](#2-installation-et-démarrage)
3. [Interface Utilisateur](#3-interface-utilisateur)
4. [Vue Logique (Flow/VSM)](#4-vue-logique-flowvsm)
5. [Vue Implantation 2D](#5-vue-implantation-2d)
6. [Vue 3D](#6-vue-3d)
7. [Équilibrage de Ligne](#7-équilibrage-de-ligne)
8. [Exemples Pratiques](#8-exemples-pratiques)
9. [Référence Rapide](#9-référence-rapide)

---

## 1. Introduction

**Textile Line Balancer** est une application de bureau complète pour l'équilibrage de lignes de production textile et l'implantation d'usine. Elle intègre trois vues synchronisées :

| Vue | Usage | Raccourci |
|-----|-------|-----------|
| **Logique (Flow/VSM)** | Dessiner le flux de valeur, définir opérations, postes, ouvriers, machines | `Ctrl+1` |
| **Implication 2D** | Positionner machines, murs, zones sur plan d'usine | `Ctrl+2` |
| **3D** | Visualiser l'usine en temps réel (VisPy/OpenGL) | `Ctrl+3` |

### Fonctionnalités Principales

- **Éditeur de graphe nœuds** type VisoNode (drag & drop, connexions, inspecteur)
- **Deux solveurs d'équilibrage** : CP-SAT (optimal, OR-Tools) et RPW (heuristique)
- **Yamazumi Chart** interactif (VA/NVA/Attente, drag-drop pour rééquilibrer)
- **Diagramme Spaghetti** (heatmap déplacements, analyse congestion)
- **Diagramme Gantt** multi-pistes (Poste/Ouvrier/Machine/AGV) avec simulation
- **Export** : Excel, JSON, PDF, Gantt PNG, ONNX (pour modèles ML)

---

## 2. Installation et Démarrage

### Prérequis

```bash
# Ubuntu / Debian / Mint
sudo apt update && sudo apt install python3 python3-venv python3-pip

# Dépendances système pour OpenGL (Vue 3D)
sudo apt install libgl1-mesa-glx libegl1-mesa libxkbcommon-x11-0
```

### Installation

```bash
cd /home/belloumi/Bureau/textile-line-balancer
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Lancement

```bash
cd /home/belloumi/Bureau/textile-line-balancer
source .venv/bin/activate
python -m gui.main
```

### Raccourcis Clavier Globaux

| Raccourci | Action |
|-----------|--------|
| `Ctrl+N` | Nouveau projet |
| `Ctrl+O` | Ouvrir projet |
| `Ctrl+S` | Sauvegarder |
| `Ctrl+Z` / `Ctrl+Y` | Annuler / Rétablir |
| `1` | Vue Logique |
| `2` | Vue 2D |
| `3` | Vue 3D |
| `P` | Masquer/Afficher palette gauche |
| `I` | Masquer/Afficher inspecteur droit |
| `Molette` ou `Ctrl+Molette` | Zoom |
| `F` | Ajuster tout (fit) |
| `C` | Centrer vue |
| `A` | Ajuster sélection |
| `Espace` + Souris | Pan (vue logique/2D) |
| `Molette` | Zoom |
| `Suppr` | Supprimer nœud sélectionné |

---

## 3. Interface Utilisateur

### Disposition Principale

```
┌─────────────────────────────────────────────────────────────────┐
│ Barre de menus (Fichier, Edition, Affichage, Outils, Aide)       │
├──────────────┬──────────────────────────────┬───────────────────┤
│   BARRE TOP  │   [Logique] [2D] [3D]   [+] [Ouvrir] [Sauver]   │
├──────────────┼──────────────────────────────┼───────────────────┤
│   PALETTE    │        CANVAS CENTRAL        │    INSPECTEUR     │
│  (Gauche)    │   (Vue Logique / 2D / 3D)    │    (Droite)       │
│              │                              │                   │
│  Vue Logique │  • Noeuds deplacables         │  • Configuration │
│  Vue 2D      │  • Connexions par ports      │    du noeud       │
│  3D          │  • Zoom/Pan                  │  • Supprimer      │
│              │                              │  • Activer/Desac.│
├──────────────┴──────────────────────────────┴───────────────────┤
│ BARRE D'EQUILIBRAGE  [Solveur] [Cycle] [Max] [Lancer] [Arreter] │
│ TERMINAL / LOGS                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Palette (Gauche) - Vue Logique

| Icône | Type | Description |
|-------|------|-------------|
| 🏭 | **Section/Atelier** | Zone de production (ex: MONTAGE, FINITION) |
| ⚙️ | **Type Machine** | Équipement requis (ex: piqueuse_plate, surjeteuse) |
| 🏭 | **Poste de travail** | Station physique avec machine affectée |
| 👤 | **Ouvrier** | Ressource humaine avec compétences |
| 📝 | **Opération** | Tâche de la gamme (durée, prédécesseurs, type VA/NVA) |

### Inspecteur (Droite) - Configuration Détaillée

Chaque type de nœud a ses propres champs avec **tooltips explicatifs** (survoler le label) :

#### Poste de Travail (Workstation)
| Champ | Type | Description | Exemple |
|-------|------|-------------|---------|
| **ID Poste** | Texte | Identifiant unique | `WS01`, `WS02` |
| **Nom du poste** | Texte | Nom descriptif | `Poste montage épaule` |
| **Type machine** | Texte | Machine affectée | `piqueuse_plate` |
| **Poste disponible** | Case à cocher | Opérationnel ? | ✅ coché = actif |
| **Nb max ouvriers** | Entier (1-10) | Capacité simultanée | `2` |
| **Section** | Texte | Rattachement atelier | `MONTAGE` |

#### Opération (Operation)
| Champ | Type | Description | Exemple |
|-------|------|-------------|---------|
| **ID Opération** | Texte | Identifiant gamme | `OP010` |
| **Nom de l'opération** | Texte | Désignation | `Montage épaule` |
| **Durée (minutes)** | Décimal | Temps standard | `0.55` |
| **Prédécesseurs** | Texte | IDs séparés par `;` | `OP005;OP008` |
| **Type machine requis** | Texte | Machine nécessaire | `piqueuse_plate` |
| **Compétences requises** | Texte | Séparées par `,` | `couture_droite,couture_courbe` |
| **Section/Atelier** | Texte | Zone de production | `MONTAGE` |
| **Type de tâche** | Liste | VA / NVA / ATTENTE | `VA` |

#### Ouvrier (Worker)
| Champ | Type | Description | Exemple |
|-------|------|-------------|---------|
| **ID Ouvrier** | Texte | Identifiant unique | `W001` |
| **Nom de l'ouvrier** | Texte | Nom complet | `Marie Dupont` |
| **Compétences** | Texte | Séparées par `,` | `couture_droite,couture_courbe` |
| **Efficacité** | Décimal (0.1-3.0) | Coefficient vitesse | `1.0` = standard |
| **Ouvrier disponible** | Case à cocher | Présent aujourd'hui | ✅ |

---

## 4. Vue Logique (Flow/VSM)

### Créer un Flux de Valeur

1. **Ajouter une Section** : Clic sur "🏭 Section/Atelier" dans la palette → clic sur le canvas
2. **Ajouter Types Machines** : "⚙️ Type Machine" → définir `machine_type` (ex: `piqueuse_plate`)
3. **Ajouter Postes** : "🏭 Poste de travail" → configurer `ws_id`, `machine_type`, `section`
4. **Ajouter Ouvriers** : "👤 Ouvrier" → compétences, efficacité
4. **Ajouter Opérations** : "📝 Opération" → durée, prédécesseurs, machine_type, type tâche

### Connecter les Nœuds (Précédence)

1. Survoler le **port de sortie** (droite d'un nœud) → curseur devient croix
2. Clic glisser vers **port d'entrée** (gauche d'un autre nœud)
3. Relâcher → arête créée (flèche de précédence)

### Types d'Arêtes
- **Précédence** (par défaut) : ordre des opérations
- **Flux** : liaison section → poste
- **Transport** : déplacement pièces entre postes

### Exemple : Ligne Montage Chemise (5 postes)

```
Section: MONTAGE
  │
  ├─ Machine: piqueuse_plate
  ├─ Machine: surjeteuse
  └─ Machine: repasseuse
       │
       ├─ WS01 (piqueuse_plate) ── Opérations: OP010, OP020, OP030
       ├─ WS02 (piqueuse_plate) ── Opérations: OP040, OP050
       ├─ WS03 (surjeteuse)     ── Opérations: OP060, OP070
       ├─ WS04 (surjeteuse)     ── Opérations: OP080
       └─ WS05 (repasseuse)     ── Opérations: OP090, OP100
```

---

## 5. Vue Implantation 2D

### Outils Disponibles (Palette Vue 2D)

| Icône | Outil | Usage |
|-------|-------|-------|
| ⚙️ | **Machine** | Positionner machine sur plan (largeur/hauteur/rotation) |
| 📦 | **Zone/Section** | Délimiter atelier (rectangle coloré) |
| 🔄 | **Flux** | Lier machines (cadence pièces/h, couleur) |
| 🧱 | **Mur** | Tracer murs extérieurs/intérieurs, poteaux |
| 🚪 | **Porte** | Placer sur mur (battante, coulissante, rideau) |
| 🚶 | **Zone circulation** | Allées piétons/chariots/AGV |
| 📚 | **Rack** | Stockage (palettes 1N-4N, drive-in, cantilever) |
| 🔗 | **Convoyeur** | Transport automatisé |
| 🤖 | **Chemin AGV** | Trajectoires véhicules autonomes |

### Grille et Aimantation

- **Grille** : 100 mm par défaut (configurable)
- **Snap** : Les objets s'aimantent à la grille
- **Échelle** : 1 px = 1 mm (affichage métrique)

### Exemple : Implantation Atelier 20m × 15m

```
┌─────────────────────────────────────────────────┐
│  MUR EXTÉRIEUR (200mm)                          │
│  ┌──────────────┐  ┌──────────────┐             │
│  │  ZONE MONTAGE│  │  ZONE FINITION│            │
│  │  (vert)      │  │  (bleu)       │            │
│  │  WS01 ●──────● WS02             │            │
│  │  WS03 ●──────● WS04             │            │
│  │              │                  │            │
│  └──────────────┘  └──────────────┘             │
│        │                  │                     │
│        ▼                  ▼                     │
│  ┌──────────────────────────────────────┐       │
│  │        ZONE EXPÉDITION (orange)       │       │
│  │        RACK palettes_3N ●             │       │
│  └──────────────────────────────────────┘       │
│                                                 │
│  🚪 PORTES sur murs extérieurs                  │
│  🚶 ALLÉES 3m piétons / 4m chariots             │
└─────────────────────────────────────────────────┘
```

### Configurer une Machine (Layout)

1. Sélectionner l'outil **Machine** (⚙️)
2. Clic sur le plan → machine placée
3. Dans l'inspecteur :
   - **Type Machine** : `piqueuse_plate`
   - **Nom** : `Piqueuse 1`
   - **Largeur (mm)** : `2000`
   - **Hauteur (mm)** : `1500`
   - **Rotation (°)** : `0` ou `90`
   - **Section** : `MONTAGE`

---

## 6. Vue 3D

### Navigation

| Action | Souris / Clavier |
|--------|------------------|
| **Orbiter** | Clic gauche + glisser |
| **Pan** | Clic droit + glisser / `Shift` + gauche |
| **Zoom** | Molette / `+/-` |
| **Réinitialiser** | `R` |
| **Vue de dessus** | `T` |
| **Vue face** | `F` |

### Rendu

- **Machines** : Boîtes colorées par type
- **Murs** : Extrusion hauteur configurable
- **Zones** : Planchers colorés semi-transparents
- **Flux** : Flèches animées (si cadence > 0)
- **AGV** : Cubes mobiles sur chemins

### Exporter Vue 3D

- `F12` : Capture d'écran PNG
- Menu **Vue > Exporter OBJ/GLTF** pour CAO

---

## 7. Équilibrage de Ligne

### Onglet "Équilibrage" (Bas)

#### Paramètres

| Paramètre | Description | Valeur par défaut |
|-----------|-------------|-------------------|
| **Algorithme** | `CP-SAT` (optimal) ou `RPW` (rapide) | CP-SAT |
| **Objectif** | `Minimiser postes` / `Minimiser cycle` / `Équilibrer charge` | Minimiser postes |
| **Max postes** | Limite supérieure (0 = illimité) | 0 |
| **Temps limite (s)** | Timeout solveur CP-SAT | 30 |
| **Cadence cible (p/h)** | Objectif de production | 60 |

#### Lancer l'Équilibrage

1. Onglet **Équilibrage** (en bas)
2. Choisir algorithme et objectif
3. Cliquer **"▶️ Lancer l'équilibrage"**
4. Résultats dans l'onglet **Résultats**

### Résultats - Yamazumi Chart

Le graphique Yamazumi affiche par poste :
- **Bleu (VA)** : Valeur Ajoutée
- **Orange (NVA)** : Non Valeur Ajoutée
- **Gris (ATTENTE)** : Temps d'attente

**Interaction** :
- Glisser une opération d'une barre à une autre pour rééquilibrer manuellement
- Clic droit sur barre → "Optimiser ce poste"

### Diagramme Spaghetti

Heatmap des déplacements opérateurs :
- **Rouge** : Forte congestion
- **Jaune** : Modéré
- **Vert** : Fluide

Métriques : distance totale, croisements, goulots.

### Diagramme Gantt Multi-Pistes

| Piste | Contenu |
|-------|---------|
| **Poste** | Occupation stations dans le temps |
| **Ouvrier** | Planning personnel |
| **Machine** | Utilisation équipements |
| **AGV** | Trajets véhicules |

**Contrôles** : Lecture ▶️, Pause ⏸️, Vitesse 0.5x-4x, Curseur temps

---

## 8. Exemples Pratiques

### Exemple 1 : Ligne Simple 5 Postes (T-shirt)

**Données :**
- 10 opérations, durée totale 12.5 min
- Cadence cible : 60 p/h → Temps de cycle = 1.0 min
- 3 types machines : piqueuse_plate, surjeteuse, repasseuse

**Étapes :**
1. Créer section `MONTAGE_TSHIRT`
2. Ajouter 3 machines types
3. Créer 5 postes (WS01-WS05) avec machines affectées
4. Ajouter 5 ouvriers avec compétences correspondantes
5. Saisir 10 opérations avec durées et précédences
6. Connecter opérations par précédence (graphe)
7. Lancer équilibrage CP-SAT → Objectif: Minimiser postes
8. Résultat : 4 postes au lieu de 5 (gain 20%)

**Fichier exemple** : `examples/tshirt_line.json`

### Exemple 2 : Usine Complète 3 Sections

**Structure :**
```
USINE
├── SECTION COUPE (1000m²)
│   ├── 2 machines découpe_laser
│   ├── 3 postes découpe
│   └── 4 ouvriers
├── SECTION MONTAGE (2000m²)
│   ├── 8 piqueuse_plate
│   ├── 4 surjeteuse
│   ├── 12 postes
│   └── 15 ouvriers
└── SECTION FINITION (800m²)
    ├── 3 repasseuse
    ├── 2 poste contrôle
    ├── 5 postes
    └── 6 ouvriers
```

**Implantation 2D :**
- Murs extérieurs 30m × 40m
- Zones colorées par section
- Allées 3m (piétons) / 4m (chariots)
- Racks expédition près porte section FINITION
- Chemins AGV entre COUPE → MONTAGE → FINITION

**Équilibrage global :**
- Objectif : 120 p/h
- CP-SAT trouve solution 22 postes (vs 25 initial)
- Yamazumi montre charge équilibrée ±5%

**Fichier exemple** : `examples/factory_complete.json`

### Exemple 3 : Import depuis Fichiers CSV/Excel

**Format opérations (operations.csv) :**
```csv
op_id,name,duration_min,predecessors,machine_type,skills,section,task_type
OP010,Montage épaule,0.55,,piqueuse_plate,couture_droite,MONTAGE,VA
OP020,Montage manche,0.48,OP010,piqueuse_plate,couture_droite,MONTAGE,VA
OP030,Surjet bas,0.32,OP020,surjeteuse,couture_courbe,MONTAGE,VA
```

**Import :**
```python
# Dans terminal intégré (onglet Terminal)
from engine.parsers import parse_operations_csv
ops = parse_operations_csv("operations.csv")
# Puis créer nœuds via API ou script
```

---

## 9. Référence Rapide

### Formats de Fichiers Supportés

| Format | Import | Export | Usage |
|--------|--------|--------|-------|
| **JSON** (.json) | ✅ | ✅ | Projet complet (nœuds, arêtes, layout, building) |
| **Excel** (.xlsx) | ❌ | ✅ | Rapport équilibrage + Yamazumi + Gantt |
| **CSV** (.csv) | ✅* | ❌ | Opérations, postes, ouvriers (via script) |
| **PDF** (.pdf) | ❌ | ✅ | Rapport visuel (graphiques) |
| **PNG** (.png) | ❌ | ✅ | Captures Gantt, Yamazumi, Spaghetti |
| **OBJ/GLTF** | ❌ | ✅ | Modèle 3D pour CAO/Blender |
| **ONNX** | ❌ | ✅ | Modèle ML pour prédiction |

*Via script Python dans terminal intégré

### Types Machines Préconfigurés

| Code | Nom | Dimensions std (mm) | Icône SVG |
|------|-----|---------------------|-----------|
| `piqueuse_plate` | Piqueuse plate | 2000×1500 | `machines/piqueuse_plate.svg` |
| `surjeteuse` | Surjeteuse | 1800×1200 | `machines/surjeteuse.svg` |
| `repasseuse` | Repasseuse tunnel | 3000×2000 | `machines/repasseuse.svg` |
| `decoupe_laser` | Découpe laser | 4000×2500 | `machines/decoupe_laser.svg` |
| `brodeuse` | Brodeuse multi-têtes | 2500×2000 | `machines/brodeuse.svg` |
| `colleuse` | Colleuse thermocollant | 1500×1000 | `machines/colleuse.svg` |
| `controle` | Poste contrôle qualité | 1200×800 | `machines/controle.svg` |
| `emballage` | Poste emballage | 1500×1200 | `machines/emballage.svg` |

*Ajouter vos machines dans `gui/svg_icons.py` → `MACHINE_SVGS`*

### Raccourcis Clavier Canvas

| Touche | Action |
|--------|--------|
| `Espace` + Glisser | Pan (déplacer vue) |
| `Molette` | Zoom in/out |
| `Ctrl + Molette` | Zoom rapide |
| `Suppr` | Supprimer sélection |
| `Ctrl + C / V` | Copier / Coller nœud |
| `Ctrl + D` | Dupliquer nœud |
| `G` | Afficher/masquer grille |
| `A` | Ajuster vue (fit all) |

### Dépannage Courant

| Problème | Solution |
|----------|----------|
| **GUI ne lance pas** | `pip install --upgrade PySide6` + vérifier `.venv` activé |
| **Vue 3D noire** | Mettre à jour drivers GPU / `export MESA_GL_VERSION_OVERRIDE=3.3` |
| **Équilibrage infini** | Réduire "Temps limite" ou passer à RPW |
| **Nœuds invisibles** | Vérifier mode Vue (Logique vs 2D) dans barre d'outils |
| **Connexions impossibles** | Ports : sortie (droite) → entrée (gauche) uniquement |

### Fichiers de Projet

```
textile-line-balancer/
├── gui/
│   ├── main.py           # Point d'entrée (< 30 lignes)
│   ├── main_window.py    # MainWindow: composition des vues
│   ├── balance_bar.py    # BalanceBar: contrôles solveur + terminal
│   ├── project_io.py     # Import/export projets
│   ├── theme.py          # Source unique couleurs, styles, icônes
│   ├── node_editor.py    # Vue Logique: éditeur graphe
│   ├── inspector.py      # Panneau propriétés unifié (3 vues)
│   ├── viz_widgets.py    # Yamazumi, Spaghetti, Gantt, Résultats
│   ├── balance_runner.py # Worker thread d'équilibrage
│   ├── layout_toolbar.py # Barre d'outils Implantation 2D
│   ├── layout_view_2d.py # Vue 2D implantation
│   ├── svg_icons.py      # Loader icônes SVG (machines + UI)
│   ├── yamazumi.py       # Graphique Yamazumi
│   ├── spaghetti.py      # Diagramme spaghetti
│   ├── timeline_gantt.py # Gantt multi-pistes
│   ├── view3d.py         # Rendu 3D VisPy
│   └── assets/           # Icônes SVG (25) + ATTRIBUTION.txt
├── engine/
│   ├── models.py         # Modèles v1 (dataclasses)
│   ├── models_v2.py      # Modèles V2 (UnifiedProject, BuildingLayout)
│   ├── adapters.py       # Pont v1 <-> v2 (UnifiedProject <-> LineBalancingProblem)
│   ├── builders.py       # Construction du problème depuis un workflow
│   ├── solvers/          # CP-SAT, RPW, ML
│   └── parsers.py        # Import CSV/JSON
├── tests/                # 69 tests pytest (49 moteur + 20 GUI)
├── data/                 # Fichiers exemples
├── docs/
│   └── manual_utilisateur.md  # Ce fichier
├── project.json          # Projet courant (auto-save)
└── README.md
```

---

## Annexe : Commandes Utiles

```bash
# Lancer avec logs verbeux
.venv/bin/python gui/main.py --verbose

# Exécuter équilibrage en ligne de commande (headless)
.venv/bin/python -c "
from engine.solvers.cp_sat_solver import solve_cp_sat
from engine.parsers import load_project
problem = load_project('project.json')
result = solve_cp_sat(problem, time_limit=60)
print(result)
"

# Générer rapport Excel seul
.venv/bin/python -c "
from gui.main import export_excel_report
export_excel_report('project.json', 'rapport.xlsx')
"

# Valider fichier projet
.venv/bin/python -m json.tool project.json > /dev/null && echo "JSON valide"
```

---

**Support** : Consultez `README.md` pour liens GitHub, issues, et contributions.

*Document généré pour Textile Line Balancer v2.0 - Juillet 2026*