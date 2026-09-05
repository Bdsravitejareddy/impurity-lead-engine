from datetime import datetime, timezone
from pathlib import Path

from impurity_leads.contacts.pipeline import enrich_opportunity_contacts
from impurity_leads.models import Opportunity

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parents[1] / "fixtures"


def _opportunity(priority: str = "HOT") -> Opportunity:
    return Opportunity(
        company_name="Example Pharma",
        molecule_name="Drug X",
        score=92,
        priority=priority,
        likely_need_type=["nitrosamine/NDSRI"],
        rationale="regulatory impurity work",
    )


def test_nitrosamine_pipeline_returns_exact_public_contact_before_pattern_contact():
    html = (FIXTURES / "contact_pattern_people.html").read_text()
    ranked = enrich_opportunity_contacts(
        _opportunity(),
        "example.com",
        [("https://example.com/team", html)],
        now=NOW,
    )
    assert ranked[0].contact.display_name == "Jane Smith"
    assert ranked[0].contact.email_status == "VERIFIED_PUBLIC"
    maya = next(item for item in ranked if item.contact.display_name == "Maya Patel")
    assert maya.contact.primary_email == "maya.patel@example.com"
    assert maya.contact.email_status == "PATTERN_CONFIRMED"
    assert all(item.contact.role_fit_score >= 55 for item in ranked)
    assert len(ranked) <= 3
    assert all(item.contact.evidence for item in ranked)


def test_review_opportunity_is_not_contact_enriched():
    html = (FIXTURES / "contact_pattern_people.html").read_text()
    assert enrich_opportunity_contacts(
        _opportunity("REVIEW"),
        "example.com",
        [("https://example.com/team", html)],
        now=NOW,
    ) == []


def test_role_only_contacts_surface_only_when_no_stronger_contact_exists():
    html = (FIXTURES / "contact_rd_no_email.html").read_text()
    ranked = enrich_opportunity_contacts(
        _opportunity(),
        "example.com",
        [("https://example.com/research", html)],
        now=NOW,
    )
    assert ranked
    assert ranked[0].contact.email_status == "ROLE_ONLY"
