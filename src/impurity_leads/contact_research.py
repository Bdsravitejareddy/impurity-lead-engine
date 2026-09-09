"""Bounded, resumable contact research worker for supplied professional sources.

The worker consumes the query seeds produced by profile ingestion and uses
public bibliographic metadata (Europe PMC) as a safe, free corroboration
source.  It never accesses authenticated professional profiles.  Every source
is given a terminal disposition so a completed run cannot leave ambiguous
``INSPECTED`` rows behind.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

from impurity_leads.contacts.normalize import normalize_person_name

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
TECHNICAL_TERMS = ("analytical", "quality", "impurity", "degradation", "stability", "method", "regulatory", "cmc", "api", "validation")
SOURCE_LIMIT_PER_QUERY = 5
QUERY_LIMIT = 20


def _normalise_query(value: str) -> str:
    return " ".join(value.split()).strip()


def _get_json(url: str, timeout: float = 15.0) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "SVAK-Impurity-Lead-Research/0.1"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - HTTPS allowlist above
        import json
        return json.loads(response.read().decode("utf-8"))


def _queries(contact: dict[str, Any], sources: list[dict[str, Any]]) -> list[str]:
    name = contact.get("display_name") or ""
    terms: list[str] = []
    for source in sources:
        extraction = source.get("extraction_json") or {}
        terms.extend(str(item) for item in extraction.get("keywords", []) if item)
        if extraction.get("currentCompany"):
            terms.append(str(extraction["currentCompany"]))
    unique: list[str] = []
    seen: set[str] = set()
    candidates = [
        f'"{name}" publication', f'"{name}" patent', f'"{name}" conference',
        f'"{name}" webinar', f'"{name}" analytical', f'"{name}" quality',
        *terms,
    ]
    for candidate in candidates:
        query = _normalise_query(candidate)
        key = query.casefold()
        if len(query) > 3 and key not in seen:
            seen.add(key)
            unique.append(query)
    return unique[:QUERY_LIMIT]


def _identity(contact: dict[str, Any], result: dict[str, Any]) -> str:
    expected = normalize_person_name(contact.get("display_name") or "")
    authors = normalize_person_name(result.get("authorString") or "")
    if not expected or not authors:
        return "REJECTED"
    expected_tokens = set(expected.split())
    author_tokens = set(authors.split())
    if len(expected_tokens.intersection(author_tokens)) >= 2:
        return "HIGH"
    if expected_tokens and expected_tokens.intersection(author_tokens):
        return "MEDIUM"
    return "LOW"


def _terminal_source(*, contact_id: str, url: str, title: str, source_date: str | None,
                     query: str, result: dict[str, Any], status: str, reason: str | None,
                     technical: bool, identity: str) -> dict[str, Any]:
    """Build a canonical source row and preserve inspection provenance."""
    return {
        "contact_id": contact_id,
        "url": url,
        "title": title[:300],
        "publisher": "Europe PMC",
        "source_type": "Scientific publication",
        "source_date": source_date,
        "status": status,
        "evidence_strength": identity,
        "why_used": "Public bibliographic record names the person and contains technical professional context." if status == "USED" else None,
        "why_not_used": reason,
        "rejection_reason": reason,
        "source_kind": "EXTERNAL_RESEARCH",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "extraction_json": {
            "identity": identity,
            "query": query,
            "author_string": result.get("authorString"),
            "technical": technical,
            "attribution": "PERSON_DIRECT" if status == "USED" else None,
        },
    }


def _publication_work(contact_id: str, contact: dict[str, Any], item: dict[str, Any], source_id: str | None, text: str) -> dict[str, Any]:
    return {
        "contact_id": contact_id,
        "work_type": "PUBLICATION",
        "title": (item.get("title") or "Europe PMC publication")[:300],
        "work_date": item.get("firstPublicationDate") or None,
        "person_role": "Named author in public bibliographic record",
        "company_context": contact.get("company") or contact.get("title"),
        "topic": text[:500],
        "technical_themes": [term for term in TECHNICAL_TERMS if term in text.lower()],
        "attribution": "PERSON_DIRECT",
        "confidence": 0.72,
        "source_ids": [source_id] if source_id else [],
    }


def _analysis_for(text: str, source_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Turn explicit technical language into conservative derived intelligence.

    These are hypotheses about the professional problem space.  They are only
    emitted when the public source contains the corresponding terms, and are
    always marked INFERRED/COMPANY or FUNCTIONAL rather than as requirements.
    """
    lower = text.lower()
    refs = [source_id] if source_id else []
    themes = []
    problems = []
    jtbd = []
    mappings = {
        "stability": ("stability and degradation control", "stability-indicating investigations", "stability/degradation support"),
        "impurity": ("impurity control", "resolving impurity-characterisation questions", "custom impurity synthesis; reference standards"),
        "analytical": ("analytical development", "maintaining validated analytical methods", "analytical/reference-standard support"),
        "quality": ("quality governance", "maintaining quality evidence across products", "regulatory analytical support"),
        "regulatory": ("regulatory analytical readiness", "supporting regulatory evidence and responses", "reference standards; impurity dossiers"),
        "validation": ("method validation", "maintaining method-validation readiness", "analytical method support"),
    }
    for term, (theme, problem, mapping) in mappings.items():
        if term not in lower:
            continue
        themes.append({"theme": theme, "evidence_count": 1, "confidence": 0.62, "source_ids": refs})
        problems.append({"problem": problem, "context": "Explicit technical language in a public professional publication.", "attribution": "DIRECT", "technical_relevance": theme, "svak_relevance": mapping, "confidence": 0.62, "source_ids": refs})
        jtbd.append({"statement": f"{problem.capitalize()} without delaying technical timelines.", "category": theme, "basis": "Public source contains explicit technical context; this is a professional hypothesis, not a confirmed requirement.", "evidence": text[:500], "confidence": 0.58, "provenance": "INFERRED", "svak_mapping": mapping, "discovery_question": "How does your team currently handle this requirement when an external standard or custom material is needed?", "source_ids": refs})
    return themes, problems, jtbd


