-- Link generic document metadata to voyage plans for cross-device voyage attachments.
alter table if exists public.document_files
    add column if not exists voyage_plan_id text references public.voyage_plans(id) on delete set null,
    add column if not exists external_provider text,
    add column if not exists external_sha text;

create index if not exists document_files_voyage_plan_idx
    on public.document_files (voyage_plan_id, updated_at desc)
    where voyage_plan_id is not null;

comment on column public.document_files.voyage_plan_id is
    'Optional voyage_plans.id link for documents attached to a voyage.';

comment on column public.document_files.external_provider is
    'Optional upstream storage provider when the file is not stored in the Supabase bucket (example: github).';

comment on column public.document_files.external_sha is
    'Optional upstream file revision identifier used for delete/update operations (example: GitHub blob sha).';
