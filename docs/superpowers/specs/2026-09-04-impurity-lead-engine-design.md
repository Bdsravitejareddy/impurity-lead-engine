# Impurity Synthesis Lead Intelligence Engine — Design

Date: 2026-09-04
Status: Proposed design for implementation
Operating-cost constraint: ₹0/month
Primary user: single internal SVAK user

## 1. Objective

Build a daily global lead-intelligence crawler that identifies pharmaceutical and biotech companies showing high-probability demand for custom impurity synthesis, reference standards, degradation products, nitrosamine/NDSRI standards, process impurities, metabolites, and related analytical synthesis work.

The primary output is a **molecule-level opportunity**, not a generic company lead.

Each qualified opportunity should answer:

- Which company is involved?
- Which molecule/API/drug candidate is involved?
- What public signal suggests impurity-synthesis demand?
- What type of impurity work is likely?
- How strong and recent is the evidence?
- Which decision-maker role is most likely relevant?
- Which source URLs support the conclusion?

Target output: **20–30 high-precision opportunities/day** once source coverage matures.

## 2. Scope

### Included in V1

- Global discovery
- Molecule-level opportunity records
- Regulatory and clinical-trial signals
- Company pipeline/news/R&D pages
- Careers/job-posting signals
- Public tenders/RFQs/procurement pages
- Common Crawl discovery and historical enrichment
- Deterministic extraction and scoring only; no paid LLM/API
- Decision-maker role inference, but no paid contact enrichment
- Daily scheduled scan
- Searchable internal dashboard
- CSV and Excel export
- Structured signal history in Supabase
- Source URL + evidence snippet retention

### Excluded from V1

- Paid search APIs
- Paid enrichment APIs
- Paid LLM calls
- CAPTCHA bypass
- Authenticated-site scraping
- LinkedIn automation/scraping
- Full raw-page storage
- Email automation / CRM sequencing
- Multi-user roles and team workflows
- Automated outreach

## 3. Architecture options considered

### Option A — Direct source crawling only

Use regulatory APIs, clinical registries, company sitemaps, careers pages, and procurement portals.

Pros:
- Highest control and precision
- Easier compliance and debugging
- Low compute use

Cons:
- Misses long-tail pages and obscure global sources
- Requires many bespoke source adapters

### Option B — Curated sources + Common Crawl — RECOMMENDED

Structured sources build the company/molecule universe. Common Crawl helps discover and enrich relevant public pages across the wider web. Original sites are re-fetched only when safe and useful.

Pros:
- Global reach at zero API cost
- Better recall than direct crawling alone
- Historical evidence is available
- Less dependence on brittle search-engine scraping

Cons:
- Common Crawl is not real-time
- Requires careful query narrowing to stay within GitHub Actions compute budgets

### Option C — Search-engine scraping + curated sources

Pros:
- Broad discovery
- Fresh results

Cons:
- Brittle
- Frequent blocking
- Higher operational risk
- Poor fit for a reliable ₹0 internal system

**Decision:** Option B.

## 4. Zero-cost infrastructure

### Scheduler and crawler execution

**GitHub Actions (private repository)**

- Daily scheduled workflow
- GitHub Free currently includes 2,000 Actions minutes/month for private repositories.
- Design goal: keep average daily production crawl under 45 minutes and monthly usage below 1,350 minutes, leaving safety margin for tests/manual runs.
- If usage approaches the quota, split source adapters across days rather than paying for compute.

### Database and API

**Supabase Free**

- Existing project: `Ravi Project`
- Store only normalized entities, structured signals, evidence snippets, scores, run metadata, and user review state.
- Do not store raw HTML/WARC payloads.
- Budget target: keep database below 350 MB to retain margin under the 500 MB free quota.
- Apply retention/compaction rules to low-value run logs and duplicate signals.

### Dashboard hosting

**Cloudflare Pages Free**

- Static frontend hosting
- Static asset requests are free/unlimited under current Pages documentation.
- Dashboard uses Supabase client APIs after authentication.
- Avoid Pages Functions unless needed; static-first architecture reduces moving parts.

### Authentication

**Supabase passwordless email login**

