-- Government tenders from GeM bid alert emails (impurity_leads.tenders).
create table if not exists public.tenders (
  bid_number text primary key,
  items text,
  quantity text,
  ministry text,
  department text,
  organisation text,
  location text,
  start_date date,
  end_date date,
  url text not null,
  source text not null default 'gem_email_alert',
  is_relevant boolean not null default false,
  excerpt text,
  received_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists tenders_end_date on public.tenders (end_date desc);

alter table public.tenders enable row level security;
revoke all on table public.tenders from anon;
grant select on table public.tenders to authenticated;
grant all on table public.tenders to service_role;
drop policy if exists tenders_read on public.tenders;
create policy tenders_read on public.tenders for select to authenticated using (true);
