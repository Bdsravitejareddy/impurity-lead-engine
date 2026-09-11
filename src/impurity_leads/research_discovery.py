"""Provider-neutral public-source discovery contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.parse import quote


@dataclass(frozen=True)
class SearchRequest:
    query: str
    seed_type: str
    seed_id: str | None = None
    target_dimension: str = "TECHNICAL_EVIDENCE"
    max_results: int = 5


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str = ""
    domain: str = ""
    discovered_via: str = "direct"
    source_type: str = "OTHER_PUBLIC_WEB"
    metadata: dict[str, Any] | None = None


class DiscoveryProvider:
    name = "provider"

    def discover(self, request: SearchRequest) -> list[SearchResult]:
        raise NotImplementedError


class EuropePmcProvider(DiscoveryProvider):
    name = "europe_pmc"

    def __init__(self, fetch_json: Callable[[str], dict[str, Any]], base_url: str = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"):
        self.fetch_json = fetch_json
        self.base_url = base_url

    def discover(self, request: SearchRequest) -> list[SearchResult]:
        url = f"{self.base_url}?query={quote(request.query)}&format=json&pageSize={min(request.max_results, 25)}"
        payload = self.fetch_json(url)
        results: list[SearchResult] = []
        for item in (payload.get("resultList") or {}).get("result", [])[:request.max_results]:
            identifier = item.get("pmid") or item.get("id")
            if not identifier:
                continue
            results.append(SearchResult(
                url=f"https://europepmc.org/article/MED/{identifier}",
                title=str(item.get("title") or "Europe PMC result"),
                snippet=str(item.get("abstractText") or "")[:500],
                domain="europepmc.org",
                discovered_via=self.name,
                source_type="SCIENTIFIC_PUBLICATION",
                metadata=item,
            ))
        return results


def dedupe_results(results: Iterable[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    output: list[SearchResult] = []
    for result in results:
        key = result.url.casefold().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(result)
    return output
