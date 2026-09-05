# Verified Contact Intelligence Subsystem — Design

**Date:** 2026-09-04  
**Parent spec:** `docs/superpowers/specs/2026-09-04-impurity-lead-engine-design.md`  
**Branch:** `feature/backend-engine`

## 1. Objective

Add a zero-cost contact-intelligence subsystem to the impurity lead engine that resolves the most relevant real person for a qualified company+molecule opportunity, captures publicly available business contact details, and labels every contact detail with an evidence-backed verification status.

The subsystem must optimize for precision over coverage. It must never present an inferred mailbox as if the mailbox itself were verified.

## 2. Scope

### Included

- Enrich `HOT` and `HIGH` molecule-level opportunities with likely decision-makers.
- Resolve real people from public professional/business sources.
- Capture public business email addresses and public business phone numbers when present.
- Infer a probable corporate email only when a stable company email pattern is supported by multiple public named-company mailboxes.
- Rank contacts by fit to the opportunity's likely impurity need.
- Store compact evidence snippets and source URLs, never full HTML.
- Preserve last-observed/last-verified timestamps.
- Export contact name, title, department, contact status, email/phone, confidence, and evidence URLs.
- Keep recurring infrastructure cost at ₹0 using the existing GitHub Actions + public web/API + Supabase Free architecture.

### Excluded

- Paid enrichment APIs such as Apollo, Hunter, RocketReach, ZoomInfo, Lusha, Clearbit, or similar services.
- LinkedIn authenticated scraping or bypassing anti-bot controls.
- CAPTCHA solving, login bypasses, paywall bypasses, or robots.txt circumvention.
- SMTP mailbox probing, catch-all probing, password-reset probing, or any technique that sends traffic intended to determine whether a specific private mailbox exists.
- Personal/home addresses, private mobile numbers, or non-business personal data.
- Personal email addresses on consumer domains unless the authoritative business source itself explicitly publishes the address as the professional contact channel; such addresses remain lower confidence and are not used for pattern inference.
- Automatically sending outreach.

## 3. Verification semantics

The system uses exact, non-overlapping statuses.

### `VERIFIED_PUBLIC`

Use only when the exact contact value is publicly published and the evidence resolves the value to the person/company context.

Examples:

- Company leadership/contact page contains the person's name, title, and `mailto:` address.
- ClinicalTrials.gov public contact data exposes the person's name/official title and email/office phone for a sponsor-linked study.
- A company press release, conference page, tender document, or scholarly source publishes the exact professional email and the person's company affiliation is independently consistent.

Requirements:

- Exact value observed in source.
- Source URL retained.
- Person/company relationship supported by the same source or a second compatible public source.
- For email, domain must match the company domain unless the source is an authoritative public professional record explicitly publishing a different business contact address.

### `PATTERN_CONFIRMED`

Use only for a generated company-domain email candidate where:

1. The person's name and current company/title are verified from public professional evidence.
2. At least two distinct named employee email addresses have been publicly observed on the same company domain.
3. Those two or more addresses produce the same deterministic name-to-email pattern.
4. Generic mailboxes such as `info@`, `sales@`, `careers@`, `support@`, `contact@`, and `procurement@` are excluded from pattern learning.
5. The generated address matches the established pattern exactly.

`PATTERN_CONFIRMED` explicitly means **pattern-derived, not mailbox-verified**. UI and exports must display that distinction.

### `ROLE_ONLY`

Use when a relevant person and/or role is identified but no sufficiently reliable email or phone can be produced.

### `STALE`

Use when a previously verified contact is older than the configured freshness window and current evidence cannot confirm the same company/title relationship. Stale details remain in evidence history but are not shown as primary contact details.

## 4. Source hierarchy

Sources are ranked by authority and by whether they directly resolve identity and contact details.

### Tier 1 — company-controlled public sources

Highest priority:

- leadership/team pages
- scientific/R&D leadership pages
- management biographies
- press releases
- investor-relations biographies
- contact pages
- procurement/tender/RFQ pages
- PDF documents publicly linked by the company
- `mailto:` and structured JSON-LD `Person`/`Organization` records

### Tier 2 — authoritative public registries and study records

- ClinicalTrials.gov public study contacts and results points of contact
- other regulator/trial records only where the contact information is explicitly public

Trial contacts are useful evidence but are not automatically treated as impurity-buying decision-makers. The role-fit scorer determines whether a trial contact should surface for the opportunity.

