-- Super admin de la plateforme (propriétaire du SaaS) + paiements manuels en TND.
--
-- * Le rôle est stocké côté serveur : private.platform_admins (par e-mail, donc
--   appliqué dès l'inscription et la confirmation de l'adresse).
-- * Le super admin n'a ni quota ni essai sur ses propres ateliers ; il n'entre
--   PAS dans les données des autres ateliers (RLS inchangée) : il les gère via
--   les fonctions private.admin_* (security definer, contrôle is_super_admin()).
-- * Les fonctions public.admin_* sont de simples relais SECURITY INVOKER pour
--   l'API REST ; tout le travail et le contrôle se font dans private.
-- * Suspension d'un utilisateur : auth.users.banned_until (refus de connexion)
--   + suppression de ses sessions + refus immédiat par la RLS (is_member/has_role).

-- ---------------------------------------------------------------- rôle
create table if not exists private.platform_admins (
  email      text primary key check (email = lower(trim(email))),
  note       text not null default '',
  created_at timestamptz not null default now()
);
revoke all on private.platform_admins from public, anon, authenticated;
insert into private.platform_admins (email, note)
  values ('belloumi.karim.professional@gmail.com', 'Propriétaire du SaaS')
  on conflict (email) do nothing;

create or replace function private.is_super_admin() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from auth.users u
    join private.platform_admins a on a.email = lower(u.email)
    where u.id = (select auth.uid())
      and u.email_confirmed_at is not null
      and (u.banned_until is null or u.banned_until <= now()));
$$;
revoke all on function private.is_super_admin() from public, anon;
grant execute on function private.is_super_admin() to authenticated;

create or replace function private.require_super_admin() returns void
language plpgsql stable security definer set search_path = '' as $$
begin
  if not private.is_super_admin() then
    raise exception 'Réservé au super administrateur' using errcode = '42501';
  end if;
end $$;
revoke all on function private.require_super_admin() from public, anon, authenticated;

-- Journal des actions du super admin.
create table if not exists private.admin_audit (
  id         bigint generated always as identity primary key,
  actor      uuid,
  action     text not null,
  target     text not null default '',
  details    jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
revoke all on private.admin_audit from public, anon, authenticated;

create or replace function private.audit(p_action text, p_target text, p_details jsonb default '{}'::jsonb)
returns void language sql security definer set search_path = '' as $$
  insert into private.admin_audit (actor, action, target, details)
  values ((select auth.uid()), p_action, coalesce(p_target, ''), coalesce(p_details, '{}'::jsonb));
$$;
revoke all on function private.audit(text, text, jsonb) from public, anon, authenticated;

-- ---------------------------------------------------------------- utilisateurs suspendus
-- Un utilisateur suspendu perd immédiatement l'accès aux données (même avec un jeton encore valide).
create or replace function private.is_member(p_org uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.memberships m
                 join auth.users u on u.id = m.user_id
                 where m.org_id = p_org and m.user_id = (select auth.uid())
                   and (u.banned_until is null or u.banned_until <= now()));
$$;

create or replace function private.has_role(p_org uuid, p_roles text[]) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.memberships m
                 join auth.users u on u.id = m.user_id
                 where m.org_id = p_org and m.user_id = (select auth.uid())
                   and m.role = any (p_roles)
                   and (u.banned_until is null or u.banned_until <= now()));
$$;

-- ---------------------------------------------------------------- aucune limite pour le super admin
create or replace function public.enforce_line_quota() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_plan public.plans;
begin
  perform private.assert_member(new.org_id);
  if private.is_super_admin() then return new; end if;
  v_plan := private.org_plan(new.org_id);
  if v_plan.code is null then
    raise exception 'Abonnement inactif ou essai expiré' using errcode = 'P0001';
  end if;
  if (select count(*) from public.lines where org_id = new.org_id) >= v_plan.max_lines then
    raise exception 'Quota de lignes atteint pour l''offre % (% max)', v_plan.name, v_plan.max_lines
      using errcode = 'P0001';
  end if;
  return new;
end $$;