- One approved internal user initially.
- RLS enabled on every exposed table.
- Frontend uses a Supabase publishable key only.
- Secret/service keys stay in GitHub Actions secrets and are never shipped to the browser.

## 5. Data-source strategy

The crawler uses source adapters with a common normalized output.

### Tier 1 — Structured, high-value sources

1. **ClinicalTrials.gov API**
   - Sponsor/company
   - Intervention/drug
   - Phase
   - Trial status
   - Start/update dates
   - Countries
   - Collaborators
   - Useful globally because many international trials are registered there

2. **FDA/openFDA / Drugs@FDA / Orange Book**
   - Applicant
   - Active ingredient
   - NDA/ANDA
   - Approval/action dates
   - Dosage forms
   - Generic/brand relationships

3. **EMA / EU medicine and clinical-trial public sources**
   - Medicine/application activity
   - Sponsor
   - Active substance
   - Regulatory milestones
   - CTIS/public trial information where publicly accessible

### Tier 2 — Company-controlled public sources

For discovered companies/domains:

- `/pipeline`
- `/research`
- `/rd`
- `/news`
- `/press-releases`
- `/investors`
- `/careers`
- `/jobs`
- `/procurement`
- `/tenders`
- `/suppliers`

Discovery methods:

- `robots.txt`
- `sitemap.xml` / sitemap indexes
- RSS/Atom feeds
- internal-link traversal constrained to relevant paths

### Tier 3 — Common Crawl

Use the latest available Common Crawl index for:

- domain page discovery
- historical mentions
- job-page discovery
- tender/procurement page discovery
- obscure public source discovery

Use targeted domain/pattern queries. Never attempt broad entire-TLD downloads in GitHub Actions.

Common Crawl records are used primarily for URL discovery and, when appropriate, small byte-range retrievals of specific archived captures.

### Tier 4 — Public tender and procurement sources

Add adapters iteratively for regions that produce actual useful signals. Requirements:

- public access without login
- permitted automated access
- stable URL/search structure or feed
- evidence contains buyer, compound, analytical standard, synthesis, impurity, or related terminology

## 6. Crawl ethics and access policy

The crawler must:

- obey robots.txt for direct website crawling
- use rate limiting per domain
- identify itself with a descriptive User-Agent and contact URL/email when deployed
- back off on 429/503 responses
- never bypass CAPTCHAs
- never scrape authenticated/private content
- never rotate identities to evade blocking
- never collect unnecessary personal data
- retain only public professional-role information needed for B2B relevance

A domain can be marked `blocked`, `manual_only`, or `do_not_crawl`.

## 7. Normalized source-adapter interface

Every adapter emits records with the same shape:

```text
source_name
source_type
source_record_id
source_url
published_at
fetched_at
company_name_raw
company_domain_raw
molecule_name_raw
active_ingredient_raw
signal_text
country
metadata_json
```

Normalization happens after ingestion.

## 8. Entity model

### companies

- id UUID
- normalized_name
- legal_name
- domain
- country
- company_type
- is_impurity_vendor
- is_cro_cdmo
- first_seen_at
- last_seen_at

### molecules

- id UUID
- canonical_name
- synonyms text[]
- cas_number nullable
- unii nullable
- development_code nullable
- molecule_type
- small_molecule boolean
- first_seen_at
- last_seen_at

### company_molecules

- id UUID
- company_id
- molecule_id
- relationship_type
- development_phase
- regulatory_status
- first_seen_at
- last_seen_at

### signals

- id UUID
- company_id
- molecule_id nullable
- source_type
- signal_type
- source_url
- source_record_id nullable
- evidence_text
- event_date
- discovered_at
- freshness_days
- base_weight
- confidence
- fingerprint unique
- metadata_json

### opportunities

- id UUID
- company_id
- molecule_id
- score
- priority
- likely_need_type text[]
- rationale
- decision_maker_role text[]
- first_qualified_at
- last_qualified_at
- last_signal_at
- status (`new`, `reviewed`, `qualified`, `dismissed`, `contacted`)
- dismissal_reason nullable

### opportunity_signals

- opportunity_id
- signal_id
- contribution_score

### crawl_runs

- id UUID
- started_at
- completed_at
- source_adapter
- status
- records_seen
- records_inserted
- errors
- duration_seconds

