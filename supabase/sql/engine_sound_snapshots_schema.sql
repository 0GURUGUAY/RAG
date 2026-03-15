-- CEIBO V5 - Engine sound snapshots (MVP)
-- Purpose: store compact audio-analysis snapshots (not continuous audio)
-- to detect drifts/anomalies by engine operating regime.

create table if not exists public.engine_sound_snapshots (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects(id) on delete cascade,
    creator_email text not null,
    creator_name text,

    captured_at timestamptz not null,

    -- Context from navigation/engine logs
    engine_hours double precision check (engine_hours >= 0),
    rpm integer check (rpm >= 0),
    speed_kn double precision,
    heel_deg double precision,
    course_deg double precision,
    wind_speed_kn double precision,
    wind_direction_deg double precision,
    sea_state text not null default 'unknown',

    -- Acquisition metadata
    device text not null default 'ipad',
    sample_rate_hz integer not null default 16000 check (sample_rate_hz >= 8000),
    duration_s double precision not null default 10 check (duration_s > 0 and duration_s <= 60),

    -- Compact signal descriptors (normalized values preferred)
    rms double precision,
    spectral_centroid_hz double precision,
    spectral_rolloff_hz double precision,
    zcr double precision,
    mfcc jsonb not null default '[]'::jsonb,
    band_energy jsonb not null default '{}'::jsonb,

    -- Anomaly model output
    baseline_profile text not null default 'default',
    anomaly_score double precision not null default 0,
    anomaly_level text not null default 'normal'
        check (anomaly_level in ('normal', 'watch', 'alert', 'critical')),
    anomaly_reasons jsonb not null default '[]'::jsonb,

    -- Optional short audio excerpt reference (store only when needed)
    audio_storage_path text,
    audio_public_url text,

    note text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists engine_sound_snapshots_creator_project_idx
    on public.engine_sound_snapshots(creator_email, project_id);

create index if not exists engine_sound_snapshots_captured_idx
    on public.engine_sound_snapshots(captured_at desc);

create index if not exists engine_sound_snapshots_level_idx
    on public.engine_sound_snapshots(anomaly_level, captured_at desc);

create index if not exists engine_sound_snapshots_baseline_idx
    on public.engine_sound_snapshots(baseline_profile, captured_at desc);

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

drop trigger if exists trg_engine_sound_snapshots_updated_at on public.engine_sound_snapshots;
create trigger trg_engine_sound_snapshots_updated_at
before update on public.engine_sound_snapshots
for each row execute function public.set_row_updated_at();

alter table public.engine_sound_snapshots enable row level security;

drop policy if exists "engine_sound_snapshots_select_own" on public.engine_sound_snapshots;
create policy "engine_sound_snapshots_select_own"
on public.engine_sound_snapshots
for select
to authenticated
using (auth.role() = 'authenticated'); -- all authenticated users can read all sound snapshots

drop policy if exists "engine_sound_snapshots_insert_own" on public.engine_sound_snapshots;
create policy "engine_sound_snapshots_insert_own"
on public.engine_sound_snapshots
for insert
to authenticated
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

drop policy if exists "engine_sound_snapshots_update_own" on public.engine_sound_snapshots;
create policy "engine_sound_snapshots_update_own"
on public.engine_sound_snapshots
for update
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'))
with check (lower(creator_email) = lower(auth.jwt() ->> 'email'));

-- Keep DELETE enabled for retention management.
drop policy if exists "engine_sound_snapshots_delete_own" on public.engine_sound_snapshots;
create policy "engine_sound_snapshots_delete_own"
on public.engine_sound_snapshots
for delete
to authenticated
using (lower(creator_email) = lower(auth.jwt() ->> 'email'));

-- Suggested retention helper (optional):
-- delete from public.engine_sound_snapshots
-- where creator_email = 'user@example.com'
--   and captured_at < now() - interval '180 days';
