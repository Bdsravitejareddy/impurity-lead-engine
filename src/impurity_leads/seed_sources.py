"""Company seeds for the daily crawl, built without manual upkeep.

Company-site crawling and contact enrichment only run for seeded companies.
The seed list used to come solely from the COMPANY_SEEDS_CSV secret, which
produced zero seeds in production, so neither stage ever ran. Seeds now come
from the database: every company with a qualified opportunity and a known
website. Companies without a website get one discovered automatically, verified
against the company name before it is stored.
"""
from __future__ import annotations

import re
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import httpx

from impurity_leads.crawling.robots import RobotsPolicy
from impurity_leads.molecule_discovery import company_tokens
from impurity_leads.seeds import CompanySeed, _normalize_domain, load_company_seeds

PAGE_SIZE = 1000
QUALIFYING_SCORE = 50
DOMAIN_LOOKUPS_PER_RUN = 25
DOMAIN_RECHECK_DAYS = 30
MAX_CANDIDATES = 12
# Country-code endings tried after .com, for the regions the leads come from.
_DOMAIN_ENDINGS = (".com", ".co.in", ".in", ".de", ".ch", ".co.jp", ".cn")
# Ordinary words that also appear in company names; a host or title matching
# only these says nothing about which company owns the site.
_COMMON_WORDS = {
    "development", "research", "international", "global", "medical", "medicine", "health", "bio",
    "biotech", "technologies", "technology", "systems", "products", "solutions", "partners",
    "specialty", "generics", "ventures", "america", "usa", "europe", "india", "china", "japan",
    "national", "united", "new", "first", "advanced", "applied", "clinical", "drug", "drugs",
}
# Parking services redirect to hosts like ww16.example.com.
_PARKED_HOST = re.compile(r"^ww\d+\.")
# A pharma company's homepage mentions what it does; parked or unrelated sites do not.
_INDUSTRY_CUE = re.compile(r"pharm|medicin|therapeut|patient|clinical|biotech|oncolog|drug|generic|health ?care|life ?science", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_SITE_NAME = re.compile(r"""<meta[^>]+property=["']og:site_name["'][^>]+content=["']([^"']+)""", re.I)


def _paged(query_builder: Callable[[], Any]) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        page = list(getattr(query_builder().range(start, start + PAGE_SIZE - 1).execute(), "data", None) or [])
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def merge_seeds(*groups: Iterable[CompanySeed]) -> list[CompanySeed]:
    """One seed per domain; molecules from every source are kept."""
    by_domain: dict[str, CompanySeed] = {}
    for group in groups:
        for seed in group:
            existing = by_domain.get(seed.domain)
            if existing is None:
                by_domain[seed.domain] = seed
                continue
            molecules = list(dict.fromkeys([*existing.molecules, *seed.molecules]))
            by_domain[seed.domain] = CompanySeed(company_name=existing.company_name, domain=existing.domain, molecules=molecules)
    return sorted(by_domain.values(), key=lambda seed: seed.domain)


def qualified_companies(client, company_columns: str = "id,legal_name,normalized_name,domain,merged_into_company_id") -> dict[str, dict]:
    """Surviving company rows that own a qualified opportunity, with its molecules.

    An opportunity stored on a soft-merged company counts for its survivor.
    """
    companies = {row["id"]: row for row in _paged(lambda: client.table("companies").select(company_columns).order("id"))}

    def survivor(company_id: str) -> str:
        for _ in range(10):
            merged_into = (companies.get(company_id) or {}).get("merged_into_company_id")
            if not merged_into:
                break
            company_id = merged_into
        return company_id

    opportunities = _paged(lambda: client.table("opportunities")
                           .select("company_id,status,molecules(canonical_name)")
                           .gte("score", QUALIFYING_SCORE).order("company_id").order("molecule_id"))
    output: dict[str, dict] = {}
    for row in opportunities:
        if str(row.get("status") or "").lower() == "dismissed" or not row.get("company_id"):
            continue
        company = companies.get(survivor(row["company_id"]))
        if not company:
            continue
        entry = output.setdefault(company["id"], {**company, "molecules": []})
        molecule = (row.get("molecules") or {}).get("canonical_name")
        if molecule and molecule not in entry["molecules"]:
            entry["molecules"].append(molecule)
    return output


def database_seeds(client) -> list[CompanySeed]:
    """Companies with a qualified opportunity and a website, with their molecules."""
    seeds = []
    for company in qualified_companies(client).values():
        name = company.get("legal_name") or company.get("normalized_name")
        if company.get("domain") and name:
            seeds.append(CompanySeed(company_name=name, domain=_normalize_domain(company["domain"]), molecules=company["molecules"]))
    return merge_seeds(seeds)


def load_run_seeds(settings, root: str | Path, client_factory: Callable[[], Any] | None = None) -> list[CompanySeed]:
    """Seeds from the optional CSV override plus every qualified company in the database."""
    csv_path = Path(root) / "seeds/companies.csv"
    csv_seeds = merge_seeds(load_company_seeds(csv_path)) if csv_path.exists() else []
    if client_factory is None:
        if not (getattr(settings, "supabase_url", None) and getattr(settings, "supabase_secret_key", None)):
            return csv_seeds
        from supabase import create_client

        def client_factory():
            return create_client(settings.supabase_url, settings.supabase_secret_key)
    try:
        return merge_seeds(csv_seeds, database_seeds(client_factory()))
    except Exception:
        # A seed read failure must not stop the structured-source crawl.
        return csv_seeds


# ---------------------------------------------------------------------------
# Website discovery


def _name_tokens(company_name: str) -> list[str]:
    return [token for token in company_tokens(company_name) if token not in _COMMON_WORDS]


def domain_candidates(company_name: str) -> list[str]:
    """Likely website hosts for a company name, most likely first."""
    tokens = _name_tokens(company_name)
    if not tokens:
        return []
    stems: list[str] = []
    if len(tokens[0]) >= 4:
        stems.append(tokens[0])
    if len(tokens) >= 2:
        stems.append(tokens[0] + tokens[1])
        stems.append(tokens[0] + "-" + tokens[1])
    if len(tokens) >= 3:
        stems.append("".join(tokens[:3]))
    stems.append(tokens[0] + "pharma")
    stems = list(dict.fromkeys(stems))
    # Every stem with .com first, then the country endings.
    candidates = [stem + ending for ending in _DOMAIN_ENDINGS for stem in stems]
    return candidates[:MAX_CANDIDATES]


def _resolves(host: str) -> bool:
    """Skip unregistered names without an HTTP request."""
    try:
        socket.getaddrinfo(host, 443)
        return True
    except (socket.gaierror, UnicodeError, OSError):
        return False


def _page_names(html: str) -> str:
    parts = [match.group(1) for pattern in (_TITLE, _SITE_NAME) for match in [pattern.search(html or "")] if match]
    return " ".join(re.sub(r"\s+", " ", part) for part in parts).casefold()


def verify_domain(http, candidate: str, company_name: str, user_agent: str) -> str | None:
    """Return the verified host when the site's title names the company.

    The first distinctive word must be in the host, and every distinctive word
    in the page title or site name, so parked or unrelated domains are rejected.
    """
    tokens = _name_tokens(company_name)
    if not tokens:
        return None
    base = f"https://{candidate}"
    try:
        robots = RobotsPolicy.fetch(http, base, user_agent)
        if robots.disallow_all or not robots.can_fetch(base + "/"):
            return None
        response = http.get(base + "/", headers={"User-Agent": user_agent})
    except (httpx.HTTPError, ValueError):
        return None
    if getattr(response, "status_code", 0) != 200:
        return None
    host = urlparse(str(getattr(response, "url", base))).netloc.lower().removeprefix("www.") or candidate
    html = getattr(response, "text", "") or ""
    if _PARKED_HOST.match(host) or not _INDUSTRY_CUE.search(html[:300_000]):
        return None
    names = _page_names(html)
    title_words = set(re.sub(r"[^a-z0-9 ]", " ", names).split())
    if tokens[0] not in host.replace("-", "") or not all(token in title_words for token in tokens):
        return None
    return host


def discover_missing_domains(settings, *, client=None, http=None, limit: int = DOMAIN_LOOKUPS_PER_RUN,
                             now: datetime | None = None, pause: float = 1.0,
                             resolves: Callable[[str], bool] = _resolves) -> dict:
    """Find websites for qualified companies that have none, and store them."""
    if client is None:
        if not (getattr(settings, "supabase_url", None) and getattr(settings, "supabase_secret_key", None)):
            return {"status": "SKIPPED", "reason": "supabase_credentials_missing"}
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_secret_key)
    now = now or datetime.now(timezone.utc)
    recheck_before = now - timedelta(days=DOMAIN_RECHECK_DAYS)
    pending: dict[str, dict] = {}
    for company in qualified_companies(client, "id,legal_name,normalized_name,domain,merged_into_company_id,domain_checked_at").values():
        checked = company.get("domain_checked_at")
        if company.get("domain"):
            continue
        if checked and datetime.fromisoformat(str(checked).replace("Z", "+00:00")) > recheck_before:
            continue
        pending[company["id"]] = company
    user_agent = getattr(settings, "user_agent", "impurity-lead-engine")
    owns_http = http is None
    http = http or httpx.Client(timeout=15, follow_redirects=True)
    found, missed = [], []
    try:
        for company in list(pending.values())[:limit]:
            name = company.get("legal_name") or company.get("normalized_name") or ""
            host = None
            for candidate in domain_candidates(name):
                if not resolves(candidate):
                    continue
                host = verify_domain(http, candidate, name, user_agent)
                if pause:
                    time.sleep(pause)
                if host:
                    break
            update = {"domain_checked_at": now.isoformat()}
            if host:
                update.update(domain=host, domain_source="AUTO_DISCOVERED")
                found.append({"company": name, "domain": host})
            else:
                missed.append(name)
            client.table("companies").update(update).eq("id", company["id"]).execute()
    finally:
        if owns_http:
            http.close()
    return {"status": "COMPLETED", "pending": len(pending), "checked": len(found) + len(missed),
            "found": found, "not_found": missed}
