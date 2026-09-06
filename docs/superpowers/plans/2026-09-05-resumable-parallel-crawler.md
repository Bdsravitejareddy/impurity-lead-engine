# Resumable Parallel Crawler Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development for independently reviewable tasks. Execute continuously under the user's approval; production migration is excluded.

**Goal:** Durable, polite, observable six-worker crawling with equivalent serial/resume results.
**Architecture:** Synchronous adapters, threaded network stages, Supabase task/run RPC coordination, deterministic stage barriers and fenced durable parsed outputs.
**Tech Stack:** Python 3.12+, httpx, PostgreSQL/Supabase, pytest, Rich presentation only.
**Spec:** docs/superpowers/specs/2026-09-05-resumable-parallel-crawler-design.md

## Global constraints

- feature/resumable-parallel-crawler only; .env protected; no production DDL.
- 48-hour auto-resume, stable material fingerprint, three total claimed attempts.
- 16 KiB checkpoint guard, 4 MiB parsed-output guard; no raw HTML/API envelopes/secrets.
- Six workers default, one request per host, one coordinator, token-fenced writes.
- Existing scoring/verification semantics and 117 regression tests preserved.
- 5s connect/pool, 20s read/write, 300s task slice, 42min invocation, 30s drain configurable.

## Task 1 — Database state and migration

Files: supabase/migrations/*_resumable_crawler.sql, supabase/schema.sql, tests/integration/test_execution_db.py, tests/integration/conftest.py.
Interfaces: RPCs crawl_begin(p_fingerprint,p_owner,p_fresh,p_config,p_lease_seconds); crawl_plan(p_run_id,p_coordinator_token,p_tasks); crawl_claim(p_run_id,p_coordinator_token,p_stage,p_owner,p_lease_seconds); crawl_heartbeat(p_run_id,p_coordinator_token,p_lease_seconds); crawl_save(p_task_id,p_token,p_coordinator_token,p_status,p_checkpoint,p_result,p_error,p_delay_seconds,p_duration_seconds); crawl_renew(p_task_id,p_token,p_coordinator_token,p_lease_seconds); crawl_finish_run(p_run_id,p_coordinator_token,p_status,p_stage,p_metrics); crawl_publish(p_task_id,p_token,p_coordinator_token,p_rows,p_checkpoint); crawl_domain_result(p_domain,p_success,p_error,p_cooldown_seconds).
RPC JSON results: run/task object or null where no claim; fenced mutations raise on lost ownership. begin returns run object with coordinator_token and resumed bool. plan task dict keys task_key/task_type/stage/identifier/domain/checkpoint_json.
- [ ] Write failing disposable PostgreSQL tests: two concurrent begin calls yield one owner; two claims yield distinct tasks; expired token cannot save; attempt 3 exhausted; age >48h abandoned; duplicate publication preserves row counts.
- [ ] Run `.venv/bin/python -m pytest tests/integration -q` and observe failures.
- [ ] Implement additive migration, guards/indexes/service-only RPCs. Publication whitelist only existing lead table names/conflict keys; transaction checks task lease before writes.
- [ ] Run migration tests, include anon/auth denial and existing schema preservation.
- [ ] Review and commit database unit.

## Task 2 — Worker orchestration and policies

Files: src/impurity_leads/execution/{tasks,runner,retry,progress}.py; tests/execution/test_runner.py.
Interfaces: TaskStore.begin(fingerprint,owner,fresh,config)->dict; plan(run,tasks); claim(stage)->dict|None; save(task,status,checkpoint,result,error,delay,duration); renew(task); heartbeat(); finish(status,stage,metrics); tasks()->list; domain_result(...); publish(task,rows,checkpoint). Run ownership retained by store instance. Execution context exposes checkpoint/save_progress, cancellation and deadline. Runner.run_stage(stage, handler) returns stage terminal status, with bounded daemon workers, no nested retries.
- [ ] Tests first: cap six active workers, never reclaim terminal tasks, scheduler persists retry delay, no >3 attempts after restart, cancellation drains boundedly, outages pause claims, safe JSON progress and ETA.
- [ ] Implement models/guards/fingerprints, typed safe failures, scheduler, events independent of Rich.
- [ ] Run tests with deterministic clocks/randomness and fake store matching DB contract.
- [ ] Review and commit scheduler unit.

## Task 3 — Crawl tasks and integration

Files: src/impurity_leads/execution/{crawl,daily}.py, storage/task_store.py, cli.py, config.py, crawling/client.py, contacts/pipeline.py.
Interfaces: daily.run_daily(settings,workers=6,fresh=False) executes stage graph using task store. crawl task handlers consume task checkpoint and durable partial result, emit compact SourceRecord/contact candidate models. Existing `process_records(records, MemoryLeadStore())` generates exact lead results; contact candidate ranking helper shares existing logic. CLI fixture path unchanged.
- [ ] Tests first: source403 skip, robots404/403, page checkpoint resume, serial/six-worker/interrupted equality, no credentials database fallback, --fresh/status argparse, host pacing and HTTPS redirects.
- [ ] Implement output checkpointing at each completed page/source; one per-domain task and task retry owner. Stage planner atomically upserts deterministic keys. Save scoring output before contacts/persistence; reuse original row serializers through an in-memory row collector before transactional publish batches.
- [ ] Update live command to require Supabase. Bind SIGINT/SIGTERM to stop event, install safe non-TTY logs and configurable timeout/worker CLI.
- [ ] Run new integration and existing regressions; review and commit integration unit.

## Task 4 — Final validation and performance

Files: scripts/benchmark_execution.py, tests/execution/test_equivalence.py, README.md, .github/workflows/test.yml, pyproject.toml, docs/crawler-execution-validation.md.
- [ ] Benchmark five repeated serial/six-worker deterministic simulated network executions; assert identical full normalized results and task/retry counts; record medians/speedup.
- [ ] Run full suite including real PostgreSQL. Run CLI help/status offline-error path and subprocess signal tests.
- [ ] Whole-branch review against spec/amendments; fix identified correctness issues with tests.
- [ ] Document migration SQL/security/indexes/rollback, exact validations and limits; show user migration and request separate production approval only after checks pass.
- [ ] Commit logically separated changes; leave feature branch unmerged and production untouched.

## Preflight review

Every approved requirement maps to tasks 1–4. Database RPC contract above is shared across implementers. Small checkpoints and bounded result data are separate columns; task attempts are consumed at claim. No raw documents or credentials in persistence. No speculative changes to score.py/classify.py/verify.py. Git branch in existing clean checkout is the user-requested isolation mechanism. Offline tests use an explicit fake task store; live code never falls back.
