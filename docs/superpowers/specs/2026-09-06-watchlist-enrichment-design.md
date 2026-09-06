# Watchlist enrichment and staged qualification design

## Problem and invariants

The current pipeline makes one qualification decision after initial signal
extraction. A regulatory application is credible discovery evidence, but its
frozen weight of 22 cannot qualify a singleton company/molecule pair. The
pipeline therefore loses useful candidates before it can search for
corroborating evidence.

This design adds a bounded watchlist enrichment stage. It does not change
scoring weights, the 50/65/80 thresholds, vendor/CRO/CDMO exclusions, contact
verification definitions, lead semantics, or the ₹0 operating-cost model.
WATCHLIST is investigation state, never an opportunity priority.

## Final staged flow

The logical stages are:

0. **Exclusion** — identify impurity-standard vendors and CRO/CDMO exclusions
   using the existing rules before candidate creation.
1. **Discovery / SourceRecord ingestion** — structured adapters and company
   crawling produce `SourceRecord` values with provenance.
2. **Existing initial scoring** — run the existing classifier, fingerprints,
   deduplication, and scorer.
3. **WATCHLIST candidate selection** — retain eligible sub-threshold pairs.
4. **Candidate prioritization** — order the bounded queue without changing
   scores.
5. **Bounded enrichment** — inspect free/public sources and candidate pages.
6. **Normal enrichment evidence processing** — every result goes through
   `SourceRecord`, the existing classifier, signal fingerprints, persistence,
   and the existing scorer. Enrichment never adds points directly.
7. **Second scoring pass** — aggregate initial and enrichment signals using the
   same scoring code and frozen weights.
8. **Promotion** — only pairs scoring into existing `REVIEW`, `HIGH`, or `HOT`
   become opportunities.
9. **Contact enrichment** — run only for promoted opportunities, as today.
10. **Export, metrics, and cooldown lifecycle** — persist outputs, metrics,
    candidate state, and next eligibility timestamps.

The initial run's stage barrier remains deterministic: all initial signals are
processed before candidates are selected, and all bounded enrichment tasks are
settled before the second scoring pass.

## WATCHLIST eligibility

Version 1 creates a candidate only when all conditions hold:

- valid company;
- valid molecule;
- company is not excluded as an impurity vendor, CRO, or CDMO;
- initial score is `>= 22` and `< 50`;
- at least one credible signal explicitly links the company and molecule;
- candidate cooldown has expired or is absent.

The first implementation caps newly selected candidates at **25 per run**.
Candidates already being enriched by a compatible resumed run are not counted
as new selections.

An initial regulatory singleton is therefore a watchlist candidate, not a
qualified opportunity.

## Candidate business state

Candidate lifecycle is separate from crawl task execution state.

```text
pending -> enriching -> enriched_not_promoted
                    -> promoted
                    -> exhausted
                    -> cooldown
```

Transitions:

- `pending -> enriching`: an enrichment task is claimed.
- `enriching -> enriched_not_promoted`: bounded search completed and the
  second score remains below 50.
- `enriching -> promoted`: second score reaches an existing threshold.
- `enriching -> exhausted`: bounded search completed successfully but no
  qualifying evidence was found. This is not a crawler error.
- `enriched_not_promoted -> cooldown`: policy schedules a future recheck.
- `exhausted -> cooldown`: default 30-day exhausted-candidate cooldown.
- `cooldown -> pending`: a new qualifying discovery or expired cooldown makes
  the candidate eligible again.

Task states remain unchanged: `pending`, `running`, `completed`, `skipped`,
`retryable_failed`, and `permanent_failed`. A task failure may leave the
candidate pending/cooldown for later retry; candidate `exhausted` means the
bounded search itself completed normally.

## Persistent candidate schema

The proposed additive table is `public.crawl_candidates`:

