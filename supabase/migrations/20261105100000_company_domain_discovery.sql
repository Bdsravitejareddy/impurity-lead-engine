-- Automatic website discovery for qualified companies (seed_sources.py).
-- domain_source says where a website came from; domain_checked_at lets a
-- company without a findable website wait 30 days before the next attempt.
alter table if exists public.companies
  add column if not exists domain_source text,
  add column if not exists domain_checked_at timestamptz;

update public.companies
set domain_source = 'LEGACY'
where domain is not null and domain_source is null;
