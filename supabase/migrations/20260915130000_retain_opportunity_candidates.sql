-- Retain resolved company/molecule pairs even when their score is below the
-- commercial qualification threshold. Existing opportunity rows remain
-- HOT/HIGH/REVIEW only; these additive fields support later rescoring.
alter table public.company_molecules
  add column if not exists candidate_score integer,
  add column if not exists candidate_status text,
  add column if not exists candidate_rationale text,
  add column if not exists candidate_signal_fingerprints text[] not null default '{}',
  add column if not exists candidate_last_signal_at timestamptz,
  add column if not exists candidate_last_evaluated_at timestamptz;
alter table public.company_molecules drop constraint if exists company_molecules_candidate_status_check;
alter table public.company_molecules add constraint company_molecules_candidate_status_check
  check (candidate_status is null or candidate_status in ('UNQUALIFIED','QUALIFIED'));
alter table public.company_molecules drop constraint if exists company_molecules_candidate_score_check;
alter table public.company_molecules add constraint company_molecules_candidate_score_check
  check (candidate_score is null or candidate_score between 0 and 100);
create index if not exists company_molecules_candidate_status_idx
  on public.company_molecules(candidate_status, candidate_score desc);

-- Extend the existing bounded publication whitelist for candidate rows.
create or replace function public.crawl_publish(p_task_id uuid,p_token uuid,p_coordinator_token uuid,p_rows jsonb,p_checkpoint jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare t public.crawl_tasks; entry jsonb; data jsonb; tab text; conflict_key text; allowed text[]; cols text; updates text;
begin
  t := public.crawl_check_task(p_task_id,p_token,p_coordinator_token);
  if jsonb_typeof(p_rows)<>'array' or jsonb_array_length(p_rows)>500 or octet_length(p_rows::text)>4194304 then raise exception 'invalid_publication'; end if;
  for entry in select value from jsonb_array_elements(p_rows) loop
    tab:=entry->>'table'; data:=entry->'row';
    case tab
      when 'companies' then conflict_key:='id'; allowed:=array['id','normalized_name','legal_name','last_seen_at'];
      when 'molecules' then conflict_key:='id'; allowed:=array['id','canonical_name','last_seen_at'];
      when 'company_molecules' then conflict_key:='company_id,molecule_id'; allowed:=array['id','company_id','molecule_id','relationship_type','development_phase','regulatory_status','candidate_score','candidate_status','candidate_rationale','candidate_signal_fingerprints','candidate_last_signal_at','candidate_last_evaluated_at'];
      when 'signals' then conflict_key:='fingerprint'; allowed:=array['id','company_id','molecule_id','source_type','signal_type','source_url','source_record_id','evidence_text','event_date','discovered_at','freshness_days','base_weight','confidence','fingerprint','metadata_json'];
      when 'opportunities' then conflict_key:='company_id,molecule_id'; allowed:=array['id','company_id','molecule_id','score','priority','likely_need_type','rationale','decision_maker_role','last_qualified_at','last_signal_at'];
      when 'opportunity_signals' then conflict_key:='opportunity_id,signal_id'; allowed:=array['opportunity_id','signal_id','contribution_score'];
      when 'contacts' then conflict_key:='company_id,normalized_name'; allowed:=array['id','company_id','normalized_name','display_name','title','department','profile_url','primary_email','email_status','primary_phone','phone_status','role_fit_score','contact_confidence','first_seen_at','last_seen_at','last_verified_at'];
      when 'contact_evidence' then conflict_key:='fingerprint'; allowed:=array['id','contact_id','evidence_type','observed_value','source_type','source_url','evidence_text','observed_at','fingerprint','metadata_json'];
      when 'opportunity_contacts' then conflict_key:='opportunity_id,contact_id'; allowed:=array['opportunity_id','contact_id','role_fit_score','rank','rationale'];
      else raise exception 'invalid_publication_table';
    end case;
    if entry->>'on_conflict' is distinct from conflict_key or jsonb_typeof(data) is distinct from 'object'
      or exists(select 1 from jsonb_object_keys(data) k where not k=any(allowed)) then raise exception 'invalid_publication_columns'; end if;
    select string_agg(format('%I',k),',' order by k),
      string_agg(format('%I=excluded.%I',k,k),',' order by k) filter(where k not in ('id','first_seen_at','discovered_at','observed_at') and not k=any(string_to_array(conflict_key,',')))
      into cols,updates from jsonb_object_keys(data) k;
    if cols is null then raise exception 'empty_publication'; end if;
    execute format('insert into public.%I (%s) select %s from jsonb_populate_record(null::public.%I,$1) on conflict (%s) do %s',
      tab,cols,cols,tab,conflict_key,case when updates is null then 'nothing' else 'update set '||updates end) using data;
  end loop;
  t := public.crawl_check_task(p_task_id,p_token,p_coordinator_token);
  update public.crawl_tasks set checkpoint_json=p_checkpoint,updated_at=clock_timestamp() where id=p_task_id returning * into t;
  return to_jsonb(t);
end $$;
