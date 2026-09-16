"""Human-in-the-loop ChatGPT Work bridge.

This module only prepares and validates staged research. It never treats an
agent response as canonical database truth without backend validation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from impurity_leads.contacts.normalize import normalize_person_name, person_name_compatibility
from impurity_leads.molecule_intelligence import apply_molecule_sections, normalize_claim_type
from impurity_leads.contact_quality import score_contact


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

MOLECULE_OUTPUT_SCHEMA = {
    "job_id": "string", "job_kind": "MOLECULE_INTELLIGENCE", "research_summary": "string",
    "molecule": {"canonical_name": "string", "claims": [{"claim": "string", "claim_type": "string", "proposed_provenance": "OBSERVED|INFERRED", "confidence": 0, "source_urls": ["https://..."]}]},
    "sources": OUTPUT_SCHEMA["sources"], "missing_dimensions_resolved": "array of strings",
    "remaining_unknowns": "array of strings", "recommended_next_queries": "array of strings",
}

OPPORTUNITY_EVIDENCE_OUTPUT_SCHEMA = {
    "job_id": "string", "job_kind": "OPPORTUNITY_EVIDENCE", "company_id": "string", "molecule_id": "string",
    "research_summary": "string",
    "evidence": [{"source_url": "https://...", "source_title": "string", "publisher": "string", "source_date": None, "source_type": "string", "signal_type": "IMPURITY_CHARACTERIZATION|DEGRADATION_PRODUCT|STABILITY|REFERENCE_STANDARD|GENOTOXIC_IMPURITY|NITROSAMINE_NDSRI|ANALYTICAL_METHOD|REGULATORY_APPLICATION|DIRECT_IMPURITY_RFQ", "evidence_text": "string", "company_specific": True, "molecule_specific": True, "confidence": 0}],
    "missing_dimensions_resolved": "array of strings", "remaining_unknowns": "array of strings", "recommended_next_queries": "array of strings",
}

ACTIVE_AGENT_STATUSES = {"QUEUED", "READY", "EXPORTED", "RESULT_SUBMITTED", "VALIDATING"}


def opportunity_contact_link_payload(*, opportunity_id: str, contact_id: str, identity_confidence: Any,
                                    source_ids: list[str], rationale: str) -> dict[str, Any]:
    """Build a schema-safe, provenance-bearing opportunity contact link."""
    try:
        score = int(round(float(identity_confidence or 0)))
    except (TypeError, ValueError):
        score = 0
    return {
        "opportunity_id": opportunity_id,
        "contact_id": contact_id,
        "role_fit_score": max(0, min(100, score)),
        "rank": 1,
        "rationale": rationale,
        "source_ids": list(dict.fromkeys(str(value) for value in source_ids if value)),
    }


def build_agent_research_prompt(job: dict[str, Any]) -> str:
    """Build one bounded, copyable Work prompt from a READY job."""
    known_entities = job.get("known_entities") or {}
    company = job.get("company") or job.get("company_name") or known_entities.get("company") or "Unknown company"
    molecule = job.get("molecule") or job.get("molecule_name") or known_entities.get("molecule") or "Unknown molecule"
    opportunity_score = job.get("opportunity_score", known_entities.get("opportunity_score", "UNKNOWN"))
    missing = job.get("missing_dimensions") or []
    job_kind = str(job.get("job_kind") or "CONTACT_RESEARCH")
    schema = MOLECULE_OUTPUT_SCHEMA if job_kind == "MOLECULE_INTELLIGENCE" else OPPORTUNITY_EVIDENCE_OUTPUT_SCHEMA if job_kind == "OPPORTUNITY_EVIDENCE" else OUTPUT_SCHEMA
    return f"""Use Work mode with web research. Return only the requested JSON, with no markdown.

You are assisting SVAK Intelligence with a bounded research task.

Research kind: {job_kind}

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

Research only the unresolved dimensions above. For OPPORTUNITY_EVIDENCE, every finding
must be specific to this exact company and molecule; generic molecule facts do not count.
Never provide scores, priorities, qualification or promotion decisions. Prefer official/regulatory sources,
publications, patents, conference or professional sources, public company pages,
and reputable public directories. Return the underlying source URLs.

