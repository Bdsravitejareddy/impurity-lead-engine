"""Optional people finder: Hunter.io domain search for qualified companies.

Hunter returns personal email addresses it has indexed from public web pages.
It is a third-party database, not a public company page, so the addresses are
stored as ROLE_ONLY with a capped confidence. They are never labelled
VERIFIED_PUBLIC, and nothing is sent to the addresses.

The stage is off unless HUNTER_API_KEY is set. Hunter's free plan allows a
small number of searches a month, so each company is searched at most once per
DOMAIN_RECHECK_DAYS and only HUNTER_MAX_SEARCHES_PER_RUN companies per run.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from impurity_leads.contacts.normalize import normalize_person_name
from impurity_leads.seed_sources import qualified_companies

HUNTER_URL = "https://api.hunter.io/v2/domain-search"
DEFAULT_MAX_SEARCHES_PER_RUN = 1
DOMAIN_RECHECK_DAYS = 30
RESULT_LIMIT = 25
MAX_CONFIDENCE = 0.6
SOURCE_TYPE = "HUNTER_DOMAIN_SEARCH"
# Roles that buy or specify impurity, analytical and regulatory work.
RELEVANT_ROLE = re.compile(
    r"quality|analytic|cmc|regulat|impurit|process|r&d|research|development|chemist|"
    r"procure|sourcing|\bqa\b|\bqc\b|gmp|validation|stability|technical|scien|"
    r"director|head|vice president|\bvp\b|chief",
    re.I,
)


def _relevant(position: str | None) -> bool:
    return bool(position) and bool(RELEVANT_ROLE.search(position or ""))


def hunter_people(http, api_key: str, domain: str, *, limit: int = RESULT_LIMIT) -> list[dict[str, Any]]:
    """Personal, role-relevant addresses Hunter holds for one domain."""
    response = http.get(HUNTER_URL, params={"domain": domain, "api_key": api_key, "limit": limit, "type": "personal"})
    response.raise_for_status()
    people = []
    for item in (response.json().get("data") or {}).get("emails", []):
        if item.get("type") != "personal" or not item.get("value"):
            continue
        if not _relevant(item.get("position")):
            continue
        name = " ".join(part for part in [item.get("first_name"), item.get("last_name")] if part).strip()
        people.append({
            "email": str(item["value"]).strip().lower(),
            "name": name or None,
            "position": item.get("position"),
            "department": item.get("department"),
            "confidence": float(item.get("confidence") or 0),
        })
    return people


def contact_confidence(hunter_confidence: float) -> float:
    """Hunter's 0-100 score, scaled and capped so it never reads as verified."""
    return round(min(MAX_CONFIDENCE, hunter_confidence / 100 * MAX_CONFIDENCE), 2)


def run_hunter_people(settings, client, *, http=None, api_key: str | None = None,
                      max_searches: int | None = None, now: datetime | None = None,
                      sleep: Callable[[float], None] | None = None) -> dict:
    api_key = api_key if api_key is not None else os.environ.get("HUNTER_API_KEY", "")
    if not api_key:
        return {"status": "SKIPPED", "reason": "hunter_api_key_not_set"}
    max_searches = max_searches if max_searches is not None else int(os.environ.get("HUNTER_MAX_SEARCHES_PER_RUN", DEFAULT_MAX_SEARCHES_PER_RUN))
    now = now or datetime.now(timezone.utc)
    recheck_before = now - timedelta(days=DOMAIN_RECHECK_DAYS)
    owns_http = http is None
    http = http or httpx.Client(timeout=20, follow_redirects=False)
    companies = [
        company for company in qualified_companies(client, "id,legal_name,normalized_name,domain,merged_into_company_id,people_checked_at").values()
        if company.get("domain")
        and not (company.get("people_checked_at") and datetime.fromisoformat(str(company["people_checked_at"]).replace("Z", "+00:00")) > recheck_before)
    ]
    companies.sort(key=lambda company: (company.get("people_checked_at") is not None, company.get("legal_name") or ""))
    searched, added, errors = 0, 0, []
    try:
        for company in companies[:max_searches]:
            domain = company["domain"]
            try:
                people = hunter_people(http, api_key, domain)
            except httpx.HTTPError as error:
                # Never echo the URL: it carries the API key.
                errors.append({"domain": domain, "error": type(error).__name__})
                continue
            searched += 1
            for person in people:
                if not person["name"]:
                    continue
                normalized = normalize_person_name(person["name"])
                row = {
                    "company_id": company["id"],
                    "normalized_name": normalized,
                    "display_name": person["name"],
                    "title": person["position"],
                    "department": person["department"],
                    "primary_email": person["email"],
                    "email_status": "ROLE_ONLY",
                    "contact_confidence": contact_confidence(person["confidence"]),
                    "first_seen_at": now.isoformat(),
                    "last_seen_at": now.isoformat(),
                }
                saved = client.table("contacts").upsert(row, on_conflict="company_id,normalized_name").execute()
                contact_id = ((getattr(saved, "data", None) or [{}])[0]).get("id")
                if contact_id:
                    client.table("contact_sources").upsert({
                        "contact_id": contact_id,
                        "url": f"https://{domain}",
                        "title": "Hunter.io domain search",
                        "publisher": "Hunter.io",
                        "source_type": SOURCE_TYPE,
                        "source_date": now.date().isoformat(),
                        "accessed_at": now.isoformat(),
                        "status": "USED",
                        "evidence_strength": "THIRD_PARTY_DATABASE",
                        "why_used": "Personal address indexed by Hunter.io; not confirmed on a company page",
                        "source_kind": SOURCE_TYPE,
                    }, on_conflict="contact_id,url").execute()
                added += 1
            client.table("companies").update({"people_checked_at": now.isoformat()}).eq("id", company["id"]).execute()
    finally:
        if owns_http:
            http.close()
    return {"status": "COMPLETED", "companies_waiting": len(companies), "searched": searched,
            "contacts_upserted": added, "errors": errors}
