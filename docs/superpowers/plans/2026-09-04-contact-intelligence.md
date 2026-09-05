# Verified Contact Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add zero-cost, evidence-backed decision-maker contact enrichment for qualified HOT/HIGH impurity-synthesis opportunities without ever presenting an inferred mailbox as verified.

**Architecture:** Contact enrichment is a second-stage pipeline that consumes existing `Opportunity` objects and known company domains, discovers public contact-oriented pages, extracts people/business contact evidence deterministically, ranks role fit, learns company email patterns only from multiple named public employee mailboxes, and stores/export up to three contacts per opportunity. Existing opportunity extraction/scoring remains unchanged; enrichment failure never blocks the underlying lead.

**Tech Stack:** Python 3.11+, Pydantic, BeautifulSoup/lxml, httpx, existing robots/sitemap/Common Crawl adapters, Supabase Python client, pytest, openpyxl.

**Spec:** `docs/superpowers/specs/2026-09-04-contact-intelligence-design.md`

## Global Constraints

- Recurring infrastructure cost must remain ₹0 within the approved free-tier limits.
- Use only public professional/business information; no authenticated LinkedIn scraping, CAPTCHA/login/paywall bypass, SMTP probing, personal-data brokers, or automatic outreach.
- `VERIFIED_PUBLIC` is only for exact contact values observed in public professional evidence.
- Generated company-domain emails are always `PATTERN_CONFIRMED`, never `VERIFIED_PUBLIC`.
- Pattern inference requires at least two distinct named employee emails on the same company domain with one consistent deterministic pattern.
- Generic aliases (`info`, `sales`, `careers`, `support`, `contact`, `procurement`) never participate in pattern learning.
- Persist evidence snippets capped at 800 characters and source URLs; never persist raw HTML.
- Enrich only HOT/HIGH opportunities, cap at 30 opportunities/day, and obey the parent daily deadline.
- Primary contacts require role-fit score >= 55; stale contacts are hidden by default.
- Existing opportunity scoring modules remain behaviorally unchanged.

---

## File Structure

- `src/impurity_leads/contacts/__init__.py` — contact subsystem package boundary.
- `src/impurity_leads/contacts/models.py` — `ContactCandidate`, `ContactEvidence`, `RankedContact` contracts and status literals.
- `src/impurity_leads/contacts/normalize.py` — names, titles, emails, phone and company-domain normalization.
- `src/impurity_leads/contacts/extract.py` — JSON-LD, `mailto:`, `tel:`, contact-card, and structured trial-contact extraction.
- `src/impurity_leads/contacts/patterns.py` — deterministic company email-pattern detection/generation.
- `src/impurity_leads/contacts/rank.py` — opportunity-context role-family mapping and role-fit scoring.
- `src/impurity_leads/contacts/verify.py` — exact-public/pattern/role-only/stale status and confidence assignment.
- `src/impurity_leads/contacts/pipeline.py` — second-stage candidate merge, pattern inference, ranking, and evidence orchestration.
- `src/impurity_leads/contacts/discovery.py` — contact-oriented company-domain URL discovery/fetching using existing robots/sitemap/Common Crawl machinery.
- `src/impurity_leads/storage/base.py` — extend persistence protocol for contacts and opportunity-contact links.
- `src/impurity_leads/storage/memory.py` — in-memory contact persistence for tests/smoke runs.
- `src/impurity_leads/storage/supabase_store.py` — stable UUID persistence for contacts/evidence/rankings.
- `src/impurity_leads/export.py` — add up to three ranked contact groups to CSV/XLSX exports.
- `src/impurity_leads/cli.py` — run contact enrichment after qualification when company seeds/domains exist.
- `supabase/schema.sql` — add contact tables, indexes, grants, and RLS.
- `tests/contacts/*` and fixtures — unit/fixture/integration coverage.

---

### Task 1: Contact Contracts and Normalization

**Files:**
- Create: `src/impurity_leads/contacts/__init__.py`
- Create: `src/impurity_leads/contacts/models.py`
- Create: `src/impurity_leads/contacts/normalize.py`
- Create: `tests/contacts/test_models.py`
- Create: `tests/contacts/test_normalize.py`

