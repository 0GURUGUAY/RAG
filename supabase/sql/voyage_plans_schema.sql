-- CEIBO - Voyage plans schema
--
-- Purpose:
--   Persist shared trip plans (voyages) and their ordered items (routes + anchorages/stops)
--   in Supabase, using the same conventions as the other CEIBO cloud tables:
--   - project-scoped data
--   - shared read access for authenticated users
--   - write access restricted to the creator_email
--
-- Notes:
--   - IDs are text because the client already generates stable string IDs locally.
--   - start_date_time is kept for forward compatibility with the current local model,
--     even if the UI mostly derives stop starts from previous legs.

create table if not exists public.voyage_plans (
    id text primary key,
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    name text not null default '',
    description text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.voyage_plan_items (
    id text primary key,
    voyage_plan_id text not null references public.voyage_plans(id) on delete cascade,
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    seq integer not null default 0,
    item_type text not null check (item_type in ('route', 'stop')),
    route_id text,
    departure_date_time timestamptz,
    start_date_time timestamptz,
    stop_departure_date_time timestamptz,
    stop_name text not null default '',
    duration_days double precision not null default 0,
    waypoint_photo_id text,
    waypoint_lat double precision,
    waypoint_lng double precision,
    notes text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint voyage_plan_items_duration_days_check
        check (duration_days >= 0),

    constraint voyage_plan_items_waypoint_lat_check
        check (waypoint_lat is null or (waypoint_lat >= -90 and waypoint_lat <= 90)),

    constraint voyage_plan_items_waypoint_lng_check
        check (waypoint_lng is null or (waypoint_lng >= -180 and waypoint_lng <= 180))
);

create unique index if not exists voyage_plan_items_plan_seq_idx
    on public.voyage_plan_items (voyage_plan_id, seq);

create index if not exists voyage_plans_project_updated_idx
    on public.voyage_plans (project_id, updated_at desc);

create index if not exists voyage_plans_creator_project_idx
    on public.voyage_plans (creator_email, project_id);

create index if not exists voyage_plan_items_project_updated_idx
    on public.voyage_plan_items (project_id, updated_at desc);

create index if not exists voyage_plan_items_creator_project_idx
    on public.voyage_plan_items (creator_email, project_id);

create index if not exists voyage_plan_items_route_id_idx
    on public.voyage_plan_items (route_id)
    where route_id is not null;

create or replace function public.set_row_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_voyage_plans_updated_at on public.voyage_plans;
create trigger trg_voyage_plans_updated_at
before update on public.voyage_plans
for each row execute function public.set_row_updated_at();

drop trigger if exists trg_voyage_plan_items_updated_at on public.voyage_plan_items;
create trigger trg_voyage_plan_items_updated_at
before update on public.voyage_plan_items
for each row execute function public.set_row_updated_at();

alter table public.voyage_plans enable row level security;
alter table public.voyage_plan_items enable row level security;

drop policy if exists "voyage_plans_select_authenticated" on public.voyage_plans;
create policy "voyage_plans_select_authenticated"
on public.voyage_plans
for select
to authenticated
using (auth.role() = 'authenticated');

drop policy if exists "voyage_plans_insert_own" on public.voyage_plans;
create policy "voyage_plans_insert_own"
on public.voyage_plans
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "voyage_plans_update_own" on public.voyage_plans;
create policy "voyage_plans_update_own"
on public.voyage_plans
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "voyage_plans_delete_own" on public.voyage_plans;
create policy "voyage_plans_delete_own"
on public.voyage_plans
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "voyage_plan_items_select_authenticated" on public.voyage_plan_items;
create policy "voyage_plan_items_select_authenticated"
on public.voyage_plan_items
for select
to authenticated
using (auth.role() = 'authenticated');

drop policy if exists "voyage_plan_items_insert_own" on public.voyage_plan_items;
create policy "voyage_plan_items_insert_own"
on public.voyage_plan_items
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "voyage_plan_items_update_own" on public.voyage_plan_items;
create policy "voyage_plan_items_update_own"
on public.voyage_plan_items
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "voyage_plan_items_delete_own" on public.voyage_plan_items;
create policy "voyage_plan_items_delete_own"
on public.voyage_plan_items
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));