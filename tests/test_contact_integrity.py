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


def test_audit_compares_contacts_under_soft_merged_companies():
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("repair_contact_integrity", Path("scripts/repair_contact_integrity.py"))
    repair = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repair)

    tables = {
        "companies": [{"id": "novartis", "merged_into_company_id": "novartis-pharma"}, {"id": "novartis-pharma", "merged_into_company_id": None}],
        "contacts": [
            {"id": "a", "company_id": "novartis", "display_name": "Ryan Bittner", "title": "Associate Director, CMC Quality Assurance"},
            {"id": "b", "company_id": "novartis-pharma", "display_name": "Ryan Bittner", "title": "Associate Director, CMC Quality Assurance", "profile_url": "https://example.test/ryan"},
        ],
    }

    class Client:
        def table(self, name):
            return SimpleNamespace(select=lambda columns: SimpleNamespace(execute=lambda: SimpleNamespace(data=tables.get(name, []))))

    report = repair.audit(Client())
    assert [(item["duplicate_id"], item["survivor_id"], item["action"]) for item in report["auto_merge_candidates"]] == [("a", "b", "AUTO_MERGE")]
