# Resumable parallel crawler — approved design

## Scope and invariants

Implement the approved architectural proposal and all 17 amendments. Production migration application requires a separate explicit approval after migration and full-suite tests and presentation of the migration. Work on feature/resumable-parallel-crawler. No secret contents, raw exceptions, HTTP headers or credentials in logs/checkpoints. Protect .env files. Preserve scoring, qualification, vendor exclusion, verification definitions and rankings. ClinicalTrials 403 remains a visible, terminal skip per run.

## Execution graph

A single coordinator executes stages: structured sources; company crawling; processing/scoring; contact enrichment; Supabase persistence; export. Network stages use six synchronous workers by default. Each domain's requests are sequential; a global host gate also covers redirects and shared Common Crawl endpoints. Requests preserve TLS verification, trust_env=False, robots 404 allow and 401/403 deny, and reject HTTPS downgrade. No nested automatic retries in durable execution.

Durable tasks: one per source, one per canonical domain (associated seed entries preserved), one scoring task, one contact-domain task (top 30 HOT/HIGH opportunities selected in existing order), one persistence task with bounded batches/cursors, one export task. Stage barriers preserve aggregation over the entire current run. Deterministic seed/task/page order preserves tie handling independently of thread completion order.

## Task state and atomicity

pending -> running -> completed | skipped | retryable_failed | permanent_failed.
retryable_failed -> running only when due and below three attempts. A claim increments attempt_count, including a recovered expired execution. Three total task execution attempts across all invocations; no multiplication by adapters. Graceful release retains consumed execution attempts. Exhausted expired/released tasks become permanent_failed rather than hanging pending forever. Completion/checkpoint/renew/release require owner token and a currently valid lease, plus valid coordinator ownership. Database server time controls leases and eligibility.

Claim uses a Postgres transaction with FOR UPDATE SKIP LOCKED, updates status, generates an unpredictable token, assigns expiry, and returns the claimed row. Coordinator acquisition also uses database locking, preventing concurrent coordinators. A live coordinator blocks another fresh/resume invocation; global singleton coordination avoids overlapping different runs as well. Coordinator and task leases default 120 seconds, heartbeat 20 seconds. RPCs are SECURITY INVOKER with EXECUTE revoked from PUBLIC, anon and authenticated and granted to service_role.

## Resume compatibility and age

Automatically resume only compatible unfinished runs aged <=48 hours. Hash canonical seed contents, enabled sources, safe material execution settings, checkpoint/schema version and relevant crawler/scoring/contact code versions. Exclude worker count, UI mode and credentials. Older unfinished runs become abandoned, retaining all history. Incompatible runs are not resumed. --fresh starts a new run while retaining history and respecting live coordinator ownership. No old-run override in v1. Database unavailable means no live crawl starts; during execution stop new claims and preserve last acknowledged durable state. Fixture commands remain offline.

## Durable data, not just statuses

crawl_tasks.checkpoint_json is a JSON object limited to 16 KiB (UTF-8 encoded JSON in Python; jsonb text bytes in PostgreSQL). It contains page/cursor positions, remaining URL references, attempt progress and small timing counters. Forbidden: raw HTML, API responses, large document bodies, secrets or headers.

A separate crawl_tasks.result_json column stores only bounded, versioned, parsed domain models: SourceRecord, extracted ContactCandidate, Signal, Opportunity and RankedContact. This is durable task output, not an API/document cache. Maximum 4 MiB per task; overflow is an explicit task failure, never silent truncation. Source adapters retain their existing extraction semantics. HTML is discarded after extraction; contact pipeline accepts extracted candidates through a small shared helper without changing verification/ranking. Page outputs and cursor commit together under fencing. Completed task outputs are immutable except deliberate export regeneration. Output counts derive from stored records, not event replay.

## Schema and security

One new table crawl_tasks: UUID id, run FK, unique(run_id,task_key), task_type, stage, identifier, domain, status, attempt_count, next_eligible_at, checkpoint_json, result_json, lease_token, lease_owner, lease_expires_at, safe last_error_code, lifecycle times and accumulated duration. Task constraints enforce state, attempts and payload sizes. Partial indexes support due claims and lease recovery; run/stage/task ordering supports deterministic reconstruction.

