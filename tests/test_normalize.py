from impurity_leads.normalize import normalize_company_name, normalize_molecule_name


def test_company_normalization_removes_common_legal_suffixes():
    assert normalize_company_name("Example Pharma, Inc.") == "example pharma"


def test_molecule_normalization_preserves_development_code():
    assert normalize_molecule_name("  ABC-123 ") == "abc-123"
