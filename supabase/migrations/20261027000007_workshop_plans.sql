-- Cartographie de l'atelier
-- workshop_plans : plans d'atelier (salle en mètres, fond importé calibré, éléments dessinés :
--                  murs, poteaux, portes/issues, allées, zones, machines avec lien vers un poste WS).
-- line_layouts   : + plan_id / assignment (stations d'un calcul placées sur les machines d'un plan).
-- Stockage       : bucket privé « workshop-plans », un dossier par atelier (<org_id>/...).
-- Sécurité : RLS stricte par atelier (membres en lecture ; owner/admin/methodes/chef_ligne en écriture ;
-- suppression owner/admin/methodes). Le super admin n'a aucun accès particulier.

-- ---------------------------------------------------------------- Plans d'atelier
create table if not exists public.workshop_plans (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null references public.organizations(id) on delete cascade,
  name          text not null default 'Plan de l''atelier' check (length(name) between 1 and 120),
  version       text not null default 'actuel' check (version in ('actuel','projet','archive')),
  width_m       numeric(7,2) not null default 30 check (width_m between 2 and 400),
  length_m      numeric(7,2) not null default 20 check (length_m between 2 and 400),
  background    jsonb check (background is null or (jsonb_typeof(background) = 'object'
                                                    and pg_column_size(background) <= 4096)),
  elements      jsonb not null default '[]'::jsonb check (jsonb_typeof(elements) = 'array'
                                                          and pg_column_size(elements) <= 1048576),
  settings      jsonb not null default '{}'::jsonb check (jsonb_typeof(settings) = 'object'
                                                          and pg_column_size(settings) <= 8192),
  machine_count integer generated always as
                (jsonb_array_length(jsonb_path_query_array(elements, '$[*] ? (@.kind == "machine")'))) stored,
  created_by    uuid references auth.users(id) on delete set null default auth.uid(),
  updated_by    uuid references auth.users(id) on delete set null default auth.uid(),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (id, org_id)
);
create index if not exists workshop_plans_org_idx on public.workshop_plans(org_id, updated_at desc);
create index if not exists workshop_plans_created_by_idx on public.workshop_plans(created_by);
create index if not exists workshop_plans_updated_by_idx on public.workshop_plans(updated_by);

drop trigger if exists workshop_plans_touch on public.workshop_plans;
create trigger workshop_plans_touch before update on public.workshop_plans
  for each row execute function public.touch_updated_at();

-- Auteurs forcés, atelier figé ; le fond doit être rangé dans le dossier de l'atelier.
create or replace function private.workshop_plan_guard() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_path text;
begin
  if tg_op = 'INSERT' then
    new.created_by := coalesce((select auth.uid()), new.created_by);
  else
    new.org_id := old.org_id;
    new.created_by := old.created_by;
  end if;
  new.updated_by := coalesce((select auth.uid()), new.updated_by);
  v_path := new.background ->> 'path';
  if v_path is not null and v_path <> '' and split_part(v_path, '/', 1) <> new.org_id::text then
    raise exception 'Fond de plan hors du dossier de l''atelier' using errcode = '42501';
  end if;
  return new;
end $$;
revoke all on function private.workshop_plan_guard() from public, anon, authenticated;
drop trigger if exists workshop_plans_guard on public.workshop_plans;
create trigger workshop_plans_guard before insert or update on public.workshop_plans
  for each row execute function private.workshop_plan_guard();

alter table public.workshop_plans enable row level security;
drop policy if exists wplans_read on public.workshop_plans;
create policy wplans_read on public.workshop_plans for select to authenticated
  using ((select private.is_member(org_id)));
drop policy if exists wplans_insert on public.workshop_plans;
create policy wplans_insert on public.workshop_plans for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists wplans_update on public.workshop_plans;
create policy wplans_update on public.workshop_plans for update to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])))
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists wplans_delete on public.workshop_plans;
create policy wplans_delete on public.workshop_plans for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes'])));

revoke update, truncate, references, trigger on public.workshop_plans from authenticated;
grant select, insert, delete on public.workshop_plans to authenticated;
grant update (name, version, width_m, length_m, background, elements, settings) on public.workshop_plans to authenticated;
revoke all on public.workshop_plans from anon;

-- ---------------------------------------------------------------- Implantation d'un calcul sur un plan
alter table public.line_layouts add column if not exists plan_id uuid;
alter table public.line_layouts add column if not exists assignment jsonb not null default '{}'::jsonb;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'line_layouts_plan_fk') then
    alter table public.line_layouts add constraint line_layouts_plan_fk
      foreign key (plan_id, org_id) references public.workshop_plans(id, org_id) on delete set null (plan_id);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'line_layouts_assignment_chk') then
    alter table public.line_layouts add constraint line_layouts_assignment_chk
      check (jsonb_typeof(assignment) = 'object' and pg_column_size(assignment) <= 65536);
  end if;
end $$;
create index if not exists line_layouts_plan_idx on public.line_layouts(plan_id);
grant update (plan_id, assignment) on public.line_layouts to authenticated;

-- ---------------------------------------------------------------- Stockage des fonds de plan
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('workshop-plans', 'workshop-plans', false, 10485760, array['image/png','image/jpeg','image/webp'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
                                allowed_mime_types = excluded.allowed_mime_types;

-- Atelier propriétaire d'un objet : premier dossier du chemin (null si ce n'est pas un uuid).
create or replace function private.storage_org(p_name text) returns uuid
language plpgsql immutable set search_path = '' as $$
begin
  return split_part(p_name, '/', 1)::uuid;
exception when others then
  return null;
end $$;
revoke all on function private.storage_org(text) from public, anon;
grant execute on function private.storage_org(text) to authenticated;

drop policy if exists wplans_files_read on storage.objects;
create policy wplans_files_read on storage.objects for select to authenticated
  using (bucket_id = 'workshop-plans' and (select private.is_member(private.storage_org(name))));
drop policy if exists wplans_files_insert on storage.objects;
create policy wplans_files_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'workshop-plans'
              and (select private.has_role(private.storage_org(name), array['owner','admin','methodes','chef_ligne'])));
drop policy if exists wplans_files_update on storage.objects;
create policy wplans_files_update on storage.objects for update to authenticated
  using (bucket_id = 'workshop-plans'
         and (select private.has_role(private.storage_org(name), array['owner','admin','methodes','chef_ligne'])))
  with check (bucket_id = 'workshop-plans'
              and (select private.has_role(private.storage_org(name), array['owner','admin','methodes','chef_ligne'])));
drop policy if exists wplans_files_delete on storage.objects;
create policy wplans_files_delete on storage.objects for delete to authenticated
  using (bucket_id = 'workshop-plans'
         and (select private.has_role(private.storage_org(name), array['owner','admin','methodes'])));
