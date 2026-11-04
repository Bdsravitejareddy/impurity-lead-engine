# Working Model Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect bounded public research providers, durable persistence, opportunity/contact linkage, and daily-stage diagnostics into one verified working loop.

**Architecture:** Keep provider discovery pure and persistence in the worker. Add an official-company provider that uses the existing safe HTTP/robots boundary, then extend the existing contact worker with idempotent source-backed writes and opportunity linking. Replace ad-hoc daily logging with a small stage-result contract while preserving the current crawl exit semantics.

**Tech Stack:** Python 3.12+, Pydantic, BeautifulSoup, Supabase Python client, pytest, React/Vite/Vitest.

**Spec:** `docs/superpowers/specs/2026-09-27-working-model-integration-design.md`

## Global Constraints

- Keep `ZERO_COST_MODE=true` as the default and block paid providers before network access.
- Obey robots.txt, descriptive User-Agent, timeout, retry, response-size, and domain restrictions.
- Do not infer or probe private mailboxes.
- Do not persist raw HTML/WARC bodies.
- Preserve manual intelligence and existing RLS/service-role boundaries.
- Every accepted claim, work, theme, and JTBD row must retain source provenance.

## Review Focus

- Company-domain lookalikes and subdomains must be handled safely — owned by Task 1 tests.
- Re-running a research run must not duplicate source-backed rows — owned by Task 2 tests.
- A provider failure must leave earlier provider evidence intact and visible — owned by Task 2 tests.
- Ambiguous identity must not create an opportunity contact — owned by Task 2 tests.
- A failed optional stage must be reported without masking a successful crawl — owned by Task 3 tests.

### Task 1: Normalize the official-company provider boundary

**Files:**
- Create: `src/impurity_leads/research_providers.py`
- Modify: `src/impurity_leads/official_company.py`
- Test: `tests/test_research_providers.py`
- Test: `tests/test_official_company.py`

**Interfaces:**
- `OfficialCompanyRequest` carries contact ID/name, company name/domain, bounded URLs, and optional molecule candidates.
- `ProviderCandidate` carries URL, title, source type, status, evidence text, metadata, and optional identity/technical flags.
- `OfficialCompanyProvider.discover(request, fetcher)` returns provider candidates and metrics without writing to Supabase.

- [ ] Write failing tests for canonical-provider output, bounded URL limits, domain rejection, fetch failure metrics, and vendor/irrelevant suppression.
- [ ] Run `pytest tests/test_research_providers.py tests/test_official_company.py -q` and verify the new provider interface fails.
- [ ] Implement the shared candidate dataclasses and official provider using the existing parser and safe fetch contract.
- [ ] Run the focused tests and verify they pass.
- [ ] Run existing adapter/parser tests to ensure no behavior regression.

### Task 2: Integrate official-company evidence into contact research

**Files:**
- Modify: `src/impurity_leads/contact_research.py`
- Modify: `src/impurity_leads/official_company.py`
- Modify: `src/impurity_leads/research_adapters.py`
- Test: `tests/test_contact_research.py`
- Test: `tests/test_research_adapters.py`

**Interfaces:**
- Add bounded official-page discovery before Europe PMC in `run_pending_contact_research`.
- Resolve the company domain from the contact’s canonical `company_id` and preserve a no-domain/blocked outcome in run metrics.
- Add idempotent persistence helpers for `contact_sources`, `contact_claims`, `contact_works`, `contact_themes`, `contact_problems`, and `contact_jtbd`.

- [ ] Write failing worker tests using the existing fake client pattern for official evidence persistence, rerun idempotency, provider failure isolation, and no-domain behavior.
- [ ] Run the focused worker tests and verify the integration is absent.
- [ ] Implement company-domain lookup, bounded official-page candidates, source upserts, and provenance-linked derived intelligence.
- [ ] Add opportunity-contact linking only for confirmed/probable identities with company/opportunity support; test ambiguous candidates remain unlinked.
- [ ] Update run metrics with provider counts, failure diagnostics, and links created.
- [ ] Run focused worker tests and the full non-integration backend suite.

### Task 3: Make daily post-crawl stages observable

**Files:**
- Create: `src/impurity_leads/execution/stages.py`
- Modify: `scripts/run_daily.py`
- Modify: `web/src/data/supabaseAdapter.ts`
- Test: `tests/test_daily_stages.py`
- Test: `web/src/data/failureDiagnostics.test.ts`

**Interfaces:**
- `StageResult` contains stage name, status, processed count, source/claim/link counts, provider usage, and bounded errors.
- `run_post_crawl_stages(settings, ...)` returns ordered stage results and an overall status while retaining the existing core-crawl exit code.

- [ ] Write failing tests for successful stages, isolated provider failure, and stable JSON event output.
- [ ] Run the focused tests and verify the stage contract is missing.
- [ ] Implement the stage wrapper and migrate `scripts/run_daily.py` to use it without changing queue order or secret handling.
- [ ] Expose the durable stage diagnostics already present in Supabase through the frontend pipeline read model and add a diagnostic rendering assertion.
- [ ] Run backend and frontend focused tests.

### Task 4: End-to-end verification and handoff

**Files:**
- Modify: `docs/PROJECT_HANDOFF.md`
- Test/fixture as needed: `tests/fixtures/`

- [ ] Run `pytest -q --ignore=tests/integration` and record the exact result.
- [ ] Run PostgreSQL integration tests with `TEST_DATABASE_URL` when a local database is available; otherwise record the environment blocker.
- [ ] Run `python -m impurity_leads.cli test-fixtures` and verify CSV/XLSX outputs.
- [ ] Run `npm test` and `npm run build` in `web/`.
- [ ] Run `git diff --check` and inspect the final diff for secrets, raw-body persistence, and unrelated changes.
- [ ] Update the handoff with implemented scope, test evidence, and any external production verification still requiring credentials.

