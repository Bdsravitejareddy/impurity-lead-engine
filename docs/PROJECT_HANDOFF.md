# SVAK Intelligence Project Handoff

Updated: 2026-09-08

## Current architecture

- Backend: Python deterministic extraction, classification, scoring and resumable crawler.
- Database: Supabase project `kifakogrfdlezwloovpv` (Ravi Project, Sydney region).
- Frontend: React + TypeScript + Vite in `web/`.
- Frontend data path: authenticated Supabase adapter first; sanitized JSON fallback at `web/public/data.json` when Supabase is unavailable.
- Hosting: Cloudflare Pages project `svak-intelligence`.
- Scheduled/backend execution: existing GitHub Actions crawler workflow and Supabase-backed crawler tables.
- Browser-safe credentials: only `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`; service credentials remain backend-only.

## Production URLs

- Website: https://svak-intelligence.pages.dev
- Supabase API: https://kifakogrfdlezwloovpv.supabase.co
- Supabase OAuth callback: https://kifakogrfdlezwloovpv.supabase.co/auth/v1/callback

## Repository state

- Branch/worktree: `spike/enrichment-feasibility` in `/Users/raviteja/impurity-lead-engine`.
- Latest meaningful commit: `ae55f68` (`feat: expand contact intelligence workspace`).
- Latest Cloudflare deployment URL/hash: `https://27c7fb50.svak-intelligence.pages.dev`.
- The working tree also contains earlier spike/scoring changes and generated research artifacts that predate the Contact 360 commit. They remain visible in `git status` and were intentionally not reset or deleted.

## Production data counts

Read-only Supabase verification on 2026-09-08:

- Qualified opportunities (`score >= 50`): 63
- Unique qualified companies: 39
- Contacts: 29
- HOT: 45
- HIGH: 9
- REVIEW: 9
- Contact sources: 4
- Career positions: 3
- JTBD records: 2

The seeded gold-standard Contact 360 profile is Vijayasarathi Ramaswami at Cipla Limited.

## Scoring methodology

The score represents outbound commercial relevance, not purchase probability. Historical positive technical evidence remains useful and never becomes negative because of age. Base signals include direct impurity RFQ, reference standards, nitrosamine/NDSRI, genotoxic impurity, impurity characterization, degradation products, stability, method validation and regulatory application. Recency is a separate one-time urgency bonus: 0–180 days +15, 181–365 +8, 366–730 +3, older or unknown +0. Duplicate/mirrored evidence must not create artificial diversity. Priority thresholds remain REVIEW >=50, HIGH >=65 and HOT >=80. Vendor exclusion and direct-RFQ semantics remain unchanged.

## Contact-status rules and stale-contact safeguard

- `VERIFIED_PUBLIC`: exact professional mailbox or business phone publicly observed for that person.
- `PATTERN_CONFIRMED`: current person plus a company email convention established from at least two distinct named public employee emails; inferred mailbox is never verified.
- `ROLE_ONLY`: relevant current person identified without an acceptable direct route.
- `STALE`: historical or no-longer-current affiliation.
- `PROFESSIONAL`: current/public professional profile is available and useful even without email.
- `UNKNOWN`: current status cannot be independently established.

Historical publication authors are research seeds only. Current role, company and function must be independently verified before being presented as current contacts. Old authors are downgraded or replaced when current evidence is unavailable.

## Contact 360 requirements and implementation

`/contacts/:contactId` is a persistent workspace with tabs for Overview, Career, Work & Research, Problems, JTBD, Opportunities, Sources, Notes & Manual Intel, and History. It displays source coverage, current-role confidence, person/company attribution, claim provenance, career positions, education, person-direct work, organisational work, problems, professional themes, JTBD hypotheses, related opportunities, and outreach preparation. Missing information is shown as unknown rather than invented.

The current implementation uses normalized Supabase tables:

- `contact_sources`
- `contact_positions`
- `contact_education`
- `contact_works`
- `contact_problems`
- `contact_themes`
- `contact_jtbd`
- `contact_claims`
- `contact_notes`
- `contact_history`
- `contact_conflicts`
- `contact_research_runs`

The additive migration is `supabase/migrations/20260908120000_contact_intelligence_workspace.sql`. RLS is enabled on all new tables; anonymous access is revoked and authenticated access is permitted. Backend crawler tables remain protected.

## Manual intelligence requirements

Users can edit a current title, add JTBD intelligence, add internal notes, submit a public source URL, and queue a research refresh. Manual records are stored in Supabase and are separate from public observations. Profile edits create `contact_history` records. `contact_conflicts` is available for manual-versus-automated review so automation does not silently overwrite human intelligence.

Manual entries should carry creator, timestamps, visibility, confidence, source description and related opportunity context. UI badges distinguish `PUBLIC · OBSERVED`, `AI · INFERRED`, `MANUAL`, and `UNKNOWN`.