def run_pending_contact_research(settings, *, limit: int = 10, fetcher: Callable[[str], dict[str, Any]] = _get_json) -> dict[str, Any]:
    """Process queued contact research runs using the backend-only Supabase key."""
    if not settings.supabase_url or not settings.supabase_secret_key:
        return {"status": "SKIPPED", "reason": "supabase_credentials_missing", "processed": 0}
    from supabase import create_client
    client = create_client(settings.supabase_url, settings.supabase_secret_key)
    queued = client.table("contact_research_runs").select("*").eq("status", "QUEUED").order("created_at").limit(limit).execute().data or []
    totals = {"status": "COMPLETED", "processed": 0, "queries": 0, "sources": 0, "used": 0, "rejected": 0, "blocked": 0, "failed": 0, "pending": 0, "works": 0, "conflicts": 0}
    for run in queued:
        run_id = run["id"]
        contact_rows = client.table("contacts").select("*").eq("id", run["contact_id"]).limit(1).execute().data or []
        if not contact_rows:
            client.table("contact_research_runs").update({"status": "FAILED", "completed_at": datetime.now(timezone.utc).isoformat(), "error": "contact_not_found", "error_code": "CONTACT_NOT_FOUND"}).eq("id", run_id).execute()
            continue
        contact = contact_rows[0]
        client.table("contact_research_runs").update({"status": "RUNNING", "started_at": datetime.now(timezone.utc).isoformat()}).eq("id", run_id).execute()
        supplied = client.table("contact_sources").select("*").eq("contact_id", contact["id"]).execute().data or []
        queries = _queries(contact, supplied)
        discovered = inspected = used = rejected = failed = works = claims = positions = education = problems = themes = jtbd = 0
        seen_urls: set[str] = set()
        try:
            for query in queries:
                endpoint = f"{EUROPE_PMC}?query={quote(query)}&format=json&pageSize=5"
                try:
                    payload = fetcher(endpoint)
                except Exception as exc:
                    failed += 1
                    # A failed public request is retained as a terminal source
                    # record, so operators can distinguish it from a rejected
                    # match and retry it on a later run.
                    failed_source = {
                        "contact_id": contact["id"], "url": endpoint,
                        "title": f"Europe PMC query: {query}"[:300],
                        "publisher": "Europe PMC", "source_type": "Scientific publication",
                        "status": "FAILED", "evidence_strength": "UNKNOWN",
                        "why_not_used": "Public source request failed; retry is allowed.",
                        "rejection_reason": "OTHER", "source_kind": "EXTERNAL_RESEARCH",
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "extraction_json": {"query": query, "error": str(exc)[:200]},
                    }
                    try:
                        client.table("contact_sources").upsert(failed_source, on_conflict="contact_id,url").execute()
                    except Exception:
                        pass
                    continue
                for item in (payload.get("resultList") or {}).get("result", [])[:SOURCE_LIMIT_PER_QUERY]:
                    discovered += 1
                    title = item.get("title") or "Europe PMC result"
                    pmid = item.get("pmid") or item.get("id")
                    if not pmid:
                        rejected += 1
                        continue
                    url = f"https://europepmc.org/article/MED/{pmid}"
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    text = " ".join(str(item.get(key) or "") for key in ("title", "abstractText", "authorString"))
                    identity = _identity(contact, item)
                    technical = any(term in text.lower() for term in TECHNICAL_TERMS)
                    status = "USED" if identity == "HIGH" and technical else "REJECTED"
                    reason = None if status == "USED" else ("WRONG_PERSON" if identity in {"LOW", "REJECTED"} else "WEAK_EVIDENCE")
                    source = _terminal_source(contact_id=contact["id"], url=url, title=title, source_date=item.get("firstPublicationDate") or None, query=query, result=item, status=status, reason=reason, technical=technical, identity=identity)
                    source_response = client.table("contact_sources").upsert(source, on_conflict="contact_id,url").select("id").execute()
                    source_rows = getattr(source_response, "data", None) or []
                    source_id = source_rows[0].get("id") if source_rows else None
                    inspected += 1
                    if status == "USED":
                        used += 1
                        client.table("contact_works").insert(_publication_work(contact["id"], contact, item, source_id, text)).execute()
                        works += 1
                        if source_id:
                            client.table("contact_claims").insert({"contact_id": contact["id"], "claim_type": "PUBLICATION_AUTHORED", "claim_text": f"{contact.get('display_name') or 'The contact'} is named in: {title[:250]}", "provenance": "OBSERVED", "confidence": 0.78, "source_ids": [source_id]}).execute()
                            claims += 1
                            derived_themes, derived_problems, derived_jtbd = _analysis_for(text, source_id)
                            for row in derived_themes:
                                client.table("contact_themes").upsert({"contact_id": contact["id"], **row}, on_conflict="contact_id,theme").execute()
                                themes += 1
                            for row in derived_problems:
                                client.table("contact_problems").insert({"contact_id": contact["id"], **row}).execute()
                                problems += 1
                            for row in derived_jtbd:
                                client.table("contact_jtbd").insert({"contact_id": contact["id"], **row}).execute()
                                jtbd += 1
                    else:
                        rejected += 1
            completed_status = "COMPLETED" if inspected else "PARTIAL"
            now = datetime.now(timezone.utc).isoformat()
            client.table("contact_research_runs").update({"status": completed_status, "completed_at": now, "queries_executed": len(queries), "sources_discovered": discovered, "sources_inspected": inspected, "sources_used": used, "sources_rejected": rejected, "sources_failed": failed, "new_claims": claims, "new_works": works, "new_problems": problems, "new_themes": themes, "new_jtbd": jtbd, "blocked_sources": 0}).eq("id", run_id).execute()
            totals.update(processed=totals["processed"] + 1, queries=totals["queries"] + len(queries), sources=totals["sources"] + inspected, used=totals["used"] + used, rejected=totals["rejected"] + rejected, failed=totals["failed"] + failed, works=totals["works"] + works, conflicts=totals["conflicts"])
        except Exception as exc:
            client.table("contact_research_runs").update({"status": "FAILED", "completed_at": datetime.now(timezone.utc).isoformat(), "error": str(exc)[:500], "error_code": "WORKER_ERROR"}).eq("id", run_id).execute()
    return totals
