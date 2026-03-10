-- CEIBO - Maintenance expenses AI analysis fields
-- Run this in Supabase SQL editor before using the IA facture feature in production.

alter table public.maintenance_expenses
    add column if not exists ai_report jsonb,
    add column if not exists ai_tasks jsonb,
    add column if not exists ai_last_analyzed_at timestamptz;

alter table public.maintenance_expenses
    alter column ai_report set default '{}'::jsonb,
    alter column ai_tasks set default '[]'::jsonb;

update public.maintenance_expenses
set
    ai_report = coalesce(ai_report, '{}'::jsonb),
    ai_tasks = coalesce(ai_tasks, '[]'::jsonb)
where ai_report is null
   or ai_tasks is null;
