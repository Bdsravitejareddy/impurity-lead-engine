from datetime import datetime, timezone

from impurity_leads.contacts.models import ContactCandidate, ContactEvidence


def test_contact_evidence_caps_snippet_to_800_chars():
    now = datetime.now(timezone.utc)
    evidence = ContactEvidence(
        evidence_type="email",
        observed_value="jane@example.com",
        source_type="company_site",
        source_url="https://example.com/team",
        evidence_text="x" * 900,
        observed_at=now,
        fingerprint="abc",
    )
    assert len(evidence.evidence_text) == 800


def test_contact_candidate_defaults_to_role_only_without_exact_values():
    candidate = ContactCandidate(
        company_name="Example Pharma",
        display_name="Dr Jane Smith",
        title="Director, Analytical Development",
    )
    assert candidate.email_status == "ROLE_ONLY"
    assert candidate.phone_status == "ROLE_ONLY"