**Interfaces:**
- Produces `ContactEvidence`, `ContactCandidate`, `RankedContact`, `EmailStatus`, `PhoneStatus`.
- Produces `normalize_person_name(name: str) -> str`, `normalize_email(value: str) -> str | None`, `email_domain(value: str) -> str | None`, `normalize_phone(value: str) -> str | None`, `title_family(title: str) -> str | None`.

- [ ] **Step 1: Write failing model tests**

```python
from datetime import datetime, timezone
from impurity_leads.contacts.models import ContactEvidence, ContactCandidate


def test_contact_evidence_rejects_long_snippet():
    now = datetime.now(timezone.utc)
    evidence = ContactEvidence(
        evidence_type="email",
        observed_value="jane@example.com",
        source_type="company_site",
        source_url="https://example.com/team",
        evidence_text="x" * 900,
        observed_at=now,
        fingerprint="abc",
    )
    assert len(evidence.evidence_text) == 800


def test_contact_candidate_defaults_to_role_only_without_exact_values():
    candidate = ContactCandidate(company_name="Example Pharma", display_name="Dr Jane Smith", title="Director, Analytical Development")
    assert candidate.email_status == "ROLE_ONLY"
    assert candidate.phone_status == "ROLE_ONLY"
```

- [ ] **Step 2: Run model tests and verify RED**

Run: `pytest tests/contacts/test_models.py -v`
Expected: import failure because `impurity_leads.contacts.models` does not exist.

- [ ] **Step 3: Implement minimal contracts**

```python
# contacts/models.py
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

EmailStatus = Literal["VERIFIED_PUBLIC", "PATTERN_CONFIRMED", "ROLE_ONLY", "STALE"]
PhoneStatus = Literal["VERIFIED_PUBLIC", "ROLE_ONLY", "STALE"]

class ContactEvidence(BaseModel):
    evidence_type: Literal["identity", "title", "email", "phone", "affiliation", "email_pattern"]
    observed_value: str
    source_type: str
    source_url: str
    evidence_text: str
    observed_at: datetime
    fingerprint: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_text")
    @classmethod
    def cap_evidence(cls, value: str) -> str:
        return value[:800]

class ContactCandidate(BaseModel):
    company_name: str
    display_name: str
    normalized_name: str = ""
    title: str | None = None
    department: str | None = None
    profile_url: str | None = None
    primary_email: str | None = None
    email_status: EmailStatus = "ROLE_ONLY"
    primary_phone: str | None = None
    phone_status: PhoneStatus = "ROLE_ONLY"
    role_fit_score: int = Field(default=0, ge=0, le=100)
    contact_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_verified_at: datetime | None = None
    evidence: list[ContactEvidence] = Field(default_factory=list)

class RankedContact(BaseModel):
    contact: ContactCandidate
    rank: int = Field(ge=1, le=3)
    rationale: str
```

- [ ] **Step 4: Write normalization tests**

```python
from impurity_leads.contacts.normalize import normalize_person_name, normalize_email, email_domain, title_family


def test_normalize_person_name_strips_honorifics_and_punctuation():
    assert normalize_person_name("Dr. Jane A. Smith") == "jane a smith"


def test_normalize_email_rejects_malformed_and_normalizes_case():
    assert normalize_email(" Jane.Smith@Example.COM ") == "jane.smith@example.com"
    assert normalize_email("not-an-email") is None


def test_title_family_maps_analytical_role():
    assert title_family("Director, Analytical Development") == "analytical"
```

- [ ] **Step 5: Run normalization tests and verify RED**

Run: `pytest tests/contacts/test_normalize.py -v`
Expected: import failure because `contacts.normalize` does not exist.

- [ ] **Step 6: Implement normalization and run Task 1 green**

