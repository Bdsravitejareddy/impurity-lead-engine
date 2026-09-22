import json
import os

from impurity_leads.cli import main
from impurity_leads.config import load_settings
from impurity_leads.contact_research import run_pending_contact_research
from impurity_leads.targeted_research_jobs import run_pending_targeted_jobs
from impurity_leads.opportunity_enrichment import run_pending_opportunity_enrichment
from impurity_leads.agent_github import export_ready_agent_jobs
from impurity_leads.zero_cost import ProviderUsage


if __name__ == "__main__":
    settings = load_settings()
    provider_usage = ProviderUsage()
    exit_code = main(["run-daily"])
    # Contact research is a bounded post-crawl stage. It uses the same
    # backend-only Supabase credentials and never exposes them to the UI.
    try:
        result = run_pending_contact_research(settings, limit=10, provider_usage=provider_usage)
        print(json.dumps({"event": "contact_research", **result}, sort_keys=True))
    except Exception as exc:
        # A research outage must not invalidate the completed lead crawl, but
        # it must remain visible in the Actions log for diagnosis/retry.
        print(json.dumps({"event": "contact_research_failed", "error": type(exc).__name__}, sort_keys=True))
    try:
        result = run_pending_targeted_jobs(settings, limit=10, provider_usage=provider_usage)
        print(json.dumps({"event": "targeted_research", **result}, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"event": "targeted_research_failed", "error": type(exc).__name__, "message": str(exc)[:240]}, sort_keys=True))
    try:
        result = run_pending_opportunity_enrichment(settings, limit=2)
        print(json.dumps({"event": "opportunity_evidence_queue", **result}, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"event": "opportunity_evidence_queue_failed", "error": type(exc).__name__}, sort_keys=True))
    try:
        if getattr(settings, "supabase_url", None) and getattr(settings, "supabase_secret_key", None) and os.environ.get("GITHUB_REPOSITORY"):
            from supabase import create_client
            client = create_client(settings.supabase_url, settings.supabase_secret_key)
            result = export_ready_agent_jobs(client, repo=os.environ["GITHUB_REPOSITORY"], limit=5, provider_usage=provider_usage)
            print(json.dumps({"event": "agent_work_export", **result}, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"event": "agent_work_export_failed", "error": type(exc).__name__}, sort_keys=True))
    print(json.dumps({"event": "provider_usage", "zero_cost_mode": settings.zero_cost_mode, "provider_usage": provider_usage.rows()}, sort_keys=True))
    raise SystemExit(exit_code)
