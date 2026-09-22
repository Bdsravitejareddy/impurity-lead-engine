"""Idempotent opportunity-directed research queue and worker."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from impurity_leads.contact_quality import QualityConfig
from impurity_leads.research_adapters import classify_source
from impurity_leads.research_discovery import DiscoveryProvider, EuropePmcProvider
from impurity_leads.zero_cost import ProviderUsage
from impurity_leads.targeted_research import OpportunityCoverage, evaluate_opportunity_coverage, targeted_query_plan
from impurity_leads.person_discovery import affiliation_matches_company, candidate_identity_state, extract_authors, rank_candidate
from impurity_leads.contacts.normalize import normalize_person_name
from impurity_leads.agent_research import queue_agent_research_job
from impurity_leads.agent_research import queue_molecule_intelligence_job
from impurity_leads.molecule_intelligence import missing_molecule_dimensions


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


def _resolve_or_create_author(client: Any, candidate: Any, *, company_id: str | None, company_name: str, source_date: str | None, technical_text: str) -> tuple[dict[str, Any] | None, str, float]:
    """Reuse a canonical person or create a conservative technical candidate."""
    if not company_id or not affiliation_matches_company(candidate.affiliation, company_name):
        return None, "NEEDS_REVIEW", 45.0
    normalized = normalize_person_name(candidate.name)
    existing_rows = client.table("contacts").select("*").eq("company_id", company_id).execute().data or []
    existing = next((row for row in existing_rows if normalize_person_name(str(row.get("display_name") or "")) == normalized), None)
    if not existing:
        existing = next((row for row in existing_rows if candidate_identity_state(candidate, row, company_match=True)[0] == "SAME_PERSON"), None)
    state, confidence, _ = candidate_identity_state(candidate, existing, company_match=True)
    if state == "NEEDS_REVIEW":
        return None, state, confidence
    if existing:
        client.table("contacts").update({"contact_confidence": max(float(existing.get("contact_confidence") or 0), confidence), "technical_relevance": max(float(existing.get("technical_relevance") or 0), candidate.technical_relevance), "identity_reason": "technical publication affiliation plus canonical name context"}).eq("id", existing["id"]).execute()
        existing["contact_confidence"] = max(float(existing.get("contact_confidence") or 0), confidence)
        existing["technical_relevance"] = max(float(existing.get("technical_relevance") or 0), candidate.technical_relevance)
        return existing, state, confidence
    contact_id = str(uuid5(NAMESPACE_URL, f"svak:contact:{company_id}:{normalized}"))
    row = {
        "id": contact_id, "company_id": company_id, "normalized_name": normalized,
        "display_name": candidate.name, "title": "Technical author (historical)",
        "department": "Analytical / technical research", "contact_confidence": confidence,
        "technical_relevance": candidate.technical_relevance, "candidate_status": "TECHNICALLY_RELEVANT",
        "identity_reason": "name plus source-dated target-company affiliation; current employment unverified",
        "first_seen_at": _now(), "last_seen_at": _now(),
    }
    client.table("contacts").upsert(row, on_conflict="id").execute()
    return row, state, confidence


def _persist_author_source(client: Any, *, contact: dict[str, Any], item: dict[str, Any], result: Any, candidate: Any, opportunity_id: str) -> str | None:
    metadata = {"publication": {"title": item.get("title"), "pmid": item.get("pmid") or item.get("id"), "doi": item.get("doi") or item.get("doiId"), "journal": item.get("journalTitle")}, "author": {"name": candidate.name, "order": candidate.author_order, "corresponding": candidate.corresponding, "affiliation": candidate.affiliation}, "attribution": "PERSON_DIRECT", "employment": "HISTORICAL_SOURCE_DATED"}
    source_row = {"contact_id": contact["id"], "url": result.url, "title": str(item.get("title") or result.title)[:300], "publisher": "Europe PMC", "source_type": "Scientific publication", "source_date": candidate.source_date, "status": "USED", "evidence_strength": "PRIMARY", "why_used": "Named author with source-dated target-company affiliation.", "source_kind": "EXTERNAL_RESEARCH", "extraction_json": metadata}
    response = client.table("contact_sources").upsert(source_row, on_conflict="contact_id,url").select("id").execute()
    data = getattr(response, "data", None) or []
    source_id = data[0].get("id") if data else None
    claim = {"contact_id": contact["id"], "claim_type": "PUBLICATION_AUTHORED", "claim_text": f"{candidate.name} is named as an author of {item.get('title') or result.title}", "provenance": "OBSERVED", "confidence": 0.82, "source_ids": [source_id] if source_id else [], "opportunity_id": opportunity_id}
    client.table("contact_claims").insert(claim).execute()
    return source_id


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
            new_contacts = 0
            linked_contacts = 0
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
                metadata = item.metadata or {}
                for candidate in extract_authors(metadata, technical_text=f"{item.title} {item.snippet}"):
                    contact, identity_state, identity_confidence = _resolve_or_create_author(client, candidate, company_id=opportunity.get("company_id"), company_name=company, source_date=candidate.source_date, technical_text=item.snippet)
                    if not contact:
                        continue
                    if not any(str(row.get("id")) == str(contact.get("id")) for row in contacts):
                        contacts.append(contact); new_contacts += 1
                    source_id = _persist_author_source(client, contact=contact, item=metadata, result=item, candidate=candidate, opportunity_id=str(opportunity.get("id")))
                    if source_id:
                        client.table("contact_works").insert({"contact_id": contact["id"], "work_type": "PUBLICATION", "title": str(metadata.get("title") or item.title)[:300], "work_date": candidate.source_date, "person_role": "Named publication author", "company_context": company, "topic": item.snippet[:500], "technical_themes": ["impurity" if "impurity" in item.snippet.casefold() else "analytical"], "attribution": "PERSON_DIRECT", "confidence": 0.82, "source_ids": [source_id]}).execute()
                        rank = rank_candidate(candidate, company_match=True)
                        client.table("opportunity_contacts").upsert({"opportunity_id": opportunity["id"], "contact_id": contact["id"], "role_fit_score": rank, "rank": 1, "rationale": "PUBLICATION_AUTHOR; source-dated target-company affiliation; current role unverified"}, on_conflict="opportunity_id,contact_id").execute()
                        linked_contacts += 1
            result = {"status": "COMPLETED", "stop_reason": "NO_NEW_EVIDENCE" if not accepted else "MAX_ROUNDS", "sources": len(found), "claims": accepted, "relationships": accepted, "new_contacts": new_contacts, "linked_contacts": linked_contacts}
        except Exception as exc:
            result = {"status": "PARTIAL", "stop_reason": "PROVIDER_ERROR", "sources": 0, "claims": 0, "relationships": 0, "error": type(exc).__name__}
    if job_id:
        client.table("targeted_research_jobs").update({"status": result["status"], "completed_at": _now(), "metrics": result, "stop_reason": result["stop_reason"]}).eq("id", job_id).execute()
    # Deterministic research remains the first line.  When it stops without
    # satisfying coverage, hand only the unresolved dimensions to the human
    # ChatGPT Work bridge; never create a Work job for a qualified opportunity.
    final_coverage = evaluate_opportunity_coverage(opportunity, contacts, config=config)
    if final_coverage.coverage_status != "QUALIFIED" and result.get("stop_reason") in {"NO_NEW_EVIDENCE", "DIMINISHING_RETURNS", "MAX_ROUNDS", "PROVIDER_ERROR"}:
        agent_job = queue_agent_research_job(
            client,
            targeted_job=job,
            opportunity=opportunity,
            missing_dimensions=final_coverage.missing_dimensions,
            quality_before={"best_contact_score": final_coverage.best_contact_score, "coverage_status": final_coverage.coverage_status, "identity_coverage": final_coverage.identity_coverage, "technical_coverage": final_coverage.technical_relevance_coverage},
            known_entities={"company": opportunity.get("company_name") or opportunity.get("company"), "molecule": opportunity.get("molecule_name") or opportunity.get("molecule"), "opportunity_score": opportunity.get("score")},
            priority=int(opportunity.get("score") or job.get("priority") or 0),
            stop_reason=result.get("stop_reason"),
        )
        result["agent_research_job_id"] = agent_job.get("id") if agent_job else None
        result["agent_research_status"] = agent_job.get("status") if agent_job else None
    return result


def run_pending_targeted_jobs(settings: Any, *, limit: int = 10, provider: DiscoveryProvider | None = None, provider_usage: ProviderUsage | None = None) -> dict[str, Any]:
    """Consume queued opportunity jobs with the existing backend secret path."""
    if not getattr(settings, "supabase_url", None) or not getattr(settings, "supabase_secret_key", None):
        return {"status": "SKIPPED", "reason": "supabase_credentials_missing", "processed": 0}
    from supabase import create_client
    from impurity_leads.contact_research import _get_json
    client = create_client(settings.supabase_url, settings.supabase_secret_key)
    provider = provider or EuropePmcProvider(_get_json)
    contact_jobs_queued = 0
    # Re-evaluate high-priority opportunities before consuming the queue. The
    # crawler may refresh contacts without creating a targeted job; contact
    # research must remain independent of molecule intelligence.
    try:
        opportunities = client.table("opportunities").select("*").in_("priority", ["HOT", "HIGH"]).order("score", desc=True).limit(50).execute().data or []
        contacts = client.table("contacts").select("*").execute().data or []
        for opportunity in opportunities:
            if contact_jobs_queued >= 5:
                break
            if opportunity.get("company_id"):
                company_rows = client.table("companies").select("legal_name,normalized_name").eq("id", opportunity["company_id"]).limit(1).execute().data or []
                if company_rows:
                    opportunity["company_name"] = company_rows[0].get("legal_name") or company_rows[0].get("normalized_name")
            if opportunity.get("molecule_id"):
                molecule_rows = client.table("molecules").select("canonical_name").eq("id", opportunity["molecule_id"]).limit(1).execute().data or []
                if molecule_rows:
                    opportunity["molecule_name"] = molecule_rows[0].get("canonical_name")
            # Coverage is opportunity-specific. Never let an unrelated
            # company contact suppress research for this opportunity.
            links = client.table("opportunity_contacts").select("contact_id").eq("opportunity_id", opportunity.get("id")).execute().data or []
            linked_ids = {str(row.get("contact_id")) for row in links if row.get("contact_id")}
            opportunity_contacts = [row for row in contacts if str(row.get("id")) in linked_ids]
            queued = queue_for_opportunity(client, opportunity, opportunity_contacts)
            contact_jobs_queued += int(queued.get("queued") or 0)
    except Exception:
        # Recovery must not prevent already-queued jobs from being processed.
        pass
    try:
        jobs = client.table("targeted_research_jobs").select("*").eq("status", "QUEUED").order("priority", desc=True).limit(limit).execute().data or []
    except Exception:
        return {"status": "SKIPPED", "reason": "targeted_jobs_table_unavailable", "processed": 0}
    result = {"status": "COMPLETED", "processed": 0, "sources": 0, "claims": 0, "relationships": 0, "stop_reasons": {}, "contact_jobs_queued": contact_jobs_queued, "molecule_jobs_queued": 0}
    for job in jobs:
        opportunity_rows = client.table("opportunities").select("*").eq("id", job["opportunity_id"]).limit(1).execute().data or []
        if not opportunity_rows:
            client.table("targeted_research_jobs").update({"status": "FAILED", "completed_at": _now(), "stop_reason": "OPPORTUNITY_NOT_FOUND"}).eq("id", job["id"]).execute()
            continue
        opportunity = opportunity_rows[0]
        if opportunity.get("company_id"):
            company_rows = client.table("companies").select("legal_name,normalized_name").eq("id", opportunity["company_id"]).limit(1).execute().data or []
            if company_rows: opportunity["company_name"] = company_rows[0].get("legal_name") or company_rows[0].get("normalized_name")
        if opportunity.get("molecule_id"):
            molecule_rows = client.table("molecules").select("canonical_name").eq("id", opportunity["molecule_id"]).limit(1).execute().data or []
            if molecule_rows: opportunity["molecule_name"] = molecule_rows[0].get("canonical_name")
        contacts = client.table("contacts").select("*").execute().data or []
        metrics = process_targeted_job(client, job, opportunity, contacts, provider)
        if provider_usage is not None:
            provider_usage.record(getattr(provider, "name", "public_research"), requests=1, jobs=1)
        result["processed"] += 1
        result["sources"] += metrics.get("sources", 0)
        result["claims"] += metrics.get("claims", 0)
        result["relationships"] += metrics.get("relationships", 0)
        result["stop_reasons"][metrics.get("stop_reason", "UNKNOWN")] = result["stop_reasons"].get(metrics.get("stop_reason", "UNKNOWN"), 0) + 1
    # Molecule intelligence is canonical across companies. Queue at most one
    # bounded Work job per distinct molecule attached to a high-value
    # opportunity, and only for unsupported sections.
    try:
        high_value = client.table("opportunities").select("id,molecule_id,score,priority").in_("priority", ["HOT", "HIGH"]).order("score", desc=True).limit(20).execute().data or []
        seen_molecules: set[str] = set()
        for opportunity in high_value:
            molecule_id = str(opportunity.get("molecule_id") or "")
            if not molecule_id or molecule_id in seen_molecules:
                continue
            seen_molecules.add(molecule_id)
            molecule_rows = client.table("molecules").select("id,canonical_name").eq("id", molecule_id).limit(1).execute().data or []
            if not molecule_rows:
                continue
            sections = client.table("molecule_intelligence_sections").select("section_type,evidence_status").eq("molecule_id", molecule_id).execute().data or []
            dimensions = missing_molecule_dimensions(sections)
            if dimensions:
                job = queue_molecule_intelligence_job(client, molecule=molecule_rows[0], missing_dimensions=dimensions, quality_before={"sections_supported": len(sections)}, priority=int(opportunity.get("score") or 0))
                result["molecule_jobs_queued"] += 1 if job else 0
    except Exception:
        # Older deployments without the additive molecule table continue with
        # deterministic contact/opportunity research unchanged.
        pass
    return result
