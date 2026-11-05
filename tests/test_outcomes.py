from impurity_leads.outcomes import pipeline_key, summarize_outcomes


def _opp(company, molecule, priority):
    return {"priority": priority, "companies": {"legal_name": company}, "molecules": {"canonical_name": molecule}}


def test_key_matches_the_dashboard():
    assert pipeline_key("  Takeda Pharmaceuticals ", "IXAZOMIB  CITRATE") == "takeda pharmaceuticals|ixazomib citrate"


def test_outcomes_report_response_rate_by_priority_from_the_furthest_stage():
    opportunities = [_opp("Takeda", "Ixazomib", "HOT"), _opp("Cipla", "Ledipasvir", "HOT"), _opp("Lupin", "Fosphenytoin", "REVIEW")]
    events = [
        {"pipeline_key": "takeda|ixazomib", "to_stage": "CONTACTED"},
        {"pipeline_key": "takeda|ixazomib", "to_stage": "REPLIED"},
        {"pipeline_key": "takeda|ixazomib", "to_stage": "WON"},
        {"pipeline_key": "cipla|ledipasvir", "to_stage": "CONTACTED"},
        {"pipeline_key": "cipla|ledipasvir", "to_stage": "LOST"},
        {"pipeline_key": "lupin|fosphenytoin", "to_stage": "REVIEWED"},
    ]
    report = summarize_outcomes(opportunities, events)
    assert report["tracked_leads"] == 3
    assert report["by_priority"]["HOT"] == {"tracked": 2, "contacted": 2, "responded": 1, "won": 1, "lost": 1, "response_rate": 0.5}
    assert report["by_priority"]["REVIEW"]["response_rate"] is None
