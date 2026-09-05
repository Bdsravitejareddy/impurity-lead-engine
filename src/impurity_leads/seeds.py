import csv
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from impurity_leads.adapters.common_crawl import DEFAULT_TERMS


@dataclass(frozen=True)
class CompanySeed:
    company_name: str
    domain: str
    molecules: list[str]


def _normalize_domain(value: str) -> str:
    value = value.strip().lower()
    if "://" not in value:
        value = f"https://{value}"
    host = urlparse(value).netloc.lower()
    return host.removeprefix("www.")


def load_company_seeds(path: str | Path) -> list[CompanySeed]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        output: list[CompanySeed] = []
        for row in rows:
            company_name = (row.get("company_name") or "").strip()
            domain = _normalize_domain(row.get("domain") or "")
            molecules = [item.strip() for item in (row.get("molecules") or "").split(";") if item.strip()]
            if company_name and domain:
                output.append(CompanySeed(company_name=company_name, domain=domain, molecules=molecules))
        return output


def relevant_candidate_urls(
    domain: str,
    sitemap_urls: list[str],
    common_urls: list[str],
    cap: int = 15,
) -> list[str]:
    normalized_domain = _normalize_domain(domain)
    output: list[str] = []
    seen: set[str] = set()
    for url in [*sitemap_urls, *common_urls]:
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        if host != normalized_domain:
            continue
        haystack = f"{parsed.path}?{parsed.query}".lower()
        if not any(term in haystack for term in DEFAULT_TERMS):
            continue
        if url in seen:
            continue
        seen.add(url)
        output.append(url)
        if len(output) >= cap:
            break
    return output
