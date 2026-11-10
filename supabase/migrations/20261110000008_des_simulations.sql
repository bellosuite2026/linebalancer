-- Simulation à événements discrets (v3.0, type FlexSim) : mêmes droits que le jumeau numérique.
-- twin_simulations.kind : 'twin' (journée simulée du jumeau, v2.3) ou 'des' (modèle à événements discrets :
-- layout = modèle complet, scenarios = [{name, overrides, absent}], results = réplications + trace d'animation).
-- RLS inchangée (membres en lecture, owner/admin/methodes/chef_ligne en écriture) ; kind figé après insertion.
alter table public.twin_simulations
  add column if not exists kind text not null default 'twin' check (kind in ('twin','des'));
create index if not exists twin_simulations_run_kind_idx on public.twin_simulations(run_id, kind, created_at desc);
-- les colonnes modifiables restent (name, status, results, error, started_at, finished_at) : kind n'en fait pas partie.
