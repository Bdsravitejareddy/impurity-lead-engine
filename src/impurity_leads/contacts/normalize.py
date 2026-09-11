import re
import unicodedata

_HONORIFICS = {"dr", "prof", "mr", "mrs", "ms", "miss", "sir"}
_ACADEMIC_SUFFIXES = {"phd", "md", "do", "mba", "rn", "dds", "dvm", "esq", "jd", "cpa"}
_EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)


def normalize_person_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    parts = [part for part in text.split() if part and part not in _HONORIFICS]
    # PDF/HTML sources commonly render ``Ph.D.`` as separate tokens. Strip
    # only terminal academic/professional suffixes; preserve initials and
    # meaningful middle names.
    while parts and parts[-1] in _ACADEMIC_SUFFIXES:
        parts.pop()
    if len(parts) >= 2 and parts[-2:] == ["ph", "d"]:
        parts = parts[:-2]
    return " ".join(parts)


def person_name_compatibility(canonical: str, candidate: str) -> float:
    """Return a conservative name-only compatibility score in [0, 1].

    This is a candidate-generation aid, never an authorization to merge a
    common name without company/profile/role context.
    """
    expected = normalize_person_name(canonical).split()
    observed = normalize_person_name(candidate).split()
    if not expected or not observed:
        return 0.0
    if expected == observed:
        return 1.0
    if len(expected) >= 2 and len(observed) >= 2:
        if expected[0] == observed[0] and observed[-1] == expected[-1][0]:
            return 0.82
        if observed[0] == expected[0][0] and observed[-1] == expected[-1]:
            return 0.80
        if expected[0] == observed[0] and expected[-1] == observed[-1]:
            return 0.92
    return 0.0


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