| Column | Type / rule | Purpose |
|---|---|---|
| `id` | `uuid primary key default gen_random_uuid()` | Stable candidate identity |
| `company_id` | `uuid not null references public.companies(id)` | Canonical company |
| `molecule_id` | `uuid not null references public.molecules(id)` | Canonical molecule |
| `state` | text check: `pending`, `enriching`, `enriched_not_promoted`, `promoted`, `exhausted`, `cooldown` | Business lifecycle |
| `initial_score` | integer, 0–100 | Score at selection |
| `current_score` | integer, 0–100 | Latest second-pass score |
| `source_strength` | numeric or integer, bounded | Queue ordering input |
| `credible_signal_count` | integer, >= 1 | Discovery evidence count |
| `corroborating_signal_count` | integer, >= 0 | Enrichment result count |
| `enrichment_attempt_count` | integer, 0–3 | Total execution attempts |
| `next_eligible_at` | timestamptz | Cooldown/retry scheduling |
| `last_error_code` | safe category text, nullable | Non-sensitive failure category |
| `last_enriched_at` | timestamptz, nullable | Measurement and freshness |
| `first_seen_at` | timestamptz not null | Candidate history |
| `last_seen_at` | timestamptz not null | New discovery tracking |
| `updated_at` | timestamptz not null default now() | State activity |

Constraints and indexes:

- unique `(company_id, molecule_id)`;
- foreign keys use existing lead rows and do not delete them;
- `state`, score, counts, and attempt bounds are database-checked;
- index `(state, next_eligible_at, current_score desc)` for queue selection;
- index `(company_id, molecule_id)` for deterministic lookup;
- optional index `(last_seen_at desc)` for reporting;
- RLS enabled with service-role-only mutations;
- authenticated reads, if needed, expose only safe summary columns.

No opportunity row is created for a candidate until promotion. Existing lead
tables remain unchanged apart from normal idempotent writes for promoted
signals/opportunities.

## Task graph and durable execution

The graph gains a `candidate_enrichment` barrier between initial processing and
contact enrichment:

```text
structured_sources
  -> company_crawling
  -> processing_scoring
  -> candidate_selection_and_prioritization
  -> candidate_enrichment (up to 25 new candidates)
  -> second_processing_scoring
  -> contact_enrichment
  -> supabase_persistence
  -> export
```

Candidate selection and prioritization are coordinator work. Each candidate
gets at most one durable task per compatible run, keyed as:

```text
candidate:{company_id}:{molecule_id}:{enrichment_policy_version}
```

Workers claim tasks through the existing atomic lease RPC. One request/task per
domain remains enforced by the host gate and task claim query. Shared public
source hosts have the same pacing and concurrency protection as company
domains. A stale lease cannot write evidence, candidate state, or promotion.

The candidate task checkpoint is intentionally small:

```json
{
  "policy_version": 1,
  "source_targets": ["company_site", "fda", "europe_pmc"],
  "next_target": 2,
  "url_cursor": 4,
  "completed_targets": ["company_site"],
  "observed_at": "2026-09-06T00:00:00Z"
}
```

It may contain cursors, stable source IDs, URL positions, and small counters.
It must not contain HTML, document bodies, API responses, headers, secrets, or
tokens. The existing checkpoint size guard applies.

Initial bounds per candidate:

- 8–12 source targets;
- at most 10–15 fetched pages;
- at most 3 task execution attempts total across restarts;
- existing request timeouts, robots policy, retry classification, and domain
  cooldowns;
- no paid API, LLM API, or paid enrichment service.

## Source adapter strategy

Enrichment uses free/public sources and existing adapters first:

1. company sitemaps, Common Crawl URLs, and same-domain technical pages;
2. FDA/public regulatory records already supported by the repository;
3. ClinicalTrials.gov when transport permits, with its known 403 isolated and
   not repeatedly retried;
4. Europe PMC/PubMed or Crossref publication metadata/full text where publicly
   available;
5. public patent publication pages and assignee information;
6. public regulatory notices, filings, product/manufacturing announcements,
   tenders, RFQs, and deficiency/response activity;
7. molecule-specific analytical, quality, CMC, or process-development hiring.

Search terms include impurity, degradation, nitrosamine, NDSRI, genotoxic
impurity, stability, analytical method, validation, process development, route
synthesis, formulation, manufacturing, regulatory response, tender, and RFQ.

Generic company news, generic hiring, molecule-only mentions, and content from
known vendors/CROs/CDMOs are weak or excluded. A result must link the company
and molecule in relevant context to be credible corroboration.

## Signal mapping and frozen scoring

Every enrichment result follows:

