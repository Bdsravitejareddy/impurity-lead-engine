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
  candidate_score integer check (candidate_score between 0 and 100),
  candidate_status text check (candidate_status in ('UNQUALIFIED','QUALIFIED')),
  candidate_rationale text,
  candidate_signal_fingerprints text[] not null default '{}',
  candidate_last_signal_at timestamptz,
  candidate_last_evaluated_at timestamptz,
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
  source_ids uuid[] not null default '{}',
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
-- Resumable crawler execution. Additive; never removes lead data or review policies.
alter table public.crawl_runs
  add column if not exists fingerprint text,
  add column if not exists schema_version integer not null default 1,
  add column if not exists current_stage text,
  add column if not exists coordinator_token uuid,
  add column if not exists coordinator_owner text,
  add column if not exists coordinator_expires_at timestamptz,
  add column if not exists heartbeat_at timestamptz,
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists config_json jsonb not null default '{}' check (jsonb_typeof(config_json)='object' and octet_length(config_json::text)<=16384),
  add column if not exists metrics_json jsonb not null default '{}' check (jsonb_typeof(metrics_json)='object' and octet_length(metrics_json::text)<=16384);
create table public.crawl_tasks (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.crawl_runs(id),
  task_key text not null,
  task_type text not null,
  stage text not null,
  identifier text not null,
  domain text,
  status text not null default 'pending' check (status in ('pending','running','completed','skipped','retryable_failed','permanent_failed')),
  attempt_count integer not null default 0 check (attempt_count between 0 and 3),
  next_eligible_at timestamptz not null default now(),
  checkpoint_json jsonb not null default '{}' check (jsonb_typeof(checkpoint_json)='object' and octet_length(checkpoint_json::text)<=16384),
  result_json jsonb not null default '{}' check (jsonb_typeof(result_json)='object' and octet_length(result_json::text)<=4194304),
  lease_token uuid,
  lease_owner text,
  lease_expires_at timestamptz,
  last_error_code text check (last_error_code ~ '^[A-Za-z0-9_]{1,80}$'),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  duration_seconds double precision not null default 0 check (duration_seconds >= 0 and duration_seconds < 'Infinity'::float8),
  unique(run_id, task_key)
);
create index crawl_tasks_due on public.crawl_tasks(run_id,stage,next_eligible_at,task_key) where status in ('pending','retryable_failed');
create index crawl_tasks_expired on public.crawl_tasks(run_id,lease_expires_at) where status='running';
create index crawl_tasks_stage on public.crawl_tasks(run_id,stage,task_key);
create index crawl_runs_resume on public.crawl_runs(fingerprint,started_at desc) where status in ('running','paused');
alter table public.crawl_tasks enable row level security;
revoke all on public.crawl_tasks from public,anon,authenticated;
grant select,insert,update,delete on public.crawl_tasks to service_role;
-- Run summaries remain readable, but coordinator credentials/config/metrics are private.
revoke select on public.crawl_runs from authenticated;
grant select(id,started_at,completed_at,source_adapter,status,records_seen,records_inserted,errors,duration_seconds) on public.crawl_runs to authenticated;

create function public.crawl_check_run(p_run_id uuid,p_coordinator_token uuid) returns void
language plpgsql security invoker set search_path='' as $$
begin
  perform 1 from public.crawl_runs where id=p_run_id and coordinator_token=p_coordinator_token
    and coordinator_expires_at>clock_timestamp() and status='running' for update;
  if not found then raise exception 'coordinator_lease_lost'; end if;
end $$;
create function public.crawl_check_task(p_task_id uuid,p_token uuid,p_coordinator_token uuid) returns public.crawl_tasks
language plpgsql security invoker set search_path='' as $$
declare t public.crawl_tasks;
begin
  select * into t from public.crawl_tasks where id=p_task_id;
  perform public.crawl_check_run(t.run_id,p_coordinator_token);
  select * into t from public.crawl_tasks where id=p_task_id and lease_token=p_token
    and lease_expires_at>clock_timestamp() and status='running' for update;
  if not found then raise exception 'task_lease_lost'; end if;
  return t;
