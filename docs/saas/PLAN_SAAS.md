---
title: "Textile Line Balancer — Plan SaaS"
subtitle: "Produit autonome pour ateliers de confection · v0.1 · 25 octobre 2026"
---

# 1. Positionnement

Produit **autonome** (distinct de BelloSuite) : l'atelier importe sa gamme SAM, ses postes et ses
ouvriers, obtient en quelques secondes un équilibrage conforme (cadence, machines, compétences),
la cadence minimale atteignable et un plan de ligne exportable. Cible initiale : ateliers et
sous-traitants de confection en Tunisie (chemise, pantalon, veste, jeans), 20 à 300 opérateurs.

# 2. Architecture

```
Navigateur (interface web)
      | HTTPS, JSON
      v
API FastAPI (api/) --> engine/ (inchangé : parseurs, precheck, RPW, CP-SAT, find_min_cycle)
      |
      +- calculs courts (RPW, precheck)  -> synchrones, < 1 s
      +- calculs longs (CP-SAT, cadence min) -> file de calculs -> workers Python
                                              (MVP : pool de threads en mémoire ;
                                               prod : Redis + arq, ou table Postgres)
Postgres : ateliers, utilisateurs, lignes/projets, historiques de calcul, abonnements
```

- **Hébergement Python hors serverless** : CP-SAT consomme du CPU plusieurs secondes à minutes,
  incompatible avec les limites Vercel/Lambda. Un conteneur Docker (API + worker) sur un VPS
  (Hetzner, OVH, Scaleway) ou une PaaS à conteneurs (Render, Railway, Fly.io).
- **Règle conservée** : `engine/` ne dépend ni de `gui/` ni de `api/`. L'API n'est qu'un adaptateur.
- L'appli de bureau PySide6 reste un client possible (mode hors-ligne / démo commerciale).

# 3. Multi-ateliers et comptes

- **Atelier = locataire (tenant)**. Toutes les données portent un `workshop_id` ; aucun accès croisé.
- Rôles : propriétaire (abonnement), méthodes / ingénieur (calculs), chef de ligne (lecture).
- MVP : une clé API par atelier (déjà en place, en-tête `X-API-Key`, isolation des calculs testée).
- V1 : comptes e-mail + mot de passe (JWT), invitations, puis connexion Google.

# 4. Périmètre MVP (6 à 8 semaines)

| Inclus | Plus tard |
|---|---|
| Import CSV/Excel SAM, postes, ouvriers (+ modèles téléchargeables) | Vue Implantation 2D / 3D |
| Diagnostic avant calcul avec actions correctives | Simulation à événements discrets |
| Équilibrage RPW et CP-SAT, cadence minimale | Scénarios what-if multiples |
| Tableau par station, Yamazumi, KPIs (efficacité, opérateurs) | Analyse capacité commande / délais |
| Export JSON + Excel (PDF en V1) | Connecteur BelloSuite / ERP |
| Comptes, ateliers, historique des calculs | Application mobile chef de ligne |
| Abonnement + essai 30 jours | Paiement en ligne automatisé |

# 5. Tarification (idée, en TND HT)

| Offre | Prix mensuel | Pour qui | Contenu |
|---|---|---|---|
| Essai | 0 (30 jours) | Découverte | Toutes fonctions, 1 ligne |
| Atelier | 149 TND | Petit atelier | 2 lignes, RPW + CP-SAT, 2 utilisateurs, export Excel |
| Usine | 390 TND | 50 à 150 opérateurs | 10 lignes, 5 utilisateurs, historique illimité, rapports PDF |
| Groupe | sur devis (~ 900 TND+) | Multi-sites | Lignes illimitées, API, formation sur site, support prioritaire |

- Annuel : 2 mois offerts. Mise en route / formation sur site facturée à part (300-600 TND).
- Paiement local : virement + facture (TVA 19 %) au départ ; Konnect ou Flouci ensuite.
- Argument de vente : 1 opérateur économisé sur une ligne ~ 1 000-1 200 TND/mois de masse salariale.

# 6. Feuille de route

1. **Fait** — API v0.1 : import, diagnostic, équilibrage, cadence min, export JSON, file de calculs, clés API, 23 tests API.
2. Corriger le bug d'affectation des postes de CP-SAT (signalé par l'API) et les données pantalon/veste.
3. Postgres + comptes + ateliers ; file Redis/arq ; Dockerfile prod.
4. Interface web : import guidé, résultats, Yamazumi, export.
5. Pilote gratuit avec 2-3 ateliers tunisiens, puis ouverture des abonnements.