create or replace function public.enforce_member_quota() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_plan public.plans;
begin
  if new.role = 'owner' and not exists (select 1 from public.memberships where org_id = new.org_id) then
    return new;
  end if;
  perform private.assert_member(new.org_id);
  if private.is_super_admin() then return new; end if;
  v_plan := private.org_plan(new.org_id);
  if v_plan.code is null then
    raise exception 'Abonnement inactif ou essai expiré' using errcode = 'P0001';
  end if;
  if (select count(*) from public.memberships where org_id = new.org_id) >= v_plan.max_users then
    raise exception 'Quota d''utilisateurs atteint pour l''offre % (% max)', v_plan.name, v_plan.max_users
      using errcode = 'P0001';
  end if;
  return new;
end $$;

create or replace function public.enforce_active_plan() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  perform private.assert_member(new.org_id);
  if private.is_super_admin() then return new; end if;
  if (private.org_plan(new.org_id)).code is null then
    raise exception 'Abonnement inactif ou essai expiré' using errcode = 'P0001';
  end if;
  return new;
end $$;

revoke all on function public.enforce_line_quota()   from public, anon, authenticated;
revoke all on function public.enforce_member_quota() from public, anon, authenticated;
revoke all on function public.enforce_active_plan()  from public, anon, authenticated;

create or replace function public.create_organization(p_name text, p_country text default 'TN')
returns public.organizations
language plpgsql security definer set search_path = '' as $$
declare
  v_uid uuid := (select auth.uid());
  v_org public.organizations;
begin
  if v_uid is null then raise exception 'Authentification requise' using errcode = '42501'; end if;
  if exists (select 1 from auth.users where id = v_uid and banned_until > now()) then
    raise exception 'Compte suspendu' using errcode = '42501';
  end if;
  if not private.is_super_admin()
     and (select count(*) from public.memberships where user_id = v_uid and role = 'owner') >= 5 then
    raise exception 'Nombre maximal d''ateliers atteint' using errcode = 'P0001';
  end if;
  insert into public.organizations (name, country, created_by)
    values (trim(p_name), coalesce(nullif(trim(p_country), ''), 'TN'), v_uid) returning * into v_org;
  insert into public.memberships (org_id, user_id, role) values (v_org.id, v_uid, 'owner');
  insert into public.subscriptions (org_id, plan_code, status, trial_ends_at)
    values (v_org.id, 'essai', 'trialing', now() + interval '30 days');
  return v_org;
end $$;
revoke all on function public.create_organization(text, text) from public, anon;
grant execute on function public.create_organization(text, text) to authenticated;

-- ---------------------------------------------------------------- paiements (saisie manuelle, TND)
create table if not exists public.payments (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid references public.organizations(id) on delete set null,
  org_name      text not null,                       -- conservé si l'atelier est supprimé
  plan_code     text not null references public.plans(code),
  amount_tnd    numeric(12,3) not null check (amount_tnd >= 0),
  paid_at       date not null default current_date,
  period_start  date,
  period_end    date check (period_end is null or period_start is null or period_end >= period_start),
  method        text not null default 'virement'
                check (method in ('especes','virement','cheque','carte','konnect','flouci','autre')),
  reference     text not null default '',
  note          text not null default '',
  created_by    uuid references auth.users(id) on delete set null,
  created_at    timestamptz not null default now()
);
create index if not exists payments_org_idx        on public.payments(org_id);
create index if not exists payments_plan_idx       on public.payments(plan_code);
create index if not exists payments_created_by_idx on public.payments(created_by);
create index if not exists payments_paid_at_idx    on public.payments(paid_at desc);

alter table public.payments enable row level security;
drop policy if exists payments_admin_read on public.payments;
create policy payments_admin_read on public.payments for select to authenticated
  using ((select private.is_super_admin()));
revoke all on public.payments from public, anon, authenticated;
grant select on public.payments to authenticated;     -- écriture : uniquement via private.admin_*

-- ---------------------------------------------------------------- fonctions d'administration (private)
create or replace function private.admin_users() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  perform private.require_super_admin();
  return coalesce((
    select jsonb_agg(x order by x->>'created_at' desc) from (
      select jsonb_build_object(
        'id', u.id, 'email', u.email, 'created_at', u.created_at,
        'last_sign_in_at', u.last_sign_in_at, 'confirmed', u.email_confirmed_at is not null,
        'suspended', coalesce(u.banned_until > now(), false),
        'is_super_admin', exists (select 1 from private.platform_admins a where a.email = lower(u.email)),
        'runs_count', (select count(*) from public.runs r where r.created_by = u.id),
        'last_run_at', (select max(r.created_at) from public.runs r where r.created_by = u.id),
        'orgs', coalesce((select jsonb_agg(jsonb_build_object(
                    'id', o.id, 'name', o.name, 'role', m.role,
                    'plan_code', s.plan_code, 'status', s.status) order by o.created_at)
                  from public.memberships m join public.organizations o on o.id = m.org_id
                  left join public.subscriptions s on s.org_id = o.id
                  where m.user_id = u.id), '[]'::jsonb)) as x
      from auth.users u) t), '[]'::jsonb);
