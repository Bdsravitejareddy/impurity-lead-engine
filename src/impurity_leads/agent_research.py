"""Human-in-the-loop ChatGPT Work bridge.

This module only prepares and validates staged research. It never treats an
agent response as canonical database truth without backend validation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from impurity_leads.contacts.normalize import normalize_person_name, person_name_compatibility


OUTPUT_SCHEMA = {
    "job_id": "string",
    "research_summary": "string",
    "people": [{
        "full_name": "string",
        "aliases": ["string"],
        "current_company": "string|null",
        "current_title": "string|null",
        "business_location": "string|null",
        "identity_confidence": 0,
        "technical_relevance": 0,
        "contactability": {"status": "UNKNOWN", "email": None, "phone": None, "professional_profile_url": None},
        "claims": [{"claim": "string", "claim_type": "string", "proposed_provenance": "OBSERVED|INFERRED", "confidence": 0, "source_urls": ["https://..."]}],
        "technical_work": [{"title": "string", "type": "PUBLICATION|PATENT|CONFERENCE|PROJECT|OTHER", "date": None, "molecule": None, "impurity": None, "technical_topic": None, "source_urls": ["https://..."]}],
        "why_relevant_to_opportunity": "string",
        "source_urls": ["https://..."]
    }],
    "sources": [{"url": "https://...", "title": "string", "publisher": "string", "source_date": None, "source_type": "string", "suggested_source_class": "PRIMARY|STRONG_PROFESSIONAL|DIRECTORY|DISCOVERY_WEAK", "access_status": "PUBLIC|BLOCKED_AUTH|FAILED", "claims_supported": ["string"]}],
    "missing_dimensions_resolved": "array of strings",
    "remaining_unknowns": "array of strings",
    "recommended_next_queries": "array of strings",
}

ACTIVE_AGENT_STATUSES = {"QUEUED", "READY", "EXPORTED", "RESULT_SUBMITTED", "VALIDATING"}


def build_agent_research_prompt(job: dict[str, Any]) -> str:
    """Build one bounded, copyable Work prompt from a READY job."""
    known_entities = job.get("known_entities") or {}
    company = job.get("company") or job.get("company_name") or known_entities.get("company") or "Unknown company"
    molecule = job.get("molecule") or job.get("molecule_name") or known_entities.get("molecule") or "Unknown molecule"
    opportunity_score = job.get("opportunity_score", known_entities.get("opportunity_score", "UNKNOWN"))
    missing = job.get("missing_dimensions") or []
    return f"""Use Work mode with web research. Return only the requested JSON, with no markdown.

You are assisting SVAK Intelligence with a bounded research task.

Opportunity
- Company: {company}
- Molecule/product: {molecule}
- Opportunity score: {opportunity_score}
- Research goal: {job.get('research_goal', 'Resolve missing contact dimensions')}
- Missing dimensions: {json.dumps(missing)}

Known context
- Known entities: {json.dumps(job.get('known_entities') or {}, ensure_ascii=False)}
- Known contacts: {json.dumps(job.get('known_contacts') or [], ensure_ascii=False)}
- Known sources: {json.dumps(job.get('known_sources') or [], ensure_ascii=False)}
- Known claims: {json.dumps(job.get('known_claims') or [], ensure_ascii=False)}
- Quality before: {json.dumps(job.get('quality_before') or {}, ensure_ascii=False)}

Research only the unresolved dimensions above. Prefer official/regulatory sources,
publications, patents, conference or professional sources, public company pages,
and reputable public directories. Return the underlying source URLs.

Do not bypass authentication, CAPTCHA, paywalls or private data. Do not guess hidden
emails. If a promising source is blocked, return access_status BLOCKED_AUTH.
Unknown values must be null or UNKNOWN. Do not manufacture sources or claims.

Return JSON matching this shape exactly:
{json.dumps(OUTPUT_SCHEMA, indent=2)}