end $$;
create function public.crawl_begin(p_fingerprint text,p_owner text,p_fresh boolean,p_config jsonb,p_lease_seconds integer) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare r public.crawl_runs; resumed boolean := false;
begin
  if p_lease_seconds not between 1 and 3600 then raise exception 'invalid_lease'; end if;
  perform pg_advisory_xact_lock(713456982145::bigint);
  if exists(select 1 from public.crawl_runs where coordinator_expires_at>clock_timestamp()) then raise exception 'coordinator_busy'; end if;
  update public.crawl_runs set status='abandoned',completed_at=clock_timestamp(),updated_at=clock_timestamp()
    where fingerprint is not null and status in ('running','paused') and started_at<clock_timestamp()-interval '48 hours';
  if not p_fresh then
    select * into r from public.crawl_runs where fingerprint=p_fingerprint and schema_version=1
      and status in ('running','paused') and started_at>=clock_timestamp()-interval '48 hours' order by started_at desc limit 1 for update;
    resumed := found;
  end if;
  if not resumed then
    insert into public.crawl_runs(source_adapter,status,fingerprint,config_json)
      values('daily','running',p_fingerprint,p_config) returning * into r;
  end if;
  update public.crawl_runs set status='running',completed_at=null,coordinator_token=gen_random_uuid(),coordinator_owner=p_owner,
    coordinator_expires_at=clock_timestamp()+make_interval(secs=>p_lease_seconds),heartbeat_at=clock_timestamp(),updated_at=clock_timestamp()
    where id=r.id returning * into r;
  return to_jsonb(r)||jsonb_build_object('resumed',resumed);