## Source/provenance model

Sources are canonical per contact and URL, with source type, publisher, source date, access date, status (`USED`, `INSPECTED`, `REJECTED`), evidence strength, claims, and reasons used/not used. Claims, positions, works, problems and JTBD store source UUIDs. Work attribution is explicitly `PERSON_DIRECT`, `COMPANY_CONTEXT` or `OPPORTUNITY_CONTEXT`; organisational evidence is never presented as the individual’s personal work.

For Vijayasarathi, sources include a public professional biography, Cipla’s official annual report, Cipla’s contact route, and a public leadership-transition announcement. The profile currently has three career positions, three education records, one person-direct leadership remit, one organisational work record, two problems, four themes and two inferred JTBD hypotheses.

## Validation status

- Frontend tests: 21 passed.
- Frontend production build: passed.
- Backend suite: 218 passed.
- Integration suite: 14 passed.
- `git diff --check`: passed.
- Production routes `/`, `/contacts`, `/contacts/:id`, `/opportunities`, `/evidence`, `/crawler`, `/settings`: HTTP 200.
- Supabase security advisors were run after the migration. Existing findings remain for protected legacy tables/functions; no anonymous policy was added by this work. New-table foreign-key indexing advisories are informational performance findings.

## Known blockers and limitations

- A fully automated authenticated-browser test of manual edit/note persistence was not available in the final verification environment; persistence is implemented through live Supabase mutations and the schema is deployed.
- Broader person-specific research remains limited where public sources do not establish publications, patents or education for a person. The UI intentionally shows “not publicly verified.”
- No Git remote was configured in this worktree, so the commit could not be pushed from here.
- Existing unrelated working-tree modifications and generated outputs remain uncommitted; they are visible in `git status` and were not altered by the Contact 360 commit.

## Current task

The next safe step is to run an authenticated browser acceptance pass against `https://svak-intelligence.pages.dev`: open Vijayasarathi’s Contact 360, edit a title, add a note, refresh, sign out/in, and verify the records remain. Then enrich additional current contacts using the same normalized model and source/provenance rules.

## 2026-09-08 Contact 360 completeness update

- Added category-based research completeness calculation across identity, employment, career, education, person work, organisational work, problems, themes, activity, contactability, JTBD and source diversity.
- Added states `UNRESEARCHED`, `PARTIAL`, `RESEARCHED`, and `DEEP PROFILE`; role fit remains separate.
- Zero-source/zero-claim contacts now receive an explicit unresearched state and no generic person-level summary or JTBD.
- Executive summaries now use only person/account intelligence and omit implementation boilerplate.
- Source counters are clickable and filter the source register by inspected/used/rejected status.
- Latest research-run metrics are shown when available.
- Frontend tests: 23 passed; backend: 218 passed; integration: 14 passed; build and diff check passed.
- Current deployment after this update: `https://6d409199.svak-intelligence.pages.dev`; production alias remains `https://svak-intelligence.pages.dev`.

## Follow-up implementation status

- Latest completeness commit: `8e8c69d feat: enforce contact research completeness`.
- Zero-source Keisuke Inoue/Takeda verification: 0 contact sources and 0 verified claims; UI now renders `UNRESEARCHED` and suppresses person-level summary/JTBD.
- Vijayasarathi remains the researched acceptance profile; the summary is generated from role, claims, positions, works, problems, themes and JTBD rather than UI implementation text.
- `Refresh research` currently creates a durable `QUEUED` row and displays the latest run metrics. A backend worker that consumes this queue and performs person-level web research is still a remaining integration task; the existing daily crawler does not yet consume `contact_research_runs`.

## Source-driven contact enrichment update

- Added source states `DISCOVERED`, `QUEUED`, `FETCHING`, `INSPECTED`, `USED`, `REJECTED`, `BLOCKED_AUTH`, `FAILED`, and `PENDING_REVIEW`.
- Added source raw-content/extraction metadata and expanded research-run metrics.
- Add Source now accepts public URLs, pasted profile text, and TXT/Markdown/PDF file input. Public fetch failures for LinkedIn are recorded as `BLOCKED_AUTH`, never silently rejected.
- Supplied profile text is parsed into observed claims, positions, education, works, themes and bounded research keywords/queries; persisted records remain source-linked.
- Latest frontend tests: 25 passed; build passed. Latest production bundle: `assets/index-BRUkMYBC.js`, HTTP 200.
- The queue currently persists ingestion and research-run lifecycle data. Full autonomous supplementary web-search worker remains a later backend task.

## Manual profile ingestion update (2026-09-09)

