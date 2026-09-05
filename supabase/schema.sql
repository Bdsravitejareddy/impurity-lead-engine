create extension if not exists pgcrypto;

create table if not exists public.companies (
  id uuid primary key,
  normalized_name text not null unique,
  legal_name text,
  domain text,
  country text,
  company_type text,
  is_impurity_vendor boolean not null default false,
  is_cro_cdmo boolean not null default false,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

create table if not exists public.molecules (
  id uuid primary key,
  canonical_name text not null,
  synonyms text[] not null default '{}',
  cas_number text,
  unii text,
  development_code text,
  molecule_type text,
  small_molecule boolean,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

create table if not exists public.company_molecules (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  molecule_id uuid not null references public.molecules(id) on delete cascade,
  relationship_type text,
  development_phase text,
  regulatory_status text,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique(company_id, molecule_id)
);

create table if not exists public.signals (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  molecule_id uuid references public.molecules(id) on delete set null,
  source_type text not null,
  signal_type text not null,
  source_url text not null,
  source_record_id text,
  evidence_text text not null,
  event_date timestamptz,
  discovered_at timestamptz not null default now(),
  freshness_days integer,
  base_weight integer not null,
  confidence numeric(5,4) not null check (confidence >= 0 and confidence <= 1),
  fingerprint text not null unique,
  metadata_json jsonb not null default '{}'::jsonb
);

create table if not exists public.opportunities (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  molecule_id uuid not null references public.molecules(id) on delete cascade,
  score integer not null check (score >= 0 and score <= 100),
  priority text not null check (priority in ('HOT','HIGH','REVIEW')),
  likely_need_type text[] not null default '{}',
  rationale text not null,
  decision_maker_role text[] not null default '{}',
  first_qualified_at timestamptz not null default now(),
  last_qualified_at timestamptz not null default now(),
  last_signal_at timestamptz,
  status text not null default 'new' check (status in ('new','reviewed','qualified','dismissed','contacted')),
  dismissal_reason text,
  unique(company_id, molecule_id)
);

create table if not exists public.opportunity_signals (
  opportunity_id uuid not null references public.opportunities(id) on delete cascade,
  signal_id uuid not null references public.signals(id) on delete cascade,
  contribution_score integer not null default 0,
  primary key(opportunity_id, signal_id)
);

create table if not exists public.crawl_runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  source_adapter text not null,
  status text not null,
  records_seen integer not null default 0,
  records_inserted integer not null default 0,
  errors integer not null default 0,
  duration_seconds numeric not null default 0
);

create table if not exists public.crawl_domains (
  domain text primary key,
  crawl_state text not null default 'active',
  last_crawled_at timestamptz,
  next_crawl_at timestamptz,
  robots_status text,
  error_count integer not null default 0,
  average_response_ms numeric
);

create index if not exists idx_signals_company_molecule_event
  on public.signals(company_id, molecule_id, event_date desc);
create index if not exists idx_opportunities_priority_score
  on public.opportunities(priority, score desc);
create index if not exists idx_crawl_domains_next
  on public.crawl_domains(next_crawl_at);
create index if not exists idx_company_domain
  on public.companies(domain);

alter table public.companies enable row level security;
alter table public.molecules enable row level security;
alter table public.company_molecules enable row level security;
alter table public.signals enable row level security;
alter table public.opportunities enable row level security;
alter table public.opportunity_signals enable row level security;
alter table public.crawl_runs enable row level security;
alter table public.crawl_domains enable row level security;

revoke all on table public.companies from anon;
revoke all on table public.molecules from anon;
revoke all on table public.company_molecules from anon;
revoke all on table public.signals from anon;
revoke all on table public.opportunities from anon;
revoke all on table public.opportunity_signals from anon;
revoke all on table public.crawl_runs from anon;
revoke all on table public.crawl_domains from anon;

grant select on table public.companies to authenticated;
grant select on table public.molecules to authenticated;
grant select on table public.company_molecules to authenticated;
grant select on table public.signals to authenticated;
grant select on table public.opportunities to authenticated;
grant select on table public.opportunity_signals to authenticated;
grant select on table public.crawl_runs to authenticated;
grant select on table public.crawl_domains to authenticated;
grant update (status, dismissal_reason) on table public.opportunities to authenticated;

grant select, insert, update, delete on table public.companies to service_role;
grant select, insert, update, delete on table public.molecules to service_role;
grant select, insert, update, delete on table public.company_molecules to service_role;
grant select, insert, update, delete on table public.signals to service_role;
grant select, insert, update, delete on table public.opportunities to service_role;
grant select, insert, update, delete on table public.opportunity_signals to service_role;
grant select, insert, update, delete on table public.crawl_runs to service_role;
grant select, insert, update, delete on table public.crawl_domains to service_role;

create policy authenticated_read_companies on public.companies
  for select to authenticated using (true);
create policy authenticated_read_molecules on public.molecules
  for select to authenticated using (true);
create policy authenticated_read_company_molecules on public.company_molecules
  for select to authenticated using (true);
create policy authenticated_read_signals on public.signals
  for select to authenticated using (true);
create policy authenticated_read_opportunities on public.opportunities
  for select to authenticated using (true);
create policy authenticated_update_opportunity_review on public.opportunities
  for update to authenticated using (true) with check (true);
create policy authenticated_read_opportunity_signals on public.opportunity_signals
  for select to authenticated using (true);
create policy authenticated_read_crawl_runs on public.crawl_runs
  for select to authenticated using (true);
create policy authenticated_read_crawl_domains on public.crawl_domains
  for select to authenticated using (true);

create table if not exists public.contacts (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  normalized_name text not null,
  display_name text not null,
  title text,
  department text,
  profile_url text,
  primary_email text,
  email_status text not null default 'ROLE_ONLY' check (email_status in ('VERIFIED_PUBLIC','PATTERN_CONFIRMED','ROLE_ONLY','STALE')),
  primary_phone text,
  phone_status text not null default 'ROLE_ONLY' check (phone_status in ('VERIFIED_PUBLIC','ROLE_ONLY','STALE')),
  role_fit_score integer not null default 0 check (role_fit_score >= 0 and role_fit_score <= 100),
  contact_confidence numeric(5,4) not null default 0 check (contact_confidence >= 0 and contact_confidence <= 1),
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  last_verified_at timestamptz,
  unique(company_id, normalized_name)
);

create table if not exists public.contact_evidence (
  id uuid primary key,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  evidence_type text not null check (evidence_type in ('identity','title','email','phone','affiliation','email_pattern')),
  observed_value text not null,
  source_type text not null,
  source_url text not null,
  evidence_text text not null check (char_length(evidence_text) <= 800),
  observed_at timestamptz not null,
  fingerprint text not null unique,
  metadata_json jsonb not null default '{}'::jsonb
);

create table if not exists public.opportunity_contacts (
  opportunity_id uuid not null references public.opportunities(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  role_fit_score integer not null check (role_fit_score >= 0 and role_fit_score <= 100),
  rank integer not null check (rank >= 1 and rank <= 3),
  rationale text not null,
  primary key(opportunity_id, contact_id)
);

create index if not exists idx_contacts_company_role_fit
  on public.contacts(company_id, role_fit_score desc);
create index if not exists idx_opportunity_contacts_rank
  on public.opportunity_contacts(opportunity_id, rank);
create index if not exists idx_contact_evidence_contact_observed
  on public.contact_evidence(contact_id, observed_at desc);

alter table public.contacts enable row level security;
alter table public.contact_evidence enable row level security;
alter table public.opportunity_contacts enable row level security;

revoke all on table public.contacts from anon;
revoke all on table public.contact_evidence from anon;
revoke all on table public.opportunity_contacts from anon;

grant select on table public.contacts to authenticated;
grant select on table public.contact_evidence to authenticated;
grant select on table public.opportunity_contacts to authenticated;

grant select, insert, update, delete on table public.contacts to service_role;
grant select, insert, update, delete on table public.contact_evidence to service_role;
grant select, insert, update, delete on table public.opportunity_contacts to service_role;

create policy authenticated_read_contacts on public.contacts
  for select to authenticated using (true);
create policy authenticated_read_contact_evidence on public.contact_evidence
  for select to authenticated using (true);
create policy authenticated_read_opportunity_contacts on public.opportunity_contacts
  for select to authenticated using (true);
