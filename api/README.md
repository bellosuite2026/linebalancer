# API Textile Line Balancer (v0.1, MVP)

Adaptateur HTTP au-dessus de `engine/`. Aucune logique d'équilibrage ici.

## Lancer

```bash
pip install -e ".[api]"         # ou: pip install -r requirements-api.txt
uvicorn api.main:app --reload   # doc interactive : http://localhost:8000/docs
pytest tests/test_api.py -q
```

Docker : `docker build -t tlb-api . && docker run -p 8000:8000 -e TLB_API_KEYS=demo tlb-api`

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `TLB_API_KEYS` | vide (auth coupée) | Clés autorisées, séparées par des virgules (1 clé = 1 atelier) |
| `TLB_SYNC_TIME_LIMIT` | 15 | Plafond (s) des calculs synchrones |
| `TLB_JOB_TIME_LIMIT` | 300 | Plafond (s) des calculs en file |
| `TLB_JOB_WORKERS` | 2 | Calculs simultanés |
| `TLB_MAX_UPLOAD_BYTES` | 5 Mo | Taille max d'un import |
| `TLB_MAX_OPERATIONS` | 500 | Opérations max par problème |

## Routes

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/health` | état, version, solveurs disponibles |
| GET | `/v1/solvers` | liste des solveurs |
| POST | `/v1/import/sam` · `/workstations` · `/workers` | fichier (CSV/XLSX/JSON, champ `file`) -> JSON |
| POST | `/v1/import/problem` | `sam` + `workstations` + `workers` + `target_cycle_time` -> problème + diagnostic |
| POST | `/v1/precheck` | diagnostic de faisabilité (`ProblemIn`) |
| POST | `/v1/balance` | équilibrage synchrone `{problem, solver: rpw|cp_sat, time_limit_seconds}` |
| POST | `/v1/min-cycle` | cadence minimale `{problem, solver, precision}` |
| POST | `/v1/export/json` | équilibrage -> fichier JSON téléchargeable |
| POST | `/v1/jobs` | calcul en file `{kind: balance|min_cycle, balance|min_cycle: {...}}` -> 202 + id |
| GET | `/v1/jobs/{id}` · `/v1/jobs/{id}/export.json` | statut/résultat · export |

Le résultat expose `success` (verdict du solveur) **et** `compliant` (= success sans violation
détectée par `engine.diagnostics.validate_result`), plus la liste `violations`.

## Comptes et ateliers (Supabase)

Actif si `TLB_SUPABASE_URL` et `TLB_SUPABASE_ANON_KEY` (clé *publishable*) sont définis.
Le navigateur se connecte avec Supabase Auth (supabase-js) puis appelle l'API avec
`Authorization: Bearer <access_token>`. Le jeton est vérifié localement (JWKS ES256).
L'API transmet ce jeton à Postgres : **l'isolation entre ateliers est garantie par RLS**,
pas seulement par le code Python. Aucune clé service n'est nécessaire.

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/v1/me` | utilisateur + ateliers + abonnement |
| POST | `/v1/orgs` | créer un atelier `{name, country}` (propriétaire, essai 30 j) |
| GET | `/v1/orgs/{org}` | atelier, rôle, offre et limites, membres |
| GET/POST | `/v1/orgs/{org}/lines` · DELETE `/lines/{id}` | lignes de production (quota de l'offre) |
| GET/POST | `/v1/orgs/{org}/problems` · GET `/problems/{id}` | gammes enregistrées (SAM + postes + ouvriers) |
| POST | `/v1/orgs/{org}/runs` | calcul historisé `{kind, solver, problem_id | problem, line_id}` -> 202 |
| GET | `/v1/orgs/{org}/runs` · `/runs/{id}` · `/runs/{id}/export.json` | historique, détail, export |

Rôles : `owner`, `admin`, `methodes`, `chef_ligne` (peut lancer des calculs), `lecteur` (lecture seule).
Quotas appliqués en base : lignes, utilisateurs, opérations par gamme ; calculs refusés si essai expiré.
Les routes sans état (`/v1/precheck`, `/v1/balance`…) acceptent aussi le jeton utilisateur ;
`X-API-Key` reste disponible pour les intégrations.

Variables : `TLB_SUPABASE_URL`, `TLB_SUPABASE_ANON_KEY`, optionnelles
`TLB_SUPABASE_SERVICE_KEY` (mise à jour des calculs très longs), `TLB_CORS_ORIGINS`.

## Limites connues

- File en mémoire : les calculs sont perdus au redémarrage (prod : Redis + arq ou Postgres).
- (corrigé en moteur v2.2) CP-SAT ne laisse plus de station machine sans poste physique.

## Options d'équilibrage (moteur v2.2, champs facultatifs de `problem`)

| Champ | Défaut | Rôle |
|---|---|---|
| `max_machines_per_station` | 3 | Machines voisines qu'un ouvrier peut tenir (1 = ancien comportement) |
| `machine_change_time` | 0 | Minutes/pièce ajoutées par machine supplémentaire dans une station |
| `section_policy` | `prefer` | `strict` : jamais deux sections dans une station |
| `split_mode` | `share` | Opération > cadence : parts pleines + reliquat combinable ; `parallel` : postes égaux |
| `workers[].skill_levels` | `{}` | Rendement par compétence (matrice de polyvalence) |

Chaque station du résultat porte aussi `machine_types`, `workstations` (un poste par type),
`shares` (minutes d'une opération partagée tenues par la station), `worker_time` (temps réel au
rendement de l'ouvrier) et `worker_efficiency`. Nouveau code de diagnostic : `SKILL_CAPACITY`.

## Super admin (propriétaire du SaaS) — `/v1/admin/*`

Réservé aux comptes listés dans `private.platform_admins` (par e-mail, adresse confirmée).
L'API vérifie le jeton Supabase puis `admin_whoami` ; chaque fonction SQL `private.admin_*`
refait le contrôle. Aucune clé secrète : appels avec le jeton de l'utilisateur.

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/v1/admin/overview` | gains en TND (12 mois, par offre), abonnements actifs, essais, MRR |
| GET | `/v1/admin/users` | utilisateurs : inscription, dernière connexion, nb de calculs, ateliers/offre, suspendu |
| POST | `/v1/admin/users/{id}/suspend` | `{"suspended": true\|false}` (déconnexion + accès coupé immédiatement) |
| DELETE | `/v1/admin/users/{id}` | `{"confirm_email": "..."}` ; supprime aussi ses ateliers sans autre propriétaire |
| GET | `/v1/admin/orgs` | ateliers : offre, statut, échéance, membres, lignes, calculs, total payé |
| PUT | `/v1/admin/orgs/{id}/plan` | `{"plan_code", "status", "trial_ends_at"?, "current_period_end"?}` |
| DELETE | `/v1/admin/orgs/{id}` | `{"confirm_name": "..."}` |
| GET/POST | `/v1/admin/payments` | liste / saisie manuelle d'un paiement (TND, période, mode, référence ; `activate` = passe l'atelier sur l'offre jusqu'à la fin de période) |
| DELETE | `/v1/admin/payments/{id}` | suppression d'une saisie erronée |

Le super admin n'a ni essai ni quota sur ses propres ateliers (seul le garde-fou CPU
`TLB_MAX_OPERATIONS` s'applique) ; il n'accède pas aux données métier des autres ateliers.
Test réel : `scripts/e2e_admin.py`.

## Suivi de production (tablette) — `/v1/orgs/{org}/production/sessions`
Module `api/routes_production.py` (routes) + `api/production.py` (plan figé, indicateurs, exports). Tables `production_sessions` / `production_entries` (migration `20261027000005_production_tracking.sql`), RLS par atelier : membres en lecture, owner/admin/methodes/chef_ligne en écriture, aucun accès particulier du super admin.

| Méthode | Route | Rôle |
|---|---|---|
| GET/POST | `/production/sessions` | lister / ouvrir une session depuis un calcul terminé (`run_id`, `model`, `line_id`, `session_date`, `shift_start` « HH:MM », `shift_hours`, `target_per_hour` = 60 / cycle réel par défaut) |
| GET/PATCH | `/production/sessions/{id}` | détail + plan figé / `status` open\|closed, objectif, horaires |
| GET/POST | `/production/sessions/{id}/entries` | saisies ; POST = envoi groupé idempotent (`client_id` généré par la tablette : renvoyer le même met à jour la saisie — fin d'arrêt, annulation `voided`) |
| PATCH | `/production/sessions/{id}/entries/{eid}` | corriger une saisie |
| GET | `/production/sessions/{id}/dashboard` | réalisé vs objectif par heure et par station, efficience, goulot observé/calculé, encours, arrêts par motif, alertes (< 80 %, arrêt > 15 min) |
| GET | `/production/sessions/{id}/export.xlsx` \| `.pdf` | rapport de la journée |

Motifs d'arrêt : `panne`, `manque_fourniture`, `absence`, `changement_modele`, `autre`. Une session fermée refuse toute saisie (déclencheur SQL). E2E : `scripts/e2e_production.py`.

## Jumeau numérique (v0.4.0)

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/v1/orgs/{org}/runs/{id}/twin` | plan de ligne (stations, opérations + compétences, ouvrières), implantation, sessions, simulations |
| PUT | `/v1/orgs/{org}/runs/{id}/layout` | `{kind: line\|u\|free, positions: {"<station>": {x, y}}}` (mètres) |
| POST | `/v1/orgs/{org}/runs/{id}/simulate` | 1–3 scénarios, tâche de fond → 202 + ligne `twin_simulations` |
| GET | `/v1/orgs/{org}/runs/{id}/simulations` | historique |
| GET | `/v1/orgs/{org}/simulations/{sid}` (+ `/export.xlsx`, `/export.pdf`) | statut, résultats, comparaison |
| GET | `/v1/orgs/{org}/runs/{id}/twin/sync?session_id=&order_qty=&order_done=` | réel vs simulé, prévision fin de journée / commande |

Scénario : `name`, `run_id` (autre modèle), `absent` [ids ouvrières], `reassign` (compétences), `operators` {station: n},
`breakdowns` [{station, start_min, duration_min}], `bundle_size` (1–100), `efficiency_pct`, `variability_pct`,
`shift_minutes` (≤ 600 : offre Render gratuite), `seed`.
Modèle : ligne série dans l'ordre des stations, paquets d'encours, ouvrières = ressources SimPy (une ouvrière
partagée sert deux postes), plafond d'encours CONWIP = Σ(opératrices + 1) paquets, transport = 0,1 min + distance / 50 m/min.

## Plan d'atelier / cartographie (v0.5.0)

| Méthode | Route | Rôle |
|---|---|---|
| GET/POST | `/v1/orgs/{org}/workshop-plans` | plans de l'atelier (résumé) / créer `{name, version: actuel\|projet\|archive, width_m, length_m, background, elements, settings}` |
| GET/PUT/DELETE | `/v1/orgs/{org}/workshop-plans/{pid}` | plan complet / modifier (`clear_background`) / supprimer (owner, admin, méthodes) |
| GET | `/v1/orgs/{org}/workshop-plans/{pid}/inventory` | postes (WS) déduits des machines (une machine = un poste, chariots exclus), temps de déplacement dérivé |
| GET | `/v1/orgs/{org}/workshop-catalog` | bibliothèque de machines (encombrements par défaut) et zones |
| POST | `/v1/orgs/{org}/runs/{id}/twin/plan` | `{plan_id, assignment?}` → stations placées sur les machines du plan, distances par les allées, analyse du flux |
| PUT | `/v1/orgs/{org}/runs/{id}/layout` | accepte aussi `{plan_id, assignment: {"<station>": [machine ids]}}` |

Éléments (mètres, y vers le bas, rotation horaire) : `wall {x1,y1,x2,y2,thickness}`, `pillar {x,y,w,d}`, `door {x,y,width,rot,exit}`,
`aisle {x,y,w,h,main}`, `zone {x,y,w,h,zone,name}`, `machine {type,x,y,w,d,rot,label,operator,status: service|panne|reserve,ws_id}`.
Fond : image dans Supabase Storage, bucket privé `workshop-plans`, chemin `<org_id>/…` (RLS par atelier) ; PDF → 1re page rendue en PNG par pdf.js dans le navigateur ; DXF → murs (LINE / LWPOLYLINE).
Géométrie : `engine/workshop.py` (A* sur grille, murs / poteaux / machines = obstacles, portes = passages). Association auto :
poste WS lié → même type (ordre des n° de machine, puis la plus proche) → famille voisine (signalée) → station « virtuelle ».
La simulation reçoit `layout.distances` ({"a-b": m}) : transport des paquets et déplacements des ouvrières au parcours réel.
« Simuler l'équilibrage sur ce plan » (front) : nouveau calcul avec `workstations` = inventaire, `machine_change_time` = aller-retour
vers la machine voisine (médiane) / 50 m/min, puis simulation comparée au calcul d'origine.
