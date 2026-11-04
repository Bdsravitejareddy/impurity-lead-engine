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


def test_intervention_labels_become_molecule_names():
    from impurity_leads.normalize import clean_intervention_names

    assert clean_intervention_names("lopinavir/ritonavir (LPV/r) (tablet or capsule) with nucleoside reverse transcriptase inhibitors (NRTIs)") == ["lopinavir", "ritonavir"]
    assert clean_intervention_names("Abrocitinib 100 mg") == ["Abrocitinib"]
    assert clean_intervention_names("Selinexor (combination therapy)") == ["Selinexor"]
    assert clean_intervention_names("Lumateperone high dose") == ["Lumateperone"]
    assert clean_intervention_names("HRS9531 injection") == ["HRS9531"]
    assert clean_intervention_names("PIOGLITAZONE HYDROCHLORIDE / GLIMEPIRIDE") == ["PIOGLITAZONE HYDROCHLORIDE", "GLIMEPIRIDE"]
    assert clean_intervention_names("5-Fluorouracil") == ["5-Fluorouracil"]
    assert clean_intervention_names("Sequential Systemic Chemotherapy") == []
    assert clean_intervention_names("Matching placebo") == []
    assert clean_intervention_names("Molgramostim Open-label") == ["Molgramostim"]