Do not bypass authentication, CAPTCHA, paywalls or private data. Do not guess hidden
emails. If a promising source is blocked, return access_status BLOCKED_AUTH.
Unknown values must be null or UNKNOWN. Do not manufacture sources or claims.

Return JSON matching this shape exactly:
{json.dumps(schema, indent=2)}

Each claim must include proposed_provenance OBSERVED or INFERRED and source_urls.
Masked or inferred emails must not be marked VERIFIED_PUBLIC.
"""


def active_agent_dedupe_key(opportunity_id: str | None, missing_dimensions: list[str], *, job_kind: str = "CONTACT_RESEARCH", molecule_id: str | None = None) -> str:
    dims = ",".join(sorted({str(item).strip().upper() for item in missing_dimensions if str(item).strip()}))
    prefix = f"molecule:{molecule_id}" if job_kind == "MOLECULE_INTELLIGENCE" else str(opportunity_id or "")
    return f"{prefix}:{dims or 'GENERAL'}"


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


def queue_molecule_intelligence_job(client: Any, *, molecule: dict[str, Any], missing_dimensions: list[str], quality_before: dict[str, Any], priority: int = 0, known_sources: list[dict[str, Any]] | None = None, known_claims: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Queue one bounded canonical molecule job, independent of companies."""
    molecule_id = str(molecule.get("id") or molecule.get("molecule_id") or "")
    if not molecule_id:
        return None
    dimensions = sorted({str(item).upper() for item in missing_dimensions if str(item).strip()})
    if not dimensions:
        return None
    dedupe_key = active_agent_dedupe_key(None, dimensions, job_kind="MOLECULE_INTELLIGENCE", molecule_id=molecule_id)
    job = {
        "job_kind": "MOLECULE_INTELLIGENCE", "molecule_id": molecule_id, "opportunity_id": None,
        "priority": int(priority), "research_goal": f"Resolve only molecule dimensions: {', '.join(dimensions)}",
        "missing_dimensions": dimensions, "known_entities": {"molecule": molecule.get("canonical_name") or molecule.get("name"), "molecule_id": molecule_id},
        "known_contacts": [], "known_sources": known_sources or [], "known_claims": known_claims or [], "quality_before": quality_before or {},
        "dedupe_key": dedupe_key, "status": "READY",
    }
    job["agent_prompt"] = build_agent_research_prompt(job)
    try:
        existing = client.table("agent_research_jobs").select("*").eq("dedupe_key", dedupe_key).in_("status", list(ACTIVE_AGENT_STATUSES)).limit(1).execute()
        rows = getattr(existing, "data", None) or []
        if rows:
            return rows[0]
        response = client.table("agent_research_jobs").insert(job).execute()
        rows = getattr(response, "data", None) or []
        return rows[0] if rows else job
    except Exception:
        try:
            rows = client.table("agent_research_jobs").select("*").eq("dedupe_key", dedupe_key).limit(1).execute().data or []
            return rows[0] if rows else None
        except Exception:
            return None