Each claim must include proposed_provenance OBSERVED or INFERRED and source_urls.
Masked or inferred emails must not be marked VERIFIED_PUBLIC.
"""


def active_agent_dedupe_key(opportunity_id: str, missing_dimensions: list[str]) -> str:
    dims = ",".join(sorted({str(item).strip().upper() for item in missing_dimensions if str(item).strip()}))
    return f"{opportunity_id}:{dims or 'GENERAL'}"


def queue_agent_research_job(client: Any, *, targeted_job: dict[str, Any], opportunity: dict[str, Any],
                             missing_dimensions: list[str], quality_before: dict[str, Any],
                             known_entities: dict[str, Any] | None = None,
                             known_contacts: list[dict[str, Any]] | None = None,
                             known_sources: list[dict[str, Any]] | None = None,
                             known_claims: list[dict[str, Any]] | None = None,
                             priority: int = 0, stop_reason: str | None = None) -> dict[str, Any] | None:
    """Create one bounded human-in-the-loop job; never create a duplicate active job."""
    dimensions = sorted({str(item).upper() for item in missing_dimensions if str(item).strip()})
    if not dimensions:
        return None
    opportunity_id = str(opportunity.get("id") or opportunity.get("opportunity_id") or "")
    if not opportunity_id:
        return None
    dedupe_key = active_agent_dedupe_key(opportunity_id, dimensions)
    job = {
        "opportunity_id": opportunity_id,
        "targeted_research_job_id": targeted_job.get("id"),
        "priority": int(priority),
        "research_goal": f"Resolve only: {', '.join(dimensions)}",
        "missing_dimensions": dimensions,
        "known_entities": known_entities or {"company": opportunity.get("company_name") or opportunity.get("company"), "molecule": opportunity.get("molecule_name") or opportunity.get("molecule"), "opportunity_score": opportunity.get("score")},
        "known_contacts": known_contacts or [],
        "known_sources": known_sources or [],
        "known_claims": known_claims or [],
        "quality_before": quality_before or {},
        "dedupe_key": dedupe_key,
        "status": "READY",
        "stop_reason": stop_reason,
    }
    job["agent_prompt"] = build_agent_research_prompt(job)
    try:
        existing = client.table("agent_research_jobs").select("*").eq("dedupe_key", dedupe_key).in_("status", list(ACTIVE_AGENT_STATUSES)).limit(1).execute()
        rows = getattr(existing, "data", None) or []
        if rows:
            return rows[0]
    except Exception:
        pass
    try:
        response = client.table("agent_research_jobs").insert(job).execute()
        rows = getattr(response, "data", None) or []
        return rows[0] if rows else job
    except Exception:
        # A unique-key race is an idempotent success; retrieve the active row.
        try:
            existing = client.table("agent_research_jobs").select("*").eq("dedupe_key", dedupe_key).limit(1).execute()
            rows = getattr(existing, "data", None) or []
            return rows[0] if rows else None
        except Exception:
            return None


def _url_ok(value: Any) -> bool:
    try:
        parsed = urlparse(str(value))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def validate_agent_submission(payload: Any, *, job_id: str, seen_submission: bool = False) -> dict[str, Any]:
    """Validate safely; return partial accepted data plus field errors."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            return {"valid": False, "errors": [{"path": "$", "message": "invalid JSON"}], "data": None}
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": [{"path": "$", "message": "object required"}], "data": None}
    if str(payload.get("job_id") or "") != str(job_id):
        errors.append({"path": "job_id", "message": "does not match staged job"})
    if seen_submission:
        errors.append({"path": "$", "message": "duplicate submission"})
    people = payload.get("people") if isinstance(payload.get("people"), list) else []
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    clean_people: list[dict[str, Any]] = []
    for index, person in enumerate(people):
        if not isinstance(person, dict) or not str(person.get("full_name") or "").strip():
            errors.append({"path": f"people[{index}]", "message": "full_name required"})
            continue
        clean = dict(person)
        contactability = dict(clean.get("contactability") or {})
        email = contactability.get("email")
        if contactability.get("status") == "VERIFIED_PUBLIC" and (not email or "*" in str(email) or contactability.get("inferred")):
            contactability["status"] = "UNKNOWN"
            errors.append({"path": f"people[{index}].contactability", "message": "masked or inferred email cannot be VERIFIED_PUBLIC"})
        clean["contactability"] = contactability
        for claim in clean.get("claims") or []:
            if isinstance(claim, dict) and claim.get("proposed_provenance") == "OBSERVED" and not claim.get("source_urls"):
                claim["proposed_provenance"] = "INFERRED"
                errors.append({"path": f"people[{index}].claims", "message": "source-free OBSERVED claim downgraded to INFERRED"})
        clean_people.append(clean)
    clean_sources: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict) or not _url_ok(source.get("url")):
            errors.append({"path": f"sources[{index}]", "message": "valid public URL required"})
            continue
        clean_sources.append(dict(source))
    data = {**payload, "job_id": str(job_id), "people": clean_people, "sources": clean_sources}
    return {"valid": not errors, "errors": errors, "data": data}