crawl_runs adds fingerprint/version, current_stage, coordinator token/owner/expiry, heartbeat/updated timestamps, safe config summary and metrics. Reuse started_at/completed_at/status/counters/duration. crawl_domains reuses error_count/next_crawl_at/robots_status/average_response_ms and adds last_request_at only if needed. New execution table RLS enabled, service-role-only. Existing lead RLS/security unchanged. New RPCs coordinate begin/resume, plan, claim, heartbeat, fenced checkpoint/completion, safe release, run pause/finalize and idempotent lead publication.

Persistence reuses existing SupabaseLeadStore row mappings and stable UUID/fingerprint/conflict rules. A bounded publication RPC performs lead upserts and checkpoint advancement in one transaction under task/coordinator fencing. Partial crash replay is safe. Preserve review status/dismissal fields, first-seen semantics and original observation timestamps. No old lead deletion/rewrite. Additive rollback: revert application, keep execution columns/tables until history is intentionally retired.

## Scheduling, retries and circuit breaker

Configurable connect/pool=5s; read/write=20s; task slice=300s; invocation=42min; shutdown reserve/drain=30s. Task scheduler owns retry policy (three attempts total), exponential backoff with jitter and capped normal delay, Retry-After persisted as next_eligible_at rather than worker sleep. 401/403 skip, missing pages skip, TLS failures permanent, temporary DNS/connect/read/5xx/429 retry, malformed output permanent. Persist successful page progress before proceeding; retry only unfinished pages. Repeated transient failures update domain cooldown; success reduces/reset domain failure state. Multiple distinct-domain connectivity failures within a rolling window stop new claims and pause the run instead of exhausting queue retries. Database outages pause immediately. Recovery resumes when a later invocation has working database/network; no aggressive probing loop.

## Shutdown and lease limits

Signal handlers only set a stop event. Stop claiming immediately, signal workers, drain for bounded time, commit safe outputs and release only workers confirmed stopped. Running native operations retain leases to expire. Use daemon worker threads and bounded joins, not an unbounded ThreadPoolExecutor context exit. A stale worker may not persist output or schedule another request. Threads cannot hard-kill DNS/native calls; leases fence state, and already-sent HTTP requests cannot be recalled. No exactly-once network claim.

## Progress, status and metrics

Business code emits safe structured events; Rich is an optional renderer chosen only for interactive non-CI TTY. Non-TTY outputs JSON lines. Stage, workers, successful/skipped/retryable/permanent counts, settled/planned progress (provisional until planning closes), elapsed and sufficiently sampled ETA. Signals/opportunities reflect scored outputs; raw collection is labelled records. Count contacts without double-counting evidence/links. Status is read-only: ID/status/age/stage/progress/all task-state counts/active leases/last activity/elapsed. Persist stage duration, task/attempt counts and durations, wall/active elapsed and safe result metrics. Missing exports regenerate from durable results without recrawling.

## Validation

TDD for each component. Actual disposable PostgreSQL tests cover transaction claims, coordinator exclusion, fencing, expiry, attempts, RLS/grants, atomic publication and migration preservation. Tests must not touch production. Unit/integration fixture executions at one/six workers and interrupted/resumed must match signals, opportunities/scores/priorities and contact statuses/rankings. Preserve existing 117 regressions. Subprocess SIGINT/SIGTERM checks and deterministic fake clocks/randomness where useful. Benchmark same deterministic simulated network workload at one/six workers, at least five repetitions, median times, task/retry counts and semantic output equality. No production migration until user reviews final SQL and approves.

## Self-review

Checked amendments 1–17 against sections above. Small checkpoints coexist with durable parsed results through a separate size-limited result column; no raw documents are retained. Retry count is task executions, not retries per request/process. Lease expiry consumes recovery attempts. No task is marked completed before output durability. Cross-source scoring remains a barrier. Local export is reproducible. Runtime permissions do not expand authenticated/anon access. No unresolved design placeholders; external schema drift will be checked before deployment approval.
