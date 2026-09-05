import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from impurity_leads.contacts.models import ContactCandidate, ContactEvidence
from impurity_leads.contacts.normalize import (
    email_domain,
    normalize_email,
    normalize_person_name,
    normalize_phone,
    title_family,
)

_NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,4}$")
_VISIBLE_EMAIL_RE = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)

_ROLE_HINTS = (
    "director",
    "head",
    "vice president",
    "vp",
    "manager",
    "scientist",
    "analytical",
    "cmc",
    "quality",
    "regulatory",
    "procurement",
    "sourcing",
    "development",
)


def _fingerprint(person: str, evidence_type: str, value: str, url: str) -> str:
    payload = "|".join((normalize_person_name(person), evidence_type, value.casefold().strip(), url))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evidence(
    person: str,
    evidence_type: str,
    value: str,
    source_type: str,
    source_url: str,
    evidence_text: str,
    observed_at: datetime,
    metadata: dict | None = None,
) -> ContactEvidence:
    return ContactEvidence(
        evidence_type=evidence_type,
        observed_value=value,
        source_type=source_type,
        source_url=source_url,
        evidence_text=evidence_text[:800],
        observed_at=observed_at,
        fingerprint=_fingerprint(person, evidence_type, value, source_url),
        metadata_json=metadata or {},
    )


def _iter_jsonld_people(value):
    if isinstance(value, list):
        for item in value:
            yield from _iter_jsonld_people(item)
    elif isinstance(value, dict):
        kind = value.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "Person" in kinds:
            yield value
        if "@graph" in value:
            yield from _iter_jsonld_people(value["@graph"])


def _plausible_name(value: str) -> bool:
    clean = re.sub(r"\s+", " ", value.strip())
    normalized = normalize_person_name(clean)
    return bool(normalized and _NAME_RE.match(clean.replace("Dr. ", "").replace("Dr ", "")))


def _candidate_from_fields(
    *,
    company_name: str,
    name: str,
    title: str | None,
    profile_url: str | None,
    email: str | None,
    phone: str | None,
    source_type: str,
    source_url: str,
    observed_at: datetime,
    evidence_text: str,
    exact_confidence: float,
) -> ContactCandidate | None:
    normalized_name = normalize_person_name(name)
    if not normalized_name:
        return None
    raw_email = email.removeprefix("mailto:").strip() if email else None
    raw_phone = phone.removeprefix("tel:").strip() if phone else None
    normalized_email = normalize_email(raw_email) if raw_email else None
    normalized_phone = normalize_phone(raw_phone) if raw_phone else None
    source_domain = urlparse(source_url).netloc.casefold().removeprefix("www.")
    observed_domain = email_domain(normalized_email) if normalized_email else None
    domain_match = bool(observed_domain and (source_domain == observed_domain or source_domain.endswith(f".{observed_domain}")))
    exact_email = normalized_email if normalized_email and domain_match else None
    evidence: list[ContactEvidence] = [
        _evidence(name, "identity", name, source_type, source_url, evidence_text, observed_at),
    ]
    if title:
        evidence.append(_evidence(name, "title", title, source_type, source_url, evidence_text, observed_at))
    if exact_email:
        evidence.append(_evidence(name, "email", exact_email, source_type, source_url, evidence_text, observed_at))
    if normalized_phone:
        evidence.append(_evidence(
            name, "phone", normalized_phone, source_type, source_url, evidence_text, observed_at,
            metadata={"raw_value": raw_phone or normalized_phone},
        ))
    return ContactCandidate(
        company_name=company_name,
        display_name=name.strip(),
        normalized_name=normalized_name,
        title=title.strip() if title else None,
        department=title_family(title) if title else None,
        profile_url=profile_url,
        primary_email=exact_email,
        email_status="VERIFIED_PUBLIC" if exact_email else "ROLE_ONLY",
        primary_phone=normalized_phone,
        phone_status="VERIFIED_PUBLIC" if normalized_phone else "ROLE_ONLY",
        contact_confidence=exact_confidence if exact_email or normalized_phone else 0.55,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
        last_verified_at=observed_at,
        evidence=evidence,
    )


def _merge_candidates(candidates: list[ContactCandidate]) -> list[ContactCandidate]:
    merged: dict[str, ContactCandidate] = {}
    for candidate in candidates:
        key = candidate.normalized_name
        current = merged.get(key)
        if current is None:
            merged[key] = candidate
            continue
        if not current.title and candidate.title:
            current.title = candidate.title
            current.department = candidate.department
        if not current.profile_url and candidate.profile_url:
            current.profile_url = candidate.profile_url
        if not current.primary_email and candidate.primary_email:
            current.primary_email = candidate.primary_email
            current.email_status = candidate.email_status
        if not current.primary_phone and candidate.primary_phone:
            current.primary_phone = candidate.primary_phone
            current.phone_status = candidate.phone_status
        current.contact_confidence = max(current.contact_confidence, candidate.contact_confidence)
        known = {item.fingerprint for item in current.evidence}
        current.evidence.extend(item for item in candidate.evidence if item.fingerprint not in known)
    return list(merged.values())


