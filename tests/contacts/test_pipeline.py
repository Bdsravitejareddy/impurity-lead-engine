from datetime import datetime, timezone
from pathlib import Path

from impurity_leads.contacts.pipeline import enrich_opportunity_contacts
from impurity_leads.contacts.models import ContactCandidate, ContactEvidence
from impurity_leads.contacts.pipeline import enrich_contact_candidates
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


def test_review_opportunity_is_contact_enriched_when_score_is_qualified():
    html = (FIXTURES / "contact_pattern_people.html").read_text()
    ranked = enrich_opportunity_contacts(
        _opportunity("REVIEW"),
        "example.com",
        [("https://example.com/team", html)],
        now=NOW,
    )
    assert ranked


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


def test_historical_publication_author_is_not_treated_as_current_contact():
    author = ContactCandidate(
        company_name="Example Pharma",
        display_name="Historical Author",
        title="Director, Analytical Development",
        last_seen_at=NOW,
        last_verified_at=NOW,
        evidence=[
            ContactEvidence(
                evidence_type="identity", observed_value="Historical Author", source_type="scientific",
                source_url="https://doi.org/10.0000/example", evidence_text="2008 publication author",
                observed_at=NOW, fingerprint="historical-identity",
            ),
            ContactEvidence(
                evidence_type="title", observed_value="Director, Analytical Development", source_type="scientific",
                source_url="https://doi.org/10.0000/example", evidence_text="2008 affiliation",
                observed_at=NOW, fingerprint="historical-title",
            ),
        ],
    )
    assert enrich_contact_candidates(_opportunity(), "example.com", [author], now=NOW) == []


def test_current_company_profile_can_verify_a_role_seed():
    person = ContactCandidate(
        company_name="Example Pharma",
        display_name="Current Scientist",
        title="Director, Analytical Development",
        last_seen_at=NOW,
        last_verified_at=NOW,
        evidence=[
            ContactEvidence(
                evidence_type="identity", observed_value="Current Scientist", source_type="company_site",
                source_url="https://example.com/leadership", evidence_text="Current Scientist, Director Analytical Development",
                observed_at=NOW, fingerprint="current-identity",
            ),
            ContactEvidence(
                evidence_type="title", observed_value="Director, Analytical Development", source_type="company_site",
                source_url="https://example.com/leadership", evidence_text="Current Scientist, Director Analytical Development",
                observed_at=NOW, fingerprint="current-title",
            ),
        ],
    )
    ranked = enrich_contact_candidates(_opportunity(), "example.com", [person], now=NOW)
    assert ranked and ranked[0].contact.email_status == "ROLE_ONLY"
