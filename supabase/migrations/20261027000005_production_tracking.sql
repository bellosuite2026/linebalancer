-- Suivi de production en direct (tablette atelier)
-- production_sessions : une journée / un poste de travail d'une ligne, lancée depuis un calcul
--                       d'équilibrage (le plan des stations est figé dans `plan`).
-- production_entries  : saisies de la tablette (pièces, défauts, retouches, arrêts avec motif).
-- Sécurité : RLS stricte par atelier (membres uniquement). Le super admin n'a AUCUN accès
-- particulier : il ne lit ces données que dans ses propres ateliers, comme tout membre.

-- ---------------------------------------------------------------- Sessions
create table if not exists public.production_sessions (
  id                uuid primary key default gen_random_uuid(),
  org_id            uuid not null references public.organizations(id) on delete cascade,
  line_id           uuid references public.lines(id) on delete set null,
  run_id            uuid references public.runs(id) on delete set null,
  problem_id        uuid references public.problems(id) on delete set null,
  line_name         text not null default '' check (length(line_name) <= 120),
  model             text not null default '' check (length(model) <= 120),
  session_date      date not null default (now() at time zone 'Africa/Tunis')::date,
  timezone          text not null default 'Africa/Tunis' check (length(timezone) <= 64),
  shift_start       time not null default '08:00',
  shift_hours       numeric(4,2) not null default 8 check (shift_hours > 0 and shift_hours <= 24),
  target_per_hour   numeric(10,2) not null check (target_per_hour > 0),
  cycle_time        numeric(10,4) check (cycle_time is null or cycle_time > 0),
  takt_time         numeric(10,4) check (takt_time is null or takt_time > 0),
  plan              jsonb not null default '{}'::jsonb,   -- stations, opérations, ouvriers (copie du calcul)
  status            text not null default 'open' check (status in ('open','closed')),
  opened_by         uuid references auth.users(id) on delete set null,
  closed_by         uuid references auth.users(id) on delete set null,
  closed_at         timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (id, org_id)
);
create index if not exists production_sessions_org_idx on public.production_sessions(org_id, session_date desc);
create index if not exists production_sessions_line_idx on public.production_sessions(line_id);
create index if not exists production_sessions_run_idx on public.production_sessions(run_id);
create index if not exists production_sessions_problem_idx on public.production_sessions(problem_id);

-- ---------------------------------------------------------------- Saisies
create table if not exists public.production_entries (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null unique default gen_random_uuid(),  -- idempotence de la file hors ligne
  session_id        uuid not null,
  org_id            uuid not null,
  slot_hour         smallint not null check (slot_hour between 0 and 23),  -- heure locale de l'atelier
  station           int not null check (station >= 1),
  worker_id         text check (worker_id is null or length(worker_id) <= 64),
  pieces            int not null default 0 check (pieces between 0 and 10000),
  defects           int not null default 0 check (defects between 0 and 10000),
  rework            int not null default 0 check (rework between 0 and 10000),
  downtime_reason   text check (downtime_reason in ('panne','manque_fourniture','absence','changement_modele','autre')),
  downtime_start    timestamptz,
  downtime_minutes  numeric(7,2) check (downtime_minutes is null or (downtime_minutes >= 0 and downtime_minutes <= 1440)),
  comment           text not null default '' check (length(comment) <= 500),
  voided            boolean not null default false,               -- correction : saisie annulée
  entered_by        uuid references auth.users(id) on delete set null default auth.uid(),
  entered_at        timestamptz not null default now(),            -- heure de la saisie sur la tablette
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  foreign key (session_id, org_id) references public.production_sessions(id, org_id) on delete cascade,
  check (downtime_reason is not null or (downtime_minutes is null and downtime_start is null))
);
create index if not exists production_entries_session_idx on public.production_entries(session_id, station);
create index if not exists production_entries_org_idx on public.production_entries(org_id);
create index if not exists production_entries_entered_by_idx on public.production_entries(entered_by);

-- ---------------------------------------------------------------- Déclencheurs
drop trigger if exists production_sessions_touch on public.production_sessions;
create trigger production_sessions_touch before update on public.production_sessions
  for each row execute function public.touch_updated_at();
drop trigger if exists production_entries_touch on public.production_entries;
create trigger production_entries_touch before update on public.production_entries
  for each row execute function public.touch_updated_at();

-- Ouvrir une session suppose un abonnement actif (même règle que les calculs).
drop trigger if exists production_sessions_active_plan on public.production_sessions;
create trigger production_sessions_active_plan before insert on public.production_sessions
  for each row execute function public.enforce_active_plan();

-- Une session fermée est figée ; à la fermeture on horodate.
create or replace function private.production_session_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.status = 'closed' and old.status = 'open' then
    new.closed_at := coalesce(new.closed_at, now());
    new.closed_by := coalesce(new.closed_by, (select auth.uid()));
  elsif new.status = 'open' and old.status = 'closed' then
    new.closed_at := null; new.closed_by := null;
  end if;
  return new;
end $$;
revoke all on function private.production_session_guard() from public, anon, authenticated;
drop trigger if exists production_sessions_guard on public.production_sessions;
create trigger production_sessions_guard before update on public.production_sessions
  for each row execute function private.production_session_guard();

