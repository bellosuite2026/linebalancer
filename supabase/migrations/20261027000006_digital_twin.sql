-- Jumeau numérique de l'atelier
-- line_layouts     : implantation 2D d'un calcul (positions des stations en mètres, ligne / U / libre).
-- twin_simulations : simulations « et si » d'un calcul (2–3 scénarios, paramètres + résultats).
-- Sécurité : RLS stricte par atelier (membres en lecture ; owner/admin/methodes/chef_ligne en écriture).
-- Le super admin n'a aucun accès particulier.

-- ---------------------------------------------------------------- Implantations
create table if not exists public.line_layouts (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references public.organizations(id) on delete cascade,
  run_id      uuid not null references public.runs(id) on delete cascade,
  kind        text not null default 'line' check (kind in ('line','u','free')),
  positions   jsonb not null default '{}'::jsonb check (jsonb_typeof(positions) = 'object'
                                                       and pg_column_size(positions) <= 65536),
  updated_by  uuid references auth.users(id) on delete set null default auth.uid(),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (org_id, run_id)
);
create index if not exists line_layouts_run_idx on public.line_layouts(run_id);
create index if not exists line_layouts_updated_by_idx on public.line_layouts(updated_by);

-- ---------------------------------------------------------------- Simulations
create table if not exists public.twin_simulations (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null references public.organizations(id) on delete cascade,
  run_id       uuid not null references public.runs(id) on delete cascade,
  name         text not null default '' check (length(name) <= 120),
  status       text not null default 'queued' check (status in ('queued','running','done','failed')),
  scenarios    jsonb not null default '[]'::jsonb check (jsonb_typeof(scenarios) = 'array'
                                                        and jsonb_array_length(scenarios) between 1 and 3),
  layout       jsonb,
  results      jsonb,
  error        text not null default '' check (length(error) <= 2000),
  created_by   uuid references auth.users(id) on delete set null default auth.uid(),
  created_at   timestamptz not null default now(),
  started_at   timestamptz,
  finished_at  timestamptz,
  updated_at   timestamptz not null default now()
);
create index if not exists twin_simulations_org_idx on public.twin_simulations(org_id, created_at desc);
create index if not exists twin_simulations_run_idx on public.twin_simulations(run_id, created_at desc);
create index if not exists twin_simulations_created_by_idx on public.twin_simulations(created_by);

-- ---------------------------------------------------------------- Déclencheurs
drop trigger if exists line_layouts_touch on public.line_layouts;
create trigger line_layouts_touch before update on public.line_layouts
  for each row execute function public.touch_updated_at();
drop trigger if exists twin_simulations_touch on public.twin_simulations;
create trigger twin_simulations_touch before update on public.twin_simulations
  for each row execute function public.touch_updated_at();

-- Le calcul référencé doit appartenir au même atelier ; l'auteur est l'utilisateur connecté.
create or replace function private.twin_guard() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if not exists (select 1 from public.runs r where r.id = new.run_id and r.org_id = new.org_id) then
    raise exception 'Calcul introuvable dans cet atelier' using errcode = '23503';
  end if;
  if tg_op = 'INSERT' then
    if tg_table_name = 'line_layouts' then
      new.updated_by := coalesce((select auth.uid()), new.updated_by);
    else
      new.created_by := coalesce((select auth.uid()), new.created_by);
    end if;
  elsif tg_op = 'UPDATE' then
    new.org_id := old.org_id; new.run_id := old.run_id;
    if tg_table_name = 'line_layouts' then
      new.updated_by := coalesce((select auth.uid()), old.updated_by);
    else
      new.created_by := old.created_by;
    end if;
  end if;
  return new;
end $$;
revoke all on function private.twin_guard() from public, anon, authenticated;
drop trigger if exists line_layouts_guard on public.line_layouts;
create trigger line_layouts_guard before insert or update on public.line_layouts
  for each row execute function private.twin_guard();
drop trigger if exists twin_simulations_guard on public.twin_simulations;
create trigger twin_simulations_guard before insert or update on public.twin_simulations
  for each row execute function private.twin_guard();

-- ---------------------------------------------------------------- RLS
alter table public.line_layouts     enable row level security;
alter table public.twin_simulations enable row level security;

drop policy if exists layouts_read on public.line_layouts;
create policy layouts_read on public.line_layouts for select to authenticated
  using ((select private.is_member(org_id)));
drop policy if exists layouts_insert on public.line_layouts;
create policy layouts_insert on public.line_layouts for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists layouts_update on public.line_layouts;
create policy layouts_update on public.line_layouts for update to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])))
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists layouts_delete on public.line_layouts;
create policy layouts_delete on public.line_layouts for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes'])));

drop policy if exists twin_read on public.twin_simulations;
create policy twin_read on public.twin_simulations for select to authenticated
  using ((select private.is_member(org_id)));
drop policy if exists twin_insert on public.twin_simulations;
create policy twin_insert on public.twin_simulations for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists twin_update on public.twin_simulations;
create policy twin_update on public.twin_simulations for update to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])))
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists twin_delete on public.twin_simulations;
create policy twin_delete on public.twin_simulations for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));

-- ---------------------------------------------------------------- Droits (colonnes modifiables limitées)
revoke update, truncate, references, trigger on public.line_layouts from authenticated;
revoke update, truncate, references, trigger on public.twin_simulations from authenticated;
grant select, insert, delete on public.line_layouts to authenticated;
grant update (kind, positions) on public.line_layouts to authenticated;
grant select, insert, delete on public.twin_simulations to authenticated;
grant update (name, status, results, error, started_at, finished_at) on public.twin_simulations to authenticated;
revoke all on public.line_layouts from anon;
revoke all on public.twin_simulations from anon;
