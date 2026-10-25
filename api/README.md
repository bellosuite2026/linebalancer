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

## Limites connues

- File en mémoire : les calculs sont perdus au redémarrage (prod : Redis + arq ou Postgres).
- CP-SAT peut, selon la solution trouvée, laisser une station sans poste physique
  (`CPSatSolver._assign_workstations`, affectation gloutonne). L'API le signale (`compliant=false`).
