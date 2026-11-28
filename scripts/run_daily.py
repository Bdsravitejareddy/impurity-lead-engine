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
from impurity_leads.hunter import run_hunter_people, run_pattern_fallback
from impurity_leads.contact_cleanup import run_contact_cleanup
from impurity_leads.tenders import run_tender_alerts
from impurity_leads.outcomes import pipeline_outcome_report
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

    def outcomes_stage():
        # Conversion by priority from the shared pipeline: the check that scores work.
        if not contacts_ready():
            return {"status": "SKIPPED", "reason": "supabase_credentials_missing"}
        from supabase import create_client
        return pipeline_outcome_report(create_client(settings.supabase_url, settings.supabase_secret_key))

    def hunter_stage():
        # Off unless HUNTER_API_KEY is set; see impurity_leads.hunter.
        if not (contacts_ready() and os.environ.get("HUNTER_API_KEY")):
            return {"status": "SKIPPED", "reason": "hunter_api_key_not_set"}
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_secret_key)
        return run_hunter_people(settings, client)

    def tender_alerts_stage():
        # Off unless the GeM alert inbox is configured; see impurity_leads.tenders.
        if not (contacts_ready() and os.environ.get("GEM_ALERT_IMAP_USER")):
            return {"status": "SKIPPED", "reason": "gem_alert_inbox_not_configured"}
        from supabase import create_client
        return run_tender_alerts(create_client(settings.supabase_url, settings.supabase_secret_key))

    def contact_cleanup_stage():
        if not contacts_ready():
            return {"status": "SKIPPED", "reason": "supabase_credentials_missing"}
        from supabase import create_client
        return run_contact_cleanup(create_client(settings.supabase_url, settings.supabase_secret_key))

    def pattern_fallback_stage():
        # Free fallback: named contacts without an address get one from the
        # company's email pattern (public pages first, else Hunter's).
        if not contacts_ready():
            return {"status": "SKIPPED", "reason": "supabase_credentials_missing"}
        from supabase import create_client
        return run_pattern_fallback(create_client(settings.supabase_url, settings.supabase_secret_key))

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
        ("contact_cleanup", contact_cleanup_stage),
        ("hunter_people", hunter_stage),
        ("email_pattern_fallback", pattern_fallback_stage),
        ("contact_rescore", contact_rescore_stage),
        ("targeted_research", targeted_stage),
        ("opportunity_evidence_queue", opportunity_stage),
        ("agent_work_export", agent_stage),
        ("pipeline_outcomes", outcomes_stage),
        ("gem_tender_alerts", tender_alerts_stage),
    ])
    for stage in post_crawl.stages:
        print(json.dumps({"event": stage.name, "status": stage.status, "processed": stage.processed, "sources": stage.sources, "claims": stage.claims, "links": stage.links, "error": stage.error, "metrics": stage.metrics}, sort_keys=True))
    print(json.dumps({"event": "post_crawl_summary", "status": post_crawl.status, "stages": len(post_crawl.stages)}, sort_keys=True))
    print(json.dumps({"event": "provider_usage", "zero_cost_mode": settings.zero_cost_mode, "provider_usage": provider_usage.rows()}, sort_keys=True))
    raise SystemExit(exit_code)
