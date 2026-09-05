from datetime import datetime, timezone

from impurity_leads.contacts.extract import extract_contacts_from_html, extract_trial_contacts
from impurity_leads.contacts.models import ContactCandidate, RankedContact
from impurity_leads.contacts.normalize import email_domain, normalize_person_name
from impurity_leads.contacts.patterns import detect_email_pattern
from impurity_leads.contacts.rank import score_role_fit
from impurity_leads.contacts.verify import apply_contact_verification
from impurity_leads.models import Opportunity

_STATUS_STRENGTH = {
    "VERIFIED_PUBLIC": 3,
    "PATTERN_CONFIRMED": 2,
    "ROLE_ONLY": 1,
    "STALE": 0,
}


def _merge_people(candidates: list[ContactCandidate]) -> list[ContactCandidate]:
    merged: dict[str, ContactCandidate] = {}
    for candidate in candidates:
        key = normalize_person_name(candidate.display_name)
        if not key:
            continue
        candidate.normalized_name = key
        current = merged.get(key)
        if current is None:
            merged[key] = candidate.model_copy(deep=True)
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
        times = [item for item in (current.first_seen_at, candidate.first_seen_at) if item]
        current.first_seen_at = min(times) if times else None
        times = [item for item in (current.last_seen_at, candidate.last_seen_at) if item]
        current.last_seen_at = max(times) if times else None
        times = [item for item in (current.last_verified_at, candidate.last_verified_at) if item]
        current.last_verified_at = max(times) if times else None
        current.contact_confidence = max(current.contact_confidence, candidate.contact_confidence)
        known = {evidence.fingerprint for evidence in current.evidence}
        for evidence in candidate.evidence:
            if evidence.fingerprint not in known:
                current.evidence.append(evidence)
                known.add(evidence.fingerprint)
    return list(merged.values())


def enrich_opportunity_contacts(
    opportunity: Opportunity,
    company_domain: str,
    page_documents: list[tuple[str, str]],
    trial_payloads: list[dict] | None = None,
    now: datetime | None = None,
) -> list[RankedContact]:
    if opportunity.priority not in {"HOT", "HIGH"}:
        return []
    now = now or datetime.now(timezone.utc)
    candidates: list[ContactCandidate] = []
    for url, html in page_documents:
        candidates.extend(extract_contacts_from_html(url, html, opportunity.company_name, now))
    for payload in trial_payloads or []:
        source_url = str(payload.get("_source_url") or "https://clinicaltrials.gov/")
        candidates.extend(extract_trial_contacts(payload, opportunity.company_name, source_url, now))

    people = _merge_people(candidates)
    normalized_domain = company_domain.casefold().removeprefix("www.")
    named_emails = [
        (person.display_name, person.primary_email)
        for person in people
        if person.primary_email
        and person.email_status == "VERIFIED_PUBLIC"
        and email_domain(person.primary_email) == normalized_domain
    ]
    confirmed_pattern = detect_email_pattern(named_emails, normalized_domain)

    verified: list[tuple[ContactCandidate, str]] = []
    for person in people:
        checked = apply_contact_verification(person, normalized_domain, confirmed_pattern, now)
        source_type = checked.evidence[0].source_type if checked.evidence else None
        fit, rationale = score_role_fit(opportunity, checked, source_type=source_type)
        checked.role_fit_score = fit
        if checked.email_status == "STALE" or fit < 55:
            continue
        verified.append((checked, rationale))

    if any(person.email_status in {"VERIFIED_PUBLIC", "PATTERN_CONFIRMED"} for person, _ in verified):
        verified = [(person, rationale) for person, rationale in verified if person.email_status != "ROLE_ONLY"]

    verified.sort(
        key=lambda item: (
            -_STATUS_STRENGTH[item[0].email_status],
            -item[0].role_fit_score,
            -item[0].contact_confidence,
            item[0].normalized_name,
        )
    )
    return [
        RankedContact(contact=person, rank=index, rationale=rationale)
        for index, (person, rationale) in enumerate(verified[:3], start=1)
    ]