end $$;

create or replace function private.admin_orgs() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  perform private.require_super_admin();
  return coalesce((
    select jsonb_agg(x order by x->>'created_at' desc) from (
      select jsonb_build_object(
        'id', o.id, 'name', o.name, 'country', o.country, 'created_at', o.created_at,
        'owner_email', (select u.email from public.memberships m join auth.users u on u.id = m.user_id
                        where m.org_id = o.id and m.role = 'owner' order by m.created_at limit 1),
        'members_count', (select count(*) from public.memberships m where m.org_id = o.id),
        'lines_count', (select count(*) from public.lines l where l.org_id = o.id),
        'runs_count', (select count(*) from public.runs r where r.org_id = o.id),
        'last_run_at', (select max(r.created_at) from public.runs r where r.org_id = o.id),
        'plan_code', s.plan_code, 'status', s.status, 'trial_ends_at', s.trial_ends_at,
        'current_period_end', s.current_period_end,
        'plan_active', (private.org_plan(o.id)).code is not null,
        'paid_total_tnd', coalesce((select sum(p.amount_tnd) from public.payments p where p.org_id = o.id), 0)) as x
      from public.organizations o left join public.subscriptions s on s.org_id = o.id) t), '[]'::jsonb);
end $$;

create or replace function private.admin_set_suspended(p_user uuid, p_suspended boolean) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v_email text;
begin
  perform private.require_super_admin();
  select email into v_email from auth.users where id = p_user;
  if v_email is null then raise exception 'Utilisateur introuvable' using errcode = 'P0002'; end if;
  if p_user = (select auth.uid()) or exists (select 1 from private.platform_admins where email = lower(v_email)) then
    raise exception 'Impossible de suspendre un super administrateur' using errcode = 'P0001';
  end if;
  update auth.users
     set banned_until = case when p_suspended then now() + interval '100 years' else null end,
         updated_at = now()
   where id = p_user;
  if p_suspended then
    delete from auth.sessions where user_id = p_user;       -- déconnexion (jetons de rafraîchissement)
  end if;
  perform private.audit(case when p_suspended then 'suspend_user' else 'reactivate_user' end, v_email);
  return jsonb_build_object('id', p_user, 'email', v_email, 'suspended', p_suspended);
end $$;

create or replace function private.admin_set_plan(p_org uuid, p_plan text, p_status text,
    p_trial_ends_at timestamptz default null, p_period_end timestamptz default null) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v_sub public.subscriptions;
begin
  perform private.require_super_admin();
  if not exists (select 1 from public.organizations where id = p_org) then
    raise exception 'Atelier introuvable' using errcode = 'P0002';
  end if;
  if not exists (select 1 from public.plans where code = p_plan) then
    raise exception 'Offre inconnue : %', p_plan using errcode = '22023';
  end if;
  if p_status not in ('trialing','active','past_due','canceled') then
    raise exception 'Statut inconnu : %', p_status using errcode = '22023';
  end if;
  insert into public.subscriptions (org_id, plan_code, status, trial_ends_at, current_period_end, updated_at)
  values (p_org, p_plan, p_status,
          case when p_status = 'trialing' then coalesce(p_trial_ends_at, now() + interval '30 days') end,
          p_period_end, now())
  on conflict (org_id) do update set
    plan_code = excluded.plan_code, status = excluded.status,
    trial_ends_at = case when excluded.status = 'trialing'
                         then coalesce(p_trial_ends_at, public.subscriptions.trial_ends_at, now() + interval '30 days')
                         else public.subscriptions.trial_ends_at end,
    current_period_end = coalesce(p_period_end, public.subscriptions.current_period_end),
    updated_at = now()
  returning * into v_sub;
  perform private.audit('set_plan', p_org::text,
                        jsonb_build_object('plan', p_plan, 'status', p_status, 'period_end', p_period_end));
  return to_jsonb(v_sub);
