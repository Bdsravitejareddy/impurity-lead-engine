"""People finder: Hunter.io first, free sources as the fallback.

Hunter returns personal email addresses it has indexed from public web pages.
It is a third-party database, not a public company page, so the addresses are
stored as ROLE_ONLY with a capped confidence. They are never labelled
VERIFIED_PUBLIC, and nothing is sent to the addresses.

Budget: Hunter's free plan has a small monthly search allowance. Before
searching, the stage reads the remaining allowance from the free account
endpoint and spreads it evenly over the days left until it resets, so the
allowance lasts the whole month. Each company is searched at most once per
DOMAIN_RECHECK_DAYS. A 429 means the allowance is used up and stops the stage.

Fallback, which runs on every daily run whether or not Hunter ran:
1. People named on the company's own pages and press releases (crawl stage).
2. Authors whose publication affiliation names the company (molecule discovery).
3. ``run_pattern_fallback``: named contacts without an address get one built
   from the company's email pattern. The pattern comes from two or more
   addresses published on the company's own pages, or else from the pattern
   Hunter reported for the domain. Built addresses are labelled as such.
"""
from __future__ import annotations

import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from impurity_leads.contacts.normalize import normalize_person_name
from impurity_leads.contacts.patterns import detect_email_pattern, generate_pattern_email
from impurity_leads.seed_sources import qualified_companies

HUNTER_URL = "https://api.hunter.io/v2/domain-search"
ACCOUNT_URL = "https://api.hunter.io/v2/account"
DEFAULT_MAX_SEARCHES_PER_RUN = 5
DOMAIN_RECHECK_DAYS = 30
# The free plan errors when limit + offset exceeds 10.
RESULT_LIMIT = 10
MAX_CONFIDENCE = 0.6
SOURCE_TYPE = "HUNTER_DOMAIN_SEARCH"
PATTERN_SOURCE_TYPE = "EMAIL_PATTERN"
PUBLIC_PATTERN_CONFIDENCE = 0.5
HUNTER_PATTERN_CONFIDENCE = 0.35
# Roles that buy or specify impurity, analytical and regulatory work.
RELEVANT_ROLE = re.compile(
    r"quality|analytic|cmc|regulat|impurit|process|r&d|research|development|chemist|"
    r"procure|sourcing|\bqa\b|\bqc\b|gmp|validation|stability|technical|scien|"
    r"director|head|vice president|\bvp\b|chief",
    re.I,
)
# Hunter's pattern notation -> the patterns contacts.patterns can build.
_HUNTER_PATTERNS = {
    "{first}.{last}": "first.last", "{first}{last}": "firstlast", "{f}.{last}": "f.last",
    "{f}{last}": "flast", "{first}{l}": "firstl", "{last}.{first}": "last.first", "{last}{f}": "lastf",
}


class HunterQuotaExhausted(Exception):
    """Hunter answered 429: the monthly allowance is used up."""


def _relevant(position: str | None) -> bool:
    return bool(position) and bool(RELEVANT_ROLE.search(position or ""))


def pattern_from_hunter(value: str | None) -> str | None:
    return _HUNTER_PATTERNS.get(str(value or "").strip().lower())


def hunter_domain_search(http, api_key: str, domain: str, *, limit: int = RESULT_LIMIT) -> dict[str, Any]:
    """Role-relevant personal addresses and the email pattern Hunter holds for a domain."""
    response = http.get(HUNTER_URL, params={"domain": domain, "api_key": api_key, "limit": limit, "type": "personal"})
    if response.status_code == 429:
        raise HunterQuotaExhausted()
    response.raise_for_status()
    data = response.json().get("data") or {}
    people = []
    for item in data.get("emails", []):
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
    return {"people": people, "pattern": pattern_from_hunter(data.get("pattern"))}


def hunter_people(http, api_key: str, domain: str, *, limit: int = RESULT_LIMIT) -> list[dict[str, Any]]:
    return hunter_domain_search(http, api_key, domain, limit=limit)["people"]


