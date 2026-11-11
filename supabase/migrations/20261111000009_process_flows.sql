-- Logique personnalisée par blocs (type Process Flow) : graphes de flux enregistrés par atelier.
-- process_flows : graphe (blocs Source, File, Opération, Retard, Décision, Séparation, Assemblage, Contrôle,
--                 Groupage/Dégroupage, Ressource prendre/libérer, Attribut, Sortie + liens), lié ou non à un calcul.
-- twin_simulations.kind accepte 'flow' (résultats d'exécution d'un graphe par le moteur à événements discrets).
-- Sécurité : RLS par atelier (membres en lecture ; owner/admin/methodes/chef_ligne en écriture ;
-- suppression owner/admin/methodes). Le super admin n'a aucun accès particulier.

create table if not exists public.process_flows (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references public.organizations(id) on delete cascade,
  run_id      uuid references public.runs(id) on delete set null,
  name        text not null default 'Flux' check (length(name) between 1 and 120),
  graph       jsonb not null default '{}'::jsonb check (jsonb_typeof(graph) = 'object'
                                                      and pg_column_size(graph) <= 524288),
  created_by  uuid references auth.users(id) on delete set null default auth.uid(),
  updated_by  uuid references auth.users(id) on delete set null default auth.uid(),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists process_flows_org_idx on public.process_flows(org_id, updated_at desc);
create index if not exists process_flows_run_idx on public.process_flows(run_id);
create index if not exists process_flows_created_by_idx on public.process_flows(created_by);
create index if not exists process_flows_updated_by_idx on public.process_flows(updated_by);

drop trigger if exists process_flows_touch on public.process_flows;
create trigger process_flows_touch before update on public.process_flows
  for each row execute function public.touch_updated_at();

create or replace function private.flow_guard() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.run_id is not null and not exists (select 1 from public.runs r where r.id = new.run_id and r.org_id = new.org_id) then
    raise exception 'Calcul introuvable dans cet atelier' using errcode = '23503';
  end if;
  if tg_op = 'INSERT' then
    new.created_by := coalesce((select auth.uid()), new.created_by);
    new.updated_by := new.created_by;
  else
    new.org_id := old.org_id; new.created_by := old.created_by;
    new.updated_by := coalesce((select auth.uid()), old.updated_by);
  end if;
  return new;
end $$;
revoke all on function private.flow_guard() from public, anon, authenticated;
drop trigger if exists process_flows_guard on public.process_flows;
create trigger process_flows_guard before insert or update on public.process_flows
  for each row execute function private.flow_guard();

alter table public.process_flows enable row level security;
drop policy if exists flows_read on public.process_flows;
create policy flows_read on public.process_flows for select to authenticated
  using ((select private.is_member(org_id)));
drop policy if exists flows_insert on public.process_flows;
create policy flows_insert on public.process_flows for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists flows_update on public.process_flows;
create policy flows_update on public.process_flows for update to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])))
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists flows_delete on public.process_flows;
create policy flows_delete on public.process_flows for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes'])));

revoke update, truncate, references, trigger on public.process_flows from authenticated;
grant select, insert, delete on public.process_flows to authenticated;
grant update (name, graph, run_id) on public.process_flows to authenticated;
revoke all on public.process_flows from anon;

alter table public.twin_simulations drop constraint if exists twin_simulations_kind_check;
alter table public.twin_simulations add constraint twin_simulations_kind_check check (kind in ('twin','des','flow'));
