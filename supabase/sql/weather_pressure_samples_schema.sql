-- CEIBO V5 - Weather history samples schema
-- Stores weather snapshots every 30 minutes in cloud with a short retention window handled by the app.

create table if not exists public.weather_pressure_samples (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,
    sample_slot_at timestamptz not null,
    measured_at timestamptz not null,
    source text not null default 'weather' check (source in ('weather', 'signalk')),
    provider text not null default 'open-meteo',
    pressure_hpa double precision,
    temperature_c double precision,
    sea_surface_temperature_c double precision,
    wind_speed_kn double precision,
    wind_gust_kn double precision,
    wind_direction_deg double precision,
    precipitation_mm double precision,
    wave_height_m double precision,
    wave_direction_deg double precision,
    wave_period_s double precision,
    current_speed_kn double precision,
    ocean_current_direction_deg double precision,
    humidity_pct double precision,
    cloud_cover_pct double precision,
    rain_rate_mm_h double precision,
    weather_code integer,
    lat double precision,
    lng double precision,
    location_label text,
    raw_payload jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.weather_pressure_samples
    add column if not exists project_id uuid references public.projects(id) on delete cascade,
    add column if not exists creator_email text,
    add column if not exists creator_name text,
    add column if not exists sample_slot_at timestamptz,
    add column if not exists measured_at timestamptz,
    add column if not exists source text,
    add column if not exists provider text,
    add column if not exists pressure_hpa double precision,
    add column if not exists temperature_c double precision,
    add column if not exists sea_surface_temperature_c double precision,
    add column if not exists wind_speed_kn double precision,
    add column if not exists wind_gust_kn double precision,
    add column if not exists wind_direction_deg double precision,
    add column if not exists precipitation_mm double precision,
    add column if not exists wave_height_m double precision,
    add column if not exists wave_direction_deg double precision,
    add column if not exists wave_period_s double precision,
    add column if not exists current_speed_kn double precision,
    add column if not exists ocean_current_direction_deg double precision,
    add column if not exists humidity_pct double precision,
    add column if not exists cloud_cover_pct double precision,
    add column if not exists rain_rate_mm_h double precision,
    add column if not exists weather_code integer,
    add column if not exists lat double precision,
    add column if not exists lng double precision,
    add column if not exists location_label text,
    add column if not exists raw_payload jsonb,
    add column if not exists created_at timestamptz,
    add column if not exists updated_at timestamptz;

alter table public.weather_pressure_samples
    alter column source set default 'weather',
    alter column provider set default 'open-meteo',
    alter column pressure_hpa drop not null,
    alter column created_at set default now(),
    alter column updated_at set default now();

update public.weather_pressure_samples
set
    source = case when source in ('weather', 'signalk') then source else 'weather' end,
    provider = case
        when coalesce(nullif(trim(provider), ''), '') <> '' then lower(trim(provider))
        when source = 'signalk' then 'signalk'
        else 'open-meteo'
    end,
    created_at = coalesce(created_at, now()),
    updated_at = coalesce(updated_at, now())
where true;

alter table public.weather_pressure_samples
    alter column provider set not null;

drop index if exists weather_pressure_samples_project_creator_slot_uidx;

create unique index if not exists weather_pressure_samples_project_creator_slot_uidx
    on public.weather_pressure_samples(project_id, creator_email, source, provider, sample_slot_at);

create index if not exists weather_pressure_samples_project_slot_idx
    on public.weather_pressure_samples(project_id, sample_slot_at desc);

create index if not exists weather_pressure_samples_creator_slot_idx
    on public.weather_pressure_samples(creator_email, sample_slot_at desc);

create or replace function public.set_row_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_weather_pressure_samples_updated_at on public.weather_pressure_samples;
create trigger trg_weather_pressure_samples_updated_at
before update on public.weather_pressure_samples
for each row execute function public.set_row_updated_at();

alter table public.weather_pressure_samples enable row level security;

drop policy if exists "weather_pressure_samples_select_auth" on public.weather_pressure_samples;
create policy "weather_pressure_samples_select_auth"
on public.weather_pressure_samples
for select
to authenticated
using (auth.role() = 'authenticated');

drop policy if exists "weather_pressure_samples_insert_own" on public.weather_pressure_samples;
create policy "weather_pressure_samples_insert_own"
on public.weather_pressure_samples
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "weather_pressure_samples_update_own" on public.weather_pressure_samples;
create policy "weather_pressure_samples_update_own"
on public.weather_pressure_samples
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "weather_pressure_samples_delete_own" on public.weather_pressure_samples;
create policy "weather_pressure_samples_delete_own"
on public.weather_pressure_samples
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));