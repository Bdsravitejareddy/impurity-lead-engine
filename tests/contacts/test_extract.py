import json
from datetime import datetime, timezone
from pathlib import Path

from impurity_leads.contacts.extract import extract_contacts_from_html, extract_trial_contacts

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_extracts_jsonld_person_and_exact_public_email():
    html = (FIXTURES / "contact_leadership.html").read_text()
    contacts = extract_contacts_from_html(
        "https://example.com/leadership", html, "Example Pharma", NOW
    )
    jane = next(c for c in contacts if c.normalized_name == "jane smith")
    assert jane.primary_email == "jane.smith@example.com"
    assert jane.email_status == "VERIFIED_PUBLIC"
    assert jane.primary_phone == "+16175550101"
    assert any(e.evidence_type == "email" and e.source_url.endswith("/leadership") for e in jane.evidence)


def test_rd_person_without_email_remains_role_only():
    html = (FIXTURES / "contact_rd_no_email.html").read_text()
    contacts = extract_contacts_from_html(
        "https://example.com/research", html, "Example Pharma", NOW
    )
    contact = contacts[0]
    assert contact.normalized_name == "arun rao"
    assert contact.title == "Associate Director, CMC"
    assert contact.primary_email is None
    assert contact.email_status == "ROLE_ONLY"


def test_extracts_public_trial_contact_fields():
    payload = json.loads((FIXTURES / "contact_trial.json").read_text())
    contacts = extract_trial_contacts(
        payload,
        company_name="Example Pharma",
        source_url="https://clinicaltrials.gov/study/NCT00000001",
        observed_at=NOW,
    )
    maya = next(c for c in contacts if c.normalized_name == "maya patel")
    assert maya.primary_email == "maya.patel@example.com"
    assert maya.email_status == "VERIFIED_PUBLIC"
    assert maya.primary_phone == "+12125550112"
    assert maya.contact_confidence == 0.95


def test_extracts_visible_public_email_without_mailto_link():
    html = (FIXTURES / "contact_visible_email.html").read_text()
    contacts = extract_contacts_from_html(
        "https://example.com/research/team", html, "Example Pharma", NOW
    )
    lina = next(c for c in contacts if c.normalized_name == "lina khan")
    assert lina.primary_email == "lina.khan@example.com"
    assert lina.email_status == "VERIFIED_PUBLIC"


def test_phone_evidence_retains_raw_observed_value_in_metadata():
    html = (FIXTURES / "contact_leadership.html").read_text()
    contacts = extract_contacts_from_html(
        "https://example.com/leadership", html, "Example Pharma", NOW
    )
    jane = next(c for c in contacts if c.normalized_name == "jane smith")
    phone_evidence = next(e for e in jane.evidence if e.evidence_type == "phone")
    assert phone_evidence.metadata_json["raw_value"] in {"+1 617 555 0101", "+16175550101"}
