# Base Supabase — Textile Line Balancer

Projet : `lkdlqijhlszyfkmunzyt` (Postgres 17). Migrations appliquées dans l'ordre :

1. `20261025000001_init_saas.sql` — offres, ateliers, membres, abonnements, lignes, gammes, calculs, RLS
2. `20261025000002_harden_functions.sql` — fonctions internes dans le schéma `private` (hors API REST)
3. `20261025000003_trigger_membership_guard.sql` — refus des non-membres avant les quotas

Tables (schéma `public`) :

| Table | Contenu |
|---|---|
| `plans` | offres : essai, atelier (149 TND), usine (390 TND), groupe (devis) + limites |
| `organizations` | ateliers (locataires) |
| `memberships` | utilisateur ↔ atelier + rôle |
| `subscriptions` | offre et statut par atelier (écriture : facturation/service uniquement) |
| `lines` | lignes de production |
| `problems` | gammes (JSON `ProblemIn` de l'API) |
| `runs` | calculs : paramètres, statut, synthèse KPIs, résultat complet |

Appliquer : `supabase db push` (CLI liée au projet) ou SQL Editor, fichier par fichier.
Passer un atelier en payant : `update subscriptions set plan_code='usine', status='active',
current_period_end=now()+interval '1 month' where org_id=…` (clé service / SQL Editor).