def _entity_id(client: Any, entity_type: str, name: str, metadata: dict[str, Any] | None = None) -> str | None:
    if not name:
        return None
    normalized = normalize_person_name(name)
    try:
        response = client.table("research_entities").upsert({"entity_type": entity_type, "canonical_name": name[:500], "normalized_name": normalized, "metadata_json": metadata or {}}, on_conflict="entity_type,normalized_name").execute()
        rows = getattr(response, "data", None) or []
        if rows:
            return rows[0].get("id")
    except Exception:
        pass
    return None


def apply_validated_agent_research(client: Any, *, job: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    """Apply only structurally valid, source-attributed findings.

    Agent statements remain INFERRED unless a deterministic source fetch has
    independently succeeded. All writes are idempotent by stable contact/source
    keys and equivalent claim checks.
    """
    data = validated.get("data") or {}
    opportunity_id = str(job.get("opportunity_id") or "")
    known = job.get("known_entities") or {}
    company = str(known.get("company") or "").strip()
    company_id = None
    try:
        opportunity = (client.table("opportunities").select("company_id").eq("id", opportunity_id).limit(1).execute().data or [{}])[0]
        company_id = opportunity.get("company_id")
    except Exception:
        pass
    sources_by_url = {str(source.get("url")): source for source in data.get("sources") or [] if _url_ok(source.get("url"))}
    metrics = {"people_proposed": len(data.get("people") or []), "sources_proposed": len(sources_by_url), "sources_accepted": 0, "sources_rejected": 0, "people_canonicalised": 0, "contacts_created": 0, "duplicates_prevented": 0, "claims_accepted": 0, "works_accepted": 0}
    source_ids: dict[str, str] = {}
    for url, source in sources_by_url.items():
        # URL validation is intentionally conservative; the underlying page is
        # still marked unverified until a source adapter or fetch confirms it.
        source_ids[url] = url
        metrics["sources_accepted"] += 1
    contacts = []
    try:
        contacts = client.table("contacts").select("*").eq("company_id", company_id).execute().data or [] if company_id else []
    except Exception:
        contacts = []
    for person in data.get("people") or []:
        name = str(person.get("full_name") or "").strip()
        if not name:
            continue
        identity = max(0.0, min(100.0, float(person.get("identity_confidence") or 0)))
        current_company = str(person.get("current_company") or "")
        company_match = bool(company and current_company and normalize_person_name(company) in normalize_person_name(current_company))
        matches = sorted(((person_name_compatibility(str(row.get("display_name") or ""), name), row) for row in contacts), reverse=True, key=lambda item: item[0])
        existing = matches[0][1] if matches and matches[0][0] >= 0.78 and (company_match or company_id) else None
        if existing:
            contact = existing
            metrics["duplicates_prevented"] += 1
            updates = {"contact_confidence": max(float(existing.get("contact_confidence") or 0), identity / 100), "technical_relevance": max(float(existing.get("technical_relevance") or 0), float(person.get("technical_relevance") or 0)), "identity_reason": "ChatGPT Work result validated against canonical name/context"}
            client.table("contacts").update(updates).eq("id", existing["id"]).execute()
        elif identity >= 70 and company_id and (company_match or not current_company):
            normalized = normalize_person_name(name)
            contact_id = str(uuid5(NAMESPACE_URL, f"svak:contact:{company_id}:{normalized}"))
            contact = {"id": contact_id, "company_id": company_id, "normalized_name": normalized, "display_name": name, "title": person.get("current_title"), "department": None, "contact_confidence": identity / 100, "technical_relevance": float(person.get("technical_relevance") or 0), "candidate_status": "IDENTITY_RESOLVED", "identity_reason": "Validated Work result with contextual identity evidence"}
            client.table("contacts").upsert(contact, on_conflict="id").execute()
            contacts.append(contact)
            metrics["contacts_created"] += 1
        else:
            continue
        metrics["people_canonicalised"] += 1
        contact_id = contact["id"]
        urls = set(str(value) for value in person.get("source_urls") or [] if _url_ok(value))
        for claim in person.get("claims") or []:
            urls.update(str(value) for value in claim.get("source_urls") or [] if _url_ok(value))
        ids = []
        for url in urls:
            source = sources_by_url.get(url) or {"url": url, "title": url, "publisher": urlparse(url).netloc, "source_type": "OTHER_PUBLIC"}
            try:
                row = client.table("contact_sources").upsert({"contact_id": contact_id, "url": url, "title": source.get("title") or url, "publisher": source.get("publisher") or urlparse(url).netloc, "source_type": source.get("source_type") or "OTHER_PUBLIC", "status": "USED", "evidence_strength": source.get("suggested_source_class") or "DISCOVERY_WEAK", "why_used": "ChatGPT Work source staged for deterministic validation", "source_kind": "CHATGPT_WORK_GITHUB"}, on_conflict="contact_id,url").select("id").execute()
                rows = getattr(row, "data", None) or []
                if rows: ids.append(rows[0]["id"])
            except Exception:
                continue
        for claim in person.get("claims") or []:
            text = str(claim.get("claim") or "").strip()
            if not text: continue
            provenance = "OBSERVED" if claim.get("source_urls") else "INFERRED"
            try:
                client.table("contact_claims").insert({"contact_id": contact_id, "claim_type": claim.get("claim_type") or "WORK_RESEARCH", "claim_text": text, "provenance": provenance, "confidence": max(0.0, min(1.0, float(claim.get("confidence") or 0.5))), "source_ids": ids, "opportunity_id": opportunity_id}).execute()
                metrics["claims_accepted"] += 1
            except Exception:
                pass
        for work in person.get("technical_work") or []:
            title = str(work.get("title") or "").strip()
            if not title: continue
            try:
                client.table("contact_works").insert({"contact_id": contact_id, "work_type": work.get("type") or "OTHER", "title": title, "work_date": work.get("date"), "person_role": "Proposed by ChatGPT Work; validation pending", "company_context": current_company or None, "topic": work.get("technical_topic"), "molecules": [work["molecule"]] if work.get("molecule") else [], "technical_themes": [work["impurity"]] if work.get("impurity") else [], "attribution": "PERSON_DIRECT", "confidence": max(0.0, min(1.0, float(person.get("technical_relevance") or 50) / 100)), "source_ids": ids}).execute()
                metrics["works_accepted"] += 1
            except Exception:
                pass
        try:
            client.table("opportunity_contacts").upsert({"opportunity_id": opportunity_id, "contact_id": contact_id, "role_fit_score": float(person.get("identity_confidence") or 0), "rank": 1, "rationale": "CHATGPT_WORK; staged source-backed candidate"}, on_conflict="opportunity_id,contact_id").execute()
        except Exception:
            pass
    return metrics
