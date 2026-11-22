-- Hunter.io people lookup: when each company was last searched, so the
-- free-plan search budget is spent once per company per month.
alter table if exists public.companies
  add column if not exists people_checked_at timestamptz;
