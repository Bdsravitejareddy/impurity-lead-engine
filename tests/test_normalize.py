from impurity_leads.normalize import normalize_company_name, normalize_molecule_name


def test_company_normalization_removes_common_legal_suffixes():
    assert normalize_company_name("Example Pharma, Inc.") == "example pharma"


def test_molecule_normalization_preserves_development_code():
    assert normalize_molecule_name("  ABC-123 ") == "abc-123"


def test_inactive_trial_comparators_are_recognized():
    from impurity_leads.normalize import is_inactive_comparator

    for name in ["Placebo", "Matching placebo tablet", "Vehicle Cream", "Sham injection"]:
        assert is_inactive_comparator(name)
    for name in ["Ritonavir", "Estradiol Vaginal Cream", "Vehiclin-5"]:
        assert not is_inactive_comparator(name)