end $$;

create or replace function private.admin_record_payment(p_org uuid, p_plan text, p_amount numeric,
    p_paid_at date default null, p_period_start date default null, p_period_end date default null,
    p_method text default 'virement', p_reference text default '', p_note text default '',
    p_activate boolean default true) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v_name text; v_pay public.payments;
begin
  perform private.require_super_admin();
  select name into v_name from public.organizations where id = p_org;
  if v_name is null then raise exception 'Atelier introuvable' using errcode = 'P0002'; end if;
  insert into public.payments (org_id, org_name, plan_code, amount_tnd, paid_at, period_start, period_end,
                               method, reference, note, created_by)
  values (p_org, v_name, p_plan, p_amount, coalesce(p_paid_at, current_date), p_period_start, p_period_end,
          coalesce(nullif(p_method, ''), 'virement'), coalesce(p_reference, ''), coalesce(p_note, ''),
          (select auth.uid()))
  returning * into v_pay;
  if p_activate then
    perform private.admin_set_plan(p_org, p_plan, 'active', null,
      case when p_period_end is not null then (p_period_end::timestamp + interval '1 day' - interval '1 second') end);
  end if;
  perform private.audit('record_payment', p_org::text,
                        jsonb_build_object('payment', v_pay.id, 'amount_tnd', p_amount, 'plan', p_plan));
  return to_jsonb(v_pay);
end $$;

create or replace function private.admin_delete_payment(p_id uuid) returns boolean
language plpgsql security definer set search_path = '' as $$
declare v_pay public.payments;
begin
  perform private.require_super_admin();
  delete from public.payments where id = p_id returning * into v_pay;
  if v_pay.id is null then return false; end if;
  perform private.audit('delete_payment', p_id::text, to_jsonb(v_pay));
  return true;
end $$;

create or replace function private.admin_payments(p_limit int default 200) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  perform private.require_super_admin();
  return coalesce((select jsonb_agg(to_jsonb(p) order by p.paid_at desc, p.created_at desc)
                   from (select * from public.payments order by paid_at desc, created_at desc
                         limit greatest(1, least(p_limit, 1000))) p), '[]'::jsonb);
end $$;

