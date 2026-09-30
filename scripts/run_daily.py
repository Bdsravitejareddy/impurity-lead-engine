import json
import os

from impurity_leads.cli import main
from impurity_leads.config import load_settings
from impurity_leads.contact_research import run_pending_contact_research
from impurity_leads.targeted_research_jobs import run_pending_targeted_jobs
from impurity_leads.opportunity_enrichment import run_pending_opportunity_enrichment
from impurity_leads.agent_github import export_ready_agent_jobs
from impurity_leads.execution.stages import run_post_crawl_stages
from impurity_leads.zero_cost import ProviderUsage


if __name__ == "__main__":
    settings = load_settings()
    provider_usage = ProviderUsage()
    exit_code = main(["run-daily"])
    def contact_stage():
        return run_pending_contact_research(settings, limit=10, provider_usage=provider_usage)

    def targeted_stage():
        return run_pending_targeted_jobs(settings, limit=10, provider_usage=provider_usage)

    def opportunity_stage():
        return run_pending_opportunity_enrichment(settings, limit=2)

    def agent_stage():
        if not (getattr(settings, "supabase_url", None) and getattr(settings, "supabase_secret_key", None) and os.environ.get("GITHUB_REPOSITORY")):
            return {"status": "SKIPPED", "reason": "agent_export_credentials_or_repository_missing"}
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_secret_key)
        return export_ready_agent_jobs(client, repo=os.environ["GITHUB_REPOSITORY"], limit=5, provider_usage=provider_usage)

    post_crawl = run_post_crawl_stages([
        ("contact_research", contact_stage),
        ("targeted_research", targeted_stage),
        ("opportunity_evidence_queue", opportunity_stage),
        ("agent_work_export", agent_stage),
    ])
    for stage in post_crawl.stages:
        print(json.dumps({"event": stage.name, "status": stage.status, "processed": stage.processed, "sources": stage.sources, "claims": stage.claims, "links": stage.links, "error": stage.error, "metrics": stage.metrics}, sort_keys=True))
    print(json.dumps({"event": "post_crawl_summary", "status": post_crawl.status, "stages": len(post_crawl.stages)}, sort_keys=True))
    print(json.dumps({"event": "provider_usage", "zero_cost_mode": settings.zero_cost_mode, "provider_usage": provider_usage.rows()}, sort_keys=True))
    raise SystemExit(exit_code)