```text
SourceRecord
  -> existing classifier
  -> existing fingerprint
  -> signal persistence
  -> existing scorer
```

The current inventory is:

| `signal_type` | Existing weight with molecule | Existing weight without molecule | Contributes to score? |
|---|---:|---:|---|
| `direct_impurity_rfq` | 70 | 45 | Yes |
| `reference_standard` | 60 | 25 | Yes |
| `nitrosamine_ndsri` | 45 | 20 | Yes |
| `genotoxic_impurity` | 40 | 18 | Yes |
| `impurity_characterization` | 38 | 15 | Yes |
| `degradation_product` | 35 | 15 | Yes |
| `stability` | 18 | 8 | Yes |
| `method_validation` | 12 | 5 | Yes |
| `phase_iii` | 18 | n/a | Yes |
| `phase_ii` | 12 | n/a | Yes |
| `regulatory_application` | 22 | n/a | Yes |
| `impurity_vendor_exclusion` | -100 | n/a | Used for exclusion; never qualifies |

Mapping for proposed enrichment categories:

| Enrichment category | Existing signal type(s) | Weight | Score contribution |
|---|---|---:|---|
| impurity / degradation study | `impurity_characterization`, `degradation_product` | 38 / 35 | Yes |
| analytical method development / validation | `method_validation`, `impurity_characterization` | 12 / 38 | Yes |
| nitrosamine / NDSRI | `nitrosamine_ndsri` | 45 | Yes |
| genotoxic impurities | `genotoxic_impurity` | 40 | Yes |
| stability study | `stability` | 18 | Yes |
| process-development / route synthesis | no dedicated scored type | n/a | Provenance/discovery only unless existing classifier matches |
| relevant patents | no dedicated scored type | n/a | Provenance/discovery only unless existing classifier matches |
| formulation/manufacturing milestone | `phase_ii`, `phase_iii` only when existing metadata qualifies | 12 / 18 | Yes only through existing classifier/metadata |
| regulatory deficiency / response | `regulatory_application` where existing metadata qualifies | 22 | Yes |
| tenders / RFQs | `direct_impurity_rfq` when existing phrases match | 70 | Yes |
| molecule-specific analytical hiring | existing matching classifier type, usually `impurity_characterization` or `method_validation` | 38 / 12 | Yes only through existing classifier |
| company+molecule publication | whichever existing classifier type matches | existing weight | Yes only through existing classifier |

If a category does not match an existing scored type, it is stored as
provenance/discovery evidence and contributes zero points. No new signal type,
weight, or threshold is invented in v1.

## Underlying-event deduplication

URL-level fingerprints are insufficient: an FDA record, company release, and
publication may describe the same regulatory event. Enrichment must preserve
all provenance while counting one underlying event once.

Each emitted signal receives a deterministic `metadata_json.event_key` built
from normalized values in this precedence order:

1. stable external event ID (FDA application/record ID, trial ID, patent
   publication number, publication DOI/PMID, tender ID);
2. normalized company ID, molecule ID, signal type, event date, and normalized
   event anchor (application number, phase, product/route anchor);
3. if no date exists, normalized company ID, molecule ID, signal type, and a
   normalized evidence anchor explicitly extracted by the adapter.

The key excludes URL, fetch time, and surrounding prose. Every provenance URL
still produces a fingerprinted stored signal/evidence record, but the second
scoring pass selects one deterministic representative per
`(company_id, molecule_id, signal_type, event_key)`:

1. prefer the strongest source class;
2. prefer a stable external ID over a fallback key;
3. prefer the earliest canonical discovery timestamp;
4. tie-break by canonical URL and fingerprint.

The representative supplies the score; other records remain available for
audit and provenance. If event identity is ambiguous, the system must keep the
records separate and mark the event key as fallback rather than guessing that
two events are identical.

## Second scoring and promotion

The second pass loads all initial and enrichment signals for each candidate,
deduplicates by the event key above, and calls the unchanged scorer. The
resulting score and priority use the existing rules:

- `HOT`: score >= 80 or direct RFQ;
- `HIGH`: score >= 65;
- `REVIEW`: score >= 50;
- below 50: not qualified.

Promotion updates candidate state and creates/updates the normal opportunity
through existing idempotent fingerprints and conflict keys. Contact enrichment
is gated on promoted `REVIEW`, `HIGH`, or `HOT` opportunities only. Watchlist
candidates never receive contacts or appear as qualified exports.

