-- Read-only audit of company normalization keys. Selects only.
-- Needs public.company_normalization_key() from
-- migrations/20261104130000_company_normalization.sql.
--
-- Before the migration: every key shared by more than one unmerged row is a
-- group the migration will soft-merge, survivor first.
-- After the migration: no row should report unmerged_rows > 1, and each
-- merged row should resolve to a survivor that is itself unmerged.
with recursive keyed as (
  select company.id,
         company.normalized_name,
         company.legal_name,
         company.domain,
         company.merged_into_company_id,
         company.merge_reason,
         public.company_normalization_key(company.normalized_name) as key
  from public.companies company
),
resolution(id, survivor_id, depth) as (
  select id, id, 0 from keyed where merged_into_company_id is null
  union all
  select child.id, resolution.survivor_id, resolution.depth + 1
  from keyed child
  join resolution on child.merged_into_company_id = resolution.id
  where resolution.depth < 10
),
groups as (
  select key,
         count(*) as rows_with_key,
         count(*) filter (where merged_into_company_id is null) as unmerged_rows
  from keyed
  where key <> ''
  group by key
  having count(*) > 1
)
select groups.key,
       groups.rows_with_key,
       groups.unmerged_rows,
       keyed.id,
       keyed.legal_name,
       keyed.normalized_name,
       keyed.domain,
       keyed.merged_into_company_id,
       keyed.merge_reason,
       resolution.survivor_id,
       resolution.depth as merge_depth,
       (select count(*) from public.contacts contact where contact.company_id = keyed.id) as contacts,
       (select count(*) from public.opportunities opportunity where opportunity.company_id = keyed.id) as opportunities,
       (select count(*) from public.signals signal where signal.company_id = keyed.id) as signals
from groups
join keyed on keyed.key = groups.key
left join resolution on resolution.id = keyed.id
order by groups.unmerged_rows desc, groups.key, keyed.merged_into_company_id nulls first, keyed.domain nulls last, keyed.id;
