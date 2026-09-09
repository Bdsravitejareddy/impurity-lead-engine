alter table public.contact_research_runs add column if not exists sources_rejected integer not null default 0;
