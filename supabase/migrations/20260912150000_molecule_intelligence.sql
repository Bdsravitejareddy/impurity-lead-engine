-- Additive, reusable molecule intelligence read model. Canonical evidence
-- remains in research_claims; this table only stores derived sections.
alter table public.research_claims add column if not exists claim_type text not null default 'OTHER';
alter table public.research_claims drop constraint if exists research_claims_attribution_check;
alter table public.research_claims add constraint research_claims_attribution_check
  check (attribution in ('PERSON_DIRECT','COMPANY_CONTEXT','OPPORTUNITY_CONTEXT','MOLECULE_CONTEXT'));
create index if not exists research_claims_molecule_type_idx on public.research_claims(entity_id, claim_type);

create table if not exists public.molecule_intelligence_sections (
  id uuid primary key default gen_random_uuid(),
  molecule_id uuid not null references public.molecules(id) on delete cascade,
  section_type text not null check (section_type in ('SUMMARY','WHAT_IT_IS','CLINICAL_USE','MECHANISM','CLINICAL_SAFETY','TOX_HAZARD','IMPURITY_RELEVANCE','SVAK_RELEVANCE','UNKNOWNS')),
  summary_text text not null,
  supporting_claim_ids uuid[] not null default '{}',
  evidence_status text not null default 'UNKNOWN' check (evidence_status in ('SUPPORTED','PARTIAL','UNKNOWN')),
  source_count integer not null default 0 check (source_count >= 0),
  confidence numeric not null default 0 check (confidence between 0 and 1),
  generated_at timestamptz not null default now(),
  generation_version integer not null default 1,
  updated_at timestamptz not null default now(),
  unique(molecule_id, section_type)
);
create index if not exists molecule_intelligence_sections_molecule_idx on public.molecule_intelligence_sections(molecule_id);
alter table public.molecule_intelligence_sections enable row level security;
revoke all on public.molecule_intelligence_sections from anon;
grant select on public.molecule_intelligence_sections to authenticated;
grant all on public.molecule_intelligence_sections to service_role;
drop policy if exists authenticated_read on public.molecule_intelligence_sections;
create policy authenticated_read on public.molecule_intelligence_sections for select to authenticated using (true);

alter table public.agent_research_jobs add column if not exists job_kind text not null default 'CONTACT_RESEARCH';
alter table public.agent_research_jobs add column if not exists molecule_id uuid references public.molecules(id) on delete cascade;
alter table public.agent_research_jobs alter column opportunity_id drop not null;
alter table public.agent_research_jobs drop constraint if exists agent_research_jobs_kind_check;
alter table public.agent_research_jobs add constraint agent_research_jobs_kind_check check (
  (job_kind = 'CONTACT_RESEARCH' and opportunity_id is not null and molecule_id is null)
  or (job_kind = 'MOLECULE_INTELLIGENCE' and molecule_id is not null and opportunity_id is null)
);
create index if not exists agent_research_jobs_molecule_idx on public.agent_research_jobs(molecule_id, status);
