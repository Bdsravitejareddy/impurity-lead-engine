# ChatGPT Work automation

SVAK exports bounded research jobs as private GitHub issues. GitHub is only a
message bus: the backend validates and persists every result. ChatGPT Work
must never access Supabase, credentials, private data, or application code.

## One-time setup

Ravi only needs to do this once:

1. Connect the GitHub account that can read and comment on
   `Bdsravitejareddy/impurity-lead-engine` to ChatGPT Work.
2. Create a ChatGPT Work Scheduled Task that runs every hour using the prompt
   below.
3. Approve only the requested GitHub read/comment permissions.

After that, no prompt or JSON copy/paste is required for normal operation.
The Crawler / Research page keeps the manual prompt/result controls under the
fallback/debug path for recovery and testing.

## Scheduled Task prompt

```text
Every hour, use the connected GitHub account to inspect the repository
Bdsravitejareddy/impurity-lead-engine.

Find open issues labelled `svak-work-ready`, sorted by priority. Process at
most five issues in one run. For each issue, read the JSON between
SVAK_AGENT_JOB_START and SVAK_AGENT_JOB_END and perform only the bounded public
web research requested by its missing_dimensions. Prefer official company or
regulatory pages, scientific publications, patents, conferences, professional
associations, public PDFs, and reputable public professional pages. Search
engines may discover sources, but return the underlying source URLs.

Do not bypass authentication, CAPTCHA, paywalls, or access controls. Do not
guess hidden emails. If a source requires authentication, report it with
access_status BLOCKED_AUTH. Do not access Supabase, use credentials, modify
application code, run shell commands, or merge pull requests.

Do not process an issue that already contains a comment with both
SVAK_WORK_RESULT_START and SVAK_WORK_RESULT_END unless the issue explicitly
asks for a follow-up round.

Post exactly one result comment per processed issue. Put JSON only between:

<!-- SVAK_WORK_RESULT_START -->
{ ... }
<!-- SVAK_WORK_RESULT_END -->

The JSON must contain job_id, research_summary, people, sources,
missing_dimensions_resolved, remaining_unknowns, and recommended_next_queries.
Each source needs a public URL and access_status. Each claim must state
proposed_provenance OBSERVED or INFERRED and include source_urls when
OBSERVED. Use null or UNKNOWN for missing values. Never manufacture sources.

Stop after five jobs or when the Work execution budget becomes constrained.
```

## Result lifecycle

GitHub Actions receives marked comments, validates the JSON, stages it in
`agent_research_submissions`, validates source and identity context, and only
then writes canonical Contact 360 and graph records. Invalid or duplicate
comments are rejected safely. A successful result receives a machine-generated
validation comment and the issue is labelled `svak-work-applied` and closed;
unresolved work remains open with a follow-up label.
# Molecule intelligence jobs

The same private GitHub issue transport also carries `MOLECULE_INTELLIGENCE`
jobs. These jobs have `molecule_id` and no `opportunity_id`; the issue payload
contains the canonical molecule and only missing dimensions such as
`CLINICAL_SAFETY`, `TOXICOLOGY`, or `IMPURITY_RELEVANCE`. Return the
job-kind-aware molecule schema from `src/impurity_leads/agent_research.py`.

Molecule results enter the same staging table and deterministic validator as
contact results. A source-free `OBSERVED` claim is downgraded to `INFERRED`;
the Work response itself is never evidence. Accepted claims become
`research_claims` with `MOLECULE_CONTEXT` attribution and drive reusable
`molecule_intelligence_sections` for every company opportunity sharing that
molecule.
