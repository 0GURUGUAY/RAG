-- CEIBO document management
-- 1) Metadata table
create table if not exists public.document_files (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null,
    creator_email text not null,
    creator_name text,
    title text not null,
    file_name text not null,
    mime_type text,
    size_bytes bigint default 0,
    category text not null,
    subcategory text,
    tags text[] not null default '{}',
    description text,
    storage_path text,
    public_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists document_files_creator_idx
    on public.document_files (creator_email, updated_at desc);

create index if not exists document_files_project_idx
    on public.document_files (project_id, updated_at desc);

alter table public.document_files enable row level security;

drop policy if exists "document_files_select_authenticated" on public.document_files;
create policy "document_files_select_authenticated"
on public.document_files
for select
to authenticated
using (creator_email = auth.email());

drop policy if exists "document_files_insert_authenticated" on public.document_files;
create policy "document_files_insert_authenticated"
on public.document_files
for insert
to authenticated
with check (creator_email = auth.email());

drop policy if exists "document_files_update_authenticated" on public.document_files;
create policy "document_files_update_authenticated"
on public.document_files
for update
to authenticated
using (creator_email = auth.email())
with check (creator_email = auth.email());

drop policy if exists "document_files_delete_authenticated" on public.document_files;
create policy "document_files_delete_authenticated"
on public.document_files
for delete
to authenticated
using (creator_email = auth.email());

-- 2) Storage bucket (run once in SQL editor)
insert into storage.buckets (id, name, public)
values ('ceibo-documents', 'ceibo-documents', true)
on conflict (id) do nothing;

-- 3) Storage policies
drop policy if exists "doc_bucket_select_authenticated" on storage.objects;
create policy "doc_bucket_select_authenticated"
on storage.objects
for select
to authenticated
using (bucket_id = 'ceibo-documents');

drop policy if exists "doc_bucket_insert_authenticated" on storage.objects;
create policy "doc_bucket_insert_authenticated"
on storage.objects
for insert
to authenticated
with check (bucket_id = 'ceibo-documents' and owner = auth.uid());

drop policy if exists "doc_bucket_update_authenticated" on storage.objects;
create policy "doc_bucket_update_authenticated"
on storage.objects
for update
to authenticated
using (bucket_id = 'ceibo-documents' and owner = auth.uid())
with check (bucket_id = 'ceibo-documents' and owner = auth.uid());

drop policy if exists "doc_bucket_delete_authenticated" on storage.objects;
create policy "doc_bucket_delete_authenticated"
on storage.objects
for delete
to authenticated
using (bucket_id = 'ceibo-documents' and owner = auth.uid());
