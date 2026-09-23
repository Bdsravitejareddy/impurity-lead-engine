from impurity_leads.role_inference import infer_role_intelligence, role_level


def test_quality_title_gets_inferred_jtbd_without_observed_claims():
    result = infer_role_intelligence({"id": "c1", "title": "Associate Director, Quality Control", "department": "Physicochemical Testing"})
    assert result["family"] == "analytical_quality"
    assert result["level"] == "DIRECTOR"
    assert result["jtbd"]
    assert all(item["provenance"] == "INFERRED" for item in result["jtbd"])
    assert all(item["source_ids"] == [] for item in result["jtbd"])


def test_generic_title_without_role_signal_stays_unknown():
    result = infer_role_intelligence({"id": "c2", "title": "Professional", "department": None})
    assert result["family"] is None
    assert result["jtbd"] == []
    assert role_level("Professional") == "UNKNOWN"


def test_inference_is_idempotent_against_existing_statement():
    first = infer_role_intelligence({"id": "c3", "title": "Head of Analytical Development"})
    existing = {first["jtbd"][0]["statement"]}
    second = infer_role_intelligence({"id": "c3", "title": "Head of Analytical Development"}, existing)
    assert len(second["jtbd"]) == len(first["jtbd"]) - 1
