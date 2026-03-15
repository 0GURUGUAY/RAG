-- MIGRATION: Partager les polaires entre tous les utilisateurs du projet
-- Date: 2026-03-15
--
-- Avant : chaque user ne voyait que ses propres polaires (filtre creator_email sur SELECT)
-- Après : tous les users authentifiés voient toutes les polaires (lecture partagée)
--         Les écritures (insert/update/delete) restent scopées au creator_email

-- Supprimer les anciennes policies SELECT (les deux noms possibles)
drop policy if exists "polar_profiles: authenticated read own" on public.polar_profiles;
drop policy if exists "polar_profiles: authenticated read all" on public.polar_profiles;

-- Créer la nouvelle policy SELECT ouverte à tous les users authentifiés
create policy "polar_profiles: authenticated read all"
    on public.polar_profiles for select
    to authenticated
    using (auth.role() = 'authenticated');