Implement deterministic regex/string normalization, then run:
`pytest tests/contacts/test_models.py tests/contacts/test_normalize.py -v`
Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/impurity_leads/contacts tests/contacts/test_models.py tests/contacts/test_normalize.py
git commit -m "feat: add contact intelligence contracts"
```

---

### Task 2: Deterministic Public Contact Extraction

**Files:**
- Create: `src/impurity_leads/contacts/extract.py`
- Create: `tests/contacts/test_extract.py`
- Create: `tests/fixtures/contact_leadership.html`
- Create: `tests/fixtures/contact_rd_no_email.html`
- Create: `tests/fixtures/contact_trial.json`

**Interfaces:**
- Consumes normalization/contracts from Task 1.
- Produces `extract_contacts_from_html(url: str, html: str, company_name: str, observed_at: datetime) -> list[ContactCandidate]`.
- Produces `extract_trial_contacts(payload: dict, company_name: str, source_url: str, observed_at: datetime) -> list[ContactCandidate]`.

- [ ] **Step 1: Add fixtures and failing extraction tests**

```python

def test_extracts_jsonld_person_and_exact_public_email(fixture_html):
    contacts = extract_contacts_from_html("https://example.com/leadership", fixture_html, "Example Pharma", NOW)
    jane = next(c for c in contacts if c.normalized_name == "jane smith")
    assert jane.primary_email == "jane.smith@example.com"
    assert jane.email_status == "VERIFIED_PUBLIC"
    assert any(e.evidence_type == "email" and e.source_url.endswith("/leadership") for e in jane.evidence)


def test_rd_person_without_email_remains_role_only(rd_html):
    contact = extract_contacts_from_html("https://example.com/research", rd_html, "Example Pharma", NOW)[0]
    assert contact.primary_email is None
    assert contact.email_status == "ROLE_ONLY"
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/contacts/test_extract.py -v`
Expected: import failure for `contacts.extract`.

- [ ] **Step 3: Implement extraction in the required order**

Implementation must parse JSON-LD `Person`, same-block `mailto:`/`tel:`, relevant contact cards, and trial contact dictionaries. Every exact email/phone creates its own `ContactEvidence`; fingerprints use a stable SHA-256 over normalized person + evidence type + observed value + source URL. No raw HTML is returned or stored.

- [ ] **Step 4: Run extraction tests green**

Run: `pytest tests/contacts/test_extract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/impurity_leads/contacts/extract.py tests/contacts/test_extract.py tests/fixtures/contact_*.html tests/fixtures/contact_trial.json
git commit -m "feat: extract public business contacts"
```

---

### Task 3: Corporate Email Pattern Learning

**Files:**
- Create: `src/impurity_leads/contacts/patterns.py`
- Create: `tests/contacts/test_patterns.py`

**Interfaces:**
- Produces `detect_email_pattern(named_emails: list[tuple[str, str]], company_domain: str) -> str | None`.
- Produces `generate_pattern_email(person_name: str, company_domain: str, pattern: str) -> str | None`.
- Supported pattern names: `first.last`, `firstlast`, `f.last`, `flast`, `firstl`, `last.first`, `lastf`.

- [ ] **Step 1: Write failing pattern tests**

```python

def test_requires_two_distinct_named_people_for_pattern():
    assert detect_email_pattern([("Jane Smith", "jane.smith@example.com")], "example.com") is None


def test_detects_consistent_first_dot_last_pattern():
    samples = [("Jane Smith", "jane.smith@example.com"), ("Arun Rao", "arun.rao@example.com")]
    assert detect_email_pattern(samples, "example.com") == "first.last"


def test_conflicting_patterns_disable_inference():
    samples = [("Jane Smith", "jane.smith@example.com"), ("Arun Rao", "arao@example.com")]
    assert detect_email_pattern(samples, "example.com") is None


def test_generic_aliases_never_train_pattern():
    samples = [("Jane Smith", "jane.smith@example.com"), ("Sales Team", "sales@example.com")]
    assert detect_email_pattern(samples, "example.com") is None
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/contacts/test_patterns.py -v`
Expected: import failure for `contacts.patterns`.

- [ ] **Step 3: Implement all seven deterministic patterns**

Pattern detection must require the same unique match for at least two distinct normalized people, reject consumer domains and generic local parts, and return `None` if more than one pattern remains plausible across the sample set.

- [ ] **Step 4: Run pattern tests green**

Run: `pytest tests/contacts/test_patterns.py -v`
Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/impurity_leads/contacts/patterns.py tests/contacts/test_patterns.py
git commit -m "feat: infer corporate email patterns safely"
```

---

### Task 4: Opportunity-Aware Role Ranking and Verification

