-- CEIBO V5 - Maintenance Tasks migration
-- Creates dedicated tables for schemas (boards) and pins (pastilles).

create table if not exists public.maintenance_schemas (
    id text primary key,
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    name text not null,
    image_data_url text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.maintenance_pins (
    id text primary key,
    schema_id text not null references public.maintenance_schemas(id) on delete cascade,
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    x_percent double precision not null check (x_percent >= 0 and x_percent <= 100),
    y_percent double precision not null check (y_percent >= 0 and y_percent <= 100),
    color_key text not null check (color_key in ('red', 'orange', 'green', 'blue')),
    status_key text not null check (status_key in ('active', 'planned', 'done')),
    legend text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists maintenance_schemas_creator_project_idx
    on public.maintenance_schemas(creator_email, project_id);

create index if not exists maintenance_pins_creator_project_idx
    on public.maintenance_pins(creator_email, project_id);

create index if not exists maintenance_pins_schema_idx
    on public.maintenance_pins(schema_id);

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

drop trigger if exists trg_maintenance_schemas_updated_at on public.maintenance_schemas;

drop trigger if exists trg_maintenance_pins_updated_at on public.maintenance_pins;
create trigger trg_maintenance_pins_updated_at
before update on public.maintenance_pins
for each row execute function public.set_row_updated_at();

alter table public.maintenance_schemas enable row level security;
alter table public.maintenance_pins enable row level security;

-- Policies: all authenticated users can read; writes are scoped to the creator.
drop policy if exists "maintenance_schemas_select_own" on public.maintenance_schemas;
create policy "maintenance_schemas_select_own"
on public.maintenance_schemas
for select
to authenticated
using (auth.role() = 'authenticated'); -- all authenticated users can read all schemas

drop policy if exists "maintenance_schemas_insert_own" on public.maintenance_schemas;
create policy "maintenance_schemas_insert_own"
on public.maintenance_schemas
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "maintenance_schemas_update_own" on public.maintenance_schemas;

drop policy if exists "maintenance_schemas_delete_own" on public.maintenance_schemas;
create policy "maintenance_schemas_delete_own"
on public.maintenance_schemas
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "maintenance_pins_select_own" on public.maintenance_pins;
create policy "maintenance_pins_select_own"
on public.maintenance_pins
for select
to authenticated
using (auth.role() = 'authenticated'); -- all authenticated users can read all pins

drop policy if exists "maintenance_pins_insert_own" on public.maintenance_pins;
create policy "maintenance_pins_insert_own"
on public.maintenance_pins
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "maintenance_pins_update_own" on public.maintenance_pins;
create policy "maintenance_pins_update_own"
on public.maintenance_pins
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "maintenance_pins_delete_own" on public.maintenance_pins;
create policy "maintenance_pins_delete_own"
on public.maintenance_pins
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));

-- Optional smoke test (replace values to match your project/user).
-- insert into public.maintenance_schemas (id, project_id, creator_email, creator_name, name, image_data_url)
-- values ('schema-test-1', '00000000-0000-4000-8000-000000000001', 'user@example.com', 'User', 'Engine room', 'data:image/jpeg;base64,...');
--
-- insert into public.maintenance_pins (id, schema_id, project_id, creator_email, creator_name, x_percent, y_percent, color_key, status_key, legend)
-- values ('pin-test-1', 'schema-test-1', '00000000-0000-4000-8000-000000000001', 'user@example.com', 'User', 42.5, 58.1, 'red', 'active', 'Replace impeller');
--
-- update public.maintenance_pins
-- set status_key = 'done', legend = 'Impeller replaced'
-- where id = 'pin-test-1';
