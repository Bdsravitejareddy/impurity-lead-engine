-- Reversible company soft merge, mirroring contacts.merged_into_contact_id.
-- The crawler keys companies by normalized name, so one group can arrive as
-- several rows ("Bayer" and "Bayer AG"). Readers resolve a merged row to its
-- survivor; no row, opportunity or signal is deleted or rewritten.
alter table if exists public.companies
  add column if not exists merged_into_company_id uuid references public.companies(id) on delete set null,
  add column if not exists merge_reason text,
  add column if not exists merged_at timestamptz;

create index if not exists companies_merged_into_company_idx
  on public.companies (merged_into_company_id)
  where merged_into_company_id is not null;

-- Reviewed duplicates seen on the dashboard on 2026-11-04. The survivor is the
-- row that already carries the company domain and linked contacts. Names are
-- matched exactly as displayed (legal_name, falling back to normalized_name);
-- a pair whose rows are not both present is skipped. Undo a merge with:
--   update public.companies set merged_into_company_id = null, merge_reason = null, merged_at = null where id = '<duplicate id>';
with pairs(duplicate_name, survivor_name) as (
  values
    ('Bayer', 'Bayer AG'),
    ('Takeda', 'Takeda Pharmaceuticals U.S.A., Inc.'),
    ('Hoffmann-La Roche', 'ROCHE'),
    ('AstraZeneca', 'AstraZeneca Pharmaceuticals'),
    ('Novo Nordisk A/S', 'NOVO NORDISK INC'),
    ('Novartis', 'Novartis Pharmaceuticals')
),
resolved as (
  select duplicate.id as duplicate_id, survivor.id as survivor_id
  from pairs
  join public.companies duplicate on lower(coalesce(duplicate.legal_name, duplicate.normalized_name)) = lower(pairs.duplicate_name)
  join public.companies survivor on lower(coalesce(survivor.legal_name, survivor.normalized_name)) = lower(pairs.survivor_name)
  where duplicate.id <> survivor.id
    and survivor.merged_into_company_id is null
)
update public.companies company
set merged_into_company_id = resolved.survivor_id,
    merge_reason = 'same_company_group_reviewed',
    merged_at = now()
from resolved
where company.id = resolved.duplicate_id
  and company.merged_into_company_id is null;
