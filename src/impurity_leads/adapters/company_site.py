import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from dateutil.parser import isoparse

from impurity_leads.classify import RULES, looks_like_impurity_vendor
from impurity_leads.extract import extract_evidence_windows_at
from impurity_leads.models import SourceRecord


def _molecule_mentions(text: str, names: list[str]) -> list[tuple[int, str]]:
    """Whole-word mentions: "Ala" is not in "alanine", nor "ABC-12" in "ABC-123"."""
    mentions = []
    for name in names:
        if not name.strip():
            continue
        pattern = re.compile(r"(?<!\w)(?<!\w-)" + re.escape(name.strip()) + r"(?!\w)(?!-\w)", re.I)
        mentions.extend((match.start(), name) for match in pattern.finditer(text))
    return sorted(mentions)


def _nearest(mentions: list[tuple[int, str]], index: int) -> str | None:
    return min(mentions, key=lambda mention: abs(mention[0] - index))[1] if mentions else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _published_at(soup: BeautifulSoup, last_modified: str | None) -> datetime | None:
    meta = soup.find("meta", attrs={"property": "article:published_time"}) or soup.find("meta", attrs={"name": "article:published_time"})
    candidates = [meta.get("content") if meta else None]
    candidates += [node.get("datetime") for node in soup.find_all("time") if node.get("datetime")]
    for value in filter(None, candidates):
        try:
            return _aware(isoparse(value.strip()))
        except (ValueError, OverflowError):
            continue
    if last_modified:
        try:
            return _aware(parsedate_to_datetime(last_modified))
        except (TypeError, ValueError, OverflowError):
            return None
    return None


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
        last_modified: str | None = None,
    ) -> list[SourceRecord]:
        soup = BeautifulSoup(html, "lxml")
        published_at = _published_at(soup, last_modified)
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        text = " ".join(soup.stripped_strings)
        lowered = text.lower()
        vendor = looks_like_impurity_vendor(text)
        mentions = _molecule_mentions(text, molecule_candidates)
        phrases = [phrase for rule in RULES for phrase in rule.phrases if phrase in lowered]
        evidence = extract_evidence_windows_at(text, phrases, window=180) if phrases else []

        metadata = {"is_impurity_vendor": vendor}
        records: list[SourceRecord] = []
        if evidence:
            for snippet, index in evidence:
                records.append(
                    SourceRecord(
                        source_name=self.name,
                        source_type=self._source_type(url),
                        source_url=url,
                        fetched_at=datetime.now(timezone.utc),
                        company_name_raw=company_name,
                        company_domain_raw=urlparse(url).netloc.lower(),
                        molecule_name_raw=_nearest(mentions, index),
                        signal_text=snippet,
                        published_at=published_at,
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
                    molecule_name_raw=mentions[0][1] if mentions else None,
                    signal_text=text[:500],
                    published_at=published_at,
                    metadata_json=metadata,
                )
            )
        return records
