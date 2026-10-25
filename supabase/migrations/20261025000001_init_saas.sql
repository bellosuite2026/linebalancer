-- Textile Line Balancer SaaS — schéma initial (Supabase / Postgres 17)
-- Multi-ateliers : chaque donnée métier porte org_id ; l'accès est filtré par RLS
-- selon l'appartenance (memberships). Les abonnements ne sont modifiables que
-- par le service (service_role / facturation), jamais par le client.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- Offres
create table if not exists public.plans (
  code             text primary key,
  name             text not null,
  price_tnd_month  numeric(10,2),          -- null = sur devis
  max_lines        int  not null,
  max_users        int  not null,
  max_operations   int  not null default 500,
  cpsat            boolean not null default true,
  pdf_reports      boolean not null default false,
  sort             int  not null default 0
);

insert into public.plans (code, name, price_tnd_month, max_lines, max_users, max_operations, cpsat, pdf_reports, sort) values
  ('essai',  'Essai 30 jours', 0,      2,   2,   300, true, false, 0),
  ('atelier','Atelier',        149,    2,   2,   300, true, false, 1),
  ('usine',  'Usine',          390,   10,   5,   500, true, true,  2),
  ('groupe', 'Groupe',         null, 100,  50,  1000, true, true,  3)
on conflict (code) do update set
  name = excluded.name, price_tnd_month = excluded.price_tnd_month,
  max_lines = excluded.max_lines, max_users = excluded.max_users,
  max_operations = excluded.max_operations, cpsat = excluded.cpsat,
  pdf_reports = excluded.pdf_reports, sort = excluded.sort;