**Files:**
- Create: `src/impurity_leads/contacts/rank.py`
- Create: `src/impurity_leads/contacts/verify.py`
- Create: `tests/contacts/test_rank.py`
- Create: `tests/contacts/test_verify.py`

**Interfaces:**
- `score_role_fit(opportunity: Opportunity, contact: ContactCandidate, source_type: str | None = None) -> tuple[int, str]`.
- `apply_contact_verification(contact: ContactCandidate, company_domain: str, confirmed_pattern: str | None, now: datetime, freshness_days: int = 180) -> ContactCandidate`.

- [ ] **Step 1: Write ranking tests**

```python

def test_nitrosamine_opportunity_prefers_analytical_director_over_ceo():
    opportunity = Opportunity(company_name="Example Pharma", molecule_name="Drug X", score=90, priority="HOT", likely_need_type=["nitrosamine/NDSRI"], rationale="x")
    analytical = ContactCandidate(company_name="Example Pharma", display_name="Jane Smith", title="Director, Analytical Development")
    ceo = ContactCandidate(company_name="Example Pharma", display_name="Bob Chief", title="Chief Executive Officer")
    assert score_role_fit(opportunity, analytical)[0] >= 55
    assert score_role_fit(opportunity, analytical)[0] > score_role_fit(opportunity, ceo)[0]


def test_direct_rfq_rewards_procurement_role():
    opportunity = Opportunity(company_name="Example Pharma", molecule_name="Drug X", score=95, priority="HOT", likely_need_type=["direct RFQ"], rationale="x")
    buyer = ContactCandidate(company_name="Example Pharma", display_name="Priya Rao", title="Director, Strategic Sourcing")
    assert score_role_fit(opportunity, buyer)[0] >= 55
```

- [ ] **Step 2: Run ranking tests RED, implement deterministic mapping, rerun green**

Run: `pytest tests/contacts/test_rank.py -v` before and after implementation.

- [ ] **Step 3: Write verification tests**

```python

def test_exact_company_domain_email_stays_verified_public():
    contact = candidate_with_exact_public_email()
    verified = apply_contact_verification(contact, "example.com", None, NOW)
    assert verified.email_status == "VERIFIED_PUBLIC"
    assert verified.contact_confidence == 1.0


def test_generated_pattern_email_is_never_verified_public():
    contact = current_role_only_candidate("Jane Smith")
    verified = apply_contact_verification(contact, "example.com", "first.last", NOW)
    assert verified.primary_email == "jane.smith@example.com"
    assert verified.email_status == "PATTERN_CONFIRMED"
    assert verified.contact_confidence == 0.70


def test_old_unconfirmed_affiliation_becomes_stale():
    contact = old_candidate(days_old=181)
    assert apply_contact_verification(contact, "example.com", None, NOW).email_status == "STALE"
```

- [ ] **Step 4: Implement verification and run Task 4 green**

Run: `pytest tests/contacts/test_rank.py tests/contacts/test_verify.py -v`
Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/impurity_leads/contacts/rank.py src/impurity_leads/contacts/verify.py tests/contacts/test_rank.py tests/contacts/test_verify.py
git commit -m "feat: rank and verify contact candidates"
```

---

### Task 5: Second-Stage Contact Enrichment Orchestration

**Files:**
- Create: `src/impurity_leads/contacts/pipeline.py`
- Create: `src/impurity_leads/contacts/discovery.py`
- Create: `tests/contacts/test_pipeline.py`
- Create: `tests/contacts/test_discovery.py`
- Create: `tests/fixtures/contact_pattern_people.html`

**Interfaces:**
- `contact_candidate_urls(urls: list[str], domain: str, limit: int = 12) -> list[str]` ranks same-domain URLs by contact-oriented path tokens.
- `enrich_opportunity_contacts(opportunity: Opportunity, company_domain: str, page_documents: list[tuple[str, str]], trial_payloads: list[dict] | None = None, now: datetime | None = None) -> list[RankedContact]` returns max three contacts.
- Enrichment keeps candidates separate when identity is ambiguous and only shows `ROLE_ONLY` when no stronger relevant contact exists.

- [ ] **Step 1: Write discovery tests**

```python