end $$;
create function public.crawl_plan(p_run_id uuid,p_coordinator_token uuid,p_tasks jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
begin
  perform public.crawl_check_run(p_run_id,p_coordinator_token);
  if jsonb_typeof(p_tasks)<>'array' or octet_length(p_tasks::text)>4194304 then raise exception 'invalid_plan'; end if;
  insert into public.crawl_tasks(run_id,task_key,task_type,stage,identifier,domain,checkpoint_json)
    select p_run_id,x->>'task_key',x->>'task_type',x->>'stage',x->>'identifier',x->>'domain',coalesce(x->'checkpoint_json','{}')
    from jsonb_array_elements(p_tasks) x on conflict(run_id,task_key) do nothing;
  return jsonb_build_object('planned',true);
end $$;
create function public.crawl_claim(p_run_id uuid,p_coordinator_token uuid,p_stage text,p_owner text,p_lease_seconds integer) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare t public.crawl_tasks;
begin
  perform public.crawl_check_run(p_run_id,p_coordinator_token);
  if p_lease_seconds not between 1 and 3600 then raise exception 'invalid_lease'; end if;
  update public.crawl_tasks set status='permanent_failed',last_error_code='attempts_exhausted',completed_at=clock_timestamp(),updated_at=clock_timestamp(),lease_token=null,lease_expires_at=null
    where run_id=p_run_id and attempt_count>=3 and (status in ('pending','retryable_failed') or (status='running' and lease_expires_at<=clock_timestamp()));
  select * into t from public.crawl_tasks q where q.run_id=p_run_id and q.stage=p_stage and q.attempt_count<3
    and ((q.status in ('pending','retryable_failed') and q.next_eligible_at<=clock_timestamp()) or (q.status='running' and q.lease_expires_at<=clock_timestamp()))
    and not exists(select 1 from public.crawl_tasks active where active.domain=q.domain and active.status='running' and active.lease_expires_at>clock_timestamp())
    and not exists(select 1 from public.crawl_domains d where
      (d.domain=q.domain or (q.stage in ('company_crawling','contact_enrichment') and d.domain='index.commoncrawl.org'))
      and d.next_crawl_at>clock_timestamp())
    order by q.task_key for update skip locked limit 1;
  if not found then return null; end if;
  update public.crawl_tasks set status='running',attempt_count=attempt_count+1,lease_token=gen_random_uuid(),lease_owner=p_owner,
    lease_expires_at=clock_timestamp()+make_interval(secs=>p_lease_seconds),started_at=coalesce(started_at,clock_timestamp()),updated_at=clock_timestamp()
    where id=t.id returning * into t;
  return to_jsonb(t);
end $$;
create function public.crawl_heartbeat(p_run_id uuid,p_coordinator_token uuid,p_lease_seconds integer) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare r public.crawl_runs;
begin
  perform public.crawl_check_run(p_run_id,p_coordinator_token);
  if p_lease_seconds not between 1 and 3600 then raise exception 'invalid_lease'; end if;
  update public.crawl_runs set coordinator_expires_at=clock_timestamp()+make_interval(secs=>p_lease_seconds),heartbeat_at=clock_timestamp(),updated_at=clock_timestamp()
    where id=p_run_id returning * into r;
  return to_jsonb(r);
end $$;
create function public.crawl_save(p_task_id uuid,p_token uuid,p_coordinator_token uuid,p_status text,p_checkpoint jsonb,p_result jsonb,p_error text,p_delay_seconds double precision,p_duration_seconds double precision) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare t public.crawl_tasks;
begin
  t := public.crawl_check_task(p_task_id,p_token,p_coordinator_token);
  if p_status not in ('pending','running','completed','skipped','retryable_failed','permanent_failed') or p_delay_seconds<0 or p_delay_seconds>172800 or p_duration_seconds<0 then raise exception 'invalid_save'; end if;
  if p_status in ('pending','retryable_failed') and t.attempt_count>=3 then p_status:='permanent_failed'; end if;
  update public.crawl_tasks set status=p_status,checkpoint_json=p_checkpoint,result_json=p_result,last_error_code=p_error,
    next_eligible_at=clock_timestamp()+make_interval(secs=>p_delay_seconds),duration_seconds=duration_seconds+p_duration_seconds,
    completed_at=case when p_status in ('completed','skipped','permanent_failed') then clock_timestamp() else null end,
    lease_expires_at=case when p_status='running' then lease_expires_at else null end,
    lease_token=case when p_status='running' then lease_token else null end,updated_at=clock_timestamp()
    where id=p_task_id returning * into t;
  return to_jsonb(t);
end $$;
create function public.crawl_renew(p_task_id uuid,p_token uuid,p_coordinator_token uuid,p_lease_seconds integer) returns boolean
language plpgsql security invoker set search_path='' as $$
declare t public.crawl_tasks;
begin
  select * into t from public.crawl_tasks where id=p_task_id;
  if t.status <> 'running' then return false; end if;
  perform public.crawl_check_run(t.run_id,p_coordinator_token);
  select * into t from public.crawl_tasks where id=p_task_id for update;
  if t.status <> 'running' then return false; end if;
  t := public.crawl_check_task(p_task_id,p_token,p_coordinator_token);
  if p_lease_seconds not between 1 and 3600 then raise exception 'invalid_lease'; end if;
  update public.crawl_tasks set lease_expires_at=clock_timestamp()+make_interval(secs=>p_lease_seconds),updated_at=clock_timestamp() where id=p_task_id;
  return true;
end $$;
create function public.crawl_finish_run(p_run_id uuid,p_coordinator_token uuid,p_status text,p_stage text,p_metrics jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare r public.crawl_runs;
begin
  perform public.crawl_check_run(p_run_id,p_coordinator_token);
  if p_status not in ('running','paused','completed','completed_with_errors','failed') then raise exception 'invalid_run_status'; end if;
  update public.crawl_runs set status=p_status,current_stage=p_stage,metrics_json=p_metrics,updated_at=clock_timestamp(),
    records_seen=coalesce((p_metrics->>'records')::integer,records_seen),records_inserted=coalesce((p_metrics->>'signals')::integer,records_inserted),
    errors=coalesce((p_metrics->>'failure_count')::integer,errors),duration_seconds=coalesce((p_metrics->>'active_elapsed_seconds')::numeric,duration_seconds),
    completed_at=case when p_status in ('completed','completed_with_errors','failed') then clock_timestamp() else null end,
    coordinator_expires_at=case when p_status='running' then coordinator_expires_at else null end,
    coordinator_token=case when p_status='running' then coordinator_token else null end
    where id=p_run_id returning * into r;
  return to_jsonb(r);
end $$;
create function public.crawl_domain_result(p_domain text,p_success boolean,p_error text,p_cooldown_seconds double precision,p_task_id uuid,p_token uuid,p_coordinator_token uuid) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare d public.crawl_domains;
begin
  perform public.crawl_check_task(p_task_id,p_token,p_coordinator_token);
  if p_cooldown_seconds<0 or p_cooldown_seconds>172800 then raise exception 'invalid_cooldown'; end if;
  insert into public.crawl_domains(domain,error_count,last_crawled_at,next_crawl_at)
    values(p_domain,case when p_success then 0 else 1 end,clock_timestamp(),clock_timestamp()+make_interval(secs=>p_cooldown_seconds))
    on conflict(domain) do update set error_count=case when p_success then 0 else public.crawl_domains.error_count+1 end,
      last_crawled_at=clock_timestamp(),next_crawl_at=clock_timestamp()+make_interval(secs=>p_cooldown_seconds)
    returning * into d;
  return to_jsonb(d);
end $$;
create function public.crawl_publish(p_task_id uuid,p_token uuid,p_coordinator_token uuid,p_rows jsonb,p_checkpoint jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare t public.crawl_tasks; entry jsonb; data jsonb; tab text; conflict_key text; allowed text[]; cols text; updates text;
begin
  t := public.crawl_check_task(p_task_id,p_token,p_coordinator_token);
  if jsonb_typeof(p_rows)<>'array' or jsonb_array_length(p_rows)>500 or octet_length(p_rows::text)>4194304 then raise exception 'invalid_publication'; end if;
  for entry in select value from jsonb_array_elements(p_rows) loop
    tab:=entry->>'table'; data:=entry->'row';
    case tab
      when 'companies' then conflict_key:='id'; allowed:=array['id','normalized_name','legal_name','last_seen_at'];
      when 'molecules' then conflict_key:='id'; allowed:=array['id','canonical_name','last_seen_at'];
      when 'company_molecules' then conflict_key:='company_id,molecule_id'; allowed:=array['id','company_id','molecule_id','relationship_type','development_phase','regulatory_status','candidate_score','candidate_status','candidate_rationale','candidate_signal_fingerprints','candidate_last_signal_at','candidate_last_evaluated_at'];
      when 'signals' then conflict_key:='fingerprint'; allowed:=array['id','company_id','molecule_id','source_type','signal_type','source_url','source_record_id','evidence_text','event_date','discovered_at','freshness_days','base_weight','confidence','fingerprint','metadata_json'];
      when 'opportunities' then conflict_key:='company_id,molecule_id'; allowed:=array['id','company_id','molecule_id','score','priority','likely_need_type','rationale','decision_maker_role','last_qualified_at','last_signal_at'];
      when 'opportunity_signals' then conflict_key:='opportunity_id,signal_id'; allowed:=array['opportunity_id','signal_id','contribution_score'];
      when 'contacts' then conflict_key:='company_id,normalized_name'; allowed:=array['id','company_id','normalized_name','display_name','title','department','profile_url','primary_email','email_status','primary_phone','phone_status','role_fit_score','contact_confidence','first_seen_at','last_seen_at','last_verified_at'];
      when 'contact_evidence' then conflict_key:='fingerprint'; allowed:=array['id','contact_id','evidence_type','observed_value','source_type','source_url','evidence_text','observed_at','fingerprint','metadata_json'];
      when 'opportunity_contacts' then conflict_key:='opportunity_id,contact_id'; allowed:=array['opportunity_id','contact_id','role_fit_score','rank','rationale'];
      else raise exception 'invalid_publication_table';
    end case;
    if entry->>'on_conflict' is distinct from conflict_key or jsonb_typeof(data) is distinct from 'object'
      or exists(select 1 from jsonb_object_keys(data) k where not k=any(allowed)) then raise exception 'invalid_publication_columns'; end if;
    select string_agg(format('%I',k),',' order by k),
      string_agg(format('%I=excluded.%I',k,k),',' order by k) filter(where k not in ('id','first_seen_at','discovered_at','observed_at') and not k=any(string_to_array(conflict_key,',')))
      into cols,updates from jsonb_object_keys(data) k;
    if cols is null then raise exception 'empty_publication'; end if;
    -- Identifiers come exclusively from the fixed whitelist above; values remain bound JSON.
    execute format('insert into public.%I (%s) select %s from jsonb_populate_record(null::public.%I,$1) on conflict (%s) do %s',
      tab,cols,cols,tab,conflict_key,case when updates is null then 'nothing' else 'update set '||updates end) using data;
  end loop;
  -- Recheck wall-clock leases after potentially slow lead writes; exception rolls back all rows.
  t := public.crawl_check_task(p_task_id,p_token,p_coordinator_token);
  update public.crawl_tasks set checkpoint_json=p_checkpoint,updated_at=clock_timestamp() where id=p_task_id returning * into t;
  return to_jsonb(t);
end $$;
-- All new functions, including internal fence helpers, are service-only invokers.
do $$ declare f regprocedure;
begin
  for f in select p.oid::regprocedure from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname in ('crawl_check_run','crawl_check_task','crawl_begin','crawl_plan','crawl_claim','crawl_heartbeat','crawl_save','crawl_renew','crawl_finish_run','crawl_publish','crawl_domain_result') loop
    execute format('revoke all on function %s from public,anon,authenticated',f);
    execute format('grant execute on function %s to service_role',f);
  end loop;
end $$;
-- Molecule intelligence is defined additively in
-- migrations/20260912150000_molecule_intelligence.sql. Keep this schema
-- snapshot aligned for fresh environments.
alter table if exists public.research_claims add column if not exists claim_type text not null default 'OTHER';
alter table if exists public.research_claims drop constraint if exists research_claims_attribution_check;
alter table if exists public.research_claims add constraint research_claims_attribution_check check (attribution in ('PERSON_DIRECT','COMPANY_CONTEXT','OPPORTUNITY_CONTEXT','MOLECULE_CONTEXT'));
create table if not exists public.molecule_intelligence_sections (
  id uuid primary key default gen_random_uuid(), molecule_id uuid not null references public.molecules(id) on delete cascade,
  section_type text not null, summary_text text not null, supporting_claim_ids uuid[] not null default '{}',
  evidence_status text not null default 'UNKNOWN', source_count integer not null default 0, confidence numeric not null default 0,
  generated_at timestamptz not null default now(), generation_version integer not null default 1, updated_at timestamptz not null default now(),
  unique(molecule_id, section_type)
);
alter table public.molecule_intelligence_sections enable row level security;
revoke all on public.molecule_intelligence_sections from anon;
grant select on public.molecule_intelligence_sections to authenticated;
grant all on public.molecule_intelligence_sections to service_role;
alter table if exists public.agent_research_jobs add column if not exists job_kind text not null default 'CONTACT_RESEARCH';
alter table if exists public.agent_research_jobs add column if not exists molecule_id uuid references public.molecules(id) on delete cascade;
alter table if exists public.agent_research_jobs alter column opportunity_id drop not null;
