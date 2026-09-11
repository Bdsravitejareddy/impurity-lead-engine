alter table public.contact_research_runs
  add column if not exists quality_metrics jsonb not null default '{}'::jsonb,
  add column if not exists ai_mode text,
  add column if not exists reason_for_ai_escalation text,
  add column if not exists ai_analysis_calls integer not null default 0,
  add column if not exists ai_web_search_calls integer not null default 0,
  add column if not exists ai_deep_calls integer not null default 0,
  add column if not exists documents_inspected integer not null default 0,
  add column if not exists people_discovered integer not null default 0,
  add column if not exists relationships_created integer not null default 0,
  add column if not exists stop_reason text;
