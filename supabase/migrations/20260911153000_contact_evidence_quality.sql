alter table public.contacts
  add column if not exists candidate_status text,
  add column if not exists identity_reason text,
  add column if not exists technical_relevance numeric,
  add column if not exists quality_diagnostics jsonb not null default '{}'::jsonb;
