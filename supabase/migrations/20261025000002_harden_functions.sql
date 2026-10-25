-- Durcissement : les fonctions internes (RLS, quotas, triggers) sortent de l'API REST.
-- Seule public.create_organization reste appelable (RPC) par un utilisateur connecté.

create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

create or replace function private.is_member(p_org uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.memberships m
                 where m.org_id = p_org and m.user_id = (select auth.uid()));
$$;

create or replace function private.has_role(p_org uuid, p_roles text[]) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.memberships m
                 where m.org_id = p_org and m.user_id = (select auth.uid())
                   and m.role = any (p_roles));
$$;

create or replace function private.org_plan(p_org uuid) returns public.plans
language sql stable security definer set search_path = '' as $$
  select p.* from public.subscriptions s join public.plans p on p.code = s.plan_code
  where s.org_id = p_org
    and (s.status = 'active'
         or (s.status = 'trialing' and coalesce(s.trial_ends_at, now()) >= now())
         or (s.status = 'past_due' and coalesce(s.current_period_end, now()) + interval '7 days' >= now()));
$$;

revoke all on function private.is_member(uuid) from public, anon;
revoke all on function private.has_role(uuid, text[]) from public, anon;
revoke all on function private.org_plan(uuid) from public, anon, authenticated;
grant execute on function private.is_member(uuid) to authenticated;
grant execute on function private.has_role(uuid, text[]) to authenticated;

-- Fonctions de trigger : pointer vers private.org_plan
create or replace function public.enforce_line_quota() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_plan public.plans;
begin
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
  if (private.org_plan(new.org_id)).code is null then
    raise exception 'Abonnement inactif ou essai expiré' using errcode = 'P0001';
  end if;
  return new;
end $$;

-- Politiques RLS réécrites sur private.*
do $$
declare r record;
begin
  for r in select schemaname, tablename, policyname from pg_policies
           where schemaname = 'public'
             and tablename in ('organizations','memberships','subscriptions','lines','problems','runs')
  loop
    execute format('drop policy %I on %I.%I', r.policyname, r.schemaname, r.tablename);
  end loop;
end $$;

create policy org_read on public.organizations for select to authenticated
  using ((select private.is_member(id)));
create policy org_update on public.organizations for update to authenticated
  using ((select private.has_role(id, array['owner','admin'])))
  with check ((select private.has_role(id, array['owner','admin'])));
create policy org_delete on public.organizations for delete to authenticated
  using ((select private.has_role(id, array['owner'])));

create policy mem_read on public.memberships for select to authenticated
  using ((select private.is_member(org_id)));
create policy mem_insert on public.memberships for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin'])));
create policy mem_update on public.memberships for update to authenticated
  using ((select private.has_role(org_id, array['owner','admin'])))
  with check ((select private.has_role(org_id, array['owner','admin'])));
create policy mem_delete on public.memberships for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin'])) or user_id = (select auth.uid()));

create policy sub_read on public.subscriptions for select to authenticated
  using ((select private.is_member(org_id)));

create policy lines_read on public.lines for select to authenticated
  using ((select private.is_member(org_id)));
create policy lines_insert on public.lines for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin','methodes']))
              and created_by = (select auth.uid()));
create policy lines_update on public.lines for update to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes'])))
  with check ((select private.has_role(org_id, array['owner','admin','methodes'])));
create policy lines_delete on public.lines for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes'])));

create policy problems_read on public.problems for select to authenticated
  using ((select private.is_member(org_id)));
create policy problems_insert on public.problems for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne']))
              and created_by = (select auth.uid()));
create policy problems_delete on public.problems for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes'])));

create policy runs_read on public.runs for select to authenticated
  using ((select private.is_member(org_id)));
create policy runs_insert on public.runs for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne']))
              and created_by = (select auth.uid()));
create policy runs_update on public.runs for update to authenticated
  using (created_by = (select auth.uid()) and (select private.is_member(org_id)))
  with check (created_by = (select auth.uid()) and (select private.is_member(org_id)));
create policy runs_delete on public.runs for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin'])));

-- Lignes : n'autoriser la modification que du nom/produit/cadence.
revoke update on public.lines from authenticated;
grant update (name, product, target_cycle_time) on public.lines to authenticated;

drop function if exists public.is_member(uuid);
drop function if exists public.has_role(uuid, text[]);
drop function if exists public.org_plan(uuid);

revoke all on function public.enforce_line_quota()   from public, anon, authenticated;
revoke all on function public.enforce_member_quota() from public, anon, authenticated;
revoke all on function public.enforce_active_plan()  from public, anon, authenticated;
revoke all on function public.protect_last_owner()   from public, anon, authenticated;
revoke all on function public.touch_updated_at()     from public, anon, authenticated;

-- Index des clés étrangères
create index if not exists lines_created_by_idx         on public.lines(created_by);
create index if not exists organizations_created_by_idx on public.organizations(created_by);
create index if not exists problems_created_by_idx      on public.problems(created_by);
create index if not exists runs_created_by_idx          on public.runs(created_by);
create index if not exists subscriptions_plan_idx       on public.subscriptions(plan_code);
