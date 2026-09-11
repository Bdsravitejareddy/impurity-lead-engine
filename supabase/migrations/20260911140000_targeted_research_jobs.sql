create table if not exists public.targeted_research_jobs (
  id uuid primary key default gen_random_uuid(),
  opportunity_id uuid not null references public.opportunities(id) on delete cascade,
  contact_id uuid references public.contacts(id) on delete set null,
  missing_dimension text not null,
  search_intent text not null,
  priority integer not null default 0,
  max_rounds integer not null default 2,
  status text not null default 'QUEUED' check (status in ('QUEUED','RUNNING','COMPLETED','PARTIAL','FAILED')),
  active_key text generated always as (case when status in ('QUEUED','RUNNING') then 'ACTIVE' else id::text end) stored,
  metadata jsonb not null default '{}'::jsonb,
  metrics jsonb not null default '{}'::jsonb,
  stop_reason text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);
create unique index if not exists targeted_research_active_idx on public.targeted_research_jobs(opportunity_id, missing_dimension, active_key);
create index if not exists targeted_research_queue_idx on public.targeted_research_jobs(status, priority desc, created_at);
alter table public.targeted_research_jobs enable row level security;
revoke all on public.targeted_research_jobs from anon;
grant select on public.targeted_research_jobs to authenticated;
grant all on public.targeted_research_jobs to service_role;
drop policy if exists authenticated_read on public.targeted_research_jobs;
create policy authenticated_read on public.targeted_research_jobs for select to authenticated using (true);