## Re-enrichment and cooldown policy

The initial policy is configurable but defaults to:

- new candidate cap: 25 per run;
- maximum execution attempts: 3;
- exhausted cooldown: 30 days;
- enriched-but-not-promoted cooldown: 30 days;
- new qualifying evidence, or a materially newer high-strength source, can
  reset cooldown early;
- a compatible resumed run continues its existing task/checkpoint;
- a fresh run may re-evaluate candidates only when cooldown or new-evidence
  rules make them eligible.

Cooldown updates are durable and use database time. Widespread network failure
pauses new claims rather than exhausting candidates.

## Metrics

Persist candidate and run metrics separately:

- candidates selected and examined;
- candidates skipped, exhausted, in cooldown, and promoted;
- corroborating signals found and unique underlying events found;
- promotion percentage to `REVIEW`, `HIGH`, and `HOT`;
- promotion rate by initial signal type and source class;
- precision of promoted opportunities from review labels;
- pages/requests per candidate;
- retries, task duration, and average enrichment time;
- cooldown rechecks and early reactivations.

No metric should call a watchlist candidate a qualified opportunity.

## Deterministic testing and backtesting

Fixtures must include:

- a regulatory singleton that enters WATCHLIST but not `opportunities`;
- a candidate promoted by one valid corroborating signal;
- a candidate remaining below 50 after bounded enrichment;
- vendor/CRO/CDMO content that never enters WATCHLIST;
- FDA, company release, and publication records for one underlying event;
- distinct events with similar prose that remain separate;
- source/page caps and retry/cooldown behavior;
- small checkpoints that resume at a source/page cursor.

Integration tests must verify atomic candidate/task claims, lease expiry and
fencing, candidate state transitions, idempotent reruns, and interruption
resume with the same run ID. Run the identical deterministic fixture at one
worker and six workers and require identical signals, event representatives,
opportunities, scores, priorities, contact statuses, rankings, and candidate
states (ordering may differ).

Backtesting acceptance criteria before any scoring recalibration:

- no false promotion caused solely by duplicate URLs for one event;
- promoted opportunities meet the frozen thresholds exactly;
- candidate enrichment is bounded by configured pages, sources, attempts, and
  requests;
- resume and rerun outputs are idempotent;
- promotion precision is measured on a held-out, time-separated labeled set;
- enrichment reports its median runtime and request cost;
- serial/parallel semantic equality passes on the deterministic workload.

Scoring calibration comes later. Freeze current weights, assemble labeled
positive and negative company/molecule examples, replay initial-only and
enriched pipelines with a time-based holdout, and measure precision, recall,
promotion precision, false-positive rate, and enrichment cost. No weight or
threshold changes are permitted until that evidence is reviewed and approved.

## Risks and mitigations

- Generic pages can create false corroboration: require explicit company and
  molecule linkage and relevant technical context.
- Vendor/CRO/CDMO content can dominate search: apply exclusions before queueing
  and during enrichment.
- Twenty-five candidates can still create excess requests: enforce per-source,
  per-page, per-attempt, and per-run caps.
- Public sources can rate-limit or fail: use existing pacing, robots, bounded
  retries, cooldowns, and source isolation.
- Event identity can be uncertain: preserve provenance and use conservative
  fallback keys rather than merging ambiguous events.
- Candidate and task state can diverge after a crash: update under lease
  fencing, make writes idempotent, and allow lease recovery.
- Enrichment may bias toward well-indexed companies: report outcomes by source
  class and company segment.

No implementation code, migration, production schema change, scoring change,
or production crawl is part of this design approval.

## Self-review

The design includes all ten required stages, separates candidate lifecycle from
task lifecycle, inventories every current scored signal type and weight, maps
each enrichment category without inventing weights, defines an event-level
deduplication key and deterministic representative selection, and preserves
all provenance URLs. Bounds, cooldowns, lease fencing, resume behavior,
contact gating, metrics, deterministic fixtures, serial/parallel equality, and
backtesting acceptance criteria are explicit. WATCHLIST is never represented
as an opportunity priority. No implementation or migration instructions are
presented as completed work.
