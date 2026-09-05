import hashlib
from datetime import datetime, timedelta

from impurity_leads.contacts.models import ContactCandidate, ContactEvidence
from impurity_leads.contacts.normalize import email_domain, normalize_email
from impurity_leads.contacts.patterns import generate_pattern_email


def _pattern_evidence(contact: ContactCandidate, email: str, pattern: str, now: datetime) -> ContactEvidence:
    source_url = contact.evidence[0].source_url if contact.evidence else ""
    payload = f"{contact.normalized_name}|email_pattern|{email}|{source_url}"
    return ContactEvidence(
        evidence_type="email_pattern",
        observed_value=email,
        source_type="derived_pattern",
        source_url=source_url,
        evidence_text=f"Pattern-derived candidate using confirmed company pattern: {pattern}",
        observed_at=now,
        fingerprint=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        metadata_json={"pattern": pattern, "mailbox_verified": False},
    )


def _exact_email_confidence(contact: ContactCandidate, company_domain: str) -> float | None:
    if not contact.primary_email:
        return None
    normalized = normalize_email(contact.primary_email)
    if not normalized:
        return None
    email_evidence = [item for item in contact.evidence if item.evidence_type == "email" and normalize_email(item.observed_value) == normalized]
    if not email_evidence:
        return None
    domain = company_domain.casefold().removeprefix("www.")
    for item in email_evidence:
        if item.source_type == "company_site" and email_domain(normalized) == domain:
            return 1.0
        if item.source_type == "clinical_trials":
            return 0.95
        if item.source_type in {"scientific", "conference", "registry"}:
            return 0.90
    return None


def apply_contact_verification(
    contact: ContactCandidate,
    company_domain: str,
    confirmed_pattern: str | None,
    now: datetime,
    freshness_days: int = 180,
) -> ContactCandidate:
    result = contact.model_copy(deep=True)
    reference_time = result.last_verified_at or result.last_seen_at
    if reference_time and now - reference_time > timedelta(days=freshness_days):
        result.email_status = "STALE"
        result.phone_status = "STALE"
        result.contact_confidence = min(result.contact_confidence or 0.55, 0.40)
        return result

    exact_confidence = _exact_email_confidence(result, company_domain)
    if exact_confidence is not None:
        result.primary_email = normalize_email(result.primary_email or "")
        result.email_status = "VERIFIED_PUBLIC"
        result.contact_confidence = exact_confidence
        result.last_verified_at = now
    elif result.primary_email:
        result.primary_email = None
        result.email_status = "ROLE_ONLY"

    if result.primary_phone and any(item.evidence_type == "phone" for item in result.evidence):
        result.phone_status = "VERIFIED_PUBLIC"
        result.last_verified_at = now

    has_current_identity = any(item.evidence_type == "identity" for item in result.evidence)
    has_current_title = bool(result.title) and any(item.evidence_type == "title" for item in result.evidence)
    if not result.primary_email and confirmed_pattern and has_current_identity and has_current_title:
        generated = generate_pattern_email(result.display_name, company_domain, confirmed_pattern)
        if generated:
            result.primary_email = generated
            result.email_status = "PATTERN_CONFIRMED"
            result.contact_confidence = 0.70
            result.evidence.append(_pattern_evidence(result, generated, confirmed_pattern, now))
            result.last_verified_at = now

    if result.email_status == "ROLE_ONLY" and has_current_identity:
        result.contact_confidence = max(result.contact_confidence, 0.55)
        result.last_verified_at = result.last_verified_at or now
    return result
