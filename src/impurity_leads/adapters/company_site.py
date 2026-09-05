from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from impurity_leads.classify import RULES, looks_like_impurity_vendor
from impurity_leads.extract import extract_evidence_windows
from impurity_leads.models import SourceRecord


class CompanySiteAdapter:
    name = "company_site"

    @staticmethod
    def _source_type(url: str) -> str:
        path = urlparse(url).path.lower()
        if "career" in path or "job" in path:
            return "job"
        if "tender" in path or "procurement" in path or "rfq" in path:
            return "tender"
        return "site"

    def parse_html(
        self,
        url: str,
        html: str,
        company_name: str,
        molecule_candidates: list[str],
    ) -> list[SourceRecord]:
        soup = BeautifulSoup(html, "lxml")
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        text = " ".join(soup.stripped_strings)
        lowered = text.lower()
        vendor = looks_like_impurity_vendor(text)
        molecules = [name for name in molecule_candidates if name.lower() in lowered]
        molecule = molecules[0] if molecules else None
        phrases = [phrase for rule in RULES for phrase in rule.phrases if phrase in lowered]
        evidence = extract_evidence_windows(text, phrases, window=180) if phrases else []

        metadata = {"is_impurity_vendor": vendor}
        records: list[SourceRecord] = []
        if evidence:
            for snippet in evidence:
                records.append(
                    SourceRecord(
                        source_name=self.name,
                        source_type=self._source_type(url),
                        source_url=url,
                        fetched_at=datetime.now(timezone.utc),
                        company_name_raw=company_name,
                        company_domain_raw=urlparse(url).netloc.lower(),
                        molecule_name_raw=molecule,
                        signal_text=snippet,
                        metadata_json=metadata,
                    )
                )
        elif vendor:
            records.append(
                SourceRecord(
                    source_name=self.name,
                    source_type=self._source_type(url),
                    source_url=url,
                    fetched_at=datetime.now(timezone.utc),
                    company_name_raw=company_name,
                    company_domain_raw=urlparse(url).netloc.lower(),
                    molecule_name_raw=molecule,
                    signal_text=text[:500],
                    metadata_json=metadata,
                )
            )
        return records