-- Pas de saisie ni de correction sur une session fermée ; saisi_par = l'utilisateur connecté.
create or replace function private.production_entry_guard() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_status text;
begin
  -- Action de clé étrangère (compte supprimé => saisi_par à NULL) : toujours permise.
  if tg_op = 'UPDATE' and new.entered_by is null and old.entered_by is not null then
    return new;
  end if;
  select s.status into v_status from public.production_sessions s
   where s.id = coalesce(new.session_id, old.session_id);
  if tg_op = 'DELETE' and v_status is null then
    return old;   -- suppression en cascade de la session / de l'atelier
  end if;
  if v_status is distinct from 'open' then
    raise exception 'Session de production fermée : saisie impossible' using errcode = 'P0001';
  end if;
  if tg_op = 'INSERT' then
    new.entered_by := (select auth.uid());
  elsif tg_op = 'UPDATE' then
    new.entered_by := old.entered_by;
    new.session_id := old.session_id; new.org_id := old.org_id; new.client_id := old.client_id;
  end if;
  return coalesce(new, old);
end $$;
revoke all on function private.production_entry_guard() from public, anon, authenticated;
drop trigger if exists production_entries_guard on public.production_entries;
create trigger production_entries_guard before insert or update or delete on public.production_entries
  for each row execute function private.production_entry_guard();

-- ---------------------------------------------------------------- RLS
alter table public.production_sessions enable row level security;
alter table public.production_entries  enable row level security;

drop policy if exists prod_sessions_read on public.production_sessions;
create policy prod_sessions_read on public.production_sessions for select to authenticated
  using ((select private.is_member(org_id)));
drop policy if exists prod_sessions_insert on public.production_sessions;
create policy prod_sessions_insert on public.production_sessions for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne']))
              and opened_by = (select auth.uid()));
drop policy if exists prod_sessions_update on public.production_sessions;
create policy prod_sessions_update on public.production_sessions for update to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])))
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists prod_sessions_delete on public.production_sessions;
create policy prod_sessions_delete on public.production_sessions for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes'])));

drop policy if exists prod_entries_read on public.production_entries;
create policy prod_entries_read on public.production_entries for select to authenticated
  using ((select private.is_member(org_id)));
drop policy if exists prod_entries_insert on public.production_entries;
create policy prod_entries_insert on public.production_entries for insert to authenticated
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists prod_entries_update on public.production_entries;
create policy prod_entries_update on public.production_entries for update to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])))
  with check ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));
drop policy if exists prod_entries_delete on public.production_entries;
create policy prod_entries_delete on public.production_entries for delete to authenticated
  using ((select private.has_role(org_id, array['owner','admin','methodes','chef_ligne'])));

-- ---------------------------------------------------------------- Droits (colonnes modifiables limitées)
-- Supabase accorde ALL par défaut sur les nouvelles tables : on retire UPDATE puis on le rend colonne par colonne.
revoke update, truncate, references, trigger on public.production_sessions from authenticated;
revoke update, truncate, references, trigger on public.production_entries from authenticated;
grant select, insert, delete on public.production_sessions to authenticated;
grant update (status, target_per_hour, shift_start, shift_hours, model, line_name, closed_at, closed_by)
  on public.production_sessions to authenticated;
grant select, insert, delete on public.production_entries to authenticated;
grant update (slot_hour, station, worker_id, pieces, defects, rework, downtime_reason, downtime_start,
              downtime_minutes, comment, voided, entered_at)
  on public.production_entries to authenticated;
revoke all on public.production_sessions from anon;
revoke all on public.production_entries from anon;

-- ---------------------------------------------------------------- Synchronisation de la tablette
-- Envoi groupé idempotent : une saisie = un client_id ; renvoyer le même client_id met à jour
-- la saisie (fin d'un arrêt, annulation). SECURITY INVOKER : la RLS ci-dessus s'applique.
create or replace function public.production_upsert_entries(p_session uuid, p_entries jsonb)
returns setof public.production_entries
language sql security invoker set search_path = '' as $$
  insert into public.production_entries as e
    (client_id, session_id, org_id, slot_hour, station, worker_id, pieces, defects, rework,
     downtime_reason, downtime_start, downtime_minutes, comment, voided, entered_at)
  select coalesce(x.client_id, gen_random_uuid()), s.id, s.org_id, x.slot_hour, x.station,
         nullif(x.worker_id, ''), coalesce(x.pieces, 0), coalesce(x.defects, 0), coalesce(x.rework, 0),
         x.downtime_reason, x.downtime_start, x.downtime_minutes, coalesce(x.comment, ''),
         coalesce(x.voided, false), coalesce(x.entered_at, now())
    from public.production_sessions s
    cross join lateral jsonb_to_recordset(p_entries) as x(
      client_id uuid, slot_hour smallint, station int, worker_id text, pieces int, defects int,
      rework int, downtime_reason text, downtime_start timestamptz, downtime_minutes numeric,
      comment text, voided boolean, entered_at timestamptz)
   where s.id = p_session
  on conflict (client_id) do update set
    slot_hour = excluded.slot_hour, station = excluded.station, worker_id = excluded.worker_id,
    pieces = excluded.pieces, defects = excluded.defects, rework = excluded.rework,
    downtime_reason = excluded.downtime_reason, downtime_start = excluded.downtime_start,
    downtime_minutes = excluded.downtime_minutes, comment = excluded.comment,
    voided = excluded.voided, entered_at = excluded.entered_at
    where e.session_id = excluded.session_id
  returning e.*;
$$;
revoke all on function public.production_upsert_entries(uuid, jsonb) from public, anon;
grant execute on function public.production_upsert_entries(uuid, jsonb) to authenticated;