-- Supprime un utilisateur. Ses ateliers dont il est le seul propriétaire sont supprimés aussi
-- (lignes, gammes, calculs) ; les paiements restent (atelier détaché, nom conservé).
create or replace function private.admin_delete_user(p_user uuid, p_confirm_email text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v_email text; v_orgs uuid[];
begin
  perform private.require_super_admin();
  select email into v_email from auth.users where id = p_user;
  if v_email is null then raise exception 'Utilisateur introuvable' using errcode = 'P0002'; end if;
  if lower(trim(coalesce(p_confirm_email, ''))) <> lower(v_email) then
    raise exception 'Confirmation incorrecte : saisir l''e-mail exact de l''utilisateur' using errcode = '22023';
  end if;
  if p_user = (select auth.uid()) or exists (select 1 from private.platform_admins where email = lower(v_email)) then
    raise exception 'Impossible de supprimer un super administrateur' using errcode = 'P0001';
  end if;
  select coalesce(array_agg(m.org_id), '{}') into v_orgs from public.memberships m
   where m.user_id = p_user and m.role = 'owner'
     and not exists (select 1 from public.memberships o
                     where o.org_id = m.org_id and o.role = 'owner' and o.user_id <> p_user);
  delete from public.organizations where id = any (v_orgs);
  delete from auth.users where id = p_user;
  perform private.audit('delete_user', v_email, jsonb_build_object('deleted_orgs', to_jsonb(v_orgs)));
  return jsonb_build_object('email', v_email, 'deleted_orgs', coalesce(array_length(v_orgs, 1), 0));
end $$;

create or replace function private.admin_delete_org(p_org uuid, p_confirm_name text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v_name text;
begin
  perform private.require_super_admin();
  select name into v_name from public.organizations where id = p_org;
  if v_name is null then raise exception 'Atelier introuvable' using errcode = 'P0002'; end if;
  if trim(coalesce(p_confirm_name, '')) <> v_name then
    raise exception 'Confirmation incorrecte : saisir le nom exact de l''atelier' using errcode = '22023';
  end if;
  delete from public.organizations where id = p_org;
  perform private.audit('delete_org', v_name, jsonb_build_object('id', p_org));
  return jsonb_build_object('id', p_org, 'name', v_name);
end $$;

-- Tableau de bord des gains (montants en TND, à partir des paiements saisis).
create or replace function private.admin_revenue() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare v_month date := date_trunc('month', (now() at time zone 'Africa/Tunis'))::date;
begin
  perform private.require_super_admin();
  return jsonb_build_object(
    'currency', 'TND',
    'payments_count', (select count(*) from public.payments),
    'total_tnd', (select coalesce(sum(amount_tnd), 0) from public.payments),
    'this_month_tnd', (select coalesce(sum(amount_tnd), 0) from public.payments where paid_at >= v_month),
    'last_month_tnd', (select coalesce(sum(amount_tnd), 0) from public.payments
                       where paid_at >= (v_month - interval '1 month')::date and paid_at < v_month),
    'by_month', (select jsonb_agg(jsonb_build_object('month', to_char(m, 'YYYY-MM'),
                   'total_tnd', coalesce((select sum(amount_tnd) from public.payments p
                                          where p.paid_at >= m and p.paid_at < (m + interval '1 month')::date), 0),
                   'count', (select count(*) from public.payments p
                             where p.paid_at >= m and p.paid_at < (m + interval '1 month')::date)) order by m)
                 from generate_series((v_month - interval '11 months')::date, v_month, interval '1 month') g(m)),
    'by_plan', coalesce((select jsonb_agg(jsonb_build_object('plan_code', pl.code, 'plan_name', pl.name,
                   'total_tnd', coalesce(t.total, 0), 'count', coalesce(t.n, 0)) order by pl.sort)
                 from public.plans pl
                 left join (select plan_code, sum(amount_tnd) total, count(*) n from public.payments group by plan_code) t
                   on t.plan_code = pl.code), '[]'::jsonb),
    'subscriptions', (select jsonb_build_object(
        'active', count(*) filter (where s.status = 'active'),
        'trialing', count(*) filter (where s.status = 'trialing' and coalesce(s.trial_ends_at, now()) >= now()),
        'trial_expired', count(*) filter (where s.status = 'trialing' and s.trial_ends_at < now()),
        'past_due', count(*) filter (where s.status = 'past_due'),
        'canceled', count(*) filter (where s.status = 'canceled'),
        'mrr_tnd', coalesce(sum(p.price_tnd_month) filter (where s.status = 'active'), 0))
      from public.subscriptions s join public.plans p on p.code = s.plan_code),
    'active_by_plan', coalesce((select jsonb_object_agg(plan_code, n) from (
        select plan_code, count(*) n from public.subscriptions where status = 'active' group by plan_code) a), '{}'::jsonb),
    'users_count', (select count(*) from auth.users),
    'orgs_count', (select count(*) from public.organizations));
end $$;

do $$
declare f text;
begin
  foreach f in array array[
    'private.admin_users()', 'private.admin_orgs()', 'private.admin_set_suspended(uuid, boolean)',
    'private.admin_set_plan(uuid, text, text, timestamptz, timestamptz)',
    'private.admin_record_payment(uuid, text, numeric, date, date, date, text, text, text, boolean)',
    'private.admin_delete_payment(uuid)', 'private.admin_payments(int)',
    'private.admin_delete_user(uuid, text)', 'private.admin_delete_org(uuid, text)', 'private.admin_revenue()']
  loop
    execute format('revoke all on function %s from public, anon', f);
    execute format('grant execute on function %s to authenticated', f);
  end loop;
end $$;

-- ---------------------------------------------------------------- relais REST (security invoker)
create or replace function public.admin_whoami() returns boolean
language sql stable security invoker set search_path = '' as $$ select private.is_super_admin() $$;
create or replace function public.admin_users() returns jsonb
language sql stable security invoker set search_path = '' as $$ select private.admin_users() $$;
create or replace function public.admin_orgs() returns jsonb
language sql stable security invoker set search_path = '' as $$ select private.admin_orgs() $$;
create or replace function public.admin_revenue() returns jsonb
language sql stable security invoker set search_path = '' as $$ select private.admin_revenue() $$;
create or replace function public.admin_payments(p_limit int default 200) returns jsonb
language sql stable security invoker set search_path = '' as $$ select private.admin_payments(p_limit) $$;
create or replace function public.admin_set_suspended(p_user uuid, p_suspended boolean) returns jsonb
language sql security invoker set search_path = '' as $$ select private.admin_set_suspended(p_user, p_suspended) $$;
create or replace function public.admin_set_plan(p_org uuid, p_plan text, p_status text,
    p_trial_ends_at timestamptz default null, p_period_end timestamptz default null) returns jsonb
language sql security invoker set search_path = '' as $$
  select private.admin_set_plan(p_org, p_plan, p_status, p_trial_ends_at, p_period_end) $$;
create or replace function public.admin_record_payment(p_org uuid, p_plan text, p_amount numeric,
    p_paid_at date default null, p_period_start date default null, p_period_end date default null,
    p_method text default 'virement', p_reference text default '', p_note text default '',
    p_activate boolean default true) returns jsonb
language sql security invoker set search_path = '' as $$
  select private.admin_record_payment(p_org, p_plan, p_amount, p_paid_at, p_period_start, p_period_end,
                                      p_method, p_reference, p_note, p_activate) $$;
create or replace function public.admin_delete_payment(p_id uuid) returns boolean
language sql security invoker set search_path = '' as $$ select private.admin_delete_payment(p_id) $$;
create or replace function public.admin_delete_user(p_user uuid, p_confirm_email text) returns jsonb
language sql security invoker set search_path = '' as $$ select private.admin_delete_user(p_user, p_confirm_email) $$;
create or replace function public.admin_delete_org(p_org uuid, p_confirm_name text) returns jsonb
language sql security invoker set search_path = '' as $$ select private.admin_delete_org(p_org, p_confirm_name) $$;

do $$
declare f text;
begin
  foreach f in array array[
    'public.admin_whoami()', 'public.admin_users()', 'public.admin_orgs()', 'public.admin_revenue()',
    'public.admin_payments(int)', 'public.admin_set_suspended(uuid, boolean)',
    'public.admin_set_plan(uuid, text, text, timestamptz, timestamptz)',
    'public.admin_record_payment(uuid, text, numeric, date, date, date, text, text, text, boolean)',
    'public.admin_delete_payment(uuid)', 'public.admin_delete_user(uuid, text)',
    'public.admin_delete_org(uuid, text)']
  loop
    execute format('revoke all on function %s from public, anon', f);
    execute format('grant execute on function %s to authenticated', f);
  end loop;
end $$;

-- ---------------------------------------------------------------- advisors
-- create_organization : même schéma (travail en private, relais invoker en public).
create or replace function private.create_organization(p_name text, p_country text default 'TN')
returns public.organizations
language plpgsql security definer set search_path = '' as $$
declare
  v_uid uuid := (select auth.uid());
  v_org public.organizations;
begin
  if v_uid is null then raise exception 'Authentification requise' using errcode = '42501'; end if;
  if exists (select 1 from auth.users where id = v_uid and banned_until > now()) then
    raise exception 'Compte suspendu' using errcode = '42501';
  end if;
  if not private.is_super_admin()
     and (select count(*) from public.memberships where user_id = v_uid and role = 'owner') >= 5 then
    raise exception 'Nombre maximal d''ateliers atteint' using errcode = 'P0001';
  end if;
  insert into public.organizations (name, country, created_by)
    values (trim(p_name), coalesce(nullif(trim(p_country), ''), 'TN'), v_uid) returning * into v_org;
  insert into public.memberships (org_id, user_id, role) values (v_org.id, v_uid, 'owner');
  insert into public.subscriptions (org_id, plan_code, status, trial_ends_at)
    values (v_org.id, 'essai', 'trialing', now() + interval '30 days');
  return v_org;
end $$;
revoke all on function private.create_organization(text, text) from public, anon;
grant execute on function private.create_organization(text, text) to authenticated;

drop function if exists public.create_organization(text, text);
create function public.create_organization(p_name text, p_country text default 'TN')
returns public.organizations
language sql security invoker set search_path = '' as $$
  select * from private.create_organization(p_name, p_country) $$;
revoke all on function public.create_organization(text, text) from public, anon;
grant execute on function public.create_organization(text, text) to authenticated;

-- Fonction d'event trigger fournie par Supabase : inutile de l'exposer en RPC.
do $$ begin
  if exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname = 'rls_auto_enable') then
    execute 'revoke execute on function public.rls_auto_enable() from public, anon, authenticated';
  end if;
end $$;
