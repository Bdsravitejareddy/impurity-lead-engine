create table if not exists public.agent_research_jobs (
  id uuid primary key default gen_random_uuid(),
  targeted_research_job_id uuid references public.targeted_research_jobs(id) on delete set null,
  opportunity_id uuid not null references public.opportunities(id) on delete cascade,
  contact_id uuid references public.contacts(id) on delete set null,
  priority integer not null default 0,
  research_goal text not null,
  missing_dimensions jsonb not null default '[]'::jsonb,
  known_entities jsonb not null default '{}'::jsonb,
  known_contacts jsonb not null default '[]'::jsonb,
  known_sources jsonb not null default '[]'::jsonb,
  known_claims jsonb not null default '[]'::jsonb,
  quality_before jsonb not null default '{}'::jsonb,
  agent_prompt text not null,
  dedupe_key text not null unique,
  status text not null default 'READY' check (status in ('QUEUED','READY','EXPORTED','RESULT_SUBMITTED','VALIDATING','APPLIED','PARTIAL','REJECTED','FAILED')),
  created_at timestamptz not null default now(), exported_at timestamptz, submitted_at timestamptz, validated_at timestamptz, completed_at timestamptz,
  stop_reason text,
  metrics jsonb not null default '{}'::jsonb
);
create index if not exists agent_research_jobs_status_idx on public.agent_research_jobs(status, priority desc, created_at);
create table if not exists public.agent_research_submissions (
  id uuid primary key default gen_random_uuid(),
  agent_job_id uuid not null references public.agent_research_jobs(id) on delete cascade,
  submitted_by uuid not null references auth.users(id),
  submitted_at timestamptz not null default now(),
  raw_result_json jsonb not null,
  schema_valid boolean not null default false,
  validation_status text not null default 'PENDING' check (validation_status in ('PENDING','VALID','PARTIAL','REJECTED')),
  validation_errors jsonb not null default '[]'::jsonb,
  processed_at timestamptz
);
alter table public.agent_research_jobs enable row level security;
alter table public.agent_research_submissions enable row level security;
revoke all on public.agent_research_jobs, public.agent_research_submissions from anon;
grant select on public.agent_research_jobs to authenticated;
grant select,insert on public.agent_research_submissions to authenticated;
grant all on public.agent_research_jobs, public.agent_research_submissions to service_role;
drop policy if exists authenticated_read on public.agent_research_jobs;
create policy authenticated_read on public.agent_research_jobs for select to authenticated using (true);
drop policy if exists own_submission_insert on public.agent_research_submissions;
create policy own_submission_insert on public.agent_research_submissions for insert to authenticated with check (submitted_by = auth.uid());
drop policy if exists own_submission_read on public.agent_research_submissions;
create policy own_submission_read on public.agent_research_submissions for select to authenticated using (submitted_by = auth.uid());