### Tier 3 — public scientific/professional evidence

- Europe PMC / PubMed Central metadata and openly accessible full-text contact/affiliation details
- Crossref metadata for author names, affiliations, ORCID, ROR, and publication discovery
- company-hosted conference presentations and scientific posters
- public conference speaker/author pages

Publication authors can establish identity, affiliation, and technical function, but a scientific author is not automatically a commercial decision-maker.

### Tier 4 — Common Crawl discovery

Use the existing Common Crawl adapter only to discover candidate public pages on the known company domain. Direct contact extraction occurs from the original public page when robots/access rules permit. Archived text is not treated as current verification by itself.

## 5. Opportunity-to-role mapping

The contact ranker uses the opportunity's `likely_need_type`, signal taxonomy, and source context.

Priority role families:

| Opportunity context | Primary role families | Secondary role families |
| --- | --- | --- |
| degradation/process impurity | Analytical R&D, Analytical Development, API/Process Development | CMC, Quality Control |
| nitrosamine/NDSRI/genotoxic | Analytical R&D, CMC, Quality/Compliance | Regulatory Affairs, Toxicology |
| stability/forced degradation | Analytical Development, Stability, Quality Control | CMC |
| ANDA/NDA/regulatory milestone | CMC, Analytical Development | Regulatory Affairs, API Development |
| direct RFQ/tender | Procurement/Sourcing plus named technical owner | Analytical R&D, CMC |
| Phase II/III small molecule | CMC, Analytical Development, API Development | Program/Technical Operations |

Default ordering within a relevant family:

1. Head / VP / SVP / Executive Director
2. Director / Associate Director
3. Senior Manager / Group Leader
4. Manager / Principal Scientist
5. Senior Scientist / Scientist

The ranker avoids over-prioritizing corporate executives with no technical or sourcing relevance.

## 6. Contact entity model

### `contacts`

One current normalized row per person+company relationship.

Fields:

- `id uuid`
- `company_id uuid`
- `normalized_name text`
- `display_name text`
- `title text`
- `department text`
- `profile_url text`
- `primary_email text`
- `email_status text` — `VERIFIED_PUBLIC`, `PATTERN_CONFIRMED`, `ROLE_ONLY`, `STALE`
- `primary_phone text`
- `phone_status text` — `VERIFIED_PUBLIC`, `ROLE_ONLY`, `STALE`
- `role_fit_score integer` — 0–100
- `contact_confidence numeric` — 0.0–1.0
- `first_seen_at timestamptz`
- `last_seen_at timestamptz`
- `last_verified_at timestamptz`
- unique constraint on `(company_id, normalized_name)`

### `contact_evidence`

Append-only evidence rows.

Fields:

- `id uuid`
- `contact_id uuid`
- `evidence_type text` — `identity`, `title`, `email`, `phone`, `affiliation`, `email_pattern`
- `observed_value text`
- `source_type text`
- `source_url text`
- `evidence_text text` — capped snippet, maximum 800 characters
- `observed_at timestamptz`
- `fingerprint text unique`
- `metadata_json jsonb`

### `opportunity_contacts`

Many-to-many ranking between molecule opportunities and contacts.

Fields:

- `opportunity_id uuid`
- `contact_id uuid`
- `role_fit_score integer`
- `rank integer`
- `rationale text`
- primary key `(opportunity_id, contact_id)`

## 7. Contact discovery pipeline

Contact enrichment is a second-stage pipeline after opportunity qualification.

```text
qualified HOT/HIGH opportunity
        ↓
known company domain + opportunity roles
        ↓
collect candidate contact pages
        ↓
extract structured people/contact blocks
        ↓
normalize person + company affiliation
        ↓
rank role relevance
        ↓
extract exact public email/phone evidence
        ↓
learn company email pattern if evidence allows
        ↓
assign verification status
        ↓
store contacts + evidence + opportunity ranking
```

Only the top opportunities are contact-enriched during a daily run. Initial cap: 30 opportunities/day, matching the approved high-precision lead-volume target.

## 8. Page discovery

For a known company domain, contact discovery reuses the existing sitemap and Common Crawl components but adds contact-oriented URL heuristics.

High-value path tokens:

- `leadership`
- `management`
- `team`
- `people`
- `about`
- `research`
- `science`
- `rd`
- `r-and-d`
- `analytical`
- `development`
- `quality`
- `regulatory`
- `procurement`
- `sourcing`
- `contact`
- `press`
- `news`
- `investor`

