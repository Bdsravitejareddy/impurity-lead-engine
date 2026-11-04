-- Shared guest sign-in. The guest account's password is handed around, so the
-- database must not rely on the dashboard hiding buttons: restrictive
-- policies are ANDed with every existing permissive policy and block all
-- guest writes, while reads are unchanged.
-- The account itself is created in Supabase Auth (not here) with this email;
-- keep it in sync with GUEST_EMAIL in web/src/lib/guest.ts.
create or replace function public.is_guest()
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select coalesce(lower(auth.jwt() ->> 'email'), '') = 'guest@svak-intelligence.pages.dev'
$$;

grant execute on function public.is_guest() to authenticated;

do $$
declare t text;
begin
  -- Every table signed-in users can write to: the Contact 360 workspace,
  -- opportunity review status, and agent research submissions.
  foreach t in array array[
    'contact_sources','contact_positions','contact_education','contact_works','contact_problems','contact_themes',
    'contact_jtbd','contact_claims','contact_notes','contact_history','contact_conflicts','contact_research_runs',
    'opportunities','agent_research_submissions'
  ] loop
    execute format('drop policy if exists guest_no_insert on public.%I', t);
    execute format('create policy guest_no_insert on public.%I as restrictive for insert to authenticated with check (not public.is_guest())', t);
    execute format('drop policy if exists guest_no_update on public.%I', t);
    execute format('create policy guest_no_update on public.%I as restrictive for update to authenticated using (not public.is_guest()) with check (not public.is_guest())', t);
    execute format('drop policy if exists guest_no_delete on public.%I', t);
    execute format('create policy guest_no_delete on public.%I as restrictive for delete to authenticated using (not public.is_guest())', t);
  end loop;
end $$;