def test_contact_url_discovery_prefers_leadership_and_rd_paths():
    urls = ["https://example.com/products", "https://example.com/about/leadership", "https://example.com/research/analytical", "https://other.com/team"]
    selected = contact_candidate_urls(urls, "example.com", limit=2)
    assert selected == ["https://example.com/about/leadership", "https://example.com/research/analytical"]
```

- [ ] **Step 2: Run discovery RED, implement, rerun green**

Run: `pytest tests/contacts/test_discovery.py -v`.

- [ ] **Step 3: Write integration-style pipeline test**

```python

def test_nitrosamine_pipeline_returns_exact_public_contact_before_pattern_contact():
    opportunity = Opportunity(company_name="Example Pharma", molecule_name="Drug X", score=92, priority="HOT", likely_need_type=["nitrosamine/NDSRI"], rationale="regulatory impurity work")
    ranked = enrich_opportunity_contacts(opportunity, "example.com", PAGE_FIXTURES, now=NOW)
    assert ranked[0].contact.title == "Director, Analytical Development"
    assert ranked[0].contact.email_status == "VERIFIED_PUBLIC"
    assert all(r.contact.role_fit_score >= 55 for r in ranked)
    assert len(ranked) <= 3
    assert all(r.contact.evidence for r in ranked)
```

- [ ] **Step 4: Implement candidate merge/pattern/ranking pipeline**

Candidate merge key is `(normalized company, normalized person)`. Merge only compatible same-person evidence. Learn a company pattern only from exact `VERIFIED_PUBLIC` named employee mailboxes. Apply pattern only to current verified person/title candidates lacking an exact email. Sort by `(email strength, role_fit_score, contact_confidence)` and cap at three.

- [ ] **Step 5: Run Task 5 green**

Run: `pytest tests/contacts/test_discovery.py tests/contacts/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/impurity_leads/contacts/pipeline.py src/impurity_leads/contacts/discovery.py tests/contacts/test_discovery.py tests/contacts/test_pipeline.py tests/fixtures/contact_pattern_people.html
git commit -m "feat: orchestrate contact enrichment"
```

---

### Task 6: Persistence, Security, and Contact-Aware Exports

**Files:**
- Modify: `src/impurity_leads/storage/base.py`
- Modify: `src/impurity_leads/storage/memory.py`
- Modify: `src/impurity_leads/storage/supabase_store.py`
- Modify: `supabase/schema.sql`
- Modify: `src/impurity_leads/export.py`
- Modify: `tests/test_supabase_store.py`
- Modify: `tests/test_export.py`
- Create: `tests/contacts/test_schema.py`

**Interfaces:**
- `LeadStore.save_contact(company_name: str, ranked_contact: RankedContact) -> None`.
- `LeadStore.link_opportunity_contact(opportunity: Opportunity, ranked_contact: RankedContact) -> None`.
- Exports accept optional mapping `contacts_by_opportunity: dict[tuple[str, str], list[RankedContact]] | None = None`.

- [ ] **Step 1: Write failing Supabase/storage tests**

Assert contact upserts use `(company_id, normalized_name)`, evidence uses unique `fingerprint`, opportunity-contact links use `(opportunity_id, contact_id)`, and no payload contains `raw_html` or full page content.

- [ ] **Step 2: Run storage tests RED**

Run: `pytest tests/test_supabase_store.py -v`
Expected: missing contact persistence methods.

- [ ] **Step 3: Extend schema**

Add exactly:

```sql
create table if not exists public.contacts (... unique(company_id, normalized_name));
create table if not exists public.contact_evidence (... fingerprint text not null unique ...);
create table if not exists public.opportunity_contacts (... primary key(opportunity_id, contact_id));
```

Include checks for allowed statuses and score/confidence ranges, indexes on `(company_id, role_fit_score desc)` and `(opportunity_id, rank)`, RLS on all three, `revoke all ... from anon`, read-only grants/policies for `authenticated`, and CRUD grants for `service_role`. No functions/triggers.

- [ ] **Step 4: Write and run schema security tests**

```python

