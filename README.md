# Impurity Synthesis Lead Intelligence Engine

A zero-paid-API research crawler for identifying pharmaceutical and biotech companies that show public, molecule-level signals of likely impurity-synthesis demand, then resolving evidence-backed public business contacts for the strongest leads.

## What V1 does

The backend turns public source records into structured signals, scores `(company, molecule)` opportunities, and enriches qualified HOT/HIGH leads with relevant public business contacts. It includes:

- ClinicalTrials.gov API v2 parsing and live retrieval
- openFDA Drugs@FDA parsing and live retrieval
- public company-page parsing for jobs, R&D, pipeline, tenders and RFQs
- robots.txt enforcement and conservative HTTP fetching
- targeted Common Crawl URL discovery
- deterministic impurity / NDSRI / degradation / reference-standard classification
- competitor / impurity-vendor suppression
- signal deduplication and opportunity aggregation
- public contact extraction from company-controlled pages and structured trial-contact records
- opportunity-aware decision-maker ranking for Analytical R&D, CMC, API/Process Development, Quality, Regulatory and Procurement roles
- guarded corporate email-pattern learning from multiple publicly observed named employee mailboxes
- explicit contact verification labels: `VERIFIED_PUBLIC`, `PATTERN_CONFIRMED`, `ROLE_ONLY`, `STALE`
- CSV and XLSX export with up to three ranked contacts per opportunity
- optional Supabase persistence
- GitHub Actions test and daily-run workflows

The production scheduler is deliberately conservative. Structured regulatory sources run first. Company-site and Common Crawl enrichment operate only against known/seeded company domains so the system does not attempt broad uncontrolled crawling.

## Contact verification semantics

The crawler never treats an inferred mailbox as verified.

- `VERIFIED_PUBLIC` — the exact professional email/phone was observed on a public company-controlled or authoritative professional source and retained with evidence URL/timestamp.
- `PATTERN_CONFIRMED` — the person's current company/title is publicly supported and the email was generated from one deterministic corporate pattern supported by at least two distinct named public employee emails. This is **pattern-derived, not mailbox-verified**.
- `ROLE_ONLY` — a relevant person/role is publicly identified but no sufficiently reliable email/phone is available.
- `STALE` — previously observed contact evidence is outside the freshness window and has not been reconfirmed.

Generic aliases such as `info@`, `sales@`, `careers@`, `support@`, `contact@`, and `procurement@` never establish an employee email pattern. The system performs no SMTP mailbox probing, catch-all testing, password-reset probing, or similar private-mailbox verification.

## Zero-cost constraint

The project is designed around free public data and free tiers only:

- no OpenAI/Claude/other paid model API
- no paid SERP/search API
- no Apollo/Hunter/RocketReach/ZoomInfo/Lusha/Clearbit-style enrichment
- no paid proxy network
- no CAPTCHA bypass
- no authenticated-site scraping
- no automatic outreach

GitHub Actions has a 45-minute hard timeout for the daily workflow and the application has a 42-minute internal budget. Contact enrichment runs only after lead scoring, only for the top 30 HOT/HIGH opportunities, and fetches at most 12 contact-oriented pages per seeded company. Supabase stores only normalized structured data and compact evidence snippets; raw HTML/WARC bodies are not persisted.

## Access and crawling rules

Direct website crawling must:

- obey `robots.txt`
- use a descriptive User-Agent
- honor HTTP 429 / `Retry-After`
- stop on repeated access denial rather than evade it
- never bypass CAPTCHAs or authentication
- collect only public professional/business contact information relevant to B2B lead intelligence
- never collect home addresses or private personal contact details

Common Crawl is used for targeted URL discovery/history, not as an unrestricted search-engine replacement. Direct contact verification is based on the original public page when it can be accessed under the crawler rules.

## Local setup

Python 3.12+ is required.

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

Run the fixture-only end-to-end smoke test:

```bash
python -m impurity_leads.cli test-fixtures
```

That command uses only saved local fixtures and writes:

```text
exports/fixture-opportunities.csv
exports/fixture-opportunities.xlsx
```

Run the live daily scan locally:

```bash
cp seeds/companies.example.csv seeds/companies.csv
# replace the example row with known company domains and molecule candidates
python -m impurity_leads.cli run-daily
```

The private `seeds/companies.csv` file activates company-site + Common Crawl signal and contact enrichment. It is ignored by Git so the target list stays private. Without Supabase credentials, the run uses in-memory persistence and still creates local exports.

For GitHub Actions, store the full seed CSV as a multiline `COMPANY_SEEDS_CSV` repository secret. The workflow materializes it only for the duration of the job.

## Export contact fields

Each opportunity export contains the original opportunity columns plus up to three ranked contact groups. Each contact group includes:

- name
- title
- department
- role-fit score
- business email and email status
- business phone and phone status
- contact confidence
- profile URL
- last verified timestamp
- evidence URLs

`PATTERN_CONFIRMED` appears explicitly in the export so a generated corporate address is never confused with an exact publicly observed mailbox.

## Supabase

`supabase/schema.sql` defines the planned V1 database. It is intentionally **not auto-applied** by this repository.

Required server-side environment variables after the schema is approved and applied:

```text
SUPABASE_URL
SUPABASE_SECRET_KEY
CRAWLER_USER_AGENT
```

No contact-enrichment API key is required.

The secret key must exist only in server-side/local environment variables or GitHub Actions Secrets. It must never be embedded in frontend code.

The schema:

- enables RLS on all exposed tables, including `contacts`, `contact_evidence`, and `opportunity_contacts`
- gives `anon` no table access
- gives authenticated dashboard users read access to contact intelligence
- limits dashboard writes to opportunity review state
- allows crawler writes only through server-side credentials
- stores compact evidence snippets capped at 800 characters and never raw page HTML

## Tests

The suite covers:

- source-record validation
- company/molecule normalization
- CAS/quantity extraction
- evidence windows
- impurity-signal classification
- vendor exclusion
- fingerprint deduplication
- freshness/scoring
- opportunity aggregation
- ClinicalTrials.gov / FDA fixture parsing
- robots.txt handling
- sitemap parsing
- company-site extraction
- Common Crawl URL filtering
- public JSON-LD / `mailto:` / visible-email / `tel:` contact extraction
- person/email/phone normalization
- corporate email-pattern detection and conflicting-pattern rejection
- generic mailbox exclusion
- opportunity-aware contact role ranking
- exact-public vs pattern-derived verification semantics
- stale contact behavior
- contact pipeline ranking and three-contact cap
- contact persistence and RLS/no-anon schema assertions
- contact-aware CSV/XLSX export
- daily 30-opportunity / 12-page / deadline guardrails
- contact-stage failure isolation
- workflow guardrails

## Current V1 boundary

The backend now includes opportunity discovery/scoring plus verified-public/pattern-derived contact intelligence. The remaining product subsystem is the authenticated static dashboard (opportunity queue/detail/filter/export UI) after the backend schema and production crawl are approved.
