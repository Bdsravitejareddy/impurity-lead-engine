-- Shared sales pipeline. Stages used to live in each browser's localStorage,
-- so teammates could not see them and outcomes could not be measured.
-- pipeline_key is lower(company)|lower(molecule), matching the dashboard.
create table if not exists public.opportunity_pipeline (
  pipeline_key text primary key,
  company_name text not null,
  molecule_name text not null,
  stage text not null default 'NEW'
    check (stage in ('NEW','REVIEWED','OUTREACH READY','CONTACTED','REPLIED','MEETING','RFQ','WON','LOST')),
  updated_by text default (auth.jwt() ->> 'email'),
  updated_at timestamptz not null default now()
);

-- Every stage change, for conversion and time-in-stage reporting.
create table if not exists public.opportunity_pipeline_events (
  id uuid primary key default gen_random_uuid(),
  pipeline_key text not null,
  from_stage text,
  to_stage text not null,
  changed_by text,
  changed_at timestamptz not null default now()
);
create index if not exists opportunity_pipeline_events_key_idx on public.opportunity_pipeline_events (pipeline_key, changed_at);

create or replace function public.record_pipeline_event() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if tg_op = 'INSERT' or new.stage is distinct from old.stage then
    insert into public.opportunity_pipeline_events (pipeline_key, from_stage, to_stage, changed_by)
    values (new.pipeline_key, case when tg_op = 'UPDATE' then old.stage end, new.stage, new.updated_by);
  end if;
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists record_pipeline_event on public.opportunity_pipeline;
create trigger record_pipeline_event
before insert or update on public.opportunity_pipeline
for each row execute function public.record_pipeline_event();

alter table public.opportunity_pipeline enable row level security;
alter table public.opportunity_pipeline_events enable row level security;
revoke all on table public.opportunity_pipeline from anon;
revoke all on table public.opportunity_pipeline_events from anon;
grant select, insert, update on table public.opportunity_pipeline to authenticated;
grant select on table public.opportunity_pipeline_events to authenticated;
grant all on table public.opportunity_pipeline to service_role;
grant all on table public.opportunity_pipeline_events to service_role;

drop policy if exists pipeline_read on public.opportunity_pipeline;
create policy pipeline_read on public.opportunity_pipeline for select to authenticated using (true);
drop policy if exists pipeline_write on public.opportunity_pipeline;
create policy pipeline_write on public.opportunity_pipeline for insert to authenticated with check (not public.is_guest());
drop policy if exists pipeline_update on public.opportunity_pipeline;
create policy pipeline_update on public.opportunity_pipeline for update to authenticated using (not public.is_guest()) with check (not public.is_guest());
drop policy if exists pipeline_events_read on public.opportunity_pipeline_events;
create policy pipeline_events_read on public.opportunity_pipeline_events for select to authenticated using (true);
