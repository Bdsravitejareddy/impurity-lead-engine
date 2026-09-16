-- Bounded company+molecule candidate enrichment jobs. Existing contact and
-- molecule job rows remain valid; this only adds nullable context columns.
alter table public.agent_research_jobs
  add column if not exists company_id uuid references public.companies(id) on delete cascade,
  add column if not exists candidate_id uuid references public.company_molecules(id) on delete cascade,
  add column if not exists research_budget jsonb not null default '{}'::jsonb,
  add column if not exists attempt_count integer not null default 0,
  add column if not exists last_attempt_at timestamptz,
  add column if not exists last_outcome text;

alter table public.agent_research_jobs drop constraint if exists agent_research_jobs_kind_check;
alter table public.agent_research_jobs add constraint agent_research_jobs_kind_check check (
  (job_kind = 'CONTACT_RESEARCH' and opportunity_id is not null and molecule_id is null and company_id is null and candidate_id is null)
  or (job_kind = 'MOLECULE_INTELLIGENCE' and molecule_id is not null and opportunity_id is null and company_id is null and candidate_id is null)
  or (job_kind = 'OPPORTUNITY_EVIDENCE' and company_id is not null and molecule_id is not null and candidate_id is not null and opportunity_id is null)
);
create index if not exists agent_research_jobs_candidate_idx on public.agent_research_jobs(candidate_id, status);

alter table public.company_molecules
  add column if not exists candidate_last_enrichment_at timestamptz,
  add column if not exists candidate_last_enrichment_outcome text;