def queue_opportunity_evidence_job(client: Any, *, candidate: dict[str, Any], company_name: str, molecule_name: str, missing_dimensions: list[str], priority: int = 0, research_budget: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Queue one bounded Work job for one retained company/molecule candidate."""
    company_id = str(candidate.get("company_id") or "")
    molecule_id = str(candidate.get("molecule_id") or "")
    score = float(candidate.get("candidate_score") or 0)
    if not company_id or not molecule_id or str(candidate.get("candidate_status") or "") != "UNQUALIFIED" or score >= 50:
        return None
    dimensions = sorted({str(item).strip().upper() for item in missing_dimensions if str(item).strip()})
    if not dimensions:
        return None
    base_dedupe_key = active_agent_dedupe_key(f"{company_id}:{molecule_id}", dimensions, job_kind="OPPORTUNITY_EVIDENCE")
    dedupe_key = base_dedupe_key
    job = {
        "job_kind": "OPPORTUNITY_EVIDENCE", "opportunity_id": None, "company_id": company_id,
        "molecule_id": molecule_id, "candidate_id": str(candidate.get("id") or ""), "priority": int(priority),
        "research_goal": f"Find company-specific evidence for {company_name} / {molecule_name}: {', '.join(dimensions)}",
        "missing_dimensions": dimensions, "known_entities": {"company": company_name, "company_id": company_id, "molecule": molecule_name, "molecule_id": molecule_id},
        "known_contacts": [], "known_sources": candidate.get("known_sources") or [{"fingerprint": fp} for fp in candidate.get("candidate_signal_fingerprints") or []],
        "known_claims": [], "quality_before": {"candidate_score": candidate.get("candidate_score"), "candidate_status": candidate.get("candidate_status"), "distance_to_qualification": max(0, 50 - score)},
        "research_budget": research_budget or {"max_rounds": 2, "max_sources": 10}, "attempt_count": 1, "last_attempt_at": datetime.now(timezone.utc).isoformat(), "dedupe_key": dedupe_key, "status": "READY",
    }
    job["agent_prompt"] = build_agent_research_prompt(job)
    try:
        rows = client.table("agent_research_jobs").select("*").eq("dedupe_key", dedupe_key).in_("status", list(ACTIVE_AGENT_STATUSES)).limit(1).execute().data or []
        if rows:
            existing = dict(rows[0]); existing["_deduped"] = True
            return existing
        history = client.table("agent_research_jobs").select("*").eq("dedupe_key", dedupe_key).limit(1).execute().data or []
        if history:
            previous = dict(history[0])
            attempts = int(previous.get("attempt_count") or 1)
            if attempts >= int((research_budget or {}).get("max_rounds", 2)) or str(previous.get("last_outcome") or "") == "NO_NEW_EVIDENCE":
                previous["_deduped"] = True
                return previous
            # A completed, useful-but-insufficient round may have its same
            # candidate researched once more. Keep active dedupe strict while
            # using a deterministic round suffix for the new issue.
            dedupe_key = f"{base_dedupe_key}:round{attempts + 1}"
            job["dedupe_key"] = dedupe_key
            job["attempt_count"] = attempts + 1
        rows = client.table("agent_research_jobs").insert(job).execute().data or []
        return rows[0] if rows else job
    except Exception:
        try:
            rows = client.table("agent_research_jobs").select("*").eq("dedupe_key", dedupe_key).limit(1).execute().data or []
            return rows[0] if rows else None
        except Exception:
            return None


def _url_ok(value: Any) -> bool:
    try:
        parsed = urlparse(str(value))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _underlying_public_url(value: Any) -> bool:
    """Reject search-result URLs; Work must return the inspectable source."""
    if not _url_ok(value):
        return False
    parsed = urlparse(str(value))
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    return not ((host.endswith("google.com") and path.startswith("/search")) or
                (host.endswith("bing.com") and path.startswith("/search")) or
                host.endswith("tavily.com"))


def validate_agent_submission(payload: Any, *, job_id: str, seen_submission: bool = False, job_kind: str = "CONTACT_RESEARCH", job_context: dict[str, Any] | None = None) -> dict[str, Any]:
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
    actual_kind = str(payload.get("job_kind") or job_kind)
    if actual_kind not in {"CONTACT_RESEARCH", "MOLECULE_INTELLIGENCE", "OPPORTUNITY_EVIDENCE"}:
        errors.append({"path": "job_kind", "message": "unsupported job kind"})
    if actual_kind == "OPPORTUNITY_EVIDENCE":
        context = job_context or {}
        if str(payload.get("company_id") or "") != str(context.get("company_id") or ""):
            errors.append({"path": "company_id", "message": "does not match staged candidate"})
        if str(payload.get("molecule_id") or "") != str(context.get("molecule_id") or ""):
            errors.append({"path": "molecule_id", "message": "does not match staged candidate"})
        for field in ("score_after", "score", "priority", "qualified", "promotion_recommendation"):
            if field in payload:
                errors.append({"path": field, "message": "computed by backend; field is not accepted"})
        allowed = {"IMPURITY_CHARACTERIZATION", "DEGRADATION_PRODUCT", "STABILITY", "REFERENCE_STANDARD", "GENOTOXIC_IMPURITY", "NITROSAMINE_NDSRI", "ANALYTICAL_METHOD", "REGULATORY_APPLICATION", "DIRECT_IMPURITY_RFQ"}
        accepted = []
        sources = {str(source.get("url")): source for source in (payload.get("sources") or []) if isinstance(source, dict) and _url_ok(source.get("url"))}
        for index, item in enumerate(payload.get("evidence") or []):
            if not isinstance(item, dict):
                errors.append({"path": f"evidence[{index}]", "message": "object required"}); continue
            url = str(item.get("source_url") or "")
            signal_type = str(item.get("signal_type") or "").upper()
            text = str(item.get("evidence_text") or "").strip()
            if not _underlying_public_url(url) or url not in sources:
                errors.append({"path": f"evidence[{index}].source_url", "message": "underlying public source URL required"}); continue
            if signal_type not in allowed:
                errors.append({"path": f"evidence[{index}].signal_type", "message": "unsupported opportunity evidence dimension"}); continue
            if not text:
                errors.append({"path": f"evidence[{index}].evidence_text", "message": "evidence text required"}); continue
            if item.get("company_specific") is not True or item.get("molecule_specific") is not True:
                errors.append({"path": f"evidence[{index}]", "message": "company and molecule specificity required"}); continue
            if str(sources[url].get("access_status") or "PUBLIC").upper() != "PUBLIC":
                errors.append({"path": f"evidence[{index}].source_url", "message": "source is not publicly accessible"}); continue
            accepted.append({**item, "signal_type": signal_type, "source_url": url})
        data = {key: value for key, value in payload.items() if key not in {"score_after", "score", "priority", "qualified", "promotion_recommendation"}}
        data.update({"job_id": str(job_id), "job_kind": actual_kind, "evidence": accepted, "sources": list(sources.values())})
        # Item-level failures are retained for observability while good independent
        # evidence can continue through the staging boundary.
        fatal = any(item["path"] in {"job_id", "company_id", "molecule_id", "job_kind", "score_after", "score", "priority", "qualified", "promotion_recommendation"} for item in errors)
        return {"valid": not fatal, "errors": errors, "data": data}
    if actual_kind == "MOLECULE_INTELLIGENCE":
        molecule = payload.get("molecule") if isinstance(payload.get("molecule"), dict) else {}
        if not str(molecule.get("canonical_name") or "").strip():
            errors.append({"path": "molecule.canonical_name", "message": "canonical molecule name required"})
        clean_claims = []
        for index, claim in enumerate(molecule.get("claims") or []):
            if not isinstance(claim, dict) or not str(claim.get("claim") or "").strip():
                errors.append({"path": f"molecule.claims[{index}]", "message": "claim required"})
                continue
            clean_claim = dict(claim)
            clean_claim["source_urls"] = list(dict.fromkeys(str(url) for url in clean_claim.get("source_urls") or [] if _url_ok(url)))
            if clean_claim.get("proposed_provenance") == "OBSERVED" and not clean_claim.get("source_urls"):
                clean_claim["proposed_provenance"] = "INFERRED"
                errors.append({"path": f"molecule.claims[{index}]", "message": "source-free OBSERVED claim downgraded to INFERRED"})
            clean_claims.append(clean_claim)
        clean_sources = [dict(source) for source in (payload.get("sources") or []) if isinstance(source, dict) and _url_ok(source.get("url"))]
        data = {**payload, "job_id": str(job_id), "job_kind": actual_kind, "molecule": {**molecule, "claims": clean_claims}, "sources": clean_sources}
        return {"valid": not errors, "errors": errors, "data": data}
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
            if isinstance(claim, dict):
                claim["source_urls"] = list(dict.fromkeys(str(url) for url in claim.get("source_urls") or [] if _url_ok(url)))
                if claim.get("proposed_provenance") == "OBSERVED" and not claim["source_urls"]:
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
        response = client.table("research_entities").upsert({"entity_type": entity_type, "canonical_name": name[:500], "normalized_name": normalized, "metadata_json": metadata or {}}, on_conflict="entity_type,normalized_name").select("id").execute()
        rows = getattr(response, "data", None) or []
        if rows:
            return rows[0].get("id")
        lookup = client.table("research_entities").select("id").eq("entity_type", entity_type).eq("normalized_name", normalized).limit(1).execute()
        rows = getattr(lookup, "data", None) or []
        if rows:
            return rows[0].get("id")
    except Exception:
        pass
    return None


def _apply_molecule_research(client: Any, *, job: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    data = validated.get("data") or {}
    molecule = data.get("molecule") or {}
    molecule_id = str(job.get("molecule_id") or "")
    if not molecule_id:
        return {"status": "PARTIAL", "rejected": ["molecule_id_missing"]}
    entity_id = _entity_id(client, "MOLECULE", str(molecule.get("canonical_name") or "Unknown molecule"), {"molecule_id": molecule_id})
    claims = []
    for claim in molecule.get("claims") or []:
        text = str(claim.get("claim") or "").strip()
        if not text:
            continue
        source_urls = [str(url) for url in claim.get("source_urls") or [] if _url_ok(url)]
        provenance = "OBSERVED" if source_urls and claim.get("proposed_provenance") == "OBSERVED" else "INFERRED"
        claim_id = str(uuid5(NAMESPACE_URL, f"svak:molecule-claim:{molecule_id}:{normalize_claim_type(claim.get('claim_type'))}:{text}"))
        row = {"id": claim_id, "entity_id": entity_id, "claim_type": normalize_claim_type(claim.get("claim_type")), "claim_text": text, "source_url": source_urls[0] if source_urls else None, "source_class": "PRIMARY" if source_urls else "DISCOVERY_WEAK", "attribution": "MOLECULE_CONTEXT", "provenance": provenance, "confidence": max(0.0, min(1.0, float(claim.get("confidence") or 0.5)))}
        try:
            client.table("research_claims").upsert(row, on_conflict="id").execute()
            claims.append(row)
        except Exception:
            claims.append({"id": None, **row})
    try:
        section_metrics = apply_molecule_sections(client, molecule_id, claims)
    except Exception as exc:
        section_metrics = {"sections_written": 0, "error": type(exc).__name__}
    return {"status": "APPLIED" if claims else "PARTIAL", "molecule_id": molecule_id, "claims_accepted": len(claims), "graph_entities": 1 if entity_id else 0, **section_metrics}


def _apply_opportunity_evidence(client: Any, *, job: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    """Convert accepted Work evidence into SourceRecords and use the normal scorer."""
    from impurity_leads.candidate_enrichment import enrich_candidate
    data = validated.get("data") or {}
    known = job.get("known_entities") or {}
    company_id = str(job.get("company_id") or known.get("company_id") or "")
    molecule_id = str(job.get("molecule_id") or known.get("molecule_id") or "")
    company_name = str(known.get("company") or "").strip()
    molecule_name = str(known.get("molecule") or "").strip()
    records = []
    for index, item in enumerate(data.get("evidence") or []):
        source_date = None
        if item.get("source_date"):
            try:
                source_date = datetime.fromisoformat(str(item["source_date"]).replace("Z", "+00:00"))
            except ValueError:
                pass
        records.append(SourceRecord(
            source_name=str(item.get("source_title") or item.get("source_url")),
            source_type=str(item.get("source_type") or "public_web"),
            source_record_id=f"work:{job.get('id')}:{index}:{item.get('source_url')}",
            source_url=str(item.get("source_url")), published_at=source_date,
            fetched_at=datetime.now(timezone.utc), company_name_raw=company_name,
            molecule_name_raw=molecule_name, signal_text=str(item.get("evidence_text")),
            metadata_json={"company_specific": True, "molecule_specific": True, "source_class": (next((s.get("suggested_source_class") for s in data.get("sources") or [] if s.get("url") == item.get("source_url")), "DISCOVERY_WEAK")), "work_job_id": job.get("id"), "work_signal_type": str(item.get("signal_type") or "").upper()},
        ))
    if not company_id or not molecule_id or not company_name or not molecule_name:
        return {"status": "PARTIAL", "outcome": "FAILED", "reason": "candidate_context_missing", "evidence_accepted": 0}
    result = enrich_candidate(client, company_id=company_id, molecule_id=molecule_id, company_name=company_name, molecule_name=molecule_name, records=records)
    result["evidence_accepted"] = len(records)
    result["evidence_rejected"] = len(validated.get("errors") or [])
    result["outcome"] = "PROMOTED" if result.get("promoted") else ("ENRICHED_BUT_UNQUALIFIED" if result.get("new_signals") else "NO_NEW_EVIDENCE")
    result["status"] = "APPLIED"
    try:
        client.table("company_molecules").update({"candidate_last_enrichment_at": datetime.now(timezone.utc).isoformat(), "candidate_last_enrichment_outcome": result["outcome"]}).eq("company_id", company_id).eq("molecule_id", molecule_id).execute()
    except Exception:
        pass
    return result


def apply_validated_agent_research(client: Any, *, job: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    """Apply only structurally valid, source-attributed findings.

    Agent statements remain INFERRED unless a deterministic source fetch has
    independently succeeded. All writes are idempotent by stable contact/source
    keys and equivalent claim checks.
    """
    if str(job.get("job_kind") or "CONTACT_RESEARCH") == "MOLECULE_INTELLIGENCE":
        return _apply_molecule_research(client, job=job, validated=validated)
    if str(job.get("job_kind") or "CONTACT_RESEARCH") == "OPPORTUNITY_EVIDENCE":
        return _apply_opportunity_evidence(client, job=job, validated=validated)
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
    metrics = {"people_proposed": len(data.get("people") or []), "sources_proposed": len(sources_by_url), "sources_accepted": 0, "sources_rejected": 0, "people_canonicalised": 0, "contacts_created": 0, "duplicates_prevented": 0, "claims_accepted": 0, "works_accepted": 0, "graph_entities": 0, "graph_relationships": 0}
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
        person_entity_id = _entity_id(client, "PERSON", name, {"contact_id": contact_id, "source_channel": "CHATGPT_WORK_GITHUB"})
        opportunity_entity_id = _entity_id(client, "OPPORTUNITY", opportunity_id, {"opportunity_id": opportunity_id})
        if person_entity_id: metrics["graph_entities"] += 1
        if opportunity_entity_id: metrics["graph_entities"] += 1
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
        if person_entity_id and opportunity_entity_id:
            try:
                client.table("research_relationships").upsert({"from_entity_id": person_entity_id, "to_entity_id": opportunity_entity_id, "relationship_type": "LINKED_TO", "source_ids": ids, "confidence": identity / 100, "provenance": "OBSERVED"}, on_conflict="from_entity_id,to_entity_id,relationship_type").execute()
                metrics["graph_relationships"] += 1
            except Exception:
                pass
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
            work_type = str(work.get("type") or "OTHER").upper()
            entity_type = "PATENT" if work_type == "PATENT" else "PUBLICATION" if work_type == "PUBLICATION" else "OTHER"
            work_entity_id = _entity_id(client, entity_type, title, {"contact_id": contact_id, "opportunity_id": opportunity_id, "source_ids": ids})
            if work_entity_id: metrics["graph_entities"] += 1
            if work_entity_id and person_entity_id:
                try:
                    client.table("research_relationships").upsert({"from_entity_id": person_entity_id, "to_entity_id": work_entity_id, "relationship_type": "INVENTOR_ON" if entity_type == "PATENT" else "AUTHORED" if entity_type == "PUBLICATION" else "WORKED_ON", "source_ids": ids, "confidence": max(0.0, min(1.0, float(person.get("technical_relevance") or 50) / 100)), "provenance": "OBSERVED"}, on_conflict="from_entity_id,to_entity_id,relationship_type").execute()
                    metrics["graph_relationships"] += 1
                except Exception:
                    pass
        try:
            link_reason = "CHATGPT_WORK; " + ("PATENT_INVENTOR" if any(str(work.get("type") or "").upper() == "PATENT" for work in person.get("technical_work") or []) else "TECHNICAL_WORK")
            client.table("opportunity_contacts").upsert(opportunity_contact_link_payload(opportunity_id=opportunity_id, contact_id=contact_id, identity_confidence=person.get("identity_confidence"), source_ids=ids, rationale=link_reason), on_conflict="opportunity_id,contact_id").execute()
        except Exception as exc:
            metrics.setdefault("link_errors", []).append(str(exc)[:240])
        # Persist the deterministic score read model after all evidence writes.
        # The canonical contacts table stores confidence as a decimal while
        # score dimensions use 0–100; score_contact normalizes that boundary.
        try:
            scored_sources = client.table("contact_sources").select("source_type,evidence_strength,status").eq("contact_id", contact_id).eq("status", "USED").execute().data or []
            scored = score_contact(contact, sources=scored_sources, opportunities=[{"id": opportunity_id}])
            diagnostics = {"score": scored["score"], "dimensions": scored["dimensions"], "diagnostics": scored["diagnostics"]}
            client.table("contacts").update({"quality_diagnostics": diagnostics}).eq("id", contact_id).execute()
        except Exception:
            # A diagnostics write must never discard an already persisted
            # source, graph relationship, claim, or opportunity link.
            pass
    return metrics
