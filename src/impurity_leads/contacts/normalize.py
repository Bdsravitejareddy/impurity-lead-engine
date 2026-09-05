import re
import unicodedata

_HONORIFICS = {"dr", "prof", "mr", "mrs", "ms", "miss", "sir"}
_EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)


def normalize_person_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    parts = [part for part in text.split() if part and part not in _HONORIFICS]
    return " ".join(parts)


def normalize_email(value: str) -> str | None:
    candidate = value.strip().strip("<>.,;:").casefold()
    if not _EMAIL_RE.match(candidate):
        return None
    return candidate


def email_domain(value: str) -> str | None:
    normalized = normalize_email(value)
    return normalized.rsplit("@", 1)[1] if normalized else None


def normalize_phone(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None
    leading_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7 or len(digits) > 15:
        return None
    return f"+{digits}" if leading_plus else digits


def title_family(title: str) -> str | None:
    value = title.casefold()
    if any(token in value for token in ("analytical", "analysis", "bioanalytical")):
        return "analytical"
    if any(token in value for token in ("cmc", "chemistry manufacturing", "technical operations", "tech ops")):
        return "cmc"
    if any(token in value for token in ("process development", "api development", "process chemistry", "api")):
        return "api_process"
    if any(token in value for token in ("quality", "quality control", "qc", "compliance")):
        return "quality"
    if any(token in value for token in ("regulatory", "reg affairs")):
        return "regulatory"
    if any(token in value for token in ("procurement", "sourcing", "purchasing", "buyer")):
        return "procurement"
    if any(token in value for token in ("stability", "forced degradation")):
        return "stability"
    if any(token in value for token in ("toxicology", "toxicologist")):
        return "toxicology"
    if any(token in value for token in ("chief executive", "ceo", "chief financial", "cfo")):
        return "executive"
    return None
