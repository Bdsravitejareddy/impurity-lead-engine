-- Reversible legacy-contact integrity guard.
-- Duplicate rows are soft-merged by scripts/repair_contact_integrity.py; no
-- production row is deleted and all child evidence remains recoverable.
alter table if exists public.contacts
  add column if not exists merged_into_contact_id uuid references public.contacts(id) on delete set null,
  add column if not exists merge_reason text,
  add column if not exists merged_at timestamptz;

create index if not exists contacts_merged_into_contact_idx
  on public.contacts (merged_into_contact_id)
  where merged_into_contact_id is not null;

create table if not exists public.contact_aliases (
  id uuid primary key default gen_random_uuid(),
  contact_id uuid not null references public.contacts(id) on delete cascade,
  alias_name text not null,
  normalized_name text not null,
  source_ids uuid[] not null default '{}',
  provenance text not null default 'OBSERVED'
    check (provenance in ('OBSERVED','INFERRED','UNKNOWN')),
  created_at timestamptz not null default now(),
  unique (contact_id, normalized_name)
);

alter table public.contact_aliases enable row level security;
revoke all on table public.contact_aliases from anon;
grant select on table public.contact_aliases to authenticated;
grant all on table public.contact_aliases to service_role;
drop policy if exists contact_aliases_authenticated_read on public.contact_aliases;
create policy contact_aliases_authenticated_read on public.contact_aliases
  for select to authenticated using (true);
