-- CEIBO - Route external comments schema
--
-- Purpose:
--   Store large rich-text comments linked to a saved route without inflating
--   the normalized routes payload or the local savedRoutes JSON blob.
--
-- Model:
--   - one optional comment per route
--   - project-scoped data
--   - read access for all authenticated users
--   - write access restricted to the creator_email

create table if not exists public.route_comments (
    route_id uuid primary key references public.routes(id) on delete cascade,
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    content_html text not null default '',
    content_text text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists route_comments_project_updated_idx
    on public.route_comments (project_id, updated_at desc);

create index if not exists route_comments_creator_project_idx
    on public.route_comments (creator_email, project_id);

create or replace function public.set_row_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_route_comments_updated_at on public.route_comments;
create trigger trg_route_comments_updated_at
before update on public.route_comments
for each row execute function public.set_row_updated_at();

alter table public.route_comments enable row level security;

drop policy if exists "route_comments_select_authenticated" on public.route_comments;
create policy "route_comments_select_authenticated"
on public.route_comments
for select
to authenticated
using (auth.role() = 'authenticated');

drop policy if exists "route_comments_insert_own" on public.route_comments;
create policy "route_comments_insert_own"
on public.route_comments
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "route_comments_update_own" on public.route_comments;
create policy "route_comments_update_own"
on public.route_comments
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "route_comments_delete_own" on public.route_comments;
create policy "route_comments_delete_own"
on public.route_comments
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));