-- People finder: when each company was last searched on Hunter.io, and the
-- email pattern it reported, so named contacts found elsewhere can be given
-- an address when Hunter's monthly allowance is used up.
alter table if exists public.companies
  add column if not exists people_checked_at timestamptz,
  add column if not exists email_pattern text,
  add column if not exists email_pattern_source text;