def test_contact_tables_have_rls_and_no_anon_grants():
    sql = Path("supabase/schema.sql").read_text().lower()
    for table in ("contacts", "contact_evidence", "opportunity_contacts"):
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from anon" in sql
```

- [ ] **Step 5: Add contact columns to exports and tests**

Add three repeated groups: `Contact N Name`, `Title`, `Department`, `Role Fit`, `Email`, `Email Status`, `Phone`, `Phone Status`, `Confidence`, `Profile URL`, `Last Verified`, `Evidence URLs`. Keep existing opportunity columns unchanged.

- [ ] **Step 6: Run Task 6 green**

Run: `pytest tests/test_supabase_store.py tests/contacts/test_schema.py tests/test_export.py -v`
Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/impurity_leads/storage src/impurity_leads/export.py supabase/schema.sql tests/test_supabase_store.py tests/test_export.py tests/contacts/test_schema.py
git commit -m "feat: persist and export verified contacts"
```

---

### Task 7: Daily CLI Integration, Budget Guard, and End-to-End Verification

**Files:**
- Modify: `src/impurity_leads/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_seed_enrichment.py`
- Modify: `README.md`
- Modify: `.env.example`

**Interfaces:**
- Daily run enriches only `HOT`/`HIGH`, at most 30 opportunities, only when a known seed domain maps to the opportunity company.
- Contact direct page fetch cap: 12/company/day.
- Enrichment stops when deadline is reached; opportunity export/persistence still completes without contacts.

- [ ] **Step 1: Write failing daily integration tests**

Test that `run_daily` calls enrichment after `process_records`, never enriches `REVIEW`, respects the 30-opportunity cap, and still returns success if contact discovery raises a recoverable fetch exception.

- [ ] **Step 2: Run CLI/integration tests RED**

Run: `pytest tests/test_cli.py tests/test_seed_enrichment.py -v`
Expected: failures because contact enrichment is not wired.

- [ ] **Step 3: Implement minimal CLI handoff**

Reuse seed domains and already-safe public fetch machinery. Discover sitemap/Common Crawl contact URLs, select max 12 same-domain candidates, fetch under robots policy, call `enrich_opportunity_contacts`, persist ranked contacts when store supports contact methods, and pass contact mapping to CSV/XLSX export. Catch contact-stage errors per opportunity and continue.

- [ ] **Step 4: Run focused green**

Run: `pytest tests/test_cli.py tests/test_seed_enrichment.py -v`
Expected: PASS.

- [ ] **Step 5: Update README and `.env.example`**

Document exact verification labels, zero-cost public-source boundary, no SMTP probing, 30-opportunity/12-page caps, and contact columns. No new paid service keys are added.

- [ ] **Step 6: Run full verification**

```bash
pytest -q
python -m impurity_leads.cli test-fixtures
python -m compileall -q src
python - <<'PY'
from pathlib import Path
sql = Path('supabase/schema.sql').read_text().lower()
for table in ('contacts','contact_evidence','opportunity_contacts'):
    assert f'alter table public.{table} enable row level security' in sql
    assert f'revoke all on table public.{table} from anon' in sql
assert 'raw_html' not in sql
print('contact-schema-security=ok')
PY
git status --short
```

Expected: all tests pass, fixture smoke succeeds, compile succeeds, schema-security prints `ok`, and only intentional generated export files (if any) are untracked/modified.

- [ ] **Step 7: Commit Task 7**

```bash
git add src/impurity_leads/cli.py tests/test_cli.py tests/test_seed_enrichment.py README.md .env.example
git commit -m "feat: enrich qualified leads with contacts"
```

---

## Plan Self-Review

- Spec coverage: models/statuses, source extraction, identity normalization, email patterns, phone handling, role-fit scoring, confidence/freshness, three-contact export, storage/RLS, error isolation, daily caps, and no-raw-HTML are all mapped to Tasks 1–7.
- Placeholder scan: no `TBD`, `TODO`, “implement later,” or unspecified test steps remain.
- Type consistency: all later tasks consume `ContactCandidate`, `ContactEvidence`, `RankedContact`, `score_role_fit`, `apply_contact_verification`, and `enrich_opportunity_contacts` with the signatures defined above.
- Scope check: Europe PMC/Crossref discovery remains optional per the approved spec and is intentionally excluded from this first implementation because company-controlled pages + structured trial contacts + existing Common Crawl discovery can satisfy the V1 success criteria without adding a new external adapter. This is YAGNI and preserves the ₹0/precision-first boundary.
