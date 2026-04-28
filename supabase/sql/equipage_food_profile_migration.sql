-- CEIBO - Equipage dietary profile migration
--
-- Adds a structured JSONB profile to store crew dietary preferences,
-- allergies, dislikes, and breakfast habits directly in the shared crew table.

alter table if exists public.equipage
    add column if not exists dietary_profile jsonb not null default '{}'::jsonb;

comment on column public.equipage.dietary_profile is
    'Structured dietary preferences for meal planning (dietType, allergiesText, dislikesText, breakfastNotes).';
