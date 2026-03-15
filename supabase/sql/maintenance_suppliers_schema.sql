-- CEIBO V5 - Maintenance suppliers migration
-- Creates dedicated table for suppliers used by the FOURNISSEURS tab.

create table if not exists public.maintenance_suppliers (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    name text not null,
    contact text not null default '',
    emergency_phone text not null default '',
    iban text not null default '',
    note text not null default '',
    documents jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- If a legacy table exists with id as text, convert it to uuid when values are compatible.
do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'maintenance_suppliers'
          and column_name = 'id'
          and data_type <> 'uuid'
    ) then
        begin
            alter table public.maintenance_suppliers
                alter column id type uuid using id::uuid;
        exception when others then
            raise exception 'maintenance_suppliers.id ne peut pas etre converti en uuid. Nettoie/convertis les valeurs id legacy puis relance la migration.';
        end;
    end if;
end
$$;

-- If the table already existed from an older version, ensure required columns exist.
alter table public.maintenance_suppliers
    add column if not exists project_id uuid references public.projects(id) on delete cascade,
    add column if not exists creator_email text,
    add column if not exists creator_name text,
    add column if not exists name text,
    add column if not exists contact text,
    add column if not exists emergency_phone text,
    add column if not exists iban text,
    add column if not exists note text,
    add column if not exists documents jsonb,
    add column if not exists created_at timestamptz,
    add column if not exists updated_at timestamptz;

-- Normalize defaults expected by app payloads.
alter table public.maintenance_suppliers
    alter column contact set default '',
    alter column emergency_phone set default '',
    alter column iban set default '',
    alter column note set default '',
    alter column documents set default '[]'::jsonb,
    alter column created_at set default now(),
    alter column updated_at set default now();

update public.maintenance_suppliers
set
    contact = coalesce(contact, ''),
    emergency_phone = coalesce(emergency_phone, ''),
    iban = coalesce(iban, ''),
    note = coalesce(note, ''),
    documents = coalesce(documents, '[]'::jsonb),
    created_at = coalesce(created_at, now()),
    updated_at = coalesce(updated_at, now());

create index if not exists maintenance_suppliers_creator_project_idx
    on public.maintenance_suppliers(creator_email, project_id);

create index if not exists maintenance_suppliers_name_idx
    on public.maintenance_suppliers(name);

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

drop trigger if exists trg_maintenance_suppliers_updated_at on public.maintenance_suppliers;
create trigger trg_maintenance_suppliers_updated_at
before update on public.maintenance_suppliers
for each row execute function public.set_row_updated_at();

alter table public.maintenance_suppliers enable row level security;

-- Policies: all authenticated users can read; writes are scoped to the creator.
drop policy if exists "maintenance_suppliers_select_own" on public.maintenance_suppliers;
create policy "maintenance_suppliers_select_own"
on public.maintenance_suppliers
for select
to authenticated
using (auth.role() = 'authenticated'); -- all authenticated users can read all suppliers

drop policy if exists "maintenance_suppliers_insert_own" on public.maintenance_suppliers;
create policy "maintenance_suppliers_insert_own"
on public.maintenance_suppliers
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "maintenance_suppliers_update_own" on public.maintenance_suppliers;
create policy "maintenance_suppliers_update_own"
on public.maintenance_suppliers
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "maintenance_suppliers_delete_own" on public.maintenance_suppliers;
create policy "maintenance_suppliers_delete_own"
on public.maintenance_suppliers
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));

-- Optional smoke test (replace values to match your project/user).
-- insert into public.maintenance_suppliers (
--     project_id,
--     creator_email,
--     creator_name,
--     name,
--     contact,
--     emergency_phone,
--     iban,
--     note,
--     documents
-- ) values (
--     '00000000-0000-4000-8000-000000000001',
--     'user@example.com',
--     'User',
--     'Electro Marine',
--     'Carlos',
--     '+34 600 000 000',
--     'ES7921000813610123456789',
--     'Test insert',
--     '[]'::jsonb
-- );
--
-- update public.maintenance_suppliers
-- set note = 'Test update'
-- where id = 'supplier-test-1';
--
-- delete from public.maintenance_suppliers
-- where id = 'supplier-test-1';
