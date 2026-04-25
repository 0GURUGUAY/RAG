-- CEIBO - Equipage schema
--
-- Purpose:
--   Persist crew members and their assignments to voyages.
--   Model:
--   - public.equipage: reusable crew directory
--   - public.voyage_equipage: many-to-many link between voyage_plans and equipage
--
-- Conventions:
--   - project-scoped data
--   - shared read access for authenticated users
--   - write access restricted to creator_email

create table if not exists public.equipage (
    id text primary key,
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    nom text not null default '',
    prenom text not null default '',
    email text not null default '',
    telephone text not null default '',
    commentaire text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.voyage_equipage (
    id text primary key,
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    voyage_plan_id text not null references public.voyage_plans(id) on delete cascade,
    equipage_id text not null references public.equipage(id) on delete cascade,
    commentaire text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists equipage_creator_project_email_uidx
    on public.equipage (project_id, creator_email, lower(email))
    where email <> '';

create index if not exists equipage_project_updated_idx
    on public.equipage (project_id, updated_at desc);

create index if not exists equipage_creator_project_idx
    on public.equipage (creator_email, project_id);

create unique index if not exists voyage_equipage_voyage_member_uidx
    on public.voyage_equipage (voyage_plan_id, equipage_id);

create index if not exists voyage_equipage_project_updated_idx
    on public.voyage_equipage (project_id, updated_at desc);

create index if not exists voyage_equipage_creator_project_idx
    on public.voyage_equipage (creator_email, project_id);

create index if not exists voyage_equipage_voyage_idx
    on public.voyage_equipage (voyage_plan_id);

create index if not exists voyage_equipage_member_idx
    on public.voyage_equipage (equipage_id);

create or replace function public.set_row_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_equipage_updated_at on public.equipage;
create trigger trg_equipage_updated_at
before update on public.equipage
for each row execute function public.set_row_updated_at();

drop trigger if exists trg_voyage_equipage_updated_at on public.voyage_equipage;
create trigger trg_voyage_equipage_updated_at
before update on public.voyage_equipage
for each row execute function public.set_row_updated_at();

alter table public.equipage enable row level security;
alter table public.voyage_equipage enable row level security;

drop policy if exists "equipage_select_authenticated" on public.equipage;
create policy "equipage_select_authenticated"
on public.equipage
for select
to authenticated
using (auth.role() = 'authenticated');

drop policy if exists "equipage_insert_own" on public.equipage;
create policy "equipage_insert_own"
on public.equipage
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "equipage_update_own" on public.equipage;
create policy "equipage_update_own"
on public.equipage
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "equipage_delete_own" on public.equipage;
create policy "equipage_delete_own"
on public.equipage
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "voyage_equipage_select_authenticated" on public.voyage_equipage;
create policy "voyage_equipage_select_authenticated"
on public.voyage_equipage
for select
to authenticated
using (auth.role() = 'authenticated');

drop policy if exists "voyage_equipage_insert_own" on public.voyage_equipage;
create policy "voyage_equipage_insert_own"
on public.voyage_equipage
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "voyage_equipage_update_own" on public.voyage_equipage;
create policy "voyage_equipage_update_own"
on public.voyage_equipage
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "voyage_equipage_delete_own" on public.voyage_equipage;
create policy "voyage_equipage_delete_own"
on public.voyage_equipage
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));