### crawl_domains

- domain
- crawl_state
- last_crawled_at
- next_crawl_at
- robots_status
- error_count
- average_response_ms

## 9. Entity normalization

### Company matching

Priority:

1. canonical domain match
2. regulatory applicant/sponsor identifiers
3. normalized legal-name exact match
4. alias table
5. conservative fuzzy match only above strict threshold

Ambiguous matches are stored as unresolved rather than merged automatically.

### Molecule matching

Normalize:

- generic/API name
- development codes
- salts/solvates
- brand names
- spelling/case/punctuation variants

CAS numbers, where publicly available, are strong identifiers but not mandatory.

A molecule should never be merged solely because two names are textually similar.

## 10. Signal taxonomy

### Direct / very-high-intent

- explicit RFQ for impurity/reference standard/custom synthesis
- named impurity with requested quantity
- tender for analytical/reference standards
- public procurement request

### High-intent analytical

- nitrosamine/NDSRI investigation
- genotoxic impurity / ICH M7 work
- impurity isolation/characterization
- degradation-product characterization
- reference-standard preparation
- forced degradation / stability-indicating method work tied to a named molecule

### Regulatory / development

- NDA/ANDA/MAA activity
- new approval or filing
- late-stage small-molecule development
- formulation-development milestone
- major manufacturing-transfer activity

### Hiring

Named molecule when available plus roles/descriptions containing:

- analytical development
- LC-MS / LC-MS/MS
- impurity profiling
- structure elucidation
- degradation products
- nitrosamines
- method development/validation
- stability studies

### Negative / exclusion signals

- company is primarily an impurity/reference-standard vendor
- company is clearly selling the same service rather than buying it
- biologic-only program with no plausible small-molecule impurity need
- stale event
- generic company-description language with no molecule linkage

## 11. Deterministic extraction

V1 has no LLM dependency.

### Extractors

- keyword phrase matcher
- regex for CAS numbers
- regex for quantities: mg, g, kg
- trial phase parser
- regulatory application parser
- molecule-name dictionary
- company/sponsor normalization
- title/heading weighting
- date extraction
- job-title parser

### Context windows

When a keyword is found, retain a compact evidence window around the hit instead of the full page.

Example:

```text
...responsible for isolation and characterization of process and degradation impurities for [Molecule X], including LC-MS and NMR...
```

This is stored as evidence_text.

## 12. High-precision scoring model

Scores are additive but capped at 100 for display.

Indicative base weights:

- direct named-molecule impurity RFQ: +70
- named-molecule reference-standard requirement: +60
- NDSRI/nitrosamine + named molecule: +45
- genotoxic impurity + named molecule: +40
- impurity isolation/characterization + named molecule: +38
- degradation product + named molecule: +35
- new NDA/ANDA/MAA activity: +22
- Phase III small-molecule program: +18
- Phase II small-molecule program: +12
- analytical-development job mentioning impurity work: +20
- stability/forced degradation + named molecule: +18
- method validation + named molecule: +12
- explicit quantity / CAS / analytical characterization package: +15

Negative weights:

- known impurity/reference-standard vendor: -100
- no named molecule/API after enrichment: -25
- signal older than 365 days: -30
- signal 180–365 days: -15
- generic pharma activity only: -25
- duplicate evidence from mirrored/syndicated page: contribution 0

### Multipliers / gates

High-precision qualification requires:

- a resolvable company, AND
- a resolvable molecule/API, AND
- at least one non-generic signal, AND
- no competitor exclusion

Priority:

- `HOT`: score >= 80 or direct RFQ
- `HIGH`: score 65–79
- `REVIEW`: score 50–64
- below 50: retained as structured signals but not shown in the default lead queue

The default dashboard shows HOT + HIGH only. This is how the system prioritizes precision.

## 13. Opportunity aggregation

Signals are not leads by themselves.

A daily job groups recent signals by `(company, molecule)` and computes:

- total weighted score
- independent-source count
- latest signal date
- likely need type
- confidence
- decision-maker role recommendation

Example:

```text
Company A + Molecule X
- Phase III update                     +18
- Analytical R&D role                 +20
- Job mentions degradation impurity   +35
- Stability study                     +18
- Independent-source bonus            +8
------------------------------------------------
Raw score                              99
Displayed score                        99
Priority                               HOT
```

