-- CEIBO public tracking shares
-- Stores token-based public links for the standalone boat follower page.

create table if not exists public.public_tracking_shares (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    title text not null default 'CEIBO live tracker',
    share_token text not null,
    history_hours integer not null default 168,
    is_active boolean not null default true,
    last_accessed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (project_id, creator_email),
    unique (share_token)
);

alter table public.public_tracking_shares
    add column if not exists project_id uuid references public.projects(id) on delete cascade,
    add column if not exists creator_email text,
    add column if not exists creator_name text,
    add column if not exists title text,
    add column if not exists share_token text,
    add column if not exists history_hours integer,
    add column if not exists is_active boolean,
    add column if not exists last_accessed_at timestamptz,
    add column if not exists created_at timestamptz,
    add column if not exists updated_at timestamptz;

alter table public.public_tracking_shares
    alter column title set default 'CEIBO live tracker',
    alter column history_hours set default 168,
    alter column is_active set default true,
    alter column created_at set default now(),
    alter column updated_at set default now();

update public.public_tracking_shares
set
    title = coalesce(nullif(title, ''), 'CEIBO live tracker'),
    history_hours = greatest(1, least(coalesce(history_hours, 168), 720)),
    is_active = coalesce(is_active, true),
    created_at = coalesce(created_at, now()),
    updated_at = coalesce(updated_at, now());

create index if not exists public_tracking_shares_project_creator_idx
    on public.public_tracking_shares(project_id, creator_email);

create index if not exists public_tracking_shares_active_idx
    on public.public_tracking_shares(is_active, updated_at desc);

drop trigger if exists trg_public_tracking_shares_updated_at on public.public_tracking_shares;
create trigger trg_public_tracking_shares_updated_at
before update on public.public_tracking_shares
for each row execute function public.set_row_updated_at();

alter table public.public_tracking_shares enable row level security;

drop policy if exists "public_tracking_shares_select_own" on public.public_tracking_shares;
create policy "public_tracking_shares_select_own"
on public.public_tracking_shares
for select
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "public_tracking_shares_insert_own" on public.public_tracking_shares;
create policy "public_tracking_shares_insert_own"
on public.public_tracking_shares
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "public_tracking_shares_update_own" on public.public_tracking_shares;
create policy "public_tracking_shares_update_own"
on public.public_tracking_shares
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "public_tracking_shares_delete_own" on public.public_tracking_shares;
create policy "public_tracking_shares_delete_own"
on public.public_tracking_shares
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));