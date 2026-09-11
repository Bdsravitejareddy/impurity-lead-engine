from impurity_leads.contact_quality import QualityConfig, portfolio_quality, score_contact


def test_dimension_score_is_backend_authoritative_and_bounded():
    result = score_contact({"contact_confidence": 95, "title": "Director Analytical Development", "last_verified_at": "2026-09-01", "profile_url": "https://example.test/p"}, sources=[{"source_class": "PRIMARY"}, {"source_class": "STRONG_PROFESSIONAL"}], opportunities=[{"id": "o1"}])
    assert 0 <= result["score"] <= 100
    assert result["dimensions"]["technical_relevance"] >= 55


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
    rows = [{"contact_confidence": 90, "title": "Analytical Development Director", "last_verified_at": "2026-09-01", "profile_url": "https://example.test/p", "source_classes": ["PRIMARY", "STRONG_PROFESSIONAL", "DIRECTORY", "DISCOVERY"], "contactability": "PROFESSIONAL", "opportunity_count": 1} for _ in range(10)]
    result = portfolio_quality(rows, config=QualityConfig(daily_contact_target=10))
    assert result["gate_passed"] is True
    assert result["ai_mode"] == "VALIDATION_ONLY"


def test_duplicate_rate_can_fail_an_otherwise_strong_portfolio():
    rows = [{"contact_confidence": 90, "title": "Quality Director", "last_verified_at": "2026-09-01", "source_classes": ["PRIMARY", "STRONG_PROFESSIONAL", "DIRECTORY", "DISCOVERY"], "contactability": "PROFESSIONAL", "opportunity_count": 1} for _ in range(10)]
    result = portfolio_quality(rows, duplicate_count=4, config=QualityConfig(daily_contact_target=10))
    assert result["duplicate_rate"] == 0.4
    assert result["gate_passed"] is False
