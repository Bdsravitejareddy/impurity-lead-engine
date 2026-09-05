from impurity_leads.contacts.models import ContactCandidate
from impurity_leads.contacts.rank import score_role_fit
from impurity_leads.models import Opportunity


def _opp(need: str) -> Opportunity:
    return Opportunity(
        company_name="Example Pharma",
        molecule_name="Drug X",
        score=90,
        priority="HOT",
        likely_need_type=[need],
        rationale="x",
    )


def test_nitrosamine_opportunity_prefers_analytical_director_over_ceo():
    opportunity = _opp("nitrosamine/NDSRI")
    analytical = ContactCandidate(
        company_name="Example Pharma",
        display_name="Jane Smith",
        title="Director, Analytical Development",
    )
    ceo = ContactCandidate(
        company_name="Example Pharma",
        display_name="Bob Chief",
        title="Chief Executive Officer",
    )
    analytical_score, _ = score_role_fit(opportunity, analytical)
    ceo_score, _ = score_role_fit(opportunity, ceo)
    assert analytical_score >= 55
    assert analytical_score > ceo_score


def test_direct_rfq_rewards_procurement_role():
    opportunity = _opp("direct RFQ")
    buyer = ContactCandidate(
        company_name="Example Pharma",
        display_name="Priya Rao",
        title="Director, Strategic Sourcing",
    )
    assert score_role_fit(opportunity, buyer)[0] >= 55


def test_generic_scientist_does_not_automatically_pass_primary_threshold():
    opportunity = _opp("nitrosamine/NDSRI")
    scientist = ContactCandidate(
        company_name="Example Pharma",
        display_name="Sam Lee",
        title="Scientist",
    )
    assert score_role_fit(opportunity, scientist)[0] < 55
