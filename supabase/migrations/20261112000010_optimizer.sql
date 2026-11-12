-- Optimiseur de la simulation (phase 2.3) : les recherches sont stockées dans twin_simulations (kind = 'opt').
-- layout = {"variants": [{name, layout, model}]} (implantations candidates), scenarios = [{config}],
-- results = progression pendant la recherche puis front de Pareto. RLS inchangée : membres en lecture,
-- owner/admin/methodes/chef_ligne en écriture (politiques existantes de twin_simulations), kind figé.
alter table public.twin_simulations drop constraint if exists twin_simulations_kind_check;
alter table public.twin_simulations add constraint twin_simulations_kind_check check (kind in ('twin','des','flow','opt'));
