import json
import os
from datetime import datetime, timezone

from impurity_leads.cli import main
from impurity_leads.config import load_settings
from impurity_leads.contact_repair import run_contact_repair
from impurity_leads.contact_rescore import run_contact_rescore
from impurity_leads.contact_research import run_pending_contact_research
from impurity_leads.targeted_research_jobs import run_pending_targeted_jobs
from impurity_leads.opportunity_enrichment import run_pending_opportunity_enrichment
from impurity_leads.opportunity_rescore import run_stale_opportunity_rescore
from impurity_leads.agent_github import export_ready_agent_jobs
from impurity_leads.execution.stages import run_post_crawl_stages
from impurity_leads.molecule_discovery import run_molecule_discovery
from impurity_leads.seed_sources import discover_missing_domains
from impurity_leads.zero_cost import ProviderUsage


if __name__ == "__main__":
    settings = load_settings()
    provider_usage = ProviderUsage()
    run_started = datetime.now(timezone.utc)
    # Find websites for qualified companies first, so today's crawl seeds them.
    try:
        discovery = discover_missing_domains(settings)
    except Exception as error:
        discovery = {"status": "FAILED", "error": str(error)[:240]}
    print(json.dumps({"event": "domain_discovery", **discovery}, default=str, sort_keys=True))
    exit_code = main(["run-daily"])

    def rescore_stage():
        # Rows this run re-qualified carry a newer last_qualified_at. A paused or
        # failed run has not published yet, so its pairs are left for next time.
        if exit_code != 0:
            return {"status": "SKIPPED", "reason": "daily_run_incomplete"}
        result = run_stale_opportunity_rescore(settings, qualified_before=run_started)
        result.pop("changes", None)
        return result

    def molecule_discovery_stage():
        # Off unless MOLECULE_DISCOVERY_ENABLED=true; returns SKIPPED otherwise.
        return run_molecule_discovery(settings, provider_usage=provider_usage)

    def contacts_ready():
        return bool(getattr(settings, "supabase_url", None) and getattr(settings, "supabase_secret_key", None))

    def contact_repair_stage():
        # Only AUTO_MERGE duplicates (same profile URL or public email) are merged.
        return run_contact_repair() if contacts_ready() else {"status": "SKIPPED", "reason": "supabase_credentials_missing"}

    def contact_rescore_stage():
        # Keeps role confidence and recency current as sources age.
        return run_contact_rescore() if contacts_ready() else {"status": "SKIPPED", "reason": "supabase_credentials_missing"}

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
        ("opportunity_rescore", rescore_stage),
        ("molecule_discovery", molecule_discovery_stage),
        ("contact_research", contact_stage),
        ("contact_repair", contact_repair_stage),
        ("contact_rescore", contact_rescore_stage),
        ("targeted_research", targeted_stage),
        ("opportunity_evidence_queue", opportunity_stage),
        ("agent_work_export", agent_stage),
    ])
    for stage in post_crawl.stages:
        print(json.dumps({"event": stage.name, "status": stage.status, "processed": stage.processed, "sources": stage.sources, "claims": stage.claims, "links": stage.links, "error": stage.error, "metrics": stage.metrics}, sort_keys=True))
    print(json.dumps({"event": "post_crawl_summary", "status": post_crawl.status, "stages": len(post_crawl.stages)}, sort_keys=True))
    print(json.dumps({"event": "provider_usage", "zero_cost_mode": settings.zero_cost_mode, "provider_usage": provider_usage.rows()}, sort_keys=True))
    raise SystemExit(exit_code)
