-- CEIBO V5 - Navigation log entries schema
-- Includes per-entry embedded GPS trace samples for reliable replay of saved tracks.

create table if not exists public.nav_log_entries (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    watch_time_iso timestamptz,
    watch_end_time_iso timestamptz,
    trace_samples jsonb not null default '[]'::jsonb,
    lat double precision,
    lng double precision,
    speed_kn double precision,
    heel_deg double precision,
    source text not null default 'manual',
    watch_crew text,
    heading_deg double precision,
    wind_direction_deg double precision,
    wind_speed_kn double precision,
    sea_state text,
    sail_config text,
    barometer_hpa double precision,
    log_distance_nm double precision,
    events text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.nav_log_entries
    add column if not exists project_id uuid references public.projects(id) on delete cascade,
    add column if not exists creator_email text,
    add column if not exists creator_name text,
    add column if not exists watch_time_iso timestamptz,
    add column if not exists watch_end_time_iso timestamptz,
    add column if not exists trace_samples jsonb,
    add column if not exists lat double precision,
    add column if not exists lng double precision,
    add column if not exists speed_kn double precision,
    add column if not exists heel_deg double precision,
    add column if not exists source text,
    add column if not exists watch_crew text,
    add column if not exists heading_deg double precision,
    add column if not exists wind_direction_deg double precision,
    add column if not exists wind_speed_kn double precision,
    add column if not exists sea_state text,
    add column if not exists sail_config text,
    add column if not exists barometer_hpa double precision,
    add column if not exists log_distance_nm double precision,
    add column if not exists events text,
    add column if not exists created_at timestamptz,
    add column if not exists updated_at timestamptz;

alter table public.nav_log_entries
    alter column source set default 'manual',
    alter column trace_samples set default '[]'::jsonb,
    alter column created_at set default now(),
    alter column updated_at set default now();

update public.nav_log_entries
set
    source = coalesce(nullif(source, ''), 'manual'),
    trace_samples = coalesce(trace_samples, '[]'::jsonb),
    created_at = coalesce(created_at, now()),
    updated_at = coalesce(updated_at, now());

create index if not exists nav_log_entries_creator_project_idx
    on public.nav_log_entries(creator_email, project_id);

create index if not exists nav_log_entries_watch_time_idx
    on public.nav_log_entries(watch_time_iso desc);

create index if not exists nav_log_entries_updated_idx
    on public.nav_log_entries(updated_at desc);

create or replace function public.set_row_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_nav_log_entries_updated_at on public.nav_log_entries;
create trigger trg_nav_log_entries_updated_at
before update on public.nav_log_entries
for each row execute function public.set_row_updated_at();

alter table public.nav_log_entries enable row level security;

drop policy if exists "nav_log_entries_select_own" on public.nav_log_entries;
create policy "nav_log_entries_select_own"
on public.nav_log_entries
for select
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "nav_log_entries_insert_own" on public.nav_log_entries;
create policy "nav_log_entries_insert_own"
on public.nav_log_entries
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "nav_log_entries_update_own" on public.nav_log_entries;
create policy "nav_log_entries_update_own"
on public.nav_log_entries
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "nav_log_entries_delete_own" on public.nav_log_entries;
create policy "nav_log_entries_delete_own"
on public.nav_log_entries
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));