The crawler remains same-domain only unless a page explicitly links to a supported authoritative source. Every direct fetch remains subject to the existing robots policy, timeout, retry, and same-domain rules.

## 9. Deterministic contact extraction

The subsystem does not require an LLM.

Extract in this order:

1. JSON-LD `Person` records: `name`, `jobTitle`, `email`, `telephone`, `url`, affiliation.
2. HTML `mailto:` links and nearby DOM block.
3. `tel:` links and nearby DOM block.
4. Contact cards containing a role keyword and a plausible person name.
5. Table/list rows containing person + title + email/phone.
6. Structured public API fields such as ClinicalTrials contacts.

Name extraction rules avoid generic labels and organization names. A candidate person must have either:

- a structured `Person` record,
- an exact contact detail within the same DOM block,
- or a plausible two-or-more-token human name adjacent to a relevant job title.

## 10. Identity normalization and deduplication

Normalize names by:

- Unicode normalization
- case folding
- stripping honorifics (`Dr`, `Prof`, `Mr`, `Ms`, etc.)
- retaining initials but comparing them cautiously
- normalizing whitespace and punctuation

Strong identity match requires company match plus one of:

- exact normalized full name,
- same surname + compatible given name/initial + same title family,
- ORCID or other exact public identifier when available.

Do not merge two people solely because they share surname and company.

## 11. Email extraction and pattern inference

### Exact public email

- Parse `mailto:` and visible email text.
- Normalize case and surrounding punctuation.
- Reject obvious malformed values.
- Determine whether email domain matches the normalized company domain.
- Preserve exact source evidence.

### Pattern learning

Supported deterministic patterns in V1:

- `first.last`
- `firstlast`
- `f.last`
- `flast`
- `firstl`
- `last.first`
- `lastf`

Pattern evidence must come from at least two distinct named people at the same company domain. If multiple patterns conflict, do not infer an address.

Generic aliases never participate in pattern learning.

No SMTP verification is performed. No generated address receives `VERIFIED_PUBLIC` status.

## 12. Phone handling

Only capture phone numbers explicitly published as professional/business contact channels.

- Normalize display format while retaining the raw observed value in evidence metadata.
- Prefer office/company numbers.
- Do not infer personal mobile numbers.
- No reverse lookup or enrichment from personal-data brokers.

## 13. Role-fit scoring

Contact fit score: 0–100.

Suggested deterministic components:

- exact target department family: +35
- exact target function keyword: +25
- seniority Head/VP/Director: +20 / +15 / +12
- company-controlled source: +10
- molecule/therapy/program context on same page: +10
- procurement role on direct RFQ/tender: +25
- generic executive role with no functional relevance: -30
- clinical site investigator only: -25 unless the opportunity itself is site-specific
- stale affiliation: -40

Scores are capped at 100. Primary dashboard contacts require role-fit score >= 55.

## 14. Contact confidence

Contact confidence is separate from role fit.

Suggested evidence confidence:

- exact person+title+email on company-controlled source: 1.00
- exact person+title+email on authoritative public registry: 0.95
- exact professional email on scientific/conference source + independently matching current company/title: 0.90
- verified current person/title + confirmed email pattern: 0.70
- verified current person/title only: 0.55

Dashboard can sort by a composite such as:

`contact_priority = opportunity_score × role_fit_score × contact_confidence`

The database stores the inputs rather than only the composite.

## 15. Freshness policy

- Company leadership/current-role evidence: fresh for 180 days.
- Public exact business email observed on current company page: fresh for 180 days.
- Trial/public registry contact tied to an active or recently active record: fresh for 180 days unless the underlying record is updated sooner.
- Scientific publication affiliation older than 365 days is supporting evidence only, not current-role verification.

Re-observing the same current evidence refreshes `last_verified_at` without duplicating evidence fingerprints.

## 16. Export and dashboard contract

For each opportunity, expose up to three ranked contacts.

Columns/fields:

- `contact_name`
- `contact_title`
- `contact_department`
- `role_fit_score`
- `business_email`
- `email_status`
- `business_phone`
- `phone_status`
- `contact_confidence`
- `profile_url`
- `last_verified_at`
- `contact_evidence_urls`

Default dashboard behavior:

- show `VERIFIED_PUBLIC` first
- show `PATTERN_CONFIRMED` with an explicit "pattern-derived" badge
- show `ROLE_ONLY` only when no stronger relevant contact exists
- hide `STALE` by default

