from impurity_leads.contact_integrity import classify_contact_pair, choose_survivor


def test_degree_suffix_and_same_profile_are_safe_auto_merge():
    decision = classify_contact_pair(
        {"id": "a", "company_id": "teva", "display_name": "Benjamin Roembke", "profile_url": "https://linkedin.com/in/broembke", "title": "Associate Director, Quality"},
        {"id": "b", "company_id": "teva", "display_name": "Benjamin Roembke, Ph.D.", "profile_url": "https://linkedin.com/in/broembke/", "title": "Associate Director, Quality"},
    )
    assert decision.action == "AUTO_MERGE"
    assert decision.reason == "same_profile_url"


def test_name_only_common_match_requires_review():
    decision = classify_contact_pair(
        {"id": "a", "company_id": "x", "display_name": "Sachin R. Vishe", "title": "Quality"},
        {"id": "b", "company_id": "x", "display_name": "Sachin R. Vishe, Ph.D.", "title": "Unknown"},
    )
    assert decision.action == "REVIEW"


def test_survivor_prefers_richer_row():
    survivor = choose_survivor([
        {"id": "old", "title": "Quality"},
        {"id": "rich", "title": "Quality", "profile_url": "https://example.com/p", "primary_email": "a@example.com"},
    ])
    assert survivor["id"] == "rich"
