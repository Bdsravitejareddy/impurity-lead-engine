alter table public.opportunity_contacts
  add column if not exists source_ids uuid[] not null default '{}';

comment on column public.opportunity_contacts.source_ids is
  'Contact source records supporting this explicit opportunity link.';
