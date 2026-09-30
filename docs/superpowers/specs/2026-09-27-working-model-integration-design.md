# Working Model Integration Design

## Goal

Connect the existing crawl, scoring, contact research, opportunity research,
Supabase persistence, frontend read model, and scheduled workflow into one
observable, idempotent working loop that can be verified locally and, when
credentials are available, against production.

## Scope

The integration covers the backend execution path and its frontend-visible
status:

`seeded crawl -> normalized signals -> scored opportunities -> queued contact
and opportunity research -> bounded public providers -> source-backed
Contact 360 records -> opportunity/contact links -> dashboard/export status`.

Paid search, authenticated-site scraping, email guessing, SMTP probing, and
unbounded crawling remain out of scope.

## Design

### Provider boundary

Research providers expose a common deterministic interface that accepts a
contact or opportunity context plus a bounded budget and returns normalized
source candidates, evidence metadata, and provider metrics. Providers do not
write directly to the UI. The worker owns persistence and applies one source
identity/idempotency rule for all providers.

The first integrated providers are:

- official company pages, restricted to the canonical company domain and a
  small allowlist of public page paths;
- Europe PMC publications, using the existing identity-resolution rules;
- existing patent/regulatory providers where their current contracts already
  exist;
- targeted opportunity research, using the existing durable job queue.

Provider failures are recorded per provider/run and do not erase successful
evidence from earlier providers.

### Official-company research

The worker resolves a contact's company domain from the canonical company
record, then fetches only bounded company URLs using the existing crawler
HTTP/robots policy. The official-company parser accepts pages only when the
host equals the canonical domain or a subdomain, rejects vendor content and
irrelevant pages, and emits source-backed technical/contact evidence.

No contact email is inferred from an official page unless the existing
verified-public/pattern rules independently permit it.

### Persistence and linkage

Accepted sources are upserted by `(contact_id, url)` with terminal status and
provider metadata. Claims, works, themes, and JTBD rows retain source IDs and
use observed versus inferred provenance correctly. Re-running a completed
research run must not duplicate source-backed facts.

Opportunity links are created or updated only when the accepted evidence has a
validated contact identity and a supported company/opportunity relationship.
Ambiguous or historical candidates remain evidence/review records and are not
promoted to canonical contacts or primary opportunity contacts.

### Orchestration and observability

The daily post-crawl stage runs contact research, targeted opportunity
research, molecule intelligence, opportunity evidence enrichment, and agent
work export through one explicit stage-result contract. Each stage reports
status, processed jobs, source/claim/link counts, provider usage, and bounded
errors. Core crawl failure remains fatal; research-stage failures are visible
and retryable without invalidating a successful crawl.

The frontend continues to use the existing Supabase read model, but receives
stage-level diagnostics from durable run/job records rather than relying on
console-only failures.

## Data safety and constraints

- Existing RLS and service-role boundaries remain unchanged.
- All public HTTP access obeys robots.txt, descriptive User-Agent, timeout,
  retry, response-size, and domain restrictions.
- `ZERO_COST_MODE=true` must prevent paid providers before network access.
- Raw HTML/WARC bodies are not persisted; only compact source metadata and
  evidence snippets are stored.
- Existing manual intelligence is never silently overwritten; conflicts remain
  explicit.

## Verification gates

The implementation is complete only when:

1. provider and parser unit tests pass;
2. fake-Supabase worker tests prove queue-to-persistence behavior, rerun
   idempotency, provider failure isolation, and opportunity linking;
3. the full local backend suite excluding only environment-blocked tests
   passes, and the PostgreSQL integration suite passes when a local database is
   available;
4. frontend tests and production build pass;
5. fixture smoke/export and `git diff --check` pass;
6. if production credentials are present, one real queued run is inspected for
   stage metrics, source rows, and lead/contact counts. If they are absent, the
   exact external verification gap is reported.

## Non-goals

This change does not redesign the frontend, replace Supabase, enable AI search
by default, or claim live production success without observing persisted
production results.
