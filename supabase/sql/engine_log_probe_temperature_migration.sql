alter table public.engine_log
    add column if not exists probe_temp_start_c double precision,
    add column if not exists probe_temp_end_c double precision;