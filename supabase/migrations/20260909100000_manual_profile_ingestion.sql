alter table public.contact_sources add column if not exists source_description text;
alter table public.contact_sources add column if not exists content_hash text;
alter table public.contact_sources add column if not exists processing_status text;
create unique index if not exists contact_sources_content_hash_idx on public.contact_sources(contact_id, content_hash) where content_hash is not null;