-- ---------------------------------------------------------------- Ateliers
create table if not exists public.organizations (
  id          uuid primary key default gen_random_uuid(),
  name        text not null check (length(trim(name)) between 2 and 120),
  country     text not null default 'TN',
  created_by  uuid references auth.users(id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.memberships (
  org_id     uuid not null references public.organizations(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  role       text not null default 'methodes'
             check (role in ('owner','admin','methodes','chef_ligne','lecteur')),
  created_at timestamptz not null default now(),
  primary key (org_id, user_id)
);
create index if not exists memberships_user_idx on public.memberships(user_id);

create table if not exists public.subscriptions (
  org_id              uuid primary key references public.organizations(id) on delete cascade,
  plan_code           text not null references public.plans(code),
  status              text not null default 'trialing'
                      check (status in ('trialing','active','past_due','canceled')),
  trial_ends_at       timestamptz,
  current_period_end  timestamptz,
  updated_at          timestamptz not null default now()
);

-- ---------------------------------------------------------------- Lignes, problèmes, calculs
create table if not exists public.lines (
  id                 uuid primary key default gen_random_uuid(),
  org_id             uuid not null references public.organizations(id) on delete cascade,
  name               text not null check (length(trim(name)) between 1 and 120),
  product            text not null default '',
  target_cycle_time  numeric(10,4) check (target_cycle_time is null or target_cycle_time > 0),
  created_by         uuid references auth.users(id) on delete set null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index if not exists lines_org_idx on public.lines(org_id);

-- Un « problème » = une gamme (SAM + postes + ouvriers + cadence) au format ProblemIn de l'API.
create table if not exists public.problems (
  id                 uuid primary key default gen_random_uuid(),
  org_id             uuid not null references public.organizations(id) on delete cascade,
  line_id            uuid references public.lines(id) on delete set null,
  name               text not null,
  target_cycle_time  numeric(10,4) not null check (target_cycle_time > 0),
  operations_count   int not null default 0,
  payload            jsonb not null,
  created_by         uuid references auth.users(id) on delete set null,
  created_at         timestamptz not null default now()
);
create index if not exists problems_org_idx on public.problems(org_id, created_at desc);
create index if not exists problems_line_idx on public.problems(line_id);

create table if not exists public.runs (
  id                 uuid primary key default gen_random_uuid(),
  org_id             uuid not null references public.organizations(id) on delete cascade,
  problem_id         uuid references public.problems(id) on delete set null,
  kind               text not null check (kind in ('balance','min_cycle')),
  solver             text not null,
  status             text not null default 'queued'
                     check (status in ('queued','running','done','failed')),
  params             jsonb not null default '{}'::jsonb,
  -- Synthèse pour l'historique (évite de relire le résultat complet)
  success            boolean,
  compliant          boolean,
  stations_used      int,
  actual_cycle_time  numeric(10,4),
  efficiency         numeric(7,4),
  min_cycle_time     numeric(10,4),
  result             jsonb,
  error              text not null default '',
  created_by         uuid references auth.users(id) on delete set null,
  created_at         timestamptz not null default now(),
  started_at         timestamptz,
  finished_at        timestamptz
);
create index if not exists runs_org_idx on public.runs(org_id, created_at desc);
create index if not exists runs_problem_idx on public.runs(problem_id);

-- ---------------------------------------------------------------- Fonctions utilitaires
create or replace function public.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin new.updated_at := now(); return new; end $$;

drop trigger if exists organizations_touch on public.organizations;
create trigger organizations_touch before update on public.organizations
  for each row execute function public.touch_updated_at();
drop trigger if exists lines_touch on public.lines;
create trigger lines_touch before update on public.lines
  for each row execute function public.touch_updated_at();

create or replace function public.is_member(p_org uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.memberships m
                 where m.org_id = p_org and m.user_id = (select auth.uid()));
$$;

create or replace function public.has_role(p_org uuid, p_roles text[]) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.memberships m
                 where m.org_id = p_org and m.user_id = (select auth.uid())
                   and m.role = any (p_roles));
$$;

-- Offre en vigueur d'un atelier (essai expiré / abonnement annulé => aucune).
create or replace function public.org_plan(p_org uuid) returns public.plans
language sql stable security definer set search_path = '' as $$
  select p.* from public.subscriptions s join public.plans p on p.code = s.plan_code
  where s.org_id = p_org
    and (s.status = 'active'
         or (s.status = 'trialing' and coalesce(s.trial_ends_at, now()) >= now())
         or (s.status = 'past_due' and coalesce(s.current_period_end, now()) + interval '7 days' >= now()));
$$;

-- Création d'un atelier : propriétaire + essai 30 jours, en une transaction.
create or replace function public.create_organization(p_name text, p_country text default 'TN')
returns public.organizations
language plpgsql security definer set search_path = '' as $$
declare
  v_uid uuid := (select auth.uid());
  v_org public.organizations;
begin
  if v_uid is null then raise exception 'Authentification requise' using errcode = '42501'; end if;
  if (select count(*) from public.memberships where user_id = v_uid and role = 'owner') >= 5 then
    raise exception 'Nombre maximal d''ateliers atteint' using errcode = 'P0001';
  end if;
  insert into public.organizations (name, country, created_by)
    values (trim(p_name), coalesce(nullif(trim(p_country), ''), 'TN'), v_uid) returning * into v_org;
  insert into public.memberships (org_id, user_id, role) values (v_org.id, v_uid, 'owner');
  insert into public.subscriptions (org_id, plan_code, status, trial_ends_at)
    values (v_org.id, 'essai', 'trialing', now() + interval '30 days');
  return v_org;
end $$;

-- Quotas de l'offre : lignes et membres.
create or replace function public.enforce_line_quota() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_plan public.plans;
begin
  v_plan := public.org_plan(new.org_id);
  if v_plan.code is null then
    raise exception 'Abonnement inactif ou essai expiré' using errcode = 'P0001';
  end if;
  if (select count(*) from public.lines where org_id = new.org_id) >= v_plan.max_lines then
    raise exception 'Quota de lignes atteint pour l''offre % (% max)', v_plan.name, v_plan.max_lines
      using errcode = 'P0001';
  end if;
  return new;
end $$;
drop trigger if exists lines_quota on public.lines;
create trigger lines_quota before insert on public.lines
  for each row execute function public.enforce_line_quota();

create or replace function public.enforce_member_quota() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_plan public.plans;
begin
  if new.role = 'owner' and not exists (select 1 from public.memberships where org_id = new.org_id) then
    return new;  -- premier propriétaire (create_organization)
  end if;
  v_plan := public.org_plan(new.org_id);
  if v_plan.code is null then
    raise exception 'Abonnement inactif ou essai expiré' using errcode = 'P0001';
  end if;
  if (select count(*) from public.memberships where org_id = new.org_id) >= v_plan.max_users then
    raise exception 'Quota d''utilisateurs atteint pour l''offre % (% max)', v_plan.name, v_plan.max_users
      using errcode = 'P0001';
  end if;
  return new;
end $$;
drop trigger if exists memberships_quota on public.memberships;
create trigger memberships_quota before insert on public.memberships
  for each row execute function public.enforce_member_quota();

-- Un calcul n'est accepté que si l'abonnement est actif.
create or replace function public.enforce_active_plan() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if (public.org_plan(new.org_id)).code is null then
    raise exception 'Abonnement inactif ou essai expiré' using errcode = 'P0001';
  end if;
  return new;
end $$;
drop trigger if exists runs_active_plan on public.runs;
create trigger runs_active_plan before insert on public.runs
  for each row execute function public.enforce_active_plan();

-- Ne jamais perdre le dernier propriétaire.
create or replace function public.protect_last_owner() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if old.role = 'owner' and (tg_op = 'DELETE' or new.role <> 'owner')
     and (select count(*) from public.memberships where org_id = old.org_id and role = 'owner') <= 1
     and exists (select 1 from public.organizations where id = old.org_id) then
    raise exception 'Un atelier doit garder au moins un propriétaire' using errcode = 'P0001';
  end if;
  return coalesce(new, old);
end $$;
drop trigger if exists memberships_last_owner on public.memberships;
create trigger memberships_last_owner before update or delete on public.memberships
  for each row execute function public.protect_last_owner();

-- ---------------------------------------------------------------- RLS
alter table public.plans          enable row level security;
alter table public.organizations  enable row level security;
alter table public.memberships    enable row level security;
alter table public.subscriptions  enable row level security;
alter table public.lines          enable row level security;
alter table public.problems       enable row level security;
alter table public.runs           enable row level security;

drop policy if exists plans_read on public.plans;
create policy plans_read on public.plans for select to anon, authenticated using (true);

drop policy if exists org_read on public.organizations;
create policy org_read on public.organizations for select to authenticated
  using ((select public.is_member(id)));
drop policy if exists org_update on public.organizations;
create policy org_update on public.organizations for update to authenticated
  using ((select public.has_role(id, array['owner','admin'])))
  with check ((select public.has_role(id, array['owner','admin'])));
drop policy if exists org_delete on public.organizations;
create policy org_delete on public.organizations for delete to authenticated
  using ((select public.has_role(id, array['owner'])));

drop policy if exists mem_read on public.memberships;
create policy mem_read on public.memberships for select to authenticated
  using ((select public.is_member(org_id)));
drop policy if exists mem_insert on public.memberships;
create policy mem_insert on public.memberships for insert to authenticated
  with check ((select public.has_role(org_id, array['owner','admin'])));
drop policy if exists mem_update on public.memberships;
create policy mem_update on public.memberships for update to authenticated
  using ((select public.has_role(org_id, array['owner','admin'])))
  with check ((select public.has_role(org_id, array['owner','admin'])));
drop policy if exists mem_delete on public.memberships;
create policy mem_delete on public.memberships for delete to authenticated
  using ((select public.has_role(org_id, array['owner','admin'])) or user_id = (select auth.uid()));

drop policy if exists sub_read on public.subscriptions;
create policy sub_read on public.subscriptions for select to authenticated
  using ((select public.is_member(org_id)));

drop policy if exists lines_read on public.lines;
create policy lines_read on public.lines for select to authenticated
  using ((select public.is_member(org_id)));
drop policy if exists lines_write on public.lines;
create policy lines_write on public.lines for insert to authenticated
  with check ((select public.has_role(org_id, array['owner','admin','methodes'])));
drop policy if exists lines_update on public.lines;
create policy lines_update on public.lines for update to authenticated
  using ((select public.has_role(org_id, array['owner','admin','methodes'])))
  with check ((select public.has_role(org_id, array['owner','admin','methodes'])));
drop policy if exists lines_delete on public.lines;
create policy lines_delete on public.lines for delete to authenticated
  using ((select public.has_role(org_id, array['owner','admin','methodes'])));

drop policy if exists problems_read on public.problems;
create policy problems_read on public.problems for select to authenticated
  using ((select public.is_member(org_id)));
drop policy if exists problems_insert on public.problems;
create policy problems_insert on public.problems for insert to authenticated
  with check ((select public.has_role(org_id, array['owner','admin','methodes','chef_ligne']))
              and created_by = (select auth.uid()));
drop policy if exists problems_delete on public.problems;
create policy problems_delete on public.problems for delete to authenticated
  using ((select public.has_role(org_id, array['owner','admin','methodes'])));

drop policy if exists runs_read on public.runs;
create policy runs_read on public.runs for select to authenticated
  using ((select public.is_member(org_id)));
drop policy if exists runs_insert on public.runs;
create policy runs_insert on public.runs for insert to authenticated
  with check ((select public.has_role(org_id, array['owner','admin','methodes','chef_ligne']))
              and created_by = (select auth.uid()));
drop policy if exists runs_update on public.runs;
create policy runs_update on public.runs for update to authenticated
  using (created_by = (select auth.uid()) and (select public.is_member(org_id)))
  with check (created_by = (select auth.uid()) and (select public.is_member(org_id)));
drop policy if exists runs_delete on public.runs;
create policy runs_delete on public.runs for delete to authenticated
  using ((select public.has_role(org_id, array['owner','admin'])));

-- ---------------------------------------------------------------- Droits
revoke all on function public.create_organization(text, text) from public, anon;
grant execute on function public.create_organization(text, text) to authenticated;
revoke all on function public.org_plan(uuid) from public, anon;
grant execute on function public.org_plan(uuid) to authenticated;
revoke all on function public.is_member(uuid) from anon;
revoke all on function public.has_role(uuid, text[]) from anon;

grant select on public.plans to anon, authenticated;
grant select, update, delete on public.organizations to authenticated;
grant select, insert, update, delete on public.memberships to authenticated;
grant select on public.subscriptions to authenticated;
grant select, insert, update, delete on public.lines to authenticated;
grant select, insert, delete on public.problems to authenticated;
grant select, insert, update, delete on public.runs to authenticated;
-- Le client ne doit jamais réécrire created_by/org_id d'un calcul : on limite les colonnes modifiables.
revoke update on public.runs from authenticated;
grant update (status, success, compliant, stations_used, actual_cycle_time, efficiency,
              min_cycle_time, result, error, started_at, finished_at) on public.runs to authenticated;
revoke update on public.memberships from authenticated;
grant update (role) on public.memberships to authenticated;
revoke update on public.organizations from authenticated;
grant update (name, country) on public.organizations to authenticated;
