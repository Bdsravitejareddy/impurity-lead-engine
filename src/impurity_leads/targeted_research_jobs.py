"""Idempotent opportunity-directed research queue and worker."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from impurity_leads.contact_quality import QualityConfig
from impurity_leads.research_adapters import classify_source
from impurity_leads.research_discovery import DiscoveryProvider, EuropePmcProvider
from impurity_leads.targeted_research import OpportunityCoverage, evaluate_opportunity_coverage, targeted_query_plan


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_targeted_job(client: Any, *, opportunity_id: str, missing_dimension: str, search_intent: str, priority: int = 0, contact_id: str | None = None, max_rounds: int = 2) -> dict[str, Any]:
    """Queue one active job per opportunity/dimension, safely retryable."""
    row = {
        "opportunity_id": opportunity_id, "contact_id": contact_id,
        "missing_dimension": missing_dimension, "search_intent": search_intent,
        "priority": priority, "max_rounds": max_rounds, "status": "QUEUED",
        "metadata": {"created_by": "quality_gate"},
    }
    try:
        response = client.table("targeted_research_jobs").upsert(row, on_conflict="opportunity_id,missing_dimension,active_key").execute()
        data = getattr(response, "data", None) or []
        return data[0] if data else row
    except Exception:
        # A legacy client/table can still report whether an active job exists;
        # callers can retry after migration without creating duplicates.
        existing = client.table("targeted_research_jobs").select("*").eq("opportunity_id", opportunity_id).eq("missing_dimension", missing_dimension).eq("status", "QUEUED").limit(1).execute()
        data = getattr(existing, "data", None) or []
        return data[0] if data else row


def queue_for_opportunity(client: Any, opportunity: dict[str, Any], contacts: list[dict[str, Any]], *, config: QualityConfig = QualityConfig()) -> dict[str, Any]:
    coverage = evaluate_opportunity_coverage(opportunity, contacts, config=config)
    if coverage.coverage_status == "QUALIFIED":
        return {"coverage": coverage, "queued": 0, "status": "QUALIFIED"}
    plans = targeted_query_plan(opportunity, coverage, max_queries=1)
    if not plans:
        return {"coverage": coverage, "queued": 0, "status": "EXHAUSTED"}
    plan = plans[0]
    high_value = float(opportunity.get("score") or 0) >= config.deep_research_opportunity_threshold
    queue_targeted_job(client, opportunity_id=str(opportunity.get("id")), missing_dimension=plan.target_dimension, search_intent=plan.query, priority=int(opportunity.get("score") or 0), max_rounds=5 if high_value else 2)
    return {"coverage": coverage, "queued": 1, "status": "TARGETED_SEARCH", "request": plan}


def _upsert_entity(client: Any, entity_type: str, name: str, metadata: dict[str, Any] | None = None) -> str | None:
    if not name:
        return None
    normalized = " ".join(str(name).casefold().split())
    response = client.table("research_entities").upsert({"entity_type": entity_type, "canonical_name": name[:500], "normalized_name": normalized, "metadata_json": metadata or {}}, on_conflict="entity_type,normalized_name").execute()
    data = getattr(response, "data", None) or []
    if data:
        return data[0].get("id")
    lookup = client.table("research_entities").select("id").eq("entity_type", entity_type).eq("normalized_name", normalized).limit(1).execute()
    data = getattr(lookup, "data", None) or []
    return data[0].get("id") if data else None


def process_targeted_job(client: Any, job: dict[str, Any], opportunity: dict[str, Any], contacts: list[dict[str, Any]], provider: DiscoveryProvider, *, config: QualityConfig = QualityConfig()) -> dict[str, Any]:
    """Process one bounded job; source URLs and graph claims are durable."""
    job_id = job.get("id")
    if job_id:
        client.table("targeted_research_jobs").update({"status": "RUNNING", "started_at": _now()}).eq("id", job_id).execute()
    coverage = evaluate_opportunity_coverage(opportunity, contacts, config=config)
    requests = targeted_query_plan(opportunity, coverage, max_queries=1)
    if not requests:
        result = {"status": "COMPLETED", "stop_reason": "NO_SEARCHABLE_DIMENSION", "sources": 0, "claims": 0, "relationships": 0}
    else:
        request = requests[0]
        try:
            found = provider.discover(request)
            accepted = 0
            company = str(opportunity.get("company_name") or opportunity.get("company") or "")
            molecule = str(opportunity.get("molecule_name") or opportunity.get("molecule") or "")
            company_id = _upsert_entity(client, "COMPANY", company)
            molecule_id = _upsert_entity(client, "MOLECULE", molecule)
            for item in found:
                source_class, source_type = classify_source(item.url, item.source_type)
                publication_id = _upsert_entity(client, "PUBLICATION", item.title, {"url": item.url, "source_class": source_class})
                if publication_id:
                    accepted += 1
                    if company_id:
                        client.table("research_relationships").upsert({"from_entity_id": company_id, "to_entity_id": publication_id, "relationship_type": "ASSOCIATED_WITH", "source_ids": [], "confidence": 0.55, "provenance": "INFERRED"}, on_conflict="from_entity_id,to_entity_id,relationship_type").execute()
                    if molecule_id:
                        client.table("research_relationships").upsert({"from_entity_id": publication_id, "to_entity_id": molecule_id, "relationship_type": "DISCUSSES", "source_ids": [], "confidence": 0.62, "provenance": "OBSERVED"}, on_conflict="from_entity_id,to_entity_id,relationship_type").execute()
                    client.table("research_claims").insert({"entity_id": publication_id, "claim_text": item.snippet or f"Public source discovered for {company} {molecule}", "source_url": item.url, "source_class": source_class if source_class in {"PRIMARY", "STRONG_PROFESSIONAL", "DIRECTORY", "DISCOVERY_WEAK"} else "DISCOVERY_WEAK", "attribution": "OPPORTUNITY_CONTEXT", "provenance": "OBSERVED", "support_text": item.snippet[:500], "confidence": 0.55}).execute()
            result = {"status": "COMPLETED", "stop_reason": "NO_NEW_EVIDENCE" if not accepted else "MAX_ROUNDS", "sources": len(found), "claims": accepted, "relationships": accepted}
        except Exception as exc:
            result = {"status": "PARTIAL", "stop_reason": "PROVIDER_ERROR", "sources": 0, "claims": 0, "relationships": 0, "error": type(exc).__name__}
    if job_id:
        client.table("targeted_research_jobs").update({"status": result["status"], "completed_at": _now(), "metrics": result, "stop_reason": result["stop_reason"]}).eq("id", job_id).execute()
    return result


def run_pending_targeted_jobs(settings: Any, *, limit: int = 10, provider: DiscoveryProvider | None = None) -> dict[str, Any]:
    """Consume queued opportunity jobs with the existing backend secret path."""
    if not getattr(settings, "supabase_url", None) or not getattr(settings, "supabase_secret_key", None):
        return {"status": "SKIPPED", "reason": "supabase_credentials_missing", "processed": 0}
    from supabase import create_client
    from impurity_leads.contact_research import _get_json
    client = create_client(settings.supabase_url, settings.supabase_secret_key)
    provider = provider or EuropePmcProvider(_get_json)
    try:
        jobs = client.table("targeted_research_jobs").select("*").eq("status", "QUEUED").order("priority", desc=True).limit(limit).execute().data or []
    except Exception:
        return {"status": "SKIPPED", "reason": "targeted_jobs_table_unavailable", "processed": 0}
    result = {"status": "COMPLETED", "processed": 0, "sources": 0, "claims": 0, "relationships": 0, "stop_reasons": {}}
    for job in jobs:
        opportunity_rows = client.table("opportunities").select("*").eq("id", job["opportunity_id"]).limit(1).execute().data or []
        if not opportunity_rows:
            client.table("targeted_research_jobs").update({"status": "FAILED", "completed_at": _now(), "stop_reason": "OPPORTUNITY_NOT_FOUND"}).eq("id", job["id"]).execute()
            continue
        opportunity = opportunity_rows[0]
        if opportunity.get("company_id"):
            company_rows = client.table("companies").select("name").eq("id", opportunity["company_id"]).limit(1).execute().data or []
            if company_rows: opportunity["company_name"] = company_rows[0].get("name")
        if opportunity.get("molecule_id"):
            molecule_rows = client.table("molecules").select("name").eq("id", opportunity["molecule_id"]).limit(1).execute().data or []
            if molecule_rows: opportunity["molecule_name"] = molecule_rows[0].get("name")
        contacts = client.table("contacts").select("*").execute().data or []
        metrics = process_targeted_job(client, job, opportunity, contacts, provider)
        result["processed"] += 1
        result["sources"] += metrics.get("sources", 0)
        result["claims"] += metrics.get("claims", 0)
        result["relationships"] += metrics.get("relationships", 0)
        result["stop_reasons"][metrics.get("stop_reason", "UNKNOWN")] = result["stop_reasons"].get(metrics.get("stop_reason", "UNKNOWN"), 0) + 1
    return result
