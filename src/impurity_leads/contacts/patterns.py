from impurity_leads.contacts.normalize import normalize_email, normalize_person_name

_GENERIC_LOCAL_PARTS = {
    "info", "sales", "careers", "career", "jobs", "support", "contact",
    "procurement", "sourcing", "office", "admin", "hello", "team",
}
_CONSUMER_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "proton.me", "protonmail.com", "aol.com",
}
_SUPPORTED = ("first.last", "firstlast", "f.last", "flast", "firstl", "last.first", "lastf")


def _name_parts(person_name: str) -> tuple[str, str] | None:
    parts = normalize_person_name(person_name).split()
    if len(parts) < 2:
        return None
    first = parts[0]
    last = parts[-1]
    if not first or not last:
        return None
    return first, last


def _local_for(person_name: str, pattern: str) -> str | None:
    parts = _name_parts(person_name)
    if not parts:
        return None
    first, last = parts
    mapping = {
        "first.last": f"{first}.{last}",
        "firstlast": f"{first}{last}",
        "f.last": f"{first[0]}.{last}",
        "flast": f"{first[0]}{last}",
        "firstl": f"{first}{last[0]}",
        "last.first": f"{last}.{first}",
        "lastf": f"{last}{first[0]}",
    }
    return mapping.get(pattern)


def generate_pattern_email(person_name: str, company_domain: str, pattern: str) -> str | None:
    domain = company_domain.strip().casefold().removeprefix("www.")
    if not domain or domain in _CONSUMER_DOMAINS or pattern not in _SUPPORTED:
        return None
    local = _local_for(person_name, pattern)
    return f"{local}@{domain}" if local else None


def detect_email_pattern(named_emails: list[tuple[str, str]], company_domain: str) -> str | None:
    domain = company_domain.strip().casefold().removeprefix("www.")
    if not domain or domain in _CONSUMER_DOMAINS:
        return None

    valid: list[tuple[str, str]] = []
    seen_people: set[str] = set()
    for person_name, email in named_emails:
        normalized_person = normalize_person_name(person_name)
        normalized_email = normalize_email(email)
        if not normalized_person or not normalized_email or normalized_person in seen_people:
            continue
        local, email_domain = normalized_email.rsplit("@", 1)
        if email_domain != domain or local in _GENERIC_LOCAL_PARTS:
            continue
        if _name_parts(person_name) is None:
            continue
        valid.append((person_name, local))
        seen_people.add(normalized_person)

    if len(valid) < 2:
        return None

    common: set[str] = set(_SUPPORTED)
    for person_name, observed_local in valid:
        matches = {pattern for pattern in _SUPPORTED if _local_for(person_name, pattern) == observed_local}
        common &= matches
        if not common:
            return None

    return next(iter(common)) if len(common) == 1 else None