- Add Source is now a visible workflow with source type, optional original URL, pasted profile text, and document upload.
- Submitted professional content is stored with raw content, source kind, description, content hash, extraction JSON and processing status.
- Profile facts are persisted as source-linked observed claims/positions/education/works/themes; generated queries are recorded in the research run.
- LinkedIn/public-profile fetch failures use `BLOCKED_AUTH`; `INSPECTED` is no longer the final disposition for processed supplied sources.
- Source register shows extraction counts and supports filtering blocked/pending/used/rejected states.
- Latest production deployment: `https://98f0b4ec.svak-intelligence.pages.dev`; alias `https://svak-intelligence.pages.dev`.

## Contact research worker update (2026-09-09)

- Added `src/impurity_leads/contact_research.py`, a backend-only, bounded worker that consumes `QUEUED` `contact_research_runs` rows after the daily crawl. It uses the generated profile keywords and executes deduplicated, capped public Europe PMC queries (maximum 20 queries and 5 results per query).
- Each discovered publication is identity-checked against the contact name. Sources finish as `USED`, `REJECTED`, or `FAILED`; rejection reasons and identity confidence are retained in `contact_sources`. Duplicate publication URLs are skipped within a run.
- High-confidence technical matches persist source-linked person-direct works and observed claims. Conservative inferred problems, themes, and JTBD hypotheses are only generated from explicit technical language in the matched source and remain provenance-linked.
- `contact_research_runs` now records rejected and failed source counts. The daily GitHub Actions crawler invokes the worker with the existing backend-only `SUPABASE_SECRET_KEY`; no privileged credential is exposed to the frontend.
- The Contact 360 Overview now displays query/source disposition and enrichment metrics, and the Sources tab supports source-type and terminal-status filters.
- Current limitation: this first worker stage has a Europe PMC adapter only. Official-company, patent, conference, regulatory, and broad-web adapters are not yet implemented; queued runs therefore provide bounded scientific-publication corroboration rather than exhaustive web research. Production execution requires the existing scheduled GitHub Actions job with its configured backend secret.
- Validation after the worker change: backend `223 passed`, integration `14 passed`, frontend `26 passed`, Vite build passed, and `git diff --check` passed. The tested build is deployed at `https://7404c2d6.svak-intelligence.pages.dev` and the production alias returned HTTP 200 for `/`, `/contacts`, and `/crawler` with asset `assets/index-mLWR4FjA.js`.

## Entity-resolution update (2026-09-09)

- Added explainable professional-person resolution with normalized aliases, initials and surname-initial compatibility. Candidate confidence combines name compatibility with employer, role/function and location context; outcomes are `CONFIRMED_MATCH`, `PROBABLE_MATCH`, `NEEDS_REVIEW`, or `REJECTED_MATCH`.
- Research queries now include bounded aliases such as full name, first-name plus surname initial, and first-name initial plus surname. A name-only match cannot confirm a common-name identity.
- A blocked LinkedIn URL can be supplied later with profile text while retaining the same canonical source URL. The transition is recorded in `contact_history`, and the supplied content is parsed into the existing Contact 360 model.
- Acceptance tests cover Vijayasarathi Ramaswami vs Vijayasarathi R with Cipla/Global Quality context and Jitendra Singh common-name collision protection.
- Contextual-resolution deployment: `https://ad29ba3e.svak-intelligence.pages.dev`; production alias serves `assets/index-YJ8Eo1QE.js` and returned HTTP 200 for `/` and `/contacts`.
- Alias correction: `name_variants` now emits `vijayasarathi ramaswami`, `vijayasarathi R`, `V Ramaswami`, and `V. Ramaswami`; redundant middle-initial combinations are suppressed. Full backend validation remains `226 passed`; integration remains `14 passed`; frontend remains `26 passed`.

## Professional profile workspace update (2026-09-09)

- Added a dedicated `Import professional profile` flow inside Contact 360 with equal PDF/TXT export upload, full-text paste, and structured form entry points.
- The parser now captures identity context, headline/about, current role, repeatable positions, education, certifications, projects/publications/patents, activity and explicit skills while filtering common LinkedIn navigation labels.
- Supplied content is retained in `contact_sources` with raw content, extraction JSON, content hash, provenance and terminal `USED`/`PENDING_REVIEW` state. Structured facts are written to the existing source-linked Contact Intelligence tables; accepted profile field changes are audited in `contact_history`.
- `Save profile only` persists immediate intelligence. `Save & research` additionally creates a durable `QUEUED` research run for the existing backend Contact Research Worker. No new crawler or schema was introduced.
- Date normalization prevents year-only profile dates from failing Postgres date columns. A regression test covers a messy full-profile export, duplicate UI headings and bounded query generation.
- Validation for this update: frontend `27 passed`, backend `226 passed`, integration `14 passed`, build passed, `git diff --check` passed. Production deployment is pending the final targeted commit.
- Known limitation: browser-level authenticated production mutation was not performed in this pass; the UI writes through the existing authenticated Supabase client and the backend worker remains asynchronous.
