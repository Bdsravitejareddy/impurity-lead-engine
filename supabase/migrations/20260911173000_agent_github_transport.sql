alter table public.agent_research_jobs add column if not exists github_issue_number bigint;
alter table public.agent_research_jobs add column if not exists github_issue_url text;
alter table public.agent_research_jobs add column if not exists work_rounds integer not null default 0;
alter table public.agent_research_submissions add column if not exists source_channel text not null default 'MANUAL_UI';
alter table public.agent_research_submissions add column if not exists github_issue_number bigint;
alter table public.agent_research_submissions add column if not exists github_comment_id bigint;
alter table public.agent_research_submissions add column if not exists github_comment_url text;
alter table public.agent_research_submissions alter column submitted_by drop not null;
create unique index if not exists agent_research_submission_comment_idx on public.agent_research_submissions(github_issue_number, github_comment_id) where github_issue_number is not null and github_comment_id is not null;
