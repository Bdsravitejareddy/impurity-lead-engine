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
            domain_raw = (row.get("domain") or "").strip()
            molecules_raw = (row.get("molecules") or "").strip()
            domain = _normalize_domain(domain_raw)
            # A repeated CSV header is data to DictReader, so reject it before
            # normalizing ("domain" would otherwise become a valid hostname).
            if (company_name.casefold() == "company_name"
                    and domain == "domain"
                    and molecules_raw.casefold() == "molecules"):
                continue
            molecules = [item.strip() for item in molecules_raw.split(";") if item.strip()]
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
