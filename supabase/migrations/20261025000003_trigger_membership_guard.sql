-- Les triggers BEFORE INSERT s'exécutent avant le contrôle RLS : un non-membre
-- recevait l'erreur de quota (fuite d'information). On refuse d'abord tout
-- utilisateur connecté qui n'appartient pas à l'atelier.

create or replace function private.assert_member(p_org uuid) returns void
language plpgsql stable security definer set search_path = '' as $$
begin
  if (select auth.uid()) is not null and not exists (
       select 1 from public.memberships m where m.org_id = p_org and m.user_id = (select auth.uid())) then
    raise exception 'new row violates row-level security policy' using errcode = '42501';
  end if;
end $$;
revoke all on function private.assert_member(uuid) from public, anon, authenticated;

create or replace function public.enforce_line_quota() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_plan public.plans;
begin
  perform private.assert_member(new.org_id);
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
  if (private.org_plan(new.org_id)).code is null then
    raise exception 'Abonnement inactif ou essai expiré' using errcode = 'P0001';
  end if;
  return new;
end $$;

revoke all on function public.enforce_line_quota()   from public, anon, authenticated;
revoke all on function public.enforce_member_quota() from public, anon, authenticated;
revoke all on function public.enforce_active_plan()  from public, anon, authenticated;