def contact_confidence(hunter_confidence: float) -> float:
    """Hunter's 0-100 score, scaled and capped so it never reads as verified."""
    return round(min(MAX_CONFIDENCE, hunter_confidence / 100 * MAX_CONFIDENCE), 2)


def searches_for_today(account: dict[str, Any], *, today: date, cap: int) -> tuple[int, int | None]:
    """(searches to spend this run, searches left this period) from /v2/account.

    The remaining allowance is spread over the days until it resets. Unknown
    account data falls back to the configured cap; a 429 still stops the stage.
    """
    data = account.get("data") or {}
    searches = ((data.get("requests") or {}).get("searches")) or {}
    if "available" not in searches:
        return cap, None
    remaining = max(0, int(searches.get("available") or 0) - int(searches.get("used") or 0))
    days_left = 30
    try:
        days_left = max(1, (date.fromisoformat(str(data.get("reset_date"))[:10]) - today).days)
    except ValueError:
        pass
    return min(cap, math.ceil(remaining / days_left)), remaining


def _contact_source(contact_id: str, *, url: str, title: str, publisher: str, source_type: str, now: datetime,
                    evidence_strength: str, why_used: str) -> dict[str, Any]:
    return {
        "contact_id": contact_id, "url": url, "title": title, "publisher": publisher,
        "source_type": source_type, "source_date": now.date().isoformat(), "accessed_at": now.isoformat(),
        "status": "USED", "evidence_strength": evidence_strength, "why_used": why_used, "source_kind": source_type,
    }


