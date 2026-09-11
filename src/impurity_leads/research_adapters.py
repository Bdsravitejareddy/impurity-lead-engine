"""Free source classification used by the provider-neutral research layer."""
from __future__ import annotations

from urllib.parse import urlparse


def classify_source(url: str, source_type: str | None = None) -> tuple[str, str]:
    """Return (source_class, canonical source type) without trusting snippets."""
    host = urlparse(url).netloc.casefold()
    kind = (source_type or "OTHER_PUBLIC_WEB").upper()
    if any(domain in host for domain in ("fda.gov", "ema.europa.eu", "cdsco.gov.in")):
        return "PRIMARY", "REGULATORY"
    if "patent" in host or "google.com" in host and "/patent" in urlparse(url).path:
        return "PRIMARY", "PATENT"
    if any(domain in host for domain in ("pubmed.ncbi.nlm.nih.gov", "europepmc.org", "crossref.org")):
        return "PRIMARY", "SCIENTIFIC_PUBLICATION"
    if any(domain in host for domain in ("linkedin.com", "rocketreach.co", "datanyze.com", "apollo.io", "zoominfo.com")):
        return ("DIRECTORY" if "linkedin.com" not in host else "STRONG_PROFESSIONAL"), "PROFESSIONAL_PROFILE"
    if kind in {"OFFICIAL_COMPANY", "COMPANY"}:
        return "PRIMARY", "OFFICIAL_COMPANY"
    if kind in {"CONFERENCE", "WEBINAR", "PROFESSIONAL_ASSOCIATION"}:
        return "STRONG_PROFESSIONAL", kind
    return "DISCOVERY_WEAK", kind
