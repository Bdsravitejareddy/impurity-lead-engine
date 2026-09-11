from impurity_leads.contact_quality import QualityConfig
from impurity_leads.research_discovery import SearchResult
from impurity_leads.targeted_research import TargetedSearchBudget, evaluate_opportunity_coverage, run_targeted_rounds, targeted_query_plan


class Provider:
    name = "fake"

    def __init__(self, results):
        self.results = results
        self.calls = []

    def discover(self, request):
        self.calls.append(request)
        return self.results


def test_missing_dimensions_are_opportunity_specific_and_bounded():
    opportunity = {"id": "o1", "company_name": "Cipla", "molecule_name": "Cobimetinib", "signal": "process impurity", "score": 90}
    coverage = evaluate_opportunity_coverage(opportunity, [])
    plans = targeted_query_plan(opportunity, coverage, max_queries=2)
    assert coverage.coverage_status == "NO_CONTACT"
    assert len(plans) == 2
    assert all(plan.seed_id == "o1" for plan in plans)


def test_targeted_round_stops_after_no_useful_evidence():
    opportunity = {"id": "o1", "company_name": "Cipla", "molecule_name": "Cobimetinib", "signal": "impurity", "score": 70}
    provider = Provider([SearchResult(url="https://example.test/weak", title="Weak result")])
    result = run_targeted_rounds(opportunity, [], provider, accept_result=lambda *_: None)
    assert result["stop_reason"] == "NO_NEW_EVIDENCE"
    assert len(provider.calls) == 1


def test_high_value_gets_more_rounds_without_lowering_thresholds():
    opportunity = {"id": "o1", "company_name": "Cipla", "molecule_name": "Cobimetinib", "signal": "impurity", "score": 94}
    provider = Provider([])
    result = run_targeted_rounds(opportunity, [], provider, accept_result=lambda *_: None, budget=TargetedSearchBudget(normal_rounds=1, high_value_rounds=5))
    assert result["stop_reason"] == "NO_NEW_EVIDENCE"
    assert len(provider.calls) == 1


def test_qualified_contact_stops_immediately():
    opportunity = {"id": "o1", "company_name": "Cipla", "molecule_name": "Cobimetinib", "score": 90}
    contact = {"contact_confidence": 95, "title": "Analytical Development Director", "last_verified_at": "2026-09-01", "profile_url": "https://example.test/p", "source_classes": ["PRIMARY", "STRONG_PROFESSIONAL", "DIRECTORY", "DISCOVERY"], "contactability": "PROFESSIONAL", "opportunity_fit": 90}
    result = run_targeted_rounds(opportunity, [contact], Provider([]), accept_result=lambda *_: None)
    assert result["stop_reason"] == "QUALIFIED"
    assert result["rounds"] == []