def run_hunter_people(settings, client, *, http=None, api_key: str | None = None,
                      max_searches: int | None = None, now: datetime | None = None,
                      sleep: Callable[[float], None] | None = None) -> dict:
    api_key = api_key if api_key is not None else os.environ.get("HUNTER_API_KEY", "")
    if not api_key:
        return {"status": "SKIPPED", "reason": "hunter_api_key_not_set", "fallback": "free_sources_only"}
    cap = max_searches if max_searches is not None else int(os.environ.get("HUNTER_MAX_SEARCHES_PER_RUN", DEFAULT_MAX_SEARCHES_PER_RUN))
    now = now or datetime.now(timezone.utc)
    recheck_before = now - timedelta(days=DOMAIN_RECHECK_DAYS)
    owns_http = http is None
    http = http or httpx.Client(timeout=20, follow_redirects=False)
    searched, added, patterns, errors = 0, 0, 0, []
    status = "COMPLETED"
    try:
        try:
            account = http.get(ACCOUNT_URL, params={"api_key": api_key})
            account.raise_for_status()
            budget, remaining = searches_for_today(account.json(), today=now.date(), cap=cap)
        except (httpx.HTTPError, ValueError) as error:
            budget, remaining = cap, None
            errors.append({"domain": "account", "error": type(error).__name__})
        if budget <= 0:
            return {"status": "QUOTA_EXHAUSTED", "searches_left": remaining, "searched": 0,
                    "fallback": "free_sources_only"}
        companies = [
            company for company in qualified_companies(client, "id,legal_name,normalized_name,domain,merged_into_company_id,people_checked_at").values()
            if company.get("domain")
            and not (company.get("people_checked_at") and datetime.fromisoformat(str(company["people_checked_at"]).replace("Z", "+00:00")) > recheck_before)
        ]
        # Never-searched companies first, then those searched longest ago.
        companies.sort(key=lambda company: (company.get("people_checked_at") is not None, str(company.get("people_checked_at") or ""), company.get("legal_name") or ""))
        for company in companies[:budget]:
            domain = company["domain"]
            try:
                result = hunter_domain_search(http, api_key, domain)
            except HunterQuotaExhausted:
                status = "QUOTA_EXHAUSTED"
                break
            except httpx.HTTPError as error:
                # Never echo the URL: it carries the API key.
                errors.append({"domain": domain, "error": type(error).__name__})
                continue
            searched += 1
            for person in result["people"]:
                if not person["name"]:
                    continue
                row = {
                    "company_id": company["id"],
                    "normalized_name": normalize_person_name(person["name"]),
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
                    client.table("contact_sources").upsert(_contact_source(
                        contact_id, url=f"https://{domain}", title="Hunter.io domain search", publisher="Hunter.io",
                        source_type=SOURCE_TYPE, now=now, evidence_strength="THIRD_PARTY_DATABASE",
                        why_used="Personal address indexed by Hunter.io; not confirmed on a company page",
                    ), on_conflict="contact_id,url").execute()
                added += 1
            update: dict[str, Any] = {"people_checked_at": now.isoformat()}
            if result["pattern"]:
                update.update(email_pattern=result["pattern"], email_pattern_source="hunter")
                patterns += 1
            client.table("companies").update(update).eq("id", company["id"]).execute()
    finally:
        if owns_http:
            http.close()
    return {"status": status, "companies_waiting": len(companies), "searched": searched,
            "searches_left": None if remaining is None else max(0, remaining - searched),
            "contacts_upserted": added, "patterns_found": patterns, "errors": errors,
            "fallback": "free_sources_only" if status == "QUOTA_EXHAUSTED" else "free_sources_also_ran"}


def _chunks(values: list[str], size: int = 100):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def run_pattern_fallback(client, *, now: datetime | None = None) -> dict:
    """Give named contacts without an address one built from the company's pattern.

    A pattern seen in two or more addresses on the company's own pages is
    preferred (PATTERN_CONFIRMED). Otherwise the pattern Hunter reported is
    used, at lower confidence and labelled ROLE_ONLY. Existing addresses are
    never replaced.
    """
    now = now or datetime.now(timezone.utc)
    companies = {company_id: company for company_id, company in qualified_companies(
        client, "id,legal_name,normalized_name,domain,merged_into_company_id,email_pattern,email_pattern_source").items()
        if company.get("domain")}
    contacts: dict[str, list[dict]] = {}
    for ids in _chunks(list(companies)):
        rows = getattr(client.table("contacts").select("id,company_id,display_name,primary_email,email_status")
                       .in_("company_id", ids).execute(), "data", None) or []
        for row in rows:
            contacts.setdefault(row["company_id"], []).append(row)
    filled, public_patterns, hunter_patterns = 0, 0, 0
    for company_id, company in companies.items():
        rows = contacts.get(company_id, [])
        missing = [row for row in rows if not row.get("primary_email") and row.get("display_name")]
        if not missing:
            continue
        domain = str(company["domain"]).lower().removeprefix("www.")
        published = [(row["display_name"], row["primary_email"]) for row in rows
                     if row.get("primary_email") and row.get("email_status") == "VERIFIED_PUBLIC"]
        pattern = detect_email_pattern(published, domain)
        if pattern:
            status, confidence, origin = "PATTERN_CONFIRMED", PUBLIC_PATTERN_CONFIDENCE, "public"
            public_patterns += 1
            why = f"Address built from the {pattern} pattern seen in addresses published on {domain}; not itself published"
        elif company.get("email_pattern"):
            pattern = company["email_pattern"]
            status, confidence, origin = "ROLE_ONLY", HUNTER_PATTERN_CONFIDENCE, "hunter"
            hunter_patterns += 1
            why = f"Address built from the {pattern} pattern Hunter.io reports for {domain}; not confirmed for this person"
        else:
            continue
        for row in missing:
            email = generate_pattern_email(row["display_name"], domain, pattern)
            if not email:
                continue
            client.table("contacts").update({"primary_email": email, "email_status": status,
                                             "contact_confidence": confidence}).eq("id", row["id"]).execute()
            client.table("contact_sources").upsert(_contact_source(
                row["id"], url=f"https://{domain}#email-pattern", title=f"Email pattern ({origin})",
                publisher="Hunter.io" if origin == "hunter" else "Official company website",
                source_type=PATTERN_SOURCE_TYPE, now=now, evidence_strength="LOW", why_used=why,
            ), on_conflict="contact_id,url").execute()
            filled += 1
    return {"status": "COMPLETED", "companies": len(companies), "emails_built": filled,
            "public_patterns": public_patterns, "hunter_patterns": hunter_patterns}
