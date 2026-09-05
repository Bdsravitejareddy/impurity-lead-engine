from impurity_leads.classify import classify_signal, looks_like_impurity_vendor


def test_named_molecule_nitrosamine_is_high_intent():
    matches = classify_signal("NDSRI nitrosamine assessment for Drug X", has_molecule=True)
    assert ("nitrosamine_ndsri", 45, "nitrosamine/NDSRI") in matches


def test_vendor_language_is_excluded():
    text = "We manufacture and supply custom impurity reference standards worldwide."
    assert looks_like_impurity_vendor(text) is True
