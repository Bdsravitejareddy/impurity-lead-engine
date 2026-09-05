from impurity_leads.extract import extract_cas_numbers, extract_quantities, extract_evidence_windows


def test_extracts_valid_cas_number_and_quantity():
    text = "Required impurity CAS 12345-67-8, quantity 50 mg with NMR."
    assert extract_cas_numbers(text) == ["12345-67-8"]
    assert extract_quantities(text) == ["50 mg"]


def test_evidence_window_contains_keyword():
    text = "A" * 250 + " degradation impurity characterization for Drug X " + "B" * 250
    windows = extract_evidence_windows(text, ["degradation impurity"], window=60)
    assert len(windows) == 1
    assert "degradation impurity" in windows[0].lower()
