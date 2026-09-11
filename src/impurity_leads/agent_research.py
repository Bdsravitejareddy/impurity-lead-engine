"""Human-in-the-loop ChatGPT Work bridge.

This module only prepares and validates staged research. It never treats an
agent response as canonical database truth without backend validation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


OUTPUT_SCHEMA = {
    "job_id": "string",
    "research_summary": "string",
    "people": "array of people with claims and technical_work",
    "sources": "array of source records",
    "missing_dimensions_resolved": "array of strings",
    "remaining_unknowns": "array of strings",
    "recommended_next_queries": "array of strings",
}

ACTIVE_AGENT_STATUSES = {"QUEUED", "READY", "EXPORTED", "RESULT_SUBMITTED", "VALIDATING"}


def build_agent_research_prompt(job: dict[str, Any]) -> str:
    """Build one bounded, copyable Work prompt from a READY job."""
    company = job.get("company") or job.get("company_name") or "Unknown company"
    molecule = job.get("molecule") or job.get("molecule_name") or "Unknown molecule"
    missing = job.get("missing_dimensions") or []
    return f"""Use Work mode with web research. Return only the requested JSON, with no markdown.

You are assisting SVAK Intelligence with a bounded research task.

Opportunity
- Company: {company}
- Molecule/product: {molecule}
- Opportunity score: {job.get('opportunity_score', 'UNKNOWN')}
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
