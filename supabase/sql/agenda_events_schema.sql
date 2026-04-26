-- CEIBO - Agenda events schema
--
-- Purpose:
--   Persist simple agenda events shown in the voyage overview calendar.
--
-- Model:
--   - project-scoped shared events
--   - optional link to a voyage for future use
--   - shared read access for authenticated users
--   - write access restricted to creator_email

create table if not exists public.agenda_events (
    id text primary key,
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    voyage_plan_id text references public.voyage_plans(id) on delete set null,
    title text not null default '',
    start_date_time timestamptz not null,
    end_date_time timestamptz not null,
    comment text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint agenda_events_time_range_check
        check (end_date_time > start_date_time)
);

create index if not exists agenda_events_project_start_idx
    on public.agenda_events (project_id, start_date_time asc);

create index if not exists agenda_events_project_updated_idx
    on public.agenda_events (project_id, updated_at desc);

create index if not exists agenda_events_creator_project_idx
    on public.agenda_events (creator_email, project_id);

create index if not exists agenda_events_voyage_idx
    on public.agenda_events (voyage_plan_id)
    where voyage_plan_id is not null;

create or replace function public.set_row_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_agenda_events_updated_at on public.agenda_events;
create trigger trg_agenda_events_updated_at
before update on public.agenda_events
for each row execute function public.set_row_updated_at();

alter table public.agenda_events enable row level security;

drop policy if exists "agenda_events_select_authenticated" on public.agenda_events;
create policy "agenda_events_select_authenticated"
on public.agenda_events
for select
to authenticated
using (auth.role() = 'authenticated');

drop policy if exists "agenda_events_insert_own" on public.agenda_events;
create policy "agenda_events_insert_own"
on public.agenda_events
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "agenda_events_update_own" on public.agenda_events;
create policy "agenda_events_update_own"
on public.agenda_events
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "agenda_events_delete_own" on public.agenda_events;
create policy "agenda_events_delete_own"
on public.agenda_events
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));