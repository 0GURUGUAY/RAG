-- CEIBO - Voyage plans food MVP migration
--
-- Stores meal planning, provisioning, and budget tracking directly on voyage_plans
-- to keep the first MVP inside the existing voyage sync model.

alter table if exists public.voyage_plans
    add column if not exists meal_plan jsonb not null default '[]'::jsonb,
    add column if not exists provisioning_items jsonb not null default '[]'::jsonb,
    add column if not exists budget_items jsonb not null default '[]'::jsonb;

comment on column public.voyage_plans.meal_plan is
    'Generated and edited lunch/dinner planning for each voyage day.';

comment on column public.voyage_plans.provisioning_items is
    'Provisioning checklist derived from meal planning plus manual monthly consumables.';

comment on column public.voyage_plans.budget_items is
    'Trip food and monthly boat expense entries for onboard life management.';
