-- Bounded evidence graph. Backend workers write; authenticated users may read
-- safe evidence and claims through the existing app.
create table if not exists public.research_entities (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null check (entity_type in ('MOLECULE','IMPURITY','COMPANY','ARTICLE','PUBLICATION','PATENT','REGULATORY_EVENT','CONFERENCE','PERSON','OPPORTUNITY','OTHER')),
  canonical_name text not null,
  normalized_name text not null,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(entity_type, normalized_name)
);
create table if not exists public.research_relationships (
  id uuid primary key default gen_random_uuid(),
  from_entity_id uuid not null references public.research_entities(id) on delete cascade,
  to_entity_id uuid not null references public.research_entities(id) on delete cascade,
  relationship_type text not null,
  source_ids uuid[] not null default '{}',
  confidence numeric not null default 0.5 check (confidence between 0 and 1),
  provenance text not null default 'OBSERVED' check (provenance in ('OBSERVED','INFERRED','UNKNOWN')),
  created_at timestamptz not null default now(),
  unique(from_entity_id, to_entity_id, relationship_type)
);
create table if not exists public.research_claims (
  id uuid primary key default gen_random_uuid(),
  entity_id uuid references public.research_entities(id) on delete cascade,
  source_id uuid references public.contact_sources(id) on delete set null,
  claim_text text not null,
  source_url text,
  source_class text not null check (source_class in ('PRIMARY','STRONG_PROFESSIONAL','DIRECTORY','DISCOVERY_WEAK')),
  attribution text not null default 'COMPANY_CONTEXT' check (attribution in ('PERSON_DIRECT','COMPANY_CONTEXT','OPPORTUNITY_CONTEXT')),
  provenance text not null default 'OBSERVED' check (provenance in ('OBSERVED','INFERRED','UNKNOWN')),
  support_text text,
  confidence numeric not null default 0.5 check (confidence between 0 and 1),
  created_at timestamptz not null default now()
);
create index if not exists research_relationships_from_idx on public.research_relationships(from_entity_id);
create index if not exists research_relationships_to_idx on public.research_relationships(to_entity_id);
create index if not exists research_claims_entity_idx on public.research_claims(entity_id);
alter table public.research_entities enable row level security;
alter table public.research_relationships enable row level security;
alter table public.research_claims enable row level security;
revoke all on public.research_entities, public.research_relationships, public.research_claims from anon;
grant select on public.research_entities, public.research_relationships, public.research_claims to authenticated;
grant all on public.research_entities, public.research_relationships, public.research_claims to service_role;
drop policy if exists authenticated_read on public.research_entities;
drop policy if exists authenticated_read on public.research_relationships;
drop policy if exists authenticated_read on public.research_claims;
create policy authenticated_read on public.research_entities for select to authenticated using (true);
create policy authenticated_read on public.research_relationships for select to authenticated using (true);
create policy authenticated_read on public.research_claims for select to authenticated using (true);
