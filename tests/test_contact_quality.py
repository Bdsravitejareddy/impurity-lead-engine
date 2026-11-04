from impurity_leads.contact_quality import QualityConfig, portfolio_quality, score_contact


def test_dimension_score_is_backend_authoritative_and_bounded():
    result = score_contact({"contact_confidence": 95, "title": "Director Analytical Development", "last_verified_at": "2026-09-01", "profile_url": "https://example.test/p"}, sources=[{"source_class": "PRIMARY"}, {"source_class": "STRONG_PROFESSIONAL"}], opportunities=[{"id": "o1"}])
    assert 0 <= result["score"] <= 100
    assert result["dimensions"]["technical_relevance"] >= 55


def test_decimal_contact_confidence_is_normalized_to_percent():
    result = score_contact({"contact_confidence": 0.94, "technical_relevance": 94})
    assert result["identity_confidence"] == 94.0


def test_explicit_zero_current_role_is_not_replaced_by_heuristic():
    result = score_contact({"contact_confidence": 0.8, "current_role_confidence": 0})
    assert result["dimensions"]["current_role"] == 0.0


def test_rejected_sources_do_not_raise_source_independence():
    result = score_contact({"contact_confidence": 0.8}, sources=[
        {"source_type": "PUBLICATION", "status": "USED"},
        {"source_type": "Official company", "status": "REJECTED"},
    ])
    assert result["dimensions"]["source_independence"] == 25.0


def test_person_direct_evidence_explains_technical_score_over_title_fallback():
    direct = score_contact({"technical_relevance": 85, "title": "Researcher", "contact_confidence": 60})
    fallback = score_contact({"title": "Analytical Development Director", "contact_confidence": 60})
    assert direct["dimensions"]["technical_relevance"] > fallback["dimensions"]["technical_relevance"]
    assert "person-direct technical evidence" in direct["diagnostics"]["technical_relevance"]


def test_gate_requires_quality_dimensions_not_only_contact_count():
    weak = [{"display_name": f"Person {i}"} for i in range(12)]
    result = portfolio_quality(weak, config=QualityConfig(daily_contact_target=10))
    assert result["gate_passed"] is False
    assert result["ai_mode"] == "TARGETED_SEARCH"


def test_gate_passes_only_when_coverage_and_median_pass():
    rows = [{"contact_confidence": 90, "current_role_confidence": 85, "recency_score": 85, "title": "Analytical Development Director", "profile_url": "https://example.test/p", "source_classes": ["PRIMARY", "STRONG_PROFESSIONAL", "DIRECTORY", "DISCOVERY"], "contactability": "PROFESSIONAL", "opportunity_count": 1} for _ in range(10)]
    result = portfolio_quality(rows, config=QualityConfig(daily_contact_target=10))
    assert result["gate_passed"] is True
    assert result["ai_mode"] == "VALIDATION_ONLY"


def test_duplicate_rate_can_fail_an_otherwise_strong_portfolio():
    rows = [{"contact_confidence": 90, "title": "Quality Director", "last_verified_at": "2026-09-01", "source_classes": ["PRIMARY", "STRONG_PROFESSIONAL", "DIRECTORY", "DISCOVERY"], "contactability": "PROFESSIONAL", "opportunity_count": 1} for _ in range(10)]
    result = portfolio_quality(rows, duplicate_count=4, config=QualityConfig(daily_contact_target=10))
    assert result["duplicate_rate"] == 0.4
    assert result["gate_passed"] is False


def test_role_confidence_comes_from_the_newest_dated_source_not_the_batch_stamp():
    from datetime import date

    contact = {"title": "Head of Quality", "last_verified_at": "2026-09-08", "contact_confidence": 0.8}
    recent = score_contact(contact, sources=[{"source_type": "OFFICIAL_COMPANY", "status": "USED", "source_date": "2026-05-01"}], today=date(2026, 11, 4))
    old = score_contact(contact, sources=[{"source_type": "PUBLICATION", "status": "USED", "source_date": "2021-03-01"}], today=date(2026, 11, 4))
    assert recent["dimensions"]["current_role"] == 85.0 and recent["basis"]["current_role"] == "SOURCE_DATED"
    assert old["dimensions"]["current_role"] == 25.0
    assert recent["dimensions"]["recency"] > old["dimensions"]["recency"]


def test_undated_role_is_marked_assumed_instead_of_a_confident_default():
    result = score_contact({"title": "Head of Quality", "last_verified_at": "2026-09-08", "contact_confidence": 0.8})
    assert result["basis"]["current_role"] == "ASSUMED"
    assert result["dimensions"]["current_role"] == 40.0
    assert result["basis"]["recency"] == "ASSUMED"
    assert "not established" in result["diagnostics"]["current_role"][0]


def test_backfilled_crawl_dates_do_not_count_as_role_evidence():
    from datetime import date

    result = score_contact({"title": "Head of Quality"}, sources=[{"source_type": "company_site", "status": "USED", "source_date": "2026-09-08", "source_kind": "LEGACY_CONTACT_EVIDENCE"}], today=date(2026, 11, 4))
    assert result["basis"]["current_role"] == "ASSUMED"


def test_rescore_reports_assumed_roles_and_skips_merged_contacts():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("rescore_contacts", Path("scripts/rescore_contacts.py"))
    rescore = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rescore)

    contacts = [
        {"id": "a", "display_name": "A", "title": "Head of Quality", "quality_diagnostics": {"score": 61, "dimensions": {"current_role": 82.0}}},
        {"id": "b", "display_name": "B", "title": "QC Lead", "merged_into_contact_id": "a"},
    ]
    sources = [{"contact_id": "a", "status": "USED", "source_type": "company_site", "source_date": "2026-09-08", "source_kind": "LEGACY_CONTACT_EVIDENCE"}]
    changes = rescore.rescore(contacts, sources, [{"contact_id": "a", "opportunity_id": "o1"}])
    assert [item["id"] for item in changes] == ["a"]
    assert changes[0]["before"]["current_role"] == 82.0
    assert changes[0]["after"]["basis"] == "ASSUMED"
    assert rescore.summarize(changes)["current_role_basis"] == {"ASSUMED": 1}


def test_dated_affiliation_department_dates_the_role_without_a_title():
    from datetime import date
    source = {"source_type": "Scientific publication", "status": "USED", "source_date": "2026-03-01", "source_kind": "MOLECULE_DISCOVERY"}
    result = score_contact({"department": "Analytical Chemistry in Development and Supply"}, sources=[source], today=date(2026, 11, 4))
    assert result["basis"]["current_role"] == "SOURCE_DATED"
    assert result["dimensions"]["current_role"] == 85.0
    assert score_contact({}, sources=[source], today=date(2026, 11, 4))["basis"]["current_role"] == "ASSUMED"
