from impurity_leads.normalize import normalize_company_name, normalize_molecule_name


def test_company_normalization_removes_common_legal_suffixes():
    assert normalize_company_name("Example Pharma, Inc.") == "example"


def test_company_normalization_strips_stacked_and_international_suffixes():
    groups = [
        ("Bayer", "Bayer AG", "BAYER A.G."),
        ("Takeda", "Takeda Pharmaceuticals U.S.A., Inc.", "Takeda Pharmaceuticals USA Inc"),
        ("Novo Nordisk A/S", "NOVO NORDISK INC", "Novo Nordisk"),
        ("Novartis", "Novartis Pharmaceuticals", "Novartis Pharma AG"),
        ("AstraZeneca", "AstraZeneca Pharmaceuticals LP", "AstraZeneca PLC"),
        ("Boehringer Ingelheim", "Boehringer Ingelheim Pharma GmbH & Co. KG"),
        ("Sanofi", "Sanofi S.A.", "SANOFI SA"),
        ("Astellas", "Astellas Pharma Inc.", "Astellas K.K."),
        ("Lonza", "Lonza Holdings", "Lonza N.V.", "Lonza B.V.", "Lonza SE"),
        ("Teva", "Teva Pharmaceuticals USA, Inc."),
    ]
    for group in groups:
        assert len({normalize_company_name(name) for name in group}) == 1, group
    assert normalize_company_name("Dr. Reddy's Laboratories Pvt. Ltd.") == "dr reddys laboratories"
    assert normalize_company_name("Hoffmann-La Roche") == "hoffmann la roche"
    # Merck KGaA (Darmstadt) and Merck & Co. (Rahway) are different companies.
    assert normalize_company_name("Merck KGaA") != normalize_company_name("Merck & Co., Inc.")


def test_company_normalization_never_strips_a_name_to_nothing():
    assert normalize_company_name("Pharma AG") == "pharma"
    assert normalize_company_name("Holdings") == "holdings"
    assert normalize_company_name("  ") == ""


def test_company_normalization_is_stable_on_legacy_keys():
    """Stored normalized_name values re-normalize to the same key as the raw name."""
    import re

    def legacy(name):
        value = re.sub(r"[,]+", "", re.sub(r"\s+", " ", name.strip().lower()))
        value = re.sub(r"\b(incorporated|inc|limited|ltd|llc|plc|corp|corporation|co)\.?$", "", value, flags=re.I).strip(" .")
        return re.sub(r"\s+", " ", value)

    for name in ["Takeda Pharmaceuticals U.S.A., Inc.", "Novo Nordisk A/S", "Bayer AG", "Merck & Co., Inc.", "Teva Pharmaceuticals USA, Inc."]:
        assert normalize_company_name(legacy(name)) == normalize_company_name(name)


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
