-- Prevent future ingestion from linking new opportunities to a soft-merged
-- contact. The survivor remains the only canonical person for new writes.
create or replace function public.reject_merged_opportunity_contact()
returns trigger
language plpgsql
security invoker
as $$
begin
  if exists (
    select 1 from public.contacts c
    where c.id = new.contact_id
      and c.merged_into_contact_id is not null
  ) then
    raise exception 'merged_contact_not_writable';
  end if;
  return new;
end;
$$;

drop trigger if exists reject_merged_opportunity_contact on public.opportunity_contacts;
create trigger reject_merged_opportunity_contact
before insert or update of contact_id on public.opportunity_contacts
for each row execute function public.reject_merged_opportunity_contact();