## 14. Decision-maker role inference

No contact scraping is required in V1.

Map likely need to roles:

- impurity characterization -> Head/Director Analytical R&D
- API/process impurity -> Process Chemistry / API Development / CMC
- nitrosamine/NDSRI -> Analytical Development / Quality / Regulatory CMC
- reference standards/procurement -> Analytical R&D + Strategic Sourcing/Procurement
- regulatory filing -> CMC / Regulatory Affairs / Analytical Development

Dashboard displays 1–3 recommended role titles.

## 15. Daily pipeline

```text
GitHub Actions cron
    |
    +--> Tier 1 adapters
    |      ClinicalTrials / FDA / EMA
    |
    +--> update company + molecule universe
    |
    +--> crawl due company domains
    |      sitemap/RSS/relevant paths
    |
    +--> query Common Crawl for targeted domains/patterns
    |
    +--> public jobs/tenders adapters
    |
    +--> normalize entities
    |
    +--> extract signals
    |
    +--> deduplicate
    |
    +--> score (company, molecule) opportunities
    |
    +--> persist structured results to Supabase
    |
    +--> generate run summary / CSV-XLSX export artifact
```

## 16. Scheduling strategy under the free compute budget

Not every source must run at the same frequency.

Daily:
- ClinicalTrials incremental changes
- high-value regulatory updates
- known active company feeds/sitemaps
- selected careers/tender pages
- opportunity rescoring

2–3 times/week:
- broader company-site recrawl
- Common Crawl enrichment for newly discovered companies/molecules

Weekly:
- stale-domain retry
- competitor/vendor list refresh
- deduplication/maintenance
- data-quality report

This keeps Actions usage predictable.

## 17. Common Crawl strategy

Common Crawl is **not** treated as a search engine replacement for arbitrary keyword search across the full web in every daily run.

Efficient V1 pattern:

1. discover company/domain from structured source
2. query the latest Common Crawl URL/CDX index for that domain and relevant path patterns
3. filter candidates by URL terms (`career`, `job`, `pipeline`, `impurity`, `nitrosamine`, `tender`, etc.)
4. retrieve only selected archived records via byte ranges if needed
5. extract text and signals
6. optionally re-fetch the live original URL subject to robots/access rules

For wider discovery, maintain curated pharmaceutical-domain seed lists by region and rotate subsets across runs.

## 18. Deduplication

Create a signal fingerprint from normalized:

```text
company_id + molecule_id + signal_type + canonical_source_url + normalized_evidence
```

Also detect mirrored press releases and syndicated jobs using content hashes.

Duplicate signals may update `last_seen` but cannot inflate opportunity scores.

## 19. Dashboard

### Default screen — Opportunity Queue

Columns:

- Priority
- Score
- Company
- Country
- Molecule/API
- Likely need
- Latest signal
- Why now
- Recommended decision-maker roles
- Evidence count
- First seen

Filters:

- priority
- country/region
- signal type
- likely need type
- development phase
- date range
- status

### Opportunity detail

- company + molecule summary
- score breakdown
- chronological evidence timeline
- evidence snippets with source links
- recommended roles
- status/action notes

### Secondary screens

- Signals
- Companies
- Molecules
- Crawl health
- Exports

## 20. Export

Daily export contains one row per qualified opportunity.

Columns:

```text
Date
Priority
Score
Company
Domain
Country
Molecule/API
CAS
Development Phase
Likely Need
Why Now
Recommended Role 1
Recommended Role 2
Latest Evidence
Latest Source URL
Signal Count
First Seen
Last Seen
Status
```

Generate CSV always and XLSX when practical in the workflow.

## 21. Security design

- Supabase RLS enabled on every exposed table.
- `anon` receives no table access.
- `authenticated` receives read/update access only where the dashboard needs it.
- crawler writes use a server-side Supabase secret key stored only in GitHub Actions Secrets.
- new Supabase projects/tables now require explicit Data API grants; migrations will include grants intentionally rather than assume auto-exposure.
- use current `sb_publishable_*` / `sb_secret_*` keys rather than designing around legacy anon/service-role keys.
- do not create `SECURITY DEFINER` functions unless strictly necessary.
- if views are exposed, use `security_invoker = true`.

