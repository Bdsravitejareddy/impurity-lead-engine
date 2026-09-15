# Live Supabase Data Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure production uses live Supabase data and surfaces explicit configuration/query failures instead of silently loading sanitized local data.

**Architecture:** `loadData()` will select local data only under an explicit `VITE_DATA_MODE=local`; otherwise it will require configured Supabase and propagate a safe data-source error. The app will render a visible error state and derive Settings values from the loaded live dataset. Existing Supabase queries, RLS, local fixtures, and canonical contact grouping remain unchanged.

**Tech Stack:** Vite, React, TypeScript, Supabase JS, Vitest.

**Spec:** Production data-source fix requested in the active task.

## Global Constraints

- Production must use LIVE SUPABASE ONLY.
- Local fallback is allowed only in explicit development/demo mode.
- Do not change schema, RLS, scoring thresholds, or production data.
- Preserve unrelated working-tree changes.

### Task 1: Adapter mode and visible error boundary

**Files:**
- Modify: `web/src/data/adapter.ts`
- Modify: `web/src/main.tsx`
- Modify: `web/src/data/supabase.ts` only if safe config metadata is needed
- Test: `web/src/data/adapter.test.ts`

- [ ] Add tests proving production config/query errors do not call local data and explicit local mode does.
- [ ] Implement explicit mode selection and safe error propagation.
- [ ] Render a visible data connection error with retry instead of an indefinite/loading or silent fallback state.

### Task 2: Live Settings and adapter coverage

**Files:**
- Modify: `web/src/main.tsx`
- Modify: `web/src/data/supabaseAdapter.ts` only if the smoke test identifies a missing UI-critical query.

- [ ] Derive Settings source, connection, refresh time, and counts from the loaded result.
- [ ] Keep canonical contacts and opportunity metrics from Supabase adapter output.

### Task 3: Production build and verification

**Files:**
- No source changes beyond Tasks 1–2.

- [ ] Run backend/frontend tests, build, diff check, and available typecheck/e2e scripts.
- [ ] Build with configured production Vite variables without committing env files.
- [ ] Run a read-only production adapter smoke test and deploy the verified build.
- [ ] Verify production routes/assets and report authentication limitations honestly.
