"""Provider-neutral bounded public research discovery."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from impurity_leads.official_company import parse_official_company_html


@dataclass(frozen=True)
class OfficialCompanyRequest:
    contact_id: str
    contact_name: str
    company_name: str
    company_domain: str
    urls: tuple[str, ...]
    molecule_candidates: tuple[str, ...] = ()
    max_pages: int = 4


@dataclass(frozen=True)
class ProviderCandidate:
    url: str
    title: str
    source_type: str
    signal_text: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    candidates: tuple[ProviderCandidate, ...]
    metrics: dict[str, int]


class OfficialCompanyProvider:
    name = "official_company"

    def discover(
        self,
        request: OfficialCompanyRequest,
        fetcher: Callable[[str], str],
    ) -> ProviderResult:
        candidates: list[ProviderCandidate] = []
        attempted = failed = 0
        for url in request.urls[: max(0, request.max_pages)]:
            attempted += 1
            try:
                html = fetcher(url)
            except Exception:
                failed += 1
                continue
            if not html:
                failed += 1
                continue
            records = parse_official_company_html(
                url,
                html,
                request.company_name,
                request.company_domain,
                contact_name=request.contact_name,
                molecule_candidates=list(request.molecule_candidates),
            )
            for record in records:
                candidates.append(
                    ProviderCandidate(
                        url=record.source_url,
                        title=record.metadata_json.get("page_title") or record.source_type,
                        source_type=record.source_type,
                        signal_text=record.signal_text,
                        metadata=dict(record.metadata_json),
                    )
                )
        return ProviderResult(
            candidates=tuple(candidates),
            metrics={"pages_attempted": attempted, "pages_accepted": len(candidates), "pages_failed": failed},
        )