## 22. Error handling

### Network

- retries: maximum 2 for transient failures
- exponential backoff
- respect Retry-After
- 429 -> defer domain
- repeated 403 -> mark manual_only/blocked

### Parsing

- malformed record does not fail whole run
- save adapter error summary without storing raw page

### Entity ambiguity

- do not force merge
- mark unresolved and exclude from high-priority opportunities until resolved

### Budget guardrails

Daily workflow stops before a configured execution deadline.

Priority order when time is constrained:

1. Tier 1 regulatory/trial sources
2. already-hot companies
3. newly discovered molecules
4. company sites/jobs
5. Common Crawl enrichment

## 23. Testing strategy

### Unit tests

- CAS extraction
- quantity extraction
- molecule alias normalization
- company normalization
- signal classifiers
- scoring
- freshness penalties
- competitor exclusion
- deduplication

### Fixture tests

Keep small saved HTML/JSON fixtures representing:

- trial record
- FDA record
- company pipeline page
- job posting
- tender/RFQ
- impurity-vendor page

No production crawling is required for unit tests.

### Adapter contract tests

Every adapter must emit the normalized source-record interface.

### End-to-end smoke test

Use a small set of 5–10 known companies/molecules and confirm:

- discovery
- extraction
- storage
- aggregation
- dashboard query
- export

### Precision acceptance test

Before considering V1 useful:

- manually review at least 100 surfaced HOT/HIGH opportunities
- target >= 80% judged commercially relevant
- target <= 10% obvious competitor/vendor false positives
- tune thresholds before increasing volume

## 24. Data retention and free-tier control

Keep:

- companies/molecules indefinitely
- qualified opportunities indefinitely
- high-value evidence indefinitely unless source removal is requested

Compact/delete:

- duplicate low-value signals after 90 days
- successful crawl-run detail after 30 days, retaining aggregates
- verbose error metadata after 30 days

Never store full HTML by default.

## 25. Implementation phases

### Phase 1 — Core engine

- Python package structure
- entity models
- extraction rules
- scoring engine
- SQLite/local fixture tests
- CSV export

### Phase 2 — Initial source adapters

- ClinicalTrials.gov
- FDA/openFDA
- company sitemap/site crawler
- Common Crawl targeted enrichment

### Phase 3 — Supabase

- schema
- RLS/grants
- authenticated single-user access
- crawler upserts

### Phase 4 — Dashboard

- static frontend
- login
- opportunity queue/detail
- filters
- CSV/XLSX export

### Phase 5 — Expansion

- EMA/EU sources
- jobs
- tenders/RFQs
- additional regional regulatory sources
- precision tuning

## 26. Success criteria

V1 is accepted when:

1. daily run completes automatically within the free GitHub Actions allowance
2. all services remain on free tiers with no paid API dependency
3. data stays below defined Supabase safety margins
4. dashboard requires authentication
5. raw page bodies are not persisted
6. opportunities are molecule-level and source-backed
7. competitor/vendor false positives are strongly suppressed
8. 100-lead manual validation achieves >=80% commercial relevance
9. system can sustain a path toward 20–30 high-quality opportunities/day without lowering precision thresholds

## 27. Current platform facts informing this design

Verified 2026-09-04:

- Common Crawl exposes free HTTP(S) access to its archives and URL/CDX indexes; latest listed crawls include 2026 archives.
- GitHub Free includes 2,000 Actions minutes/month for private repositories using standard hosted runners.
- Supabase Free includes a 500 MB database quota and 5 GB uncached egress plus 5 GB cached egress; projects may pause after inactivity.
- Cloudflare Pages static asset requests are free and unlimited; free plan currently allows 500 builds/month.
- Supabase is moving/has moved public tables toward explicit Data API grants instead of automatic exposure; the schema will use explicit grants.
- Supabase recommends publishable/secret keys for new integrations; legacy anon/service-role keys remain compatible only through the end of 2026.

## 28. Final design decision

Implement **curated structured sources + targeted Common Crawl**, with deterministic scoring and authenticated Supabase-backed dashboard, optimized first for precision and constrained to zero paid infrastructure/API spend.
