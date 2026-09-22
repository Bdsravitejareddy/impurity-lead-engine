# Provider cost policy

SVAK's production workflow sets `ZERO_COST_MODE=true`. In this mode the
deterministic crawler uses only public, structured or directly fetched sources:

- openFDA (`api.fda.gov`)
- ClinicalTrials.gov (`clinicaltrials.gov`)
- Europe PMC (`ebi.ac.uk/europepmc` and `europepmc.org`)
- Common Crawl index (`index.commoncrawl.org`)
- public company pages and public patents (`patents.google.com`)
- the private GitHub issue bus for human ChatGPT Work research

There is no Tavily, Serper, SerpAPI, Bing Search API, Google Custom Search API,
Gemini, Groq, or paid scraping dependency in this repository. Google Patents is
used as a public web source, not as a paid Google Search API.

The optional backend-only OpenAI Responses adapter is the only direct paid-capable
model path (`src/impurity_leads/ai_analysis.py`). It is disabled by default and
raises `paid_provider_disabled` before any request when zero-cost mode is active.
If evidence is unavailable, the existing staged ChatGPT Work job path is used;
the worker receives no Supabase credentials and writes no canonical data directly.

Each run records safe per-provider counters with `provider`, `requests`, `jobs`,
and `estimated_paid_requests`. Counters contain no URLs, prompts, credentials,
or response content.
