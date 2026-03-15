-- CEIBO ARRIVEE - Cached arrival analyses

create table if not exists public.arrival_analyses (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    cache_key text not null,
    destination_label text,
    destination_lat double precision not null,
    destination_lng double precision not null,
    arrival_iso timestamptz,
    route_name text,
    top_anchorage_name text,
    summary_text text,
    recommendations jsonb not null default '[]'::jsonb,
    restaurants jsonb not null default '[]'::jsonb,
    shops jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists arrival_analyses_creator_project_cache_idx
    on public.arrival_analyses (creator_email, project_id, cache_key);

create index if not exists arrival_analyses_creator_updated_idx
    on public.arrival_analyses (creator_email, updated_at desc);

create index if not exists arrival_analyses_project_updated_idx
    on public.arrival_analyses (project_id, updated_at desc);

create or replace function public.set_row_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_arrival_analyses_updated_at on public.arrival_analyses;
create trigger trg_arrival_analyses_updated_at
before update on public.arrival_analyses
for each row execute function public.set_row_updated_at();

alter table public.arrival_analyses enable row level security;

drop policy if exists "arrival_analyses_select_own" on public.arrival_analyses;
create policy "arrival_analyses_select_own"
on public.arrival_analyses
for select
to authenticated
using (auth.role() = 'authenticated'); -- all authenticated users can read all arrival analyses

drop policy if exists "arrival_analyses_insert_own" on public.arrival_analyses;
create policy "arrival_analyses_insert_own"
on public.arrival_analyses
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "arrival_analyses_update_own" on public.arrival_analyses;
create policy "arrival_analyses_update_own"
on public.arrival_analyses
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "arrival_analyses_delete_own" on public.arrival_analyses;
create policy "arrival_analyses_delete_own"
on public.arrival_analyses
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));
