# Contact Intelligence Workspace Implementation Plan

**Goal:** Turn `/contacts/:contactId` into a persistent, evidence-backed Contact 360 workspace with normalized Supabase intelligence, manual notes, audit history, and a richer responsive UI.

**Architecture:** Add additive, RLS-protected normalized contact-intelligence tables. Extend the Supabase adapter with a batched per-contact intelligence query and mutation helpers. Render tabbed Contact 360 sections from a normalized model, with manual writes and research queueing through Supabase; preserve the existing local fallback and lead/scoring architecture.

**Tech Stack:** React/TypeScript/Vite, Supabase JS, PostgreSQL migration, Vitest.

**Global Constraints:** No scoring/classifier/crawler changes; no privileged browser credentials; preserve historical evidence; label observed/inferred/unknown; keep manual intelligence persistent and audit-able; do not weaken anonymous access.

### Task 1: Add normalized Supabase model and RLS
- Create migration for sources, positions, education, works, problems, themes, JTBD, claims, notes, history, conflicts, research runs.
- Enable RLS and authenticated-only policies; keep service-role backend access.
- Add seed data for Vijayasarathi via reviewed public sources.
- Run security advisors.

### Task 2: Extend data adapter and mutation helpers
- Add TypeScript normalized intelligence types.
- Query new tables in parallel for loaded contacts.
- Deduplicate sources and map claim provenance.
- Add helpers for profile updates, notes, intelligence rows, source submission, refresh queue.

### Task 3: Build Contact 360 workspace UI
- Add tab navigation and sections for all requested domains.
- Render observed/inferred/unknown badges, source coverage, person/company attribution, empty states, related opportunities, outreach briefing.
- Add edit/add intelligence/add source/refresh controls and persistence feedback.

### Task 4: Seed Vijayasarathi gold-standard profile
- Insert reviewed source register, current role, organization context, themes, problems, JTBD, claims, and research status through Supabase.
- Avoid unsupported person-specific work and education claims.

### Task 5: Tests, build, deployment, verification
- Add tests for normalization, source dedupe, attribution, missing sections, manual persistence helpers, conflict/history rendering, routing.
- Run frontend/backend/integration tests, build, diff check, advisors, deploy Cloudflare, verify routes and production bundle.
