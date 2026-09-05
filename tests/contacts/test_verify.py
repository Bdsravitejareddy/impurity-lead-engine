from datetime import datetime, timedelta, timezone

from impurity_leads.contacts.models import ContactCandidate, ContactEvidence
from impurity_leads.contacts.verify import apply_contact_verification

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _evidence(kind: str, value: str, source_type: str = "company_site") -> ContactEvidence:
    return ContactEvidence(
        evidence_type=kind,
        observed_value=value,
        source_type=source_type,
        source_url="https://example.com/team",
        evidence_text="Jane Smith Director Analytical Development",
        observed_at=NOW,
        fingerprint=f"{kind}-{value}",
    )


def test_exact_company_domain_email_stays_verified_public():
    contact = ContactCandidate(
        company_name="Example Pharma",
        display_name="Jane Smith",
        normalized_name="jane smith",
        title="Director, Analytical Development",
        primary_email="jane.smith@example.com",
        email_status="VERIFIED_PUBLIC",
        last_seen_at=NOW,
        last_verified_at=NOW,
        evidence=[_evidence("identity", "Jane Smith"), _evidence("title", "Director, Analytical Development"), _evidence("email", "jane.smith@example.com")],
    )
    verified = apply_contact_verification(contact, "example.com", None, NOW)
    assert verified.email_status == "VERIFIED_PUBLIC"
    assert verified.contact_confidence == 1.0


def test_generated_pattern_email_is_never_verified_public():
    contact = ContactCandidate(
        company_name="Example Pharma",
        display_name="Jane Smith",
        normalized_name="jane smith",
        title="Director, Analytical Development",
        last_seen_at=NOW,
        last_verified_at=NOW,
        evidence=[_evidence("identity", "Jane Smith"), _evidence("title", "Director, Analytical Development")],
    )
    verified = apply_contact_verification(contact, "example.com", "first.last", NOW)
    assert verified.primary_email == "jane.smith@example.com"
    assert verified.email_status == "PATTERN_CONFIRMED"
    assert verified.contact_confidence == 0.70
    assert any(e.evidence_type == "email_pattern" for e in verified.evidence)


def test_old_unconfirmed_affiliation_becomes_stale():
    old = NOW - timedelta(days=181)
    contact = ContactCandidate(
        company_name="Example Pharma",
        display_name="Jane Smith",
        normalized_name="jane smith",
        title="Director, Analytical Development",
        last_seen_at=old,
        last_verified_at=old,
        evidence=[
            ContactEvidence(
                evidence_type="identity",
                observed_value="Jane Smith",
                source_type="company_site",
                source_url="https://example.com/team",
                evidence_text="Jane Smith",
                observed_at=old,
                fingerprint="old-id",
            )
        ],
    )
    stale = apply_contact_verification(contact, "example.com", None, NOW)
    assert stale.email_status == "STALE"
    assert stale.phone_status == "STALE"
