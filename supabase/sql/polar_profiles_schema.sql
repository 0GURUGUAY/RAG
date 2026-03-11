-- CEIBO - Polar profiles schema
-- Stores user-defined polar (speed vs wind angle) matrices by rigging / sail configuration.
-- One row per saved profile, per user, per project.

create table if not exists public.polar_profiles (
    id          text        primary key,          -- client-generated id (UUID or slug like 'default-d56-standard')
    project_id  uuid        not null references public.projects(id) on delete cascade,
    creator_email text      not null,
    creator_name  text,
    name          text      not null default '',  -- human label, e.g. "GV + Génois réduit"
    notes         text      not null default '',  -- free-text rigging description
    polar_data    jsonb     not null default '{}'::jsonb,  -- { "tws": { "twa": boatSpeedKn, ... }, ... }
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

-- Row-Level Security
alter table public.polar_profiles enable row level security;

create policy "polar_profiles: authenticated read own"
    on public.polar_profiles for select
    to authenticated
    using ((auth.jwt() ->> 'email') = creator_email);

create policy "polar_profiles: authenticated insert own"
    on public.polar_profiles for insert
    to authenticated
    with check ((auth.jwt() ->> 'email') = creator_email);

create policy "polar_profiles: authenticated update own"
    on public.polar_profiles for update
    to authenticated
    using ((auth.jwt() ->> 'email') = creator_email);

create policy "polar_profiles: authenticated delete own"
    on public.polar_profiles for delete
    to authenticated
    using ((auth.jwt() ->> 'email') = creator_email);

-- Index for fast per-project, per-user queries
create index if not exists idx_polar_profiles_project_creator
    on public.polar_profiles (project_id, creator_email);

-- Auto-update updated_at on row change
create or replace function public.handle_polar_profiles_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists polar_profiles_updated_at_trigger on public.polar_profiles;
create trigger polar_profiles_updated_at_trigger
    before update on public.polar_profiles
    for each row execute procedure public.handle_polar_profiles_updated_at();
