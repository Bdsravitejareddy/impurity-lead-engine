"""Deterministic extraction from public pages on a company's own domain."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from impurity_leads.classify import RULES, classify_signal, looks_like_impurity_vendor
from impurity_leads.extract import extract_evidence_windows
from impurity_leads.models import SourceRecord


def _host(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").casefold().removeprefix("www.").rstrip(".")


def is_company_url(url: str, company_domain: str) -> bool:
    """Return whether *url* is HTTPS/HTTP on the supplied company domain."""
    parsed = urlparse(url)
    host = _host(url)
    expected = _host(company_domain)
    return parsed.scheme in {"http", "https"} and bool(expected) and (host == expected or host.endswith(f".{expected}"))


def _normalise_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _visible_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for node in soup(["script", "style", "noscript", "template", "svg"]):
        node.decompose()
    return " ".join(soup.stripped_strings), title[:300]


def parse_official_company_html(
    url: str,
    html: str,
    company_name: str,
    company_domain: str,
    *,
    contact_name: str | None = None,
    molecule_candidates: list[str] | None = None,
) -> list[SourceRecord]:
    """Extract one conservative evidence record from an official company page.

    The function is intentionally pure: fetching, retry policy and persistence
    stay with the caller. A page must be on the expected domain, contain a
    classified technical signal, and not look like an impurity vendor page.
    """
    if not is_company_url(url, company_domain):
        return []
    text, page_title = _visible_text(html)
    lowered = text.casefold()
    if not text or looks_like_impurity_vendor(text) or "custom impurity synthesis" in lowered:
        return []
    matches = classify_signal(text, bool(molecule_candidates and any(m.casefold() in lowered for m in molecule_candidates)))
    if not matches:
        return []
    phrases = [phrase for rule in RULES for phrase in rule.phrases if phrase in lowered]
    windows = extract_evidence_windows(text, phrases, window=220)
    signal_text = " ".join(windows)[:1200] if windows else text[:1200]
    molecules = [molecule for molecule in (molecule_candidates or []) if molecule.casefold() in lowered]
    normalized_contact = _normalise_name(contact_name or "")
    contact_match = bool(normalized_contact and normalized_contact in _normalise_name(text))
    return [
        SourceRecord(
            source_name="official_company",
            source_type="official_company",
            source_url=url,
            fetched_at=datetime.now(timezone.utc),
            company_name_raw=company_name,
            company_domain_raw=_host(company_domain),
            molecule_name_raw=molecules[0] if molecules else None,
            signal_text=signal_text,
            metadata_json={
                "page_title": page_title,
                "contact_name_match": contact_match,
                "matched_signal_types": [signal_type for signal_type, _, _ in matches],
                "source_class": "PRIMARY",
            },
        )
    ]
