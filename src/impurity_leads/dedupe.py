import hashlib
import re
from urllib.parse import urlsplit, urlunsplit


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def signal_fingerprint(
    company: str,
    molecule: str | None,
    signal_type: str,
    source_url: str,
    evidence_text: str,
) -> str:
    payload = "|".join(
        (_norm(company), _norm(molecule), signal_type, canonical_url(source_url), _norm(evidence_text))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
