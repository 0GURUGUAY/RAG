-- CEIBO V5 - Engine log table (MOTEUR)
-- INSERT + UPDATE only (no DELETE policy).

create table if not exists public.engine_log (
    id text primary key,
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    timestamp timestamptz not null,
    hours double precision not null check (hours >= 0),
    fuel_added_l double precision not null default 0 check (fuel_added_l >= 0),
    note text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists engine_log_creator_project_idx
    on public.engine_log(creator_email, project_id);

create index if not exists engine_log_timestamp_idx
    on public.engine_log(timestamp desc);

-- Keep updated_at current on updates.
create or replace function public.set_row_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_engine_log_updated_at on public.engine_log;
create trigger trg_engine_log_updated_at
before update on public.engine_log
for each row execute function public.set_row_updated_at();

alter table public.engine_log enable row level security;

drop policy if exists "engine_log_select_own" on public.engine_log;
create policy "engine_log_select_own"
on public.engine_log
for select
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "engine_log_insert_own" on public.engine_log;
create policy "engine_log_insert_own"
on public.engine_log
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "engine_log_update_own" on public.engine_log;
create policy "engine_log_update_own"
on public.engine_log
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

-- Intentionally no DELETE policy: destruction of engine logs is disabled.
