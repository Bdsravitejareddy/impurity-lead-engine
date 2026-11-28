-- Contacts that are not people (section headings stored by older crawls) are
-- hidden rather than deleted, so their sources and links are kept.
alter table if exists public.contacts
  add column if not exists hidden_reason text;