def extract_contacts_from_html(
    url: str,
    html: str,
    company_name: str,
    observed_at: datetime,
) -> list[ContactCandidate]:
    soup = BeautifulSoup(html, "lxml")
    candidates: list[ContactCandidate] = []

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for person in _iter_jsonld_people(payload):
            name = str(person.get("name") or "").strip()
            if not name:
                continue
            candidate = _candidate_from_fields(
                company_name=company_name,
                name=name,
                title=str(person.get("jobTitle") or "").strip() or None,
                profile_url=urljoin(url, str(person.get("url") or "")) if person.get("url") else None,
                email=str(person.get("email") or "").strip() or None,
                phone=str(person.get("telephone") or "").strip() or None,
                source_type="company_site",
                source_url=url,
                observed_at=observed_at,
                evidence_text=json.dumps(person, ensure_ascii=False),
                exact_confidence=1.0,
            )
            if candidate:
                candidates.append(candidate)

    card_selectors = "[class*='person'],[class*='leader'],[class*='team'],[class*='contact'],article,section"
    for card in soup.select(card_selectors):
        text = " ".join(card.stripped_strings)
        if not text or not any(hint in text.casefold() for hint in _ROLE_HINTS):
            continue
        heading = card.find(["h1", "h2", "h3", "h4", "strong"])
        if not isinstance(heading, Tag):
            continue
        name = " ".join(heading.stripped_strings)
        if not _plausible_name(name):
            continue
        title = None
        for node in card.find_all(["p", "span", "div"], limit=8):
            candidate_title = " ".join(node.stripped_strings)
            if candidate_title and candidate_title != name and any(hint in candidate_title.casefold() for hint in _ROLE_HINTS):
                title = candidate_title
                break
        mail = card.find("a", href=re.compile(r"^mailto:", re.I))
        visible_email = _VISIBLE_EMAIL_RE.search(text)
        tel = card.find("a", href=re.compile(r"^tel:", re.I))
        profile = card.find("a", href=True)
        candidate = _candidate_from_fields(
            company_name=company_name,
            name=name,
            title=title,
            profile_url=urljoin(url, profile["href"]) if profile and not str(profile["href"]).startswith(("mailto:", "tel:")) else None,
            email=mail["href"] if mail else (visible_email.group(0) if visible_email else None),
            phone=tel["href"] if tel else None,
            source_type="company_site",
            source_url=url,
            observed_at=observed_at,
            evidence_text=text,
            exact_confidence=1.0,
        )
        if candidate:
            candidates.append(candidate)

    return _merge_candidates(candidates)


def extract_trial_contacts(
    payload: dict,
    company_name: str,
    source_url: str,
    observed_at: datetime,
) -> list[ContactCandidate]:
    contacts_module = (
        payload.get("protocolSection", {})
        .get("contactsLocationsModule", {})
    )
    officials = {
        normalize_person_name(str(item.get("name") or "")): item
        for item in contacts_module.get("overallOfficials", [])
        if item.get("name")
    }
    candidates: list[ContactCandidate] = []
    for item in contacts_module.get("centralContacts", []):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        official = officials.get(normalize_person_name(name), {})
        title = str(official.get("role") or item.get("role") or "").replace("_", " ").title() or None
        email = normalize_email(str(item.get("email") or ""))
        phone = normalize_phone(str(item.get("phone") or ""))
        text = " | ".join(str(value) for value in (name, title, item.get("email"), item.get("phone"), official.get("affiliation")) if value)
        evidence = [_evidence(name, "identity", name, "clinical_trials", source_url, text, observed_at)]
        if title:
            evidence.append(_evidence(name, "title", title, "clinical_trials", source_url, text, observed_at))
        if official.get("affiliation"):
            evidence.append(_evidence(name, "affiliation", str(official["affiliation"]), "clinical_trials", source_url, text, observed_at))
        if email:
            evidence.append(_evidence(name, "email", email, "clinical_trials", source_url, text, observed_at))
        if phone:
            evidence.append(_evidence(
                name, "phone", phone, "clinical_trials", source_url, text, observed_at,
                metadata={"raw_value": str(item.get("phone") or phone)},
            ))
        candidates.append(
            ContactCandidate(
                company_name=company_name,
                display_name=name,
                normalized_name=normalize_person_name(name),
                title=title,
                department=title_family(title or ""),
                primary_email=email,
                email_status="VERIFIED_PUBLIC" if email else "ROLE_ONLY",
                primary_phone=phone,
                phone_status="VERIFIED_PUBLIC" if phone else "ROLE_ONLY",
                contact_confidence=0.95 if email or phone else 0.55,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                last_verified_at=observed_at,
                evidence=evidence,
            )
        )
    return _merge_candidates(candidates)
