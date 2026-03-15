-- MIGRATION: Partage de toutes les données entre utilisateurs
-- Date: 2026-03-15
--
-- Avant : chaque user ne voyait que ses propres enregistrements (filtre creator_email sur SELECT)
-- Après : tous les users authentifiés lisent toutes les données du projet
--         Les écritures (insert/update/delete) restent scopées au creator_email

-- document_files
drop policy if exists "document_files_select_authenticated" on public.document_files;
create policy "document_files_select_authenticated"
on public.document_files for select to authenticated
using (auth.role() = 'authenticated');

-- nav_log_entries
drop policy if exists "nav_log_entries_select_own" on public.nav_log_entries;
create policy "nav_log_entries_select_own"
on public.nav_log_entries for select to authenticated
using (auth.role() = 'authenticated');

-- maintenance_schemas
drop policy if exists "maintenance_schemas_select_own" on public.maintenance_schemas;
create policy "maintenance_schemas_select_own"
on public.maintenance_schemas for select to authenticated
using (auth.role() = 'authenticated');

-- maintenance_pins
drop policy if exists "maintenance_pins_select_own" on public.maintenance_pins;
create policy "maintenance_pins_select_own"
on public.maintenance_pins for select to authenticated
using (auth.role() = 'authenticated');

-- maintenance_expenses
drop policy if exists "maintenance_expenses_select_own" on public.maintenance_expenses;
create policy "maintenance_expenses_select_own"
on public.maintenance_expenses for select to authenticated
using (auth.role() = 'authenticated');

-- maintenance_suppliers
drop policy if exists "maintenance_suppliers_select_own" on public.maintenance_suppliers;
create policy "maintenance_suppliers_select_own"
on public.maintenance_suppliers for select to authenticated
using (auth.role() = 'authenticated');

-- engine_log
drop policy if exists "engine_log_select_own" on public.engine_log;
create policy "engine_log_select_own"
on public.engine_log for select to authenticated
using (auth.role() = 'authenticated');

-- engine_sound_snapshots
drop policy if exists "engine_sound_snapshots_select_own" on public.engine_sound_snapshots;
create policy "engine_sound_snapshots_select_own"
on public.engine_sound_snapshots for select to authenticated
using (auth.role() = 'authenticated');

-- arrival_analyses
drop policy if exists "arrival_analyses_select_own" on public.arrival_analyses;
create policy "arrival_analyses_select_own"
on public.arrival_analyses for select to authenticated
using (auth.role() = 'authenticated');
