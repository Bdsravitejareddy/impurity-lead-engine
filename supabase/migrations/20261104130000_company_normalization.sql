-- Company keys now strip punctuation first and then legal forms and group
-- words repeatedly ("Takeda Pharmaceuticals U.S.A., Inc." -> "takeda").
-- Company ids derive from that key, so existing rows would no longer match the
-- crawler's ids. Nothing is re-keyed or deleted: the crawler resolves each new
-- key to the stored row that owns it (following merged_into_company_id), and
-- this migration soft-merges unmerged rows whose names now share a key.
--
-- public.company_normalization_key() mirrors
-- impurity_leads.normalize.normalize_company_name(); keep the suffix lists equal.
-- Preview and verify with supabase/audits/company_normalization_audit.sql.
create or replace function public.company_normalization_key(p_name text) returns text
language plpgsql immutable set search_path='' as $$
declare
  value text;
  stripped text;
begin
  value := regexp_replace(lower(coalesce(p_name, '')), '[.''’]', '', 'g');
  value := btrim(regexp_replace(value, '[^[:alnum:]]+', ' ', 'g'));
  loop
    stripped := regexp_replace(value,
      '\s+(incorporated|inc|limited|ltd|llc|llp|lp|plc|corporation|corp|co|ag|gmbh|kg|sa|nv|bv|se|kk|pvt|private|spa|srl|ab|a s|holdings|holding|usa|us|pharmaceuticals|pharmaceutical|pharma)$',
      '');
    if stripped = value then
      return value;
    end if;
    value := stripped;
  end loop;
end $$;

-- The survivor of a group is the row the dashboard already treats as the
-- company: it carries a domain, absorbs reviewed merges, has the most contacts,
-- then is the oldest. Undo one merge with:
--   update public.companies set merged_into_company_id = null, merge_reason = null, merged_at = null where id = '<duplicate id>';
with keyed as (
  select company.id,
         public.company_normalization_key(company.normalized_name) as key,
         company.domain is not null as has_domain,
         (select count(*) from public.companies child where child.merged_into_company_id = company.id) as merged_children,
         (select count(*) from public.contacts contact where contact.company_id = company.id) as contacts,
         company.first_seen_at
  from public.companies company
  where company.merged_into_company_id is null
),
ranked as (
  select keyed.id,
         first_value(keyed.id) over (
           partition by keyed.key
           order by keyed.has_domain desc, keyed.merged_children desc, keyed.contacts desc, keyed.first_seen_at, keyed.id
         ) as survivor_id
  from keyed
  where keyed.key <> ''
)
update public.companies company
set merged_into_company_id = ranked.survivor_id,
    merge_reason = 'normalized_name_collision',
    merged_at = now()
from ranked
where company.id = ranked.id
  and ranked.id <> ranked.survivor_id
  and company.merged_into_company_id is null;