## 17. Storage and security

The new tables follow the existing Supabase security model:

- RLS enabled on all exposed tables.
- `anon` receives no access.
- authenticated internal user receives read-only access to contact/evidence tables.
- service-side crawler secret performs inserts/updates.
- no service secret is exposed to the browser.
- raw HTML is never stored.

Contact evidence contains public professional information only and is retained solely to support sourcing/verification of B2B lead intelligence.

## 18. Error handling

- Failed page fetch: skip and record adapter error; never downgrade an existing verified contact solely because a page is temporarily unavailable.
- Ambiguous person identity: keep candidates separate and do not assign a primary email.
- Conflicting titles: prefer fresher higher-authority evidence; preserve history.
- Conflicting email patterns: disable pattern inference for that domain until sufficient consistent evidence exists.
- Domain mismatch: do not mark company-domain verification unless independently justified by authoritative evidence.

## 19. Testing strategy

### Unit tests

- JSON-LD Person extraction
- `mailto:`/`tel:` extraction
- contact-card extraction
- name normalization
- role-family classification
- role-fit scoring
- email pattern detection
- conflicting pattern rejection
- generic mailbox exclusion
- verification status assignment
- stale evidence behavior

### Fixture tests

Fixtures for:

- company leadership page with exact email
- company R&D page with no email
- public trial contact JSON
- scientific page with author affiliation/email
- two employee pages establishing one corporate email pattern
- conflicting email-pattern company
- generic contact page that must not generate a named-person pattern

### Integration test

A fixture opportunity with `nitrosamine/NDSRI` need must resolve:

1. the relevant Analytical/CMC contact above a generic CEO,
2. an exact public email as `VERIFIED_PUBLIC` when directly observed,
3. a generated email only as `PATTERN_CONFIRMED`,
4. evidence URLs and timestamps,
5. no raw page HTML in storage.

## 20. Daily compute budget

Contact enrichment runs after lead scoring and only for the top 30 `HOT`/`HIGH` opportunities.

Per company/day default limits:

- sitemap candidate scan: existing limits
- contact-oriented direct page fetches: maximum 12
- Common Crawl candidate discovery: existing throttled adapter
- scientific/API lookups: maximum 5 relevant queries

The enrichment stage must obey the parent daily deadline. If remaining time is insufficient, opportunities without contact enrichment remain valid leads and are retried on a later run.

## 21. Implementation boundaries

Recommended files/components:

- `src/impurity_leads/contacts/models.py` — contact/evidence contracts
- `src/impurity_leads/contacts/extract.py` — structured HTML/API extraction
- `src/impurity_leads/contacts/normalize.py` — person/title/email normalization
- `src/impurity_leads/contacts/patterns.py` — deterministic corporate email-pattern logic
- `src/impurity_leads/contacts/rank.py` — opportunity-to-contact role fit
- `src/impurity_leads/contacts/verify.py` — status/confidence assignment
- `src/impurity_leads/contacts/pipeline.py` — second-stage enrichment orchestration
- `src/impurity_leads/adapters/europe_pmc.py` — optional public scientific discovery adapter
- update `supabase/schema.sql` with contact tables, indexes, grants, and RLS
- update storage adapters and exporters
- update CLI daily run to call contact enrichment after opportunity scoring

The existing opportunity extraction/scoring modules remain unchanged except for the explicit handoff into contact enrichment.

## 22. Success criteria

The subsystem is accepted when:

1. Every surfaced email is labeled either exact-public or pattern-derived; no inferred mailbox is presented as verified.
2. At least one evidence URL supports every surfaced person identity.
3. `VERIFIED_PUBLIC` contact values are exact values observed in public professional evidence.
4. Pattern inference requires at least two distinct named employee mailboxes with one consistent company-domain pattern.
5. Generic aliases never establish a person-email pattern.
6. The role ranker prioritizes relevant Analytical R&D/CMC/API/Quality/Procurement decision-makers over generic executives.
7. Contact enrichment can fail without blocking the underlying molecule-level lead.
8. Raw HTML is not persisted.
9. Full tests are green before schema/deployment changes.
10. Recurring infrastructure cost remains ₹0 within the approved free-tier limits.

## 23. Final design decision

Implement contact intelligence as an independent second-stage enrichment subsystem. Enrich only qualified high-priority opportunities, use public professional sources, rank contacts deterministically by opportunity relevance, and maintain strict verification labels so users can distinguish directly published contact details from pattern-derived candidates.
